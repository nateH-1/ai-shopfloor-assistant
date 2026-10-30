"""Authentication isolation for tabs sharing one browser cookie."""
import io
import time
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

import app as app_module


@pytest.fixture
def browser(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "USERS_DB_PATH", tmp_path / "users.db")
    monkeypatch.setitem(app_module.app.config, "TESTING", True)
    monkeypatch.setattr(app_module, "password_hasher", SimpleNamespace(
        hash=lambda password: f"test:{password}",
        verify=lambda password, hashed: hashed == f"test:{password}",
    ))
    app_module.conversation_sessions.clear()
    with app_module.app.test_client() as client:
        assert client.post("/users/session").status_code == 204
        yield client
    app_module.conversation_sessions.clear()


def headers(tab):
    return {"X-Tab-ID": tab}


def register(browser, tab, role="Guest", username="test@example.com"):
    response = browser.post("/users/register", headers=headers(tab), json={
        "role": role, "username": username, "password": "correct-password", "full_name": "Test User",
    })
    assert response.status_code in (200, 201), response.get_json()
    return response.get_json()["user_id"]


def role(browser, tab):
    response = browser.post("/roles/permissions", headers=headers(tab))
    assert response.status_code == 200, response.get_json()
    return response.get_json()["name"]


def test_bootstrap_is_idempotent_and_cookie_has_no_account_identity(browser):
    cookie_name = app_module.app.config["SESSION_COOKIE_NAME"]
    original_cookie = browser.get_cookie(cookie_name).value
    register(browser, str(uuid4()))
    response = browser.post("/users/session")
    assert response.status_code == 204
    assert "Set-Cookie" not in response.headers
    assert browser.get_cookie(cookie_name).value == original_cookie
    with browser.session_transaction() as session:
        assert set(session) == {"browser_session_id"}


def test_two_tabs_can_switch_accounts_and_logout_independently(browser):
    tab_a, tab_b = str(uuid4()), str(uuid4())
    admin_id = register(browser, tab_a, "Admin", "admin@example.com")
    worker_id = register(browser, tab_b, "Worker", "worker@example.com")
    assert role(browser, tab_a) == "Admin"
    assert role(browser, tab_b) == "Worker"
    response = browser.post("/users/login", headers=headers(tab_b), json={
        "username": "admin@example.com", "password": "correct-password",
    })
    assert response.get_json()["user_id"] == admin_id
    assert role(browser, tab_a) == role(browser, tab_b) == "Admin"
    guest_id = register(browser, tab_a)
    assert guest_id not in (admin_id, worker_id)
    assert role(browser, tab_a) == "Guest"
    assert role(browser, tab_b) == "Admin"
    assert browser.post("/users/logout", headers=headers(tab_a)).status_code == 204
    assert browser.get("/users/verification-status", headers=headers(tab_a)).status_code == 401
    assert role(browser, tab_b) == "Admin"
    assert browser.post("/users/logout", headers=headers(tab_a)).status_code == 204


def test_new_tab_does_not_inherit_logged_in_account(browser):
    register(browser, str(uuid4()), "Admin")
    new_tab = str(uuid4())
    assert browser.get("/users/verification-status", headers=headers(new_tab)).status_code == 401
    assert browser.get("/api/documents", headers=headers(new_tab)).status_code == 401


def test_guest_tabs_have_distinct_uuid_identity_and_document_lists(browser, monkeypatch):
    tab_a, tab_b = str(uuid4()), str(uuid4())
    guest_a = register(browser, tab_a)
    guest_b = register(browser, tab_b)
    assert str(UUID(guest_a)) == guest_a
    assert str(UUID(guest_b)) == guest_b
    assert guest_a != guest_b
    monkeypatch.setattr(app_module, "_load_doc_registry", lambda: {
        "a.pdf": {"guest_id": guest_a}, "b.pdf": {"guest_id": guest_b}, "shared.pdf": {},
    })
    for tab, filename in [(tab_a, "a.pdf"), (tab_b, "b.pdf")]:
        docs = browser.get("/api/documents", headers=headers(tab)).get_json()["documents"]
        assert [doc["filename"] for doc in docs] == [filename]
        assert browser.get("/users/verification-status", headers=headers(tab)).get_json() == {
            "verification_status": "VERIFIED",
        }


@pytest.mark.parametrize("tab", [None, "", "not-a-uuid", "x" * 1000])
@pytest.mark.parametrize("endpoint", ["/users/register", "/users/login", "/users/logout"])
def test_auth_mutations_require_valid_tab_header(browser, tab, endpoint):
    response = browser.post(endpoint, headers=headers(tab) if tab is not None else {}, json={"role": "Guest"})
    assert response.status_code == 400


def test_login_requires_bootstrapped_browser_cookie(browser):
    with app_module.app.test_client() as other:
        response = other.post("/users/register", headers=headers(str(uuid4())), json={"role": "Guest"})
        assert response.status_code == 401


@pytest.mark.parametrize("invalid_cookie", [False, True])
def test_logout_without_valid_browser_cookie_is_idempotent(browser, invalid_cookie):
    other_tab = str(uuid4())
    register(browser, other_tab)
    with app_module.app.test_client() as other:
        if invalid_cookie:
            other.set_cookie(app_module.app.config["SESSION_COOKIE_NAME"], "invalid-signature")
        for _ in range(2):
            response = other.post("/users/logout", headers=headers(other_tab))
            assert response.status_code == 204
            assert "Set-Cookie" not in response.headers
    assert role(browser, other_tab) == "Guest"


@pytest.mark.parametrize("path,method", [
    ("/chat", "POST"), ("/api/documents", "GET"), ("/api/documents/upload", "POST"),
    ("/api/documents/test.pdf", "DELETE"), ("/api/clear", "POST"),
    ("/users/verification-status", "GET"), ("/roles/permissions", "POST"),
])
def test_account_cookie_without_tab_cannot_authenticate(browser, path, method):
    register(browser, str(uuid4()))
    assert browser.open(path, method=method).status_code == 401


def test_same_tab_id_does_not_authenticate_another_browser(browser):
    tab = str(uuid4())
    register(browser, tab, "Admin")
    with app_module.app.test_client() as other:
        assert other.post("/users/session").status_code == 204
        assert other.get("/users/verification-status", headers=headers(tab)).status_code == 401
        register(other, tab)
        assert role(other, tab) == "Guest"
    assert role(browser, tab) == "Admin"


def test_expired_login_is_rejected_and_cleanup_preserves_other_tabs(browser):
    tab_a, tab_b = str(uuid4()), str(uuid4())
    register(browser, tab_a)
    register(browser, tab_b)
    with app_module.database_connection() as conn:
        conn.execute("UPDATE tab_sessions SET expires_at = ? WHERE tab_id = ?", (time.time() - 1, tab_a))
    assert browser.get("/users/verification-status", headers=headers(tab_a)).status_code == 401
    assert browser.post("/users/session").status_code == 204
    with app_module.database_connection() as conn:
        assert conn.execute("SELECT tab_id FROM tab_sessions").fetchone()["tab_id"] == tab_b
    assert role(browser, tab_b) == "Guest"


def test_failed_login_does_not_replace_existing_tab_login(browser):
    tab = str(uuid4())
    register(browser, tab, "Worker")
    response = browser.post("/users/login", headers=headers(tab), json={
        "username": "test@example.com", "password": "wrong-password",
    })
    assert response.status_code == 401
    assert role(browser, tab) == "Worker"


def test_deleting_account_revokes_its_logins_without_affecting_other_accounts(browser):
    tab_a, tab_b, tab_c = (str(uuid4()) for _ in range(3))
    register(browser, tab_a, "Admin", "admin@example.com")
    target_id = register(browser, tab_b, "Worker", "worker@example.com")
    response = browser.post("/users/login", headers=headers(tab_c), json={
        "username": "worker@example.com", "password": "correct-password",
    })
    assert response.status_code == 200
    assert browser.delete("/users/delete", headers=headers(tab_a), json={"user_id": target_id}).status_code == 200
    for tab in (tab_b, tab_c):
        assert browser.get("/users/verification-status", headers=headers(tab)).status_code == 401
    assert role(browser, tab_a) == "Admin"
    with app_module.database_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM tab_sessions WHERE user_id = ?", (target_id,)).fetchone()[0] == 0


def test_verification_changes_are_read_from_database(browser):
    tab_a, tab_b = str(uuid4()), str(uuid4())
    register(browser, tab_a, "Admin", "admin@example.com")
    user_id = register(browser, tab_b, "Worker", "worker@example.com")
    assert browser.get("/users/verification-status", headers=headers(tab_b)).get_json()["verification_status"] == "PENDING"
    assert browser.post("/users/verify", headers=headers(tab_a), json={
        "user_id": user_id, "verification_status": "VERIFIED",
    }).status_code == 200
    assert browser.get("/users/verification-status", headers=headers(tab_b)).get_json()["verification_status"] == "VERIFIED"


def test_legacy_cookie_requires_fresh_login(browser):
    with browser.session_transaction() as session:
        session.clear()
        session.update(user_id="old-admin", role="Admin", verification_status="VERIFIED")
    tab = str(uuid4())
    assert browser.get("/users/verification-status", headers=headers(tab)).status_code == 401
    assert browser.post("/users/session").status_code == 204
    with browser.session_transaction() as session:
        assert set(session) == {"browser_session_id"}
    assert browser.get("/users/verification-status", headers=headers(tab)).status_code == 401


def test_chat_and_clear_are_scoped_to_login_even_with_same_conversation_id(browser, monkeypatch):
    tab_a, tab_b = str(uuid4()), str(uuid4())
    register(browser, tab_a)
    register(browser, tab_b)
    monkeypatch.setattr(app_module, "collection", MagicMock())
    def answer(message, sessions, key, *_args):
        state = sessions.setdefault(key, {"messages": [], "last_accessed": time.monotonic()})
        state["messages"].append(message)
        return {"reply": ",".join(state["messages"]), "chunks": [], "clarification": None}
    monkeypatch.setattr(app_module, "answer_question", answer)
    def chat(tab, message):
        response = browser.post("/chat", headers=headers(tab), json={"message": message, "session_id": "same"})
        assert response.status_code == 200
        assert response.get_json()["session_id"] == "same"
        return response.get_json()["reply"]
    assert chat(tab_a, "a1") == "a1"
    assert chat(tab_b, "b1") == "b1"
    assert chat(tab_a, "a2") == "a1,a2"
    assert browser.post("/api/clear", headers=headers(tab_a), json={"session_id": "same"}).status_code == 200
    assert chat(tab_a, "a3") == "a3"
    assert chat(tab_b, "b2") == "b1,b2"
    register(browser, tab_a)
    assert chat(tab_a, "new-login") == "new-login"
    assert chat(tab_b, "b3") == "b1,b2,b3"


def test_guest_upload_tags_tab_owner_and_preserves_numbered_path(browser, monkeypatch, tmp_path):
    tab = str(uuid4())
    guest_id = register(browser, tab)
    monkeypatch.setattr(app_module, "KNOWLEDGE_BASE_DIR", tmp_path)
    monkeypatch.setattr(app_module, "collection", MagicMock())
    (tmp_path / "notes.txt").write_text("existing")
    registry = {"notes.txt": {"guest_id": "other-guest"}}
    monkeypatch.setattr(app_module, "_load_doc_registry", lambda: dict(registry))
    saved = []
    monkeypatch.setattr(app_module, "_save_doc_registry", saved.append)
    ingested = []
    def ingest(path, _collection):
        ingested.append(path)
        return True, "Ingested.", 1
    monkeypatch.setattr(app_module, "_ingest_file", ingest)
    response = browser.post("/api/documents/upload", headers=headers(tab), data={
        "file": (io.BytesIO(b"new content"), "notes.txt"),
    })
    assert response.status_code == 200
    assert response.get_json()["filename"] == "notes_1.txt"
    assert ingested == [tmp_path / "notes_1.txt"]
    assert (tmp_path / "notes.txt").read_text() == "existing"
    assert saved[0]["notes_1.txt"]["guest_id"] == guest_id


def test_authenticated_responses_are_not_cached(browser):
    tab = str(uuid4())
    register(browser, tab)
    response = browser.get("/users/verification-status", headers=headers(tab))
    assert response.headers["Cache-Control"] == "no-store"
