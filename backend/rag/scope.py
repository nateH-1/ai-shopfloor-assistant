import os
from pathlib import Path

from rag.config import BROAD_INTENT_PHRASES
from rag.retrieval import _similarity_search_with_score

_SCOPE_CANDIDATE_K      = 12
_SCORE_COMPETITION_GAP  = 0.15  # L2 distance margin — sources within this gap of the
                                # top chunk are considered genuinely competitive
_MIN_RELEVANCE_SCORE    = 0.20  # Skip clarification entirely if the best chunk is
                                # worse than this — no doc truly contains the answer
_DOMINANCE_RATIO        = 0.10  # If (runner-up - top) / top >= this ratio the top doc
                                # is dominant enough to skip clarification

# Words that occur in many filenames and carry no distinguishing meaning.
# Used by _extract_distinctive_keywords to avoid matching on 'manual', 'procedure', etc.
_FILENAME_STOP_WORDS = {
    "sop", "manual", "operation", "operations", "operator", "procedure",
    "schedule", "log", "inspection", "report", "document", "documents",
    "guide", "guidelines", "instruction", "instructions", "basic", "ref",
    "reference", "overview", "pdf", "doc", "txt", "md", "csv", "tsv",
    "html", "htm", "json", "docx",
}


def _extract_distinctive_keywords(filename: str) -> set:
    """Pull meaningful words from a filename, dropping generic filler.

    Example: 'Forklift_Operation_Manual.pdf' → {'forklift'}
    """
    stem  = Path(filename).stem.lower()
    words = set(stem.replace("-", " ").replace("_", " ").split())
    # drop pure numbers (e.g. '001', '002', '2025')
    words = {w for w in words if not w.isdigit()}
    return words - _FILENAME_STOP_WORDS


def _display_name(filename: str) -> str:
    """'SOP-001-Assembly-Line-Startup.txt' → 'SOP-001 Assembly Line Startup'"""
    return Path(filename).stem.replace("-", " ").replace("_", " ")


def _build_clarification_options(sources: list) -> list:
    options = [{"label": _display_name(s), "value": s} for s in sources]
    options.append({"label": "All relevant documents", "value": "__all__"})
    return options


def _build_clarification_question(sources: list) -> str:
    names = [f'"{_display_name(s)}"' for s in sources[:3]]
    more  = f" (and {len(sources) - 3} more)" if len(sources) > 3 else ""
    if len(names) == 1:
        doc_list = names[0]
    elif len(names) == 2:
        doc_list = f"{names[0]} and {names[1]}"
    else:
        doc_list = f"{names[0]}, {names[1]}, and {names[2]}"
    return (
        f"I found relevant content in multiple documents: {doc_list}{more}. "
        f"Which one are you asking about, or would you like me to check all relevant documents?"
    )


def _detect_scope(message: str, session: dict, collection) -> tuple:
    """
    Determine retrieval scope. Returns (scope, data):
      ("pass",            None)             — proceed with full chain as-is
      ("broad",           None)             — explicit multi-doc synthesis
      ("ambiguous",       [filenames])      — multiple docs match, needs clarification
      ("resolved_single", (file, orig_q))  — clarification resolved to one doc
      ("resolved_all",    orig_q)          — clarification resolved to all docs

    session is the caller's session dict; a resolved or abandoned clarification
    is cleared on it in place. collection is the Chroma collection to search.
    """
    msg_lower = message.lower().strip()
    pending   = session.get("pending_clarification")

    # 1 — Resolve a pending clarification
    if pending:
        choice = message.strip().lower()
        for opt in pending["options"]:
            label = str(opt.get("label", "")).strip().lower()
            value = str(opt.get("value", "")).strip().lower()
            display_value = _display_name(str(opt.get("value", ""))).lower()
            if choice in {label, value, display_value}:
                session["pending_clarification"] = None
                orig = pending["original_question"]
                if opt["value"] == "__all__":
                    return ("resolved_all", orig)
                return ("resolved_single", (opt["value"], orig))
        # User asked something new — clear pending and fall through
        session["pending_clarification"] = None

    # 2 — Explicit broad intent
    if any(phrase in msg_lower for phrase in BROAD_INTENT_PHRASES):
        return ("broad", None)

    # 3 — Candidate retrieval + score-based competition check
    candidates = _similarity_search_with_score(collection, message, k=_SCOPE_CANDIDATE_K)
    if not candidates:
        return ("pass", None)

    # Track best (lowest L2) score and chunk list per source
    best_score:  dict = {}
    by_source:   dict = {}
    for doc, score in candidates:
        src = os.path.basename(doc.metadata.get("source", "unknown"))
        by_source.setdefault(src, []).append(doc)
        if src not in best_score or score < best_score[src]:
            best_score[src] = score

    if len(by_source) <= 1:
        return ("pass", None)

    top_score = min(best_score.values())

    # If user explicitly named a document (full stem), skip clarification
    for src in by_source:
        stem = Path(src).stem.lower()
        if stem in msg_lower or stem.replace("-", " ") in msg_lower or stem.replace("_", " ") in msg_lower:
            return ("pass", None)

    # Partial keyword match — if a distinctive word from exactly one filename
    # appears in the query AND that document is the best (or near-best) scorer
    # AND that keyword doesn't appear in the retrieved chunks of other sources
    # (which would mean it's a generic cross-cutting term, not a distinctive
    # entity name like "forklift" or "HPM100").
    msg_words = set(msg_lower.split())
    keyword_matches: dict = {}          # src → set of matched keywords
    for src in by_source:
        keywords = _extract_distinctive_keywords(src)
        # Match if a keyword is an exact word OR a prefix of a word in the query
        # (e.g. keyword "forklift" matches query word "forklifts")
        overlap = {
            kw for kw in keywords
            if any(w == kw or w.startswith(kw) or kw.startswith(w)
                   for w in msg_words)
        }
        if overlap:
            keyword_matches[src] = overlap
    if len(keyword_matches) == 1:
        matched_src   = next(iter(keyword_matches))
        matched_score = best_score[matched_src]
        matched_kw    = keyword_matches[matched_src]
        # Verify the keyword is truly distinctive: if it appears far more in the
        # matched doc's chunks than in all other docs' chunks combined, it's a
        # specific entity (like "forklift") — not a generic cross-cutting term.
        matched_text = " ".join(doc.page_content.lower() for doc in by_source[matched_src])
        other_text   = " ".join(
            doc.page_content.lower()
            for src2, docs in by_source.items() if src2 != matched_src
            for doc in docs
        )
        for kw in matched_kw:
            matched_count = matched_text.count(kw)
            other_count   = other_text.count(kw)
            # Distinctive if matched doc has the keyword and others have ≤25% as many occurrences
            if matched_count > 0 and other_count <= matched_count * 0.25:
                if matched_score <= top_score + 0.05:
                    return ("pass", None)
                break

    # If even the best match is a poor semantic fit, skip clarification — no doc
    # truly contains the answer so disambiguation wouldn't help.
    if top_score >= _MIN_RELEVANCE_SCORE:
        return ("pass", None)
    # Dominance check — if the top doc's score is substantially better than the
    # runner-up (by ratio), one doc clearly owns this query.
    sorted_scores = sorted(best_score.values())
    if len(sorted_scores) >= 2 and top_score > 0:
        runner_up = sorted_scores[1]
        if (runner_up - top_score) / top_score >= _DOMINANCE_RATIO:
            return ("pass", None)
    competitive  = [s for s, sc in best_score.items() if sc <= top_score + _SCORE_COMPETITION_GAP]

    if len(competitive) >= 2:
        ranked = sorted(competitive, key=lambda s: best_score[s])
        return ("ambiguous", ranked)

    return ("pass", None)
