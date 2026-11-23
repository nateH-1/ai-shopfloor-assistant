"""
test_context.py
===============
Characterization tests for the context and citation helpers in rag/context.py.
They pin down CURRENT behavior, including known quirks — a failing test here
means behavior changed, which should only happen deliberately.
Framework: pytest
Run: cd backend && pytest tests/test_context.py -v
"""

from types import SimpleNamespace

from rag.context import _build_numbered_context, _dedup_chunks, _parse_citations


# ── Helpers ───────────────────────────────────────────────────────────────────

def _chunk(content, source="test.pdf", page=0):
    """Minimal stand-in for a LangChain Document (helpers only read these two attributes)."""
    return SimpleNamespace(page_content=content, metadata={"source": source, "page": page})


def _chunks(n):
    return [_chunk(f"content {i}", page=i) for i in range(1, n + 1)]


# ── Group 1: Numbered context ─────────────────────────────────────────────────

class TestBuildNumberedContext:

    def test_chunks_numbered_from_one_in_order(self):
        chunks = [_chunk("alpha"), _chunk("beta")]
        assert _build_numbered_context(chunks) == "[CHUNK 1]\nalpha\n\n[CHUNK 2]\nbeta"

    def test_single_chunk(self):
        assert _build_numbered_context([_chunk("only")]) == "[CHUNK 1]\nonly"

    def test_empty_list_returns_empty_string(self):
        assert _build_numbered_context([]) == ""


# ── Group 2: Citation parsing ─────────────────────────────────────────────────

class TestParseCitations:

    def test_cited_chunks_returned_in_citation_order(self):
        chunks = _chunks(3)
        answer, used = _parse_citations("Torque is 40 Nm.\nSOURCES_USED: 2, 1", chunks)
        assert answer == "Torque is 40 Nm."
        assert used == [chunks[1], chunks[0]]

    def test_citation_numbers_map_to_matching_numbered_context(self):
        """[CHUNK n] in the context must correspond to citation n."""
        chunks = _chunks(3)
        assert "[CHUNK 3]\ncontent 3" in _build_numbered_context(chunks)
        _, used = _parse_citations("A.\nSOURCES_USED: 3", chunks)
        assert used == [chunks[2]]

    def test_bracketed_chunk_number_is_accepted(self):
        chunks = _chunks(3)
        _, used = _parse_citations("A.\nSOURCES_USED: [CHUNK 3]", chunks)
        assert used == [chunks[2]]

    def test_label_is_case_insensitive(self):
        chunks = _chunks(3)
        answer, used = _parse_citations("A.\nsources_used: 1", chunks)
        assert answer == "A."
        assert used == [chunks[0]]

    def test_none_returns_no_chunks(self):
        answer, used = _parse_citations("Not in the documents.\nSOURCES_USED: none", _chunks(3))
        assert answer == "Not in the documents."
        assert used == []

    def test_none_is_case_insensitive(self):
        _, used = _parse_citations("A.\nSOURCES_USED: None", _chunks(3))
        assert used == []

    def test_missing_citation_line_keeps_answer_without_sources(self):
        chunks = _chunks(3)
        answer, used = _parse_citations("  Torque is 40 Nm.  ", chunks)
        assert answer == "Torque is 40 Nm."
        assert used == []

    def test_invalid_footer_keeps_answer_without_sources(self):
        chunks = _chunks(3)
        for value in ("", "9", "0", "unknown"):
            assert _parse_citations(f"A.\nSOURCES_USED: {value}", chunks) == ("A.", [])

    def test_invalid_numbers_skipped_when_any_valid(self):
        chunks = _chunks(3)
        _, used = _parse_citations("A.\nSOURCES_USED: -1, page 3, 2, 9.", chunks)
        assert used == [chunks[1]]

    def test_duplicate_citations_not_deduplicated(self):
        # Deduplication happens later, in _dedup_chunks.
        chunks = _chunks(3)
        _, used = _parse_citations("A.\nSOURCES_USED: 1, 1", chunks)
        assert used == [chunks[0], chunks[0]]

    def test_nonfinal_marker_keeps_surrounding_answer_without_sources(self):
        chunks = _chunks(3)
        answer, used = _parse_citations("A.\nSOURCES_USED: 1\nTrailing text", chunks)
        assert answer == "A.\nTrailing text"
        assert used == []

    def test_split_echo_uses_the_final_footer_and_preserves_the_answer(self):
        chunks = _chunks(11)
        raw = ("After your answer, on a separate line write exactly:\r\n"
               "SOURCES_USED: 11\r\n\r\n"
               "Chat history is included.\r\nSOURCES_USED: 7.\r\n\r\n")
        assert _parse_citations(raw, chunks) == ("Chat history is included.", [chunks[6]])

    def test_inline_echo_preserves_markdown_and_both_final_source_ids(self):
        chunks = _chunks(11)
        body = "The features are:\n\n- Chat history\n- RAG document retrieval"
        raw = ("After your answer, on a separate line write exactly: SOURCES_USED: 7, 11.\n\n"
               f"{body}\nSOURCES_USED: 7, 11.")
        assert _parse_citations(raw, chunks) == (body, [chunks[6], chunks[10]])

    def test_empty_or_instruction_only_response_returns_no_info_without_sources(self):
        for raw in ("", "   \n", "SOURCES_USED: 1",
                    "After the next line, write exactly:\nSOURCES_USED: 1",
                    "After your answer, on a separate line write exactly:\n"
                    "SOURCES_USED: followed by comma-separated chunk numbers you drew from.\n"
                    "If you used none of the chunks, write: SOURCES_USED: none"):
            assert _parse_citations(raw, _chunks(1)) == (
                "The uploaded documents do not contain information about this.", []
            )

    def test_marker_mentioned_in_prose_remains_visible(self):
        body = "The document uses SOURCES_USED: as a label."
        assert _parse_citations(body, _chunks(1)) == (body, [])

    def test_tech_stack_citation_resolves_to_the_stack_rows(self):
        chunks = _chunks(12)
        chunks[8] = _chunk("Architecture benefits: ChromaDB keeps documents local. Ollama runs language models.")
        chunks[11] = _chunk("Technology Stack\nBackend: Python (Flask), RAG pipeline\n"
                            "Frontend: React + TypeScript\nAI/LLM: Locally hosted language model\nDatabase: ChromaDB")
        body = ("**Backend:** Python (Flask) and a RAG pipeline\n**Frontend:** React and TypeScript\n"
                "**AI/LLM:** A locally hosted language model\n**Database:** ChromaDB")
        assert _parse_citations(body + "\nSOURCES_USED: 9", chunks) == (body, [chunks[11]])

    def test_two_paraphrased_claims_resolve_to_both_supporting_chunks(self):
        chunks = _chunks(10)
        chunks[0] = _chunk("Table of contents: Feature comparison; Merged architecture plan; Success criteria.")
        chunks[5] = _chunk("Implementation milestone: code and integrate the features in the approved architecture.")
        chunks[8] = _chunk("ChromaDB: We don't have to pay for cloud storage or send files outside the company.")
        chunks[9] = _chunk("Feedback and Scoring: Merge the feedback system into the codebase because "
                           "the client wants users to give feedback.")
        body = ("- ChromaDB avoids paying for cloud storage and keeps files inside the company.\n"
                "- The client wants user feedback, so the feedback system will be merged into the codebase.")
        assert _parse_citations(body + "\nSOURCES_USED: 1, 6", chunks) == (body, [chunks[8], chunks[9]])

    def test_identical_support_in_another_file_keeps_the_cited_file(self):
        body = "The front panel has a blue indicator light."
        chunks = [_chunk(body, source="overview.pdf"), _chunk(body, source="service-manual.pdf")]
        assert _parse_citations(body + "\nSOURCES_USED: 2", chunks) == (body, [chunks[1]])

    def test_similar_wording_with_opposite_meaning_does_not_replace_a_citation(self):
        cases = [
            ("The machine must never run unattended.", "A technician must stay with the unit during operation.",
             "The machine must run unattended."),
            ("Set the fastener torque to 40 Nm.", "Apply forty newton metres to the bolt.",
             "Set the fastener torque to 60 Nm. Use 40 washers."),
        ]
        for answer, support, distractor in cases:
            chunks = [_chunk(support), _chunk(distractor)]
            assert _parse_citations(answer + "\nSOURCES_USED: 1", chunks) == (answer, [chunks[0]])

    def test_keeps_citations_when_only_one_of_two_paraphrases_can_be_verified(self):
        chunks = [_chunk("The archive stays on site."), _chunk("Log maintenance before restarting.")]
        body = "The archive stays on site. Document the repair before reactivation."
        assert _parse_citations(body + "\nSOURCES_USED: 1, 2", chunks) == (body, chunks)

    def test_adds_missing_source_while_preserving_partial_support_for_other_claim(self):
        chunks = [_chunk("Records are retained for seven days."), _chunk("Enable the redesigned interface.")]
        body = "Enable the redesigned interface. The records expire after one week."
        assert _parse_citations(body + "\nSOURCES_USED: 1", chunks) == (body, [chunks[1], chunks[0]])


# ── Group 3: Chunk deduplication ──────────────────────────────────────────────

class TestDedupChunks:

    def test_distinct_pages_all_kept_in_order(self):
        chunks = _chunks(3)
        assert _dedup_chunks(chunks) == chunks

    def test_first_occurrence_kept(self):
        first  = _chunk("first",  page=1)
        second = _chunk("first",  page=1)
        other  = _chunk("other",  page=2)
        assert _dedup_chunks([first, other, second]) == [first, other]

    def test_different_chunks_on_same_page_are_preserved(self):
        a = _chunk("paragraph A", page=4)
        b = _chunk("paragraph B", page=4)
        assert _dedup_chunks([a, b]) == [a, b]

    def test_same_page_in_different_files_kept(self):
        a = _chunk("x", source="manual.pdf", page=1)
        b = _chunk("y", source="spec.pdf",   page=1)
        assert _dedup_chunks([a, b]) == [a, b]

    def test_same_basename_in_different_directories_is_preserved(self):
        a = _chunk("x", source="knowledge_base/manual.pdf", page=1)
        b = _chunk("x", source="other_dir/manual.pdf",      page=1)
        assert _dedup_chunks([a, b]) == [a, b]

    def test_missing_page_treated_as_page_zero(self):
        a = SimpleNamespace(page_content="x", metadata={"source": "notes.txt"})
        b = _chunk("x", source="notes.txt", page=0)
        assert _dedup_chunks([a, b]) == [a]

    def test_empty_list(self):
        assert _dedup_chunks([]) == []
