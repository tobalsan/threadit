import pytest


def test_area_create_edit_list_and_validation(admin, alice):
    a = admin.make_area("Alpha", "first")
    assert a["description"] == "first"
    assert admin.post("/api/areas", {"name": "alpha"}).status_code == 409
    assert admin.post("/api/areas", {"name": " "}).status_code == 422
    assert admin.post("/api/areas", {"name": "x", "bogus": 1}).status_code == 422
    edited = alice.ok("PATCH", f"/api/areas/{a['id']}", {"description": "second"})
    assert edited["description"] == "second" and edited["name"] == "Alpha"
    b = admin.make_area("Beta")
    assert admin.call("PATCH", f"/api/areas/{b['id']}", json={"name": "ALPHA"}).status_code == 409
    renamed = admin.ok("PATCH", f"/api/areas/{a['id']}", {"name": "ALPHA"})
    assert renamed["name"] == "ALPHA"
    admin.make_thread(a["id"])
    listing = admin.ok("GET", "/api/areas")["areas"]
    assert [x["name"] for x in listing] == ["ALPHA", "Beta"]
    assert listing[0]["active_threads"] == 1 and listing[1]["active_threads"] == 0
    assert admin.get("/api/areas/999").status_code == 404
    assert admin.get(f"/api/areas/{a['id']}").json()["name"] == "ALPHA"


def test_thread_create_read_and_invalid(admin, area):
    detail = admin.make_thread(area["id"], "Title", "hello")
    t = detail["thread"]
    assert t["importance"] == 0 and t["message_count"] == 1 and t["closed"] is None
    assert detail["area"]["description"] == "area desc"
    op = detail["messages"][0]
    assert op["is_op"] and op["parent_id"] is None and op["author"]["account_type"] == "human"
    assert admin.post("/api/threads", {"area_id": 999, "title": "t", "body": "b"}).status_code == 404
    assert admin.post("/api/threads", {"area_id": area["id"], "title": "", "body": "b"}).status_code == 422
    assert admin.post("/api/threads", {"area_id": area["id"], "title": "t", "body": " "}).status_code == 422
    assert admin.post("/api/threads", {"area_id": area["id"], "title": "t"}).status_code == 422
    assert admin.get("/api/threads/999").status_code == 404
    assert admin.post("/api/threads/999/messages", {"body": "x"}).status_code == 404


def test_messages_nested_and_parent_validation(admin, alice, area):
    t1 = admin.make_thread(area["id"])
    t2 = admin.make_thread(area["id"], "other")
    tid = t1["thread"]["id"]
    op = t1["messages"][0]["id"]
    peer = alice.say(tid, "peer reply")
    child = admin.say(tid, "child", peer["id"])
    grand = alice.say(tid, "grand", child["id"])
    assert grand["parent_id"] == child["id"]
    other_op = t2["messages"][0]["id"]
    r = admin.post(f"/api/threads/{tid}/messages", {"body": "x", "parent_id": other_op})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_parent"
    assert admin.post(f"/api/threads/{tid}/messages", {"body": "x", "parent_id": 9999}).status_code == 422
    assert admin.post(f"/api/threads/{tid}/messages", {"body": ""}).status_code == 422
    allm = admin.ok("GET", f"/api/threads/{tid}/messages")["messages"]
    assert [m["id"] for m in allm] == [op, peer["id"], child["id"], grand["id"]]
    top = admin.ok("GET", f"/api/threads/{tid}/messages", params={"top_level_only": True})
    assert [m["id"] for m in top["messages"]] == [op, peer["id"]]
    assert admin.ok("GET", f"/api/messages/{grand['id']}")["parent_id"] == child["id"]
    assert admin.get("/api/messages/9999").status_code == 404


def test_message_body_returned_verbatim_not_html(admin, area):
    payload = "<script>alert(1)</script> & \"q\""
    d = admin.make_thread(area["id"], "<b>t</b>", payload)
    assert d["messages"][0]["body"] == payload and d["thread"]["title"] == "<b>t</b>"
    r = admin.get(f"/api/threads/{d['thread']['id']}")
    assert r.headers["content-type"].startswith("application/json")


def test_scoring_signed_repeatable_and_importance_is_op_only(admin, alice, bot, area):
    d = admin.make_thread(area["id"])
    tid, op = d["thread"]["id"], d["messages"][0]["id"]
    reply = alice.say(tid, "reply")
    for delta in (1, 1, 5, 10, 100, -1):
        r = bot.ok("POST", f"/api/messages/{reply['id']}/votes", {"delta": delta})
    assert r["score"] == 116 and r["delta"] == -1
    assert admin.ok("GET", f"/api/threads/{tid}")["thread"]["importance"] == 0
    admin.ok("POST", f"/api/messages/{op}/votes", {"delta": 5})
    alice.ok("POST", f"/api/messages/{op}/votes", {"delta": -1})
    t = admin.ok("GET", f"/api/threads/{tid}")
    assert t["thread"]["importance"] == 4
    scores = {m["id"]: m["score"] for m in t["messages"]}
    assert scores == {op: 4, reply["id"]: 116}
    for bad in (0, 2, 1000, "x", None):
        assert admin.post(f"/api/messages/{op}/votes", {"delta": bad}).status_code == 422
    assert admin.post("/api/messages/9999/votes", {"delta": 1}).status_code == 404


def test_sorting_and_pinning(admin, alice, area):
    a = admin.make_thread(area["id"], "A")["thread"]["id"]
    b = admin.make_thread(area["id"], "B")["thread"]["id"]
    c = admin.make_thread(area["id"], "C")["thread"]["id"]
    op_a = admin.ok("GET", f"/api/threads/{a}")["thread"]["op_message_id"]
    op_b = admin.ok("GET", f"/api/threads/{b}")["thread"]["op_message_id"]
    admin.ok("POST", f"/api/messages/{op_a}/votes", {"delta": 100})
    admin.ok("POST", f"/api/messages/{op_b}/votes", {"delta": 5})
    # a reply (not OP) score must not affect importance
    r = admin.say(c, "reply")
    admin.ok("POST", f"/api/messages/{r['id']}/votes", {"delta": 100})
    admin.say(a, "bump a")  # a most recently active
    ids = lambda sort: [  # noqa: E731
        t["id"] for t in admin.ok("GET", "/api/threads", params={"sort": sort})["threads"]
    ]
    assert ids("created") == [c, b, a]
    assert ids("activity") == [a, c, b]
    assert ids("importance") == [a, b, c]
    def asc(sort):
        listing = admin.ok("GET", "/api/threads", params={"sort": sort, "order": "asc"})
        return [t["id"] for t in listing["threads"]]

    assert asc("created") == [a, b, c]
    assert asc("activity") == [b, c, a]
    assert admin.get("/api/threads", params={"sort": "bogus"}).status_code == 422
    assert admin.get("/api/threads", params={"order": "up"}).status_code == 422
    # pin: owner only, separate group
    assert alice.call("PUT", f"/api/threads/{b}/pin", json={"pinned": True}).status_code == 403
    pinned = admin.ok("PUT", f"/api/threads/{b}/pin", {"pinned": True})
    assert pinned["pinned"] is True
    listing = admin.ok("GET", "/api/threads", params={"sort": "importance"})
    assert [t["id"] for t in listing["pinned"]] == [b]
    assert [t["id"] for t in listing["threads"]] == [a, c]
    admin.ok("PUT", f"/api/threads/{b}/pin", {"pinned": False})
    assert admin.ok("GET", "/api/threads")["pinned"] == []
    assert admin.ok("GET", "/api/threads", params={"limit": 1})["threads"].__len__() == 1


def test_thread_list_filters_by_area(admin, area):
    other = admin.make_area("Other")
    t1 = admin.make_thread(area["id"])["thread"]["id"]
    admin.make_thread(other["id"])
    got = admin.ok("GET", "/api/threads", params={"area_id": area["id"]})["threads"]
    assert [t["id"] for t in got] == [t1]


# ---------- reactions ----------


def test_reactions_add_remove_summary(admin, alice, area):
    d = admin.make_thread(area["id"])
    op = d["messages"][0]["id"]
    admin.react(op, "🎉")
    m = alice.react(op, "🎉")
    assert m["reactions"] == [
        {"emoji": "🎉", "users": ["root", "alice"], "mine": True, "count": 2}
    ]
    admin.react(op, "🎉")  # idempotent
    assert admin.ok("GET", f"/api/messages/{op}")["reactions"][0]["count"] == 2
    gone = alice.ok("DELETE", f"/api/messages/{op}/reactions/🎉")
    assert gone["reactions"][0]["users"] == ["root"] and gone["reactions"][0]["mine"] is False
    for bad in ("", "two words", "x" * 40):
        assert admin.post(f"/api/messages/{op}/reactions", {"emoji": bad}).status_code == 422


# ---------- context ----------


def test_context_pruning(admin, alice, area):
    d = admin.make_thread(area["id"], "ctx", "OP")
    tid, op = d["thread"]["id"], d["messages"][0]["id"]
    t2 = alice.say(tid, "top2")
    t2a = admin.say(tid, "t2 child A", t2["id"])
    t2b = admin.say(tid, "t2 child B (sibling)", t2["id"])
    t2a1 = alice.say(tid, "t2 grandchild", t2a["id"])
    t2a1x = admin.say(tid, "t2 great", t2a1["id"])
    t2a2 = admin.say(tid, "t2 grandchild sibling", t2a["id"])
    op_child = admin.say(tid, "child of op", op)
    t3 = alice.say(tid, "top3 later")
    ids = lambda ms: [m["id"] for m in ms]  # noqa: E731

    c = admin.ok("GET", f"/api/messages/{t2['id']}/context")
    assert ids(c["top_level"]) == [op, t2["id"]] and c["chain"] == []
    assert c["area"]["description"] == "area desc" and c["thread"]["id"] == tid
    assert c["target_id"] == t2["id"]

    c = admin.ok("GET", f"/api/messages/{t2a1x['id']}/context")
    assert ids(c["top_level"]) == [op, t2["id"]]
    assert ids(c["chain"]) == [t2a["id"], t2a1["id"], t2a1x["id"]]
    everything = set(ids(c["top_level"]) + ids(c["chain"]))
    assert not everything & {t2b["id"], t2a2["id"], op_child["id"], t3["id"]}

    c = admin.ok("GET", f"/api/messages/{op_child['id']}/context")
    assert ids(c["top_level"]) == [op] and ids(c["chain"]) == [op_child["id"]]

    c = admin.ok("GET", f"/api/messages/{op}/context")
    assert ids(c["top_level"]) == [op] and c["chain"] == []
    c = admin.ok("GET", f"/api/messages/{t3['id']}/context")
    assert ids(c["top_level"]) == [op, t2["id"], t3["id"]]
    assert admin.get("/api/messages/9999/context").status_code == 404


# ---------- lifecycle ----------


def test_close_reopen_and_write_guards(admin, alice, bot, area):
    d = admin.make_thread(area["id"])
    tid, op = d["thread"]["id"], d["messages"][0]["id"]
    reply = alice.say(tid, "r")
    assert alice.post(f"/api/threads/{tid}/close", {"reason": "nope"}).status_code == 422
    assert alice.post(f"/api/threads/{tid}/close", {}).status_code == 422
    closed = alice.ok("POST", f"/api/threads/{tid}/close", {"reason": "completed"})
    assert closed["closed"]["reason"] == "completed" and closed["closed"]["by"] == "alice"
    assert admin.post(f"/api/threads/{tid}/close", {"reason": "archived"}).status_code == 409

    guarded = [
        ("POST", f"/api/threads/{tid}/messages", {"body": "x"}),
        ("POST", f"/api/messages/{op}/votes", {"delta": 1}),
        ("POST", f"/api/messages/{op}/reactions", {"emoji": "👍"}),
        ("DELETE", f"/api/messages/{op}/reactions/👍", None),
        ("PUT", f"/api/threads/{tid}/pin", {"pinned": True}),
    ]
    for actor in (admin, alice, bot):
        for method, path, payload in guarded:
            r = actor.call(method, path, json=payload)
            assert r.status_code == 409, (method, path)
            err = r.json()["error"]
            assert err["code"] == "thread_closed"
            assert f"/api/threads/{tid}/reopen" in err["message"] and "completed" in err["message"]

    # consultability preserved
    assert len(admin.ok("GET", f"/api/threads/{tid}")["messages"]) == 2
    assert admin.ok("GET", f"/api/messages/{reply['id']}/context")["thread"]["closed"]["reason"] == "completed"

    reopened = bot.ok("POST", f"/api/threads/{tid}/reopen")
    assert reopened["closed"] is None
    assert bot.post(f"/api/threads/{tid}/reopen").status_code == 409
    alice.say(tid, "works again")
    admin.ok("POST", f"/api/threads/{tid}/close", {"reason": "archived"})
    assert admin.get(f"/api/threads/{tid}").json()["thread"]["closed"]["reason"] == "archived"


def test_closed_hidden_from_active_lists_but_browsable(admin, area):
    open_t = admin.make_thread(area["id"], "open")["thread"]["id"]
    shut = admin.make_thread(area["id"], "shut")["thread"]["id"]
    admin.ok("PUT", f"/api/threads/{shut}/pin", {"pinned": True})
    admin.ok("POST", f"/api/threads/{shut}/close", {"reason": "archived"})
    active = admin.ok("GET", "/api/threads")
    assert [t["id"] for t in active["threads"]] == [open_t] and active["pinned"] == []
    closed = admin.ok("GET", "/api/threads", params={"state": "closed"})
    assert [t["id"] for t in closed["pinned"]] == [shut]
    both = admin.ok("GET", "/api/threads", params={"state": "all"})
    assert {t["id"] for t in both["threads"] + both["pinned"]} == {open_t, shut}
    row = next(a for a in admin.ok("GET", "/api/areas")["areas"] if a["id"] == area["id"])
    assert row["active_threads"] == 1 and row["closed_threads"] == 1


# ---------- search / activity ----------


def test_search_areas_threads_messages_and_closed(admin, alice, board):
    area = admin.make_area("Gardening", "tomato growing notes")
    d = admin.make_thread(area["id"], "Compost heap", "worms love peels")
    tid = d["thread"]["id"]
    nested = alice.say(tid, "reply about WORMS bins", d["messages"][0]["id"])
    s = admin.ok("GET", "/api/search", params={"q": "tomato"})
    assert [a["id"] for a in s["areas"]] == [area["id"]]
    s = admin.ok("GET", "/api/search", params={"q": "compost"})
    assert [t["id"] for t in s["threads"]] == [tid]
    s = admin.ok("GET", "/api/search", params={"q": "worms"})
    assert [m["id"] for m in s["messages"]] == [nested["id"], d["messages"][0]["id"]]
    hit = s["messages"][0]
    assert hit["thread_id"] == tid and hit["context_url"] == f"/api/messages/{nested['id']}/context"
    assert admin.ok("GET", hit["context_url"])["target_id"] == nested["id"]

    admin.ok("POST", f"/api/threads/{tid}/close", {"reason": "completed"})
    s = admin.ok("GET", "/api/search", params={"q": "worms"})
    assert s["messages"] == []
    assert admin.ok("GET", "/api/search", params={"q": "compost"})["threads"] == []
    s = admin.ok("GET", "/api/search", params={"q": "worms", "include_closed": True})
    assert len(s["messages"]) == 2 and s["messages"][0]["closed_reason"] == "completed"
    assert admin.ok("GET", "/api/search", params={"q": "tomato"})["areas"]  # areas not closable

    other = admin.make_area("Elsewhere")
    s = admin.ok("GET", "/api/search", params={"q": "worms", "include_closed": True, "area_id": other["id"]})
    assert s["messages"] == []


def test_search_treats_wildcards_literally_and_validates(admin, area):
    admin.make_thread(area["id"], "t", "100% sure_thing")
    assert len(admin.ok("GET", "/api/search", params={"q": "100%"})["messages"]) == 1
    assert admin.ok("GET", "/api/search", params={"q": "%"})["messages"].__len__() == 1
    assert admin.ok("GET", "/api/search", params={"q": "sure_t"})["messages"].__len__() == 1
    assert admin.ok("GET", "/api/search", params={"q": "s_re"})["messages"] == []
    assert admin.ok("GET", "/api/search", params={"q": "x' OR 1=1 --"})["messages"] == []
    assert admin.get("/api/search").status_code == 422
    assert admin.get("/api/search", params={"q": ""}).status_code == 422


def test_activity_feed(admin, alice, area):
    d = admin.make_thread(area["id"], "feed")
    tid = d["thread"]["id"]
    m = alice.say(tid, "hello")
    admin.ok("POST", f"/api/threads/{tid}/close", {"reason": "completed"})
    admin.ok("POST", f"/api/threads/{tid}/reopen")
    admin.ok("PATCH", f"/api/areas/{area['id']}", {"description": "changed"})
    ev = admin.ok("GET", "/api/activity")["events"]
    assert [e["kind"] for e in ev] == [
        "area_updated", "thread_reopened", "thread_closed",
        "message_posted", "thread_created", "area_created",
    ]
    posted = next(e for e in ev if e["kind"] == "message_posted")
    assert posted["message_id"] == m["id"] and posted["thread_id"] == tid
    assert posted["actor"]["username"] == "alice" and posted["thread_title"] == "feed"
    assert posted["context_url"] == f"/api/messages/{m['id']}/context"
    assert next(e for e in ev if e["kind"] == "thread_closed")["detail"] == "completed"
    page = admin.ok("GET", "/api/activity", params={"limit": 2, "before_id": ev[2]["id"]})["events"]
    assert [e["id"] for e in page] == [ev[3]["id"], ev[4]["id"]]
    assert admin.get("/api/activity", params={"limit": 0}).status_code == 422


@pytest.mark.parametrize("state", ["active", "closed", "all"])
def test_thread_state_param_accepts_values(admin, state):
    assert admin.get("/api/threads", params={"state": state}).status_code == 200


def test_persistence_across_restart(board, admin, alice, area):
    d = admin.make_thread(area["id"], "persist", "kept @alice")
    tid = d["thread"]["id"]
    alice.say(tid, "second")
    admin.ok("POST", f"/api/threads/{tid}/close", {"reason": "archived"})
    token_user = board.client.post("/api/register", json={"username": "pending1", "account_type": "agent", "description": "d"}).json()
    board.restart()
    board.actor_for(admin)
    board.actor_for(alice)
    t = admin.ok("GET", f"/api/threads/{tid}")
    assert t["thread"]["closed"]["reason"] == "archived" and len(t["messages"]) == 2
    assert alice.ok("GET", "/api/me")["username"] == "alice"
    assert board.client.post("/api/login", json={"token": token_user["token"]}).status_code == 403
    assert alice.attention("unacknowledged", include_closed=True)
    nxt = board.client.post("/api/register", json={"username": "second", "account_type": "human"}).json()
    assert nxt["status"] == "pending"

