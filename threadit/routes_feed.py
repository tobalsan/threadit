from typing import Literal

from fastapi import APIRouter, Query, Request

from threadit.core import session
from threadit.views import fetch_messages

router = APIRouter()


def _like(term: str) -> str:
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _snippet(body: str, term: str, width: int = 200) -> str:
    at = body.lower().find(term.lower())
    start = max(0, at - width // 4)
    cut = body[start : start + width]
    return ("…" if start else "") + cut + ("…" if start + width < len(body) else "")


@router.get("/api/search")
def search(
    request: Request,
    q: str = Query(min_length=1, max_length=200),
    include_closed: bool = False,
    area_id: int | None = None,
    limit: int = Query(50, ge=1, le=200),
    areas_offset: int = Query(0, ge=0),
    threads_offset: int = Query(0, ge=0),
    messages_offset: int = Query(0, ge=0),
):
    term = q.strip()
    pattern = _like(term)
    with session(request) as (conn, _):
        area_clause = " AND a.id = ?" if area_id is not None else ""
        area_args = (area_id,) if area_id is not None else ()
        open_clause = "" if include_closed else " AND t.closed_reason IS NULL"

        areas = conn.execute(
            "SELECT a.id, a.name, a.slug, a.description FROM areas a"
            " WHERE (a.name LIKE ? ESCAPE '\\' OR a.description LIKE ? ESCAPE '\\')"
            + area_clause
            + " ORDER BY a.name_key LIMIT ? OFFSET ?",
            (pattern, pattern, *area_args, limit + 1, areas_offset),
        ).fetchall()
        threads = conn.execute(
            "SELECT t.id, t.title, t.area_id, a.name AS area_name, a.slug AS area_slug, t.closed_reason,"
            " t.edited_at"
            " FROM threads t JOIN areas a ON a.id = t.area_id"
            " WHERE t.title LIKE ? ESCAPE '\\'" + area_clause + open_clause
            + " ORDER BY t.last_activity_at DESC, t.id DESC LIMIT ? OFFSET ?",
            (pattern, *area_args, limit + 1, threads_offset),
        ).fetchall()
        message_rows = conn.execute(
            "SELECT m.id, t.closed_reason FROM messages m"
            " JOIN threads t ON t.id = m.thread_id JOIN areas a ON a.id = t.area_id"
            " WHERE m.body LIKE ? ESCAPE '\\'" + area_clause + open_clause
            + " ORDER BY m.id DESC LIMIT ? OFFSET ?",
            (pattern, *area_args, limit + 1, messages_offset),
        ).fetchall()
        has_more = {
            "areas": len(areas) > limit,
            "threads": len(threads) > limit,
            "messages": len(message_rows) > limit,
        }
        areas, threads, message_rows = areas[:limit], threads[:limit], message_rows[:limit]
        closed_by_message = {r["id"]: r["closed_reason"] for r in message_rows}
        ids = list(closed_by_message)
        found = (
            fetch_messages(
                conn,
                0,
                f"m.id IN ({','.join('?' * len(ids))})",
                tuple(ids),
                order="m.id DESC",
            )
            if ids
            else []
        )
        return {
            "query": term,
            "has_more": has_more,
            "areas": [
                {
                    "id": r["id"],
                    "name": r["name"],
                    "slug": r["slug"],
                    "snippet": _snippet(r["description"], term),
                }
                for r in areas
            ],
            "threads": [
                {
                    "id": r["id"],
                    "title": r["title"],
                    "area_id": r["area_id"],
                    "area_name": r["area_name"],
                    "area_slug": r["area_slug"],
                    "closed_reason": r["closed_reason"],
                    "edited_at": r["edited_at"],
                }
                for r in threads
            ],
            "messages": [
                {
                    "id": m["id"],
                    "thread_id": m["thread_id"],
                    "thread_title": m["thread_title"],
                    "area_id": m["area_id"],
                    "area_name": m["area_name"],
                    "area_slug": m["area_slug"],
                    "parent_id": m["parent_id"],
                    "author": m["author"],
                    "created_at": m["created_at"],
                    "edited_at": m["edited_at"],
                    "snippet": _snippet(m["body"], term),
                    "closed_reason": closed_by_message[m["id"]],
                    "context_url": m["context_url"],
                }
                for m in found
            ],
        }


@router.get("/api/activity")
def activity(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    before_id: int | None = None,
):
    with session(request) as (conn, _):
        where, args = "1=1", []
        if before_id is not None:
            where, args = "e.id < ?", [before_id]
        rows = conn.execute(
            f"""SELECT e.id, e.kind, e.detail, e.created_at, e.area_id, e.thread_id, e.message_id,
                       u.id AS actor_id, u.username AS actor_username, u.account_type AS actor_type,
                       a.name AS area_name, a.slug AS area_slug, t.title AS thread_title,
                       t.closed_reason
                FROM events e JOIN users u ON u.id = e.actor_id
                LEFT JOIN areas a ON a.id = e.area_id
                LEFT JOIN threads t ON t.id = e.thread_id
                WHERE {where} ORDER BY e.id DESC LIMIT ?""",
            (*args, limit),
        ).fetchall()
        return {
            "events": [
                {
                    "id": r["id"],
                    "kind": r["kind"],
                    "detail": r["detail"],
                    "created_at": r["created_at"],
                    "actor": {
                        "id": r["actor_id"],
                        "username": r["actor_username"],
                        "account_type": r["actor_type"],
                    },
                    "area_id": r["area_id"],
                    "area_name": r["area_name"],
                    "area_slug": r["area_slug"],
                    "thread_id": r["thread_id"],
                    "thread_title": r["thread_title"],
                    "thread_closed_reason": r["closed_reason"],
                    "message_id": r["message_id"],
                    "context_url": (
                        f"/api/messages/{r['message_id']}/context" if r["message_id"] else None
                    ),
                }
                for r in rows
            ]
        }


@router.get("/api/attention")
def attention(
    request: Request,
    status: Literal[
        "all", "unacknowledged", "processing", "processed", "acknowledged"
    ] = "all",
    include_closed: bool = False,
    order: Literal["asc", "desc"] = "asc",
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    with session(request) as (conn, user):
        where, params = "att.message_id IS NOT NULL", []
        if status != "all":
            where += " AND att.status = ?"
            params.append(status)
        if not include_closed:
            where += " AND t.closed_reason IS NULL"
        items = fetch_messages(
            conn,
            user["id"],
            where,
            tuple(params),
            order=f"m.id {order.upper()}",
            limit=limit + 1,
            offset=offset,
        )
        return {"items": items[:limit], "has_more": len(items) > limit}
