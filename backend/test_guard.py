"""
test_guard.py
=============
Characterization tests for the off-topic guard in rag/guard.py.
They pin down CURRENT behavior: keyword checks, YES/NO interpretation,
lazy client creation and fail-open error handling.
Framework: pytest + unittest.mock
Run: cd backend && pytest test_guard.py -v
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from rag.guard import _is_off_topic


# ── Helpers ───────────────────────────────────────────────────────────────────

def _llm_replying(text):
    """Return (getter, llm) where llm.invoke(...) returns a response with .content == text."""
    llm = MagicMock()
    llm.invoke.return_value = SimpleNamespace(content=text)
    return MagicMock(return_value=llm), llm


# ── Group 1: Keyword check ────────────────────────────────────────────────────

class TestKeywordCheck:

    @pytest.mark.parametrize("message", [
        "Tell me a joke",
        "Write a poem about welding",
        "Can you sing something?",
        "Any good RIDDLES?",
        "Tell me a story.",
    ])
    def test_entertainment_words_blocked(self, message):
        assert _is_off_topic(message, MagicMock()) is True

    def test_keyword_match_does_not_create_or_call_client(self):
        getter, llm = _llm_replying("NO")
        _is_off_topic("tell me a joke", getter)
        getter.assert_not_called()
        llm.invoke.assert_not_called()

    @pytest.mark.parametrize("message", [
        "What is the casing thickness?",   # contains "sing"
        "Is the value singular?",          # contains "sing"
        "Check the storyboard",            # contains "story"
    ])
    def test_substrings_do_not_trigger_keyword_check(self, message):
        getter, llm = _llm_replying("NO")
        assert _is_off_topic(message, getter) is False
        llm.invoke.assert_called_once()


# ── Group 2: Classifier interpretation ────────────────────────────────────────

class TestClassifier:

    @pytest.mark.parametrize("reply", ["YES", "yes", "Yes.", "  YES  "])
    def test_yes_replies_block(self, reply):
        getter, _ = _llm_replying(reply)
        assert _is_off_topic("How are you?", getter) is True

    @pytest.mark.parametrize("reply", ["NO", "no", "", "Maybe"])
    def test_other_replies_allow(self, reply):
        getter, _ = _llm_replying(reply)
        assert _is_off_topic("What is the torque spec?", getter) is False

    def test_message_inserted_into_prompt_with_quotes_replaced(self):
        getter, llm = _llm_replying("NO")
        _is_off_topic('What does "Mode 3" mean?', getter)
        prompt = llm.invoke.call_args.args[0]
        assert "User message: \"What does 'Mode 3' mean?\"" in prompt

    def test_client_fetched_once_per_call(self):
        getter, _ = _llm_replying("NO")
        _is_off_topic("What is the torque spec?", getter)
        getter.assert_called_once_with()


# ── Group 3: Fail-open behavior ───────────────────────────────────────────────

class TestFailOpen:

    def test_client_creation_error_allows_message(self):
        getter = MagicMock(side_effect=RuntimeError("OPENAI_API_KEY missing"))
        assert _is_off_topic("How are you?", getter) is False

    def test_model_call_error_allows_message(self):
        llm = MagicMock()
        llm.invoke.side_effect = TimeoutError("model timed out")
        assert _is_off_topic("How are you?", MagicMock(return_value=llm)) is False
