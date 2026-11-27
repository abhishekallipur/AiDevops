"""Shared administrator-only dependencies for management APIs."""

from __future__ import annotations

import re

from fastapi import HTTPException, Request

from ..auth import SESSION_COOKIE

_SESSION_TOKEN = re.compile(r"^[A-Za-z0-9_-]{20,128}$")


def require_admin(request: Request, capability: str = "management") -> str:
    token = request.cookies.get(SESSION_COOKIE, "")
    if not _SESSION_TOKEN.fullmatch(token):
        raise HTTPException(status_code=401, detail="Not authenticated.")
    username = request.app.state.auth_store.get_session_username(token)
    if username is None:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    admin_username = request.app.state.settings.admin_username
    if username.casefold() != admin_username.casefold():
        raise HTTPException(
            status_code=403,
            detail=(
                f"Signed in as '{username}'; {capability} is restricted to the "
                f"configured administrator '{admin_username}'. Sign out and use that account."
            ),
        )
    return username
