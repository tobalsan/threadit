import re
import sqlite3

from playwright.sync_api import expect
from test_ui_features import open_page
from test_ui_integration import call, make_thread, seed_users


def test_strikethrough_nests_inline_markdown_and_keeps_single_tilde(server, browser):
    human, _ = seed_users(server)
    area = call(server, "POST", "/api/areas", human, {"name": "Markdown"})
    thread = make_thread(server, human, area["id"], "Obsolete ideas", "~~old **bold** *idea* [link](https://example.com)~~ EDIT: ~5 minutes")
    ctx, page = open_page(browser, server, human)
    try:
        page.goto(f"{server}/#/thread/{thread['id']}")
        deleted = page.get_by_role("deletion")
        expect(deleted).to_have_text("old bold idea link")
        expect(deleted.get_by_role("link", name="link")).to_have_attribute("href", "https://example.com")
        expect(page.get_by_text("EDIT: ~5 minutes", exact=False)).to_be_visible()
    finally:
        ctx.close()


def test_thread_pills_preserve_boundaries_code_and_edit_refresh(server, browser):
    human, _ = seed_users(server)
    area = call(server, "POST", "/api/areas", human, {"name": "References"})
    target = make_thread(server, human, area["id"], "**Runner** [guide](https://example.com)")
    ref = f"#{target['id']}"
    thread = make_thread(server, human, area["id"], "Reading links", "\n".join([
        f"**x**{ref} and {ref}", f"**{ref}**", f"`{ref}` #999999", f"```\n{ref}\n```",
        f"# Heading {ref}", f"- List {ref}", f"> Quote {ref}",
    ]))
    call(server, "POST", f"/api/threads/{target['id']}/close", human, {"reason": "completed"})
    ctx, page = open_page(browser, server, human)
    try:
        page.goto(f"{server}/#/thread/{thread['id']}")
        pills = page.get_by_role("link", name=re.compile(r"^Thread #\d+: Runner guide"))
        expect(pills).to_have_count(4)
        expect(pills.first).to_have_attribute("href", f"#/thread/{target['id']}")
        expect(pills.first).to_contain_text("Closed")
        expect(page.get_by_text("#999999", exact=False)).to_be_visible()
        expect(page.get_by_text(ref, exact=True)).to_have_count(3)  # bold, code span, code block
        expect(page.get_by_role("link", name="guide", exact=True)).to_have_count(0)
        pills.first.click()
        expect(page.get_by_role("heading", name="Runner guide", exact=True)).to_be_visible()
        page.goto(f"{server}/#/thread/{thread['id']}")
        page.get_by_role("button", name="More actions").first.click()
        page.get_by_role("menuitem", name="Edit", exact=True).click()
        page.get_by_label("Edit message").fill(f"New reference {ref}")
        page.get_by_role("button", name="Save edit").click()
        expect(pills).to_have_count(1)
        expect(page.get_by_text("New reference", exact=False)).to_be_visible()
    finally:
        ctx.close()


def test_thread_autocomplete_filters_picks_and_preserves_heading(server, browser):
    human, _ = seed_users(server)
    area = call(server, "POST", "/api/areas", human, {"name": "Runner area"})
    target = make_thread(server, human, area["id"], "Runner exact")
    closed = make_thread(server, human, area["id"], "Runner finished")
    call(server, "POST", f"/api/threads/{closed['id']}/close", human, {"reason": "completed"})
    ctx, page = open_page(browser, server, human)
    try:
        page.goto(f"{server}/#/thread/{target['id']}")
        page.get_by_role("button", name="Reply to thread").click()
        box = page.get_by_role("textbox", name="Add top-level reply", exact=False)
        pop = page.get_by_role("listbox", name="Thread suggestions")
        box.fill(f"see #{target['id']}")
        expect(pop.get_by_role("option").first).to_contain_text("Runner exact")
        box.press("Enter")
        expect(box).to_have_value(f"see #{target['id']} ")
        box.fill("#runner")
        expect(pop.get_by_role("option")).to_have_count(2)
        expect(pop).to_contain_text("Runner area")
        expect(pop).to_contain_text("Closed")
        box.press("ArrowDown")
        expect(pop.get_by_role("option").nth(1)).to_have_attribute("aria-selected", "true")
        box.press("ArrowUp")
        box.press("Tab")
        expect(box).to_have_value(f"#{closed['id']} ")
        expect(pop).to_be_hidden()
        box.fill("#")
        expect(pop.get_by_role("option")).to_have_count(2)
        box.press("Escape")
        expect(pop).to_be_hidden()
        box.fill("# ")
        expect(pop).to_be_hidden()
        box.fill("a#runner")
        expect(pop).to_be_hidden()
        box.fill("(#runner")
        expect(pop).to_be_visible()
        pop.get_by_role("option").first.click()
        expect(box).to_have_value(f"(#{closed['id']} ")
    finally:
        ctx.close()


def test_home_recently_completed_limits_orders_and_links_full_list(server, browser, tmp_path):
    human, _ = seed_users(server)
    area = call(server, "POST", "/api/areas", human, {"name": "Wins"})
    for i in range(6):
        thread = make_thread(server, human, area["id"], f"Finished {i}")
        call(server, "POST", f"/api/threads/{thread['id']}/close", human, {"reason": "completed"})
    archived = make_thread(server, human, area["id"], "Abandoned")
    call(server, "POST", f"/api/threads/{archived['id']}/close", human, {"reason": "archived"})
    make_thread(server, human, area["id"], "Still active")
    ctx, page = open_page(browser, server, human)
    try:
        recent = page.get_by_role("region", name="Recently completed", exact=True)
        expect(recent.get_by_role("heading", name="Recently completed")).to_be_visible()
        links = recent.get_by_role("link", name=re.compile("^Finished"))
        expect(links).to_have_text(["Finished 5", "Finished 4", "Finished 3", "Finished 2", "Finished 1"])
        expect(recent).to_contain_text("by hanna")
        expect(recent.get_by_role("link", name="Abandoned")).to_have_count(0)
        recent.get_by_role("link", name="All completed threads").click()
        expect(page).to_have_url(f"{server}/#/completed")
        expect(page.get_by_role("link", name=re.compile("^Finished"))).to_have_count(6)
        page.goto(f"{server}/#/area/wins")
        page.get_by_label("Show", exact=True).select_option("completed")
        expect(page.get_by_role("link", name=re.compile("^Finished"))).to_have_count(6)
        page.get_by_label("Show", exact=True).select_option("archived")
        expect(page.get_by_role("link", name="Abandoned")).to_be_visible()
        with sqlite3.connect(tmp_path / "e2e.db") as conn:
            conn.execute("UPDATE threads SET closed_at = '2000-01-01T00:00:00.000000+00:00' WHERE closed_at IS NOT NULL")
        page.goto(f"{server}/#/")
        expect(page.get_by_role("link", name="Still active")).to_be_visible()
        expect(recent).to_have_count(0)
    finally:
        ctx.close()


def test_reply_collapse_counts_persists_opens_deep_links_and_survives_deletion(server, browser):
    human, agent = seed_users(server)
    area = call(server, "POST", "/api/areas", human, {"name": "Branches"})
    thread = make_thread(server, human, area["id"], "Tree")
    path = f"/api/threads/{thread['id']}/messages"
    parent = call(server, "POST", path, human, {"body": "Parent branch"})
    child = call(server, "POST", path, agent, {"body": "Child branch", "parent_id": parent["id"]})
    grandchild = call(server, "POST", path, human, {"body": "Deep target", "parent_id": child["id"]})
    ctx, page = open_page(browser, server, human)
    try:
        page.goto(f"{server}/#/thread/{thread['id']}")
        toggle = page.get_by_role("button", name="Hide 2 replies", exact=True)
        expect(toggle).to_have_attribute("aria-expanded", "true")
        toggle.focus()
        page.keyboard.press("Enter")
        expect(page.get_by_text("Child branch", exact=True)).to_be_hidden()
        expect(page.get_by_role("button", name="Show 2 replies")).to_have_attribute("aria-expanded", "false")
        page.reload()
        expect(page.get_by_role("button", name="Show 2 replies")).to_be_visible()
        expect(page.get_by_text("Deep target", exact=True)).to_be_hidden()
        page.get_by_role("button", name="Show 2 replies").click()
        page.get_by_role("button", name="Hide 1 reply", exact=True).click()
        page.get_by_role("button", name="Hide 2 replies", exact=True).click()
        page.goto(f"{server}/#/thread/{thread['id']}?m={grandchild['id']}")
        expect(page.get_by_text("Deep target", exact=True)).to_be_visible()
        page.reload()
        expect(page.get_by_text("Deep target", exact=True)).to_be_visible()
        call(server, "DELETE", f"/api/messages/{parent['id']}", human)
        page.reload()
        expect(page.get_by_text("message deleted", exact=True)).to_be_visible()
        page.get_by_role("button", name="Hide 2 replies", exact=True).click()
        expect(page.get_by_text("Deep target", exact=True)).to_be_hidden()
    finally:
        ctx.close()


def test_collapsed_branch_keeps_poll_state_and_opens_after_own_reply(server, browser):
    human, agent = seed_users(server)
    area = call(server, "POST", "/api/areas", human, {"name": "Live branches"})
    thread = make_thread(server, human, area["id"], "Live tree")
    path = f"/api/threads/{thread['id']}/messages"
    parent = call(server, "POST", path, agent, {"body": "Agent branch"})
    child = call(server, "POST", path, human, {"body": "First child", "parent_id": parent["id"]})
    ctx, page = open_page(browser, server, human)
    try:
        page.goto(f"{server}/#/thread/{thread['id']}")
        page.get_by_role("button", name="Hide 1 reply", exact=True).click()
        call(server, "POST", path, agent, {"body": "Polled child", "parent_id": child["id"]})
        expect(page.get_by_role("button", name="Show 2 replies", exact=True)).to_be_visible(timeout=10000)
        expect(page.get_by_text("Polled child", exact=True)).to_be_hidden()
        page.get_by_role("button", name="Reply", exact=True).nth(1).click()
        page.get_by_role("textbox", name="Reply to agentx", exact=True).fill("My visible reply")
        page.get_by_role("button", name="Send reply", exact=True).click()
        expect(page.get_by_text("My visible reply", exact=True)).to_be_visible()
        expect(page.get_by_text("First child", exact=True)).to_be_visible()
        expect(page.get_by_role("button", name="Hide 3 replies", exact=True)).to_be_visible()
        page.reload()
        expect(page.get_by_text("My visible reply", exact=True)).to_be_visible()
    finally:
        ctx.close()


def test_thread_references_keep_source_boundaries_in_blockquotes(server, browser):
    human, _ = seed_users(server)
    area = call(server, "POST", "/api/areas", human, {"name": "Quotes"})
    target = make_thread(server, human, area["id"], "Quoted target")
    thread = make_thread(server, human, area["id"], "Quote boundaries", f"#{target['id']}\n\n>#{target['id']}\n> #{target['id']}\n>>#{target['id']}\n>> #{target['id']}")
    ctx, page = open_page(browser, server, human)
    try:
        page.goto(f"{server}/#/thread/{thread['id']}")
        expect(page.get_by_role("link", name=f"Thread #{target['id']}: Quoted target", exact=True)).to_have_count(3)
    finally:
        ctx.close()
