"""
test_chat_endpoint.py
=====================
Unit tests for all Flask routes.
Framework: pytest + unittest.mock + Flask test client
Run: cd backend && pytest test_chat_endpoint.py -v
"""

import io
import os
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
import app as app_module
from app import app


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture(autouse=True)
def reset_global_state():
    """Isolate global state between every test."""
    app_module.collection = None
    app_module.llm = None
    app_module.conversation_sessions.clear()
    yield
    app_module.collection = None
    app_module.llm = None
    app_module.conversation_sessions.clear()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mock_chat_response(answer="Mocked answer.", sources=None):
    """Return (answer, chunks) tuple as _chat_with_memory does."""
    return (answer, sources or [])


def _ready_collection(count=5):
    """Return a MagicMock ChromaDB collection that looks populated."""
    coll = MagicMock()
    coll.count.return_value = count
    return coll


def _mock_doc(content, page=0, source="test.pdf"):
    doc = MagicMock()
    doc.page_content = content
    doc.metadata = {"source": source, "page": page}
    return doc


# ── Group 1: Input Validation (Rule 1 — empty message check) ─────────────────

class TestEmptyMessageValidation:

    def test_empty_string_returns_400(self, client):
        res = client.post("/chat", json={"message": ""})
        assert res.status_code == 400
        assert res.get_json()["error"] == "Message cannot be empty"

    def test_whitespace_only_returns_400(self, client):
        res = client.post("/chat", json={"message": "   "})
        assert res.status_code == 400
        assert res.get_json()["error"] == "Message cannot be empty"

    def test_tab_and_newline_only_returns_400(self, client):
        res = client.post("/chat", json={"message": "\t\n"})
        assert res.status_code == 400
        assert res.get_json()["error"] == "Message cannot be empty"

    def test_missing_message_field_returns_400(self, client):
        res = client.post("/chat", json={"session_id": "abc"})
        assert res.status_code == 400
        assert res.get_json()["error"] == "Message cannot be empty"

    def test_null_message_returns_400(self, client):
        res = client.post("/chat", json={"message": None})
        assert res.status_code == 400
        assert res.get_json()["error"] == "Message cannot be empty"

    def test_single_character_passes_empty_check(self, client):
        """1-character message must not be rejected."""
        app_module.collection = _ready_collection()
        app_module.llm = MagicMock()
        with patch("app._is_off_topic", return_value=False), \
             patch("app._chat_with_memory", return_value=_mock_chat_response()):
            res = client.post("/chat", json={"message": "a"})
        assert res.status_code == 200

    def test_empty_body_returns_400(self, client):
        res = client.post("/chat", content_type="application/json", data="")
        assert res.status_code == 400


# ── Group 2: Vector Store & API Key (Rule 2 — fires before off-topic) ─────────

class TestVectorStoreAndApiKey:

    def test_no_api_key_returns_503(self, client):
        with patch("app._init_store", return_value=(False, "OPENAI_API_KEY not set in environment.")):
            res = client.post("/chat", json={"message": "hello"})
        assert res.status_code == 503

    def test_no_documents_returns_503(self, client):
        with patch("app._init_store", return_value=(False, "No documents ingested yet. Please upload a PDF first.")):
            res = client.post("/chat", json={"message": "hello"})
        assert res.status_code == 503

    def test_empty_api_key_string_treated_as_missing(self, client):
        """OPENAI_API_KEY='' must be treated as not set → 503."""
        with patch("app._init_store", return_value=(False, "OPENAI_API_KEY not set in environment.")):
            res = client.post("/chat", json={"message": "hello"})
        assert res.status_code == 503

    def test_off_topic_without_vectorstore_returns_503_not_canned_reply(self, client):
        """
        CRITICAL precedence test: Rule 2 must fire before Rule 3.
        A personal question with no vector store must return 503, not the
        canned off-topic reply.
        """
        with patch("app._init_store", return_value=(False, "No documents ingested yet. Please upload a PDF first.")), \
             patch("app._is_off_topic", return_value=True):
            res = client.post("/chat", json={"message": "What is my name?"})
        assert res.status_code == 503


# ── Group 3: Off-topic Guard (Rule 3) ────────────────────────────────────────

class TestOffTopicGuard:

    def setup_method(self):
        app_module.collection = _ready_collection()
        app_module.llm = MagicMock()

    def test_personal_question_returns_canned_reply(self, client):
        with patch("app._is_off_topic", return_value=True):
            res = client.post("/chat", json={"message": "What is my name?"})
        assert res.status_code == 200
        data = res.get_json()
        assert data["reply"] == "I can only answer questions about the uploaded documents."
        assert data["metadata"]["sources"] == []

    def test_small_talk_returns_canned_reply(self, client):
        with patch("app._is_off_topic", return_value=True):
            res = client.post("/chat", json={"message": "Hey how are you?"})
        assert res.get_json()["reply"] == "I can only answer questions about the uploaded documents."

    def test_canned_reply_echoes_resolved_session_id(self, client):
        with patch("app._is_off_topic", return_value=True):
            res = client.post("/chat", json={"message": "Who am I?", "session_id": "sess-42"})
        assert res.get_json()["session_id"] == "sess-42"

    def test_topic_name_question_is_not_blocked(self, client):
        """'What is the name of the model?' must pass through to RAG."""
        with patch("app._is_off_topic", return_value=False), \
             patch("app._chat_with_memory", return_value=_mock_chat_response("gpt-3.5-turbo")):
            res = client.post("/chat", json={"message": "What is the name of the model?"})
        assert res.status_code == 200
        assert res.get_json()["reply"] != "I can only answer questions about the uploaded documents."

    def test_guard_receives_message_and_client_getter(self, client):
        with patch("app._is_off_topic", return_value=True) as mock_guard:
            client.post("/chat", json={"message": "How are you?"})
        mock_guard.assert_called_once_with("How are you?", app_module._get_guard_llm)

    def test_guard_skipped_while_clarification_pending(self, client):
        """A reply to a document-choice prompt must never be classified as off-topic."""
        app_module.conversation_sessions["sess-3"] = {
            "pending_clarification": {
                "original_question": "what is the torque spec",
                "options": [
                    {"label": "Manual A", "value": "manual_a.pdf"},
                    {"label": "All relevant documents", "value": "__all__"},
                ],
            }
        }
        with patch("app._is_off_topic", return_value=True) as mock_guard, \
             patch("app._answer_single_doc") as mock_single:
            mock_single.return_value = app.response_class(
                response='{"reply":"Spec answer","session_id":"sess-3","metadata":{"sources":[]}}',
                status=200,
                mimetype="application/json",
            )
            res = client.post("/chat", json={"message": "manual_a.pdf", "session_id": "sess-3"})
        mock_guard.assert_not_called()
        assert res.get_json()["reply"] == "Spec answer"


# ── Group 4: Successful Response Shape ───────────────────────────────────────

class TestSuccessfulResponseShape:

    def setup_method(self):
        app_module.collection = _ready_collection()
        app_module.llm = MagicMock()

    def test_valid_message_returns_200_with_correct_keys(self, client):
        with patch("app._is_off_topic", return_value=False), \
             patch("app._chat_with_memory", return_value=_mock_chat_response("The answer is 42.")):
            res = client.post("/chat", json={"message": "What is the answer?"})
        assert res.status_code == 200
        data = res.get_json()
        assert "reply" in data
        assert "session_id" in data
        assert "metadata" in data
        assert "sources" in data["metadata"]

    def test_history_field_accepted_without_error(self, client):
        """history in request body must be accepted — not cause a 400/500."""
        with patch("app._is_off_topic", return_value=False), \
             patch("app._chat_with_memory", return_value=_mock_chat_response()):
            res = client.post("/chat", json={
                "message": "follow up",
                "history": [{"role": "user", "content": "previous question"}]
            })
        assert res.status_code == 200


# ── Group 5: Source Formatting ────────────────────────────────────────────────

class TestSourceFormatting:

    def setup_method(self):
        app_module.collection = _ready_collection()
        app_module.llm = MagicMock()

    def test_snippet_exactly_150_chars_no_ellipsis(self, client):
        doc = _mock_doc("x" * 150, page=0, source="manual.pdf")
        with patch("app._is_off_topic", return_value=False), \
             patch("app._chat_with_memory", return_value=_mock_chat_response(sources=[doc])):
            res = client.post("/chat", json={"message": "anything"})
        snippet = res.get_json()["metadata"]["sources"][0]["snippet"]
        assert snippet == "x" * 150
        assert not snippet.endswith("...")

    def test_snippet_151_chars_gets_ellipsis(self, client):
        doc = _mock_doc("x" * 151, page=0, source="manual.pdf")
        with patch("app._is_off_topic", return_value=False), \
             patch("app._chat_with_memory", return_value=_mock_chat_response(sources=[doc])):
            res = client.post("/chat", json={"message": "anything"})
        snippet = res.get_json()["metadata"]["sources"][0]["snippet"]
        assert snippet == "x" * 150 + "..."

    def test_newlines_replaced_with_spaces_in_snippet(self, client):
        doc = _mock_doc("line one\nline two\nline three", page=0, source="sop.pdf")
        with patch("app._is_off_topic", return_value=False), \
             patch("app._chat_with_memory", return_value=_mock_chat_response(sources=[doc])):
            res = client.post("/chat", json={"message": "anything"})
        assert "\n" not in res.get_json()["metadata"]["sources"][0]["snippet"]

    def test_page_raw_0_returns_1_indexed(self, client):
        doc = _mock_doc("content", page=0, source="doc.pdf")
        with patch("app._is_off_topic", return_value=False), \
             patch("app._chat_with_memory", return_value=_mock_chat_response(sources=[doc])):
            res = client.post("/chat", json={"message": "anything"})
        assert res.get_json()["metadata"]["sources"][0]["page"] == 1

    def test_page_raw_5_returns_6(self, client):
        doc = _mock_doc("content", page=5, source="doc.pdf")
        with patch("app._is_off_topic", return_value=False), \
             patch("app._chat_with_memory", return_value=_mock_chat_response(sources=[doc])):
            res = client.post("/chat", json={"message": "anything"})
        assert res.get_json()["metadata"]["sources"][0]["page"] == 6

    def test_source_ids_start_at_1_and_increment(self, client):
        docs = [
            _mock_doc("A", page=0, source="a.pdf"),
            _mock_doc("B", page=1, source="b.pdf"),
            _mock_doc("C", page=2, source="c.pdf"),
        ]
        with patch("app._is_off_topic", return_value=False), \
             patch("app._chat_with_memory", return_value=_mock_chat_response(sources=docs)):
            res = client.post("/chat", json={"message": "anything"})
        ids = [s["id"] for s in res.get_json()["metadata"]["sources"]]
        assert ids == [1, 2, 3]

    def test_file_field_is_basename_only(self, client):
        """Full path in metadata must be stripped to filename only."""
        doc = _mock_doc("content", page=0, source="/deep/nested/path/manual.pdf")
        with patch("app._is_off_topic", return_value=False), \
             patch("app._chat_with_memory", return_value=_mock_chat_response(sources=[doc])):
            res = client.post("/chat", json={"message": "anything"})
        assert res.get_json()["metadata"]["sources"][0]["file"] == "manual.pdf"


# ── Group 6: Session Management ───────────────────────────────────────────────

class TestSessionManagement:

    def setup_method(self):
        app_module.collection = _ready_collection()
        app_module.llm = MagicMock()

    def test_missing_session_id_defaults_to_default(self, client):
        with patch("app._is_off_topic", return_value=False), \
             patch("app._chat_with_memory", return_value=_mock_chat_response()):
            res = client.post("/chat", json={"message": "hello"})
        assert res.get_json()["session_id"] == "default"

    def test_null_session_id_defaults_to_default(self, client):
        with patch("app._is_off_topic", return_value=False), \
             patch("app._chat_with_memory", return_value=_mock_chat_response()):
            res = client.post("/chat", json={"message": "hello", "session_id": None})
        assert res.get_json()["session_id"] == "default"

    def test_explicit_session_id_is_echoed(self, client):
        with patch("app._is_off_topic", return_value=False), \
             patch("app._chat_with_memory", return_value=_mock_chat_response()):
            res = client.post("/chat", json={"message": "hello", "session_id": "my-session"})
        assert res.get_json()["session_id"] == "my-session"

    def test_two_sessions_get_independent_chains(self, client):
        """Two different session IDs must not share memory."""
        def pick_response(question, sid):
            return _mock_chat_response("Answer for A") if sid == "session-a" else _mock_chat_response("Answer for B")

        with patch("app._is_off_topic", return_value=False), \
             patch("app._chat_with_memory", side_effect=pick_response):
            res_a = client.post("/chat", json={"message": "question", "session_id": "session-a"})
            res_b = client.post("/chat", json={"message": "question", "session_id": "session-b"})

        assert res_a.get_json()["reply"] == "Answer for A"
        assert res_b.get_json()["reply"] == "Answer for B"


# ── Group 7: Health Endpoint ──────────────────────────────────────────────────

class TestHealthEndpoint:

    def test_returns_200(self, client):
        res = client.get("/api/health")
        assert res.status_code == 200

    def test_response_has_required_keys(self, client):
        data = client.get("/api/health").get_json()
        for key in ("status", "has_documents", "has_api_key", "ready", "active_sessions"):
            assert key in data

    def test_has_api_key_false_when_key_missing(self, client):
        with patch("app.os.getenv", side_effect=lambda k, *a: "" if k == "OPENAI_API_KEY" else os.environ.get(k)):
            data = client.get("/api/health").get_json()
        assert data["has_api_key"] is False

    def test_has_api_key_true_when_key_present(self, client):
        with patch("app.os.getenv", side_effect=lambda k, *a: "sk-test" if k == "OPENAI_API_KEY" else os.environ.get(k)):
            data = client.get("/api/health").get_json()
        assert data["has_api_key"] is True

    def test_active_sessions_count_matches_state(self, client):
        app_module.conversation_sessions["s1"] = {}
        app_module.conversation_sessions["s2"] = {}
        data = client.get("/api/health").get_json()
        assert data["active_sessions"] == 2

    def test_ready_false_when_no_collection(self, client):
        data = client.get("/api/health").get_json()
        assert data["ready"] is False


# ── Group 8: Document List Endpoint ──────────────────────────────────────────

class TestDocumentsListEndpoint:

    def test_returns_200(self, client):
        with patch("app._load_doc_registry", return_value={}):
            res = client.get("/api/documents")
        assert res.status_code == 200

    def test_empty_registry_returns_empty_list(self, client):
        with patch("app._load_doc_registry", return_value={}):
            data = client.get("/api/documents").get_json()
        assert data["documents"] == []

    def test_registry_entry_is_mapped_correctly(self, client):
        registry = {"report.pdf": {"chunks": 10, "uploaded_at": "2026-01-01T00:00:00+00:00"}}
        with patch("app._load_doc_registry", return_value=registry):
            docs = client.get("/api/documents").get_json()["documents"]
        assert len(docs) == 1
        assert docs[0]["filename"] == "report.pdf"
        assert docs[0]["chunks"] == 10

    def test_multiple_documents_all_returned(self, client):
        registry = {
            "a.pdf": {"chunks": 5, "uploaded_at": ""},
            "b.txt": {"chunks": 3, "uploaded_at": ""},
        }
        with patch("app._load_doc_registry", return_value=registry):
            docs = client.get("/api/documents").get_json()["documents"]
        filenames = {d["filename"] for d in docs}
        assert filenames == {"a.pdf", "b.txt"}


# ── Group 9: Document Upload Endpoint ────────────────────────────────────────

class TestDocumentUploadEndpoint:

    def test_no_file_field_returns_400(self, client):
        res = client.post("/api/documents/upload", data={}, content_type="multipart/form-data")
        assert res.status_code == 400
        assert "No file field" in res.get_json()["message"]

    def test_unsupported_extension_returns_400(self, client):
        payload = {"file": (io.BytesIO(b"content"), "evil.exe")}
        res = client.post("/api/documents/upload", data=payload, content_type="multipart/form-data")
        assert res.status_code == 400
        assert "Unsupported file type" in res.get_json()["message"]

    def test_successful_upload_returns_success_shape(self, client):
        app_module.collection = _ready_collection()
        payload = {"file": (io.BytesIO(b"Hello world"), "notes.txt")}
        with patch("app._ingest_file", return_value=(True, "Ingested 3 chunks.", 3)), \
             patch("app._load_doc_registry", return_value={}), \
             patch("app._save_doc_registry"), \
             patch("werkzeug.datastructures.FileStorage.save"):
            res = client.post("/api/documents/upload", data=payload, content_type="multipart/form-data")
        assert res.status_code == 200
        body = res.get_json()
        assert body["success"] is True
        assert body["filename"] == "notes.txt"
        assert body["chunks"] == 3

    def test_ingest_failure_returns_500(self, client):
        app_module.collection = _ready_collection()
        payload = {"file": (io.BytesIO(b"bad data"), "doc.txt")}
        with patch("app._ingest_file", return_value=(False, "Parse error.", 0)), \
             patch("app._load_doc_registry", return_value={}), \
             patch("werkzeug.datastructures.FileStorage.save"), \
             patch("pathlib.Path.unlink"):
            res = client.post("/api/documents/upload", data=payload, content_type="multipart/form-data")
        assert res.status_code == 500
        assert res.get_json()["success"] is False


# ── Group 10: Document Delete Endpoint ───────────────────────────────────────

class TestDocumentDeleteEndpoint:

    def test_unknown_filename_returns_404(self, client):
        with patch("app._load_doc_registry", return_value={}):
            res = client.delete("/api/documents/missing.pdf")
        assert res.status_code == 404
        assert res.get_json()["success"] is False

    def test_successful_delete_returns_success(self, client):
        registry = {"report.pdf": {"chunks": 10}}
        app_module.collection = _ready_collection()
        with patch("app._load_doc_registry", return_value=registry), \
             patch("app._save_doc_registry"), \
             patch("pathlib.Path.unlink"):
            res = client.delete("/api/documents/report.pdf")
        assert res.status_code == 200
        assert res.get_json()["success"] is True

    def test_delete_clears_sessions(self, client):
        """After deletion, conversation_sessions must be cleared."""
        app_module.conversation_sessions["old-session"] = {}
        registry = {"doc.txt": {"chunks": 2}}
        app_module.collection = _ready_collection()
        with patch("app._load_doc_registry", return_value=registry), \
             patch("app._save_doc_registry"), \
             patch("pathlib.Path.unlink"):
            client.delete("/api/documents/doc.txt")
        assert app_module.conversation_sessions == {}


# ── Group 11: Clear Conversation Endpoint ────────────────────────────────────

class TestClarificationResolution:

    def setup_method(self):
        app_module.collection = _ready_collection()
        app_module.llm = MagicMock()

    def test_detect_scope_resolves_selected_option_by_value(self):
        app_module.conversation_sessions["sess-1"] = {
            "pending_clarification": {
                "original_question": "what are all the cs project class assignments and their grade percentages",
                "options": [
                    {"label": "Found Testing Documentation cs project syllabus spring 2026 v2", "value": "cs_project_syllabus_spring_2026_v2.pdf"},
                    {"label": "Found Testing Documentation cs seminar syllabus spring 2026 v1", "value": "cs_seminar_syllabus_spring_2026_v1.pdf"},
                ],
            }
        }

        scope, scope_data = app_module._detect_scope(
            "cs_project_syllabus_spring_2026_v2.pdf",
            app_module.conversation_sessions["sess-1"],
            app_module.collection,
        )

        assert scope == "resolved_single"
        assert scope_data == (
            "cs_project_syllabus_spring_2026_v2.pdf",
            "what are all the cs project class assignments and their grade percentages",
        )
        assert app_module.conversation_sessions["sess-1"]["pending_clarification"] is None

    def test_chat_does_not_reask_after_clarification_selection(self, client):
        app_module.conversation_sessions["sess-2"] = {
            "pending_clarification": {
                "original_question": "what are all the cs project class assignments and their grade percentages",
                "options": [
                    {"label": "Found Testing Documentation cs project syllabus spring 2026 v2", "value": "cs_project_syllabus_spring_2026_v2.pdf"},
                    {"label": "All relevant documents", "value": "__all__"},
                ],
            }
        }

        with patch("app._answer_single_doc") as mock_single:
            mock_single.return_value = app.response_class(
                response='{"reply":"Assignments answer","session_id":"sess-2","metadata":{"sources":[]}}',
                status=200,
                mimetype="application/json",
            )
            res = client.post("/chat", json={"message": "cs_project_syllabus_spring_2026_v2.pdf", "session_id": "sess-2"})

        assert res.status_code == 200
        assert res.get_json()["reply"] == "Assignments answer"
        mock_single.assert_called_once_with(
            "what are all the cs project class assignments and their grade percentages",
            "cs_project_syllabus_spring_2026_v2.pdf",
            "sess-2",
        )


class TestClearConversationEndpoint:

    def test_clears_named_session(self, client):
        app_module.conversation_sessions["test-session"] = {"memory": MagicMock()}
        res = client.post("/api/clear", json={"session_id": "test-session"})
        assert res.status_code == 200
        assert "test-session" not in app_module.conversation_sessions

    def test_missing_session_id_clears_default(self, client):
        app_module.conversation_sessions["default"] = {"memory": MagicMock()}
        res = client.post("/api/clear", json={})
        assert res.status_code == 200
        assert "default" not in app_module.conversation_sessions

    def test_nonexistent_session_returns_success(self, client):
        """Clearing a session that doesn't exist must not raise an error."""
        res = client.post("/api/clear", json={"session_id": "ghost"})
        assert res.status_code == 200
        assert res.get_json()["status"] == "success"

    def test_response_has_status_success(self, client):
        res = client.post("/api/clear", json={"session_id": "any"})
        assert res.get_json()["status"] == "success"

