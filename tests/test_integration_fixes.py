def test_thread_list_paginates_with_pins_separate(admin, area):
    ids = [admin.make_thread(area["id"], f"t{i}")["thread"]["id"] for i in range(5)]
    admin.ok("PUT", f"/api/threads/{ids[0]}/pin", {"pinned": True})
    first = admin.ok("GET", "/api/threads", params={"area_id": area["id"], "limit": 2, "sort": "created"})
    second = admin.ok(
        "GET", "/api/threads", params={"area_id": area["id"], "limit": 2, "offset": 2, "sort": "created"}
    )
    third = admin.ok(
        "GET", "/api/threads", params={"area_id": area["id"], "limit": 2, "offset": 4, "sort": "created"}
    )
    assert [t["id"] for t in first["pinned"]] == [ids[0]]
    paged = [t["id"] for r in (first, second, third) for t in r["threads"]]
    assert paged == [ids[4], ids[3], ids[2], ids[1]]
    assert ids[0] not in paged
    assert [first["has_more"], second["has_more"], third["has_more"]] == [True, False, False]


def test_default_thread_sort_is_importance_with_explicit_alternatives(admin, area):
    low = admin.make_thread(area["id"], "low")["thread"]
    high = admin.make_thread(area["id"], "high")["thread"]
    newest = admin.make_thread(area["id"], "newest")["thread"]
    admin.ok("POST", f"/api/messages/{high['op_message_id']}/votes", {"delta": 10})
    admin.say(low["id"], "bump activity")
    params = {"area_id": area["id"]}
    default = admin.ok("GET", "/api/threads", params=params)["threads"]
    assert [t["id"] for t in default][0] == high["id"]
    created = admin.ok("GET", "/api/threads", params={**params, "sort": "created"})["threads"]
    assert [t["id"] for t in created] == [newest["id"], high["id"], low["id"]]
    activity = admin.ok("GET", "/api/threads", params={**params, "sort": "activity"})["threads"]
    assert activity[0]["id"] == low["id"]


def test_attention_paginates_and_keeps_closed_opt_in(admin, alice, bot, area):
    thread = admin.make_thread(area["id"])["thread"]
    sent = [bot.say(thread["id"], f"m{i} @alice")["id"] for i in range(5)]
    got, offset = [], 0
    while True:
        page = alice.ok(
            "GET",
            "/api/attention",
            params={"status": "unacknowledged", "order": "asc", "limit": 2, "offset": offset},
        )
        got += [m["id"] for m in page["items"]]
        offset += 2
        if not page["has_more"]:
            break
    assert got == sent
    admin.ok("POST", f"/api/threads/{thread['id']}/close", {"reason": "archived"})
    assert alice.ok("GET", "/api/attention")["items"] == []
    closed = alice.ok("GET", "/api/attention", params={"include_closed": "true"})["items"]
    assert len(closed) == 5
    assert {m["thread_closed_reason"] for m in closed} == {"archived"}


def test_message_json_reports_thread_closed_reason(admin, area):
    thread = admin.make_thread(area["id"])["thread"]
    op = thread["op_message_id"]
    assert admin.ok("GET", f"/api/messages/{op}")["thread_closed_reason"] is None
    admin.ok("POST", f"/api/threads/{thread['id']}/close", {"reason": "completed"})
    assert admin.ok("GET", f"/api/messages/{op}")["thread_closed_reason"] == "completed"


def test_search_each_category_fully_reachable(admin, area):
    for i in range(7):
        admin.make_area(f"needle-area-{i}", "d")
        admin.make_thread(area["id"], f"needle thread {i}", f"needle body {i}")
    seen = {"areas": [], "threads": [], "messages": []}
    offsets = {"areas": 0, "threads": 0, "messages": 0}
    for _ in range(10):
        page = admin.ok(
            "GET",
            "/api/search",
            params={
                "q": "needle",
                "limit": 3,
                "areas_offset": offsets["areas"],
                "threads_offset": offsets["threads"],
                "messages_offset": offsets["messages"],
            },
        )
        for key in seen:
            seen[key] += [x["id"] for x in page[key]]
            offsets[key] += len(page[key])
        if not any(page["has_more"].values()):
            break
    assert len(seen["areas"]) == len(set(seen["areas"])) == 7
    assert len(seen["threads"]) == len(set(seen["threads"])) == 7
    assert len(seen["messages"]) == len(set(seen["messages"])) == 7


def test_late_approval_gets_no_backfilled_attention(board, admin, bot, area):
    late = board.register("late", "human", approve=False)
    thread = admin.make_thread(area["id"])["thread"]
    old = bot.say(thread["id"], "before approval @late")
    board.admin.ok("POST", f"/api/admin/users/{late.id}/approve")
    assert late.attention() == {}
    new = bot.say(thread["id"], "after approval @late")
    assert set(late.attention()) == {new["id"]}
    assert old["id"] not in late.attention()


def test_mentions_require_exact_username_including_hyphens(board, admin, area):
    plain = board.register("bobby", "agent")
    hyphen = board.register("bobby-2", "agent")
    thread = admin.make_thread(area["id"])["thread"]
    msg = admin.say(thread["id"], "ping @bobby-2 please")
    assert msg["id"] in hyphen.attention()
    assert msg["id"] not in plain.attention()
    msg2 = admin.say(thread["id"], "ping @bobby")
    assert msg2["id"] in plain.attention()
    assert msg2["id"] not in hyphen.attention()
