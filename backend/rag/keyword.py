import re

from rank_bm25 import BM25Okapi

from rag.config import NUM_CHUNKS

# A token is letters/digits, optionally joined by - . or / so that codes like
# "8mm-1.25", "kg/cm2" or "4.2" stay in one piece.
_TOKEN_RE = re.compile(r"[a-z0-9]+(?:[-./][a-z0-9]+)*")


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
