import os
import re


def _build_numbered_context(chunks: list) -> str:
    """Format chunks as numbered sections so the LLM can cite which ones it used."""
    return "\n\n".join(f"[CHUNK {i}]\n{c.page_content}" for i, c in enumerate(chunks, 1))


def _dedup_chunks(chunks: list) -> list:
    """Remove duplicate chunks by (source_file, page), preserving order."""
    seen = set()
    result = []
    for doc in chunks:
        key = (
            os.path.basename(doc.metadata.get("source", "")),
            doc.metadata.get("page", 0),
        )
        if key not in seen:
            seen.add(key)
            result.append(doc)
    return result


def _parse_citations(raw_answer: str, chunks: list) -> tuple:
    """Parse SOURCES_USED line from answer. Returns (clean_answer, cited_chunks).
    Falls back to all chunks if the LLM omits the citation line.
    """
    match = re.search(r'\s*SOURCES_USED:\s*(.+?)\s*$', raw_answer, re.IGNORECASE | re.MULTILINE)
    if not match:
        return raw_answer.strip(), chunks

    clean_answer = raw_answer[:match.start()].strip()
    cited_str    = match.group(1).strip()

    if cited_str.lower() == "none" or not cited_str:
        return clean_answer, []

    cited_chunks = []
    for part in cited_str.split(","):
        m = re.search(r'\d+', part.strip())
        if m:
            idx = int(m.group()) - 1  # 1-based → 0-based
            if 0 <= idx < len(chunks):
                cited_chunks.append(chunks[idx])

    # Fallback: if parsing yielded nothing, return all chunks
    return clean_answer, cited_chunks if cited_chunks else chunks
