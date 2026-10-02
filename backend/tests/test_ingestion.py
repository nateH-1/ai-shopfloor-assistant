"""
test_ingestion.py
=================
Tests for _ingest_file in rag/ingestion.py — the code that writes uploaded
documents into the Chroma collection. A fake collection records what would
be deleted and added; nothing touches the real database.
Framework: pytest + unittest.mock
Run: cd backend && pytest tests/test_ingestion.py -v
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from rag import ingestion


def _ingest(chunks, collection=None):
    """Run _ingest_file on a fake file whose splitter returns `chunks`."""
    collection = collection or MagicMock()
    splitter = MagicMock()
    splitter.split_documents.return_value = chunks
    with patch.object(ingestion, "_load_docs", return_value=["page"]), \
         patch.object(ingestion, "RecursiveCharacterTextSplitter", return_value=splitter):
        result = ingestion._ingest_file(Path("knowledge_base/manual.pdf"), collection)
    return result, collection


def _chunk(i):
    return SimpleNamespace(page_content=f"text {i}", metadata={"page": i, "bad": [1, 2]})


def test_replaces_old_chunks_with_stable_ids_and_source():
    result, coll = _ingest([_chunk(0), _chunk(1)])
    source = str(Path("knowledge_base/manual.pdf"))
    assert result == (True, "Ingested 2 chunks.", 2)
    coll.delete.assert_called_once_with(where={"source": source})
    coll.add.assert_called_once_with(
        ids=["manual.pdf__chunk_0", "manual.pdf__chunk_1"],
        documents=["text 0", "text 1"],
        metadatas=[{"source": source, "page": 0}, {"source": source, "page": 1}],  # non-primitive "bad" dropped
    )


def test_adds_in_batches_of_100():
    _, coll = _ingest([_chunk(i) for i in range(250)])
    assert [len(c.kwargs["ids"]) for c in coll.add.call_args_list] == [100, 100, 50]


def test_empty_file_reports_and_leaves_index_alone():
    coll = MagicMock()
    with patch.object(ingestion, "_load_docs", return_value=[]):
        result = ingestion._ingest_file(Path("knowledge_base/empty.txt"), coll)
    assert result == (False, "No content extracted from empty.txt.", 0)
    coll.delete.assert_not_called()


def test_errors_are_reported_not_raised():
    coll = MagicMock()
    coll.add.side_effect = RuntimeError("embedding quota exceeded")
    result, _ = _ingest([_chunk(0)], coll)
    assert result == (False, "Ingestion error: embedding quota exceeded", 0)
