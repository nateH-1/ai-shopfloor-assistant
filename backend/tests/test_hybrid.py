"""
test_hybrid.py
==============
Tests for _hybrid_search in rag/retrieval.py: vector search first, BM25 keyword
results merged in (by rank) only for code-like questions or weak vector matches.
Chroma and the keyword search are faked; no OpenAI calls.
Framework: pytest + unittest.mock
Run: cd backend && pytest tests/test_hybrid.py -v
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from rag.keyword import _build_keyword_index, _tokenize
from rag.retrieval import (
    _hybrid_search, _is_code_like_query, _reciprocal_rank_fusion,
    _similarity_search, _similarity_search_with_score,
)


@pytest.fixture(autouse=True)
def real_documents():
    # conftest fakes langchain_core, so make Document a plain object we can inspect.
    with patch("rag.retrieval.Document", side_effect=lambda page_content, metadata: SimpleNamespace(
            page_content=page_content, metadata=metadata)):
        yield


def _collection(hits):
    """Fake Chroma collection whose query returns hits = [(id, distance)], best first."""
    coll = MagicMock()
    coll.count.return_value = 50
    coll.query.return_value = {
        "ids":       [[i for i, _ in hits]],
        "documents": [[f"text of {i}" for i, _ in hits]],
        "metadatas": [[{"source": "kb/manual.pdf", "guest_id": ""} for _ in hits]],
        "distances": [[d for _, d in hits]],
    }
    return coll


def _kw(*ids):
    return [{"id": i, "text": f"text of {i}", "metadata": {"source": "kb/manual.pdf", "guest_id": ""}, "score": 5.0} for i in ids]


def _search(query, vector_hits, keyword_hits, vocab=None, **kwargs):
    """Run _hybrid_search; the fake index's vocabulary holds every query word unless given."""
    getter = MagicMock(return_value={
        "vocab_by_guest": {kwargs.get("guest_id", ""): set(_tokenize(query)) if vocab is None else vocab},
    })
    with patch("rag.retrieval._keyword_search", return_value=keyword_hits) as kw:
        docs, enough = _hybrid_search(_collection(vector_hits), query, getter, **kwargs)
    return [d.page_content.removeprefix("text of ") for d in docs], getter, kw, enough


def test_strong_plain_question_uses_vector_only():
    ids, getter, kw, enough = _search("how do I clean a lathe", [("a", 0.11), ("b", 0.15)], _kw("z"))
    assert ids == ["a", "b"] and enough
    getter.assert_not_called()          # keyword index never even built
    kw.assert_not_called()


def test_weak_vector_match_adds_keyword_results():
    ids, getter, _, enough = _search("how do I clean a lathe", [("a", 0.25), ("b", 0.30)], _kw("z"))
    assert set(ids) == {"a", "b", "z"} and enough
    getter.assert_called_once()


def test_code_like_question_adds_keyword_results_even_when_vector_is_strong():
    ids, _, _, _ = _search("what drill goes with an 8mm-1.25 tap", [("a", 0.12)], _kw("z"))
    assert "z" in ids


def test_chunk_found_by_both_searches_ranks_first():
    ids, _, _, _ = _search("CO2 welding", [("a", 0.12), ("b", 0.13), ("c", 0.14)], _kw("c", "z"))
    assert ids[0] == "c"


def test_document_scope_applies_to_keyword_search():
    _, _, kw, _ = _search("CO2 welding", [("a", 0.25)], _kw("z"), where={"source": "kb/manual.pdf"})
    assert kw.call_args.kwargs["source"] == "kb/manual.pdf"


@pytest.mark.parametrize("guest_id", ["", "guest-a", "guest-b"])
def test_hybrid_combines_owner_with_source_and_forwards_owner_to_keyword_search(guest_id):
    collection = _collection([("a", 0.12)])
    with patch("rag.retrieval._keyword_search", return_value=[]) as keyword_search:
        _hybrid_search(collection, "CO2 welding", lambda: None,
                       where={"source": "kb/manual.pdf"}, guest_id=guest_id)
    assert collection.query.call_args.kwargs["where"] == {
        "$and": [{"guest_id": guest_id}, {"source": "kb/manual.pdf"}],
    }
    assert keyword_search.call_args.kwargs["guest_id"] == guest_id
    assert keyword_search.call_args.kwargs["source"] == "kb/manual.pdf"


def _mixed_owner_collection(distance):
    """Evaluate query filters over mixed ownership; get() exposes the full keyword corpus."""
    rows = [
        ("a", "CO2 welding", {"source": "kb/manual.pdf", "guest_id": "guest-a"}),
        ("b", "CO2 welding", {"source": "kb/manual.pdf", "guest_id": "guest-b"}),
        ("shared", "CO2 welding", {"source": "kb/manual.pdf", "guest_id": ""}),
        ("legacy", "CO2 welding", {"source": "kb/manual.pdf"}),
        ("a-other", "CO2 welding", {"source": "kb/other.pdf", "guest_id": "guest-a"}),
    ] + [(f"filler-{i}", "lathe spindle cutting oil", {"source": "kb/legacy.pdf"}) for i in range(8)]
    collection = MagicMock()
    collection.count.return_value = len(rows)
    collection.get.return_value = {
        "ids": [r[0] for r in rows], "documents": [r[1] for r in rows],
        "metadatas": [r[2] for r in rows],
    }

    def matches(metadata, where):
        if "$and" in where:
            return all(matches(metadata, clause) for clause in where["$and"])
        return all(metadata.get(key) == value for key, value in where.items())

    def query(**kwargs):
        selected = [r for r in rows if matches(r[2], kwargs.get("where", {}))][:kwargs["n_results"]]
        return {
            "ids": [[r[0] for r in selected]], "documents": [[r[1] for r in selected]],
            "metadatas": [[r[2] for r in selected]], "distances": [[distance for _ in selected]],
        }

    collection.query.side_effect = query
    return collection


@pytest.mark.parametrize("guest_id,expected", [
    ("", {"shared"}), ("guest-a", {"a", "a-other"}), ("guest-b", {"b"}), ("new-guest", set()),
])
def test_hybrid_never_merges_other_owners_or_untagged_legacy_chunks(guest_id, expected):
    collection = _mixed_owner_collection(0.25)
    index = _build_keyword_index(collection)
    documents, enough = _hybrid_search(collection, "CO2 welding", lambda: index, guest_id=guest_id)
    assert all(doc.metadata["guest_id"] == guest_id for doc in documents)
    # The fake Chroma query identifies the vector hits; keyword fallback must not add other owners.
    assert len(documents) == len(expected)
    assert enough is bool(expected)


def test_hybrid_owner_and_source_both_limit_real_keyword_fallback():
    collection = _mixed_owner_collection(0.25)
    index = _build_keyword_index(collection)
    documents, enough = _hybrid_search(
        collection, "CO2 welding", lambda: index, guest_id="guest-a",
        where={"source": "kb/manual.pdf"},
    )
    assert enough and len(documents) == 1
    assert documents[0].metadata == {"source": "kb/manual.pdf", "guest_id": "guest-a"}


@pytest.mark.parametrize("search", [_similarity_search, _similarity_search_with_score])
@pytest.mark.parametrize("guest_id", ["", "guest-a", "guest-b"])
def test_similarity_helpers_enforce_owner_filter(search, guest_id):
    collection = _mixed_owner_collection(0.12)
    results = search(collection, "welding", guest_id=guest_id)
    documents = [result[0] if isinstance(result, tuple) else result for result in results]
    assert documents
    assert all(document.metadata["guest_id"] == guest_id for document in documents)
    assert collection.query.call_args.kwargs["where"] == {"guest_id": guest_id}


def test_code_detection_and_rank_fusion():
    assert _is_code_like_query("8mm-1.25 tap") and _is_code_like_query("CO2 cylinder")
    assert not _is_code_like_query("how do I clean a lathe")
    assert _reciprocal_rank_fusion([["a", "b"], ["b", "c"]]) == ["b", "a", "c"]


# ── Evidence check (PR C) ─────────────────────────────────────────────────────

def test_weak_match_with_word_missing_from_documents_is_not_enough_evidence():
    ids, _, kw, enough = _search("what is the warranty period", [("a", 0.22)], _kw("z"),
                                 vocab={"period"})          # "warranty" appears in no chunk
    assert ids == [] and not enough
    kw.assert_not_called()


def test_strong_match_is_enough_even_with_unknown_words():
    _, getter, _, enough = _search("how do I clean a lathe quickly", [("a", 0.11)], [], vocab=set())
    assert enough
    getter.assert_not_called()
