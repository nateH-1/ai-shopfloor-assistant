"""Local answer feedback. No model calls or document-search embeddings are used."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from uuid import UUID, uuid4

import chromadb
from flask import Blueprint, current_app, jsonify, request

REASONS = {"incorrect", "incomplete", "irrelevant", "unclear", "missing_sources", "other"}
COLLECTION_NAME = "answer_feedback_v1"
MAX_COMMENT = 2000
RETENTION_DAYS = 7
MAX_STYLE_COMMENTS = 3

STYLE_REASON_GUIDANCE = {
    "unclear": "Use clearer wording and break the answer into shorter steps.",
    "incomplete": "When the retrieved context supports it, cover the relevant steps more completely.",
    "missing_sources": "Make source support easier to follow without adding unsupported claims.",
    "irrelevant": "Stay closer to the exact user question.",
    "other": "Improve the answer presentation based on the user's comment.",
}


def canonical_uuid(value):
    """Accept only canonical UUIDs, not arbitrary paths or query expressions."""
    if not isinstance(value, str):
        return None
    try:
        parsed = str(UUID(value))
        return parsed if parsed == value else None
    except (ValueError, AttributeError):
        return None


def owner_hash(value):
    # The random browser cookie is a bearer credential; never store its raw value.
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class FeedbackStore:
    """One saved feedback row per answer; unanswered rating prompts stay in memory."""

    def __init__(self, path):
        self.path = str(Path(path).resolve())
        self._collection = None
        self._pending = {}
        # Serializes read/update within this local, single-process Flask deployment.
        self._lock = RLock()

    @property
    def collection(self):
        with self._lock:
            if self._collection is None:
                client = chromadb.PersistentClient(path=self.path)
                self._collection = client.get_or_create_collection(
                    COLLECTION_NAME,
                    embedding_function=None,
                    metadata={"schema_version": 1},
                )
            return self._collection

    def prepare_answer(self, owner, question, payload, model):
        # Do not write a database record until the user actually submits a vote.
        message_id = str(uuid4())
        # The answer and citations come from Flask, never a client-supplied vote.
        snapshot = {
            "question": question,
            "answer": payload["reply"],
            "sources": payload.get("metadata", {}).get("sources", []),
            "model": model,
            "session_id": payload.get("session_id", ""),
        }
        with self._lock:
            self._pending[message_id] = {
                "owner": owner_hash(owner),
                "snapshot": snapshot,
                "expires_at": datetime.now(timezone.utc) + timedelta(hours=24),
            }
        return message_id

    def _drop_expired_pending(self):
        now = datetime.now(timezone.utc)
        expired = [
            message_id for message_id, item in self._pending.items()
            if item["expires_at"] <= now
        ]
        for message_id in expired:
            self._pending.pop(message_id, None)

    @staticmethod
    def _is_expired(value):
        try:
            created_at = datetime.fromisoformat(value)
        except (TypeError, ValueError):
            return False
        return created_at < datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)

    def cleanup_expired(self):
        # Cleanup is intentionally best-effort so expired feedback never blocks
        # the user from submitting or reading current feedback.
        with self._lock:
            self._drop_expired_pending()
            result = self.collection.get(include=["metadatas"])
            expired = [
                message_id
                for message_id, metadata in zip(result.get("ids", []), result.get("metadatas", []))
                if self._is_expired((metadata or {}).get("created_at"))
            ]
            if expired:
                self.collection.delete(ids=expired)

    def _owned_metadata(self, message_id, owner):
        result = self.collection.get(
            ids=[message_id],
            where={"owner": owner_hash(owner)},
            include=["metadatas"],
        )
        if not result["ids"]:
            raise LookupError("Answer not found.")
        return result["metadatas"][0]

    @staticmethod
    def public_feedback(metadata):
        if not metadata or metadata.get("vote") == "unrated":
            return None
        return {key: metadata[key] for key in ("vote", "reason", "comment", "updated_at")}

    def get(self, message_id, owner):
        with self._lock:
            self.cleanup_expired()
            pending = self._pending.get(message_id)
            if pending and pending["owner"] == owner_hash(owner):
                return None
            return self.public_feedback(self._owned_metadata(message_id, owner))

    def style_guidance(self, owner):
        """Summarize recent feedback as presentation guidance, never as factual context."""
        with self._lock:
            self.cleanup_expired()
            owner_key = owner_hash(owner)
            result = self.collection.get(
                where={"owner": owner_key},
                include=["metadatas"],
                limit=50,
            )
            rows = sorted(
                result.get("metadatas", []),
                key=lambda metadata: (metadata or {}).get("updated_at") or (metadata or {}).get("created_at") or "",
                reverse=True,
            )

        guidance = []
        comments = []
        for metadata in rows:
            if not metadata or metadata.get("vote") != "not_helpful":
                continue
            reason = metadata.get("reason", "")
            if reason in STYLE_REASON_GUIDANCE and STYLE_REASON_GUIDANCE[reason] not in guidance:
                guidance.append(STYLE_REASON_GUIDANCE[reason])
            comment = " ".join((metadata.get("comment") or "").split())
            if comment:
                comments.append(comment[:300])
            if len(comments) >= MAX_STYLE_COMMENTS:
                break

        if not guidance and not comments:
            return ""

        lines = [
            "Apply these as style and clarity guidance only. Do not treat feedback as a source of facts.",
            "The current user question takes priority over older style feedback.",
        ]
        lines.extend(f"- {item}" for item in guidance[:MAX_STYLE_COMMENTS])
        lines.extend(f'- User comment: "{comment}"' for comment in comments[:MAX_STYLE_COMMENTS])
        return "\n".join(lines)

    def save(self, message_id, owner, vote, reason, comment):
        with self._lock:
            self.cleanup_expired()
            owner_key = owner_hash(owner)
            metadata = None
            try:
                metadata = self._owned_metadata_by_hash(message_id, owner_key)
            except LookupError:
                pending = self._pending.get(message_id)
                if not pending or pending["owner"] != owner_key:
                    raise
                self._pending.pop(message_id, None)
                now = utc_now()
                metadata = {
                    "owner": owner_key,
                    "vote": vote,
                    "reason": reason,
                    "comment": comment,
                    "created_at": now,
                    "updated_at": now,
                    "schema_version": 1,
                }
                self.collection.add(
                    ids=[message_id],
                    documents=[json.dumps(pending["snapshot"], ensure_ascii=False)],
                    # Chroma requires a vector. This collection uses ID lookup only;
                    # a constant vector avoids cloud calls and embedding downloads.
                    embeddings=[[0.0]],
                    metadatas=[metadata],
                )
                return self.public_feedback(metadata)
            # Update only rating fields. The original answer and owner are immutable.
            self.collection.update(ids=[message_id], metadatas=[{
                "vote": vote, "reason": reason, "comment": comment, "updated_at": utc_now(),
            }])
            return self.public_feedback(self._owned_metadata_by_hash(message_id, owner_key))

    def _owned_metadata_by_hash(self, message_id, owner):
        result = self.collection.get(
            ids=[message_id],
            where={"owner": owner},
            include=["metadatas"],
        )
        if not result["ids"]:
            raise LookupError("Answer not found.")
        return result["metadatas"][0]

    def remove(self, message_id, owner):
        with self._lock:
            self.cleanup_expired()
            owner_key = owner_hash(owner)
            pending = self._pending.get(message_id)
            if pending and pending["owner"] == owner_key:
                self._pending.pop(message_id, None)
                return
            self._owned_metadata(message_id, owner)
            self.collection.delete(ids=[message_id])


def register_feedback(app, database_path, model):
    """Attach storage lazily so missing feedback storage never prevents startup."""
    app.extensions["feedback_store"] = FeedbackStore(database_path)
    bp = Blueprint("feedback", __name__)

    @app.after_request
    def attach_feedback_id(response):
        # Add an ID only after a successful normal chat reply. Clarification
        # prompts and error responses are not answers that can be rated.
        if request.endpoint != "chat" or response.status_code != 200:
            return response
        owner = canonical_uuid(request.headers.get("X-Feedback-Owner"))
        payload = response.get_json(silent=True)
        if (not owner or not isinstance(payload, dict) or not payload.get("reply")
                or payload.get("metadata", {}).get("clarification")):
            return response
        try:
            body = request.get_json(silent=True) or {}
            # A clarification reply may contain a filename rather than the question.
            # The chat route captures the original question before resolving it.
            from flask import g
            question = getattr(g, "feedback_question", body.get("message", ""))
            message_id = app.extensions["feedback_store"].prepare_answer(
                owner, question, payload, model,
            )
            payload["message_id"] = message_id
        except Exception:
            current_app.logger.exception("Could not prepare local answer feedback")
            # Preserve a successful chat answer if disk/database access fails.
            payload["feedback_unavailable"] = True
        response.set_data(app.json.dumps(payload))
        response.headers["Cache-Control"] = "no-store"
        return response

    @bp.route("/api/feedback/<message_id>", methods=["GET", "PUT", "DELETE"])
    def answer_feedback(message_id):
        owner = canonical_uuid(request.headers.get("X-Feedback-Owner"))
        if not owner:
            return jsonify(error="Feedback browser identity is missing."), 401
        if not canonical_uuid(message_id):
            return jsonify(error="Answer not found."), 404
        if request.content_length and request.content_length > 16384:
            return jsonify(error="Feedback request is too large."), 413

        store = current_app.extensions["feedback_store"]
        try:
            if request.method == "GET":
                response = jsonify(feedback=store.get(message_id, owner))
            elif request.method == "DELETE":
                store.remove(message_id, owner)
                response = jsonify(feedback=None)
            else:
                body = request.get_json(silent=True)
                if not isinstance(body, dict):
                    return jsonify(error="Send a JSON feedback object."), 400
                if set(body) - {"vote", "reason", "comment"}:
                    return jsonify(error="Unexpected feedback fields."), 400
                vote, reason, comment = body.get("vote"), body.get("reason", ""), body.get("comment", "")
                if not isinstance(vote, str) or vote not in {"helpful", "not_helpful"}:
                    return jsonify(error="Choose helpful or not_helpful."), 400
                if not isinstance(reason, str) or (reason and reason not in REASONS):
                    return jsonify(error="Choose a valid feedback reason."), 400
                if not isinstance(comment, str) or len(comment) > MAX_COMMENT:
                    return jsonify(error=f"Comment must be at most {MAX_COMMENT} characters."), 400
                if vote == "helpful" and reason:
                    return jsonify(error="Reasons apply to not-helpful feedback only."), 400
                response = jsonify(feedback=store.save(
                    message_id, owner, vote, reason, comment.strip(),
                ))
            response.headers["Cache-Control"] = "no-store"
            return response
        except LookupError:
            # Do not reveal whether the answer belongs to a different browser.
            return jsonify(error="Answer not found."), 404
        except Exception:
            current_app.logger.exception("Local feedback storage failed")
            return jsonify(error="Feedback could not be saved or loaded. Please try again."), 503

    app.register_blueprint(bp)
