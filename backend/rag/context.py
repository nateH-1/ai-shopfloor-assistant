import re

from rag.keyword import _STOP_WORDS, _tokenize


NO_INFO_REPLY = "The uploaded documents do not contain information about this."

_SOURCE_LINE = re.compile(r"SOURCES_USED\s*:\s*(.*)", re.IGNORECASE)
_INLINE_SOURCE = re.compile(r"\[Source:\s*([^\]]+)\]", re.IGNORECASE)
_NEGATIONS = {"no", "not", "never", "without", "avoid", "avoids", "avoiding", "prohibited", "forbidden"}
_PROMPT_ECHO = re.compile(
    r"(?:After your answer(?:,? on a separate line)?|After the next line),? write exactly:"
    r"\s*(?:SOURCES_USED\s*:.*)?|If you used none of the chunks, write:\s*SOURCES_USED:\s*none\.?",
    re.IGNORECASE,
)


def _build_numbered_context(chunks: list) -> str:
    """Format chunks as numbered sections so the LLM can cite which ones it used."""
    return "\n\n".join(f"[CHUNK {i}]\n{c.page_content}" for i, c in enumerate(chunks, 1))


def _dedup_chunks(chunks: list) -> list:
    """Keep each distinct cited passage in citation order."""
    seen = set()
    result = []
    for doc in chunks:
        key = (
            doc.metadata.get("source", ""),
            doc.metadata.get("page", 0),
            doc.page_content,
        )
        if key not in seen:
            seen.add(key)
            result.append(doc)
    return result


def _citation_features(text: str) -> tuple[set, set]:
    text = re.sub(r"n['’]t\b|\bcannot\b", " not", text, flags=re.I)
    words = [w for w in _tokenize(text) if w not in _STOP_WORDS or w in _NEGATIONS]
    return set(words), set(zip(words, words[1:]))


def _claim_matches(terms, pairs, filenames, passages) -> tuple[list[int], bool]:
    """A strong match requires an ordered word pair and at least half of the claim's terms."""
    values = {word for word in terms if any(c.isdigit() for c in word)}
    negative = bool(terms & _NEGATIONS)
    scores = {}
    for index, (filename, spans) in enumerate(passages):
        if filenames and filename not in filenames:
            continue
        for doc_terms, doc_pairs in spans:
            if not values.issubset(doc_terms) or negative != bool(doc_terms & _NEGATIONS):
                continue
            common_terms = len(terms & doc_terms)
            if common_terms:
                common_pairs = len(pairs & doc_pairs)
                strong = common_pairs > 0 and 2 * common_terms >= len(terms)
                score = (strong, common_terms + common_pairs)
                scores[index] = max(scores.get(index, (False, 0)), score)
    best = max(scores.values(), default=(False, 0))
    return [i for i, score in scores.items() if score == best], best[0]


def _match_answer_sources(answer: str, chunks: list, cited: list[int]) -> list[int]:
    """Correct a valid footer when the answer's claims match other retrieved passages."""
    if not cited or len(chunks) < 2:
        return cited

    # Score a claim against individual sentences/paragraphs. Two facts on
    # opposite ends of a chunk may refer to different products or settings.
    passages = []
    for chunk in chunks:
        filename = str(chunk.metadata.get("source", "")).replace("\\", "/").rsplit("/", 1)[-1]
        spans = re.split(r"(?<=[.!?;])\s+|\n\s*\n", chunk.page_content)
        passages.append((filename, [_citation_features(span) for span in spans]))
    supported = {}
    uncertain = []
    unmatched = False
    for statement in re.split(r"\n|(?<=[.!?;])\s+(?!\s*\[Source:)", answer, flags=re.I):
        # Introductory headings and inline filenames are not factual evidence.
        if statement.rstrip("* ").endswith(":") or statement.lstrip().startswith("#"):
            continue
        source_labels = [name.strip() for name in _INLINE_SOURCE.findall(statement)]
        terms, pairs = _citation_features(_INLINE_SOURCE.sub("", statement))
        if not pairs:
            continue
        winners, strong = _claim_matches(terms, pairs, source_labels, passages)
        if strong and len(winners) == 1:
            supported[winners[0]] = None
        else:
            uncertain.append(winners)
            unmatched |= not strong
    if not supported and not uncertain:
        return cited
    if unmatched and supported.keys() <= set(cited):
        # A fully paraphrased claim may still be backed by another cited passage.
        return cited
    # An overlapping chunk adds no evidence for a claim already accounted for.
    for winners in uncertain:
        if not any(i in supported for i in winners):
            supported.update(dict.fromkeys(i for i in cited if i in winners))
    return cited if supported.keys() == set(cited) else list(supported)


def _read_cited_answer(raw_answer: str, chunks: list) -> tuple[str, list, bool]:
    """Read the final footer and flag invalid IDs for the feedback rewrite check."""
    lines = raw_answer.rstrip().splitlines()
    footer = _SOURCE_LINE.fullmatch(lines[-1].strip()) if lines else None
    body = [line for line in lines
            if not _SOURCE_LINE.fullmatch(line.strip()) and not _PROMPT_ECHO.fullmatch(line.strip())]
    answer = "\n".join(body).strip()
    if not answer or answer == NO_INFO_REPLY or not footer:
        return answer, [], False

    value = footer.group(1).removesuffix(".").strip()
    if value.casefold() == "none":
        return answer, [], False

    numbered = {str(i + 1): i for i in range(len(chunks))}
    cited = []
    invalid = False
    for part in value.split(","):
        token = part.strip()
        if token.startswith("[") and token.endswith("]"):
            token = token[1:-1].strip()
        match = re.fullmatch(r"(?:CHUNK\s+)?([0-9]+)", token, re.IGNORECASE)
        number = match.group(1).lstrip("0") if match else ""
        if number in numbered:
            cited.append(numbered[number])
        else:
            invalid = True
    indices = _match_answer_sources(answer, chunks, cited)
    return answer, [chunks[i] for i in indices], invalid


def _parse_citations(raw_answer: str, chunks: list) -> tuple[str, list]:
    """Return the visible reply and resolve its citations against the retrieved passages."""
    answer, cited, _ = _read_cited_answer(raw_answer, chunks)
    return answer or NO_INFO_REPLY, cited
