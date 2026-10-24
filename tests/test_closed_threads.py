"""Completed and archived lists observed through GET /api/threads."""

import sqlite3

import pytest


def test_closed_reason_filters_do_not_mix_completed_and_archived(admin, area):
    completed = admin.make_thread(area["id"], title="Finished")["thread"]["id"]
    archived = admin.make_thread(area["id"], title="Abandoned")["thread"]["id"]
    admin.make_thread(area["id"], title="Still going")
    admin.ok("POST", f"/api/threads/{completed}/close", {"reason": "completed"})
    admin.ok("POST", f"/api/threads/{archived}/close", {"reason": "archived"})
    done = admin.ok("GET", "/api/threads", params={"state": "completed"})
    abandoned = admin.ok("GET", "/api/threads", params={"state": "archived"})
    assert [t["id"] for t in done["threads"]] == [completed]
    assert [t["id"] for t in abandoned["threads"]] == [archived]


def test_closed_order_uses_close_time_and_id_without_separating_pins(board, admin, area):
    recent = admin.make_thread(area["id"], title="Recent")["thread"]["id"]
    old = admin.make_thread(area["id"], title="Old pinned")["thread"]["id"]
    tied = admin.make_thread(area["id"], title="Same close time")["thread"]["id"]
    active = admin.make_thread(area["id"], title="Active")["thread"]["id"]
    admin.ok("PUT", f"/api/threads/{old}/pin", {"pinned": True})
    for tid in [recent, old, tied]:
        admin.ok("POST", f"/api/threads/{tid}/close", {"reason": "completed"})
    with sqlite3.connect(board.path) as conn:
        conn.executemany(
            "UPDATE threads SET closed_at = ? WHERE id = ?",
            [
                ("2026-10-23T10:00:00.000000+00:00", recent),
                ("2026-10-20T10:00:00.000000+00:00", old),
                ("2026-10-23T10:00:00.000000+00:00", tied),
            ],
        )
    result = admin.ok("GET", "/api/threads", params={"state": "all", "sort": "closed"})
    assert result["pinned"] == []
    assert [t["id"] for t in result["threads"]] == [tied, recent, old, active]
    result = admin.ok(
        "GET", "/api/threads", params={"state": "all", "sort": "closed", "order": "asc"}
    )
    assert [t["id"] for t in result["threads"]] == [old, recent, tied, active]
    page = admin.ok(
        "GET", "/api/threads", params={"state": "completed", "sort": "closed", "limit": 2}
    )
    assert [t["id"] for t in page["threads"]] == [tied, recent]
    assert page["has_more"] is True
    assert admin.get("/api/threads", params={"sort": "closed"}).status_code == 200


def test_closed_since_is_inclusive_and_normalizes_timezone(board, admin, area):
    before = admin.make_thread(area["id"], title="Before cutoff")["thread"]["id"]
    exact = admin.make_thread(area["id"], title="At cutoff")["thread"]["id"]
    after = admin.make_thread(area["id"], title="After cutoff")["thread"]["id"]
    admin.make_thread(area["id"], title="Active")
    for tid in [before, exact, after]:
        admin.ok("POST", f"/api/threads/{tid}/close", {"reason": "completed"})
    with sqlite3.connect(board.path) as conn:
        conn.executemany(
            "UPDATE threads SET closed_at = ? WHERE id = ?",
            [
                ("2026-10-17T09:59:59.999999+00:00", before),
                ("2026-10-17T10:00:00.000000+00:00", exact),
                ("2026-10-17T10:00:00.000001+00:00", after),
            ],
        )
    for cutoff in ["2026-10-17T10:00:00Z", "2026-10-17T12:00:00+02:00"]:
        data = admin.ok(
            "GET",
            "/api/threads",
            params={"state": "all", "sort": "closed", "closed_since": cutoff},
        )
        assert [t["id"] for t in data["threads"]] == [after, exact]
        active = admin.ok(
            "GET", "/api/threads", params={"state": "active", "closed_since": cutoff}
        )
        assert active["threads"] == []
        assert active["pinned"] == []


@pytest.mark.parametrize(
    "cutoff",
    [
        "not-a-date",
        "2026-10-17T10:00:00",
        "2026-10-17",
        "",
        "2026-13-17T10:00:00Z",
        "0001-01-01T00:00:00+01:00",
        "9999-12-31T23:59:59-01:00",
    ],
)
def test_closed_since_rejects_invalid_or_timezone_free_values(admin, cutoff):
    response = admin.get("/api/threads", params={"closed_since": cutoff})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_input"
