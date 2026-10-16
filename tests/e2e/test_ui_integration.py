import json
import urllib.request

from playwright.sync_api import Page, expect


def call(base, method, path, token=None, body=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=20) as resp:
        text = resp.read()
    return json.loads(text) if text else None


def seed_users(base):
    """Returns (human token, agent token, human id). First user is approved superadmin."""
    human = call(base, "POST", "/api/register", body={"username": "hanna", "account_type": "human"})
    agent = call(base, "POST", "/api/register", body={"username": "agentx", "account_type": "agent"})
    call(base, "POST", f"/api/admin/users/{agent['id']}/approve", human["token"])
    return human["token"], agent["token"]


def login(page: Page, base: str, token: str) -> None:
    page.goto(base + "/")
    page.fill("#login-token", token)
    page.get_by_role("button", name="Log in").click()
    expect(page.get_by_role("heading", name="Areas")).to_be_visible()


def make_thread(base, token, area_id, title, body="op"):
    return call(base, "POST", "/api/threads", token, {"area_id": area_id, "title": title, "body": body})["thread"]


def test_area_pagination_pin_and_default_sort(server, browser):
    human, _ = seed_users(server)
    area = call(server, "POST", "/api/areas", human, {"name": "Big", "description": "d"})
    pinned = make_thread(server, human, area["id"], "pinned-one")
    call(server, "PUT", f"/api/threads/{pinned['id']}/pin", human, {"pinned": True})
    for i in range(102):
        make_thread(server, human, area["id"], f"bulk {i}")
    ctx = browser.new_context()
    page = ctx.new_page()
    try:
        login(page, server, human)
        page.goto(f"{server}/#/area/{area['id']}")
        expect(page.locator("#sortsel")).to_have_value("importance")
        rows = page.locator(".card.thread")
        expect(rows).to_have_count(101)  # 1 pinned + first page of 100
        page.get_by_role("button", name="Load more threads").click()
        expect(rows).to_have_count(103)
        expect(page.get_by_role("button", name="Load more threads")).to_have_count(0)
        expect(page.get_by_role("link", name="pinned-one")).to_have_count(1)
        page.locator("#sortsel").select_option("created")
        expect(page).to_have_url(f"{server}/#/area/{area['id']}?state=active&sort=created")
        expect(page.locator("#sortsel")).to_have_value("created")
    finally:
        ctx.close()


def test_attention_pagination_and_closed_attention_is_read_only(server, browser):
    human, agent = seed_users(server)
    area = call(server, "POST", "/api/areas", human, {"name": "Ops", "description": "d"})
    thread = make_thread(server, human, area["id"], "Busy")
    for i in range(101):
        call(server, "POST", f"/api/threads/{thread['id']}/messages", agent, {"body": f"note {i}"})
    ctx = browser.new_context()
    page = ctx.new_page()
    try:
        login(page, server, human)
        page.goto(f"{server}/#/attention")
        cards = page.locator("main .card")
        expect(cards).to_have_count(100)
        page.get_by_role("button", name="Load more").click()
        expect(cards).to_have_count(101)

        # archive close from the thread page, then attention only with explicit opt-in
        page.goto(f"{server}/#/thread/{thread['id']}")
        page.locator("summary", has_text="Close thread").click()
        page.get_by_role("button", name="Close as archived").click()
        expect(page.get_by_text("Read-only: reopen")).to_be_visible()
        page.goto(f"{server}/#/attention")
        expect(page.get_by_text("Nothing here.")).to_be_visible()
        page.goto(f"{server}/#/attention?include_closed=true")
        first = page.locator("main .card").first
        expect(first.locator(".badge.closed", has_text="closed: archived")).to_be_visible()
        expect(first.get_by_role("button", name="Vote +1", exact=True)).to_be_disabled()
        expect(first.get_by_role("button", name="Reply")).to_be_disabled()
        expect(first.get_by_role("button", name="React 👍")).to_be_disabled()
        first.get_by_role("link", name="Reopen thread").click()
        expect(page.get_by_role("button", name="Reopen thread")).to_be_visible()
    finally:
        ctx.close()


def test_search_pagination_same_query_retry_and_context_target(server, browser):
    human, _ = seed_users(server)
    area = call(server, "POST", "/api/areas", human, {"name": "Lab", "description": "d"})
    thread = make_thread(server, human, area["id"], "Host", "first")
    for i in range(55):
        call(server, "POST", f"/api/threads/{thread['id']}/messages", human, {"body": f"needle msg {i}"})
    ctx = browser.new_context()
    page = ctx.new_page()
    try:
        login(page, server, human)
        page.route("**/api/search*", lambda route: route.abort())
        page.fill("#searchbox", "needle")
        page.press("#searchbox", "Enter")
        expect(page.get_by_role("alert")).to_contain_text("Network error")
        page.unroute("**/api/search*")
        page.fill("#searchbox", "needle")
        page.press("#searchbox", "Enter")  # same hash: must reroute, not stay stuck
        results = page.locator("a", has_text="Show context")
        expect(results).to_have_count(50)
        page.get_by_role("button", name="Load more messages").click()
        expect(results).to_have_count(55)

        results.first.click()
        expect(page.get_by_role("link", name="Open full thread at this message")).to_be_visible()
        page.get_by_role("link", name="Open full thread at this message").click()
        expect(page.locator(".msg.target")).to_be_visible()
        expect(page.locator(".msg.target").locator(".body").first).to_contain_text("needle msg 54")
    finally:
        ctx.close()


def test_owner_pin_section_and_failed_actions_keep_ui_usable(server, browser):
    human, _ = seed_users(server)
    area = call(server, "POST", "/api/areas", human, {"name": "Pins", "description": "d"})
    thread = make_thread(server, human, area["id"], "Pin me")
    ctx = browser.new_context()
    page = ctx.new_page()
    try:
        login(page, server, human)
        page.goto(f"{server}/#/thread/{thread['id']}")
        page.get_by_role("button", name="Pin to top").click()
        expect(page.get_by_role("button", name="Unpin")).to_be_visible()
        page.goto(f"{server}/#/area/{area['id']}")
        expect(page.get_by_role("heading", name="Pinned")).to_be_visible()

        page.goto(f"{server}/#/thread/{thread['id']}")
        page.route("**/api/messages/*/votes", lambda route: route.abort())
        vote = page.get_by_role("button", name="Vote +1", exact=True).first
        vote.click()
        expect(page.locator("#toast .bad")).to_contain_text("Network error")
        expect(vote).to_be_enabled()
        page.unroute("**/api/messages/*/votes")
        vote.click()
        expect(page.get_by_label("score 1").first).to_be_visible()

        page.route("**/api/threads/*/messages", lambda route: route.abort() if route.request.method == "POST" else route.continue_())
        page.fill("#top-reply", "will fail")
        page.get_by_role("button", name="Post", exact=True).click()
        expect(page.get_by_role("alert")).to_contain_text("Network error")
        expect(page.locator("#top-reply")).to_have_value("will fail")
        expect(page.get_by_role("button", name="Post", exact=True)).to_be_enabled()
        page.get_by_role("link", name="Activity").click()
        expect(page.get_by_role("heading", name="Activity")).to_be_visible()
        page.unroute("**/api/threads/*/messages")
    finally:
        ctx.close()


def test_responsive_390px_smoke(server, browser):
    human, _ = seed_users(server)
    area = call(server, "POST", "/api/areas", human, {"name": "Narrow", "description": "d"})
    thread = make_thread(server, human, area["id"], "Narrow thread")
    ctx = browser.new_context(viewport={"width": 390, "height": 800})
    page = ctx.new_page()
    try:
        login(page, server, human)
        for route in ("#/", f"#/area/{area['id']}", f"#/thread/{thread['id']}", "#/attention", "#/activity"):
            page.goto(f"{server}/{route}")
            expect(page.locator("main h1").first).to_be_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"), route
    finally:
        ctx.close()
