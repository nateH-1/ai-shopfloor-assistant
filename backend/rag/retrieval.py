from langchain_core.documents import Document

from rag.config import NUM_CHUNKS

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