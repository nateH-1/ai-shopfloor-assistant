"""
Kuldeep RAG Chatbot — Flask Backend
=====================================
RAG pipeline powered by ChromaDB + LangChain + OpenAI.

Endpoints
---------
POST   /chat                         — Main chat (used by Next.js proxy)
GET    /api/documents                — List uploaded documents
POST   /api/documents/upload         — Upload + ingest a document
DELETE /api/documents/<filename>     — Delete a document + its vectors
POST   /api/clear                    — Clear conversation history for a session
GET    /api/health                   — Health check
"""

import os
import json
import time
import traceback
import secrets
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, request, jsonify, g, session
from feedback import register_feedback
from flask_cors import CORS
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

import chromadb

from langchain_openai import ChatOpenAI

from rag.config import (
    KNOWLEDGE_BASE_DIR,
    CHROMA_DB_DIR,
    DOCUMENTS_JSON,
    MODEL_NAME,
    MAX_UPLOAD_MB,
    ALLOWED_EXTENSIONS,
    SESSION_TTL_SECONDS,
)

from rag.context import _dedup_chunks

from rag.resources import (
    _create_collection,
    _create_guard_llm,
    _create_llm,
)

from rag.ingestion import _ingest_file

from rag.keyword import _build_keyword_index

from rag.pipeline import answer_question

import sqlite3
import uuid
from contextlib import contextmanager
from pwdlib import PasswordHash

load_dotenv()

KNOWLEDGE_BASE_DIR.mkdir(exist_ok=True)

USERS_DB_PATH = Path(__file__).resolve().parent / "users_database" / "data.db"
password_hasher = PasswordHash.recommended()

# ── Flask app ─────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.getenv("FLASK_SECRET_KEY") or secrets.token_hex(32),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true",
)
CORS(app)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024

# Feedback is stored separately from the document collection.  It does not
# alter retrieval, prompts, citations, or the RAG answer flow.
register_feedback(app, CHROMA_DB_DIR, MODEL_NAME)

# ── Global state ─────────────────────────────────────────────────────────────
collection: chromadb.Collection | None = None
llm:        ChatOpenAI | None          = None
_guard_llm: ChatOpenAI | None          = None   # cheap off-topic classifier
conversation_sessions: dict            = {}      # session_id → { memory, last_accessed }
_keyword_index:       dict | None      = None    # BM25 index over the collection's chunks
_keyword_index_stale: bool             = True    # rebuild before next use (documents changed)

def _get_guard_llm() -> ChatOpenAI:
    """Return the cheap off-topic classifier client, creating it on first use."""
    global _guard_llm
    if _guard_llm is None:
        _guard_llm = _create_guard_llm()
    return _guard_llm


def _get_keyword_index() -> dict | None:
    """Return the BM25 keyword index, rebuilding it first if the documents changed."""
    global _keyword_index, _keyword_index_stale
    if collection is None:
        return None
    if _keyword_index_stale:
        _keyword_index = _build_keyword_index(collection)
        _keyword_index_stale = False
    return _keyword_index


def _mark_keyword_index_stale() -> None:
    """Call after documents are added or removed so the next search rebuilds the index."""
    global _keyword_index_stale
    _keyword_index_stale = True


def _get_keyword_index() -> dict | None:
    """Return the BM25 keyword index, rebuilding it first if the documents changed."""
    global _keyword_index, _keyword_index_stale
    if collection is None:
        return None
    if _keyword_index_stale:
        _keyword_index = _build_keyword_index(collection)
        _keyword_index_stale = False
    return _keyword_index


def _mark_keyword_index_stale() -> None:
    """Call after documents are added or removed so the next search rebuilds the index."""
    global _keyword_index_stale
    _keyword_index_stale = True


# ── Helper: database connections ─────────────────────────────────────────────────
def get_connection():
    USERS_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(USERS_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

@contextmanager
def database_connection():
    conn = get_connection()

    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

# ── Helper: document registry ─────────────────────────────────────────────────
def _load_doc_registry() -> dict:
    """Load the JSON registry of ingested documents."""
    if DOCUMENTS_JSON.exists():
        return json.loads(DOCUMENTS_JSON.read_text())
    return {}


def _save_doc_registry(registry: dict) -> None:
    DOCUMENTS_JSON.write_text(json.dumps(registry, indent=2))


# ── Helper: initialise / reload vector store ─────────────────────────────────
def _init_store() -> tuple[bool, str]:
    """Initialise (or reload) the ChromaDB collection and LLM. Returns (ok, message)."""
    global collection, llm

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return False, "OPENAI_API_KEY not set in environment."

    try:
        collection = _create_collection(api_key)
        llm        = _create_llm()
        _mark_keyword_index_stale()
        return True, "Vector store loaded."
    except Exception as exc:
        return False, f"Failed to load vector store: {exc}"


def _evict_stale_sessions() -> None:
    """Remove sessions that have been idle longer than SESSION_TTL_SECONDS."""
    now     = time.monotonic()
    stale   = [sid for sid, s in conversation_sessions.items()
               if now - s.get("last_accessed", now) > SESSION_TTL_SECONDS]
    for sid in stale:
        conversation_sessions.pop(sid, None)


def _format_sources(chunks: list) -> list:
    """Turn the chunks an answer used into the source list the frontend shows."""
    sources = []
    for i, doc in enumerate(_dedup_chunks(chunks), 1):
        src     = doc.metadata.get("source", "Unknown")
        page    = doc.metadata.get("page", 0)
        snippet = doc.page_content[:150].replace("\n", " ")
        if len(doc.page_content) > 150:
            snippet += "..."
        sources.append({
            "id":         i,
            "file":       os.path.basename(src),
            "page":       page + 1,
            "snippet":    snippet,
            "full_snippet": doc.page_content.replace("\n", " "),
        })
    return sources


# ── Helper: creating database tables ─────────────────────────────────────────────────
def _create_roles_table():
    with database_connection() as conn:
        cursor = conn.cursor()

        # Create roles table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS roles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                can_upload_files BOOLEAN NOT NULL DEFAULT 0,
                files_get_saved BOOLEAN NOT NULL DEFAULT 0,
                can_start_server BOOLEAN NOT NULL DEFAULT 0,
                can_join_server BOOLEAN NOT NULL DEFAULT 0,
                can_select_model BOOLEAN NOT NULL DEFAULT 0,
                can_manage_users BOOLEAN NOT NULL DEFAULT 0
            )
        """)

        # Define roles and permissions
        roles = [
            # name, upload, save, start, join, model, manage
            ("Admin",  True, True, True, True, True, True),
            ("Worker", False, False, False, True, False, False),
            ("Guest",  True, False, False, False, True, False)
        ]

        # Insert or update existing roles
        cursor.executemany("""
            INSERT INTO roles (
                name,
                can_upload_files,
                files_get_saved,
                can_start_server,
                can_join_server,
                can_select_model,
                can_manage_users
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                can_upload_files = excluded.can_upload_files,
                files_get_saved = excluded.files_get_saved,
                can_start_server = excluded.can_start_server,
                can_join_server = excluded.can_join_server,
                can_select_model = excluded.can_select_model,
                can_manage_users = excluded.can_manage_users
        """, roles)

def _create_users_table():
    with database_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY NOT NULL,
                username TEXT UNIQUE NOT NULL,
                full_name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                role_id INTEGER NOT NULL,
                verification_status TEXT NOT NULL DEFAULT 'PENDING'
                    CHECK (verification_status IN ('VERIFIED', 'PENDING', 'REJECTED')),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (role_id)
                    REFERENCES roles(id)
                    ON DELETE RESTRICT
                    ON UPDATE CASCADE
            )
        """)



# ═══════════════════════════════════════════════════════════════════════════════
#  Routes
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/chat", methods=["POST"])
def chat():
    """
    Main chat endpoint — matches the contract the Next.js proxy expects.
    Body:   { message: str, history: list, session_id?: str }
    Reply:  { reply: str, session_id: str, metadata: { sources: [] } }
    """
    try:
        data       = request.get_json(silent=True) or {}
        message    = (data.get("message") or "").strip()
        session_id = data.get("session_id") or "default"

        if not message:
            return jsonify({"error": "Message cannot be empty"}), 400

        # Evict idle sessions to prevent unbounded memory growth
        _evict_stale_sessions()

        # Lazy-init ChromaDB collection
        if collection is None:
            ok, msg = _init_store()
            if not ok:
                return jsonify({
                    "reply":      "The assistant isn't ready yet. Please upload a document first.",
                    "session_id": session_id,
                    "metadata":   {"sources": []},
                }), 503

        # Guard: no documents uploaded yet
        if collection.count() == 0:
            return jsonify({
                "reply":      "No documents have been uploaded yet. Please upload a document using the sidebar before asking questions.",
                "session_id": session_id,
                "metadata":   {"sources": []},
            })

        # When a document-choice button resolves a prior question, preserve the
        # original question with the answer snapshot used by feedback storage.
        # Capture it before answer_question, which clears pending_clarification.
        session_data = conversation_sessions.get(session_id, {})
        g.feedback_question = (session_data.get("pending_clarification") or {}).get("original_question", message)

        result = answer_question(
            message,
            conversation_sessions,
            session_id,
            collection,
            llm,
            _get_guard_llm,
            lambda: len(_load_doc_registry()),
            _get_keyword_index,
        )

        metadata = {"sources": _format_sources(result["chunks"])}
        if result["clarification"]:
            metadata["clarification"] = result["clarification"]
        return jsonify({
            "reply":      result["reply"],
            "session_id": session_id,
            "metadata":   metadata,
        })

    except Exception as exc:
        traceback.print_exc()
        return jsonify({"error": str(exc)}), 500


@app.route("/api/documents", methods=["GET"])
def list_documents():
    """Return a list of all uploaded/ingested documents."""
    registry = _load_doc_registry()
    docs = [
        {"filename": name, "chunks": info.get("chunks", 0), "uploaded_at": info.get("uploaded_at", "")}
        for name, info in registry.items()
    ]
    return jsonify({"documents": docs})


@app.route("/api/documents/upload", methods=["POST"])
def upload_document():
    """Upload and ingest a PDF file."""
    if "file" not in request.files:
        return jsonify({"success": False, "message": "No file field in request"}), 400

    file = request.files["file"]
    ext = Path(file.filename).suffix.lower() if file.filename else ""
    if not file.filename or ext not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        return jsonify({"success": False, "message": f"Unsupported file type. Allowed: {allowed}"}), 400

    filename = secure_filename(Path(file.filename).name)
    filepath = KNOWLEDGE_BASE_DIR / filename
    file.save(filepath)

    # Ensure ChromaDB collection is initialised before ingestion
    if collection is None:
        ok, msg = _init_store()
        if not ok:
            filepath.unlink(missing_ok=True)
            return jsonify({"success": False, "message": msg}), 503

    ok, msg, chunk_count = _ingest_file(filepath, collection)
    if not ok:
        filepath.unlink(missing_ok=True)
        return jsonify({"success": False, "message": msg}), 500
    _mark_keyword_index_stale()

    # Update registry
    registry = _load_doc_registry()
    registry[filename] = {"chunks": chunk_count, "uploaded_at": datetime.now(timezone.utc).isoformat()}
    _save_doc_registry(registry)

    # Clear sessions so they don't use stale context
    conversation_sessions.clear()

    return jsonify({"success": True, "message": msg, "filename": filename, "chunks": chunk_count})


@app.route("/api/documents/<filename>", methods=["DELETE"])
def delete_document(filename: str):
    """
    Delete a document file and remove its vectors from ChromaDB.
    ChromaDB supports selective deletion by metadata — no full index rebuild needed.
    """
    registry = _load_doc_registry()
    if filename not in registry:
        return jsonify({"success": False, "message": "Document not found"}), 404

    # Remove the file from disk
    (KNOWLEDGE_BASE_DIR / filename).unlink(missing_ok=True)

    # Remove from registry
    del registry[filename]
    _save_doc_registry(registry)

    # Selectively delete only this document's vectors — no rebuild required
    collection.delete(where={"source": str(KNOWLEDGE_BASE_DIR / filename)})
    _mark_keyword_index_stale()

    # Clear sessions so memory doesn't reference deleted content
    conversation_sessions.clear()

    return jsonify({"success": True, "message": f"{filename} deleted successfully."})


@app.route("/api/clear", methods=["POST"])
def clear_conversation():
    """Clear conversation history for a session."""
    data       = request.get_json(silent=True) or {}
    session_id = data.get("session_id", "default")
    conversation_sessions.pop(session_id, None)
    return jsonify({"status": "success", "message": "Conversation cleared."})


@app.route("/users/register", methods=["POST"])
def register_user():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Expected a JSON object."}), 400
    username = data.get("username")
    password = data.get("password")
    full_name = data.get("full_name")
    role = data.get("role")
    if role not in ["Worker", "Admin", "Guest"]:
        return jsonify({"error": "Valid role not in entry"}), 400
    if role == "Guest":
        session.clear()
        session["user_id"] = "Guest"
        session["role"] = "Guest"
        session["verification_status"] = "VERIFIED"
        return jsonify({"user_id": "Guest", "verification_status": "VERIFIED"})
    if not isinstance(username, str) or not username.strip():
        return jsonify({"error": "Username must be a non-empty string."}), 400
    if not isinstance(password, str) or not password:
        return jsonify({"error": "Password must be a non-empty string."}), 400
    if not isinstance(full_name, str) or not full_name:
            return jsonify({"error": "Full name must be a non-empty string."}), 400
    username = username.strip()

    try:
        user_id = str(uuid.uuid4())
        hashed = password_hasher.hash(password)

        with database_connection() as conn:
            # Check if username already exists in database
            username_already_exists = conn.execute(
                "SELECT username FROM users WHERE username = ?",
                (username,)
            ).fetchone()
            if username_already_exists:
                return jsonify({"error": "Username already exists"}), 409
            
            # Get the role id of the given role
            role_row = conn.execute(
                "SELECT id FROM roles WHERE name = ?",
                (role,)
            ).fetchone()
            if role_row is None:
                app.logger.error("Registration failed: Worker role is missing.")
                return jsonify({"error": "Registration is temporarily unavailable."}), 503
            role_id = role_row["id"]

            # If this is the first admin, they are automatically verified
            verification_status = "PENDING"
            if role == "Admin":
                existing_admin = conn.execute(
                    "SELECT username FROM users WHERE role_id = ? AND verification_status = ?",
                    (role_id, "VERIFIED")
                ).fetchone()
                if existing_admin is None:
                    verification_status = "VERIFIED"
            
            conn.execute("""
                INSERT INTO users (
                    id,
                    username,
                    full_name,
                    password_hash,
                    role_id,
                    verification_status
                )
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                user_id,
                username,
                full_name,
                hashed,
                role_id,
                verification_status
            ))

        session.clear()
        session["user_id"] = user_id
        session["role"] = role
        session["verification_status"] = verification_status
        return jsonify({"user_id": user_id, "verification_status": verification_status}), 201
    except sqlite3.IntegrityError as exc:
        if "users.username" in str(exc):
            return jsonify({"error": "Username already exists."}), 409
        app.logger.exception("Registration failed due to a database constraint.")
        return jsonify({"error": "Unable to register user."}), 500
    except Exception:
        app.logger.exception("Registration failed.")
        return jsonify({"error": "Unable to register user."}), 500

@app.route("/users/login", methods=["POST"])
def login_user():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Expected a JSON object."}), 400
    given_username = data.get("username")
    given_password = data.get("password")
    if not isinstance(given_username, str) or not given_username.strip():
        return jsonify({"error": "Username must be a non-empty string."}), 400
    if not isinstance(given_password, str) or not given_password:
        return jsonify({"error": "Password must be a non-empty string."}), 400

    try:
        with database_connection() as conn:
            user = conn.execute(
                "SELECT id, password_hash, verification_status, role_id FROM users WHERE username = ?",
                (given_username.strip(),)
            ).fetchone()

            if user:
                role_name = conn.execute(
                    "SELECT name FROM roles WHERE id = ?",
                    (user["role_id"],)
                ).fetchone()

        if user is None or not password_hasher.verify(given_password, user["password_hash"]):
            return jsonify({"error": "Invalid username or password."}), 401

        session.clear()
        session["user_id"] = user["id"]
        session["role"] = role_name["name"]
        session["verification_status"] = user["verification_status"]
        return jsonify({"user_id": user["id"], "verification_status": user["verification_status"]}), 200
    except Exception:
        app.logger.exception("Login failed.")
        return jsonify({"error": "Unable to log in."}), 500


def _current_user_role():
    user_id = session.get("user_id")
    if not user_id:
        return None
    if user_id == "Guest":
        return "Guest"
    with database_connection() as conn:
        user_role = conn.execute(
            "SELECT roles.name FROM users JOIN roles ON users.role_id = roles.id WHERE users.id = ?",
            (user_id,)
        ).fetchone()
    return user_role["name"] if user_role else None


@app.route("/roles/permissions", methods=["POST"])
def get_role_permissions():
    role = _current_user_role()
    if not role:
        return jsonify({"error": "Please log in to view your permissions."}), 401

    with database_connection() as conn:
        role_info = conn.execute(
            "SELECT * FROM roles WHERE name = ?",
            (role,)
        ).fetchone()
    
    if role_info:
        return jsonify({
            "name": role_info["name"],
            "can_upload_files": role_info["can_upload_files"],
            "files_get_saved": role_info["files_get_saved"],
            "can_start_server": role_info["can_start_server"],
            "can_join_server": role_info["can_join_server"],
            "can_select_model": role_info["can_select_model"],
            "can_manage_users": role_info["can_manage_users"]
        }), 200
    else:
        return jsonify({"error": "Failed to fetch role info."}), 500

@app.route("/users", methods=["GET"])
def get_all_users():
    if _current_user_role() != "Admin":
        return jsonify({"error": "Admin access required."}), 403
    
    with database_connection() as conn:
        users = conn.execute(
            "SELECT users.id, users.username, users.full_name, users.verification_status, roles.name FROM users JOIN roles ON users.role_id = roles.id WHERE verification_status = ?",
            ("VERIFIED",)
        ).fetchall()

        pending = conn.execute(
            "SELECT users.id, users.username, users.full_name, users.verification_status, roles.name FROM users JOIN roles ON users.role_id = roles.id WHERE verification_status = ?",
            ("PENDING",)
        ).fetchall()

    return jsonify({"verified_users": [dict(user) for user in users], "pending_users": [dict(pender) for pender in pending]}), 200

@app.route("/users/verify", methods=["POST"])
def verify_single_user():
    if _current_user_role() != "Admin":
        return jsonify({"error": "Admin access required."}), 403
    
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Expected a JSON object."}), 400
    user_id = data.get("user_id")
    if not user_id or not isinstance(user_id, str):
        return jsonify({"error": "No valid user ID recieved"}), 400
    new_status = data.get("verification_status")
    if not new_status or new_status not in ["VERIFIED", "REJECTED"]:
        return jsonify({"error": "Recieved invalid verification"}), 400

    with database_connection() as conn:
        conn.execute(
            "UPDATE users SET verification_status = ? WHERE id = ?",
            (new_status, user_id,)
        )
    return jsonify({"message": "User verified!"}), 200

@app.route("/users/delete", methods=["DELETE"])
def delete_user():
    if _current_user_role() != "Admin":
        return jsonify({"error": "Admin access required."}), 403

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Expected a JSON object."}), 400
    user_id = data.get("user_id")
    if not isinstance(user_id, str) or not user_id.strip():
        return jsonify({"error": "No valid user ID received."}), 400

    with database_connection() as conn:
        deleted = conn.execute(
            "DELETE FROM users WHERE id = ?",
            (user_id,)
        )
        if deleted.rowcount == 0:
            return jsonify({"error": "User not found"}), 404

    if user_id == session.get("user_id"):
        session.clear()
    return jsonify({"message": "User successfully deleted!"}), 200

@app.route("/users/change-role", methods=["POST"])
def change_role():
    if _current_user_role() != "Admin":
        return jsonify({"error": "Admin access required."}), 403
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Expected a JSON object."}), 400
    user_id = data.get("user_id")
    if not isinstance(user_id, str) or not user_id.strip():
        return jsonify({"error": "No valid user ID received."}), 400
    new_role = data.get("role")
    if new_role not in ["Admin", "Worker"]:
        return jsonify({"error": "No valid role received."}), 400

    with database_connection() as conn:
        role_row = conn.execute(
            "SELECT id FROM roles WHERE name = ?",
            (new_role,)
        ).fetchone()

        if role_row is None:
            return jsonify({"error": "Role not found"}), 404

        updated = conn.execute(
            "UPDATE users SET role_id = ? WHERE id = ?",
            (role_row["id"], user_id,)
        )
        if updated.rowcount == 0:
            return jsonify({"error": "User not found"}), 404
    if user_id == session.get("user_id"):
        session["role"] = new_role
    return jsonify({"message": "Role successfully changed!"}), 200

@app.route("/users/verification-status", methods=["GET"])
def get_verification_status():
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"error": "Please log in."}), 401
    if user_id == "Guest":
        return jsonify({"verification_status": "VERIFIED"})

    with database_connection() as conn:
        user = conn.execute(
            "SELECT verification_status FROM users WHERE id = ?",
            (user_id,)
        ).fetchone()

    if user is None:
        return jsonify({"error": "User not found."}), 401

    return jsonify({"verification_status": user["verification_status"]})



@app.route("/api/health", methods=["GET"])
def health():
    """Health / readiness check."""
    has_api_key  = bool(os.getenv("OPENAI_API_KEY"))
    has_docs     = collection is not None and collection.count() > 0
    return jsonify({
        "status":          "healthy",
        "has_documents":   has_docs,
        "has_api_key":     has_api_key,
        "ready":           has_docs and has_api_key and collection is not None,
        "active_sessions": len(conversation_sessions),
    })


# ── Startup ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  Kuldeep RAG Chatbot  —  Flask Backend (ChromaDB)")
    print("=" * 60)
    _init_store()   # best-effort on startup; 
    print("  Open: http://localhost:5000")
    print("=" * 60 + "\n")
    app.run(debug=True, host="0.0.0.0", port=5000)

