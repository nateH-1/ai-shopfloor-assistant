import re

from rag.prompts import _GUARD_PROMPT


def _is_off_topic(question: str, get_guard_llm) -> bool:
    """
    Make a cheap, context-free LLM call to classify whether the question is
    clearly personal / off-topic BEFORE the RAG chain retrieves any documents.
    Running this *before* retrieval prevents document context from biasing the answer.
    Returns True  → block the question and return the canned off-topic reply.
    Returns False → let the full RAG chain handle it normally.

    get_guard_llm is called (inside the fail-open block) only when the keyword
    check does not decide, so the caller can create the client lazily.
    """
    # Fast deterministic check for obvious entertainment requests (whole-word match)
    _lower = question.lower()
    _ENTERTAINMENT_WORDS = ("joke", "jokes", "story", "stories", "poem", "poems",
                            "riddle", "riddles", "sing", "song", "limerick")
    if any(re.search(r'\b' + w + r'\b', _lower) for w in _ENTERTAINMENT_WORDS):
        return True

    try:
        guard_llm = get_guard_llm()
        safe_msg = question.replace('"', "'")
        result   = guard_llm.invoke(_GUARD_PROMPT.format(msg=safe_msg))
        raw      = result.content.strip()
        return raw.upper().startswith("YES")
    except Exception:
        return False   # fail open — let the chain handle edge cases
