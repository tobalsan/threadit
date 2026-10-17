import sqlite3

from tests.test_features import PNG, upload


def delete(actor, message_id):
    return actor.call("DELETE", f"/api/messages/{message_id}")


def test_author_deletes_and_body_stays_in_database(board, alice, area):
    thread = alice.make_thread(area["id"])
    msg = alice.say(thread["thread"]["id"], "secret words")
    first = delete(alice, msg["id"])
    assert first.status_code == 200
    out = first.json()
    assert out["deleted_at"] and out["body"] == "" and out["attachments"] == []
    again = delete(alice, msg["id"])
    assert again.status_code == 200 and again.json()["deleted_at"] == out["deleted_at"]
    conn = sqlite3.connect(board.path)
    body = conn.execute("SELECT body FROM messages WHERE id = ?", (msg["id"],)).fetchone()[0]
    conn.close()
    assert body == "secret words"


def test_non_author_and_closed_thread(admin, alice, bob, area):
    thread = alice.make_thread(area["id"])
    tid = thread["thread"]["id"]
    msg = alice.say(tid, "mine")
    assert delete(bob, msg["id"]).status_code == 403
    assert delete(admin, msg["id"]).status_code == 403
    assert alice.get(f"/api/messages/{msg['id']}").json()["deleted_at"] is None
    alice.ok("POST", f"/api/threads/{tid}/close", {"reason": "completed"})
    blocked = delete(alice, msg["id"])
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "thread_closed"
    assert delete(alice, 9999).status_code == 404


def test_op_delete_keeps_thread_and_title(alice, area):
    thread = alice.make_thread(area["id"], "Keep title", "op text")
    op_id = thread["thread"]["op_message_id"]
    assert delete(alice, op_id).status_code == 200
    detail = alice.ok("GET", f"/api/threads/{thread['thread']['id']}")
    assert detail["thread"]["title"] == "Keep title"
    assert detail["messages"][0]["deleted_at"] and detail["messages"][0]["body"] == ""


def test_hidden_on_every_read_path(admin, alice, bob, area):
    pic = upload(alice).json()
    thread = alice.make_thread(area["id"])
    tid = thread["thread"]["id"]
    msg = alice.ok(
        "POST",
        f"/api/threads/{tid}/messages",
        {"body": "zebra needle", "attachment_ids": [pic["id"]]},
        201,
    )
    child = bob.say(tid, "child", msg["id"])
    assert admin.get(pic["url"]).status_code == 200
    delete(alice, msg["id"])
    assert admin.get(pic["url"]).status_code == 404
    assert alice.get(pic["url"]).status_code == 404

    def find(messages):
        return next(m for m in messages if m["id"] == msg["id"])

    paths = [
        find(alice.ok("GET", f"/api/threads/{tid}")["messages"]),
        find(alice.ok("GET", f"/api/threads/{tid}/messages")["messages"]),
        alice.ok("GET", f"/api/messages/{msg['id']}"),
        find(alice.ok("GET", f"/api/messages/{child['id']}/context")["top_level"]),
    ]
    for m in paths:
        assert m["body"] == "" and m["attachments"] == [] and m["deleted_at"]
    assert "zebra" not in alice.get(f"/api/messages/{child['id']}/context").text
    assert bob.ok("GET", f"/api/messages/{child['id']}")["body"] == "child"
    assert alice.ok("GET", "/api/search", params={"q": "zebra"})["messages"] == []


def test_deleted_message_is_read_only(admin, alice, bob, area):
    tid = alice.make_thread(area["id"])["thread"]["id"]
    msg = alice.say(tid, "x")
    delete(alice, msg["id"])
    calls = [
        (alice, "PATCH", {"body": "new"}, ""),
        (bob, "POST", {"delta": 1}, "/votes"),
        (bob, "POST", {"emoji": "👍"}, "/reactions"),
    ]
    for actor, method, payload, suffix in calls:
        r = actor.call(method, f"/api/messages/{msg['id']}{suffix}", json=payload)
        assert r.status_code == 409, (suffix, r.text)
        assert r.json()["error"]["code"] == "message_deleted"
    reply = bob.post(f"/api/threads/{tid}/messages", {"body": "r", "parent_id": msg["id"]})
    assert reply.status_code == 409 and reply.json()["error"]["code"] == "message_deleted"


def test_replies_stay_after_parent_delete(alice, bob, area):
    tid = alice.make_thread(area["id"])["thread"]["id"]
    msg = alice.say(tid, "parent")
    child = bob.say(tid, "kid", msg["id"])
    delete(alice, msg["id"])
    assert bob.ok("GET", f"/api/messages/{child['id']}")["body"] == "kid"


def test_attention_drops_deleted_message(admin, alice, bot, area):
    tid = alice.make_thread(area["id"])["thread"]["id"]
    msg = bot.say(tid, "hello @alice @root")
    assert msg["id"] in alice.attention()
    before = alice.ok("GET", "/api/attention")["unacknowledged_count"]
    assert alice.ok("GET", f"/api/threads/{tid}")["thread"]["pending_attention"] == before
    delete(bot, msg["id"])
    assert msg["id"] not in alice.attention() and msg["id"] not in admin.attention()
    assert alice.ok("GET", "/api/attention")["unacknowledged_count"] == before - 1
    assert alice.ok("GET", f"/api/threads/{tid}")["thread"]["pending_attention"] == before - 1
    assert alice.ok("POST", "/api/attention/acknowledge-all")["acknowledged"] == before - 1


def test_attention_rows_stay_in_database(board, alice, bot, area):
    tid = alice.make_thread(area["id"])["thread"]["id"]
    msg = bot.say(tid, "hi @alice")
    delete(bot, msg["id"])
    conn = sqlite3.connect(board.path)
    count = conn.execute(
        "SELECT COUNT(*) FROM attention WHERE message_id = ?", (msg["id"],)
    ).fetchone()[0]
    conn.close()
    assert count > 0


def test_delete_is_not_activity(board, alice, area):
    tid = alice.make_thread(area["id"])["thread"]["id"]
    msg = alice.say(tid, "x")
    conn = sqlite3.connect(board.path)
    conn.execute("UPDATE threads SET last_activity_at = '2020-01-01T00:00:00+00:00'")
    conn.commit()
    events = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    attention = conn.execute("SELECT COUNT(*) FROM attention").fetchone()[0]
    delete(alice, msg["id"])
    assert conn.execute("SELECT last_activity_at FROM threads").fetchone()[0].startswith("2020")
    assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == events
    assert conn.execute("SELECT COUNT(*) FROM attention").fetchone()[0] == attention
    conn.close()
