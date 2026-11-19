import re


NO_INFO_REPLY = "The uploaded documents do not contain information about this."

_CITATION_FOOTER = re.compile(r"SOURCES_USED\s*:\s*(.*)", re.I)
_CITATION_INSTRUCTION = re.compile(
    r"(?:After your answer(?:,? on a separate line)?|After the next line),? "
    r"write exactly:\s*(?:SOURCES_USED\s*:.*)?"
    r"|If you used none of the chunks, write:\s*SOURCES_USED:\s*none\.?",
    re.I,
)
_CHUNK_NUMBER = re.compile(r"\[?(?:CHUNK\s+)?([0-9]+)\]?", re.I)


def _build_numbered_context(chunks: list) -> str:
    """Format chunks as numbered sections so the LLM can cite which ones it used."""
    return "\n\n".join(f"[CHUNK {i}]\n{c.page_content}" for i, c in enumerate(chunks, 1))


def _dedup_chunks(chunks: list) -> list:
    """Keep each distinct cited passage in the order it was cited."""
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


def _read_citation_footer(raw_answer: str, chunks: list) -> tuple[str, list, bool]:
    """Read only the final standalone footer. Report malformed IDs for rewrite retries."""
    lines = raw_answer.rstrip().splitlines()
    body = []
    footer = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        marker = _CITATION_FOOTER.fullmatch(stripped)
        if marker:
            if i == len(lines) - 1:
                footer = marker.group(1).removesuffix(".").strip()
        elif not _CITATION_INSTRUCTION.fullmatch(stripped):
            body.append(line)

    answer = "\n".join(body).strip()
    if not answer or answer == NO_INFO_REPLY or footer is None or footer.casefold() == "none":
        return answer, [], False

    numbered = {str(i): chunk for i, chunk in enumerate(chunks, 1)}
    cited = {}
    invalid = False
    for part in footer.split(","):
        match = _CHUNK_NUMBER.fullmatch(part.strip())
        number = match.group(1).lstrip("0") if match else ""
        if number in numbered:
            cited[number] = numbered[number]
        else:
            invalid = True
    return answer, list(cited.values()), invalid


def _parse_citations(raw_answer: str, chunks: list) -> tuple[str, list]:
    """Extract the visible answer and the chunks explicitly cited in its footer."""
    answer, cited, _ = _read_citation_footer(raw_answer, chunks)
    return answer or NO_INFO_REPLY, cited
