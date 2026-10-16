import hashlib
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from fastapi import Request


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def user_from_token(conn: sqlite3.Connection, token: str) -> sqlite3.Row:
    """Resolve a token to an approved user; pending accounts get no access."""
    user = conn.execute(
        "SELECT * FROM users WHERE token_hash = ?", (hash_token(token),)
    ).fetchone()
    if user is None:
        raise ApiError(401, "invalid_token", "Unknown token.")
    if user["status"] != "approved":
        raise ApiError(
            403,
            "account_pending",
            "Account is pending approval by the superadmin.",
        )
    return user


def authenticate(conn: sqlite3.Connection, request: Request) -> sqlite3.Row:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise ApiError(
            401, "unauthenticated", "Send 'Authorization: Bearer <token>'."
        )
    return user_from_token(conn, token.strip())


@contextmanager
def session(request: Request, *, write: bool = False, admin: bool = False):
    """One transaction plus an authenticated approved user: yields (conn, user)."""
    with request.app.state.db.tx(write) as conn:
        user = authenticate(conn, request)
        if admin and not user["is_superadmin"]:
            raise ApiError(403, "forbidden", "Superadmin only.")
        yield conn, user
