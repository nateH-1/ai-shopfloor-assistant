"""Batch ingestion preserves ownership without calling embedding services."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import ingest


@pytest.mark.parametrize("store_exists", [False, True])
def test_batch_tags_shared_chunks_and_preserves_existing_guest_owner(monkeypatch, store_exists):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    files = [Path("kb/shared.txt"), Path("kb/guest.txt")]
    chunks_by_file = [
        [SimpleNamespace(page_content=f"file {file_index} page {page}",
                         metadata={"page": page, "guest_id": "untrusted-owner"})
         for page in range(2)]
        for file_index in range(2)
    ]
    splitter = MagicMock()
    splitter.split_documents.side_effect = chunks_by_file

    original_upload = "2026-01-01T12:00:00+00:00"
    with patch.object(ingest, "load_registry", return_value={
            "guest.txt": {"guest_id": "guest-a", "uploaded_at": original_upload}}), \
         patch.object(ingest, "save_registry") as save_registry, \
         patch.object(ingest, "_load_docs", return_value=["loaded page"]), \
         patch.object(ingest, "RecursiveCharacterTextSplitter", return_value=splitter), \
         patch.object(ingest, "OpenAIEmbeddings"), \
         patch.object(ingest.os.path, "exists", return_value=store_exists), \
         patch.object(ingest, "Chroma") as chroma:
        ingest.ingest_files(files)

    write = chroma.return_value.add_documents if store_exists else chroma.from_documents
    write.assert_called_once()
    written_chunks = write.call_args.args[0]
    assert [chunk.metadata for chunk in written_chunks] == [
        {"page": page, "guest_id": owner}
        for owner in ("", "guest-a")
        for page in range(2)
    ]
    save_registry.assert_called_once()
    saved = save_registry.call_args.args[0]
    assert saved["shared.txt"]["guest_id"] is None
    assert saved["guest.txt"]["guest_id"] == "guest-a"
    assert saved["guest.txt"]["uploaded_at"] == original_upload
    assert saved["shared.txt"]["uploaded_at"] != original_upload
    assert all(info["chunks"] == 2 for info in saved.values())
