"""Guest settings persist and are enforced using the authenticated tab identity."""

import io
import json
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

import app as app_module


@pytest.fixture
def browser(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "USERS_DB_PATH", tmp_path / "users.db")
    app_module._initialize_sqlite()
    monkeypatch.setitem(app_module.app.config, "TESTING", True)
    monkeypatch.setattr(app_module, "password_hasher", SimpleNamespace(
        hash=lambda password: f"test:{password}",
        verify=lambda password, hashed: hashed == f"test:{password}",
    ))
    directory = tmp_path / "knowledge_base"
    directory.mkdir()
    monkeypatch.setattr(app_module, "KNOWLEDGE_BASE_DIR", directory)
    monkeypatch.setattr(app_module, "DOCUMENTS_JSON", directory / "documents.json")
    monkeypatch.setattr(app_module, "conversation_sessions", {})
    collection = MagicMock()
    collection.count.return_value = 5
    monkeypatch.setattr(app_module, "collection", collection)
    monkeypatch.setattr(app_module, "_ingest_file", MagicMock(return_value=(True, "Ingested.", 1)))
    monkeypatch.setattr(app_module, "answer_question", MagicMock(return_value={
        "reply": "Answer.", "chunks": [], "clarification": None,
    }))
    with app_module.app.test_client() as client:
        assert client.post("/users/session").status_code == 204
        yield client


def headers(tab):
    return {"X-Tab-ID": tab}


def register(browser, role="Guest"):
    tab = str(uuid4())
    response = browser.post("/users/register", headers=headers(tab), json={
        "role": role, "username": f"{tab}@example.com", "password": "password", "full_name": "Test User",
    })
    assert response.status_code in (200, 201), response.get_json()
    return tab, response.get_json()["user_id"]


def set_enabled(browser, admin_tab, enabled):
    response = browser.post("/guest/enable", headers=headers(admin_tab), json={"enabled": enabled})
    assert response.status_code == 200, response.get_json()
    assert response.get_json() == {"guests_enabled": enabled == "enabled"}
    return response


def test_defaults_get_response_and_reinitialization_preserve_disabled_setting(browser):
    assert app_module.guest_is_enabled() is True
    response = browser.get("/guest/status")
    assert response.status_code == 200
    assert response.get_json() == {"guests_enabled": True}
    with app_module.database_connection() as conn:
        conn.execute("UPDATE app_settings SET guests_enabled = 0 WHERE id = 1")
    app_module._initialize_sqlite()
    assert app_module.guest_is_enabled() is False
    assert browser.get("/guest/status").get_json() == {"guests_enabled": False}
    with app_module.database_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM app_settings").fetchone()[0] == 1
        conn.execute("DELETE FROM app_settings")
    assert app_module.guest_is_enabled() is False


def test_verified_admin_can_disable_reenable_and_repeat_updates(browser):
    admin, _ = register(browser, "Admin")
    for value in ("disabled", "disabled", "enabled", "enabled"):
        set_enabled(browser, admin, value)
        assert app_module.guest_is_enabled() is (value == "enabled")


def test_disabling_revokes_all_guest_tabs_across_browsers_and_preserves_accounts(browser):
    admin, _ = register(browser, "Admin")
    worker, _ = register(browser, "Worker")
    guest, _ = register(browser)
    other_browser = app_module.app.test_client()
    assert other_browser.post("/users/session").status_code == 204
    other_guest, _ = register(other_browser)
    cookie_name = app_module.app.config["SESSION_COOKIE_NAME"]
    cookies = [client.get_cookie(cookie_name).value for client in (browser, other_browser)]
    with app_module.database_connection() as conn:
        logins = {row["tab_id"]: row["login_id"] for row in conn.execute("SELECT tab_id, login_id FROM tab_sessions")}
    for login_id in logins.values():
        for conversation in ("default", "another"):
            app_module.conversation_sessions[f"tab:{login_id}:{conversation}"] = {"memory": "old context"}

    response = set_enabled(browser, admin, "disabled")

    assert "Set-Cookie" not in response.headers
    assert [client.get_cookie(cookie_name).value for client in (browser, other_browser)] == cookies
    with app_module.database_connection() as conn:
        remaining = {row["tab_id"]: row["login_id"] for row in conn.execute("SELECT tab_id, login_id FROM tab_sessions")}
    assert remaining == {tab: logins[tab] for tab in (admin, worker)}
    assert set(app_module.conversation_sessions) == {
        f"tab:{logins[tab]}:{conversation}"
        for tab in (admin, worker) for conversation in ("default", "another")
    }
    for client, tab in ((browser, guest), (other_browser, other_guest)):
        assert client.get("/users/verification-status", headers=headers(tab)).status_code == 401
        assert client.post("/chat", headers=headers(tab), json={"message": "question"}).status_code == 401
    for tab in (admin, worker):
        assert browser.get("/users/verification-status", headers=headers(tab)).status_code == 200

    set_enabled(browser, admin, "disabled")
    set_enabled(browser, admin, "enabled")
    for client, tab in ((browser, guest), (other_browser, other_guest)):
        assert client.get("/users/verification-status", headers=headers(tab)).status_code == 401
    register(other_browser)


def test_enabling_preserves_existing_guest_login_and_memory(browser):
    admin, _ = register(browser, "Admin")
    guest, _ = register(browser)
    with app_module.database_connection() as conn:
        login_id = conn.execute("SELECT login_id FROM tab_sessions WHERE tab_id = ?", (guest,)).fetchone()[0]
    memory_key = f"tab:{login_id}:default"
    app_module.conversation_sessions[memory_key] = {"memory": "old context"}

    set_enabled(browser, admin, "enabled")

    assert browser.get("/users/verification-status", headers=headers(guest)).status_code == 200
    assert app_module.conversation_sessions[memory_key] == {"memory": "old context"}
    with app_module.database_connection() as conn:
        assert conn.execute("SELECT login_id FROM tab_sessions WHERE tab_id = ?", (guest,)).fetchone()[0] == login_id


def test_logout_all_guests_also_removes_expired_logins_and_is_idempotent(browser):
    admin, _ = register(browser, "Admin")
    guest, _ = register(browser)
    expired_guest, _ = register(browser)
    with app_module.database_connection() as conn:
        logins = {row["tab_id"]: row["login_id"] for row in conn.execute("SELECT tab_id, login_id FROM tab_sessions")}
        conn.execute("UPDATE tab_sessions SET expires_at = 0 WHERE tab_id = ?", (expired_guest,))
    for login_id in logins.values():
        app_module.conversation_sessions[f"tab:{login_id}:default"] = {"memory": "old context"}

    assert app_module.logout_all_guests() == 2
    assert app_module.logout_all_guests() == 0

    with app_module.database_connection() as conn:
        assert [row["tab_id"] for row in conn.execute("SELECT tab_id FROM tab_sessions")] == [admin]
    assert set(app_module.conversation_sessions) == {f"tab:{logins[admin]}:default"}
    assert app_module.guest_is_enabled() is True


@pytest.mark.parametrize("role,status", [
    (None, None), ("Guest", None), ("Worker", None), ("Admin", "PENDING"), ("Admin", "REJECTED"),
])
def test_only_verified_admin_can_change_setting(browser, role, status):
    tab = str(uuid4())
    if role:
        tab, user_id = register(browser, role)
        if status:
            with app_module.database_connection() as conn:
                conn.execute("UPDATE users SET verification_status = ? WHERE id = ?", (status, user_id))
    response = browser.post("/guest/enable", headers=headers(tab), json={"enabled": "disabled"})
    assert response.status_code == 403
    assert app_module.guest_is_enabled() is True


@pytest.mark.parametrize("body", [None, [], "disabled", {}, {"enabled": None}, {"enabled": True},
                                      {"enabled": 0}, {"enabled": ""}, {"enabled": "enable"}])
def test_invalid_toggle_payloads_do_not_change_setting(browser, body):
    admin, _ = register(browser, "Admin")
    response = browser.post("/guest/enable", headers=headers(admin), data=json.dumps(body),
                            content_type="application/json")
    assert response.status_code == 400
    assert app_module.guest_is_enabled() is True


def test_disabled_guests_cannot_register_and_can_register_after_reenabling(browser):
    admin, _ = register(browser, "Admin")
    set_enabled(browser, admin, "disabled")
    tab = str(uuid4())
    response = browser.post("/users/register", headers=headers(tab), json={"role": "Guest"})
    assert response.status_code == 403
    with app_module.database_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM tab_sessions WHERE is_guest = 1").fetchone()[0] == 0
    set_enabled(browser, admin, "enabled")
    assert browser.post("/users/register", headers=headers(tab), json={"role": "Guest"}).status_code == 200


def test_guest_registration_rechecks_setting_before_creating_login(browser, monkeypatch):
    with app_module.database_connection() as conn:
        conn.execute("UPDATE app_settings SET guests_enabled = 0 WHERE id = 1")
    monkeypatch.setattr(app_module, "guest_is_enabled", lambda: True)

    response = browser.post("/users/register", headers=headers(str(uuid4())), json={"role": "Guest"})

    assert response.status_code == 403
    with app_module.database_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM tab_sessions").fetchone()[0] == 0


@pytest.mark.parametrize("operation", ["chat", "upload", "upload-without-file", "delete"])
def test_disabled_guest_actions_revoke_only_caller_before_side_effects(browser, operation):
    guest, guest_id = register(browser)
    other_guest, _ = register(browser)
    admin, _ = register(browser, "Admin")
    filepath = app_module.KNOWLEDGE_BASE_DIR / "notes.txt"
    filepath.write_text("existing content", encoding="utf-8")
    registry = {"notes.txt": {"guest_id": guest_id, "chunks": 1}}
    app_module._save_doc_registry(registry)
    with app_module.database_connection() as conn:
        logins = {row["tab_id"]: row["login_id"] for row in conn.execute("SELECT tab_id, login_id FROM tab_sessions")}
    for tab in (guest, other_guest, admin):
        app_module.conversation_sessions[f"tab:{logins[tab]}:default"] = {"memory": "old context"}
    # Exercise request-time enforcement when the setting changes outside the admin endpoint.
    with app_module.database_connection() as conn:
        conn.execute("UPDATE app_settings SET guests_enabled = 0 WHERE id = 1")

    if operation == "chat":
        response = browser.post("/chat", headers=headers(guest), json={"message": "question"})
    elif operation.startswith("upload"):
        data = {} if operation == "upload-without-file" else {"file": (io.BytesIO(b"new content"), "new.txt")}
        response = browser.post("/api/documents/upload", headers=headers(guest), data=data)
    else:
        response = browser.delete("/api/documents/notes.txt", headers=headers(guest))

    assert response.status_code == 403
    assert "disabled guest features" in response.get_json()["error"]
    assert filepath.read_text(encoding="utf-8") == "existing content"
    assert app_module._load_doc_registry() == registry
    assert not (app_module.KNOWLEDGE_BASE_DIR / "new.txt").exists()
    app_module.collection.delete.assert_not_called()
    app_module._ingest_file.assert_not_called()
    app_module.answer_question.assert_not_called()
    assert browser.get("/users/verification-status", headers=headers(guest)).status_code == 401
    for tab in (other_guest, admin):
        assert browser.get("/users/verification-status", headers=headers(tab)).status_code == 200
        assert f"tab:{logins[tab]}:default" in app_module.conversation_sessions
    assert f"tab:{logins[guest]}:default" not in app_module.conversation_sessions
    assert browser.post("/chat", headers=headers(admin), json={"message": "question"}).status_code == 200


@pytest.mark.parametrize("role,owner,allowed", [
    ("Guest", "self", True), ("Guest", "guest-other", False), ("Guest", None, False),
    ("Admin", "guest-other", False), ("Admin", None, True),
])
def test_document_delete_respects_owner(browser, role, owner, allowed):
    tab, user_id = register(browser, role)
    owner = user_id if owner == "self" else owner
    filepath = app_module.KNOWLEDGE_BASE_DIR / "notes.txt"
    filepath.write_text("content", encoding="utf-8")
    registry = {"notes.txt": {"guest_id": owner, "chunks": 1}}
    app_module._save_doc_registry(registry)

    response = browser.delete("/api/documents/notes.txt", headers=headers(tab))

    assert response.status_code == (200 if allowed else 403)
    if allowed:
        assert not filepath.exists()
        assert app_module._load_doc_registry() == {}
        app_module.collection.delete.assert_called_once()
    else:
        assert filepath.exists()
        assert app_module._load_doc_registry() == registry
        app_module.collection.delete.assert_not_called()


def test_enabled_guest_can_upload_and_chat(browser):
    tab, guest_id = register(browser)
    response = browser.post("/api/documents/upload", headers=headers(tab), data={
        "file": (io.BytesIO(b"content"), "notes.txt"),
    })
    assert response.status_code == 200
    assert app_module._load_doc_registry()["notes.txt"]["guest_id"] == guest_id
    assert browser.post("/chat", headers=headers(tab), json={"message": "question"}).status_code == 200
    assert app_module.answer_question.call_args.kwargs["guest_id"] == guest_id
