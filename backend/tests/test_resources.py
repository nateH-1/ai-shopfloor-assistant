"""
test_resources.py
=================
Tests for resource creation in rag/resources.py and how app.py stores it.
They pin down the settings that must not change silently (collection name,
embedding model, chat models) and the current _init_store error behavior.
Framework: pytest + unittest.mock
Run: cd backend && pytest tests/test_resources.py -v
"""

from unittest.mock import MagicMock, patch

import pytest

import app as app_module
from rag import resources
from rag.config import CHROMA_DB_DIR, MODEL_NAME


@pytest.fixture(autouse=True)
def reset_globals():
    app_module.collection = None
    app_module.llm = None
    app_module._guard_llm = None
    yield
    app_module.collection = None
    app_module.llm = None
    app_module._guard_llm = None


def test_collection_uses_existing_index_settings():
    # Changing any of these would point the app at a different (empty) index.
    with patch.object(resources, "chromadb") as chroma, \
         patch.object(resources, "OpenAIEmbeddingFunction") as ef:
        resources._create_collection("sk-test")
    ef.assert_called_once_with(api_key="sk-test", model_name="text-embedding-ada-002")
    chroma.PersistentClient.assert_called_once_with(path=CHROMA_DB_DIR)
    chroma.PersistentClient.return_value.get_or_create_collection.assert_called_once_with(
        name="documents", embedding_function=ef.return_value)


def test_chat_model_settings():
    with patch.object(resources, "ChatOpenAI") as chat:
        resources._create_llm()
        resources._create_guard_llm()
    assert chat.call_args_list[0].kwargs == {"model_name": MODEL_NAME, "temperature": 0}
    assert chat.call_args_list[1].kwargs == {"model_name": "gpt-4o-mini", "temperature": 0, "max_tokens": 3}


def test_guard_client_created_once_and_reused():
    with patch("app._create_guard_llm", return_value=MagicMock()) as create:
        first = app_module._get_guard_llm()
        second = app_module._get_guard_llm()
    create.assert_called_once()
    assert first is second


def test_init_store_without_api_key_reports_it():
    with patch("app.os.getenv", return_value=None):
        assert app_module._init_store() == (False, "OPENAI_API_KEY not set in environment.")
    assert app_module.collection is None


def test_init_store_failure_is_reported_not_raised():
    with patch("app.os.getenv", return_value="sk-test"), \
         patch("app._create_collection", side_effect=RuntimeError("disk locked")):
        assert app_module._init_store() == (False, "Failed to load vector store: disk locked")


# ── Model provider switch (PR D) ──────────────────────────────────────────────

def test_ollama_provider_uses_local_model_with_large_context(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.delenv("GUARD_LLM_PROVIDER", raising=False)
    with patch("langchain_ollama.ChatOllama") as ollama, patch.object(resources, "ChatOpenAI") as openai:
        resources._create_llm()
        resources._create_guard_llm()
    assert ollama.call_args_list[0].kwargs["num_ctx"] == resources.OLLAMA_NUM_CTX   # no silent truncation
    assert ollama.call_args_list[1].kwargs["num_predict"] == 3                        # guard follows main
    openai.assert_not_called()


def test_guard_provider_can_differ_from_main(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("GUARD_LLM_PROVIDER", "openai")
    assert (resources._llm_provider(), resources._llm_provider("guard")) == ("ollama", "openai")


def test_unknown_provider_is_rejected(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "olama")
    with pytest.raises(ValueError):
        resources._llm_provider()


def test_ollama_status_reports_unreachable_server():
    with patch("rag.resources.urllib.request.urlopen", side_effect=OSError("connection refused")):
        assert "not reachable" in resources._ollama_status()


def test_chat_explains_when_ollama_is_down():
    app_module.collection = MagicMock(**{"count.return_value": 5})
    app_module.llm = MagicMock()
    with patch("app.answer_question", side_effect=ConnectionError("Failed to connect to Ollama")):
        res = app_module.app.test_client().post("/chat", json={"message": "how do I clean a lathe"})
    assert res.status_code == 503
    assert "Ollama" in res.get_json()["reply"]
