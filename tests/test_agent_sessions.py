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


def test_top_level_reply_is_the_reply_to_the_op(admin, bot, item):
    tid, op = item
    reply = bot.say(tid, "answer without parent_id")
    assert reply["parent_id"] is None
    assert sessions(admin, op)[0]["reply_id"] == reply["id"]


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


def test_retry_failed_run(admin, alice, bot, item):
    tid, mid = item
    bot.react(mid, "👀")
    activity(bot, mid, "error", "Run failed")
    reply = bot.say(tid, "I could not finish this request.")
    before = admin.ok("GET", f"/api/threads/{tid}")["thread"]["last_activity_at"]

    s = alice.ok("POST", f"/api/messages/{mid}/agent-sessions/BOTTY/retry")

    assert s["state"] == "queued" and s["status"] == "unacknowledged"
    assert s["stop_requested"] is None and s["reply_id"] is None
    assert s["activities"][-1]["kind"] == "thought"
    assert s["activities"][-1]["body"] == "Retry requested by @alice"
    assert s["activities"][-1]["ephemeral"] is False
    message = admin.ok("GET", f"/api/messages/{mid}")
    assert message["agent_sessions"][0] == s
    assert message["reactions"] == []
    assert bot.attention()[mid]["status"] == "unacknowledged"
    assert admin.get(f"/api/messages/{reply['id']}").status_code == 404
    thread = admin.ok("GET", f"/api/threads/{tid}")
    assert [m["id"] for m in thread["messages"]] == [mid]
    assert thread["thread"]["last_activity_at"] == before


@pytest.mark.parametrize("state,code", [
    ("queued", "not_retryable"),
    ("working", "not_retryable"),
    ("needs_input", "not_retryable"),
    ("done", "already_finished"),
])
def test_retry_refuses_non_error_sessions(admin, bot, item, state, code):
    _, mid = item
    if state != "queued":
        bot.react(mid, "👀")
    if state == "needs_input":
        activity(bot, mid, "elicitation", "Which option?")
    if state == "done":
        activity(bot, mid, "error", "Run failed")
        bot.react(mid, "✅")
    before = sessions(admin, mid)

    r = admin.call("POST", f"/api/messages/{mid}/agent-sessions/botty/retry")

    assert r.status_code == 409 and r.json()["error"]["code"] == code
    assert sessions(admin, mid) == before


def test_retry_permissions_and_guard_order(admin, bot, bot2, item):
    tid, mid = item
    activity(bot, mid, "error", "Run failed")
    r = bot.call("POST", f"/api/messages/{mid}/agent-sessions/botty/retry")
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"
    for ref in ("robo", "nobody", "999", "root"):
        r = admin.call("POST", f"/api/messages/{mid}/agent-sessions/{ref}/retry")
        assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    r = bot.call("POST", "/api/messages/999/agent-sessions/botty/retry")
    assert r.status_code == 404 and r.json()["error"]["code"] == "message_not_found"
    admin.ok("DELETE", f"/api/messages/{mid}")
    r = bot.call("POST", f"/api/messages/{mid}/agent-sessions/botty/retry")
    assert r.status_code == 409 and r.json()["error"]["code"] == "message_deleted"
    admin.ok("POST", f"/api/threads/{tid}/close", {"reason": "archived"})
    for caller in (admin, bot):
        r = caller.call("POST", f"/api/messages/{mid}/agent-sessions/botty/retry")
        assert r.status_code == 409 and r.json()["error"]["code"] == "thread_closed"


@pytest.mark.parametrize("deleted_child", [False, True])
def test_retry_keeps_deleted_card_when_failure_reply_has_children(admin, bot, item, deleted_child):
    tid, mid = item
    bot.react(mid, "👀")
    activity(bot, mid, "error", "Run failed")
    reply = bot.say(tid, "I could not finish this request.")
    child = admin.say(tid, "Please try again", reply["id"])
    if deleted_child:
        admin.ok("DELETE", f"/api/messages/{child['id']}")

    s = admin.ok("POST", f"/api/messages/{mid}/agent-sessions/botty/retry")

    assert s["state"] == "queued" and s["reply_id"] is None
    card = admin.ok("GET", f"/api/messages/{reply['id']}")
    assert card["deleted_at"] and card["body"] == ""
    assert admin.ok("GET", f"/api/messages/{child['id']}")["parent_id"] == reply["id"]
    thread = admin.ok("GET", f"/api/threads/{tid}")
    assert [m["id"] for m in thread["messages"]] == [mid, reply["id"], child["id"]]


@pytest.mark.parametrize("stopping", [False, True])
def test_retry_clears_stop_and_can_only_be_requested_once(admin, bot, item, stopping):
    _, mid = item
    bot.react(mid, "👀")
    activity(bot, mid, "error", "Run failed")
    if stopping:
        s = admin.ok("POST", f"/api/messages/{mid}/agent-sessions/botty/stop")
        assert s["state"] == "stopping"
    else:
        bot.ok("DELETE", f"/api/messages/{mid}/reactions/👀")
    before = sessions(admin, mid)[0]["updated_at"]

    s = admin.ok("POST", f"/api/messages/{mid}/agent-sessions/{bot.id}/retry")

    assert s["state"] == "queued" and s["stop_requested"] is None
    assert s["updated_at"] > before
    poll = bot.ok("GET", "/api/attention?status=unacknowledged")["items"][0]
    assert poll["id"] == mid and poll["reactions"] == []
    assert poll["agent_sessions"][0] == s
    r = admin.call("POST", f"/api/messages/{mid}/agent-sessions/botty/retry")
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_retryable"
    assert sessions(admin, mid)[0] == s


@pytest.mark.parametrize("op_target", [False, True])
def test_retry_removes_only_later_replies_to_its_target(admin, bot, bot2, item, op_target):
    tid, op = item
    mid = op if op_target else admin.say(tid, "Please help @botty")["id"]
    earlier = bot.say(tid, "Previous answer", mid)
    bot.react(mid, "👀")
    activity(bot, mid, "error", "Run failed")
    failures = [bot.say(tid, body, mid) for body in ("Failure one", "Failure two")]
    other_agent = bot2.say(tid, "Other agent's answer", mid)
    other_target = admin.say(tid, "Another question")
    unrelated = bot.say(tid, "Answer to another question", other_target["id"])

    s = admin.ok("POST", f"/api/messages/{mid}/agent-sessions/botty/retry")

    assert s["reply_id"] == earlier["id"]
    for reply in failures:
        assert admin.get(f"/api/messages/{reply['id']}").status_code == 404
    for reply in (earlier, other_agent, unrelated):
        assert admin.ok("GET", f"/api/messages/{reply['id']}")["body"] == reply["body"]
    messages = admin.ok("GET", f"/api/threads/{tid}")["messages"]
    assert all(m["id"] not in [r["id"] for r in failures] for m in messages)


def test_retry_hard_deletes_failure_reply_with_references(admin, bot, bot2, item):
    tid, mid = item
    activity(bot, mid, "error", "Run failed")
    upload = bot.ok("POST", "/api/attachments?filename=failure.txt", status=201, content=b"failure details")
    reply = bot.ok("POST", f"/api/threads/{tid}/messages", {
        "body": "I could not finish this request. @robo", "attachment_ids": [upload["id"]],
    }, 201)
    admin.react(reply["id"], "👍")
    admin.ok("POST", f"/api/messages/{reply['id']}/votes", {"delta": 1})
    activity(bot2, reply["id"], "thought", "Looking into it")

    s = admin.ok("POST", f"/api/messages/{mid}/agent-sessions/botty/retry")

    assert s["reply_id"] is None
    assert admin.get(f"/api/messages/{reply['id']}").status_code == 404
    assert admin.get(f"/api/attachments/{upload['id']}").status_code == 404
    assert reply["id"] not in bot2.attention()
    assert "I could not finish this request." not in admin.get("/api/activity").text


def test_reply_id_ignores_agent_deleted_reply(admin, bot, item):
    tid, mid = item
    earlier = bot.say(tid, "Earlier answer")
    latest = bot.say(tid, "Deleted answer")
    assert sessions(admin, mid)[0]["reply_id"] == latest["id"]

    bot.ok("DELETE", f"/api/messages/{latest['id']}")
    assert sessions(admin, mid)[0]["reply_id"] == earlier["id"]
    bot.ok("DELETE", f"/api/messages/{earlier['id']}")
    assert sessions(admin, mid)[0]["reply_id"] is None


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


def test_only_newest_50_activities_per_session(admin, bot, item, board):
    _, mid = item
    now = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    conn = sqlite3.connect(board.path)
    conn.executemany(
        "INSERT INTO agent_activities (message_id, user_id, kind, body, created_at)"
        " VALUES (?, ?, 'thought', ?, ?)",
        [(mid, bot.id, f"n{i}", now) for i in range(120)],
    )
    conn.commit()
    conn.close()
    log = sessions(admin, mid)[0]["activities"]
    assert [a["body"] for a in log] == [f"n{i}" for i in range(70, 120)]
