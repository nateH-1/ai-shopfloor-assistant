"""
test_keyword.py
===============
Tests for BM25 keyword search in rag/keyword.py and the index cache in app.py.
Uses the real rank-bm25 library on a small fake collection; no Chroma or OpenAI.
Framework: pytest + unittest.mock
Run: cd backend && pytest tests/test_keyword.py -v
"""

from unittest.mock import MagicMock, patch

import app as app_module
from rag.keyword import _build_keyword_index, _keyword_search, _tokenize


def _collection(chunks):
    """Fake Chroma collection holding (id, text, source) chunks."""
    coll = MagicMock()
    coll.get.return_value = {
        "ids":       [c[0] for c in chunks],
        "documents": [c[1] for c in chunks],
        "metadatas": [{"source": c[2], "page": 0} for c in chunks],
    }
    return coll


_CHUNKS = [
    ("lathe__0",   "Set the lathe spindle speed before cutting.",          "kb/lathe.pdf"),
    ("lathe__1",   "Tap the hole with an 8mm-1.25 tap and cutting oil.",   "kb/lathe.pdf"),
    ("weld__0",    "Oxyacetylene welding burns acetylene to make CO2.",    "kb/weld.pdf"),
    ("weld__1",    "Check cylinder pressure, about 1 kg/cm2, before use.", "kb/weld.pdf"),
    ("cast__0",    "Pig iron is melted in a cupola furnace.",              "kb/cast.pdf"),
]


def test_tokenize_keeps_codes_whole():
    assert _tokenize("Use an 8mm-1.25 bolt, CO2 gas and 5 kg/cm2 pressure.") == \
        ["use", "an", "8mm-1.25", "bolt", "co2", "gas", "and", "5", "kg/cm2", "pressure"]


def test_exact_code_ranks_its_chunk_first():
    index = _build_keyword_index(_collection(_CHUNKS))
    hits = _keyword_search(index, "what is an 8mm-1.25 tap?")
    assert hits[0]["id"] == "lathe__1"
    assert set(hits[0]) == {"id", "text", "metadata", "score"}


def test_source_limits_results_to_one_file():
    index = _build_keyword_index(_collection(_CHUNKS))
    hits = _keyword_search(index, "cutting welding pressure", source="kb/weld.pdf")
    assert hits and {h["metadata"]["source"] for h in hits} == {"kb/weld.pdf"}


def test_no_shared_words_returns_nothing():
    index = _build_keyword_index(_collection(_CHUNKS))
    assert _keyword_search(index, "forklift battery") == []


def test_empty_collection_gives_no_index_and_no_results():
    index = _build_keyword_index(_collection([]))
    assert index is None
    assert _keyword_search(index, "anything") == []


def test_app_rebuilds_index_only_after_documents_change():
    app_module.collection = _collection(_CHUNKS)
    app_module._mark_keyword_index_stale()
    try:
        with patch("app._build_keyword_index", wraps=_build_keyword_index) as build:
            first = app_module._get_keyword_index()
            assert app_module._get_keyword_index() is first      # cached
            app_module._mark_keyword_index_stale()               # e.g. after an upload
            app_module._get_keyword_index()
        assert build.call_count == 2
    finally:
        app_module.collection = None
        app_module._mark_keyword_index_stale()
