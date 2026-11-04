"""Guest retention removes expired data without touching shared documents."""

import json
import runpy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import app as app_module


NOW = datetime(2030, 1, 2, 12, tzinfo=timezone.utc)


@pytest.fixture
def storage(tmp_path, monkeypatch):
    directory = tmp_path / "knowledge_base"
    directory.mkdir()
    registry_path = directory / "documents.json"
    monkeypatch.setattr(app_module, "KNOWLEDGE_BASE_DIR", directory)
    monkeypatch.setattr(app_module, "DOCUMENTS_JSON", registry_path)
    monkeypatch.setattr(app_module, "conversation_sessions", {"old-login": {"memory": "old context"}})
    monkeypatch.setattr(app_module, "_keyword_index", {"old": "index"})
    monkeypatch.setattr(app_module, "_keyword_index_stale", False)
    vectors = {}
    collection = MagicMock()

    def get(*, where, include):
        source_filter = where["source"]
        sources = source_filter["$in"] if isinstance(source_filter, dict) else [source_filter]
        selected = {key: metadata for key, metadata in vectors.items() if metadata["source"] in sources}
        return {"ids": list(selected), "metadatas": list(selected.values())}

    def delete(*, ids):
        for chunk_id in ids:
            vectors.pop(chunk_id, None)

    collection.get.side_effect = get
    collection.delete.side_effect = delete
    monkeypatch.setattr(app_module, "_get_guest_cleanup_collections", lambda: [collection])

    def write_registry(registry):
        registry_path.write_text(json.dumps(registry), encoding="utf-8")

    def add_file(filename, owner="guest-a"):
        path = directory / filename
        path.write_text("uploaded content", encoding="utf-8")
        vectors[filename] = {"source": str(path), "guest_id": owner}
        return path

    return SimpleNamespace(
        directory=directory, registry_path=registry_path, vectors=vectors,
        collection=collection, write_registry=write_registry, add_file=add_file,
        read_registry=lambda: json.loads(registry_path.read_text(encoding="utf-8")),
    )


def uploaded(owner="guest-a", age=timedelta(hours=24)):
    return {"guest_id": owner, "uploaded_at": (NOW - age).isoformat(), "chunks": 1}


def test_expiration_boundary_keeps_new_and_shared_documents(storage):
    registry = {
        "expired.txt": uploaded(),
        "older.txt": uploaded("guest-b", timedelta(days=2)),
        "new.txt": uploaded(age=timedelta(hours=24) - timedelta(microseconds=1)),
        "shared.txt": uploaded(None, timedelta(days=30)),
        "shared-empty.txt": uploaded("", timedelta(days=30)),
    }
    for filename, info in registry.items():
        storage.add_file(filename, info["guest_id"])
    storage.write_registry(registry)

    assert app_module._cleanup_expired_guest_documents(now=NOW) == 2

    survivors = {"new.txt", "shared.txt", "shared-empty.txt"}
    assert set(storage.read_registry()) == survivors
    assert set(storage.vectors) == survivors
    assert {path.name for path in storage.directory.glob("*.txt")} == survivors
    assert app_module._keyword_index_stale is True
    assert app_module.conversation_sessions == {}


def test_legacy_vectors_are_removed_but_other_owners_are_preserved(storage):
    path = storage.add_file("expired.txt")
    storage.vectors.update({
        "legacy": {"source": str(path)},
        "other-guest": {"source": str(path), "guest_id": "guest-b"},
        "shared": {"source": str(path), "guest_id": ""},
        "other-file": {"source": str(storage.directory / "other.txt"), "guest_id": "guest-a"},
    })
    storage.write_registry({"expired.txt": uploaded()})

    assert app_module._cleanup_expired_guest_documents(now=NOW) == 1

    assert set(storage.vectors) == {"other-guest", "shared", "other-file"}
    assert not path.exists()
    assert storage.read_registry() == {}


@pytest.mark.parametrize("operation", ["get", "delete"])
def test_vector_failure_keeps_file_and_registry_for_retry(storage, operation):
    path = storage.add_file("expired.txt")
    storage.write_registry({"expired.txt": uploaded()})
    method = getattr(storage.collection, operation)
    normal_operation = method.side_effect
    method.side_effect = RuntimeError("database unavailable")

    assert app_module._cleanup_expired_guest_documents(now=NOW) == 0
    assert path.exists()
    assert "expired.txt" in storage.read_registry()
    if operation == "delete":
        assert app_module._keyword_index_stale is True
        assert app_module.conversation_sessions == {}

    method.side_effect = normal_operation
    assert app_module._cleanup_expired_guest_documents(now=NOW) == 1
    assert not path.exists()
    assert storage.read_registry() == {}
    assert storage.vectors == {}


def test_unlink_failure_keeps_registry_and_invalidates_cached_context(storage, monkeypatch):
    path = storage.add_file("expired.txt")
    storage.write_registry({"expired.txt": uploaded()})
    real_unlink = Path.unlink

    def locked_unlink(target, *args, **kwargs):
        if target == path:
            raise PermissionError("file locked")
        return real_unlink(target, *args, **kwargs)

    with monkeypatch.context() as patcher:
        patcher.setattr(Path, "unlink", locked_unlink)
        assert app_module._cleanup_expired_guest_documents(now=NOW) == 0

    assert path.exists()
    assert "expired.txt" in storage.read_registry()
    assert storage.vectors == {}
    assert app_module._keyword_index_stale is True
    assert app_module.conversation_sessions == {}
    assert app_module._cleanup_expired_guest_documents(now=NOW) == 1
    assert storage.read_registry() == {}


def test_missing_file_does_not_prevent_vector_and_registry_cleanup(storage):
    path = storage.add_file("expired.txt")
    path.unlink()
    storage.write_registry({"expired.txt": uploaded()})

    assert app_module._cleanup_expired_guest_documents(now=NOW) == 1
    assert storage.vectors == {}
    assert storage.read_registry() == {}


def test_invalid_dates_and_unsafe_paths_are_not_deleted(storage):
    outside = storage.directory.parent / "outside.txt"
    outside.write_text("outside the knowledge base", encoding="utf-8")
    registry = {
        "bad-date.txt": {"guest_id": "guest-a", "uploaded_at": "not a timestamp"},
        "missing-date.txt": {"guest_id": "guest-a"},
        "../outside.txt": uploaded(),
        str(outside): uploaded(),
        "documents.json": uploaded(),
    }
    for name in ("bad-date.txt", "missing-date.txt"):
        storage.add_file(name)
    storage.write_registry(registry)

    assert app_module._cleanup_expired_guest_documents(now=NOW) == 0

    assert storage.read_registry() == registry
    assert outside.read_text(encoding="utf-8") == "outside the knowledge base"
    assert (storage.directory / "bad-date.txt").exists()
    assert (storage.directory / "missing-date.txt").exists()
    storage.collection.get.assert_not_called()


def test_naive_upload_timestamps_are_treated_as_utc(storage):
    storage.add_file("expired.txt")
    info = uploaded()
    info["uploaded_at"] = (NOW - timedelta(hours=24)).replace(tzinfo=None).isoformat()
    storage.write_registry({"expired.txt": info})

    assert app_module._cleanup_expired_guest_documents(now=NOW) == 1
    assert storage.read_registry() == {}


def test_missing_vector_store_still_removes_expired_file(storage, monkeypatch):
    path = storage.add_file("expired.txt")
    storage.write_registry({"expired.txt": uploaded()})
    monkeypatch.setattr(app_module, "_get_guest_cleanup_collections", lambda: [])

    assert app_module._cleanup_expired_guest_documents(now=NOW) == 1
    assert not path.exists()
    assert storage.read_registry() == {}


def test_cleanup_store_open_failure_keeps_data_for_retry(storage, monkeypatch):
    path = storage.add_file("expired.txt")
    storage.write_registry({"expired.txt": uploaded()})
    monkeypatch.setattr(app_module, "_get_guest_cleanup_collections", MagicMock(side_effect=RuntimeError("locked")))

    assert app_module._cleanup_expired_guest_documents(now=NOW) == 0
    assert path.exists()
    assert "expired.txt" in storage.read_registry()
    assert "expired.txt" in storage.vectors


def test_cleanup_opens_only_document_collections_without_embeddings(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "CHROMA_DB_DIR", str(tmp_path))
    monkeypatch.setattr(app_module, "collection", None)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    client = MagicMock()
    client.list_collections.return_value = [
        SimpleNamespace(name="documents"), SimpleNamespace(name="langchain"), SimpleNamespace(name="feedback"),
    ]
    open_client = MagicMock(return_value=client)
    monkeypatch.setattr(app_module.chromadb, "PersistentClient", open_client)

    assert len(app_module._get_guest_cleanup_collections()) == 2
    assert [call.kwargs for call in client.get_collection.call_args_list] == [
        {"name": "documents", "embedding_function": None},
        {"name": "langchain", "embedding_function": None},
    ]


def test_startup_sweeps_once_and_starts_one_worker(monkeypatch):
    sweep = MagicMock()
    thread_factory = MagicMock()
    thread_factory.return_value.is_alive.return_value = True
    monkeypatch.setattr(app_module, "_guest_cleanup_thread", None)
    monkeypatch.setattr(app_module, "_guest_cleanup_stop", MagicMock())
    monkeypatch.setattr(app_module, "_cleanup_expired_guest_documents", sweep)
    monkeypatch.setattr(app_module, "Thread", thread_factory)

    app_module._start_guest_cleanup()
    app_module._start_guest_cleanup()

    sweep.assert_called_once()
    thread_factory.assert_called_once()
    assert thread_factory.call_args.kwargs["target"] is app_module._guest_cleanup_loop
    assert thread_factory.call_args.kwargs["daemon"] is True
    thread_factory.return_value.start.assert_called_once()


def test_periodic_worker_retries_after_failure_without_traffic(monkeypatch):
    stop = MagicMock()
    stop.wait.side_effect = [False, False, True]
    sweep = MagicMock(side_effect=[RuntimeError("temporary failure"), 1])
    monkeypatch.setattr(app_module, "_guest_cleanup_stop", stop)
    monkeypatch.setattr(app_module, "_cleanup_expired_guest_documents", sweep)

    app_module._guest_cleanup_loop()

    assert sweep.call_count == 2
    assert all(call.args == (60,) for call in stop.wait.call_args_list)


def test_launcher_starts_cleanup_before_serving(monkeypatch):
    calls = []
    monkeypatch.setattr(app_module, "_initialize_sqlite", lambda: calls.append("database"))
    monkeypatch.setattr(app_module, "_start_guest_cleanup", lambda: calls.append("cleanup"))
    monkeypatch.setattr(app_module.app, "run", lambda **kwargs: calls.append("server"))

    runpy.run_path(str(Path(app_module.__file__).with_name("run.py")), run_name="__main__")

    assert calls == ["database", "cleanup", "server"]
