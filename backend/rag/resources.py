import json
import os
import urllib.request

import chromadb
from chromadb.utils.embedding_functions import OllamaEmbeddingFunction
from langchain_ollama import ChatOllama

from rag.config import (
    CHROMA_DB_DIR,
    DEFAULT_OLLAMA_BASE_URL,
    DEFAULT_OLLAMA_MODEL,
    OLLAMA_NUM_CTX,
    OLLAMA_TIMEOUT_SECONDS,
)


class _OllamaRetrievalEmbeddings(OllamaEmbeddingFunction):
    """Apply model-specific retrieval instructions when embedding queries."""

    def embed_query(self, input: list[str]):
        if self.model_name == "qwen3-embedding:0.6b":
            input = [
                "Instruct: Retrieve manufacturing documentation that answers the user's question.\n"
                f"Query: {query}"
                for query in input
            ]
        elif self.model_name == "embeddinggemma-2":
            input = [f"task: search result | query: {query}" for query in input]
        return self(input=input)


def _create_collection() -> chromadb.Collection:
    """Open (or create) the persistent Chroma collection holding document chunks."""
    ef = _OllamaRetrievalEmbeddings(
        url=_ollama_settings()[1],
        model_name=os.getenv("OLLAMA_EMBEDDING_MODEL") or "nomic-embed-text:v1.5",
    )
    client = chromadb.PersistentClient(path=CHROMA_DB_DIR)
    return client.get_or_create_collection(name="documents", embedding_function=ef)


def _ollama_settings() -> tuple[str, str]:
    return (os.getenv("OLLAMA_MODEL") or DEFAULT_OLLAMA_MODEL,
            (os.getenv("OLLAMA_BASE_URL") or DEFAULT_OLLAMA_BASE_URL).rstrip("/"))


def _create_ollama_llm(**extra) -> ChatOllama:
    model, base_url = _ollama_settings()
    return ChatOllama(
        model=model,
        base_url=base_url,
        temperature=0,
        num_ctx=OLLAMA_NUM_CTX,
        client_kwargs={"timeout": OLLAMA_TIMEOUT_SECONDS},
        **extra,
    )


def _create_llm() -> ChatOllama:
    """Create the main answer / condense model (local Ollama)."""
    return _create_ollama_llm()


def _create_guard_llm() -> ChatOllama:
    """Create the off-topic classifier model (same local model; only needs YES/NO)."""
    return _create_ollama_llm(num_predict=3)


def _ollama_status() -> str | None:
    """None if the Ollama server is reachable and has the configured model, else a short reason."""
    model, base_url = _ollama_settings()
    try:
        with urllib.request.urlopen(f"{base_url}/api/tags", timeout=2) as resp:
            names = {m.get("name", "") for m in json.load(resp).get("models", [])}
    except Exception:
        return f"Ollama is not reachable at {base_url}. Start Ollama and try again."
    if model not in names and f"{model}:latest" not in names:
        return f"Ollama model {model!r} is not installed. Run: ollama pull {model}"
    return None
