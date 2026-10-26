"""Real local Chroma integration tests; no OpenAI calls or production data."""
import importlib
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest
from flask import Flask, jsonify

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

for module_name in [
    # Chat endpoint tests may have already imported feedback.py while Chroma was
    # mocked by backend/conftest.py. Remove that cached module as well so this
    # integration suite exercises a real temporary Chroma database.
    "feedback",
    "chromadb",
    "chromadb.utils",
    "chromadb.utils.embedding_functions",
]:
    sys.modules.pop(module_name, None)

importlib.import_module("chromadb")
from feedback import FeedbackStore, register_feedback


@pytest.fixture
def system(tmp_path):
    app = Flask(__name__)
    app.config["TESTING"] = True
    register_feedback(app, tmp_path / "chroma", "test-model")

    @app.post("/chat")
    def chat():
        return jsonify(reply="Use the SOP.", session_id="test-session",
                       metadata={"sources": [{"file": "sop.pdf", "page": 2}]})

    owner = str(uuid4())
    headers = {"X-Feedback-Owner": owner}
    client = app.test_client()
    answer = client.post("/chat", json={"message": "How?"}, headers=headers).get_json()
    return app, client, headers, answer["message_id"], tmp_path / "chroma"


def test_unrated_answer_is_not_persisted(system):
    app, client, headers, mid, _ = system
    row = app.extensions["feedback_store"].collection.get(ids=[mid], include=["documents"])
    assert row["documents"] == []
    assert client.get(f"/api/feedback/{mid}", headers=headers).get_json() == {"feedback": None}
    assert app.extensions["feedback_store"].collection.count() == 0


def test_change_vote_and_reload_from_disk(system):
    app, client, headers, mid, path = system
    url = f"/api/feedback/{mid}"
    assert client.put(url, headers=headers, json={"vote": "helpful"}).status_code == 200
    data = {"vote": "not_helpful", "reason": "incorrect", "comment": "  Missing step.  "}
    response = client.put(url, headers=headers, json=data)
    assert response.status_code == 200
    assert response.get_json()["feedback"]["comment"] == "Missing step."
    row = app.extensions["feedback_store"].collection.get(ids=[mid], include=["documents"])
    assert '"answer": "Use the SOP."' in row["documents"][0]
    assert '"model": "test-model"' in row["documents"][0]
    reopened = FeedbackStore(path)
    saved = reopened.get(mid, headers["X-Feedback-Owner"])
    assert saved["vote"] == "not_helpful"
    assert saved["reason"] == "incorrect"
    assert reopened.collection.count() == 1
    original = reopened.collection.get(ids=[mid], include=["documents"])["documents"][0]
    assert '"question": "How?"' in original


def test_negative_feedback_becomes_future_style_guidance(system):
    app, client, headers, mid, _ = system
    response = client.put(
        f"/api/feedback/{mid}",
        headers=headers,
        json={
            "vote": "not_helpful",
            "reason": "unclear",
            "comment": "Use shorter numbered steps next time.",
        },
    )
    assert response.status_code == 200

    guidance = app.extensions["feedback_store"].style_guidance(headers["X-Feedback-Owner"])
    assert "Use clearer wording" in guidance
    assert "Use shorter numbered steps next time." in guidance
    assert "Do not treat feedback as a source of facts" in guidance


def test_duplicate_and_concurrent_votes_do_not_add_rows(system):
    app, _, headers, mid, _ = system
    store = app.extensions["feedback_store"]
    owner = headers["X-Feedback-Owner"]
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: store.save(mid, owner, "helpful", "", ""), range(12)))
    assert store.collection.count() == 1
    assert store.get(mid, owner)["vote"] == "helpful"


def test_remove_erases_saved_feedback_record(system):
    app, client, headers, mid, _ = system
    url = f"/api/feedback/{mid}"
    client.put(url, headers=headers, json={"vote": "not_helpful", "comment": "Remove me"})
    assert client.delete(url, headers=headers).get_json() == {"feedback": None}
    assert client.get(url, headers=headers).status_code == 404
    assert app.extensions["feedback_store"].collection.get(ids=[mid])["ids"] == []


@pytest.mark.parametrize("method", ["get", "put", "delete"])
def test_different_browser_cannot_access_feedback(system, method):
    _, client, _, mid, _ = system
    response = getattr(client, method)(
        f"/api/feedback/{mid}",
        headers={"X-Feedback-Owner": str(uuid4())},
        json={"vote": "helpful"} if method == "put" else None,
    )
    assert response.status_code == 404


@pytest.mark.parametrize("body", [
    None, [], {"vote": []}, {"vote": "excellent"}, {"vote": "helpful", "reason": "incorrect"},
    {"vote": "not_helpful", "reason": "unknown"}, {"vote": "helpful", "comment": 1},
    {"vote": "helpful", "comment": "x" * 2001},
    {"vote": "helpful", "answer": "forged"}, {"vote": "helpful", "owner": "forged"},
])
def test_invalid_feedback_rejected(system, body):
    app, client, headers, mid, _ = system
    assert client.put(f"/api/feedback/{mid}", headers=headers, json=body).status_code == 400
    assert app.extensions["feedback_store"].get(mid, headers["X-Feedback-Owner"]) is None


def test_identity_ids_and_payload_limits(system):
    _, client, headers, mid, _ = system
    assert client.get(f"/api/feedback/{mid}").status_code == 401
    assert client.get("/api/feedback/not-an-id", headers=headers).status_code == 404
    assert client.put(f"/api/feedback/{mid}", headers=headers,
                      data="x" * 17000, content_type="application/json").status_code == 413


def test_storage_failure_does_not_break_chat(system, monkeypatch):
    app, client, headers, _, _ = system
    def fail(*args, **kwargs):
        raise OSError("disk unavailable")
    monkeypatch.setattr(app.extensions["feedback_store"], "prepare_answer", fail)
    response = client.post("/chat", json={"message": "How?"}, headers=headers)
    assert response.status_code == 200
    assert response.get_json()["reply"] == "Use the SOP."
    assert response.get_json()["feedback_unavailable"] is True


def test_storage_failure_returns_retryable_error(system, monkeypatch):
    app, client, headers, mid, _ = system
    def fail(*args, **kwargs):
        raise OSError("private filesystem detail")
    monkeypatch.setattr(app.extensions["feedback_store"], "get", fail)
    response = client.get(f"/api/feedback/{mid}", headers=headers)
    assert response.status_code == 503
    assert "private filesystem detail" not in response.get_data(as_text=True)


def test_missing_owner_keeps_legacy_chat_compatible(system):
    _, client, _, _, _ = system
    response = client.post("/chat", json={"message": "How?"}).get_json()
    assert "message_id" not in response
    assert response["reply"] == "Use the SOP."
