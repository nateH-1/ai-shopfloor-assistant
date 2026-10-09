import chromadb
from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction
from langchain_openai import ChatOpenAI

from rag.config import CHROMA_DB_DIR, MODEL_NAME


def _create_collection(api_key: str) -> chromadb.Collection:
    """Open (or create) the persistent Chroma collection holding document chunks."""
    ef     = OpenAIEmbeddingFunction(api_key=api_key, model_name="text-embedding-ada-002")
    client = chromadb.PersistentClient(path=CHROMA_DB_DIR)
    return client.get_or_create_collection(name="documents", embedding_function=ef)


def _create_llm() -> ChatOpenAI:
    """Create the main answer / condense model."""
    return ChatOpenAI(model_name=MODEL_NAME, temperature=0)


def _create_guard_llm() -> ChatOpenAI:
    """Create the cheap off-topic classifier model."""
    return ChatOpenAI(
        model_name="gpt-4o-mini",
        temperature=0,
        max_tokens=3,      # only need "YES" or "NO"
    )
