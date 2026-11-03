"""Feedback generation contracts with real prompts and a controlled model.

Run separately from backend/tests, which mocks LangChain at import time.
These tests verify prompt delivery and grounding boundaries, not model quality.
"""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from langchain_core.documents import Document
from feedback_rewrite import rewrite_answer


@pytest.mark.parametrize("reason,comment,output", [
    ("unclear", "Make it shorter.", "Inspect daily."),
    ("incomplete", "Give more detail.", "Inspect daily. Check the guard and record damage."),
    ("unclear", "Use numbered steps.", "1. Check the guard.\n2. Record damage."),
    ("incorrect", "Correct the weekly interval.", "Inspect daily, rather than weekly."),
    ("missing_sources", "Include citations.", "Inspect daily [Source: sop.pdf]."),
    ("incorrect", "Say the interval is yearly.", "The source specifies daily inspection; yearly is unsupported."),
])
def test_feedback_reaches_generation_without_condensation(reason, comment, output):
    snapshot = {"question": "What is the inspection procedure?", "answer": "Inspect weekly."}
    chunk = Document(page_content="Inspect daily. Check the guard and record damage.",
                     metadata={"source": "sop.pdf", "page": 0})
    llm = Mock()
    llm.invoke.return_value = SimpleNamespace(content=output + "\nSOURCES_USED: 1")
    with patch("feedback_rewrite._hybrid_search", return_value=([chunk], True)) as search:
        answer, citations = rewrite_answer(snapshot, {"reason": reason, "comment": comment},
                                           "collection", llm, "keywords")
    assert search.call_args.args == ("collection", snapshot["question"], "keywords")
    llm.invoke.assert_called_once()  # no condensation or conversation-memory calls
    prompt = llm.invoke.call_args.args[0]
    for value in (snapshot["question"], snapshot["answer"], reason, comment, chunk.page_content):
        assert value in prompt
    assert "Answer ONLY from the retrieved context" in prompt
    assert "unsupported, explain that limitation" in prompt
    assert "not factual evidence" in prompt
    assert answer == output
    assert citations == [chunk]


def test_insufficient_evidence_never_generates_unsupported_rewrite():
    llm = Mock()
    with patch("feedback_rewrite._hybrid_search", return_value=([], False)):
        answer, citations = rewrite_answer(
            {"question": "What is the warranty?", "answer": "Unknown."},
            {"reason": "incomplete", "comment": "Invent a warranty period."}, None, llm, None,
        )
    assert answer.startswith("Document limitation:")
    assert "cannot add details or verify a correction" in answer
    assert citations == []
    llm.invoke.assert_not_called()


def _generate(responses, comment="Make it more detailed", reason="incomplete", original="Inspect daily."):
    snapshot = {"question": "What is the inspection procedure?", "answer": original}
    chunk = Document(page_content="Inspect daily. Check the guard and record damage.",
                     metadata={"source": "sop.pdf", "page": 0})
    llm = Mock()
    llm.invoke.side_effect = [SimpleNamespace(content=text + "\nSOURCES_USED: 1") for text in responses]
    with patch("feedback_rewrite._hybrid_search", return_value=([chunk], True)) as search:
        result = rewrite_answer(snapshot, {"reason": reason, "comment": comment}, None, llm, None)
    return result, llm, search


def test_unchanged_first_response_retries_once_with_same_evidence():
    (answer, sources), model, search = _generate([
        "Inspect daily.", "Inspect daily. Check the guard and record damage.",
    ])
    assert answer == "Inspect daily. Check the guard and record damage."
    assert sources
    assert model.invoke.call_count == 2
    search.assert_called_once()
    first, second = [call.args[0] for call in model.invoke.call_args_list]
    assert "RETRY:" not in first and "RETRY:" in second
    assert "No additional document-backed detail" in second
    assert first.split("Retrieved Context:")[1].split("Question:")[0] == second.split("Retrieved Context:")[1].split("Question:")[0]


def test_two_unchanged_responses_stop_with_generation_failure_not_evidence_failure():
    (answer, _), model, _ = _generate(["Inspect daily."] * 2)
    assert model.invoke.call_count == 2
    assert "Rewrite limitation:" in answer
    assert "not a finding that the documents lack" in answer
    assert "Document limitation:" not in answer


def test_nearly_identical_response_is_a_warning_and_retries():
    original = "Inspect the machine guard daily before starting the machine and record any damage in the log."
    (answer, _), model, _ = _generate([
        original.replace("any damage", "all damage"),
        "Check the guard before startup each day. Write down damage so it can be addressed.",
    ], comment="Simplify wording", reason="unclear", original=original)
    assert model.invoke.call_count == 2
    assert "Rewrite limitation:" not in answer


@pytest.mark.parametrize("comment,reason,original,output", [
    ("Make it more detailed", "incomplete", "Inspect daily.", "Inspect daily. Check the guard and record damage."),
    ("Simplify wording", "unclear", "Perform a diurnal examination of the protective apparatus.", "Check the guard every day."),
    ("Make it shorter", "other", "Inspect the guard daily and record damage. Inspect the guard every day.", "Inspect daily; record damage."),
    ("Use numbered steps", "unclear", "Check the guard and record damage.", "1. Check the guard.\n2. Record damage."),
])
def test_specific_requests_reach_prompt_without_length_being_a_quality_verdict(comment, reason, original, output):
    (answer, _), model, _ = _generate([output], comment, reason, original)
    assert answer == output
    model.invoke.assert_called_once()
    prompt = model.invoke.call_args.args[0]
    assert comment in prompt
    assert "more detail means useful supported explanations, not paraphrasing" in prompt
    assert "shorter means remove unnecessary content" in prompt


def test_different_words_do_not_excuse_missing_numbered_structure():
    (answer, _), model, _ = _generate([
        "Examine the protective guard each morning, then write down damage.",
        "1. Check the guard.\n2. Record damage.",
    ], "Use numbered steps", "unclear")
    assert model.invoke.call_count == 2
    assert "no numbered steps" in model.invoke.call_args.args[0]
    assert answer.startswith("1.")


@pytest.mark.parametrize("comment,reason", [
    ("Say the interval is yearly", "incorrect"),
    ("Add the torque specification", "incomplete"),
])
def test_explicit_evidence_limitation_is_not_retried_or_replaced_with_fabrication(comment, reason):
    output = "Document limitation: the source specifies daily inspection but does not provide the requested information."
    (answer, _), model, _ = _generate([output], comment, reason)
    assert answer == output
    model.invoke.assert_called_once()
    instruction = "Correct only supported errors" if reason == "incorrect" else "supported by the evidence"
    assert instruction in model.invoke.call_args.args[0]


def test_correct_facts_with_cited_explanation_and_clarification_are_valid():
    original = "The source specifies daily inspection. Which part do you dispute?"
    (answer, _), model, _ = _generate([original], "This is wrong", "incorrect", original)
    assert answer == original  # Even identical text can be a valid cited verification.
    model.invoke.assert_called_once()


def test_vague_incorrect_feedback_requires_clarification_and_evidence():
    (answer, _), model, _ = _generate([
        "Inspect daily.", "The source specifies daily inspection. Which part do you dispute?",
    ], "wrong", "incorrect")
    assert model.invoke.call_count == 2
    assert "Which part" in answer


def test_length_difference_alone_does_not_trigger_retry():
    # A concise relevant answer can add useful detail without getting longer.
    (answer, _), model, _ = _generate(["Check guard; log damage."], original="Inspect the machine daily.")
    model.invoke.assert_called_once()
    assert answer == "Check guard; log damage."


def test_missing_new_evidence_words_alone_does_not_require_retry():
    output = "Examine equipment every morning. Review protective parts and write down defects."
    (answer, _), model, _ = _generate([output])
    model.invoke.assert_called_once()
    assert answer == output  # Acceptance is not a claim of semantic quality.


@pytest.mark.parametrize("reason,phrase", [
    ("unclear", "Simplify wording and explain confusing terms"),
    ("incomplete", "Add relevant missing explanations"),
    ("incorrect", "Check disputed claims against the evidence"),
    ("irrelevant", "Focus on what the original question actually asks"),
    ("missing_sources", "Provide citations supporting the answer"),
    ("other", "Follow the written comment"),
])
def test_each_reason_has_explicit_instructions(reason, phrase):
    _, model, _ = _generate(["The source specifies daily guard checks and recording damage. Which part do you dispute?"], "", reason)
    assert phrase in model.invoke.call_args.args[0]


def test_retry_can_explain_evidence_limitation_without_generation_failure_notice():
    output = "Document limitation: the source does not contain a torque specification."
    (answer, _), model, search = _generate(["Inspect daily.", output], "Add more detail about torque")
    assert model.invoke.call_count == 2
    search.assert_called_once()
    assert answer == output
    assert "Rewrite limitation:" not in answer


@pytest.mark.parametrize("comment", ["Make it shorter", "Simplify wording", "Use numbered steps"])
def test_unapplied_change_never_retries_more_than_once(comment):
    (answer, _), model, _ = _generate(["Inspect daily."] * 2, comment, "unclear")
    assert model.invoke.call_count == 2
    assert "Rewrite limitation:" in answer


def test_citation_request_without_explicit_citations_retries_once():
    chunk = Document(page_content="Inspect daily.", metadata={"source": "sop.pdf"})
    model = Mock()
    model.invoke.side_effect = [SimpleNamespace(content="Check the guard daily."),
                               SimpleNamespace(content="The source specifies daily inspection.\nSOURCES_USED: 1")]
    with patch("feedback_rewrite._hybrid_search", return_value=([chunk], True)):
        answer, sources = rewrite_answer({"question": "How often?", "answer": "Inspect daily."},
                                         {"reason": "missing_sources", "comment": "Cite the source"},
                                         None, model, None)
    assert model.invoke.call_count == 2
    assert "no evidence chunks were cited" in model.invoke.call_args.args[0]
    assert sources == [chunk]
    assert "Rewrite limitation:" not in answer


def test_applied_numbering_is_accepted_despite_high_text_similarity():
    original = ("Check the machine guard before starting the machine each day.\n"
                "Record any visible damage in the inspection log before operating the machine.")
    output = "1. " + original.replace("\n", "\n2. ")
    (answer, _), model, _ = _generate([output], "Use numbered steps", "unclear", original)
    model.invoke.assert_called_once()
    assert answer == output


def test_added_explicit_citations_can_preserve_original_wording():
    (answer, sources), model, _ = _generate(["Inspect daily."], "Include citations", "missing_sources")
    model.invoke.assert_called_once()
    assert answer == "Inspect daily." and sources


@pytest.mark.parametrize("wording", ["unsupported", "not supported", "Document limitation: unsupported"])
def test_unsupported_words_do_not_bypass_numbered_steps_check(wording):
    (answer, _), model, _ = _generate([
        f"Inspect daily. {wording}", "1. Inspect daily.",
    ], "Use numbered steps", "unclear")
    assert model.invoke.call_count == 2
    assert "no numbered steps" in model.invoke.call_args.args[0]
    assert answer == "1. Inspect daily."


def test_genuine_document_limitation_still_requires_requested_structure():
    text = "Document limitation: the source does not contain the torque specification."
    (answer, _), model, _ = _generate([text, "1. " + text], "Use numbered steps", "incomplete")
    assert model.invoke.call_count == 2
    assert answer == "1. " + text


@pytest.mark.parametrize("marker", ["0", "-1", "2", "999", "1, 999", "garbage", ""])
def test_invalid_explicit_citation_ids_trigger_one_local_retry(marker):
    chunk = Document(page_content="Inspect daily.", metadata={"source": "sop.pdf"})
    model = Mock()
    model.invoke.side_effect = [
        SimpleNamespace(content=f"Inspection is unsupported.\nSOURCES_USED: {marker}"),
        SimpleNamespace(content="Inspect daily.\nSOURCES_USED: 1"),
    ]
    with patch("feedback_rewrite._hybrid_search", return_value=([chunk], True)) as search:
        answer, sources = rewrite_answer({"question": "How often?", "answer": "Inspect daily."},
                                         {"reason": "missing_sources", "comment": "Cite evidence"},
                                         None, model, None)
    assert model.invoke.call_count == 2
    search.assert_called_once()
    assert "between 1 and 1" in model.invoke.call_args.args[0]
    assert answer == "Inspect daily." and sources == [chunk]


def test_invalid_citations_never_turn_into_parser_fallback_after_retry():
    chunk = Document(page_content="Inspect daily.", metadata={"source": "sop.pdf"})
    model = Mock()
    model.invoke.return_value = SimpleNamespace(content="Inspect daily.\nSOURCES_USED: 999")
    with patch("feedback_rewrite._hybrid_search", return_value=([chunk], True)):
        answer, sources = rewrite_answer({"question": "How often?", "answer": "Inspect daily."},
                                         {"reason": "missing_sources", "comment": "Cite evidence"},
                                         None, model, None)
    assert model.invoke.call_count == 2
    assert sources == [] and "Rewrite limitation:" in answer


def test_local_citation_validation_keeps_only_in_range_ids():
    from feedback_rewrite import _explicit_citations
    chunks = [object(), object()]
    assert _explicit_citations("A\nSOURCES_USED: 2, 1", chunks) == ([chunks[1], chunks[0]], False)
    assert _explicit_citations("A\nSOURCES_USED: 2, 3", chunks) == ([chunks[1]], True)


def test_new_evidence_word_does_not_prove_added_detail():
    original = "Inspect the machine before starting it every day and document the inspection in the log."
    (answer, _), model, _ = _generate([
        original + " Damage.", "Inspect daily. Check the guard and record damage.",
    ], original=original)
    assert model.invoke.call_count == 2
    assert "repeats or closely copies" in model.invoke.call_args.args[0]
    assert answer == "Inspect daily. Check the guard and record damage."


def test_combined_numbering_and_detail_does_not_accept_numbering_alone():
    original = "Inspect the guard daily. Record damage before operating the machine."
    first = "1. Inspect the guard daily.\n2. Record damage before operating the machine."
    final = "1. Inspect the guard daily, checking for damage.\n2. Record damage before operating the machine."
    (answer, _), model, search = _generate([first, final],
        "Use numbered steps and add more detail", "unclear", original)
    assert model.invoke.call_count == 2
    search.assert_called_once()
    assert "Numbering was requested together with more detail" in model.invoke.call_args.args[0]
    # Both candidates remain close to the original; this also tests the bound.
    # A weak checker may still flag the final candidate and must retain its notice.
    assert answer.startswith(final)


def test_combined_numbering_and_detail_accepts_observable_addition():
    (answer, _), model, _ = _generate([
        "1. Inspect the guard daily.\n2. Write down any damage found during the check.",
    ], "Use numbered steps and add more detail", "unclear", "Inspect daily.")
    model.invoke.assert_called_once()
    assert "Rewrite limitation:" not in answer


def test_combined_citations_and_simplicity_requires_wording_change():
    original = "Maintain uniform temperature across the entire cross-section of the metal."
    first = original + " (Chunk 1)."
    final = "Keep the whole piece of metal equally hot, including its middle [Source: sop.pdf]."
    (answer, _), model, search = _generate([first, final],
        "Add citations and make it simpler", "missing_sources", original)
    assert model.invoke.call_count == 2
    search.assert_called_once()
    assert "separate simplification request" in model.invoke.call_args.args[0]
    assert answer == final


def test_unmet_combined_request_after_retry_keeps_specific_failure_notice():
    text = "Inspect the guard daily. Record damage before operating the machine."
    numbered = "1. Inspect the guard daily.\n2. Record damage before operating the machine."
    (answer, _), model, _ = _generate([numbered] * 2,
        "Use numbered steps and add more detail", "unclear", text)
    assert model.invoke.call_count == 2
    assert "Rewrite limitation:" in answer
    assert "Remaining issue: Numbering" in answer


def test_vague_incorrect_requires_targeted_question_not_any_question():
    first = "The source specifies daily inspection. Would you like a shorter answer?"
    final = "Evidence check: the source specifies daily inspection, supporting the original facts. Which specific claim do you dispute?"
    (answer, _), model, _ = _generate([first, final], "This is incorrect", "incorrect")
    assert model.invoke.call_count == 2
    assert "Which specific claim do you dispute?" in model.invoke.call_args.args[0]
    assert answer == final and "Rewrite limitation:" not in answer


def test_vague_incorrect_allows_document_supported_correction():
    final = "Evidence check: the source specifies daily inspection, not weekly. The weekly claim was incorrect. Which specific claim do you dispute?"
    (answer, _), model, _ = _generate([final], "This is incorrect", "incorrect", "Inspect weekly.")
    model.invoke.assert_called_once()
    assert answer == final
    prompt = model.invoke.call_args.args[0]
    assert "Do not assume the original answer or the user's objection is right" in prompt
    assert "contradicted, or not verifiable" in prompt


def test_prompt_requires_all_parts_and_readable_citations():
    _, model, _ = _generate(["Check the guard every day [Source: sop.pdf]."],
        "Add citations and make it simpler", "missing_sources", "Perform a diurnal inspection of the protective apparatus.")
    prompt = model.invoke.call_args.args[0]
    assert "satisfy EVERY part independently" in prompt
    assert "source filename and page from SOURCE MAP" in prompt
    assert "Do not invent definitions or details" in prompt


def test_observed_live_numbering_only_candidate_does_not_escape_detail_check():
    original = ("The purpose of annealing carbon steel is to soften the material and remove any internal "
                "stresses. This process increases ductility due to grain growth. In annealing, the work "
                "piece is allowed to cool inside the furnace only after switching off the electrical "
                "power or oil supply. This ensures that the work piece cools at a very slow rate.")
    first = ("1. The purpose of annealing carbon steel is to:\n- Soften the material.\n"
             "- Remove internal stresses.\n- Increase ductility due to grain growth.\n"
             "2. The cooling process in annealing involves:\n- Switching off the electrical power "
             "or oil supply to the furnace.\n- Allowing the work piece to cool inside the furnace "
             "at a very slow rate.")
    (answer, _), model, _ = _generate([first, first],
        "Use numbered steps and add more detail", "unclear", original)
    assert model.invoke.call_count == 2
    assert "Numbering was requested together with more detail" in model.invoke.call_args.args[0]
    assert "Rewrite limitation:" in answer


def test_rewrite_checklist_follows_qa_summary_cue_and_labels_pdf_pages_correctly():
    _, model, _ = _generate(["Check the guard every day [Source: sop.pdf, PDF page 1]."],
        "Add citations and make it simpler", "missing_sources", "Perform a diurnal inspection of the protective apparatus.")
    prompt = model.invoke.call_args.args[0]
    assert prompt.index("FEEDBACK REWRITE OUTPUT CHECKLIST:") > prompt.index("Answer (extract/summarize")
    assert '"PDF page (one-based)": 1' in prompt
    assert "Adding citations alone does not simplify" in prompt
    assert "Use ONLY definitions explicitly supplied in the retrieved context" in prompt
    assert "omit that optional jargon" in prompt


def test_new_definition_not_supplied_by_evidence_triggers_specific_retry():
    first = "Annealing improves ductility, which is the ability to deform without breaking [Source: sop.pdf]."
    final = "Annealing softens the material [Source: sop.pdf]."
    (answer, _), model, _ = _generate([first, final], "Add citations and make it simpler", "missing_sources", "Annealing improves ductility.")
    assert model.invoke.call_count == 2
    assert "explicit definition is not apparent" in model.invoke.call_args.args[0]
    assert answer == final


def test_definition_warning_accepts_explicit_definition_but_not_word_overlap():
    from feedback_rewrite import _definition_warning
    answer = "Ductility, which is the ability to deform without breaking."
    assert _definition_warning(answer, "Ductility is the ability to deform without breaking.") == ""
    assert _definition_warning(answer, "Annealing increases ductility due to grain growth.")
    # Plain-language paraphrasing without a defining assertion is not rejected
    # merely because its vocabulary differs from the evidence.
    assert _definition_warning("Keep the whole piece equally hot.", "Hold until temperature is uniform.") == ""
    assert _definition_warning("This means the whole piece is equally hot.", "Hold until temperature is uniform.") == ""
    assert _definition_warning("Cool at a slow rate, which is crucial for softening.", "Cool very slowly to soften.") == ""
    assert "defines 'ductility'" in _definition_warning("Ductility, which means it bends without breaking.", "Annealing increases ductility.").lower()
