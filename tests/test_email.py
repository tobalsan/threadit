def test_set_read_and_clear_email(board, alice):
    me = alice.ok("PATCH", "/api/me", {"email": "  Alice@Example.COM "})
    assert me["email"] == "alice@example.com"
    assert alice.ok("GET", "/api/me")["email"] == "alice@example.com"
    users = {u["username"]: u for u in board.admin.ok("GET", "/api/users")["users"]}
    assert users["alice"]["email"] == "alice@example.com" and users["root"]["email"] == ""
    assert alice.ok("PATCH", "/api/me", {"email": ""})["email"] == ""


def test_invalid_email_is_422(alice):
    for bad in ("nope", "a@b@c", "a b@c.d", "@x", "x@", "a" * 250 + "@x.io"):
        r = alice.call("PATCH", "/api/me", json={"email": bad})
        assert r.status_code == 422, bad
        assert r.json()["error"]["code"] == "invalid_input"


def test_duplicate_email_is_409(alice, bob):
    alice.ok("PATCH", "/api/me", {"email": "alice@example.com"})
    r = bob.call("PATCH", "/api/me", json={"email": "ALICE@example.com"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "email_taken"
    # setting your own email again is fine; empty emails never collide
    alice.ok("PATCH", "/api/me", {"email": "alice@example.com"})
    alice.ok("PATCH", "/api/me", {"email": ""})
    bob.ok("PATCH", "/api/me", {"email": ""})


def test_description_only_patch_keeps_email(alice):
    alice.ok("PATCH", "/api/me", {"email": "alice@example.com"})
    me = alice.ok("PATCH", "/api/me", {"description": "hi"})
    assert me["description"] == "hi" and me["email"] == "alice@example.com"


def test_agent_email_patch_keeps_description(bot):
    before = bot.ok("GET", "/api/me")["description"]
    assert before
    me = bot.ok("PATCH", "/api/me", {"email": "bot@example.com"})
    assert me["description"] == before and me["email"] == "bot@example.com"
    assert bot.call("PATCH", "/api/me", json={"description": ""}).status_code == 422
