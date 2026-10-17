"""Attention rules.

Agents: top-level message needs an explicit @mention; nested reply notifies only the
direct parent's author plus mentions. Humans: every agent message needs every approved
human; human messages notify via @mention or direct reply. Never self, never inherited.
"""

import re
import sqlite3

from threadit.core import now

EYES = "👀"
CHECK = "✅"
RESERVED = {EYES: "processing", CHECK: "processed"}

MENTION = re.compile(r"(?<![A-Za-z0-9_-])@([A-Za-z0-9_-]{3,32})")


def mentioned_keys(body: str) -> set[str]:
    return {m.lower() for m in MENTION.findall(body)}


def record_attention(
    conn: sqlite3.Connection,
    message_id: int,
    author: sqlite3.Row,
    parent_author_id: int | None,
    body: str,
) -> None:
    keys = mentioned_keys(body)
    ts = now()
    approved = conn.execute(
        "SELECT id, account_type, username_key FROM users WHERE status = 'approved'"
    ).fetchall()
    for user in approved:
        if user["id"] == author["id"]:
            continue
        if user["id"] == parent_author_id:
            reason = "reply"
        elif user["username_key"] in keys:
            reason = "mention"
        elif author["account_type"] == "agent" and user["account_type"] == "human":
            reason = "agent_message"
        else:
            continue
        conn.execute(
            "INSERT INTO attention (message_id, user_id, reason, status, created_at, updated_at)"
            " VALUES (?, ?, ?, 'unacknowledged', ?, ?)",
            (message_id, user["id"], reason, ts, ts),
        )


def acknowledge_human(conn: sqlite3.Connection, user: sqlite3.Row, message_id: int) -> None:
    """Own emoji or direct reply acknowledges exactly that one message."""
    if user["account_type"] != "human":
        return
    conn.execute(
        "UPDATE attention SET status = 'acknowledged', updated_at = ?"
        " WHERE message_id = ? AND user_id = ? AND status = 'unacknowledged'",
        (now(), message_id, user["id"]),
    )


def agent_reaction_added(
    conn: sqlite3.Connection, user: sqlite3.Row, message_id: int, emoji: str
) -> None:
    """Reserved 👀/✅ replace each other and set the agent's status for that message."""
    for other in RESERVED:
        if other != emoji:
            conn.execute(
                "DELETE FROM reactions WHERE message_id = ? AND user_id = ? AND emoji = ?",
                (message_id, user["id"], other),
            )
    _set_agent_status(conn, user["id"], message_id, RESERVED[emoji])


def agent_reaction_removed(
    conn: sqlite3.Connection, user: sqlite3.Row, message_id: int, emoji: str
) -> None:
    conn.execute(
        "UPDATE attention SET status = 'unacknowledged', updated_at = ?"
        " WHERE message_id = ? AND user_id = ? AND status = ?",
        (now(), message_id, user["id"], RESERVED[emoji]),
    )


def _set_agent_status(
    conn: sqlite3.Connection, user_id: int, message_id: int, status: str
) -> None:
    conn.execute(
        "UPDATE attention SET status = ?, updated_at = ? WHERE message_id = ? AND user_id = ?",
        (status, now(), message_id, user_id),
    )


def acknowledge_all(conn: sqlite3.Connection, user: sqlite3.Row, include_closed: bool) -> int:
    """Add the user's ✅ to every unacknowledged item. Returns how many items changed."""
    rows = conn.execute(
        "SELECT att.message_id FROM attention att"
        " JOIN messages m ON m.id = att.message_id JOIN threads t ON t.id = m.thread_id"
        " WHERE att.user_id = ? AND att.status = 'unacknowledged'"
        + ("" if include_closed else " AND t.closed_reason IS NULL"),
        (user["id"],),
    ).fetchall()
    for row in rows:
        message_id = row["message_id"]
        conn.execute(
            "INSERT OR IGNORE INTO reactions (message_id, user_id, emoji, created_at)"
            " VALUES (?, ?, ?, ?)",
            (message_id, user["id"], CHECK, now()),
        )
        if user["account_type"] == "human":
            acknowledge_human(conn, user, message_id)
        else:
            agent_reaction_added(conn, user, message_id, CHECK)
    return len(rows)


def count_unacknowledged(conn: sqlite3.Connection, user_id: int, include_closed: bool) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM attention att"
        " JOIN messages m ON m.id = att.message_id JOIN threads t ON t.id = m.thread_id"
        " WHERE att.user_id = ? AND att.status = 'unacknowledged'"
        + ("" if include_closed else " AND t.closed_reason IS NULL"),
        (user_id,),
    ).fetchone()[0]
