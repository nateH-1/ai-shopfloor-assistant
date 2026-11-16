"""
conftest.py
===========
Mocks out all heavy third-party dependencies (LangChain, Ollama, ChromaDB)
before app.py is imported, so pytest's import hook never triggers their
bytecode compilation. This keeps unit tests fast and AV-safe.
"""
import sys
from pathlib import Path
from shutil import rmtree
from unittest.mock import MagicMock
from uuid import uuid4

import pytest


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    """Isolate temp files from Windows temp folders owned by another account."""
    if config.option.basetemp is not None:
        return
    temp_root = Path(__file__).resolve().parents[1] / ".pytest-tmp"
    temp_root.mkdir(exist_ok=True)
    # A new path per run avoids both ownership conflicts and concurrent cleanup.
    run_temp = temp_root / uuid4().hex
    config.option.basetemp = str(run_temp)
    config.add_cleanup(lambda: rmtree(run_temp, ignore_errors=True))


_MOCKED = [
    "langchain_ollama",
    "langchain_community",
    "langchain_community.vectorstores",
    "langchain_community.document_loaders",
    "langchain_community.document_loaders.pdf",
    "langchain",
    "langchain.prompts",
    "langchain.memory",
    "langchain_text_splitters",
    "langchain_core",
    "langchain_core.documents",
    "langsmith",
    "opentelemetry",
    "chromadb",
    "chromadb.utils",
    "chromadb.utils.embedding_functions",
]

for _mod in _MOCKED:
    sys.modules.setdefault(_mod, MagicMock())

# Provide specific named symbols the app imports directly
from unittest.mock import MagicMock as _M

sys.modules["langchain_ollama"].ChatOllama = _M
sys.modules["langchain_ollama"].OllamaEmbeddings = _M
sys.modules["langchain_community.document_loaders"].PyPDFLoader = _M
sys.modules["langchain.prompts"].PromptTemplate = _M
sys.modules["langchain.memory"].ConversationBufferMemory = _M
sys.modules["langchain_text_splitters"].RecursiveCharacterTextSplitter = _M
sys.modules["chromadb.utils.embedding_functions"].OllamaEmbeddingFunction = _M


@pytest.fixture(autouse=True)
def no_openai_api_key(monkeypatch):
    """Keep a developer's local .env from hiding obsolete API-key requirements."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
