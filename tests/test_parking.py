import sqlite3
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


def parking_dates():
    today = datetime.now(ZoneInfo("Europe/Paris")).date()
    return [(today + timedelta(days=days)).isoformat() for days in (-1, 0, 1, 7)]


def test_approved_accounts_can_park_and_unpark_without_bumping_activity(alice, bot, area):
    thread = alice.make_thread(area["id"])["thread"]
    url = f"/api/threads/{thread['id']}"
    yesterday, today, tomorrow, next_week = parking_dates()

    for invalid in (yesterday, today, "2026-02-30", "20261126", 1795651200):
        response = alice.post(f"{url}/park", {"until": invalid})
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_input"

    for actor, date in ((alice, tomorrow), (bot, next_week)):
        parked = actor.ok("POST", f"{url}/park", {"until": date})
        assert parked["parked_until"] == date
        assert parked["last_activity_at"] == thread["last_activity_at"]
    for actor in (bot, alice):
        unparked = actor.ok("POST", f"{url}/unpark")
        assert unparked["parked_until"] is None
        assert unparked["last_activity_at"] == thread["last_activity_at"]

    events = alice.ok("GET", "/api/activity")["events"]
    updates = [(e["kind"], e["detail"]) for e in events if e["kind"] in (
        "thread_parked", "thread_unparked"
    )]
    assert updates == [("thread_unparked", ""), ("thread_parked", next_week), ("thread_parked", tomorrow)]

    bot.ok("POST", f"{url}/park", {"until": tomorrow})
    assert bot.ok("POST", f"{url}/close", {"reason": "completed"})["parked_until"] is None
    response = bot.post(f"{url}/park", {"until": tomorrow})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "thread_closed"
    assert alice.ok("POST", f"{url}/reopen")["parked_until"] is None


def test_parked_threads_sort_last_and_keep_disjoint_area_counts(admin, alice, area):
    def create(title, body="Plan"):
        return alice.make_thread(area["id"], title, body)["thread"]["id"]

    pinned, ordinary = create("Pinned"), create("Ordinary")
    parked, closed = create("Deferred work", "For @root"), create("Finished")
    alice.ok("PUT", f"/api/threads/{pinned}/pin", {"pinned": True})
    alice.ok("PUT", f"/api/threads/{parked}/pin", {"pinned": True})
    alice.ok("POST", f"/api/threads/{parked}/park", {"until": parking_dates()[3]})
    alice.ok("POST", f"/api/threads/{closed}/close", {"reason": "completed"})
    other_area = alice.make_area("Other")
    other = alice.make_thread(other_area["id"])["thread"]["id"]
    alice.ok("POST", f"/api/threads/{other}/park", {"until": parking_dates()[3]})

    def listing(**params):
        return admin.ok("GET", "/api/threads", params={
            "area_id": area["id"], "sort": "created", **params
        })

    default = listing()
    assert default["parked_count"] == 1
    assert [t["id"] for t in default["pinned"]] == [pinned]
    assert [t["id"] for t in default["threads"]] == [ordinary]
    for order in ("asc", "desc"):
        included = listing(parked="include", order=order)
        assert included["parked_count"] == 1
        assert [t["id"] for t in included["pinned"]] == [pinned]
        assert [t["id"] for t in included["threads"]] == [ordinary, parked]
    with_hot = listing(parked="include", sort="hot")
    assert with_hot["pinned"] == []
    assert {t["id"] for t in with_hot["threads"][:-1]} == {ordinary, pinned}
    assert with_hot["threads"][-1]["id"] == parked
    first = listing(parked="include", limit=1)
    assert first["has_more"]
    last = listing(parked="include", limit=1, offset=1)
    assert [t["id"] for t in last["threads"]] == [parked]
    assert not last["has_more"] and last["parked_count"] == 1
    assert listing(state="closed")["parked_count"] == 0
    assert listing(state="all")["parked_count"] == 1

    latest = alice.ok("GET", f"/api/threads/{closed}")["thread"]["last_activity_at"]
    listed_area = next(a for a in admin.ok("GET", "/api/areas")["areas"] if a["id"] == area["id"])
    detailed_area = admin.ok("GET", f"/api/areas/{area['slug']}")
    for counts in (listed_area, detailed_area):
        assert (counts["active_threads"], counts["parked_threads"], counts["closed_threads"]) == (2, 1, 1)
        assert counts["last_activity_at"] == latest
    attention = admin.ok("GET", "/api/attention")
    assert attention["unacknowledged_count"] == 1
    item = attention["items"][0]
    assert item["thread_id"] == parked
    assert admin.ok("GET", item["context_url"])["thread"]["id"] == parked
    search = admin.ok("GET", "/api/search", params={"q": "Deferred work"})
    assert [t["id"] for t in search["threads"]] == [parked]


def test_only_new_messages_that_create_attention_unpark(alice, bob, bot, area):
    thread = alice.make_thread(area["id"], body="Original @botty")["thread"]
    thread_id, op_id = thread["id"], thread["op_message_id"]
    url = f"/api/threads/{thread_id}"
    date = parking_dates()[3]

    def park():
        alice.ok("POST", f"{url}/park", {"until": date})

    def parked_until():
        return alice.ok("GET", url)["thread"]["parked_until"]

    park()
    note = alice.say(thread_id, "A note to myself")
    assert parked_until() == date
    alice.ok("PATCH", f"/api/messages/{note['id']}", {"body": "Edited note @bob"})
    assert parked_until() == date
    bob.react(op_id, "👍")
    assert parked_until() == date
    bob.ok("POST", f"/api/messages/{op_id}/votes", {"delta": 1})
    assert parked_until() == date
    bot.ok("POST", f"/api/messages/{op_id}/agent-activities", {"kind": "thought", "body": "A thought"}, 201)
    assert parked_until() == date

    alice.say(thread_id, "Question for @bob")
    assert parked_until() is None
    park()
    reply = bob.say(thread_id, "I can help")
    assert parked_until() is None
    park()
    alice.say(thread_id, "Thanks", parent_id=reply["id"])
    assert parked_until() is None


def test_an_expired_park_date_reads_as_unparked(board, alice, area):
    thread_id = alice.make_thread(area["id"])["thread"]["id"]
    yesterday, today, tomorrow, _ = parking_dates()
    for stored_date, visible_date in ((yesterday, None), (today, None), (tomorrow, tomorrow)):
        with sqlite3.connect(board.path) as conn:
            conn.execute("UPDATE threads SET parked_until = ? WHERE id = ?", (stored_date, thread_id))
        thread = alice.ok("GET", f"/api/threads/{thread_id}")["thread"]
        assert thread["parked_until"] == visible_date
        listing = alice.ok("GET", "/api/threads")
        assert listing["parked_count"] == int(visible_date is not None)
        assert [t["id"] for t in listing["threads"]] == ([] if visible_date else [thread_id])


def test_paris_midnight_in_winter_and_summer():
    from threadit.db import paris_today

    for month, hour in ((1, 23), (7, 22)):
        midnight = datetime(2026, month, 15, hour, tzinfo=timezone.utc)
        assert paris_today(midnight - timedelta(microseconds=1)) == f"2026-{month:02d}-15"
        assert paris_today(midnight) == f"2026-{month:02d}-16"
