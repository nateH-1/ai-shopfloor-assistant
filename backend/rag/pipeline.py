import os
import time

from langchain.memory import ConversationBufferMemory
from langchain_core.documents import Document

from rag.config import KNOWLEDGE_BASE_DIR, MAX_MULTI_DOC_CHUNKS, NUM_CHUNKS
from rag.context import _build_numbered_context, _parse_citations
from rag.guard import _is_off_topic
from rag.prompts import CONDENSE_PROMPT, QA_PROMPT, _MULTI_DOC_QA_TEMPLATE
from rag.retrieval import _hybrid_search
from rag.scope import (
    _build_clarification_options,
    _build_clarification_question,
    _detect_scope,
    _display_name,
)

OFF_TOPIC_REPLY = "I can only answer questions about the uploaded documents."
NO_INFO_REPLY   = "The uploaded documents do not contain information about this."


def answer_question(
    message: str,
    sessions: dict,
    session_id: str,
    collection,
    llm,
    get_guard_llm,
    get_num_docs,
    get_keyword_index,
) -> dict:
    """
    Run one chat turn: off-topic guard → condense follow-up → scope detection →
    clarification or one of the three answer paths.

    sessions is the caller's session store (session_id → session dict); entries are
    created only where the answer paths need them. get_guard_llm, get_num_docs and
    get_keyword_index are called only when needed.

    Returns {"reply": str, "chunks": list[Document], "clarification": dict | None}.
    """
    # Guard: block personal/entertainment/small-talk questions BEFORE retrieval.
    # Still skip when a clarification is pending — the user is replying to a
    # document-selection prompt, so their short answer ("the first one", "yes")
    # should never be classified as off-topic.
    session_data = sessions.get(session_id, {})
    has_history = "memory" in session_data and session_data["memory"].load_memory_variables({}).get("chat_history", "")
    has_pending_clarification = bool(session_data.get("pending_clarification"))
    if not has_pending_clarification and _is_off_topic(message, get_guard_llm):
        return {"reply": OFF_TOPIC_REPLY, "chunks": [], "clarification": None}

    # ── Condense follow-ups before scope detection ──────────────────────────
    # If there's conversation history, rephrase the message into a standalone
    # question so that scope detection works on the full context, not just
    # a bare pronoun like "tell me more about the first one."
    chat_history = ""
    if has_history:
        chat_history = session_data["memory"].load_memory_variables({}).get("chat_history", "")
        condensed_for_scope = llm.invoke(
            CONDENSE_PROMPT.format(chat_history=chat_history, question=message)
        ).content.strip()
    else:
        condensed_for_scope = message

    # ── Scope detection ──────────────────────────────────────────────────────
    scope, scope_data = _detect_scope(
        condensed_for_scope,
        sessions.get(session_id, {}),
        collection,
    )

    if scope == "ambiguous":
        options  = _build_clarification_options(scope_data)
        question = _build_clarification_question(scope_data)
        sessions.setdefault(session_id, {})["pending_clarification"] = {
            "original_question": message,
            "options":           options,
        }
        return {
            "reply":         question,
            "chunks":        [],
            "clarification": {"question": question, "options": options},
        }

    if scope in ("broad", "resolved_all"):
        answer, used_chunks = _answer_multi_doc(
            scope_data if scope == "resolved_all" else message,
            get_num_docs(),
            collection,
            llm,
            get_keyword_index,
        )
        return {"reply": answer, "chunks": used_chunks, "clarification": None}

    if scope == "resolved_single":
        filename, original_q = scope_data
        answer, used_chunks = _answer_single_doc(original_q, filename, collection, llm, get_keyword_index)
        return {"reply": answer, "chunks": used_chunks, "clarification": None}

    # ── Default: manual conversational RAG pipeline ─────────────────────────
    answer, source_docs = _chat_with_memory(
        message,
        sessions.setdefault(session_id, {}),
        collection,
        llm,
        get_keyword_index,
    )
    return {"reply": answer, "chunks": source_docs, "clarification": None}


def _answer_single_doc(question: str, filename: str, collection, llm, get_keyword_index) -> tuple[str, list[Document]]:
    """Retrieve chunks from a specific file using ChromaDB metadata filter."""
    doc_chunks, enough_evidence = _hybrid_search(
        collection,
        question,
        get_keyword_index,
        k=NUM_CHUNKS,
        where={"source": str(KNOWLEDGE_BASE_DIR / filename)},
    )

    if not doc_chunks or not enough_evidence:
        return f'The document "{_display_name(filename)}" does not appear to contain information about this.', []

    context          = _build_numbered_context(doc_chunks)
    result           = llm.invoke(QA_PROMPT.format(context=context, question=question))
    answer, used_chunks = _parse_citations(result.content, doc_chunks)
    return answer, used_chunks


def _answer_multi_doc(question: str, num_docs: int, collection, llm, get_keyword_index) -> tuple[str, list[Document]]:
    """Retrieve chunks balanced across sources and synthesize with multi-doc prompt.

    num_docs is the number of registered documents (used to size retrieval).
    """
    # Scale k with the number of known documents so every doc gets fair representation.
    # Cap total chunks at MAX_MULTI_DOC_CHUNKS to stay within the LLM context window.
    num_docs       = max(1, num_docs)
    pool_k         = min(num_docs * 5, 80)            # retrieve a wide pool
    chunks_per_src = max(2, MAX_MULTI_DOC_CHUNKS // num_docs)  # balance per source
    candidates, enough_evidence = _hybrid_search(collection, question, get_keyword_index, k=pool_k)
    if not enough_evidence:
        return NO_INFO_REPLY, []
    by_source: dict = {}
    for doc in candidates:
        src = os.path.basename(doc.metadata.get("source", "unknown"))
        if src not in by_source:
            by_source[src] = []
        if len(by_source[src]) < chunks_per_src:
            by_source[src].append(doc)

    context_parts: list = []
    all_chunks:    list = []
    chunk_num = 1
    for src, chunks in by_source.items():
        context_parts.append(f"[Source: {src}]")
        for chunk in chunks:
            context_parts.append(f"[CHUNK {chunk_num}]\n{chunk.page_content}")
            all_chunks.append(chunk)
            chunk_num += 1
        context_parts.append("")

    result = llm.invoke(_MULTI_DOC_QA_TEMPLATE.format(
        context="\n".join(context_parts),
        question=question,
    ))
    answer, used_chunks = _parse_citations(result.content, all_chunks)
    return answer, used_chunks


def _chat_with_memory(question: str, session: dict, collection, llm, get_keyword_index) -> tuple[str, list[Document]]:
    """
    Manual replacement for ConversationalRetrievalChain.
    1. Condense follow-up questions using CONDENSE_PROMPT + chat history.
    2. Retrieve top-k chunks from ChromaDB.
    3. Answer with QA_PROMPT (strict grounding).
    4. Save to ConversationBufferMemory for next turn.

    session is the caller's session dict; memory and last_accessed are stored on it.
    """
    session["last_accessed"] = time.monotonic()

    if "memory" not in session:
        session["memory"] = ConversationBufferMemory(
            memory_key="chat_history",
            return_messages=False,
        )

    memory      = session["memory"]
    chat_history = memory.load_memory_variables({}).get("chat_history", "")

    # Step 1: Condense follow-up question into standalone form if needed
    if chat_history:
        condensed = llm.invoke(
            CONDENSE_PROMPT.format(chat_history=chat_history, question=question)
        ).content.strip()
    else:
        condensed = question

    # Step 2: Retrieve relevant chunks
    chunks, enough_evidence = _hybrid_search(collection, condensed, get_keyword_index, k=NUM_CHUNKS)
    if not chunks or not enough_evidence:
        answer = NO_INFO_REPLY
        memory.save_context({"input": question}, {"output": answer})
        return answer, []

    # Step 3: Answer strictly from retrieved context
    context   = _build_numbered_context(chunks)
    raw       = llm.invoke(QA_PROMPT.format(context=context, question=condensed)).content
    answer, chunks = _parse_citations(raw, chunks)

    # Step 4: Persist turn to memory
    memory.save_context({"input": question}, {"output": answer})
    return answer, chunks
