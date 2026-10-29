import sqlite3

from aidevops.api import main as api_main
from aidevops.auth import AuthStore


def test_login_page_is_served_by_backend(client):
    response = client.get("/login")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert 'id="username"' in response.text
    assert '"/api/auth/login"' in response.text
    assert '"/api/auth/register"' in response.text
    assert 'id="mode-toggle"' in response.text


def test_login_page_uses_saved_dashboard_theme(client, monkeypatch, tmp_path):
    theme_settings = tmp_path / "ui_theme.json"
    theme_settings.write_text('{"theme":"dark"}', encoding="utf-8")
    monkeypatch.setattr(api_main, "THEME_SETTINGS_PATH", theme_settings)

    response = client.get("/login")

    assert response.status_code == 200
    assert '<html lang="en" data-theme="dark">' in response.text
    assert 'body[data-theme="light"] .login-card' in response.text


def test_admin_login_persists_only_a_password_hash(client, settings):
    response = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "admin123"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "authenticated": True,
        "username": "admin",
        "redirect_url": "http://127.0.0.1:8501",
    }
    assert "httponly" in response.headers["set-cookie"].lower()

    with sqlite3.connect(settings.db_path) as conn:
        username, password_hash = conn.execute(
            "SELECT username, password_hash FROM users WHERE username = 'admin'"
        ).fetchone()
        token_hash, = conn.execute(
            "SELECT token_hash FROM auth_sessions"
        ).fetchone()

    assert username == "admin"
    assert password_hash != "admin123"
    assert password_hash.startswith("pbkdf2_sha256$")
    assert token_hash not in response.headers["set-cookie"]


def test_login_rejects_invalid_credentials_without_creating_session(client, settings):
    response = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "incorrect"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid username or password."
    with sqlite3.connect(settings.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM auth_sessions").fetchone()[0] == 0


def test_signup_creates_user_hash_then_requires_login(client, settings):
    response = client.post(
        "/api/auth/register",
        json={"username": "new-user", "password": "secure-password"},
    )

    assert response.status_code == 201
    assert response.json()["registered"] is True
    assert response.json()["username"] == "new-user"
    assert "set-cookie" not in response.headers
    assert client.get("/api/auth/me").status_code == 401

    with sqlite3.connect(settings.db_path) as conn:
        password_hash = conn.execute(
            "SELECT password_hash FROM users WHERE username = 'new-user'"
        ).fetchone()[0]
    assert password_hash != "secure-password"
    assert password_hash.startswith("pbkdf2_sha256$")

    login = client.post(
        "/api/auth/login",
        json={"username": "new-user", "password": "secure-password"},
    )
    assert login.status_code == 200
    assert login.json()["authenticated"] is True
    assert client.get("/api/auth/me").json() == {"username": "new-user"}


def test_signup_rejects_duplicate_username_case_insensitively(client, settings):
    response = client.post(
        "/api/auth/register",
        json={"username": "ADMIN", "password": "another-password"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Username is already taken."


def test_signup_rejects_short_password(client):
    response = client.post(
        "/api/auth/register",
        json={"username": "new-user", "password": "short"},
    )

    assert response.status_code == 422


def test_authenticated_session_can_be_checked_and_revoked(client):
    login = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "admin123"},
    )
    assert login.status_code == 200
    assert client.get("/api/auth/me").json() == {"username": "admin"}

    logout = client.post("/api/auth/logout")
    assert logout.status_code == 200
    assert logout.json() == {"authenticated": False}
    assert client.get("/api/auth/me").status_code == 401


def test_dashboard_logout_link_revokes_session_and_redirects_to_login(client):
    login = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "admin123"},
    )
    assert login.status_code == 200
    assert client.get("/api/auth/me").status_code == 200

    logout_page = client.get("/logout")
    assert logout_page.status_code == 200
    assert 'method="post"' in logout_page.text
    assert client.get("/api/auth/me").status_code == 200

    logout = client.post(
        "/api/auth/logout?redirect_to_login=true",
        follow_redirects=False,
    )
    assert logout.status_code == 303
    assert logout.headers["location"] == "/login"
    assert client.get("/api/auth/me").status_code == 401


def test_sidebar_logout_route_ends_session_and_returns_to_login(client):
    login = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "admin123"},
    )
    assert login.status_code == 200
    assert client.get("/api/auth/me").status_code == 200

    logout_page = client.get("/logout")
    assert logout_page.status_code == 200
    assert 'method="post"' in logout_page.text
    assert "/api/auth/logout?redirect_to_login=true" in logout_page.text

    logout = client.post(
        "/api/auth/logout?redirect_to_login=true",
        follow_redirects=False,
    )
    assert logout.status_code == 303
    assert logout.headers["location"] == "/login"
    assert "max-age=0" in logout.headers["set-cookie"].lower()
    assert client.get("/api/auth/me").status_code == 401


def test_admin_password_configuration_updates_existing_user(client, settings):
    AuthStore(
        settings.db_path,
        admin_username="admin",
        admin_password="different-admin-password",
    )

    assert client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "different-admin-password"},
    ).status_code == 200
    assert client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "admin123"},
    ).status_code == 401
