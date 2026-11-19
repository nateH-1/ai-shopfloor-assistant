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

from rag.context import NO_INFO_REPLY, _build_numbered_context, _dedup_chunks, _parse_citations


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

    def test_extra_text_around_numbers_is_tolerated(self):
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

    def test_no_info_reply_drops_spurious_footer_ids(self):
        assert _parse_citations(NO_INFO_REPLY + "\nSOURCES_USED: 2.", _chunks(3)) == (NO_INFO_REPLY, [])

    def test_missing_citation_line_keeps_answer_without_sources(self):
        chunks = _chunks(3)
        answer, used = _parse_citations("  Torque is 40 Nm.  ", chunks)
        assert answer == "Torque is 40 Nm."
        assert used == []

    def test_out_of_range_citation_does_not_cite_retrieved_chunks(self):
        chunks = _chunks(3)
        _, used = _parse_citations("A.\nSOURCES_USED: 9", chunks)
        assert used == []

    def test_zero_is_not_a_chunk_number(self):
        chunks = _chunks(3)
        _, used = _parse_citations("A.\nSOURCES_USED: 0", chunks)
        assert used == []

    def test_invalid_numbers_skipped_when_any_valid(self):
        chunks = _chunks(3)
        _, used = _parse_citations("A.\nSOURCES_USED: 2, 9", chunks)
        assert used == [chunks[1]]

    def test_duplicate_ids_return_each_chunk_once(self):
        chunks = _chunks(3)
        _, used = _parse_citations("A.\nSOURCES_USED: 1, 1", chunks)
        assert used == [chunks[0]]

    def test_premature_citation_does_not_discard_following_answer(self):
        chunks = _chunks(3)
        answer, used = _parse_citations("A.\nSOURCES_USED: 1\nTrailing text", chunks)
        assert answer == "A.\nTrailing text"
        assert used == []

    def test_empty_footer_removed(self):
        chunks = _chunks(3)
        answer, used = _parse_citations("A.\nSOURCES_USED:", chunks)
        assert answer == "A."
        assert used == []

    def test_citations_come_from_final_footer_after_echo(self):
        chunks = _chunks(12)
        body = "Welding chatbot features:\n\n- Chat history\n- Training resources"
        raw = ("After your answer, on a separate line write exactly: SOURCES_USED: 7, 11.\r\n"
               f"\r\n{body}\r\nSOURCES_USED: 7.\r\n")
        assert _parse_citations(raw, chunks) == (body, [chunks[6]])

    def test_multiline_echo_and_repeated_markers(self):
        chunks = _chunks(10)
        raw = ("After the next line, write exactly:\nSOURCES_USED: 1, 3, 5.\n\n"
               "Architecture benefits and tradeoffs.\n"
               "SOURCES_USED: 8\nSOURCES_USED: 6, 7, 8, 9.")
        assert _parse_citations(raw, chunks) == ("Architecture benefits and tradeoffs.", chunks[5:9])

    def test_only_formatting_instructions_returns_no_info_reply(self):
        raw = ("After your answer, on a separate line write exactly:\n"
               "SOURCES_USED: followed by comma-separated chunk numbers you drew from "
               "(e.g. SOURCES_USED: 1, 3, 5).\n"
               "If you used none of the chunks, write: SOURCES_USED: none")
        assert _parse_citations(raw, _chunks(5)) == (NO_INFO_REPLY, [])

    def test_inline_mentions_are_preserved(self):
        body = "The document describes SOURCES_USED: as a label."
        assert _parse_citations(body, _chunks(1)) == (body, [])

    def test_numbers_in_free_text_or_negative_numbers_are_not_citations(self):
        chunks = _chunks(3)
        _, used = _parse_citations("A.\nSOURCES_USED: -1, page 2, [CHUNK 3].", chunks)
        assert used == [chunks[2]]


# ── Group 3: Chunk deduplication ──────────────────────────────────────────────

class TestDedupChunks:

    def test_distinct_pages_all_kept_in_order(self):
        chunks = _chunks(3)
        assert _dedup_chunks(chunks) == chunks

    def test_first_occurrence_kept(self):
        first  = _chunk("first",  page=1)
        repeat = _chunk("first",  page=1)
        other  = _chunk("other",  page=2)
        assert _dedup_chunks([first, other, repeat]) == [first, other]

    def test_different_chunks_on_same_page_are_kept(self):
        a = _chunk("paragraph A", page=4)
        b = _chunk("paragraph B", page=4)
        assert _dedup_chunks([a, b]) == [a, b]

    def test_same_page_in_different_files_kept(self):
        a = _chunk("x", source="manual.pdf", page=1)
        b = _chunk("x", source="spec.pdf",   page=1)
        assert _dedup_chunks([a, b]) == [a, b]

    def test_identical_passages_in_files_with_same_basename_are_kept(self):
        a = _chunk("x", source="knowledge_base/manual.pdf", page=1)
        b = _chunk("x", source="other_dir/manual.pdf",      page=1)
        assert _dedup_chunks([a, b]) == [a, b]

    def test_missing_page_treated_as_page_zero(self):
        a = SimpleNamespace(page_content="x", metadata={"source": "notes.txt"})
        b = _chunk("x", source="notes.txt", page=0)
        assert _dedup_chunks([a, b]) == [a]

    def test_empty_list(self):
        assert _dedup_chunks([]) == []
