"""Optional thread lookups must leave the real board usable."""

import re
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import expect
from test_ui_features import open_page
from test_ui_integration import call, make_thread, seed_users


@pytest.mark.parametrize("outcome", ["pending", "failure", "timeout"])
def test_thread_suggestion_network_problems_do_not_block_posting(server, browser, outcome):
    human, _ = seed_users(server)
    area = call(server, "POST", "/api/areas", human, {"name": "Resilience"})
    thread = make_thread(server, human, area["id"], "Runner")
    ctx, page = open_page(browser, server, human)
    pending = []
    try:
        page.goto(f"{server}/#/thread/{thread['id']}")
        page.get_by_role("button", name="Reply to thread").click()
        box = page.get_by_role("textbox", name="Add top-level reply", exact=False)
        if outcome == "timeout":
            page.clock.install()

        def interrupt(route):
            if outcome != "failure":
                pending.append(route)
            else:
                route.abort()

        page.route("**/api/search?**", interrupt)
        with page.expect_request("**/api/search?**"):
            box.fill("#runner")
        if outcome == "timeout":
            with page.expect_event("requestfailed", predicate=lambda r: "/api/search?" in r.url):
                page.clock.fast_forward(16000)
            expect(page.get_by_role("listbox", name="Thread suggestions")).to_be_hidden()
        box.press("End")
        box.press_sequentially(" posted despite lookup problems")
        box.press("ControlOrMeta+Enter")
        expect(page.get_by_text("#runner posted despite lookup problems", exact=True)).to_be_visible()
        messages = call(server, "GET", f"/api/threads/{thread['id']}/messages", human)["messages"]
        assert messages[-1]["body"] == "#runner posted despite lookup problems"
        if outcome == "pending":
            for route in pending:
                route.abort()
    finally:
        ctx.close()


@pytest.mark.parametrize("action", ["change", "caret", "escape"])
def test_late_thread_suggestions_do_not_replace_the_current_choice(server, browser, action):
    human, _ = seed_users(server)
    area = call(server, "POST", "/api/areas", human, {"name": "Late lookups"})
    runner = make_thread(server, human, area["id"], "Runner older lookup")
    make_thread(server, human, area["id"], "Worker current lookup")
    ctx, page = open_page(browser, server, human)
    pending = []
    try:
        page.goto(f"{server}/#/thread/{runner['id']}")
        page.get_by_role("button", name="Reply to thread").click()
        box = page.get_by_role("textbox", name="Add top-level reply", exact=False)
        pop = page.get_by_role("listbox", name="Thread suggestions")

        def hold_runner(route):
            query = parse_qs(urlparse(route.request.url).query).get("q")
            if query == ["runner"]:
                pending.append(route)
            else:
                route.continue_()

        page.route("**/api/search?**", hold_runner)
        with page.expect_request("**/api/search?**"):
            box.fill("#runner")
        if action == "change":
            box.fill("#worker")
            expect(pop.get_by_role("option")).to_have_text(re.compile("Worker current lookup"))
        elif action == "caret":
            box.press("ArrowLeft")
        else:
            box.press("Escape")
            page.get_by_role("button", name="Reply to thread").click()
            expect(box).to_have_value("#runner")
        with page.expect_response(lambda r: parse_qs(urlparse(r.url).query).get("q") == ["runner"]) as response:
            pending[0].continue_()
        response.value.finished()
        page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
        if action == "change":
            expect(pop.get_by_role("option")).to_have_text(re.compile("Worker current lookup"))
        else:
            expect(pop).to_be_hidden()
    finally:
        ctx.close()


@pytest.mark.parametrize("outcome", ["pending", "failure", "timeout"])
def test_home_hot_threads_work_while_recent_completions_are_unavailable(server, browser, outcome):
    human, _ = seed_users(server)
    area = call(server, "POST", "/api/areas", human, {"name": "Optional completions"})
    make_thread(server, human, area["id"], "Active work")
    done = make_thread(server, human, area["id"], "Completed work")
    call(server, "POST", f"/api/threads/{done['id']}/close", human, {"reason": "completed"})
    ctx, page = open_page(browser, server, human)
    interrupted = []
    try:
        if outcome == "timeout":
            page.clock.install()

        def interrupt_first_recent(route):
            query = parse_qs(urlparse(route.request.url).query)
            if query.get("state") == ["completed"] and not interrupted:
                interrupted.append(route)
                if outcome == "failure":
                    route.abort()
            else:
                route.continue_()

        page.route("**/api/threads?**", interrupt_first_recent)
        with page.expect_request(lambda r: parse_qs(urlparse(r.url).query).get("state") == ["completed"]):
            page.reload()
        active = page.get_by_role("link", name="Active work", exact=True)
        expect(active).to_be_visible()
        if outcome == "pending":
            active.click()
            expect(page.get_by_role("heading", name="Active work", exact=True)).to_be_visible()
            interrupted[0].abort()
            page.get_by_role("link", name="Home", exact=True).click()
        else:
            if outcome == "timeout":
                with page.expect_event("requestfailed", predicate=lambda r: parse_qs(urlparse(r.url).query).get("state") == ["completed"]):
                    page.clock.fast_forward(16000)
                expect(page.get_by_role("alert")).to_contain_text("Request timed out after 15s")
            else:
                expect(page.get_by_role("alert")).to_contain_text("Network error")
            page.get_by_role("button", name="Retry", exact=True).click()
        recent = page.get_by_role("region", name="Recently completed", exact=True)
        expect(recent.get_by_role("link", name="Completed work", exact=True)).to_be_visible()
        expect(page.get_by_role("link", name="Active work", exact=True)).to_be_visible()
    finally:
        ctx.close()


def test_thread_suggestions_are_shared_by_new_nested_and_edit_forms(server, browser):
    human, agent = seed_users(server)
    area = call(server, "POST", "/api/areas", human, {"name": "Forms"})
    target = make_thread(server, human, area["id"], "Reference target")
    source = make_thread(server, human, area["id"], "Form surfaces")
    call(server, "POST", f"/api/threads/{source['id']}/messages", agent, {"body": "Agent parent"})
    ref = f"#{target['id']}"
    ctx, page = open_page(browser, server, human)
    try:
        page.goto(f"{server}/#/thread/{source['id']}")
        expect(page.get_by_role("heading", name="Form surfaces", exact=True)).to_be_visible()
        page.get_by_role("button", name="New thread").click()
        sheet = page.get_by_role("dialog", name="New thread", exact=True)
        sheet.get_by_label("Title", exact=True).fill("Linked opening post")
        opening = sheet.get_by_label("Opening post", exact=False)
        opening.fill(ref)
        expect(sheet.get_by_role("option").first).to_contain_text("Reference target")
        opening.press("Tab")
        expect(opening).to_have_value(ref + " ")
        sheet.get_by_role("button", name="Create thread", exact=False).click()
        expect(page.get_by_role("heading", name="Linked opening post", exact=True)).to_be_visible()
        pill = page.get_by_role("link", name=f"Thread {ref}: Reference target", exact=True)
        expect(pill).to_have_attribute("href", f"#/thread/{target['id']}")

        page.goto(f"{server}/#/thread/{source['id']}")
        page.get_by_role("button", name="Reply", exact=True).last.click()
        nested = page.get_by_role("textbox", name="Reply to agentx", exact=True)
        nested.fill(ref)
        expect(page.get_by_role("option").first).to_contain_text("Reference target")
        nested.press("Enter")
        expect(nested).to_have_value(ref + " ")
        nested.press("ControlOrMeta+Enter")
        expect(pill).to_have_count(1)

        page.get_by_role("button", name="More actions", exact=True).first.click()
        page.get_by_role("menuitem", name="Edit", exact=True).click()
        edited = page.get_by_role("textbox", name="Edit message", exact=True)
        edited.fill(ref)
        page.get_by_role("option", name=re.compile("Reference target")).click()
        expect(edited).to_have_value(ref + " ")
        page.get_by_role("button", name="Save edit", exact=True).click()
        expect(pill).to_have_count(2)
    finally:
        ctx.close()


def test_bare_hash_merges_pinned_threads_then_limits_by_recent_activity(server, browser):
    human, _ = seed_users(server)
    area = call(server, "POST", "/api/areas", human, {"name": "Recent suggestions"})
    for i in range(10):
        thread = make_thread(server, human, area["id"], f"Pinned old {i}")
        call(server, "PUT", f"/api/threads/{thread['id']}/pin", human, {"pinned": True})
    newest = make_thread(server, human, area["id"], "Newest unpinned")
    ctx, page = open_page(browser, server, human)
    try:
        page.goto(f"{server}/#/thread/{newest['id']}")
        page.get_by_role("button", name="Reply to thread").click()
        box = page.get_by_role("textbox", name="Add top-level reply", exact=False)
        box.fill("#")
        options = page.get_by_role("listbox", name="Thread suggestions").get_by_role("option")
        expect(options).to_have_count(8)
        expect(options.first).to_contain_text("Newest unpinned")
        expect(options.nth(1)).to_contain_text("Pinned old 9")
        expect(options.nth(7)).to_contain_text("Pinned old 3")
        box.press("Enter")
        expect(box).to_have_value(f"#{newest['id']} ")
    finally:
        ctx.close()
