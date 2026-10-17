import sqlite3
from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture
def item(admin, bot, area):
    """A thread whose OP mentions the bot: returns (thread_id, op_id)."""
    t = admin.make_thread(area["id"], body="hi @botty")
    return t["thread"]["id"], t["messages"][0]["id"]


def sessions(actor, message_id):
    return actor.ok("GET", f"/api/messages/{message_id}")["agent_sessions"]


def activity(bot, mid, kind="thought", body="x", **extra):
    return bot.ok("POST", f"/api/messages/{mid}/agent-activities", {"kind": kind, "body": body, **extra}, 201)


def test_queued_then_working_then_done(admin, bot, item):
    tid, mid = item
    s = sessions(admin, mid)
    assert len(s) == 1 and s[0]["state"] == "queued" and s[0]["agent"]["username"] == "botty"
    assert s[0]["reason"] == "mention" and s[0]["activities"] == [] and s[0]["reply_id"] is None
    bot.react(mid, "👀")
    assert sessions(admin, mid)[0]["state"] == "working"
    s = activity(bot, mid, "action", "Running")
    assert s["state"] == "working" and s["activities"][0]["body"] == "Running"
    assert s["last_activity_at"] == s["activities"][0]["created_at"]
    reply = bot.say(tid, "done", mid)
    bot.react(mid, "✅")
    s = sessions(admin, mid)[0]
    assert s["state"] == "done" and s["reply_id"] == reply["id"]


def test_needs_input_and_error(admin, bot, item):
    _, mid = item
    bot.react(mid, "👀")
    assert activity(bot, mid, "elicitation", "which?")["state"] == "needs_input"
    assert activity(bot, mid, "error", "boom")["state"] == "error"
    assert activity(bot, mid, "thought", "retry")["state"] == "working"


def test_stale_after_30_minutes(admin, bot, item, board):
    _, mid = item
    bot.react(mid, "👀")
    old = (datetime.now(timezone.utc) - timedelta(minutes=31)).isoformat(timespec="microseconds")
    conn = sqlite3.connect(board.path)
    conn.execute("UPDATE attention SET updated_at = ? WHERE user_id = ?", (old, bot.id))
    conn.commit()
    assert sessions(admin, mid)[0]["state"] == "stale"
    conn.execute(
        "INSERT INTO agent_activities (message_id, user_id, kind, body, created_at)"
        " VALUES (?, ?, 'thought', 'x', ?)",
        (mid, bot.id, datetime.now(timezone.utc).isoformat(timespec="microseconds")),
    )
    conn.commit()
    conn.close()
    assert sessions(admin, mid)[0]["state"] == "working"


def test_ephemeral_replacement(bot, item):
    _, mid = item
    activity(bot, mid, "thought", "Started")
    activity(bot, mid, "action", "step 1", ephemeral=True)
    s = activity(bot, mid, "action", "step 2", ephemeral=True)
    assert [a["body"] for a in s["activities"]] == ["Started", "step 2"]
    s = activity(bot, mid, "thought", "next")
    assert [a["body"] for a in s["activities"]] == ["Started", "next"]


def test_activity_validation_and_permissions(admin, alice, bot, bot2, item):
    tid, mid = item
    r = bot.call("POST", f"/api/messages/{mid}/agent-activities", json={"kind": "error", "body": "x", "ephemeral": True})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_input"
    for kind, body in (("nope", "x"), ("thought", ""), ("thought", "a" * 2001)):
        assert bot.call("POST", f"/api/messages/{mid}/agent-activities", json={"kind": kind, "body": body}).status_code == 422
    for who in (alice, bot2):
        r = who.call("POST", f"/api/messages/{mid}/agent-activities", json={"kind": "thought", "body": "x"})
        assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"
    admin.ok("POST", f"/api/threads/{tid}/close", {"reason": "archived"})
    r = bot.call("POST", f"/api/messages/{mid}/agent-activities", json={"kind": "thought", "body": "x"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "thread_closed"


def test_activity_creates_no_attention_or_events(admin, bot, item):
    tid, mid = item
    before = admin.get(f"/api/threads/{tid}").json()["thread"]["last_activity_at"]
    events = admin.get("/api/activity").text
    activity(bot, mid)
    assert admin.get(f"/api/threads/{tid}").json()["thread"]["last_activity_at"] == before
    assert admin.get("/api/activity").text == events
    assert bot.attention()[mid]["status"] == "unacknowledged"


def test_stop_flow(admin, alice, bot, item):
    _, mid = item
    bot.react(mid, "👀")
    s = alice.ok("POST", f"/api/messages/{mid}/agent-sessions/BOTTY/stop")
    assert s["state"] == "stopping" and s["stop_requested"]["by"]["username"] == "alice"
    first = s["stop_requested"]["at"]
    again = admin.ok("POST", f"/api/messages/{mid}/agent-sessions/{bot.id}/stop")
    assert again["stop_requested"]["at"] == first and again["stop_requested"]["by"]["username"] == "alice"
    assert activity(bot, mid)["stop_requested"]["at"] == first
    assert bot.get("/api/attention?status=processing").json()["items"][0]["agent_sessions"][0]["stop_requested"]
    bot.react(mid, "✅")
    assert sessions(admin, mid)[0]["state"] == "stopped"
    r = alice.call("POST", f"/api/messages/{mid}/agent-sessions/botty/stop")
    assert r.status_code == 409 and r.json()["error"]["code"] == "already_finished"


def test_stop_errors(admin, bot, bot2, item):
    tid, mid = item
    r = bot2.call("POST", f"/api/messages/{mid}/agent-sessions/botty/stop")
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"
    for ref in ("robo", "nobody", "999", "root"):
        r = admin.call("POST", f"/api/messages/{mid}/agent-sessions/{ref}/stop")
        assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    admin.ok("POST", f"/api/threads/{tid}/close", {"reason": "archived"})
    r = admin.call("POST", f"/api/messages/{mid}/agent-sessions/botty/stop")
    assert r.status_code == 409 and r.json()["error"]["code"] == "thread_closed"


def test_sessions_on_every_message_shape_ordered_by_username(admin, bot, bot2, area):
    t = admin.make_thread(area["id"], body="@robo and @botty")
    mid = t["messages"][0]["id"]
    assert [s["agent"]["username"] for s in t["messages"][0]["agent_sessions"]] == ["botty", "robo"]
    ctx = admin.ok("GET", f"/api/messages/{mid}/context")
    assert len(ctx["top_level"][0]["agent_sessions"]) == 2
    assert len(admin.ok("GET", f"/api/threads/{t['thread']['id']}/messages")["messages"][0]["agent_sessions"]) == 2
    assert bot.ok("GET", "/api/attention")["items"][0]["agent_sessions"][0]["agent"]["username"] == "botty"


def test_sessions_are_batched(admin, bot, area, board):
    t = admin.make_thread(area["id"], body="@botty")
    for i in range(5):
        admin.say(t["thread"]["id"], f"@botty {i}")
    queries = []
    from threadit import db

    # count statements through a trace callback on new connections
    real_connect = db.Database._connect

    def connect(self):
        conn = real_connect(self)
        conn.set_trace_callback(queries.append)
        return conn

    db.Database._connect = connect
    try:
        admin.ok("GET", f"/api/threads/{t['thread']['id']}")
    finally:
        db.Database._connect = real_connect
    assert sum("agent_activities" in q for q in queries) == 1
