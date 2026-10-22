"""Every attention rule, via HTTP."""

EYES, CHECK = "👀", "✅"


def status_of(actor, message_id, **params):
    return actor.attention("all", include_closed=True, **params).get(message_id)


def test_agent_top_level_needs_explicit_mention(admin, bot, bot2, area):
    d = admin.make_thread(area["id"], "t", "no mention here")
    tid, op = d["thread"]["id"], d["messages"][0]["id"]
    assert status_of(bot, op) is None and status_of(bot2, op) is None
    peer = admin.say(tid, "ping @BOTTY please")  # case-insensitive, top-level reply
    assert status_of(bot, peer["id"]) == {"status": "unacknowledged", "reason": "mention"}
    assert status_of(bot2, peer["id"]) is None
    d2 = admin.make_thread(area["id"], "t2", "hey @robo and @botty")
    op2 = d2["messages"][0]["id"]
    assert status_of(bot, op2) and status_of(bot2, op2)
    # substring / email-like / unknown mentions do nothing
    plain = admin.say(tid, "mail me@botty.com or @botty2 or @nobody")
    assert status_of(bot, plain["id"]) is None


def test_nested_reply_notifies_only_direct_parent_author_and_mentions(admin, alice, bot, bot2, area):
    d = admin.make_thread(area["id"], "t", "op by admin")
    tid = d["thread"]["id"]
    top = bot.say(tid, "bot top")  # top-level, no mention
    child = admin.say(tid, "reply to bot", top["id"])
    assert status_of(bot, child["id"])["reason"] == "reply"
    grand = alice.say(tid, "reply to admin", child["id"])
    assert status_of(bot, grand["id"]) is None  # no branch inheritance
    ment = alice.say(tid, "reply to admin + @robo", child["id"])
    assert status_of(bot2, ment["id"])["reason"] == "mention"
    assert status_of(bot, ment["id"]) is None
    # nested reply by agent to its own message: no self-notification
    own = bot.say(tid, "talking to myself @botty", top["id"])
    assert status_of(bot, own["id"]) is None
    # agent replying to another agent's message notifies that agent
    reply_agent = bot2.say(tid, "agent to agent", top["id"])
    assert status_of(bot, reply_agent["id"])["reason"] == "reply"
    # human replying directly to top-level OP-peer by an agent also works for top-level parent
    assert status_of(admin, child["id"]) is None  # human own msg


def test_top_level_reply_notifies_op_author(admin, bot, area):
    d = admin.make_thread(area["id"], "t", "op")
    reply = bot.say(d["thread"]["id"], "top-level reply")
    assert status_of(bot, d["messages"][0]["id"]) is None
    assert status_of(admin, reply["id"]) == {"status": "unacknowledged", "reason": "reply"}
    own = admin.say(d["thread"]["id"], "OP author replies too")
    assert status_of(admin, own["id"]) is None  # no self-notification


def test_reply_with_op_as_parent_becomes_top_level(admin, alice, area):
    d = admin.make_thread(area["id"], "t", "hi @alice")
    tid, op = d["thread"]["id"], d["messages"][0]["id"]
    reply = alice.say(tid, "answer", op)
    assert reply["parent_id"] is None
    assert status_of(admin, reply["id"])["reason"] == "reply"
    # replying to the OP acknowledges the human's own attention on it
    assert status_of(alice, op)["status"] == "acknowledged"


def test_agent_status_transitions_only_for_reserved_emoji(admin, bot, area):
    d = admin.make_thread(area["id"], "t", "hi @botty")
    op = d["messages"][0]["id"]
    assert status_of(bot, op)["status"] == "unacknowledged"
    bot.react(op, "👍")
    assert status_of(bot, op)["status"] == "unacknowledged"
    m = bot.react(op, EYES)
    assert status_of(bot, op)["status"] == "processing"
    assert m["my_attention"]["status"] == "processing"
    bot.react(op, "🎉")
    assert status_of(bot, op)["status"] == "processing"
    m = bot.react(op, CHECK)
    assert status_of(bot, op)["status"] == "processed"
    emojis = {r["emoji"] for r in m["reactions"]}
    assert EYES not in emojis and CHECK in emojis and "👍" in emojis  # 👀 replaced
    bot.react(op, EYES)
    assert status_of(bot, op)["status"] == "processing"
    assert CHECK not in {r["emoji"] for r in admin.ok("GET", f"/api/messages/{op}")["reactions"]}
    bot.ok("DELETE", f"/api/messages/{op}/reactions/{EYES}")
    assert status_of(bot, op)["status"] == "unacknowledged"
    bot.ok("DELETE", f"/api/messages/{op}/reactions/👍")
    assert status_of(bot, op)["status"] == "unacknowledged"


def test_agent_reaction_by_unrelated_agent_or_human_does_not_change_others(admin, bot, bot2, area):
    d = admin.make_thread(area["id"], "t", "hi @botty")
    op = d["messages"][0]["id"]
    bot2.react(op, CHECK)  # bot2 has no attention row
    admin.react(op, EYES)
    assert status_of(bot, op)["status"] == "unacknowledged"
    assert status_of(bot2, op) is None


def test_agent_status_filters(admin, bot, area):
    ids = []
    for i in range(4):
        ids.append(admin.make_thread(area["id"], f"t{i}", "@botty go")["messages"][0]["id"])
    bot.react(ids[1], EYES)
    bot.react(ids[2], CHECK)
    bot.react(ids[3], CHECK)
    f = lambda s: sorted(bot.attention(s))  # noqa: E731
    assert f("all") == sorted(ids)
    assert f("unacknowledged") == [ids[0]]
    assert f("processing") == [ids[1]]
    assert f("processed") == [ids[2], ids[3]]
    assert f("acknowledged") == []
    assert list(bot.attention("all", order="desc")) == sorted(ids, reverse=True)
    assert list(bot.attention("all", limit=2)) == ids[:2]
    assert bot.get("/api/attention", params={"status": "bogus"}).status_code == 422


def test_agent_messages_notify_humans_only_via_mention_or_direct_reply(admin, alice, bob, bot, bot2, area):
    d = admin.make_thread(area["id"], "t", "human op")
    tid, op = d["thread"]["id"], d["messages"][0]["id"]
    top = bot.say(tid, "agent top-level, no mention")
    nested = bot2.say(tid, "agent to agent nested", top["id"])
    assert status_of(admin, top["id"]) == {"status": "unacknowledged", "reason": "reply"}
    for human in (admin, alice, bob):
        assert status_of(human, nested["id"]) is None
    assert status_of(alice, top["id"]) is None and status_of(bob, top["id"]) is None
    reply = bot.say(tid, "agent answers admin", op)
    assert status_of(admin, reply["id"]) == {"status": "unacknowledged", "reason": "reply"}
    assert status_of(alice, reply["id"]) is None and status_of(bob, reply["id"]) is None
    ment = bot.say(tid, "fyi @alice", top["id"])
    assert status_of(alice, ment["id"]) == {"status": "unacknowledged", "reason": "mention"}
    assert status_of(admin, ment["id"]) is None and status_of(bob, ment["id"]) is None
    # agent OP notifies nobody without a mention
    agent_op = bot.make_thread(area["id"], "agent thread", "agent op")["messages"][0]["id"]
    assert all(status_of(h, agent_op) is None for h in (admin, alice, bob))


def test_human_messages_notify_humans_only_via_mention_or_direct_reply(admin, alice, bob, area):
    d = admin.make_thread(area["id"], "t", "plain op")
    tid, op = d["thread"]["id"], d["messages"][0]["id"]
    assert status_of(alice, op) is None and status_of(bob, op) is None
    peer = alice.say(tid, "peer, no mention")
    assert status_of(admin, peer["id"])["reason"] == "reply"  # OP author
    assert status_of(bob, peer["id"]) is None
    ment = alice.say(tid, "hey @BOB and @alice")
    assert status_of(bob, ment["id"]) == {"status": "unacknowledged", "reason": "mention"}
    assert status_of(alice, ment["id"]) is None  # no self-notification
    assert status_of(admin, ment["id"])["reason"] == "reply"
    reply = bob.say(tid, "reply to alice's", peer["id"])
    assert status_of(alice, reply["id"])["reason"] == "reply"
    assert status_of(admin, reply["id"]) is None  # admin was not the direct parent
    deeper = admin.say(tid, "nested under bob", reply["id"])
    assert status_of(bob, deeper["id"])["reason"] == "reply"
    assert status_of(alice, deeper["id"]) is None


def test_human_acknowledged_by_own_emoji_only_that_message(admin, alice, bot, area):
    d = admin.make_thread(area["id"], "t", "op")
    tid = d["thread"]["id"]
    m1 = bot.say(tid, "one @alice @root")
    m2 = bot.say(tid, "two @alice @root")
    m3 = bot.say(tid, "three @alice @root")
    # reading never acknowledges
    alice.ok("GET", f"/api/threads/{tid}")
    alice.ok("GET", f"/api/messages/{m1['id']}")
    alice.ok("GET", f"/api/messages/{m1['id']}/context")
    alice.ok("GET", f"/api/threads/{tid}/messages")
    pending = alice.attention("unacknowledged")
    assert set(pending) == {m1["id"], m2["id"], m3["id"]}
    alice.react(m2["id"], "👍")  # any emoji
    assert set(alice.attention("unacknowledged")) == {m1["id"], m3["id"]}
    assert alice.attention("acknowledged") == {m2["id"]: {"status": "acknowledged", "reason": "mention"}}
    # per-human independence
    assert set(admin.attention("unacknowledged")) == {m1["id"], m2["id"], m3["id"]}
    # removing the emoji does not re-open
    alice.ok("DELETE", f"/api/messages/{m2['id']}/reactions/👍")
    assert m2["id"] in alice.attention("acknowledged")
    # someone else's reaction does not acknowledge mine
    admin.react(m1["id"], EYES)
    assert m1["id"] in alice.attention("unacknowledged")
    # a human reacting with 👀/✅ is just an emoji (no processing states)
    alice.react(m3["id"], CHECK)
    assert alice.attention("all")[m3["id"]]["status"] == "acknowledged"


def test_human_acknowledged_by_direct_reply_only_that_message(admin, alice, bot, area):
    d = admin.make_thread(area["id"], "t", "op")
    tid = d["thread"]["id"]
    m1 = bot.say(tid, "one @alice @root")
    m2 = bot.say(tid, "two @alice @root")
    child = bot.say(tid, "nested under one @alice", m1["id"])
    alice.say(tid, "my reply", m1["id"])
    pend = alice.attention("unacknowledged")
    assert m1["id"] not in pend and {m2["id"], child["id"]} <= set(pend)
    # a top-level peer post does not acknowledge anything
    alice.say(tid, "peer post")
    assert {m2["id"], child["id"]} <= set(alice.attention("unacknowledged"))
    # an agent reply does not acknowledge a human's attention
    reply_to_m2 = bot.say(tid, "agent reply @alice", m2["id"])
    assert m2["id"] in alice.attention("unacknowledged") and reply_to_m2["id"] in alice.attention("unacknowledged")


def test_new_agent_messages_pending_independently_no_thread_clearing(admin, alice, bot, area):
    d = admin.make_thread(area["id"], "t", "op")
    tid = d["thread"]["id"]
    first = bot.say(tid, "first @alice @root")
    alice.react(first["id"], "👍")
    second = bot.say(tid, "second @alice @root")
    assert set(alice.attention("unacknowledged")) == {second["id"]}
    thread = alice.ok("GET", f"/api/threads/{tid}")["thread"]
    assert thread["pending_attention"] == 1  # derived from pending messages
    alice.react(second["id"], "👍")
    assert alice.ok("GET", f"/api/threads/{tid}")["thread"]["pending_attention"] == 0
    assert admin.ok("GET", f"/api/threads/{tid}")["thread"]["pending_attention"] == 2


def test_attention_items_carry_context_links(admin, alice, bot, area):
    d = admin.make_thread(area["id"], "ctx thread", "op")
    m = bot.say(d["thread"]["id"], "agent says hi @alice")
    item = alice.ok("GET", "/api/attention", params={"status": "unacknowledged"})["items"][0]
    assert item["id"] == m["id"] and item["thread_title"] == "ctx thread"
    assert item["area_name"] == "Ops" and item["context_url"] == f"/api/messages/{m['id']}/context"
    assert alice.ok("GET", item["context_url"])["target_id"] == m["id"]


def test_closed_threads_excluded_from_attention_until_reopened(admin, alice, bot, area):
    d = admin.make_thread(area["id"], "t", "op @botty")
    tid, op = d["thread"]["id"], d["messages"][0]["id"]
    m = bot.say(tid, "agent msg @alice")
    assert op in bot.attention("unacknowledged") and m["id"] in alice.attention("unacknowledged")
    admin.ok("POST", f"/api/threads/{tid}/close", {"reason": "completed"})
    assert bot.attention("unacknowledged") == {} and alice.attention("unacknowledged") == {}
    assert op in bot.attention("unacknowledged", include_closed=True)
    assert alice.ok("GET", f"/api/threads/{tid}")["thread"]["pending_attention"] == 0
    # cannot clear attention while closed
    assert alice.post(f"/api/messages/{m['id']}/reactions", {"emoji": "👍"}).status_code == 409
    assert bot.post(f"/api/messages/{op}/reactions", {"emoji": EYES}).status_code == 409
    admin.ok("POST", f"/api/threads/{tid}/reopen")
    assert op in bot.attention("unacknowledged") and m["id"] in alice.attention("unacknowledged")
    assert alice.ok("GET", f"/api/threads/{tid}")["thread"]["pending_attention"] == 1


def test_pending_accounts_receive_no_attention_rows(board, admin, area):
    pend = board.register("waiting", "human", approve=False)
    bot = board.register("agentx", "agent")
    bot.make_thread(area["id"], "t", "hi @waiting")
    board.admin.ok("POST", f"/api/admin/users/{pend.id}/approve")
    assert pend.attention("all") == {}
