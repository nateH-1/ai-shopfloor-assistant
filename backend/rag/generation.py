import json
import logging

from rag.context import NO_INFO_REPLY, _parse_citations


logger = logging.getLogger(__name__)

_EVIDENCE = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "chunk": {"type": "integer", "minimum": 1},
            "quote": {"type": "string", "minLength": 1, "maxLength": 120, "pattern": "^[^\r\n]+$"},
        },
        "required": ["chunk", "quote"],
    },
}
_ANSWER_FORMAT = {
    "type": "object",
    "properties": {"answer": {"type": "string"}, "evidence": _EVIDENCE},
    "required": ["answer", "evidence"],
}
_CITATION_FORMAT = {"type": "object", "properties": {"evidence": _EVIDENCE}, "required": ["evidence"]}

_OUTPUT_INSTRUCTIONS = (
    "Return JSON. Put only the user-facing Markdown reply in answer. In evidence, give the "
    "CHUNK number and one short verbatim phrase per supporting passage. Copy a few consecutive "
    "words from the original text that directly support a fact in the answer. For a table, copy "
    "words from a single cell. Omit headings and passages that only repeat facts already cited. "
    "If the context does not answer the question, use the document limitation reply and empty evidence."
)


def _match_evidence(evidence, chunks: list) -> tuple[list, bool]:
    """Resolve each quote to its numbered passage, allowing for whitespace in extracted text."""
    if not isinstance(evidence, list) or not evidence:
        return [], False
    passages = [" ".join(doc.page_content.split()) for doc in chunks]
    used = {}
    complete = True
    for item in evidence:
        quote = item.get("quote") if isinstance(item, dict) else None
        if not isinstance(quote, str) or not quote.strip():
            complete = False
            continue
        quote = " ".join(quote.split())
        number = item.get("chunk")
        # The model can copy the right passage and miscount its CHUNK label.
        matches = [i for i, passage in enumerate(passages) if quote in passage]
        if type(number) is int and number - 1 in matches:
            index = number - 1
        elif len(matches) == 1:
            index = matches[0]
        else:
            complete = False
            continue
        used.setdefault(index, set()).add(quote)

    # Overlapping chunks can repeat several table rows. A second card for the
    # same file is redundant when another cited passage already has every quote.
    for index in reversed(list(used)):
        source = chunks[index].metadata.get("source")
        alternatives = [passages[i] for i in used if i != index and chunks[i].metadata.get("source") == source]
        if source and any(all(q in passage for q in used[index]) for passage in alternatives):
            del used[index]
    return [chunks[i] for i in used], complete


def _generate_answer(llm, prompt: str, chunks: list) -> tuple[str, list]:
    """Generate the reply and validate its citations against the exact context sent to Ollama."""
    raw = llm.invoke(_OUTPUT_INSTRUCTIONS + "\n\n" + prompt, format=_ANSWER_FORMAT).content.strip()
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        # Keep a plain-text answer if a model ignores the schema. Its footer alone
        # cannot establish which passages support it. Never display truncated JSON.
        result = {} if raw.startswith(("{", "```json")) else {"answer": raw}
    if not isinstance(result, dict) or not isinstance(result.get("answer"), str):
        return NO_INFO_REPLY, []

    answer, _ = _parse_citations(result["answer"], [])
    if answer == NO_INFO_REPLY:
        return answer, []
    evidence = result.get("evidence")
    sources, complete = _match_evidence(evidence, chunks)
    if complete:
        return answer, sources

    # Repair only the citations. Keep the answer the user will actually see fixed.
    repair = (
        f"{prompt}\n\nThe answer has already been written:\n{json.dumps(answer, ensure_ascii=False)}\n"
        "Find the fewest passages that directly support its factual claims. For each, return "
        "the CHUNK number and a few consecutive words copied from a supporting sentence or "
        "single table cell. Exclude headings, related topics and redundant passages."
    )
    try:
        raw = llm.invoke(repair, format=_CITATION_FORMAT).content
    except Exception:
        logger.warning("Citation repair failed. Returning the answer with its verified sources.", exc_info=True)
        return answer, sources
    try:
        repaired = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return answer, sources
    if isinstance(repaired, dict) and isinstance(repaired.get("evidence"), list):
        verified, complete = _match_evidence(repaired["evidence"], chunks)
        if complete:
            return answer, verified
        if isinstance(evidence, list):
            verified, _ = _match_evidence(evidence + repaired["evidence"], chunks)
        return answer, verified
    return answer, sources
