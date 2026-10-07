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

from rag.retrieval import _hybrid_search, _is_code_like_query, _reciprocal_rank_fusion


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
        "metadatas": [[{"source": "kb/manual.pdf"} for _ in hits]],
        "distances": [[d for _, d in hits]],
    }
    return coll


def _kw(*ids):
    return [{"id": i, "text": f"text of {i}", "metadata": {"source": "kb/manual.pdf"}, "score": 5.0} for i in ids]


def _search(query, vector_hits, keyword_hits, **kwargs):
    getter = MagicMock(return_value="INDEX")
    with patch("rag.retrieval._keyword_search", return_value=keyword_hits) as kw:
        docs = _hybrid_search(_collection(vector_hits), query, getter, **kwargs)
    return [d.page_content.removeprefix("text of ") for d in docs], getter, kw


def test_strong_plain_question_uses_vector_only():
    ids, getter, kw = _search("how do I clean a lathe", [("a", 0.11), ("b", 0.15)], _kw("z"))
    assert ids == ["a", "b"]
    getter.assert_not_called()          # keyword index never even built
    kw.assert_not_called()


def test_weak_vector_match_adds_keyword_results():
    ids, getter, _ = _search("how do I clean a lathe", [("a", 0.25), ("b", 0.30)], _kw("z"))
    assert set(ids) == {"a", "b", "z"}
    getter.assert_called_once()


def test_code_like_question_adds_keyword_results_even_when_vector_is_strong():
    ids, _, _ = _search("what drill goes with an 8mm-1.25 tap", [("a", 0.12)], _kw("z"))
    assert "z" in ids


def test_chunk_found_by_both_searches_ranks_first():
    ids, _, _ = _search("CO2 welding", [("a", 0.12), ("b", 0.13), ("c", 0.14)], _kw("c", "z"))
    assert ids[0] == "c"


def test_document_scope_applies_to_keyword_search():
    _, _, kw = _search("CO2 welding", [("a", 0.25)], _kw("z"), where={"source": "kb/manual.pdf"})
    assert kw.call_args.kwargs["source"] == "kb/manual.pdf"


def test_code_detection_and_rank_fusion():
    assert _is_code_like_query("8mm-1.25 tap") and _is_code_like_query("CO2 cylinder")
    assert not _is_code_like_query("how do I clean a lathe")
    assert _reciprocal_rank_fusion([["a", "b"], ["b", "c"]]) == ["b", "a", "c"]
