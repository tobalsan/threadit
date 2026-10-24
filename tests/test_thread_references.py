"""Thread references observed through the HTTP message read model."""

import pytest


def test_messages_resolve_existing_thread_references(admin, area):
    target = admin.make_thread(area["id"], title="Runner")
    tid = target["thread"]["id"]
    source = admin.make_thread(
        area["id"], title="Notes", body=f"See #{tid}, then #999999."
    )
    expected = {
        str(tid): {
            "id": tid,
            "title": "Runner",
            "area_slug": "ops",
            "closed_reason": None,
        }
    }
    assert source["messages"][0]["linked_threads"] == expected
    read = admin.ok("GET", f"/api/threads/{source['thread']['id']}")
    assert read["messages"][0]["linked_threads"] == expected
    assert target["messages"][0]["linked_threads"] == {}


def test_leading_zero_references_resolve_to_canonical_thread_ids(admin, area):
    target = admin.make_thread(area["id"], title="Runner")["thread"]["id"]
    source = admin.make_thread(area["id"], body=f"See #000{target}")
    assert source["messages"][0]["linked_threads"] == {
        str(target): {
            "id": target,
            "title": "Runner",
            "area_slug": "ops",
            "closed_reason": None,
        }
    }


def test_reference_metadata_reaches_context_attention_and_search(admin, alice, area):
    target = admin.make_thread(area["id"], title="Runner")
    tid = target["thread"]["id"]
    source = admin.make_thread(area["id"], body=f"Notes #{tid}")
    source_id = source["thread"]["id"]
    reply = admin.say(source_id, f"@alice reference #{tid}")
    nested = alice.say(source_id, f"Follow #{tid}", parent_id=reply["id"])
    context = admin.ok("GET", f"/api/messages/{nested['id']}/context")
    assert context["top_level"][0]["linked_threads"][str(tid)]["title"] == "Runner"
    assert context["chain"][0]["linked_threads"][str(tid)]["title"] == "Runner"
    attention = alice.ok("GET", "/api/attention")["items"]
    assert next(m for m in attention if m["id"] == reply["id"])["linked_threads"][str(tid)]["title"] == "Runner"
    hits = admin.ok("GET", "/api/search", params={"q": "reference"})["messages"]
    assert hits[0]["linked_threads"][str(tid)]["title"] == "Runner"


@pytest.mark.parametrize(
    "body,exists",
    [
        ("#{id}", True),
        ("see #{id}.", True),
        ("(#{id})", True),
        ("[#{id}]", True),
        ("line\n#{id}", True),
        ("`#{id}`", False),
        ("`see #{id}`", True),
        ("```\n#{id}\n```", True),
        ("a#{id}", False),
        ("#{id}abc", False),
        ("#{id}_", False),
        ("&#{id};", False),
        ("/#{id}", False),
        ("https://x.com/?q=#{id}", False),
    ],
)
def test_only_references_at_specified_boundaries_resolve(admin, area, body, exists):
    target = admin.make_thread(area["id"], title="Target")["thread"]["id"]
    source = admin.make_thread(area["id"], body=body.format(id=target))
    refs = source["messages"][0]["linked_threads"]
    assert list(refs) == ([str(target)] if exists else [])


def test_references_stay_current_on_every_message_response(admin, alice, area):
    target = alice.make_thread(area["id"], title="Old runner")["thread"]["id"]
    source = admin.make_thread(area["id"])["thread"]["id"]
    posted = admin.say(source, f"See #{target}")
    mid = posted["id"]
    assert posted["linked_threads"][str(target)]["title"] == "Old runner"
    assert alice.attention() == {}
    alice.ok("PATCH", f"/api/threads/{target}", {"title": "New runner"})
    alice.ok("POST", f"/api/threads/{target}/close", {"reason": "completed"})
    for message in [
        admin.ok("GET", f"/api/messages/{mid}"),
        admin.ok("GET", f"/api/threads/{source}/messages")["messages"][-1],
        admin.ok("PATCH", f"/api/messages/{mid}", {"body": f"Now #{target}"}),
        admin.react(mid, "👍"),
        admin.ok("DELETE", f"/api/messages/{mid}/reactions/👍"),
    ]:
        assert message["linked_threads"] == {
            str(target): {
                "id": target,
                "title": "New runner",
                "area_slug": "ops",
                "closed_reason": "completed",
            }
        }
    assert alice.attention() == {}
    deleted = admin.ok("DELETE", f"/api/messages/{mid}")
    assert deleted["linked_threads"] == {}


def _backlinks(admin, tid):
    return admin.ok("GET", f"/api/threads/{tid}")["referenced_by"]


def test_backlink_lists_other_thread_with_newest_message(admin, area):
    target = admin.make_thread(area["id"], title="Runner")["thread"]["id"]
    src = admin.make_thread(area["id"], title="Notes", body=f"See #{target}")
    newest = admin.say(src["thread"]["id"], f"again #{target}")
    admin.say(src["thread"]["id"], "no reference")
    (entry,) = _backlinks(admin, target)
    assert entry["thread_id"] == src["thread"]["id"]
    assert entry["title"] == "Notes"
    assert entry["area_slug"] == "ops"
    assert entry["area_name"] == "Ops"
    assert entry["closed_reason"] is None
    assert entry["message_id"] == newest["id"]
    assert entry["author"] == "root"
    assert entry["at"] == newest["created_at"]
    assert _backlinks(admin, src["thread"]["id"]) == []


def test_backlink_includes_closed_thread(admin, area):
    target = admin.make_thread(area["id"])["thread"]["id"]
    src = admin.make_thread(area["id"], body=f"#{target}")["thread"]["id"]
    admin.ok("POST", f"/api/threads/{src}/close", {"reason": "archived"})
    assert [e["closed_reason"] for e in _backlinks(admin, target)] == ["archived"]


def test_backlink_ignores_self_deleted_and_longer_ids(admin, area):
    target = admin.make_thread(area["id"])["thread"]["id"]
    admin.say(target, f"self #{target}")
    gone = admin.make_thread(area["id"], body=f"#{target}")
    admin.ok("DELETE", f"/api/messages/{gone['messages'][0]['id']}")
    admin.make_thread(area["id"], body=f"#{target}0 and #{target}x")
    assert _backlinks(admin, target) == []


def test_backlink_ignores_code(admin, area):
    target = admin.make_thread(area["id"])["thread"]["id"]
    admin.make_thread(area["id"], body=f"inline `see #{target}` here")
    admin.make_thread(area["id"], body=f"```\nsee #{target}\n```")
    assert _backlinks(admin, target) == []


def test_backlinks_newest_first(admin, area):
    target = admin.make_thread(area["id"])["thread"]["id"]
    first = admin.make_thread(area["id"], body=f"#{target}")["thread"]["id"]
    second = admin.make_thread(area["id"], body=f"#{target}")["thread"]["id"]
    admin.say(first, f"bump #{target}")
    assert [e["thread_id"] for e in _backlinks(admin, target)] == [first, second]


def test_backlink_code_span_does_not_join_text_to_reference(admin, area):
    target = admin.make_thread(area["id"])["thread"]["id"]
    admin.make_thread(area["id"], body=f"x `code`#{target}")
    admin.make_thread(area["id"], body=f"x ```\ncode\n```#{target}")
    assert _backlinks(admin, target) == []


def test_backlink_counts_leading_zeros(admin, area):
    target = admin.make_thread(area["id"])["thread"]["id"]
    src = admin.make_thread(area["id"], body=f"see #000{target}")["thread"]["id"]
    assert [e["thread_id"] for e in _backlinks(admin, target)] == [src]


def test_backlink_ignores_fence_with_inner_backticks(admin, area):
    target = admin.make_thread(area["id"])["thread"]["id"]
    admin.make_thread(area["id"], body=f"```\na ```b\nsee #{target}\n```")
    assert _backlinks(admin, target) == []
