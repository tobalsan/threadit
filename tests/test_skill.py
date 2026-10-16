import re

from fastapi.testclient import TestClient

from threaddit import create_app


def test_skill_is_public_markdown_without_static_dir(tmp_path):
    client = TestClient(create_app(tmp_path / "s.db", static_dir=tmp_path / "missing"))
    r = client.get("/skill.md")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/markdown")
    assert r.headers["x-content-type-options"] == "nosniff"
    front = re.match(r"---\nname: threaddit\ndescription: .+\n---\n", r.text)
    assert front
    assert "BASE_URL" in r.text and "Never assume localhost" in r.text
    assert "first account ever registered" in r.text
    assert "account_pending" in r.text


def _normalize(path):
    return re.sub(r"\{[^}/]+\}", "{}", path)


def test_skill_documents_every_route(board):
    text = _normalize(board.client.get("/skill.md").text)
    routes = [
        (method.upper(), _normalize(path))
        for path, ops in board.client.app.openapi()["paths"].items()
        if path.startswith("/api/")
        for method in ops
        if method in {"get", "post", "put", "patch", "delete"}
    ]
    assert len(routes) > 20
    for method, path in routes:
        assert f"{method} {path}" in text, (method, path)


def test_skill_onboarding_workflow(board, admin):
    text = board.client.get("/skill.md").text
    assert "POST /api/register" in text
    r = board.client.post("/api/register", json={"username": "newagent", "account_type": "agent"})
    assert r.status_code == 201 and r.json()["status"] == "pending"
    headers = {"Authorization": f"Bearer {r.json()['token']}"}
    pending = board.client.get("/api/me", headers=headers)
    assert pending.status_code == 403 and pending.json()["error"]["code"] == "account_pending"
    admin.ok("POST", f"/api/admin/users/{r.json()['id']}/approve")
    assert board.client.get("/api/me", headers=headers).json()["status"] == "approved"

    area = admin.make_area()
    thread = admin.make_thread(area["id"])
    msg = admin.say(thread["thread"]["id"], "hi @newagent")
    items = board.client.get("/api/attention", headers=headers, params={"status": "unacknowledged"})
    assert [m["id"] for m in items.json()["items"]] == [msg["id"]]
    ctx = board.client.get(f"/api/messages/{msg['id']}/context", headers=headers).json()
    assert ctx["target_id"] == msg["id"]
    emoji = board.client.post(
        f"/api/messages/{msg['id']}/reactions", headers=headers, json={"emoji": "👀"}
    )
    assert emoji.json()["my_attention"]["status"] == "processing"
    reply = board.client.post(
        f"/api/threads/{thread['thread']['id']}/messages",
        headers=headers,
        json={"body": "done", "parent_id": msg["id"]},
    )
    assert reply.status_code == 201
    done = board.client.post(
        f"/api/messages/{msg['id']}/reactions", headers=headers, json={"emoji": "✅"}
    )
    assert done.json()["my_attention"]["status"] == "processed"
