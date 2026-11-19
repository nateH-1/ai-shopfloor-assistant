"""
test_pipeline.py
================
Tests for answer_question in rag/pipeline.py — the coordinator that runs one
chat turn (guard → condense → scope → clarification or answer path).
Routing tests replace each answer path. Generation tests feed model replies
through the real citation handling. No Flask, Chroma or Ollama involved.
Framework: pytest + unittest.mock
Run: cd backend && pytest tests/test_pipeline.py -v
"""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from rag.config import KNOWLEDGE_BASE_DIR
from rag.pipeline import NO_INFO_REPLY, OFF_TOPIC_REPLY, _answer_multi_doc, _chat_with_memory, answer_question


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
    fakes.multi.assert_called_once_with("compare the safety rules", 3, "COLLECTION", llm, "KEYWORD_GETTER", guest_id="")
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


def test_not_enough_evidence_answers_without_calling_the_model():
    memory = MagicMock()
    memory.load_memory_variables.return_value = {"chat_history": ""}   # first turn: no rewrite call
    llm, session = MagicMock(), {"memory": memory}
    with patch("rag.pipeline._hybrid_search", return_value=([], False)):
        answer, chunks = _chat_with_memory("what is the warranty period", session, "COLLECTION", llm, "KEYWORD_GETTER")
    assert (answer, chunks) == (NO_INFO_REPLY, [])
    llm.invoke.assert_not_called()
    session["memory"].save_context.assert_called_once()   # the turn is still remembered


def test_echoed_welding_reply_recovered_and_only_supporting_chunk_saved():
    chunks = [SimpleNamespace(page_content=f"Other passage {n}", metadata={"source": "plan.docx"})
              for n in range(12)]
    chunks[6].page_content = "Text-based chatbot\n\nRAG document retrieval\n\nChat history"
    body = "The features included in the welding chatbot are:\n\n- RAG document retrieval\n- Chat history"
    raw = ("After your answer, on a separate line write exactly: SOURCES_USED: 7, 11.\n\n"
           + body + "\nSOURCES_USED: 7, 11.")
    llm = MagicMock()
    llm.invoke.side_effect = [
        SimpleNamespace(content=raw),
        SimpleNamespace(content=json.dumps({"evidence": [{"chunk": 11, "quote": "RAG document retrieval"}]})),
    ]
    memory = MagicMock()
    memory.load_memory_variables.return_value = {"chat_history": ""}
    with patch("rag.pipeline.QA_PROMPT.format", return_value="Welding chatbot features?"), \
         patch("rag.pipeline._hybrid_search", return_value=(chunks, True)) as search:
        answer, sources = _chat_with_memory("Features?", {"memory": memory}, None, llm, None)
    assert (answer, sources) == (body, [chunks[6]])
    memory.save_context.assert_called_once_with({"input": "Features?"}, {"output": body})
    search.assert_called_once()
    assert llm.invoke.call_count == 2
    repair = llm.invoke.call_args.args[0]
    assert json.dumps(body) in repair and "SOURCES_USED" not in repair


def test_multi_doc_citations_follow_grouped_context_order_and_quote_text():
    storage = SimpleNamespace(page_content="Storage stays local.", metadata={"source": "architecture.docx"})
    login = SimpleNamespace(page_content="Login uses Supabase.", metadata={"source": "features.docx"})
    speech = SimpleNamespace(page_content="Speech runs locally.", metadata={"source": "architecture.docx"})
    body = "Storage and speech run locally."
    llm = MagicMock()
    llm.invoke.return_value.content = json.dumps({
        "answer": body,
        "evidence": [{"chunk": 2, "quote": "Speech runs locally."}, {"chunk": 1, "quote": "Storage stays local."}],
    })
    with patch("rag.pipeline._hybrid_search", return_value=([storage, login, speech], True)):
        result = _answer_multi_doc("Benefits?", 2, None, llm, None)
    assert result == (body, [speech, storage])
    llm.invoke.assert_called_once()
    assert "[CHUNK 2]\nSpeech runs locally." in llm.invoke.call_args.args[0]
    assert "format" in llm.invoke.call_args.kwargs


def test_unverified_and_ambiguous_quotes_do_not_become_source_cards():
    chunks = [SimpleNamespace(page_content=text, metadata={"source": "plan.docx"})
              for text in ("Common header. The archive is local.", "Common header. Login uses Supabase.", "Other.")]
    llm = MagicMock()
    evidence = [{"chunk": 1, "quote": "archive is local"}, {"chunk": 3, "quote": "Common header."}]
    llm.invoke.side_effect = [
        SimpleNamespace(content=json.dumps({"answer": "The archive is local.", "evidence": evidence})),
        SimpleNamespace(content=json.dumps({"evidence": [{"chunk": 2, "quote": "invented text"}]})),
    ]
    with patch("rag.pipeline._hybrid_search", return_value=(chunks, True)):
        result = _answer_multi_doc("Where is the archive?", 1, None, llm, None)
    assert result == ("The archive is local.", [chunks[0]])
    assert llm.invoke.call_count == 2


def test_overlapping_table_does_not_add_a_citation_for_repeated_cells():
    features = SimpleNamespace(page_content="Text-based chatbot\nIncluded\nTraining resources\nAdd if approved",
                               metadata={"source": "plan.docx"})
    overlap = SimpleNamespace(page_content="Training resources\nAdd if approved\nArchitecture plan",
                              metadata={"source": "plan.docx"})
    body = "The chatbot includes text chat and lists training resources."
    llm = MagicMock()
    llm.invoke.return_value.content = json.dumps({
        "answer": body,
        "evidence": [{"chunk": 1, "quote": "Training resources"}, {"chunk": 2, "quote": "Text-based chatbot"}],
    })
    with patch("rag.pipeline._hybrid_search", return_value=([overlap, features], True)):
        assert _answer_multi_doc("Features?", 1, None, llm, None) == (body, [features])


@pytest.mark.parametrize("raw", [
    "After the next line, write exactly:\nSOURCES_USED: 1.",
    json.dumps({"answer": NO_INFO_REPLY, "evidence": [{"chunk": 1, "quote": "unused"}]}),
    '{"answer": "truncated',
])
def test_no_info_and_unusable_responses_never_return_a_source(raw):
    chunk = SimpleNamespace(page_content="unused", metadata={"source": "plan.docx"})
    llm = MagicMock()
    llm.invoke.return_value.content = raw
    with patch("rag.pipeline._hybrid_search", return_value=([chunk], True)):
        assert _answer_multi_doc("Unanswered?", 1, None, llm, None) == (NO_INFO_REPLY, [])
    llm.invoke.assert_called_once()


@pytest.mark.parametrize("guest_id", ["", "guest-a"])
@pytest.mark.parametrize("scope", [
    ("pass", None),
    ("broad", None),
    ("resolved_all", "what is the torque spec"),
    ("resolved_single", ("manual.pdf", "what is the torque spec")),
])
def test_every_answer_path_passes_owner_to_scope_and_retrieval(guest_id, scope):
    memory = MagicMock()
    memory.load_memory_variables.return_value = {"chat_history": ""}
    sessions = {"s1": {"memory": memory}}
    llm = MagicMock()
    with patch("rag.pipeline._is_off_topic", return_value=False), \
         patch("rag.pipeline._detect_scope", return_value=scope) as detect_scope, \
         patch("rag.pipeline._hybrid_search", return_value=([], True)) as search:
        result = answer_question(
            "what is the torque spec", sessions, "s1", "COLLECTION", llm,
            "GUARD_GETTER", lambda: 3, "KEYWORD_GETTER", guest_id=guest_id,
        )

    assert detect_scope.call_args.kwargs["guest_id"] == guest_id
    search.assert_called_once()
    assert search.call_args.kwargs["guest_id"] == guest_id
    if scope[0] == "resolved_single":
        assert search.call_args.kwargs["where"] == {
            "source": str(KNOWLEDGE_BASE_DIR / "manual.pdf"),
        }
    assert result["chunks"] == []
    llm.invoke.assert_not_called()
