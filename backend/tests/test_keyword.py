"""
test_keyword.py
===============
Tests for BM25 keyword search in rag/keyword.py and the index cache in app.py.
Uses the real rank-bm25 library on a small fake collection; no Chroma or OpenAI.
Framework: pytest + unittest.mock
Run: cd backend && pytest tests/test_keyword.py -v
"""

from unittest.mock import MagicMock, patch

import pytest

import app as app_module
from rag.keyword import _build_keyword_index, _keyword_search, _tokenize, _unknown_terms


def _collection(chunks):
    """Fake Chroma collection holding (id, text, source) chunks."""
    coll = MagicMock()
    coll.get.return_value = {
        "ids":       [c[0] for c in chunks],
        "documents": [c[1] for c in chunks],
        "metadatas": [{"source": c[2], "page": 0, "guest_id": ""} for c in chunks],
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


@pytest.mark.parametrize("guest_id,expected", [("guest-a", "a"), ("guest-b", "b"), ("", "shared")])
def test_keyword_filters_owner_before_top_k_and_excludes_legacy(guest_id, expected):
    index = {
        "ids": ["legacy", "b", "shared", "a"],
        "texts": ["CO2 welding"] * 4,
        "metadatas": [
            {"source": "kb/manual.pdf"},
            {"source": "kb/manual.pdf", "guest_id": "guest-b"},
            {"source": "kb/manual.pdf", "guest_id": ""},
            {"source": "kb/manual.pdf", "guest_id": "guest-a"},
        ],
        "bm25": MagicMock(),
    }
    index["bm25"].get_scores.return_value = [100, 90, 80, 10]
    hits = _keyword_search(index, "CO2 welding", k=1, guest_id=guest_id)
    assert [hit["id"] for hit in hits] == [expected]
    assert _keyword_search(index, "CO2 welding", guest_id="unknown-guest") == []


def test_owner_vocabulary_excludes_other_guests_shared_and_legacy_terms():
    collection = _collection([
        ("a", "welding", "kb/a.pdf"),
        ("b", "warranty", "kb/b.pdf"),
        ("shared", "assembly", "kb/shared.pdf"),
        ("legacy", "secret", "kb/legacy.pdf"),
    ])
    collection.get.return_value["metadatas"][0]["guest_id"] = "guest-a"
    collection.get.return_value["metadatas"][1]["guest_id"] = "guest-b"
    del collection.get.return_value["metadatas"][3]["guest_id"]
    index = _build_keyword_index(collection)
    assert _unknown_terms(index, "welding warranty assembly secret", guest_id="guest-a") == [
        "warranty", "assembly", "secret",
    ]
    assert _unknown_terms(index, "welding warranty assembly secret", guest_id="") == [
        "welding", "warranty", "secret",
    ]


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
