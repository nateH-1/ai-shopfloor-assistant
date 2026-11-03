"""Verify the real Flask rewrite wiring stays outside normal conversation state."""
from unittest.mock import MagicMock, patch
from uuid import uuid4

import app as backend


def test_rewrite_route_uses_snapshot_without_mutating_chat_session(monkeypatch):
    snapshot = {"question": "Original question", "answer": "Original answer"}
    feedback = {"vote": "not_helpful", "reason": "unclear", "comment": "Number the steps"}
    store = MagicMock()
    store.rewrite_input.return_value = (snapshot, feedback)
    store.prepare_answer.return_value = str(uuid4())
    monkeypatch.setitem(backend.app.extensions, "feedback_store", store)
    collection, llm = MagicMock(), MagicMock()
    monkeypatch.setattr(backend, "collection", collection)
    monkeypatch.setattr(backend, "llm", llm)
    sessions = {"newer": {"memory": "newer conversation"}}
    monkeypatch.setattr(backend, "conversation_sessions", sessions)
    owner, mid = str(uuid4()), str(uuid4())
    with patch("feedback_rewrite.rewrite_answer", return_value=("Rewritten", [])) as rewrite, \
         patch.object(backend, "answer_question") as chat_pipeline:
        response = backend.app.test_client().post(
            f"/api/feedback/{mid}", headers={"X-Feedback-Owner": owner},
        )
    assert response.status_code == 200
    assert response.get_json()["reply"] == "Rewritten"
    store.rewrite_input.assert_called_once_with(mid, owner)
    rewrite.assert_called_once_with(snapshot, feedback, collection, llm, backend._get_keyword_index)
    chat_pipeline.assert_not_called()
    assert backend.conversation_sessions == {"newer": {"memory": "newer conversation"}}
    store.prepare_answer.assert_called_once()
    assert store.prepare_answer.call_args.args[1] == "Original question"
