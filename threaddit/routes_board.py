import sqlite3
from typing import Literal

from fastapi import APIRouter, Query, Request

from threaddit.attention import (
    RESERVED,
    acknowledge_human,
    agent_reaction_added,
    agent_reaction_removed,
)
from threaddit.core import ApiError, now, session
from threaddit.schemas import (
    AreaIn,
    AreaPatch,
    CloseIn,
    MessageIn,
    PinIn,
    ReactionIn,
    ThreadIn,
    VoteIn,
)
from threaddit.service import (
    add_event,
    get_message_row,
    get_thread_row,
    insert_message,
    require_open,
)
from threaddit.views import (
    area_json,
    fetch_messages,
    fetch_threads,
    get_area,
    get_message_json,
    get_thread_json,
    list_areas,
)

router = APIRouter()


# ---------- areas ----------


def _check_area_name_free(conn: sqlite3.Connection, name: str, own_id: int = 0) -> None:
    taken = conn.execute(
        "SELECT 1 FROM areas WHERE name_key = ? AND id != ?", (name.lower(), own_id)
    ).fetchone()
    if taken:
        raise ApiError(409, "area_exists", "An area with this name already exists.")


@router.get("/api/areas")
def areas(request: Request):
    with session(request) as (conn, _):
        return {"areas": list_areas(conn)}


@router.post("/api/areas", status_code=201)
def create_area(body: AreaIn, request: Request):
    with session(request, write=True) as (conn, user):
        _check_area_name_free(conn, body.name)
        ts = now()
        area_id = conn.execute(
            "INSERT INTO areas (name, name_key, description, created_by, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (body.name, body.name.lower(), body.description, user["id"], ts, ts),
        ).lastrowid
        add_event(conn, "area_created", user["id"], area_id)
        return area_json(get_area(conn, area_id))


@router.get("/api/areas/{area_id}")
def read_area(area_id: int, request: Request):
    with session(request) as (conn, _):
        return area_json(get_area(conn, area_id))


@router.patch("/api/areas/{area_id}")
def edit_area(area_id: int, body: AreaPatch, request: Request):
    with session(request, write=True) as (conn, user):
        area = get_area(conn, area_id)
        name = body.name if body.name is not None else area["name"]
        description = (
            body.description if body.description is not None else area["description"]
        )
        _check_area_name_free(conn, name, area_id)
        conn.execute(
            "UPDATE areas SET name = ?, name_key = ?, description = ?, updated_at = ?"
            " WHERE id = ?",
            (name, name.lower(), description, now(), area_id),
        )
        add_event(conn, "area_updated", user["id"], area_id)
        return area_json(get_area(conn, area_id))


# ---------- threads ----------


def _thread_detail(conn: sqlite3.Connection, viewer_id: int, thread_id: int) -> dict:
    thread = get_thread_json(conn, viewer_id, thread_id)
    return {
        "thread": thread,
        "area": area_json(get_area(conn, thread["area_id"])),
        "messages": fetch_messages(conn, viewer_id, "m.thread_id = ?", (thread_id,)),
    }


@router.get("/api/threads")
def list_threads(
    request: Request,
    area_id: int | None = None,
    state: Literal["active", "closed", "all"] = "active",
    sort: Literal["created", "activity", "importance"] = "importance",
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    with session(request) as (conn, user):
        clauses, params = [], []
        if area_id is not None:
            clauses.append("t.area_id = ?")
            params.append(area_id)
        if state == "active":
            clauses.append("t.closed_reason IS NULL")
        elif state == "closed":
            clauses.append("t.closed_reason IS NOT NULL")
        base = " AND ".join(clauses) or "1=1"
        pinned = fetch_threads(conn, user["id"], base + " AND t.pinned = 1", tuple(params), sort)
        rest = fetch_threads(
            conn, user["id"], base + " AND t.pinned = 0", tuple(params), sort, limit + 1, offset
        )
        return {"pinned": pinned, "threads": rest[:limit], "has_more": len(rest) > limit}


@router.post("/api/threads", status_code=201)
def create_thread(body: ThreadIn, request: Request):
    with session(request, write=True) as (conn, user):
        get_area(conn, body.area_id)
        ts = now()
        thread_id = conn.execute(
            "INSERT INTO threads (area_id, title, owner_id, created_at, last_activity_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (body.area_id, body.title, user["id"], ts, ts),
        ).lastrowid
        thread = get_thread_row(conn, thread_id)
        insert_message(conn, thread, user, body.body, None, is_op=True)
        add_event(conn, "thread_created", user["id"], body.area_id, thread_id)
        return _thread_detail(conn, user["id"], thread_id)


@router.get("/api/threads/{thread_id}")
def read_thread(thread_id: int, request: Request):
    with session(request) as (conn, user):
        return _thread_detail(conn, user["id"], thread_id)


@router.get("/api/threads/{thread_id}/messages")
def read_thread_messages(
    thread_id: int, request: Request, top_level_only: bool = False
):
    with session(request) as (conn, user):
        get_thread_row(conn, thread_id)
        where = "m.thread_id = ?" + (" AND m.parent_id IS NULL" if top_level_only else "")
        return {"messages": fetch_messages(conn, user["id"], where, (thread_id,))}


@router.post("/api/threads/{thread_id}/messages", status_code=201)
def post_message(thread_id: int, body: MessageIn, request: Request):
    with session(request, write=True) as (conn, user):
        thread = get_thread_row(conn, thread_id)
        require_open(thread)
        message_id = insert_message(conn, thread, user, body.body, body.parent_id)
        return get_message_json(conn, user["id"], message_id)


@router.post("/api/threads/{thread_id}/close")
def close_thread(thread_id: int, body: CloseIn, request: Request):
    with session(request, write=True) as (conn, user):
        thread = get_thread_row(conn, thread_id)
        if thread["closed_reason"]:
            raise ApiError(
                409, "already_closed", f"Thread {thread_id} is already closed."
            )
        ts = now()
        conn.execute(
            "UPDATE threads SET closed_reason = ?, closed_at = ?, closed_by = ?,"
            " last_activity_at = ? WHERE id = ?",
            (body.reason, ts, user["id"], ts, thread_id),
        )
        add_event(
            conn, "thread_closed", user["id"], thread["area_id"], thread_id, None, body.reason
        )
        return get_thread_json(conn, user["id"], thread_id)


@router.post("/api/threads/{thread_id}/reopen")
def reopen_thread(thread_id: int, request: Request):
    with session(request, write=True) as (conn, user):
        thread = get_thread_row(conn, thread_id)
        if not thread["closed_reason"]:
            raise ApiError(409, "not_closed", f"Thread {thread_id} is not closed.")
        conn.execute(
            "UPDATE threads SET closed_reason = NULL, closed_at = NULL, closed_by = NULL,"
            " last_activity_at = ? WHERE id = ?",
            (now(), thread_id),
        )
        add_event(conn, "thread_reopened", user["id"], thread["area_id"], thread_id)
        return get_thread_json(conn, user["id"], thread_id)


@router.put("/api/threads/{thread_id}/pin")
def pin_thread(thread_id: int, body: PinIn, request: Request):
    with session(request, write=True) as (conn, user):
        thread = get_thread_row(conn, thread_id)
        require_open(thread)
        if thread["owner_id"] != user["id"]:
            raise ApiError(403, "not_owner", "Only the thread owner can pin or unpin it.")
        conn.execute(
            "UPDATE threads SET pinned = ? WHERE id = ?", (int(body.pinned), thread_id)
        )
        add_event(
            conn,
            "thread_pinned" if body.pinned else "thread_unpinned",
            user["id"],
            thread["area_id"],
            thread_id,
        )
        return get_thread_json(conn, user["id"], thread_id)


# ---------- messages ----------


def _writable_message(conn: sqlite3.Connection, message_id: int) -> sqlite3.Row:
    message = get_message_row(conn, message_id)
    require_open(get_thread_row(conn, message["thread_id"]))
    return message


@router.get("/api/messages/{message_id}")
def read_message(message_id: int, request: Request):
    with session(request) as (conn, user):
        return get_message_json(conn, user["id"], message_id)


@router.get("/api/messages/{message_id}/context")
def message_context(message_id: int, request: Request):
    """Top-level messages through the target's top-level ancestor, plus the ancestor
    chain down to the target. Sibling branches and later top-level messages are pruned."""
    with session(request) as (conn, user):
        target = get_message_row(conn, message_id)
        chain_ids = [target["id"]]
        parent_id = target["parent_id"]
        while parent_id is not None:
            chain_ids.append(parent_id)
            parent_id = conn.execute(
                "SELECT parent_id FROM messages WHERE id = ?", (parent_id,)
            ).fetchone()[0]
        chain_ids.reverse()
        root_id, below_root = chain_ids[0], chain_ids[1:]
        thread = get_thread_json(conn, user["id"], target["thread_id"])
        top_level = fetch_messages(
            conn,
            user["id"],
            "m.thread_id = ? AND m.parent_id IS NULL AND m.id <= ?",
            (target["thread_id"], root_id),
        )
        by_id = {
            m["id"]: m
            for m in fetch_messages(
                conn, user["id"], f"m.id IN ({','.join('?' * len(below_root))})", tuple(below_root)
            )
        } if below_root else {}
        return {
            "area": area_json(get_area(conn, thread["area_id"])),
            "thread": thread,
            "target_id": message_id,
            "top_level": top_level,
            "chain": [by_id[i] for i in below_root],
        }


@router.post("/api/messages/{message_id}/votes")
def vote(message_id: int, body: VoteIn, request: Request):
    with session(request, write=True) as (conn, user):
        _writable_message(conn, message_id)
        conn.execute(
            "UPDATE messages SET score = score + ? WHERE id = ?", (body.delta, message_id)
        )
        conn.execute(
            "INSERT INTO votes (message_id, user_id, delta, created_at) VALUES (?, ?, ?, ?)",
            (message_id, user["id"], body.delta, now()),
        )
        score = conn.execute(
            "SELECT score FROM messages WHERE id = ?", (message_id,)
        ).fetchone()[0]
        return {"message_id": message_id, "delta": body.delta, "score": score}


@router.post("/api/messages/{message_id}/reactions")
def add_reaction(message_id: int, body: ReactionIn, request: Request):
    with session(request, write=True) as (conn, user):
        _writable_message(conn, message_id)
        conn.execute(
            "INSERT OR IGNORE INTO reactions (message_id, user_id, emoji, created_at)"
            " VALUES (?, ?, ?, ?)",
            (message_id, user["id"], body.emoji, now()),
        )
        if user["account_type"] == "human":
            acknowledge_human(conn, user, message_id)
        elif body.emoji in RESERVED:
            agent_reaction_added(conn, user, message_id, body.emoji)
        return get_message_json(conn, user["id"], message_id)


@router.delete("/api/messages/{message_id}/reactions/{emoji}")
def remove_reaction(message_id: int, emoji: str, request: Request):
    with session(request, write=True) as (conn, user):
        _writable_message(conn, message_id)
        removed = conn.execute(
            "DELETE FROM reactions WHERE message_id = ? AND user_id = ? AND emoji = ?",
            (message_id, user["id"], emoji),
        ).rowcount
        if removed and user["account_type"] == "agent" and emoji in RESERVED:
            agent_reaction_removed(conn, user, message_id, emoji)
        return get_message_json(conn, user["id"], message_id)
