import sqlite3
import threading

import pytest
from fastapi.testclient import TestClient

from threaddit import create_app


def test_first_registration_is_superadmin_and_returns_token(tmp_path):
    client = TestClient(create_app(tmp_path / "a.db"))
    r = client.post("/api/register", json={"username": "Root", "account_type": "human"})
    assert r.status_code == 201
    body = r.json()
    assert {"id", "username", "token"} <= set(body)
    assert body["status"] == "approved" and body["is_superadmin"] is True
    me = client.get("/api/me", headers={"Authorization": f"Bearer {body['token']}"})
    assert me.status_code == 200 and me.json()["is_superadmin"] is True


def test_later_accounts_pending_and_token_gives_no_access(board):
    r = board.client.post(
        "/api/register", json={"username": "newbie", "account_type": "agent"}
    )
    assert r.json()["status"] == "pending" and r.json()["is_superadmin"] is False
    headers = {"Authorization": f"Bearer {r.json()['token']}"}
    for method, path in [
        ("GET", "/api/me"),
        ("GET", "/api/areas"),
        ("GET", "/api/threads"),
        ("GET", "/api/attention"),
        ("GET", "/api/activity"),
        ("GET", "/api/search?q=x"),
    ]:
        resp = board.client.request(method, path, headers=headers)
        assert resp.status_code == 403, path
        assert resp.json()["error"]["code"] == "account_pending"
    write = board.client.post("/api/areas", json={"name": "Sneaky"}, headers=headers)
    assert write.status_code == 403
    assert board.admin.ok("GET", "/api/areas")["areas"] == []
    login = board.client.post("/api/login", json={"token": r.json()["token"]})
    assert login.status_code == 403


def test_approval_grants_access_and_is_superadmin_only(board, alice):
    new = board.client.post(
        "/api/register", json={"username": "later", "account_type": "human"}
    ).json()
    r = alice.call("POST", f"/api/admin/users/{new['id']}/approve")
    assert r.status_code == 403
    assert alice.call("GET", "/api/admin/users").status_code == 403
    pending = board.admin.ok("GET", "/api/admin/users", params={"status": "pending"})
    assert [u["username"] for u in pending["users"]] == ["later"]
    board.admin.ok("POST", f"/api/admin/users/{new['id']}/approve")
    login = board.client.post("/api/login", json={"token": new["token"]})
    assert login.status_code == 200 and login.json()["username"] == "later"
    assert board.admin.call("POST", "/api/admin/users/9999/approve").status_code == 404


def test_missing_and_bad_tokens(board):
    assert board.client.get("/api/me").status_code == 401
    bad = board.client.get("/api/me", headers={"Authorization": "Bearer nope"})
    assert bad.status_code == 401 and bad.json()["error"]["code"] == "invalid_token"
    assert (
        board.client.get("/api/me", headers={"Authorization": "Basic abc"}).status_code
        == 401
    )
    assert board.client.post("/api/login", json={"token": "nope"}).status_code == 401


def test_usernames_unique_case_insensitive_and_validated(board):
    dup = board.client.post(
        "/api/register", json={"username": "ROOT", "account_type": "human"}
    )
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "username_taken"
    for bad in ["ab", "has space", "x" * 33, "bad!", "@at", ""]:
        r = board.client.post(
            "/api/register", json={"username": bad, "account_type": "human"}
        )
        assert r.status_code == 422, bad
    for payload in [
        {"username": "okname"},
        {"username": "okname", "account_type": "robot"},
        {"username": "okname", "account_type": "human", "extra": 1},
    ]:
        assert board.client.post("/api/register", json=payload).status_code == 422


def test_tokens_stored_hashed_only(board):
    reg = board.client.post(
        "/api/register", json={"username": "hashme", "account_type": "human"}
    ).json()
    raw = sqlite3.connect(board.path).execute("SELECT token_hash FROM users").fetchall()
    stored = {row[0] for row in raw}
    assert reg["token"] not in stored and all(len(h) == 64 for h in stored)
    assert reg["token"] not in board.path.read_bytes().decode("latin-1")
    users = board.admin.ok("GET", "/api/admin/users")["users"]
    assert all("token" not in u and "token_hash" not in u for u in users)


def test_bootstrap_is_atomic_under_concurrency(tmp_path):
    client = TestClient(create_app(tmp_path / "race.db"))
    results = []

    def go(i):
        r = client.post(
            "/api/register", json={"username": f"racer{i}", "account_type": "human"}
        )
        results.append(r.json())

    threads = [threading.Thread(target=go, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(results) == 8
    assert sum(1 for r in results if r["is_superadmin"]) == 1
    assert sum(1 for r in results if r["status"] == "approved") == 1


def test_users_list_only_approved(board, alice):
    board.client.post("/api/register", json={"username": "pend", "account_type": "agent"})
    names = [u["username"] for u in alice.ok("GET", "/api/users")["users"]]
    assert names == ["alice", "root"]


def test_security_headers_and_error_shape(board):
    r = board.client.get("/api/nope")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "default-src 'self'" in r.headers["content-security-policy"]


def test_fresh_db_init_is_idempotent(tmp_path):
    create_app(tmp_path / "x.db")
    create_app(tmp_path / "x.db")


@pytest.mark.parametrize("path", ["/api/threads/abc", "/api/messages/abc/context"])
def test_bad_path_ids_422(board, path):
    assert board.admin.get(path).status_code == 422
