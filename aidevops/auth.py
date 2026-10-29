"""SQLite-backed admin credentials and browser sessions."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import sqlite3
import time
from contextlib import closing
from pathlib import Path

_HASH_ALGORITHM = "pbkdf2_sha256"
_HASH_ITERATIONS = 600_000
_SESSION_TTL_SECONDS = 12 * 60 * 60
_DUMMY_SALT = b"aidevops-login-dummy"


def _hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, _HASH_ITERATIONS
    )
    return "$".join(
        (
            _HASH_ALGORITHM,
            str(_HASH_ITERATIONS),
            base64.b64encode(salt).decode("ascii"),
            base64.b64encode(derived).decode("ascii"),
        )
    )


_DUMMY_HASH = _hash_password("invalid-login", _DUMMY_SALT)


def _verify_password(password: str, encoded_hash: str) -> bool:
    try:
        algorithm, iterations, salt_text, digest_text = encoded_hash.split("$")
        if algorithm != _HASH_ALGORITHM or int(iterations) != _HASH_ITERATIONS:
            return False
        salt = base64.b64decode(salt_text, validate=True)
        expected = base64.b64decode(digest_text, validate=True)
        if len(salt) < 16 or len(expected) != hashlib.sha256().digest_size:
            return False
        actual = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            _HASH_ITERATIONS,
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


class AuthStore:
    """Persists a bootstrap admin account and opaque, expiring sessions."""

    def __init__(
        self,
        db_path: Path | str,
        *,
        admin_username: str,
        admin_password: str,
    ) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", admin_username):
            raise ValueError(
                "AIDEVOPS_ADMIN_USERNAME must contain 1-64 letters, digits, dots, "
                "underscores, or hyphens"
            )
        if len(admin_password) < 8 or len(admin_password) > 1024:
            raise ValueError(
                "AIDEVOPS_ADMIN_PASSWORD must be between 8 and 1024 characters"
            )

        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.db_path, timeout=30)) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    username TEXT PRIMARY KEY COLLATE NOCASE,
                    password_hash TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS auth_sessions (
                    token_hash TEXT PRIMARY KEY,
                    username TEXT NOT NULL COLLATE NOCASE
                        REFERENCES users(username) ON DELETE CASCADE,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_auth_sessions_expiry
                    ON auth_sessions(expires_at);
                """
            )
            conn.execute(
                """
                INSERT INTO users (username, password_hash, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(username) DO UPDATE SET
                    password_hash = excluded.password_hash
                """,
                (admin_username, _hash_password(admin_password), time.time()),
            )
            conn.commit()

    def authenticate(self, username: str, password: str) -> str | None:
        with closing(sqlite3.connect(self.db_path, timeout=30)) as conn:
            row = conn.execute(
                "SELECT username, password_hash FROM users WHERE username = ?",
                (username,),
            ).fetchone()

        if row is None:
            _verify_password(password, _DUMMY_HASH)
            return None
        return row[0] if _verify_password(password, row[1]) else None

    def create_user(self, username: str, password: str) -> bool:
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", username):
            raise ValueError("Username must contain 1-64 letters, digits, dots, underscores, or hyphens")
        if len(password) < 8 or len(password) > 1024:
            raise ValueError("Password must be between 8 and 1024 characters")

        try:
            with closing(sqlite3.connect(self.db_path, timeout=30)) as conn:
                conn.execute(
                    "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                    (username, _hash_password(password), time.time()),
                )
                conn.commit()
        except sqlite3.IntegrityError:
            return False
        return True

    def create_session(self, username: str) -> tuple[str, int]:
        token = secrets.token_urlsafe(32)
        now = time.time()
        expires_at = now + _SESSION_TTL_SECONDS
        token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
        with closing(sqlite3.connect(self.db_path, timeout=30)) as conn:
            conn.execute("DELETE FROM auth_sessions WHERE expires_at <= ?", (now,))
            conn.execute(
                """
                INSERT INTO auth_sessions (token_hash, username, created_at, expires_at)
                VALUES (?, ?, ?, ?)
                """,
                (token_hash, username, now, expires_at),
            )
            conn.commit()
        return token, _SESSION_TTL_SECONDS

    def get_session_username(self, token: str) -> str | None:
        token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
        with closing(sqlite3.connect(self.db_path, timeout=30)) as conn:
            row = conn.execute(
                """
                SELECT username
                FROM auth_sessions
                WHERE token_hash = ? AND expires_at > ?
                """,
                (token_hash, time.time()),
            ).fetchone()
        return row[0] if row else None

    def revoke_session(self, token: str) -> None:
        token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
        with closing(sqlite3.connect(self.db_path, timeout=30)) as conn:
            conn.execute(
                "DELETE FROM auth_sessions WHERE token_hash = ?", (token_hash,)
            )
            conn.commit()
