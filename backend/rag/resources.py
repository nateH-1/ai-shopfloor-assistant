import json
import os
import urllib.request

import chromadb
from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction
from langchain_openai import ChatOpenAI

from rag.config import (
    CHROMA_DB_DIR,
    DEFAULT_LLM_PROVIDER,
    DEFAULT_OLLAMA_BASE_URL,
    DEFAULT_OLLAMA_MODEL,
    MODEL_NAME,
    OLLAMA_NUM_CTX,
    OLLAMA_TIMEOUT_SECONDS,
)

_PROVIDERS = ("openai", "ollama")


def _create_collection(api_key: str) -> chromadb.Collection:
    """Open (or create) the persistent Chroma collection holding document chunks."""
    ef     = OpenAIEmbeddingFunction(api_key=api_key, model_name="text-embedding-ada-002")
    client = chromadb.PersistentClient(path=CHROMA_DB_DIR)
    return client.get_or_create_collection(name="documents", embedding_function=ef)


def _llm_provider(role: str = "main") -> str:
    """Provider for a role ("main" = answers + rewriting, "guard" = off-topic check), from .env."""
    main = (os.getenv("LLM_PROVIDER") or DEFAULT_LLM_PROVIDER).strip().lower()
    provider = (os.getenv("GUARD_LLM_PROVIDER") or main).strip().lower() if role == "guard" else main
    if provider not in _PROVIDERS:
        raise ValueError(f"Unknown LLM provider {provider!r}; use one of {', '.join(_PROVIDERS)}.")
    return provider


def _ollama_settings() -> tuple[str, str]:
    return (os.getenv("OLLAMA_MODEL") or DEFAULT_OLLAMA_MODEL,
            (os.getenv("OLLAMA_BASE_URL") or DEFAULT_OLLAMA_BASE_URL).rstrip("/"))


def _create_ollama_llm(**extra):
    from langchain_ollama import ChatOllama   # only needed when Ollama is selected
    model, base_url = _ollama_settings()
    return ChatOllama(
        model=model,
        base_url=base_url,
        temperature=0,
        num_ctx=OLLAMA_NUM_CTX,
        client_kwargs={"timeout": OLLAMA_TIMEOUT_SECONDS},
        **extra,
    )


def _create_llm():
    """Create the main answer / condense model (OpenAI or Ollama, per LLM_PROVIDER)."""
    if _llm_provider("main") == "ollama":
        return _create_ollama_llm()
    return ChatOpenAI(model_name=MODEL_NAME, temperature=0)


def _create_guard_llm():
    """Create the cheap off-topic classifier model (per GUARD_LLM_PROVIDER)."""
    if _llm_provider("guard") == "ollama":
        return _create_ollama_llm(num_predict=3)   # only need "YES" or "NO"
    return ChatOpenAI(
        model_name="gpt-4o-mini",
        temperature=0,
        max_tokens=3,      # only need "YES" or "NO"
    )


def _ollama_status() -> str | None:
    """None if the Ollama server is reachable and has the configured model, else a short reason."""
    model, base_url = _ollama_settings()
    try:
        with urllib.request.urlopen(f"{base_url}/api/tags", timeout=2) as resp:
            names = {m.get("name", "") for m in json.load(resp).get("models", [])}
    except Exception:
        return f"Ollama is not reachable at {base_url}. Start Ollama or set LLM_PROVIDER=openai."
    if model not in names and f"{model}:latest" not in names:
        return f"Ollama model {model!r} is not installed. Run: ollama pull {model}"
    return None
