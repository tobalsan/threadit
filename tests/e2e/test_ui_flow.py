import re

from playwright.sync_api import Page, expect


def register(page: Page, base: str, name: str, kind: str) -> str:
    """Register through the UI; returns the token (never printed)."""
    page.goto(base + "/")
    page.fill("#reg-name", name)
    page.select_option("#reg-type", kind)
    page.fill("#reg-desc", f"{name} description")
    page.get_by_role("button", name="Register").click()
    token = page.locator(".tokenbox").inner_text()
    assert token
    return token


def login(page: Page, base: str, token: str) -> None:
    page.goto(base + "/")
    page.fill("#login-token", token)
    page.get_by_role("button", name="Log in").click()


def new_page(browser):
    ctx = browser.new_context()
    return ctx, ctx.new_page()


def test_full_flow(server, browser):
    actx, alice = new_page(browser)
    bctx, bob = new_page(browser)
    try:
        # first registration -> approved superadmin
        alice_token = register(alice, server, "alice", "human")
        expect(alice.get_by_text("approved superadmin")).to_be_visible()
        alice.get_by_role("button", name="I saved my token, continue").click()
        expect(alice.get_by_role("heading", name="Areas")).to_be_visible()
        expect(alice.locator("#whoami .badge.super")).to_be_visible()

        # second account pending, no app access
        bob_token = register(bob, server, "bob", "agent")
        expect(bob.get_by_text("Account is pending")).to_be_visible()
        bob.get_by_role("button", name="I saved my token, continue").click()
        expect(bob.get_by_role("heading", name="Waiting for approval")).to_be_visible()
        assert bob.evaluate(
            "t => fetch('/api/areas', {headers:{Authorization:'Bearer '+t}}).then(r => r.status)",
            bob_token,
        ) in (401, 403)

        # approval
        alice.get_by_role("link", name="Admin").click()
        alice.get_by_role("button", name="Approve bob").click()
        expect(alice.get_by_text("No pending accounts.")).to_be_visible()
        bob.get_by_role("button", name="Check again").click()
        expect(bob.get_by_role("heading", name="Areas")).to_be_visible()
        expect(bob.locator("#whoami .badge.agent")).to_be_visible()

        # area + thread (alice)
        alice.get_by_role("link", name="Areas").click()
        alice.get_by_role("button", name="New area").click()
        alice.fill("#area-name", "Research")
        alice.fill("#area-desc", "Findings land here <b>x</b>")
        alice.get_by_role("button", name="Save").click()
        alice.get_by_role("link", name="Research").click()
        alice.get_by_role("button", name="New thread").click()
        alice.fill("#th-title", "Pricing study")
        alice.fill("#th-body", "Please look into pricing @bob <img src=x onerror=window.pwned=1>")
        alice.get_by_role("button", name="Create thread").click()
        expect(alice.get_by_role("heading", name="Pricing study")).to_be_visible()
        assert alice.evaluate("window.pwned") is None
        expect(alice.locator(".msgbody .body").first).to_contain_text("<img src=x")

        # vote on OP -> importance
        alice.get_by_role("button", name="Vote +10").first.click()
        expect(alice.get_by_text("importance (OP score): 10")).to_be_visible()

        # bob sees attention, reacts processing, replies nested
        bob.get_by_role("link", name="Attention").click()
        expect(bob.get_by_text("attention: unacknowledged")).to_be_visible()
        bob.get_by_role("button", name="React 👀").click()
        expect(bob.get_by_text("attention: processing")).to_be_visible()
        bob.get_by_role("link", name="Pricing study").click()
        bob.get_by_role("button", name="Reply", exact=True).first.click()
        bob.get_by_label("Reply to alice").fill("Found three vendors")
        bob.get_by_role("button", name="Post reply").click()
        expect(bob.get_by_text("Found three vendors")).to_be_visible()
        bob.get_by_role("button", name="React ✅").first.click()

        # alice: agent message needs her attention; nested reply by alice acks
        alice.get_by_role("link", name="Attention").click()
        expect(alice.get_by_text("Found three vendors")).to_be_visible()
        alice.get_by_role("link", name="context").first.click()
        expect(alice.get_by_text("Showing only the path to this message")).to_be_visible()
        alice.get_by_role("button", name="Reply", exact=True).last.click()
        alice.get_by_label("Reply to bob").fill("Thanks, details please")
        alice.get_by_role("button", name="Post reply").click()
        alice.get_by_role("link", name="Attention").click()
        expect(alice.get_by_text("Nothing here.")).to_be_visible()

        # bob is notified of the direct reply
        bob.get_by_role("link", name="Attention").click()
        expect(bob.get_by_text("Thanks, details please")).to_be_visible()

        # search
        alice.fill("#searchbox", "vendors")
        alice.press("#searchbox", "Enter")
        expect(alice.get_by_role("heading", name="Messages")).to_be_visible()
        alice.get_by_role("link", name="Show context").first.click()
        expect(alice.get_by_text("Found three vendors")).to_be_visible()

        # close completed
        alice.get_by_role("link", name="Open full thread at this message").click()
        alice.get_by_text("Close thread").click()
        alice.get_by_role("button", name="Close as completed").click()
        expect(alice.get_by_text("Read-only: reopen")).to_be_visible()
        expect(alice.get_by_role("button", name="Post")).to_be_disabled()

        # closed hidden from active list and search, visible when requested
        alice.get_by_role("link", name="Research").click()
        expect(alice.get_by_text("No threads here.")).to_be_visible()
        alice.select_option("#statesel", "closed")
        expect(alice.get_by_role("link", name="Pricing study")).to_be_visible()
        alice.fill("#searchbox", "vendors")
        alice.press("#searchbox", "Enter")
        expect(alice.get_by_text("No results.")).to_be_visible()
        alice.get_by_label("include closed threads").check()
        expect(alice.get_by_text("Found three vendors").first).to_be_visible()

        # server rejects writes on closed thread with reopen guidance
        status, text = alice.evaluate(
            """async t => { const r = await fetch('/api/threads/1/messages', {method:'POST',
              headers:{Authorization:'Bearer '+t,'Content-Type':'application/json'},
              body: JSON.stringify({body:'x'})}); return [r.status, await r.text()]; }""",
            alice_token,
        )
        assert status in (409, 423) and "reopen" in text.lower()

        # reopen
        alice.goto(server + "/#/thread/1")
        alice.get_by_role("button", name="Reopen thread").click()
        expect(alice.get_by_role("button", name="Close thread")).to_have_count(0)
        expect(alice.get_by_text("Close thread")).to_be_visible()

        # activity
        alice.get_by_role("link", name="Activity").click()
        expect(alice.get_by_text("reopened thread")).to_be_visible()

        # login by token after logout
        alice.get_by_role("button", name="Log out").click()
        login(alice, server, alice_token)
        expect(alice.get_by_role("heading", name="Areas")).to_be_visible()
    finally:
        actx.close()
        bctx.close()


def test_failure_timeout_and_navigation_recovery(server, browser):
    ctx, page = new_page(browser)
    try:
        register(page, server, "carol", "human")
        page.get_by_role("button", name="I saved my token, continue").click()
        expect(page.get_by_role("heading", name="Areas")).to_be_visible()

        # network failure -> error + retry works
        page.route("**/api/activity*", lambda route: route.abort())
        page.get_by_role("link", name="Activity").click()
        expect(page.get_by_role("alert")).to_contain_text("Network error")
        page.unroute("**/api/activity*")
        page.get_by_role("button", name="Retry").click()
        expect(page.get_by_text("No activity yet.").or_(page.get_by_text("created area"))).to_be_visible()

        # server error body shown
        page.route(
            "**/api/attention*",
            lambda route: route.fulfill(
                status=500,
                content_type="application/json",
                body='{"error":{"code":"boom","message":"Server exploded"}}',
            ),
        )
        page.get_by_role("link", name="Attention").click()
        expect(page.get_by_role("alert")).to_contain_text("Server exploded")
        page.unroute("**/api/attention*")
        page.get_by_role("button", name="Retry").click()
        expect(page.get_by_text("Nothing here.")).to_be_visible()

        # hung request: navigation stays usable, then timeout error + retry
        hung = []
        page.route("**/api/activity*", lambda route: hung.append(route))
        page.get_by_role("link", name="Activity").click()
        expect(page.get_by_text("Loading…")).to_be_visible()
        page.get_by_role("link", name="Areas").click()
        expect(page.get_by_role("heading", name="Areas")).to_be_visible()
        page.get_by_role("button", name="New area").click()
        expect(page.locator("#area-name")).to_be_visible()
        page.get_by_role("link", name="Activity").click()
        expect(page.get_by_role("alert")).to_contain_text("timed out", timeout=25000)
        for r in hung:
            try:
                r.abort()
            except Exception:
                pass
        page.unroute("**/api/activity*")
        page.get_by_role("button", name="Retry").click()
        expect(page.get_by_role("heading", name="Activity")).to_be_visible()
    finally:
        ctx.close()
