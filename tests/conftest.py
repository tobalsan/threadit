import pytest
from fastapi.testclient import TestClient

from threaddit import create_app


class Actor:
    def __init__(self, client, info):
        self.client = client
        self.id = info["id"]
        self.username = info["username"]
        self._token = info["token"]
        self.headers = {"Authorization": f"Bearer {self._token}"}

    def call(self, method, path, **kwargs):
        return self.client.request(method, path, headers=self.headers, **kwargs)

    def get(self, path, **kw):
        return self.call("GET", path, **kw)

    def post(self, path, json=None, **kw):
        return self.call("POST", path, json=json, **kw)

    def ok(self, method, path, json=None, status=200, **kw):
        r = self.call(method, path, json=json, **kw)
        assert r.status_code == status, r.text
        return r.json()

    def make_area(self, name="Ops", description="area desc"):
        return self.ok("POST", "/api/areas", {"name": name, "description": description}, 201)

    def make_thread(self, area_id, title="T", body="op body"):
        return self.ok(
            "POST", "/api/threads", {"area_id": area_id, "title": title, "body": body}, 201
        )

    def say(self, thread_id, body, parent_id=None):
        return self.ok(
            "POST",
            f"/api/threads/{thread_id}/messages",
            {"body": body, "parent_id": parent_id},
            201,
        )

    def react(self, message_id, emoji):
        return self.ok("POST", f"/api/messages/{message_id}/reactions", {"emoji": emoji})

    def attention(self, status="all", **params):
        data = self.ok("GET", "/api/attention", params={"status": status, **params})
        return {m["id"]: m["my_attention"] for m in data["items"]}


class Board:
    def __init__(self, path):
        self.path = path
        self.client = TestClient(create_app(path, static_dir=path.parent / "nostatic"))

    def restart(self):
        self.client.close()
        self.client = TestClient(create_app(self.path, static_dir=self.path.parent / "nostatic"))

    def register(self, username, account_type="human", approve=True, description=None):
        if description is None:
            description = "test agent" if account_type == "agent" else ""
        r = self.client.post(
            "/api/register",
            json={"username": username, "account_type": account_type, "description": description},
        )
        assert r.status_code == 201, r.text
        actor = Actor(self.client, r.json())
        if approve and r.json()["status"] != "approved":
            self.admin.ok("POST", f"/api/admin/users/{actor.id}/approve")
        return actor

    def actor_for(self, actor):
        """Rebind an actor to the current (restarted) client."""
        actor.client = self.client
        return actor


@pytest.fixture
def board(tmp_path):
    b = Board(tmp_path / "db" / "board.db")
    b.admin = b.register("root")
    yield b
    b.client.close()


@pytest.fixture
def admin(board):
    return board.admin


@pytest.fixture
def alice(board):
    return board.register("alice")


@pytest.fixture
def bob(board):
    return board.register("bob")


@pytest.fixture
def bot(board):
    return board.register("botty", "agent")


@pytest.fixture
def bot2(board):
    return board.register("robo", "agent")


@pytest.fixture
def area(admin):
    return admin.make_area()
