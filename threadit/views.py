"""Read queries and JSON shaping for users, areas, threads and messages."""

import re
import sqlite3

from threadit.core import ApiError
from threadit.sessions import fetch_sessions

_THREAD_REFERENCE = re.compile(r"(?<![^\s(\[])#([0-9]+)(?![A-Za-z0-9_])")

_MESSAGE_SQL = """
SELECT m.id, m.thread_id, m.parent_id, m.is_op, m.body, m.created_at, m.score, m.edited_at,
       m.deleted_at,
       u.id AS author_id, u.username AS author_username, u.account_type AS author_type,
       t.title AS thread_title, t.area_id AS area_id, ar.name AS area_name, ar.slug AS area_slug,
       att.status AS att_status, att.reason AS att_reason,
       t.closed_reason AS thread_closed_reason
FROM messages m
JOIN users u ON u.id = m.author_id
JOIN threads t ON t.id = m.thread_id
JOIN areas ar ON ar.id = t.area_id
LEFT JOIN attention att ON att.message_id = m.id AND att.user_id = ?
"""

_THREAD_SQL = """
SELECT t.id, t.area_id, ar.name AS area_name, ar.slug AS area_slug, t.title,
       t.created_at, t.edited_at,
       t.last_activity_at, t.pinned, t.closed_reason, t.closed_at,
       cb.username AS closed_by,
       o.id AS owner_id, o.username AS owner_username, o.account_type AS owner_type,
       op.id AS op_message_id, op.score AS importance,
       (SELECT COUNT(*) FROM messages mm WHERE mm.thread_id = t.id) AS message_count,
       CASE WHEN t.closed_reason IS NOT NULL THEN 0 ELSE
         (SELECT COUNT(*) FROM attention att JOIN messages am ON am.id = att.message_id
          WHERE am.thread_id = t.id AND am.deleted_at IS NULL
            AND att.user_id = ? AND att.status = 'unacknowledged')
       END AS pending_attention
FROM threads t
JOIN areas ar ON ar.id = t.area_id
JOIN users o ON o.id = t.owner_id
JOIN messages op ON op.thread_id = t.id AND op.is_op = 1
LEFT JOIN users cb ON cb.id = t.closed_by
"""

# "hot" = OP score minus a penalty that grows with idle days: 2 * log2(1 + idle_days).
# Score matters most. Each +2 score keeps the rank while (1 + idle days) doubles.
THREAD_ORDERS = {
    "created": "t.created_at {d}, t.id {d}",
    "activity": "t.last_activity_at {d}, t.id {d}",
    "closed": "t.closed_at IS NULL ASC, t.closed_at {d}, t.id {d}",
    "hot": "op.score - 2.0 * log2(1 + MAX(0, julianday('now') - julianday(t.last_activity_at))) {d},"
    " t.last_activity_at {d}, t.id {d}",
    "importance": "op.score {d}, t.last_activity_at {d}, t.created_at {d}, t.id {d}",
}


def user_json(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "username": row["username"],
        "account_type": row["account_type"],
        "status": row["status"],
        "is_superadmin": bool(row["is_superadmin"]),
        "created_at": row["created_at"],
        "description": row["description"],
    }


def attachment_json(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "filename": row["filename"],
        "content_type": row["content_type"],
        "size": row["size"],
        "url": f"/api/attachments/{row['id']}",
    }


def area_json(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "slug": row["slug"],
        "description": row["description"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_areas(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT a.*,
          (SELECT COUNT(*) FROM threads t WHERE t.area_id = a.id AND t.closed_reason IS NULL) AS active_threads,
          (SELECT COUNT(*) FROM threads t WHERE t.area_id = a.id AND t.closed_reason IS NOT NULL) AS closed_threads,
          (SELECT MAX(t.last_activity_at) FROM threads t WHERE t.area_id = a.id) AS last_activity_at
        FROM areas a ORDER BY a.name_key
        """
    ).fetchall()
    return [
        {
            **area_json(r),
            "active_threads": r["active_threads"],
            "closed_threads": r["closed_threads"],
            "last_activity_at": r["last_activity_at"],
        }
        for r in rows
    ]


def get_area(conn: sqlite3.Connection, area_ref: int | str) -> sqlite3.Row:
    """Area by numeric id, or by slug when `area_ref` is not an integer."""
    if isinstance(area_ref, str) and not re.fullmatch(r"[0-9]+", area_ref):
        row = conn.execute("SELECT * FROM areas WHERE slug = ?", (area_ref,)).fetchone()
    else:
        row = conn.execute("SELECT * FROM areas WHERE id = ?", (int(area_ref),)).fetchone()
    if row is None:
        raise ApiError(404, "area_not_found", f"Area {area_ref} does not exist.")
    return row


def thread_json(row: sqlite3.Row) -> dict:
    closed = None
    if row["closed_reason"]:
        closed = {
            "reason": row["closed_reason"],
            "at": row["closed_at"],
            "by": row["closed_by"],
        }
    return {
        "id": row["id"],
        "area_id": row["area_id"],
        "area_name": row["area_name"],
        "area_slug": row["area_slug"],
        "title": row["title"],
        "owner": {
            "id": row["owner_id"],
            "username": row["owner_username"],
            "account_type": row["owner_type"],
        },
        "created_at": row["created_at"],
        "edited_at": row["edited_at"],
        "last_activity_at": row["last_activity_at"],
        "pinned": bool(row["pinned"]),
        "closed": closed,
        "importance": row["importance"],
        "op_message_id": row["op_message_id"],
        "message_count": row["message_count"],
        "pending_attention": row["pending_attention"],
    }


def fetch_threads(
    conn: sqlite3.Connection,
    viewer_id: int,
    where: str = "1=1",
    params: tuple = (),
    sort: str = "activity",
    limit: int | None = None,
    offset: int = 0,
    order: str = "desc",
) -> list[dict]:
    direction = {"asc": "ASC", "desc": "DESC"}[order]
    sql = f"{_THREAD_SQL} WHERE {where} ORDER BY {THREAD_ORDERS[sort].format(d=direction)}"
    args: tuple = (viewer_id, *params)
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        args += (limit, offset)
    return [thread_json(r) for r in conn.execute(sql, args).fetchall()]


def get_thread_json(conn: sqlite3.Connection, viewer_id: int, thread_id: int) -> dict:
    found = fetch_threads(conn, viewer_id, "t.id = ?", (thread_id,))
    if not found:
        raise ApiError(404, "thread_not_found", f"Thread {thread_id} does not exist.")
    return found[0]


def fetch_messages(
    conn: sqlite3.Connection,
    viewer_id: int,
    where: str = "1=1",
    params: tuple = (),
    order: str = "m.id ASC",
    limit: int | None = None,
    offset: int = 0,
) -> list[dict]:
    sql = f"{_MESSAGE_SQL} WHERE {where} ORDER BY {order}"
    args: tuple = (viewer_id, *params)
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        args += (limit, offset)
    rows = conn.execute(sql, args).fetchall()
    reactions: dict[int, dict[str, dict]] = {}
    ids = [r["id"] for r in rows]
    for start in range(0, len(ids), 500):
        chunk = ids[start : start + 500]
        marks = ",".join("?" * len(chunk))
        for r in conn.execute(
            f"""SELECT r.message_id, r.emoji, r.user_id, u.username
                FROM reactions r JOIN users u ON u.id = r.user_id
                WHERE r.message_id IN ({marks}) ORDER BY r.created_at, u.id""",
            chunk,
        ):
            entry = reactions.setdefault(r["message_id"], {}).setdefault(
                r["emoji"], {"emoji": r["emoji"], "users": [], "mine": False}
            )
            entry["users"].append(r["username"])
            entry["mine"] = entry["mine"] or r["user_id"] == viewer_id
    attachments: dict[int, list[dict]] = {}
    for start in range(0, len(ids), 500):
        chunk = ids[start : start + 500]
        marks = ",".join("?" * len(chunk))
        for a in conn.execute(
            "SELECT id, message_id, filename, content_type, size FROM attachments"
            f" WHERE message_id IN ({marks}) ORDER BY id",
            chunk,
        ):
            attachments.setdefault(a["message_id"], []).append(attachment_json(a))
    sessions = fetch_sessions(conn, ids)
    out = []
    for r in rows:
        mine = None
        if r["att_status"] is not None:
            mine = {"status": r["att_status"], "reason": r["att_reason"]}
        grouped = list(reactions.get(r["id"], {}).values())
        for entry in grouped:
            entry["count"] = len(entry["users"])
        out.append(
            {
                "id": r["id"],
                "thread_id": r["thread_id"],
                "thread_title": r["thread_title"],
                "area_id": r["area_id"],
                "area_name": r["area_name"],
                "area_slug": r["area_slug"],
                "parent_id": r["parent_id"],
                "is_op": bool(r["is_op"]),
                "author": {
                    "id": r["author_id"],
                    "username": r["author_username"],
                    "account_type": r["author_type"],
                },
                "body": "" if r["deleted_at"] else r["body"],
                "deleted_at": r["deleted_at"],
                "created_at": r["created_at"],
                "edited_at": r["edited_at"],
                "attachments": [] if r["deleted_at"] else attachments.get(r["id"], []),
                "score": r["score"],
                "reactions": grouped,
                "my_attention": mine,
                "agent_sessions": sessions.get(r["id"], []),
                "thread_closed_reason": r["thread_closed_reason"],
                "context_url": f"/api/messages/{r['id']}/context",
            }
        )
    link_threads(conn, out)
    return out

_CODE = re.compile(r"```.*?(?:```|\Z)|`[^`\n]*`", re.DOTALL)


def referenced_by(conn: sqlite3.Connection, thread_id: int) -> list[dict]:
    """Other threads with a live message that references this thread, newest first."""
    rows = conn.execute(
        "SELECT m.id, m.thread_id, m.body, m.created_at, u.username,"
        " t.title, t.closed_reason, a.slug AS area_slug, a.name AS area_name"
        " FROM messages m JOIN threads t ON t.id = m.thread_id"
        " JOIN areas a ON a.id = t.area_id JOIN users u ON u.id = m.author_id"
        " WHERE m.thread_id != ? AND m.deleted_at IS NULL AND m.body LIKE ?"
        " ORDER BY m.created_at DESC, m.id DESC",
        (thread_id, f"%#{thread_id}%"),
    )
    found: dict[int, dict] = {}
    for r in rows:
        if r["thread_id"] in found:
            continue
        refs = _THREAD_REFERENCE.findall(_CODE.sub("\x00", r["body"]))
        if any((ref.lstrip("0") or "0") == str(thread_id) for ref in refs):
            found[r["thread_id"]] = {
                "thread_id": r["thread_id"],
                "title": r["title"],
                "area_slug": r["area_slug"],
                "area_name": r["area_name"],
                "closed_reason": r["closed_reason"],
                "message_id": r["id"],
                "author": r["username"],
                "at": r["created_at"],
            }
    return sorted(found.values(), key=lambda e: e["at"], reverse=True)


def link_threads(conn: sqlite3.Connection, messages: list[dict]) -> None:
    """Resolve all references in a message response together, at read time."""
    references = [
        {ref.lstrip("0") or "0" for ref in _THREAD_REFERENCE.findall(m["body"])}
        for m in messages
    ]
    ids = set().union(*references)
    linked = {}
    if ids:
        marks = ",".join("?" * len(ids))
        linked = {
            str(r["id"]): dict(r)
            for r in conn.execute(
                "SELECT t.id, t.title, a.slug AS area_slug, t.closed_reason"
                " FROM threads t JOIN areas a ON a.id = t.area_id"
                f" WHERE t.id IN ({marks})",
                tuple(ids),
            )
        }
    for message, refs in zip(messages, references):
        message["linked_threads"] = {ref: linked[ref] for ref in refs if ref in linked}


def get_message_json(conn: sqlite3.Connection, viewer_id: int, message_id: int) -> dict:
    found = fetch_messages(conn, viewer_id, "m.id = ?", (message_id,))
    if not found:
        raise ApiError(404, "message_not_found", f"Message {message_id} does not exist.")
    return found[0]
