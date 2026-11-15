from test_features import upload


def ids(msg):
    return [a["id"] for a in msg["attachments"]]


def posted(actor, thread_id, n=1):
    att = [upload(actor).json()["id"] for _ in range(n)]
    msg = actor.ok("POST", f"/api/threads/{thread_id}/messages", {"body": "hi", "attachment_ids": att}, 201)
    return msg, att


def patch(actor, mid, **body):
    return actor.call("PATCH", f"/api/messages/{mid}", json=body)


def test_replace_add_remove_and_clear(alice, area):
    tid = alice.make_thread(area["id"])["thread"]["id"]
    msg, (a1, a2) = posted(alice, tid, 2)
    new = upload(alice).json()["id"]
    r = patch(alice, msg["id"], attachment_ids=[a1, new])  # replace a2 with new
    assert r.status_code == 200 and ids(r.json()) == [a1, new]
    assert r.json()["body"] == "hi" and r.json()["edited_at"]
    assert alice.get(f"/api/attachments/{a2}").status_code == 404
    more = upload(alice).json()["id"]
    assert ids(patch(alice, msg["id"], attachment_ids=[a1, new, more]).json()) == [a1, new, more]
    assert ids(patch(alice, msg["id"], attachment_ids=[a1, more]).json()) == [a1, more]
    assert ids(patch(alice, msg["id"], attachment_ids=[]).json()) == []
    for gone in (a1, new, more):
        assert alice.get(f"/api/attachments/{gone}").status_code == 404


def test_body_only_and_attachments_only(alice, area):
    tid = alice.make_thread(area["id"])["thread"]["id"]
    msg, att = posted(alice, tid)
    r = patch(alice, msg["id"], body="new body").json()
    assert r["body"] == "new body" and ids(r) == att
    r = patch(alice, msg["id"], attachment_ids=[]).json()
    assert r["body"] == "new body" and ids(r) == []


def test_invalid_patches(admin, alice, bob, area):
    tid = alice.make_thread(area["id"])["thread"]["id"]
    msg, att = posted(alice, tid)
    other, other_att = posted(alice, tid)
    assert patch(alice, msg["id"]).status_code == 422
    assert patch(alice, msg["id"], body="").status_code == 422
    bobs = upload(bob).json()["id"]
    r = patch(alice, msg["id"], attachment_ids=att + [bobs])
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_attachment"
    r = patch(alice, msg["id"], attachment_ids=other_att)
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_attachment"
    eleven = att + [upload(alice).json()["id"] for _ in range(10)]
    assert patch(alice, msg["id"], attachment_ids=eleven).status_code == 422
    # failed edits changed nothing
    assert ids(alice.ok("GET", f"/api/messages/{msg['id']}")) == att
    assert ids(alice.ok("GET", f"/api/messages/{other['id']}")) == other_att
    r = patch(bob, msg["id"], attachment_ids=[])
    assert r.status_code == 403
    admin.ok("POST", f"/api/threads/{tid}/close", {"reason": "completed"})
    assert patch(alice, msg["id"], attachment_ids=[]).status_code == 409


def test_superadmin_keeps_removes_and_adds_own_uploads(admin, alice, area):
    tid = alice.make_thread(area["id"])["thread"]["id"]
    msg, (a1, a2) = posted(alice, tid, 2)
    mine = upload(admin).json()["id"]
    r = patch(admin, msg["id"], attachment_ids=[a1, mine])
    assert r.status_code == 200 and ids(r.json()) == [a1, mine]
    alices = upload(alice).json()["id"]
    assert patch(admin, msg["id"], attachment_ids=[alices]).status_code == 422
