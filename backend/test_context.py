"""
test_context.py
===============
Characterization tests for the context and citation helpers in rag/context.py.
They pin down CURRENT behavior, including known quirks — a failing test here
means behavior changed, which should only happen deliberately.
Framework: pytest
Run: cd backend && pytest test_context.py -v
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

    def test_missing_citation_line_falls_back_to_all_chunks(self):
        chunks = _chunks(3)
        answer, used = _parse_citations("  Torque is 40 Nm.  ", chunks)
        assert answer == "Torque is 40 Nm."
        assert used == chunks

    def test_out_of_range_citation_falls_back_to_all_chunks(self):
        # Known issue #1: invalid citations are treated as citing everything.
        # Update deliberately when retrieved vs. cited sources are separated.
        chunks = _chunks(3)
        _, used = _parse_citations("A.\nSOURCES_USED: 9", chunks)
        assert used == chunks

    def test_zero_citation_falls_back_to_all_chunks(self):
        # Known issue #1: citations are 1-based, so 0 is invalid → fallback.
        chunks = _chunks(3)
        _, used = _parse_citations("A.\nSOURCES_USED: 0", chunks)
        assert used == chunks

    def test_invalid_numbers_skipped_when_any_valid(self):
        chunks = _chunks(3)
        _, used = _parse_citations("A.\nSOURCES_USED: 2, 9", chunks)
        assert used == [chunks[1]]

    def test_duplicate_citations_not_deduplicated(self):
        # Deduplication happens later, in _dedup_chunks.
        chunks = _chunks(3)
        _, used = _parse_citations("A.\nSOURCES_USED: 1, 1", chunks)
        assert used == [chunks[0], chunks[0]]

    def test_text_after_citation_line_is_dropped(self):
        # Current behavior: everything from the SOURCES_USED line onward is removed.
        chunks = _chunks(3)
        answer, used = _parse_citations("A.\nSOURCES_USED: 1\nTrailing text", chunks)
        assert answer == "A."
        assert used == [chunks[0]]

    def test_empty_citation_value_leaks_label_into_answer(self):
        # Current behavior (not yet fixed): with nothing after the label the line
        # does not match, so the raw "SOURCES_USED:" text stays in the answer.
        chunks = _chunks(3)
        answer, used = _parse_citations("A.\nSOURCES_USED:", chunks)
        assert answer == "A.\nSOURCES_USED:"
        assert used == chunks


# ── Group 3: Chunk deduplication ──────────────────────────────────────────────

class TestDedupChunks:

    def test_distinct_pages_all_kept_in_order(self):
        chunks = _chunks(3)
        assert _dedup_chunks(chunks) == chunks

    def test_first_occurrence_kept(self):
        first  = _chunk("first",  page=1)
        second = _chunk("second", page=1)
        other  = _chunk("other",  page=2)
        assert _dedup_chunks([first, other, second]) == [first, other]

    def test_different_chunks_on_same_page_collapse(self):
        # Known issue #6: identity is (source, page), not chunk ID.
        a = _chunk("paragraph A", page=4)
        b = _chunk("paragraph B", page=4)
        assert _dedup_chunks([a, b]) == [a]

    def test_same_page_in_different_files_kept(self):
        a = _chunk("x", source="manual.pdf", page=1)
        b = _chunk("y", source="spec.pdf",   page=1)
        assert _dedup_chunks([a, b]) == [a, b]

    def test_source_compared_by_basename(self):
        a = _chunk("x", source="knowledge_base/manual.pdf", page=1)
        b = _chunk("y", source="other_dir/manual.pdf",      page=1)
        assert _dedup_chunks([a, b]) == [a]

    def test_missing_page_treated_as_page_zero(self):
        a = SimpleNamespace(page_content="x", metadata={"source": "notes.txt"})
        b = _chunk("y", source="notes.txt", page=0)
        assert _dedup_chunks([a, b]) == [a]

    def test_empty_list(self):
        assert _dedup_chunks([]) == []
