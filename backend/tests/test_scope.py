"""
test_scope.py
=============
Characterization tests for document-scope detection in rag/scope.py.
They pin down CURRENT behavior, including known issue #10.
Retrieval is replaced with scripted (chunk, distance) pairs, so no
Chroma or OpenAI calls are made. Lower distance = better match.
Framework: pytest + unittest.mock
Run: cd backend && pytest tests/test_scope.py -v
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from rag.scope import _build_clarification_question, _detect_scope


# ── Helpers ───────────────────────────────────────────────────────────────────

def _hit(source, distance, text="some text"):
    """One retrieved chunk from `source` at the given L2 distance."""
    doc = SimpleNamespace(page_content=text, metadata={"source": f"knowledge_base/{source}"})
    return (doc, distance)


def _scope(message, hits, session=None):
    """Run _detect_scope with retrieval returning `hits`."""
    session = {} if session is None else session
    with patch("rag.scope._similarity_search_with_score", return_value=hits):
        return _detect_scope(message, session, MagicMock())


def _pending():
    return {
        "pending_clarification": {
            "original_question": "what is the torque spec",
            "options": [
                {"label": "forklift manual",        "value": "forklift_manual.pdf"},
                {"label": "All relevant documents", "value": "__all__"},
            ],
        }
    }


def _forklift_and_crane(crane_text="crane hoist and crane load"):
    """Two documents scoring close enough to be ambiguous on their own."""
    return [_hit("forklift_manual.pdf", 0.100, "forklift brakes and forklift load"),
            _hit("crane_manual.pdf",    0.102, crane_text)]


# ── Resolving a pending clarification ─────────────────────────────────────────

class TestClarificationResolution:

    def test_choosing_a_document_resolves_to_it(self):
        session = _pending()
        assert _scope("forklift manual", [], session) == (
            "resolved_single", ("forklift_manual.pdf", "what is the torque spec"))
        assert session["pending_clarification"] is None

    def test_choosing_all_resolves_to_all(self):
        assert _scope("All relevant documents", [], _pending()) == ("resolved_all", "what is the torque spec")

    def test_new_question_clears_pending(self):
        session = _pending()
        _scope("how do I calibrate the press", [], session)
        assert session["pending_clarification"] is None


# ── When to ask "which document?" ─────────────────────────────────────────────

class TestScopeDecision:

    def test_broad_phrase_returns_broad(self):
        assert _scope("Compare the safety rules", []) == ("broad", None)

    def test_close_scores_are_ambiguous(self):
        hits = [_hit("beta.pdf", 0.105), _hit("alpha.pdf", 0.100)]
        assert _scope("what is the torque spec", hits) == ("ambiguous", ["alpha.pdf", "beta.pdf"])

    def test_clearly_better_document_passes(self):
        # Runner-up is 20% worse (>= _DOMINANCE_RATIO of 10%).
        hits = [_hit("alpha.pdf", 0.10), _hit("beta.pdf", 0.12)]
        assert _scope("what is the torque spec", hits) == ("pass", None)

    def test_no_good_match_passes(self):
        # Best distance >= _MIN_RELEVANCE_SCORE (0.20): no document really answers it.
        hits = [_hit("alpha.pdf", 0.20), _hit("beta.pdf", 0.201)]
        assert _scope("what is the torque spec", hits) == ("pass", None)

    def test_clarification_question_wording(self):
        assert _build_clarification_question(["forklift_manual.pdf", "crane_manual.pdf"]) == (
            'I found relevant content in multiple documents: "forklift manual" and "crane manual". '
            "Which one are you asking about, or would you like me to check all relevant documents?"
        )


# ── Naming a document in the question ─────────────────────────────────────────

class TestNamedDocument:

    def test_distinctive_keyword_passes(self):
        assert _scope("what is the forklift braking distance", _forklift_and_crane()) == ("pass", None)

    def test_keyword_common_in_other_documents_does_not_pass(self):
        hits = _forklift_and_crane(crane_text="keep forklift clear of crane")
        assert _scope("what is the forklift braking distance", hits) == (
            "ambiguous", ["forklift_manual.pdf", "crane_manual.pdf"])

    def test_short_query_word_matches_keyword_prefix(self):
        # Known issue #10: "for" is a prefix of the keyword "forklift", so this
        # question skips clarification even though it never mentions forklifts.
        assert _scope("what is the torque spec of this part", _forklift_and_crane())[0] == "ambiguous"
        assert _scope("what is the torque spec for this part", _forklift_and_crane()) == ("pass", None)
