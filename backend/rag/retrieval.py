import re

from langchain_core.documents import Document

from rag.config import KEYWORD_FALLBACK_DISTANCE, NUM_CHUNKS, RRF_K
from rag.keyword import _keyword_search, _unknown_terms

def _similarity_search(collection, query: str, k: int = NUM_CHUNKS, where: dict = None) -> list[Document]:
    """Query ChromaDB and return LangChain Document objects."""
    n = min(k, collection.count())
    if n == 0:
        return []
    kwargs: dict = {"query_texts": [query], "n_results": n, "include": ["documents", "metadatas"]}
    if where:
        kwargs["where"] = where
    results = collection.query(**kwargs)
    return [Document(page_content=t, metadata=m)
            for t, m in zip(results["documents"][0], results["metadatas"][0])]


def _similarity_search_with_score(collection, query: str, k: int = NUM_CHUNKS) -> list[tuple[Document, float]]:
    """Query ChromaDB and return (Document, distance) tuples."""
    n = min(k, collection.count())
    if n == 0:
        return []
    results = collection.query(query_texts=[query], n_results=n,
                               include=["documents", "metadatas", "distances"])
    return [(Document(page_content=t, metadata=m), d)
            for t, m, d in zip(results["documents"][0], results["metadatas"][0], results["distances"][0])]


def _is_code_like_query(query: str) -> bool:
    """True if the query contains a code like 8mm-1.25, CO2 or kg/cm2 (from the welding project)."""
    if re.search(r"[A-Za-z0-9]+[-./][A-Za-z0-9]+", query):
        return True
    if re.search(r"\b(?:[A-Za-z]+\d+|\d+[A-Za-z]+)\b", query):
        return True
    upper_codes = [t for t in re.findall(r"\b[A-Za-z0-9]+\b", query) if len(t) <= 6 and t.isupper()]
    return len(upper_codes) >= 2


def _reciprocal_rank_fusion(ranked_lists: list[list[str]], rrf_k: int = RRF_K) -> list[str]:
    """Merge ranked ID lists by position only; vector and BM25 scores are on unrelated scales."""
    scores: dict = {}
    for ranked in ranked_lists:
        for rank, chunk_id in enumerate(ranked, 1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (rrf_k + rank)
    return sorted(scores, key=lambda chunk_id: scores[chunk_id], reverse=True)


def _hybrid_search(collection, query: str, get_keyword_index, k: int = NUM_CHUNKS,
                   where: dict = None) -> tuple[list[Document], bool]:
    """Vector search plus BM25 fallback; returns (chunks, enough_evidence)."""
    n = min(k, collection.count())
    if n == 0:
        return [], False
    kwargs: dict = {"query_texts": [query], "n_results": n, "include": ["documents", "metadatas", "distances"]}
    if where:
        kwargs["where"] = where
    results = collection.query(**kwargs)
    ids       = results["ids"][0]
    docs      = {i: Document(page_content=t, metadata=m)
                 for i, t, m in zip(ids, results["documents"][0], results["metadatas"][0])}
    distances = results["distances"][0]

    weak = not distances or distances[0] >= KEYWORD_FALLBACK_DISTANCE
    if not (weak or _is_code_like_query(query)):
        return [docs[i] for i in ids], True

    index = get_keyword_index()
    if weak and _unknown_terms(index, query):
        return [], False

    source = where.get("source") if where else None
    keyword_hits = _keyword_search(index, query, k=k, source=source)
    if not keyword_hits:
        return [docs[i] for i in ids], True

    for hit in keyword_hits:
        docs.setdefault(hit["id"], Document(page_content=hit["text"], metadata=hit["metadata"]))
    merged = _reciprocal_rank_fusion([ids, [hit["id"] for hit in keyword_hits]])
    return [docs[i] for i in merged[:k]], True
