"""Agent sessions: one attention row of an agent, plus its activity log.

State is derived on read. See the "Agent sessions" section of threadit/skill.md.
"""

import sqlite3
from datetime import datetime, timedelta

from threadit.core import ApiError, now

STALE_AFTER = timedelta(minutes=30)
MAX_ACTIVITIES = 50
EPHEMERAL_KINDS = ("thought", "action")

_SESSION_SQL = """
SELECT att.message_id, att.reason, att.status, att.created_at, att.updated_at,
       att.stop_requested_at,
       u.id AS agent_id, u.username AS agent_username, u.account_type AS agent_type,
       sb.id AS stop_by_id, sb.username AS stop_by_username, sb.account_type AS stop_by_type
FROM attention att
JOIN users u ON u.id = att.user_id AND u.account_type = 'agent'
LEFT JOIN users sb ON sb.id = att.stop_requested_by
"""


def _user(id_: int, username: str, account_type: str) -> dict:
    return {"id": id_, "username": username, "account_type": account_type}


def derive_state(
    status: str, stop_requested: bool, last_kind: str | None, last_at: str | None, updated_at: str
) -> str:
    if status == "processed":
        return "stopped" if stop_requested else "done"
    if stop_requested:
        return "stopping"
    if status == "unacknowledged":
        return "queued"
    if last_kind == "elicitation":
        return "needs_input"
    if last_kind == "error":
        return "error"
    newest = max(last_at or updated_at, updated_at)
    if datetime.fromisoformat(now()) - datetime.fromisoformat(newest) > STALE_AFTER:
        return "stale"
    return "working"


def _build(conn: sqlite3.Connection, rows: list[sqlite3.Row]) -> dict[int, list[dict]]:
    """Group session objects by message id. Uses three queries for any number of rows."""
    if not rows:
        return {}
    ids = sorted({r["message_id"] for r in rows})
    activities: dict[tuple[int, int], list[dict]] = {}
    replies: dict[tuple[int, int], int] = {}
    for start in range(0, len(ids), 500):
        chunk = ids[start : start + 500]
        marks = ",".join("?" * len(chunk))
        for a in conn.execute(
            "SELECT id, message_id, user_id, kind, body, ephemeral, created_at FROM ("
            "SELECT *, ROW_NUMBER() OVER ("
            "PARTITION BY message_id, user_id ORDER BY id DESC) AS rn"
            f" FROM agent_activities WHERE message_id IN ({marks}))"
            f" WHERE rn <= {MAX_ACTIVITIES} ORDER BY id",
            chunk,
        ):
            activities.setdefault((a["message_id"], a["user_id"]), []).append(
                {
                    "id": a["id"],
                    "kind": a["kind"],
                    "body": a["body"],
                    "ephemeral": bool(a["ephemeral"]),
                    "created_at": a["created_at"],
                }
            )
        # A top-level reply answers the OP, so it counts as a reply to the OP.
        for m in conn.execute(
            "SELECT target, author_id, MAX(id) AS reply_id FROM ("
            "SELECT m.id, m.author_id, COALESCE(m.parent_id, op.id) AS target FROM messages m"
            " LEFT JOIN messages op ON m.parent_id IS NULL AND m.is_op = 0"
            " AND op.thread_id = m.thread_id AND op.is_op = 1 WHERE m.deleted_at IS NULL)"
            f" WHERE target IN ({marks}) GROUP BY target, author_id",
            chunk,
        ):
            replies[(m["target"], m["author_id"])] = m["reply_id"]
    out: dict[int, list[dict]] = {}
    for r in rows:
        log = activities.get((r["message_id"], r["agent_id"]), [])
        last = log[-1] if log else None
        stop = None
        if r["stop_requested_at"]:
            stop = {
                "at": r["stop_requested_at"],
                "by": _user(r["stop_by_id"], r["stop_by_username"], r["stop_by_type"])
                if r["stop_by_id"]
                else None,
            }
        out.setdefault(r["message_id"], []).append(
            {
                "agent": _user(r["agent_id"], r["agent_username"], r["agent_type"]),
                "reason": r["reason"],
                "status": r["status"],
                "state": derive_state(
                    r["status"],
                    stop is not None,
                    last["kind"] if last else None,
                    last["created_at"] if last else None,
                    r["updated_at"],
                ),
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
                "last_activity_at": last["created_at"] if last else None,
                "stop_requested": stop,
                "reply_id": replies.get((r["message_id"], r["agent_id"])),
                "activities": log[-MAX_ACTIVITIES:],
            }
        )
    return out


def fetch_sessions(conn: sqlite3.Connection, message_ids: list[int]) -> dict[int, list[dict]]:
    rows: list[sqlite3.Row] = []
    for start in range(0, len(message_ids), 500):
        chunk = message_ids[start : start + 500]
        marks = ",".join("?" * len(chunk))
        rows += conn.execute(
            f"{_SESSION_SQL} WHERE att.message_id IN ({marks}) ORDER BY u.username_key", chunk
        ).fetchall()
    return _build(conn, rows)


def _session(conn: sqlite3.Connection, message_id: int, agent_id: int) -> dict:
    rows = conn.execute(
        f"{_SESSION_SQL} WHERE att.message_id = ? AND att.user_id = ?", (message_id, agent_id)
    ).fetchall()
    return _build(conn, rows)[message_id][0]


def add_activity(
    conn: sqlite3.Connection,
    user: sqlite3.Row,
    message_id: int,
    kind: str,
    body: str,
    ephemeral: bool,
) -> dict:
    mine = None
    if user["account_type"] == "agent":
        mine = conn.execute(
            "SELECT 1 FROM attention WHERE message_id = ? AND user_id = ?",
            (message_id, user["id"]),
        ).fetchone()
    if mine is None:
        raise ApiError(
            403,
            "forbidden",
            "Only an agent with an attention item on this message can post activities.",
        )
    if ephemeral and kind not in EPHEMERAL_KINDS:
        raise ApiError(422, "invalid_input", "Only thought and action activities can be ephemeral.")
    conn.execute(
        "DELETE FROM agent_activities WHERE message_id = ? AND user_id = ? AND ephemeral = 1",
        (message_id, user["id"]),
    )
    conn.execute(
        "INSERT INTO agent_activities (message_id, user_id, kind, body, ephemeral, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (message_id, user["id"], kind, body, int(ephemeral), now()),
    )
    return _session(conn, message_id, user["id"])


def _agent_attention(conn: sqlite3.Connection, message_id: int, agent_ref: str) -> sqlite3.Row:
    if agent_ref.isascii() and agent_ref.isdigit():
        agent = conn.execute(
            "SELECT id FROM users WHERE id = ? AND account_type = 'agent'", (int(agent_ref),)
        ).fetchone()
    else:
        agent = conn.execute(
            "SELECT id FROM users WHERE username_key = ? AND account_type = 'agent'",
            (agent_ref.lower(),),
        ).fetchone()
    row = None
    if agent is not None:
        row = conn.execute(
            "SELECT user_id, status, stop_requested_at FROM attention WHERE message_id = ? AND user_id = ?",
            (message_id, agent["id"]),
        ).fetchone()
    if row is None:
        raise ApiError(404, "not_found", f"Agent {agent_ref} has no session on this message.")
    return row


def request_stop(
    conn: sqlite3.Connection, user: sqlite3.Row, message_id: int, agent_ref: str
) -> dict:
    if user["account_type"] != "human":
        raise ApiError(403, "forbidden", "Only a human can stop an agent session.")
    row = _agent_attention(conn, message_id, agent_ref)
    if row["status"] == "processed":
        raise ApiError(409, "already_finished", "This agent session is already finished.")
    if row["stop_requested_at"] is None:
        conn.execute(
            "UPDATE attention SET stop_requested_at = ?, stop_requested_by = ?"
            " WHERE message_id = ? AND user_id = ?",
            (now(), user["id"], message_id, row["user_id"]),
        )
    return _session(conn, message_id, row["user_id"])


def request_retry(
    conn: sqlite3.Connection, user: sqlite3.Row, message_id: int, agent_ref: str
) -> dict:
    if user["account_type"] != "human":
        raise ApiError(403, "forbidden", "Only a human can retry an agent session.")
    row = _agent_attention(conn, message_id, agent_ref)
    if row["status"] == "processed":
        raise ApiError(409, "already_finished", "This agent session is already finished.")
    agent_id = row["user_id"]
    last = conn.execute(
        "SELECT kind, created_at FROM agent_activities"
        " WHERE message_id = ? AND user_id = ? ORDER BY id DESC LIMIT 1",
        (message_id, agent_id),
    ).fetchone()
    if last is None or last["kind"] != "error":
        raise ApiError(409, "not_retryable", "Only a failed agent session can be retried.")
    ts = now()
    conn.execute(
        "DELETE FROM reactions WHERE message_id = ? AND user_id = ? AND emoji = '👀'",
        (message_id, agent_id),
    )
    conn.execute(
        "UPDATE attention SET status = 'unacknowledged', updated_at = ?,"
        " stop_requested_at = NULL, stop_requested_by = NULL"
        " WHERE message_id = ? AND user_id = ?",
        (ts, message_id, agent_id),
    )
    replies = conn.execute(
        "SELECT reply.id FROM messages reply JOIN messages target ON target.id = ?"
        " WHERE reply.thread_id = target.thread_id AND reply.author_id = ?"
        " AND reply.deleted_at IS NULL AND reply.created_at > ?"
        " AND (reply.parent_id = target.id"
        " OR (target.is_op = 1 AND reply.parent_id IS NULL AND reply.is_op = 0))",
        (message_id, agent_id, last["created_at"]),
    ).fetchall()
    for reply in replies:
        if conn.execute("SELECT 1 FROM messages WHERE parent_id = ?", (reply["id"],)).fetchone():
            conn.execute("UPDATE messages SET deleted_at = ? WHERE id = ?", (ts, reply["id"]))
            continue
        for table in ("reactions", "votes", "attention", "agent_activities", "events", "attachments"):
            conn.execute(f"DELETE FROM {table} WHERE message_id = ?", (reply["id"],))
        conn.execute("DELETE FROM messages WHERE id = ?", (reply["id"],))
    conn.execute(
        "INSERT INTO agent_activities (message_id, user_id, kind, body, ephemeral, created_at)"
        " VALUES (?, ?, 'thought', ?, 0, ?)",
        (message_id, agent_id, f"Retry requested by @{user['username']}", ts),
    )
    return _session(conn, message_id, agent_id)
