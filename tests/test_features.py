import sqlite3

from fastapi.testclient import TestClient

from threadit import create_app

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20


def upload(actor, data=PNG, filename="pic.png", content_type="image/png"):
    return actor.client.post(
        "/api/attachments",
        params={"filename": filename},
        content=data,
        headers={**actor.headers, "Content-Type": content_type},
    )


# ---------- user descriptions ----------


def test_register_description_rules(board):
    r = board.client.post("/api/register", json={"username": "ann", "account_type": "agent"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_input"
    r = board.client.post(
        "/api/register", json={"username": "ann", "account_type": "agent", "description": ""}
    )
    assert r.status_code == 422
    r = board.client.post(
        "/api/register",
        json={"username": "ann", "account_type": "agent", "description": "x" * 1001},
    )
    assert r.status_code == 422
    r = board.client.post(
        "/api/register", json={"username": "ann", "account_type": "agent", "description": "Does X"}
    )
    assert r.status_code == 201 and r.json()["description"] == "Does X"
    r = board.client.post("/api/register", json={"username": "hum", "account_type": "human"})
    assert r.status_code == 201 and r.json()["description"] == ""


def test_users_list_and_patch_me(board, alice, bot):
    users = {u["username"]: u for u in alice.ok("GET", "/api/users")["users"]}
    assert users["botty"]["description"] == "test agent" and users["alice"]["description"] == ""
    me = alice.ok("PATCH", "/api/me", {"description": "I review things"})
    assert me["description"] == "I review things"
    assert alice.ok("GET", "/api/me")["description"] == "I review things"
    assert alice.ok("PATCH", "/api/me", {"description": ""})["description"] == ""
    assert alice.call("PATCH", "/api/me", json={"description": "x" * 1001}).status_code == 422
    assert alice.call("PATCH", "/api/me", json={"other": "x"}).status_code == 422
    blank = bot.call("PATCH", "/api/me", json={"description": ""})
    assert blank.status_code == 422 and blank.json()["error"]["code"] == "invalid_input"
    assert bot.ok("PATCH", "/api/me", {"description": "new"})["description"] == "new"
    assert board.client.patch("/api/me", json={"description": "x"}).status_code == 401


# ---------- slugs ----------


def test_area_slug_create_collision_patch_and_lookup(admin):
    a = admin.make_area("Deep Research!")
    assert a["slug"] == "deep-research"
    b = admin.make_area("deep  research?")
    assert b["slug"] == f"deep-research-{b['id']}"
    assert admin.ok("GET", "/api/areas/deep-research")["id"] == a["id"]
    assert admin.ok("GET", f"/api/areas/{a['id']}")["slug"] == "deep-research"
    assert admin.get("/api/areas/nope").status_code == 404
    assert admin.get("/api/areas/nope").json()["error"]["code"] == "area_not_found"
    assert admin.make_area("2024")["slug"] == "area-2024"
    assert admin.make_area("???")["slug"] == "area"

    renamed = admin.ok("PATCH", f"/api/areas/{a['id']}", {"name": "Fresh Name"})
    assert renamed["slug"] == "fresh-name"
    assert admin.get("/api/areas/deep-research").status_code == 404
    kept = admin.ok("PATCH", "/api/areas/fresh-name", {"description": "only desc"})
    assert kept["slug"] == "fresh-name"


def test_area_slug_in_thread_message_search_activity(admin, area):
    t = admin.make_thread(area["id"])
    assert t["thread"]["area_slug"] == area["slug"] == "ops"
    assert t["messages"][0]["area_slug"] == "ops"
    assert admin.ok("GET", "/api/search", params={"q": "Ops"})["areas"][0]["slug"] == "ops"
    assert admin.ok("GET", "/api/search", params={"q": "T"})["threads"][0]["area_slug"] == "ops"
    assert admin.ok("GET", "/api/search", params={"q": "op body"})["messages"][0]["area_slug"] == "ops"
    assert admin.ok("GET", "/api/activity")["events"][0]["area_slug"] == "ops"


# ---------- attachments ----------


def test_upload_and_download_image_inline(admin, alice):
    r = upload(alice)
    assert r.status_code == 201, r.text
    info = r.json()
    assert info["filename"] == "pic.png" and info["content_type"] == "image/png"
    assert info["size"] == len(PNG) and info["url"] == f"/api/attachments/{info['id']}"
    got = admin.get(info["url"])
    assert got.status_code == 200 and got.content == PNG
    assert got.headers["content-type"] == "image/png"
    assert got.headers["x-content-type-options"] == "nosniff"
    assert got.headers["content-disposition"].startswith("inline")
    assert admin.get("/api/attachments/999").status_code == 404
    assert admin.get("/api/attachments/999").json()["error"]["code"] == "attachment_not_found"


def test_download_requires_auth_and_non_images_are_attachments(board, alice):
    for filename, ctype in [("a.svg", "image/svg+xml"), ("a.html", "text/html"), ("a.bin", "application/pdf")]:
        info = upload(alice, b"<svg onload=1>", filename, ctype).json()
        got = alice.get(info["url"])
        assert got.headers["content-disposition"].startswith("attachment"), ctype
        assert got.headers["x-content-type-options"] == "nosniff"
        assert got.headers["content-type"].startswith(ctype)
    assert board.client.get(info["url"]).status_code == 401


def test_upload_limits_and_validation(board, alice):
    assert upload(alice, b"").status_code == 422
    big = upload(alice, b"x" * (10 * 1024 * 1024 + 1))
    assert big.status_code == 413 and big.json()["error"]["code"] == "too_large"
    assert upload(alice, b"x" * (10 * 1024 * 1024)).status_code == 201
    missing = alice.call("POST", "/api/attachments", content=b"x")
    assert missing.status_code == 422
    anon = board.client.post("/api/attachments", params={"filename": "a"}, content=b"x")
    assert anon.status_code == 401


def test_attachments_on_thread_and_message(admin, alice, area):
    a1, a2 = upload(alice).json(), upload(alice, b"hello", "n.txt", "text/plain").json()
    t = alice.ok(
        "POST",
        "/api/threads",
        {"area_id": area["id"], "title": "T", "body": "see", "attachment_ids": [a1["id"]]},
        201,
    )
    assert [a["id"] for a in t["messages"][0]["attachments"]] == [a1["id"]]
    assert t["messages"][0]["attachments"][0]["url"] == a1["url"]
    m = alice.ok(
        "POST",
        f"/api/threads/{t['thread']['id']}/messages",
        {"body": "more", "attachment_ids": [a2["id"]]},
        201,
    )
    assert m["attachments"] == [{**a2, "url": a2["url"]}]
    assert alice.ok("GET", f"/api/messages/{m['id']}")["attachments"][0]["filename"] == "n.txt"
    assert admin.say(t["thread"]["id"], "plain")["attachments"] == []


def test_invalid_attachment_ids(admin, alice, area):
    mine = upload(alice).json()
    thread = alice.make_thread(area["id"])["thread"]["id"]
    path = f"/api/threads/{thread}/messages"
    other = admin.call("POST", path, json={"body": "x", "attachment_ids": [mine["id"]]})
    assert other.status_code == 422 and other.json()["error"]["code"] == "invalid_attachment"
    assert alice.call("POST", path, json={"body": "x", "attachment_ids": [9999]}).status_code == 422
    assert alice.ok("POST", path, {"body": "x", "attachment_ids": [mine["id"]]}, 201)
    reuse = alice.call("POST", path, json={"body": "y", "attachment_ids": [mine["id"]]})
    assert reuse.status_code == 422 and reuse.json()["error"]["code"] == "invalid_attachment"
    ids = [upload(alice).json()["id"] for _ in range(11)]
    assert alice.call("POST", path, json={"body": "z", "attachment_ids": ids}).status_code == 422
    bad_thread = alice.call(
        "POST",
        "/api/threads",
        json={"area_id": area["id"], "title": "t", "body": "b", "attachment_ids": [9999]},
    )
    assert bad_thread.status_code == 422
    # failed create rolled back: no extra thread
    assert len(alice.ok("GET", "/api/threads")["threads"]) == 1


# ---------- editing ----------


def test_edit_message_rules(admin, alice, area):
    tid = alice.make_thread(area["id"])["thread"]["id"]
    msg = alice.say(tid, "first")
    assert msg["edited_at"] is None
    edited = alice.ok("PATCH", f"/api/messages/{msg['id']}", {"body": "second"})
    assert edited["body"] == "second" and edited["edited_at"]
    assert alice.ok("GET", f"/api/messages/{msg['id']}")["edited_at"] == edited["edited_at"]
    denied = admin.call("PATCH", f"/api/messages/{msg['id']}", json={"body": "hack"})
    assert denied.status_code == 403 and denied.json()["error"]["code"] == "not_author"
    assert alice.call("PATCH", f"/api/messages/{msg['id']}", json={"body": ""}).status_code == 422
    assert alice.call("PATCH", "/api/messages/999", json={"body": "x"}).status_code == 404
    assert alice.call("PATCH", f"/api/messages/{msg['id']}", json={"x": 1}).status_code == 422
    op_id = alice.ok("GET", f"/api/threads/{tid}")["thread"]["op_message_id"]
    assert alice.ok("PATCH", f"/api/messages/{op_id}", {"body": "new op"})["is_op"] is True
    kinds = [e["kind"] for e in alice.ok("GET", "/api/activity")["events"]]
    assert kinds.count("message_edited") == 2
    event = alice.ok("GET", "/api/activity")["events"][0]
    assert event["message_id"] == op_id and event["thread_id"] == tid

    alice.ok("POST", f"/api/threads/{tid}/close", {"reason": "completed"})
    closed = alice.call("PATCH", f"/api/messages/{msg['id']}", json={"body": "late"})
    assert closed.status_code == 409 and closed.json()["error"]["code"] == "thread_closed"


def test_edit_message_creates_no_attention(admin, alice, bot, area):
    tid = alice.make_thread(area["id"])["thread"]["id"]
    msg = alice.say(tid, "hello")
    assert bot.attention() == {}
    alice.ok("PATCH", f"/api/messages/{msg['id']}", {"body": "hello @botty"})
    assert bot.attention() == {}
    assert alice.attention() == {}


def test_edit_thread_rules(admin, alice, area):
    thread = alice.make_thread(area["id"], title="Old")["thread"]
    assert thread["edited_at"] is None
    edited = alice.ok("PATCH", f"/api/threads/{thread['id']}", {"title": "New"})
    assert edited["title"] == "New" and edited["edited_at"]
    assert alice.ok("GET", f"/api/threads/{thread['id']}")["thread"]["edited_at"]
    denied = admin.call("PATCH", f"/api/threads/{thread['id']}", json={"title": "x"})
    assert denied.status_code == 403 and denied.json()["error"]["code"] == "not_owner"
    assert alice.call("PATCH", f"/api/threads/{thread['id']}", json={"title": ""}).status_code == 422
    assert alice.call("PATCH", "/api/threads/999", json={"title": "x"}).status_code == 404
    assert alice.ok("GET", "/api/activity")["events"][0]["kind"] == "thread_edited"
    alice.ok("POST", f"/api/threads/{thread['id']}/close", {"reason": "archived"})
    closed = alice.call("PATCH", f"/api/threads/{thread['id']}", json={"title": "late"})
    assert closed.status_code == 409 and closed.json()["error"]["code"] == "thread_closed"


# ---------- migration ----------

OLD_SCHEMA = """
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    username_key TEXT NOT NULL UNIQUE,
    account_type TEXT NOT NULL CHECK (account_type IN ('human', 'agent')),
    status TEXT NOT NULL CHECK (status IN ('pending', 'approved')),
    is_superadmin INTEGER NOT NULL DEFAULT 0,
    token_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);
CREATE TABLE areas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    name_key TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    created_by INTEGER NOT NULL REFERENCES users (id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE threads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    area_id INTEGER NOT NULL REFERENCES areas (id),
    title TEXT NOT NULL,
    owner_id INTEGER NOT NULL REFERENCES users (id),
    created_at TEXT NOT NULL,
    last_activity_at TEXT NOT NULL,
    pinned INTEGER NOT NULL DEFAULT 0,
    closed_reason TEXT CHECK (closed_reason IN ('completed', 'archived')),
    closed_at TEXT,
    closed_by INTEGER REFERENCES users (id)
);
CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id INTEGER NOT NULL REFERENCES threads (id),
    parent_id INTEGER REFERENCES messages (id),
    author_id INTEGER NOT NULL REFERENCES users (id),
    body TEXT NOT NULL,
    created_at TEXT NOT NULL,
    is_op INTEGER NOT NULL DEFAULT 0,
    score INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE reactions (
    message_id INTEGER NOT NULL REFERENCES messages (id),
    user_id INTEGER NOT NULL REFERENCES users (id),
    emoji TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (message_id, user_id, emoji)
);
CREATE TABLE votes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER NOT NULL REFERENCES messages (id),
    user_id INTEGER NOT NULL REFERENCES users (id),
    delta INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE attention (
    message_id INTEGER NOT NULL REFERENCES messages (id),
    user_id INTEGER NOT NULL REFERENCES users (id),
    reason TEXT NOT NULL CHECK (reason IN ('mention', 'reply', 'agent_message')),
    status TEXT NOT NULL CHECK (status IN ('unacknowledged', 'processing', 'processed', 'acknowledged')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (message_id, user_id)
);
CREATE TABLE events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    actor_id INTEGER NOT NULL REFERENCES users (id),
    area_id INTEGER REFERENCES areas (id),
    thread_id INTEGER REFERENCES threads (id),
    message_id INTEGER REFERENCES messages (id),
    detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
"""


def test_old_database_is_migrated(tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript(OLD_SCHEMA)
    ts = "2024-01-01T00:00:00+00:00"
    from threadit.core import hash_token

    conn.execute(
        "INSERT INTO users (username, username_key, account_type, status, is_superadmin,"
        " token_hash, created_at) VALUES ('old', 'old', 'agent', 'approved', 1, ?, ?)",
        (hash_token("tok"), ts),
    )
    for name in ("Big Ideas", "big ideas!", "Other"):
        conn.execute(
            "INSERT INTO areas (name, name_key, created_by, created_at, updated_at)"
            " VALUES (?, ?, 1, ?, ?)",
            (name, name.lower(), ts, ts),
        )
    conn.execute(
        "INSERT INTO threads (area_id, title, owner_id, created_at, last_activity_at)"
        " VALUES (1, 'T', 1, ?, ?)",
        (ts, ts),
    )
    conn.execute(
        "INSERT INTO messages (thread_id, author_id, body, created_at, is_op)"
        " VALUES (1, 1, 'hello', ?, 1)",
        (ts,),
    )
    conn.commit()
    conn.close()

    client = TestClient(create_app(path, static_dir=tmp_path / "nostatic"))
    headers = {"Authorization": "Bearer tok"}
    me = client.get("/api/me", headers=headers).json()
    assert me["username"] == "old" and me["description"] == ""
    areas = client.get("/api/areas", headers=headers).json()["areas"]
    assert {a["name"]: a["slug"] for a in areas} == {
        "Big Ideas": "big-ideas",
        "big ideas!": "big-ideas-2",
        "Other": "other",
    }
    assert client.get("/api/areas/big-ideas", headers=headers).json()["id"] == 1
    detail = client.get("/api/threads/1", headers=headers).json()
    assert detail["thread"]["edited_at"] is None and detail["thread"]["area_slug"] == "big-ideas"
    message = detail["messages"][0]
    assert message["edited_at"] is None and message["attachments"] == []
    assert client.patch(
        "/api/messages/1", json={"body": "edited"}, headers=headers
    ).json()["edited_at"]
    assert client.patch("/api/me", json={"description": "now set"}, headers=headers).status_code == 200
    created = client.post("/api/areas", json={"name": "big ideas"}, headers=headers)
    assert created.status_code == 409
    new = client.post("/api/areas", json={"name": "Big-Ideas?"}, headers=headers).json()
    assert new["slug"] == f"big-ideas-{new['id']}"
    client.close()
    # reopening an already-migrated db is a no-op
    client = TestClient(create_app(path, static_dir=tmp_path / "nostatic"))
    assert client.get("/api/areas/other", headers=headers).status_code == 200
    client.close()


def test_non_ascii_digit_area_ref_is_404(admin):
    for ref in ("%C2%B2", "%D9%A1"):
        for resp in (admin.get(f"/api/areas/{ref}"), admin.call("PATCH", f"/api/areas/{ref}", json={"name": "x"})):
            assert resp.status_code == 404
            assert resp.json()["error"]["code"] == "area_not_found"


def test_favicon_served_and_linked(tmp_path):
    client = TestClient(create_app(tmp_path / "fav.db"))
    resp = client.get("/favicon.svg")
    assert resp.status_code == 200 and resp.headers["content-type"].startswith("image/svg+xml")
    assert 'rel="icon"' in client.get("/").text and "/favicon.svg" in client.get("/").text
    client.close()
