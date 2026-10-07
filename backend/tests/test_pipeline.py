"""
test_pipeline.py
================
Tests for answer_question in rag/pipeline.py — the coordinator that runs one
chat turn (guard → condense → scope → clarification or answer path).
The guard, scope detection and answer paths are replaced with fakes so each
test checks only the routing decision. No Flask, Chroma or OpenAI involved.
Framework: pytest + unittest.mock
Run: cd backend && pytest tests/test_pipeline.py -v
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from rag.pipeline import OFF_TOPIC_REPLY, answer_question


def _ask(message="what is the torque spec", sessions=None, scope=("pass", None),
         off_topic=False, llm=None):
    """Run answer_question with faked helpers. Returns (result, sessions, fakes)."""
    sessions = {} if sessions is None else sessions
    fakes = SimpleNamespace(get_num_docs=MagicMock(return_value=3))
    with patch("rag.pipeline._is_off_topic", return_value=off_topic) as fakes.guard, \
         patch("rag.pipeline._detect_scope", return_value=scope) as fakes.scope, \
         patch("rag.pipeline._answer_multi_doc", return_value=("multi answer", ["m"])) as fakes.multi, \
         patch("rag.pipeline._chat_with_memory", return_value=("memory answer", ["c"])) as fakes.memory:
        result = answer_question(message, sessions, "s1", "COLLECTION", llm or MagicMock(),
                                 "GUARD_GETTER", fakes.get_num_docs, "KEYWORD_GETTER")
    return result, sessions, fakes


def test_off_topic_is_refused_before_any_search():
    result, sessions, fakes = _ask("tell me a joke", off_topic=True)
    assert result == {"reply": OFF_TOPIC_REPLY, "chunks": [], "clarification": None}
    fakes.scope.assert_not_called()
    assert sessions == {}   # a refused message does not create a session


def test_ambiguous_question_asks_and_remembers_it():
    result, sessions, _ = _ask(scope=("ambiguous", ["a.pdf", "b.pdf"]))
    assert result["chunks"] == []
    assert [o["value"] for o in result["clarification"]["options"]] == ["a.pdf", "b.pdf", "__all__"]
    assert sessions["s1"]["pending_clarification"]["original_question"] == "what is the torque spec"


def test_broad_question_uses_multi_doc_path():
    llm = MagicMock()
    result, _, fakes = _ask("compare the safety rules", scope=("broad", None), llm=llm)
    fakes.multi.assert_called_once_with("compare the safety rules", 3, "COLLECTION", llm, "KEYWORD_GETTER")
    assert result == {"reply": "multi answer", "chunks": ["m"], "clarification": None}


def test_document_count_only_read_for_multi_doc():
    _, _, fakes = _ask(scope=("pass", None))
    fakes.get_num_docs.assert_not_called()


def test_default_question_uses_memory_path_with_new_session():
    result, sessions, fakes = _ask()
    assert fakes.memory.call_args.args[1] is sessions["s1"]
    assert result == {"reply": "memory answer", "chunks": ["c"], "clarification": None}


def test_follow_up_is_condensed_for_scope_only():
    # Known issue #3: scope sees the condensed question, while the memory path
    # receives the original message and condenses it again itself.
    memory = MagicMock()
    memory.load_memory_variables.return_value = {"chat_history": "Human: hi\nAI: hello"}
    llm = MagicMock()
    llm.invoke.return_value = SimpleNamespace(content="What is the torque spec of the press?")
    _, _, fakes = _ask("and the press?", sessions={"s1": {"memory": memory}}, llm=llm)
    assert fakes.scope.call_args.args[0] == "What is the torque spec of the press?"
    assert fakes.memory.call_args.args[0] == "and the press?"
