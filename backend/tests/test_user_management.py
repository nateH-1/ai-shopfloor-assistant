import pytest
import time
from uuid import uuid4

import app as app_module


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "USERS_DB_PATH", tmp_path / "users.db")
    monkeypatch.setitem(app_module.app.config, "TESTING", True)
    app_module._create_roles_table()
    app_module._create_users_table()
    app_module._create_tab_sessions_table()
    with app_module.database_connection() as conn:
        for user_id, role in [("admin", "Admin"), ("target", "Worker")]:
            conn.execute("""
                INSERT INTO users (id, username, full_name, password_hash, role_id, verification_status)
                VALUES (?, ?, ?, 'unused-test-hash', (SELECT id FROM roles WHERE name = ?), 'VERIFIED')
            """, (user_id, f"{user_id}@example.com", user_id, role))
    with app_module.app.test_client() as client:
        tab_id = str(uuid4())
        browser_id = "test-browser"
        client.environ_base["HTTP_X_TAB_ID"] = tab_id
        with client.session_transaction() as session:
            session["browser_session_id"] = browser_id
        with app_module.database_connection() as conn:
            conn.execute("INSERT INTO tab_sessions VALUES (?, ?, ?, ?, ?, ?)",
                         (browser_id, tab_id, "admin", 0, str(uuid4()), time.time() + 3600))
        yield client


def test_delete_user_persists_and_missing_user_returns_404(client):
    response = client.delete("/users/delete", json={"user_id": "target"})
    assert response.status_code == 200
    listed = client.get("/users").get_json()["verified_users"]
    assert [user["id"] for user in listed] == ["admin"]
    assert client.delete("/users/delete", json={"user_id": "target"}).status_code == 404


@pytest.mark.parametrize("role", ["Worker", "Admin"])
def test_change_role_persists(client, role):
    # Start with the opposite role so both cases verify a persisted change.
    with app_module.database_connection() as conn:
        conn.execute(
            "UPDATE users SET role_id = (SELECT id FROM roles WHERE name = ?) WHERE id = 'target'",
            ("Admin" if role == "Worker" else "Worker",),
        )
    response = client.post("/users/change-role", json={"user_id": "target", "role": role})
    assert response.status_code == 200
    users = client.get("/users").get_json()["verified_users"]
    assert next(user for user in users if user["id"] == "target")["name"] == role


def test_change_role_missing_user_returns_404(client):
    response = client.post("/users/change-role", json={"user_id": "missing", "role": "Admin"})
    assert response.status_code == 404


@pytest.mark.parametrize("role", [None, "Guest", "Owner", [], {}])
def test_invalid_role_is_rejected(client, role):
    assert client.post("/users/change-role", json={"user_id": "target", "role": role}).status_code == 400


@pytest.mark.parametrize("path,method", [("/users/delete", "DELETE"), ("/users/change-role", "POST")])
@pytest.mark.parametrize("user_id", [None, "", "   ", 123, []])
def test_invalid_user_id_is_rejected(client, path, method, user_id):
    assert client.open(path, method=method, json={"user_id": user_id, "role": "Worker"}).status_code == 400


@pytest.mark.parametrize("path,method", [("/users/delete", "DELETE"), ("/users/change-role", "POST")])
def test_non_object_body_is_rejected(client, path, method):
    assert client.open(path, method=method, json=[]).status_code == 400


@pytest.mark.parametrize("identity", [None, "target", "missing"])
@pytest.mark.parametrize("path,method", [("/users/delete", "DELETE"), ("/users/change-role", "POST")])
def test_non_admin_cannot_mutate_users(client, identity, path, method):
    with client.session_transaction() as session:
        session.clear()
        if identity:
            session["user_id"] = identity
            session["role"] = "Admin"  # An old cookie must not grant access.
    assert client.open(path, method=method, json={"user_id": "target", "role": "Admin"}).status_code == 403


@pytest.mark.parametrize("deleted", [False, True])
def test_old_admin_session_loses_access_after_account_change(client, deleted):
    with app_module.database_connection() as conn:
        if deleted:
            conn.execute("DELETE FROM users WHERE id = 'admin'")
        else:
            conn.execute("UPDATE users SET role_id = (SELECT id FROM roles WHERE name = 'Worker') WHERE id = 'admin'")
    assert client.get("/users").status_code == 403
    assert client.post("/users/verify", json={"user_id": "target", "verification_status": "VERIFIED"}).status_code == 403
    assert client.delete("/users/delete", json={"user_id": "target"}).status_code == 403
    assert client.post("/users/change-role", json={"user_id": "target", "role": "Admin"}).status_code == 403
    permissions = client.post("/roles/permissions")
    if deleted:
        assert permissions.status_code == 401
    else:
        assert permissions.get_json()["name"] == "Worker"


def test_self_delete_revokes_login_and_preserves_browser_cookie(client):
    assert client.delete("/users/delete", json={"user_id": "admin"}).status_code == 200
    with client.session_transaction() as session:
        assert "user_id" not in session
        assert session["browser_session_id"] == "test-browser"
    assert client.get("/users/verification-status").status_code == 401
    with app_module.database_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM tab_sessions WHERE user_id = 'admin'").fetchone()[0] == 0


def test_self_role_change_is_reflected_in_next_request(client):
    assert client.post("/users/change-role", json={"user_id": "admin", "role": "Worker"}).status_code == 200
    assert client.post("/roles/permissions").get_json()["name"] == "Worker"
    assert client.get("/users").status_code == 403


def test_logout_revokes_tab_login_without_expiring_cookie(client):
    response = client.post("/users/logout")
    assert response.status_code == 204
    assert "Set-Cookie" not in response.headers
    with client.session_transaction() as session:
        assert dict(session) == {"browser_session_id": "test-browser"}
    assert client.get("/users/verification-status").status_code == 401
    assert client.get("/users").status_code == 403
    assert client.post("/users/logout").status_code == 204


def test_logout_requires_post(client):
    assert client.get("/users/logout").status_code == 405
    assert client.post("/roles/permissions").get_json()["name"] == "Admin"
