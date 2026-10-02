"""
test_resources.py
=================
Tests for resource creation in rag/resources.py and how app.py stores it.
They pin down the settings that must not change silently (collection name,
embedding model, chat models) and the current _init_store error behavior.
Framework: pytest + unittest.mock
Run: cd backend && pytest test_resources.py -v
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
