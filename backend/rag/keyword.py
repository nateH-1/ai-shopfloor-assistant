import re

from rank_bm25 import BM25Okapi

from rag.config import NUM_CHUNKS

# A token is letters/digits, optionally joined by - . or / so that codes like
# "8mm-1.25", "kg/cm2" or "4.2" stay in one piece.
_TOKEN_RE = re.compile(r"[a-z0-9]+(?:[-./][a-z0-9]+)*")

# Filler words that say nothing about the topic. A question word missing from the
# manuals only counts as evidence of "not covered" if it is NOT one of these.
_STOP_WORDS = frozenset("""
a an the and or but not no yes if then than so as at by for from in into of on onto to with without about
after before during over under up down out off again also too very really just only here there
i me my we us our you your he she it its they them their this that these those
is are was were be been being am do does did done doing have has had can could should would will shall may might must
what which who whom whose when where why how
tell explain describe show give list define mean means meaning need know want please help more
difference between example examples kind type types way ways thing things one ones other else all each every
some any many much same such like use used using get got make made go goes refer refers
""".split())


def _tokenize(text: str) -> list[str]:
    """Lowercase words, keeping part numbers and codes as single tokens."""
    return _TOKEN_RE.findall(text.lower())


def _build_keyword_index(collection) -> dict | None:
    """Read every chunk from the Chroma collection and build a BM25 index over them.

    Returns None when the collection is empty (BM25 cannot be built from zero chunks).
    """
    data = collection.get(include=["documents", "metadatas"])
    if not data["ids"]:
        return None

    tokenized = [_tokenize(text) for text in data["documents"]]
    return {
        "ids":       data["ids"],
        "texts":     data["documents"],
        "metadatas": data["metadatas"],
        "bm25":      BM25Okapi(tokenized),
        "vocab":     {token for tokens in tokenized for token in tokens},
    }


def _keyword_search(index: dict | None, query: str, k: int = NUM_CHUNKS, source: str = None) -> list[dict]:
    """Return up to k chunks ranked by BM25 score, best first.

    Only chunks sharing at least one word with the query are returned.
    source limits results to one file (the same "source" value Chroma stores).
    Each result: {"id", "text", "metadata", "score"}.
    """
    query_tokens = _tokenize(query)
    if index is None or not query_tokens:
        return []

    scores = index["bm25"].get_scores(query_tokens)
    ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)

    results = []
    for i in ranked:
        if scores[i] <= 0:
            break
        if source is not None and index["metadatas"][i].get("source") != source:
            continue
        results.append({
            "id":       index["ids"][i],
            "text":     index["texts"][i],
            "metadata": index["metadatas"][i],
            "score":    float(scores[i]),
        })
        if len(results) == k:
            break
    return results


def _unknown_terms(index: dict | None, query: str) -> list[str]:
    """Important words in the query (not filler, longer than 1 character) that appear
    in no chunk at all. A question built around such a word cannot be answered from
    the documents, e.g. "warranty" or "salary" in manuals that never mention them.
    """
    if index is None:
        return []
    return [w for w in dict.fromkeys(_tokenize(query))
            if len(w) > 1 and w not in _STOP_WORDS and w not in index["vocab"]]
