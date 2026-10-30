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
from rag.config import CHROMA_DB_DIR


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


# ── Local model (Ollama only) ─────────────────────────────────────────────────

def test_models_use_local_ollama_with_large_context(monkeypatch):
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    with patch.object(resources, "ChatOllama") as ollama:
        resources._create_llm()
        resources._create_guard_llm()
    main, guard = ollama.call_args_list[0].kwargs, ollama.call_args_list[1].kwargs
    assert main["model"] == resources.DEFAULT_OLLAMA_MODEL
    assert main["num_ctx"] == resources.OLLAMA_NUM_CTX      # no silent truncation
    assert guard["num_predict"] == 3                         # guard only needs YES/NO


def test_ollama_model_can_be_overridden_in_env(monkeypatch):
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.2:3b")
    with patch.object(resources, "ChatOllama") as ollama:
        resources._create_llm()
    assert ollama.call_args.kwargs["model"] == "llama3.2:3b"


def test_ollama_status_reports_unreachable_server():
    with patch("rag.resources.urllib.request.urlopen", side_effect=OSError("connection refused")):
        assert "not reachable" in resources._ollama_status()


def test_chat_explains_when_ollama_is_down(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "USERS_DB_PATH", tmp_path / "users.db")
    client = app_module.app.test_client()
    client.environ_base["HTTP_X_TAB_ID"] = "7e8fd964-c9c4-40bf-b7fa-4b48444bf45c"
    assert client.post("/users/session").status_code == 204
    assert client.post("/users/register", json={"role": "Guest"}).status_code == 200
    app_module.collection = MagicMock(**{"count.return_value": 5})
    app_module.llm = MagicMock()
    with patch("app.answer_question", side_effect=ConnectionError("Failed to connect to Ollama")):
        res = client.post("/chat", json={"message": "how do I clean a lathe"})
    assert res.status_code == 503
    assert "Ollama" in res.get_json()["reply"]
