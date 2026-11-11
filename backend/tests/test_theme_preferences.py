"""Account theme persistence and safe migration of existing user databases."""
import sqlite3
from types import SimpleNamespace
from uuid import uuid4

import pytest

import app as app_module


@pytest.fixture
def database(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "USERS_DB_PATH", tmp_path / "users.db")
    monkeypatch.setitem(app_module.app.config, "TESTING", True)
    monkeypatch.setattr(app_module, "password_hasher", SimpleNamespace(
        hash=lambda password: f"test:{password}",
        verify=lambda password, hashed: hashed == f"test:{password}",
    ))


@pytest.fixture
def client(database):
    app_module._initialize_sqlite()
    with app_module.app.test_client() as browser:
        browser.environ_base["HTTP_X_TAB_ID"] = str(uuid4())
        assert browser.post("/users/session").status_code == 204
        yield browser


def register(client, username="worker@example.com", role="Worker", tab=None):
    response = client.post("/users/register", json={
        "username": username, "password": "test-password", "full_name": "Test User", "role": role,
    }, headers={"X-Tab-ID": tab} if tab else {})
    assert response.status_code in (200, 201)
    return response.get_json()["user_id"]


def saved_theme(client):
    response = client.get("/users/theme")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    return response.get_json()


def test_existing_users_migrate_without_losing_data_and_initialization_is_repeatable(database):
    app_module._create_roles_table()
    with app_module.database_connection() as conn:
        conn.execute("""
            CREATE TABLE users (
                id TEXT PRIMARY KEY NOT NULL,
                username TEXT UNIQUE NOT NULL,
                full_name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                role_id INTEGER NOT NULL,
                verification_status TEXT NOT NULL DEFAULT 'PENDING'
                    CHECK (verification_status IN ('VERIFIED', 'PENDING', 'REJECTED')),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (role_id) REFERENCES roles(id)
                    ON DELETE RESTRICT ON UPDATE CASCADE
            )
        """)
        conn.execute("""
            INSERT INTO users (id, username, full_name, password_hash, role_id, created_at)
            VALUES ('existing', 'existing@example.com', 'Existing User', 'existing-hash',
                    (SELECT id FROM roles WHERE name = 'Worker'), '2026-01-01 00:00:00')
        """)
        original = dict(conn.execute("SELECT * FROM users WHERE id = 'existing'").fetchone())

    app_module._initialize_sqlite()
    with app_module.database_connection() as conn:
        migrated = dict(conn.execute("SELECT * FROM users WHERE id = 'existing'").fetchone())
        assert migrated == {**original, "theme_preference": None}
        conn.execute("UPDATE users SET theme_preference = 'red' WHERE id = 'existing'")
    app_module._initialize_sqlite()
    with app_module.database_connection() as conn:
        row = dict(conn.execute("SELECT * FROM users WHERE id = 'existing'").fetchone())
        assert row == {**original, "theme_preference": "red"}
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE users SET theme_preference = 'invalid' WHERE id = 'existing'")


@pytest.mark.parametrize("theme", ["light", "dark", "red"])
@pytest.mark.parametrize("status", ["PENDING", "VERIFIED", "REJECTED"])
def test_account_can_save_each_theme_regardless_of_verification(client, theme, status):
    user_id = register(client)
    with app_module.database_connection() as conn:
        conn.execute("UPDATE users SET verification_status = ? WHERE id = ?", (status, user_id))
    initial = saved_theme(client)
    assert initial["theme"] is None
    assert initial["user_id"] == user_id
    response = client.put("/users/theme", json={**initial, "theme": theme})
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert saved_theme(client)["theme"] == theme


@pytest.mark.parametrize("theme", [None, "", "blue", "DARK", 1, True, [], {}])
def test_invalid_theme_is_rejected_without_overwriting_saved_value(client, theme):
    register(client)
    identity = saved_theme(client)
    assert client.put("/users/theme", json={**identity, "theme": "dark"}).status_code == 200
    response = client.put("/users/theme", json={**identity, "theme": theme})
    assert response.status_code == 400
    assert saved_theme(client)["theme"] == "dark"


@pytest.mark.parametrize("body", [[], "dark", 7, {"theme": "red"}, {"theme": "red", "user_id": [], "login_id": {}}])
def test_malformed_save_body_is_rejected(client, body):
    register(client)
    assert client.put("/users/theme", json=body).status_code == 400
    assert saved_theme(client)["theme"] is None


def test_malformed_json_is_rejected(client):
    register(client)
    response = client.put("/users/theme", data="{", content_type="application/json")
    assert response.status_code == 400


@pytest.mark.parametrize("method", ["GET", "HEAD", "PUT"])
def test_signed_out_requests_are_rejected(client, method):
    response = client.open("/users/theme", method=method, json={"theme": "red"})
    assert response.status_code == 401
    assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize("role", ["Worker", "Guest"])
def test_head_reads_theme_without_mutation(client, role):
    register(client, role=role)
    initial = saved_theme(client)
    if role == "Worker":
        assert client.put("/users/theme", json={**initial, "theme": "red"}).status_code == 200
        initial = saved_theme(client)
    response = client.head("/users/theme", json={**initial, "theme": "dark"})
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.data == b""
    assert saved_theme(client) == initial


def test_guests_have_no_account_theme_and_cannot_save_one(client):
    register(client, role="Guest")
    identity = saved_theme(client)
    assert identity["theme"] is None
    assert identity["user_id"] is None
    assert identity["login_id"]
    assert client.put("/users/theme", json={**identity, "theme": "red"}).status_code == 403


def test_theme_is_account_scoped_and_persists_after_logout_and_login(client):
    first_id = register(client)
    first = saved_theme(client)
    assert client.put("/users/theme", json={**first, "theme": "red"}).status_code == 200
    assert client.post("/users/logout").status_code == 204
    second_id = register(client, username="other@example.com")
    second = saved_theme(client)
    assert second["user_id"] == second_id
    assert second["theme"] is None
    # A late save from the previous account must not modify either account.
    assert client.put("/users/theme", json={**first, "theme": "dark"}).status_code == 409
    assert saved_theme(client)["theme"] is None
    assert client.post("/users/logout").status_code == 204
    response = client.post("/users/login", json={
        "username": "worker@example.com", "password": "test-password",
    })
    assert response.status_code == 200
    restored = saved_theme(client)
    assert restored["user_id"] == first_id
    assert restored["theme"] == "red"
    assert restored["login_id"] != first["login_id"]
    assert client.put("/users/theme", json={**first, "theme": "dark"}).status_code == 409


def test_other_tab_identity_cannot_be_used_to_change_its_theme(client):
    first_id = register(client)
    first = saved_theme(client)
    other_tab = str(uuid4())
    other_id = register(client, username="other@example.com", tab=other_tab)
    other = client.get("/users/theme", headers={"X-Tab-ID": other_tab}).get_json()
    assert other["user_id"] == other_id
    assert client.put("/users/theme", json={**other, "theme": "red"}).status_code == 409
    assert client.put("/users/theme", json={**first, "user_id": other_id, "theme": "red"}).status_code == 409
    assert saved_theme(client) == first
    with app_module.database_connection() as conn:
        assert {row["id"]: row["theme_preference"] for row in conn.execute("SELECT * FROM users")} == {
            first_id: None, other_id: None,
        }


def test_revocation_after_identity_lookup_prevents_the_write(client, monkeypatch):
    register(client)
    identity = saved_theme(client)
    original_current_user = app_module._current_user

    def revoke_after_lookup():
        user = original_current_user()
        with app_module.database_connection() as conn:
            conn.execute("DELETE FROM tab_sessions WHERE login_id = ?", (user["login_id"],))
        return user

    monkeypatch.setattr(app_module, "_current_user", revoke_after_lookup)
    assert client.put("/users/theme", json={**identity, "theme": "red"}).status_code == 409
    with app_module.database_connection() as conn:
        assert conn.execute("SELECT theme_preference FROM users").fetchone()["theme_preference"] is None
