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

from langchain_ollama import ChatOllama

from rag.config import (
    KNOWLEDGE_BASE_DIR,
    CHROMA_DB_DIR,
    DOCUMENTS_JSON,
    MAX_UPLOAD_MB,
    ALLOWED_EXTENSIONS,
    SESSION_TTL_SECONDS,
)

from rag.context import _dedup_chunks

from rag.resources import (
    _create_collection,
    _create_guard_llm,
    _create_llm,
    _ollama_settings,
    _ollama_status,
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
    AUTH_SESSION_TTL_SECONDS=int(os.getenv("AUTH_SESSION_TTL_SECONDS", str(8 * 60 * 60))),
)
CORS(app)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024

# Feedback is stored separately from the document collection.  It does not
# alter retrieval, prompts, citations, or the RAG answer flow.
register_feedback(app, CHROMA_DB_DIR, _ollama_settings()[0])

# ── Global state ─────────────────────────────────────────────────────────────
collection: chromadb.Collection | None = None
llm:        ChatOllama | None          = None
_guard_llm: ChatOllama | None          = None   # off-topic classifier
conversation_sessions: dict            = {}      # session_id → { memory, last_accessed }
_keyword_index:       dict | None      = None    # BM25 index over the collection's chunks
_keyword_index_stale: bool             = True    # rebuild on next use

def _get_guard_llm() -> ChatOllama:
    """Return the off-topic classifier client, creating it on first use."""
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


# ── Helper: creating users database tables ─────────────────────────────────────────────────
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

# ── Helper: fetch from database ─────────────────────────────────────────────────
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


def _create_tab_sessions_table():
    with database_connection() as conn:
        # Guests have UUIDs but no account in users, so user_id is not a foreign key.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tab_sessions (
                browser_session_id TEXT NOT NULL,
                tab_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                is_guest INTEGER NOT NULL DEFAULT 0 CHECK (is_guest IN (0, 1)),
                login_id TEXT NOT NULL UNIQUE,
                expires_at REAL NOT NULL,
                PRIMARY KEY (browser_session_id, tab_id)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS tab_sessions_expiry ON tab_sessions(expires_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS tab_sessions_user ON tab_sessions(user_id)")


def _request_tab_id():
    value = request.headers.get("X-Tab-ID", "")
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError):
        return None
    return str(parsed) if str(parsed) == value.lower() else None


def _current_user():
    """Resolve this tab's login; cookie contents never grant an account role."""
    if "tab_user" in g:
        return g.tab_user
    g.tab_user = None
    browser_id = session.get("browser_session_id")
    tab_id = _request_tab_id()
    if not browser_id or not tab_id:
        return None
    with database_connection() as conn:
        row = conn.execute("""
            SELECT tab_sessions.user_id, tab_sessions.is_guest, tab_sessions.login_id,
                   users.id AS account_id, users.verification_status, roles.name AS role
            FROM tab_sessions
            LEFT JOIN users ON users.id = tab_sessions.user_id
            LEFT JOIN roles ON roles.id = users.role_id
            WHERE browser_session_id = ? AND tab_id = ? AND expires_at > ?
        """, (browser_id, tab_id, time.time())).fetchone()
    if row is not None and (row["is_guest"] or row["account_id"] is not None):
        g.tab_user = {
            "user_id": row["user_id"],
            "role": "Guest" if row["is_guest"] else row["role"],
            "verification_status": "VERIFIED" if row["is_guest"] else row["verification_status"],
            "login_id": row["login_id"],
        }
    return g.tab_user


def _current_user_role():
    user = _current_user()
    return user["role"] if user else None


def _current_user_id():
    user = _current_user()
    return user["user_id"] if user else None


def _discard_login_memory(login_id):
    prefix = f"tab:{login_id}:"
    for key in list(conversation_sessions):
        if key.startswith(prefix):
            conversation_sessions.pop(key, None)


def _start_tab_login(user_id, *, is_guest=False):
    browser_id = session["browser_session_id"]
    tab_id = _request_tab_id()
    now = time.time()
    with database_connection() as conn:
        old = conn.execute(
            "SELECT login_id FROM tab_sessions WHERE browser_session_id = ? AND tab_id = ?",
            (browser_id, tab_id),
        ).fetchone()
        conn.execute("DELETE FROM tab_sessions WHERE expires_at <= ?", (now,))
        conn.execute("""
            INSERT INTO tab_sessions (browser_session_id, tab_id, user_id, is_guest, login_id, expires_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(browser_session_id, tab_id) DO UPDATE SET
                user_id = excluded.user_id,
                is_guest = excluded.is_guest,
                login_id = excluded.login_id,
                expires_at = excluded.expires_at
        """, (browser_id, tab_id, user_id, int(is_guest), str(uuid.uuid4()),
              now + app.config["AUTH_SESSION_TTL_SECONDS"]))
    if old:
        _discard_login_memory(old["login_id"])
    g.pop("tab_user", None)


def _conversation_key(session_id):
    return f"tab:{_current_user()['login_id']}:{session_id}"


@app.before_request
def require_tab_authentication():
    if request.method == "OPTIONS":
        return None
    if request.endpoint in {"register_user", "login_user", "logout_user"}:
        if not _request_tab_id():
            return jsonify({"error": "A valid X-Tab-ID header is required."}), 400
        if request.endpoint != "logout_user" and not session.get("browser_session_id"):
            return jsonify({"error": "Initialize the browser session before logging in."}), 401
    if request.endpoint in {"chat", "list_documents", "upload_document", "delete_document", "clear_conversation"}:
        if not _current_user():
            return jsonify({"error": "Please log in."}), 401


@app.after_request
def prevent_auth_response_caching(response):
    if (request.path.startswith("/users") or request.path.startswith("/roles/")
            or request.path.startswith("/api/documents") or request.path in {"/chat", "/api/clear"}):
        response.headers["Cache-Control"] = "no-store"
    return response




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
        conversation_key = _conversation_key(session_id)

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
        session_data = conversation_sessions.get(conversation_key, {})
        g.feedback_question = (session_data.get("pending_clarification") or {}).get("original_question", message)

        result = answer_question(
            message,
            conversation_sessions,
            conversation_key,
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

    except ConnectionError as exc:
        traceback.print_exc()
        return jsonify({
            "reply":      "The local AI model isn't reachable right now. Please make sure Ollama is running and try again.",
            "session_id": session_id,
            "metadata":   {"sources": []},
        }), 503
    except Exception as exc:
        traceback.print_exc()
        return jsonify({"error": str(exc)}), 500


@app.route("/api/documents", methods=["GET"])
def list_documents():
    """Return a list of all uploaded/ingested documents."""
    registry = _load_doc_registry()
    """docs = [
        {"filename": name, "chunks": info.get("chunks", 0), "uploaded_at": info.get("uploaded_at", "")}
        for name, info in registry.items()
    ]"""
    docs = []
    if _current_user_role() == "Guest":
        for name, info in registry.items():
            if info.get("guest_id", None) == _current_user_id():
                docs.append({"filename": name, "chunks": info.get("chunks", 0), "uploaded_at": info.get("uploaded_at", "")})
    else:
        for name, info in registry.items():
            if info.get("guest_id", None) is None:
                docs.append({"filename": name, "chunks": info.get("chunks", 0), "uploaded_at": info.get("uploaded_at", "")})

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

    # increment the filename if one already exists
    registry = _load_doc_registry()
    original = Path(secure_filename(Path(file.filename).name))
    filename = original.name
    count = 1

    while filename in registry or (KNOWLEDGE_BASE_DIR / filename).exists():
        filename = f"{original.stem}_{count}{original.suffix}"
        count += 1

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

    # check if current user is a guest. If so, tag file with the guest ID so only they see it.
    guest_id = _current_user_id() if _current_user_role() == "Guest" else None

    # Update registry
    registry = _load_doc_registry()
    registry[filename] = {"chunks": chunk_count, "guest_id": guest_id, "uploaded_at": datetime.now(timezone.utc).isoformat()}
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
    conversation_sessions.pop(_conversation_key(session_id), None)
    return jsonify({"status": "success", "message": "Conversation cleared."})


@app.route("/users/session", methods=["POST"])
def initialize_browser_session():
    """Create a stable browser credential; each tab authenticates separately."""
    _create_roles_table()
    _create_users_table()
    _create_tab_sessions_table()
    with database_connection() as conn:
        conn.execute("DELETE FROM tab_sessions WHERE expires_at <= ?", (time.time(),))
    if not session.get("browser_session_id"):
        # Old account cookies are deliberately not migrated into a tab login.
        session.clear()
        session["browser_session_id"] = secrets.token_urlsafe(32)
    return "", 204


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
        user_id = str(uuid.uuid4())
        _start_tab_login(user_id, is_guest=True)
        return jsonify({"user_id": user_id, "verification_status": "VERIFIED"})
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

        _start_tab_login(user_id)
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

        if user is None or not password_hasher.verify(given_password, user["password_hash"]):
            return jsonify({"error": "Invalid username or password."}), 401

        _start_tab_login(user["id"])
        return jsonify({"user_id": user["id"], "verification_status": user["verification_status"]}), 200
    except Exception:
        app.logger.exception("Login failed.")
        return jsonify({"error": "Unable to log in."}), 500


@app.route("/users/logout", methods=["POST"])
def logout_user():
    """Revoke only this tab's login, leaving the shared browser cookie intact."""
    if not session.get("browser_session_id"):
        return "", 204
    with database_connection() as conn:
        row = conn.execute(
            "SELECT login_id FROM tab_sessions WHERE browser_session_id = ? AND tab_id = ?",
            (session["browser_session_id"], _request_tab_id()),
        ).fetchone()
        conn.execute(
            "DELETE FROM tab_sessions WHERE browser_session_id = ? AND tab_id = ?",
            (session["browser_session_id"], _request_tab_id()),
        )
    if row:
        _discard_login_memory(row["login_id"])
    g.pop("tab_user", None)
    return "", 204


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

        logins = conn.execute("SELECT login_id FROM tab_sessions WHERE user_id = ?", (user_id,)).fetchall()
        conn.execute("DELETE FROM tab_sessions WHERE user_id = ?", (user_id,))
    for login in logins:
        _discard_login_memory(login["login_id"])
    g.pop("tab_user", None)
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
    g.pop("tab_user", None)
    return jsonify({"message": "Role successfully changed!"}), 200

@app.route("/users/verification-status", methods=["GET"])
def get_verification_status():
    user = _current_user()
    if not user:
        return jsonify({"error": "Please log in."}), 401
    return jsonify({"verification_status": user["verification_status"]})



@app.route("/api/health", methods=["GET"])
def health():
    """Health / readiness check."""
    has_api_key  = bool(os.getenv("OPENAI_API_KEY"))
    has_docs     = collection is not None and collection.count() > 0
    llm_error    = _ollama_status()
    return jsonify({
        "status":          "healthy",
        "has_documents":   has_docs,
        "has_api_key":     has_api_key,
        "llm_error":       llm_error,
        "ready":           has_docs and has_api_key and collection is not None and llm_error is None,
        "active_sessions": len(conversation_sessions),
    })


# ── Startup ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    _create_roles_table()
    _create_users_table()
    _create_tab_sessions_table()
    print("\n" + "=" * 60)
    print("  Kuldeep RAG Chatbot  —  Flask Backend (ChromaDB)")
    print("=" * 60)
    _init_store()   # best-effort on startup; 
    print("  Open: http://localhost:5000")
    print("=" * 60 + "\n")
    app.run(debug=True, host="0.0.0.0", port=5000)

