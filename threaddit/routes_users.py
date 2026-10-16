from typing import Literal

from fastapi import APIRouter, Request

from threaddit.core import (
    ApiError,
    hash_token,
    new_token,
    now,
    session,
    user_from_token,
)
from threaddit.schemas import LoginIn, MePatch, RegisterIn
from threaddit.views import user_json

router = APIRouter()


@router.post("/api/register", status_code=201)
def register(body: RegisterIn, request: Request):
    token = new_token()
    with request.app.state.db.tx(True) as conn:
        key = body.username.lower()
        if conn.execute("SELECT 1 FROM users WHERE username_key = ?", (key,)).fetchone():
            raise ApiError(409, "username_taken", "Username is already taken.")
        first = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
        user_id = conn.execute(
            "INSERT INTO users (username, username_key, account_type, status,"
            " is_superadmin, token_hash, created_at, description)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                body.username,
                key,
                body.account_type,
                "approved" if first else "pending",
                int(first),
                hash_token(token),
                now(),
                body.description,
            ),
        ).lastrowid
    return {
        "id": user_id,
        "username": body.username,
        "token": token,
        "account_type": body.account_type,
        "status": "approved" if first else "pending",
        "is_superadmin": first,
        "description": body.description,
    }


@router.post("/api/login")
def login(body: LoginIn, request: Request):
    with request.app.state.db.tx(False) as conn:
        return user_json(user_from_token(conn, body.token))


@router.get("/api/me")
def me(request: Request):
    with session(request) as (_, user):
        return user_json(user)


@router.patch("/api/me")
def edit_me(body: MePatch, request: Request):
    with session(request, write=True) as (conn, user):
        if user["account_type"] == "agent" and not body.description:
            raise ApiError(
                422, "invalid_input", "description is required for agent accounts."
            )
        conn.execute(
            "UPDATE users SET description = ? WHERE id = ?", (body.description, user["id"])
        )
        return user_json(
            conn.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
        )


@router.get("/api/users")
def list_users(request: Request):
    with session(request) as (conn, _):
        rows = conn.execute(
            "SELECT * FROM users WHERE status = 'approved' ORDER BY username_key"
        ).fetchall()
        return {"users": [user_json(r) for r in rows]}


@router.get("/api/admin/users")
def admin_list_users(
    request: Request, status: Literal["all", "pending", "approved"] = "all"
):
    with session(request, admin=True) as (conn, _):
        sql, args = "SELECT * FROM users", ()
        if status != "all":
            sql, args = sql + " WHERE status = ?", (status,)
        rows = conn.execute(sql + " ORDER BY id", args).fetchall()
        return {"users": [user_json(r) for r in rows]}


@router.post("/api/admin/users/{user_id}/approve")
def admin_approve(user_id: int, request: Request):
    with session(request, write=True, admin=True) as (conn, _):
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            raise ApiError(404, "user_not_found", f"User {user_id} does not exist.")
        conn.execute("UPDATE users SET status = 'approved' WHERE id = ?", (user_id,))
        return user_json(
            conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        )
