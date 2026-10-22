"""Write-side helpers shared by routes."""

import sqlite3
from collections.abc import Sequence

from threadit.attention import acknowledge_human, record_attention
from threadit.core import ApiError, now


def add_event(
    conn: sqlite3.Connection,
    kind: str,
    actor_id: int,
    area_id: int | None = None,
    thread_id: int | None = None,
    message_id: int | None = None,
    detail: str = "",
) -> None:
    conn.execute(
        "INSERT INTO events (kind, actor_id, area_id, thread_id, message_id, detail, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (kind, actor_id, area_id, thread_id, message_id, detail, now()),
    )


def get_thread_row(conn: sqlite3.Connection, thread_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM threads WHERE id = ?", (thread_id,)).fetchone()
    if row is None:
        raise ApiError(404, "thread_not_found", f"Thread {thread_id} does not exist.")
    return row


def get_message_row(conn: sqlite3.Connection, message_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone()
    if row is None:
        raise ApiError(404, "message_not_found", f"Message {message_id} does not exist.")
    return row


def require_open(thread: sqlite3.Row) -> None:
    if thread["closed_reason"]:
        raise ApiError(
            409,
            "thread_closed",
            f"Thread {thread['id']} is closed ({thread['closed_reason']}) and read-only. "
            f"Reopen it with POST /api/threads/{thread['id']}/reopen before changing it.",
        )


def require_not_deleted(message: sqlite3.Row) -> None:
    if message["deleted_at"]:
        raise ApiError(
            409, "message_deleted", "The message was deleted and is read-only."
        )


def link_attachments(
    conn: sqlite3.Connection, user: sqlite3.Row, attachment_ids: list[int], message_id: int
) -> None:
    """Attach the caller's own unlinked uploads to the message, else 422."""
    for attachment_id in dict.fromkeys(attachment_ids):
        linked = conn.execute(
            "UPDATE attachments SET message_id = ?"
            " WHERE id = ? AND uploader_id = ? AND message_id IS NULL",
            (message_id, attachment_id, user["id"]),
        ).rowcount
        if not linked:
            raise ApiError(
                422,
                "invalid_attachment",
                f"Attachment {attachment_id} was not uploaded by you or is already used.",
            )


def insert_message(
    conn: sqlite3.Connection,
    thread: sqlite3.Row,
    author: sqlite3.Row,
    body: str,
    parent_id: int | None = None,
    is_op: bool = False,
    attachment_ids: Sequence[int] = (),
) -> int:
    # A top-level reply answers the OP: it notifies and acknowledges like a direct reply to it.
    replied_to = None
    if parent_id is not None:
        parent = conn.execute(
            "SELECT id, thread_id, author_id, deleted_at, is_op FROM messages WHERE id = ?",
            (parent_id,),
        ).fetchone()
        if parent is None or parent["thread_id"] != thread["id"]:
            raise ApiError(
                422, "invalid_parent", "parent_id must be a message in the same thread."
            )
        if parent["is_op"]:
            parent_id = None  # No nesting under the OP: store it as a top-level reply.
        else:
            require_not_deleted(parent)
            replied_to = parent
    if parent_id is None and not is_op:
        replied_to = conn.execute(
            "SELECT id, author_id FROM messages"
            " WHERE thread_id = ? AND is_op = 1 AND deleted_at IS NULL",
            (thread["id"],),
        ).fetchone()
    parent_author_id = replied_to["author_id"] if replied_to else None
    ts = now()
    message_id = conn.execute(
        "INSERT INTO messages (thread_id, parent_id, author_id, body, created_at, is_op)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (thread["id"], parent_id, author["id"], body, ts, int(is_op)),
    ).lastrowid
    link_attachments(conn, author, attachment_ids, message_id)
    record_attention(conn, message_id, author, parent_author_id, body)
    if replied_to is not None:
        acknowledge_human(conn, author, replied_to["id"])
    conn.execute(
        "UPDATE threads SET last_activity_at = ? WHERE id = ?", (ts, thread["id"])
    )
    if not is_op:
        add_event(
            conn, "message_posted", author["id"], thread["area_id"], thread["id"], message_id
        )
    return message_id
