def test_human_acknowledge_all_counts_and_leaves_others(admin, alice, bob, bot, area):
    t = admin.make_thread(area["id"])["thread"]["id"]
    m1 = bot.say(t, "one @alice @bob")["id"]
    m2 = bot.say(t, "two @alice @bob")["id"]
    assert alice.get("/api/attention", params={"status": "unacknowledged"}).json()["unacknowledged_count"] == 2
    assert alice.ok("POST", "/api/attention/acknowledge-all") == {"acknowledged": 2}
    states = alice.attention()
    assert states[m1]["status"] == states[m2]["status"] == "acknowledged"
    items = {m["id"]: m for m in alice.ok("GET", "/api/attention")["items"]}
    assert {r["emoji"] for r in items[m1]["reactions"]} == {"✅"}
    assert bob.attention("unacknowledged").keys() >= {m1, m2}
    assert alice.ok("POST", "/api/attention/acknowledge-all") == {"acknowledged": 0}


def test_agent_acknowledge_all_marks_processed(admin, bot, area):
    t = admin.make_thread(area["id"], "T", "x")["thread"]["id"]
    m1 = admin.say(t, "hi @botty")["id"]
    m2 = admin.say(t, "yo @botty")["id"]
    bot.react(m2, "👀")
    assert bot.ok("POST", "/api/attention/acknowledge-all") == {"acknowledged": 1}
    states = bot.attention()
    assert states[m1]["status"] == "processed"
    assert states[m2]["status"] == "processing"


def test_acknowledge_all_empty_queue(alice):
    assert alice.ok("POST", "/api/attention/acknowledge-all") == {"acknowledged": 0}
    assert alice.get("/api/attention").json()["unacknowledged_count"] == 0


def test_acknowledge_all_closed_threads_need_include_closed(admin, alice, bot, area):
    open_t = admin.make_thread(area["id"], "open")["thread"]["id"]
    closed_t = admin.make_thread(area["id"], "closed")["thread"]["id"]
    open_m = bot.say(open_t, "a @alice")["id"]
    closed_m = bot.say(closed_t, "b @alice")["id"]
    admin.ok("POST", f"/api/threads/{closed_t}/close", {"reason": "completed"})
    assert alice.get("/api/attention", params={"include_closed": "true"}).json()["unacknowledged_count"] == 2
    assert alice.get("/api/attention").json()["unacknowledged_count"] == 1
    assert alice.ok("POST", "/api/attention/acknowledge-all") == {"acknowledged": 1}
    states = alice.attention(include_closed="true")
    assert states[open_m]["status"] == "acknowledged"
    assert states[closed_m]["status"] == "unacknowledged"
    assert alice.ok("POST", "/api/attention/acknowledge-all", params={"include_closed": "true"}) == {
        "acknowledged": 1
    }
    assert alice.attention(include_closed="true")[closed_m]["status"] == "acknowledged"


def test_acknowledge_all_creates_no_attention_or_activity(admin, alice, bob, bot, area):
    t = admin.make_thread(area["id"])["thread"]["id"]
    bot.say(t, "one @alice")
    before = admin.ok("GET", "/api/activity")["events"]
    bob_before = bob.attention()
    alice.ok("POST", "/api/attention/acknowledge-all")
    assert admin.ok("GET", "/api/activity")["events"] == before
    assert bob.attention() == bob_before
