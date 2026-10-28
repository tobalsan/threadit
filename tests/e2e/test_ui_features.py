import base64
import re
import time

from playwright.sync_api import expect
from test_ui_integration import call, login, make_thread, seed_users

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


def open_page(browser, server, token):
    ctx = browser.new_context(reduced_motion="reduce")
    page = ctx.new_page()
    login(page, server, token)
    return ctx, page


def test_markdown_renders_and_is_xss_safe(server, browser):
    human, _ = seed_users(server)
    area = call(
        server, "POST", "/api/areas", human,
        {"name": "Docs", "description": "# Rules\n\n- be **kind**\n- _careful_\n\n[home](/#/) <img src=x onerror=window.pwned=1>"},
    )
    body = "\n".join([
        "# Big heading",
        "Some **bold** and *italic* and `inline <b>code</b>` text",
        "second line same paragraph",
        "",
        "```",
        "<script>window.pwned=1</script>",
        "```",
        "1. one",
        "2. two",
        "",
        "> quoted **text**",
        "",
        "[ok](https://example.com/x) [bad](javascript:window.pwned=1) [proto](//evil.example) [data](data:text/html,x)",
        "[rel](/#/users) mail: [m](mailto:a@b.example)",
        "<img src=x onerror=window.pwned=1> <script>window.pwned=1</script> <b>raw</b>",
    ])
    thread = call(server, "POST", "/api/threads", human, {
        "area_id": area["id"], "title": "**Bold** title <i>raw</i> [l](javascript:window.pwned=1)", "body": body,
    })["thread"]
    ctx, page = open_page(browser, server, human)
    try:
        page.goto(f"{server}/#/area/docs")
        card = page.locator(".card .md").first
        expect(card.locator("h3")).to_have_text("Rules")
        expect(card.locator("ul li")).to_have_count(2)
        expect(card.locator("ul li strong")).to_have_text("kind")
        expect(card.locator("ul li em")).to_have_text("careful")
        expect(card.locator("img")).to_have_count(0)
        expect(page.locator(".li.thread a.t strong")).to_have_text("Bold")
        expect(page.locator(".li.thread a.t i")).to_have_count(0)

        page.goto(f"{server}/#/thread/{thread['id']}")
        h1 = page.locator("h1")
        expect(h1.locator("strong")).to_have_text("Bold")
        expect(h1).to_contain_text("<i>raw</i>")
        expect(h1.locator("a")).to_have_count(0)
        msg = page.locator(".msgbody .md").first
        expect(msg.locator("h3")).to_have_text("Big heading")
        expect(msg.locator("strong").first).to_have_text("bold")
        expect(msg.locator("em").first).to_have_text("italic")
        expect(msg.locator("p code").first).to_have_text("inline <b>code</b>")
        expect(msg.locator("p br").first).to_be_attached()
        expect(msg.locator("pre code")).to_have_text("<script>window.pwned=1</script>")
        expect(msg.locator("ol li")).to_have_count(2)
        expect(msg.locator("blockquote strong")).to_have_text("text")
        ok = msg.get_by_role("link", name="ok")
        assert ok.get_attribute("href") == "https://example.com/x"
        assert "noopener" in ok.get_attribute("rel")
        assert msg.get_by_role("link", name="rel").get_attribute("href") == "/#/users"
        assert msg.get_by_role("link", name="m").get_attribute("href") == "mailto:a@b.example"
        hrefs = msg.locator("a").evaluate_all("els => els.map(e => e.getAttribute('href'))")
        assert sorted(hrefs) == sorted(["https://example.com/x", "/#/users", "mailto:a@b.example"])
        expect(msg).to_contain_text("[bad](javascript:window.pwned=1)")
        expect(msg).to_contain_text("<img src=x onerror=window.pwned=1> <script>window.pwned=1</script> <b>raw</b>")
        for tag in ("img", "script", "b", "i"):
            expect(msg.locator(tag)).to_have_count(0)
        assert page.evaluate("window.pwned") is None
        assert page.evaluate("document.querySelectorAll('main a[href^=\"javascript\"]').length") == 0

        # editor keeps raw markdown (rendering happens at display time only)
        page.get_by_role("button", name="More actions").first.click()
        page.get_by_role("menuitem", name="Edit").click()
        expect(page.get_by_label("Edit message")).to_have_value(body)
    finally:
        ctx.close()


def test_mention_autocomplete(server, browser):
    human, agent = seed_users(server)
    other = call(server, "POST", "/api/register", body={"username": "agentz", "account_type": "agent", "description": "Zed does zoology"})
    call(server, "POST", f"/api/admin/users/{other['id']}/approve", human)
    area = call(server, "POST", "/api/areas", human, {"name": "Ment", "description": "d"})
    thread = make_thread(server, human, area["id"], "Mentions")
    ctx, page = open_page(browser, server, human)
    try:
        page.goto(f"{server}/#/thread/{thread['id']}")
        page.get_by_role("button", name="Reply to thread").click()
        box = page.locator("#top-reply")
        pop = page.get_by_role("listbox", name="Mention suggestions")
        box.click()
        box.press_sequentially("hello @ag")
        expect(pop.get_by_role("option")).to_have_count(2)
        expect(pop).to_contain_text("@agentx")
        expect(pop).to_contain_text("Zed does zoology")
        expect(pop.get_by_role("option").first).to_have_attribute("aria-selected", "true")
        box.press_sequentially("entz")
        expect(pop.get_by_role("option")).to_have_count(1)
        box.press("Enter")
        expect(box).to_have_value("hello @agentz ")
        expect(pop).to_be_hidden()

        box.fill("")
        box.press_sequentially("x @ag")
        box.press("ArrowDown")
        expect(pop.get_by_role("option").nth(1)).to_have_attribute("aria-selected", "true")
        box.press("ArrowUp")
        box.press("ArrowDown")
        box.press("Tab")
        expect(box).to_have_value("x @agentz ")

        box.fill("")
        box.press_sequentially("@ha")
        expect(pop.get_by_role("option")).to_have_count(1)
        expect(pop).to_contain_text("@hanna")
        box.press("Escape")
        expect(pop).to_be_hidden()
        expect(box).to_have_value("@ha")

        box.fill("")
        box.press_sequentially("mail a@ag")
        expect(pop).to_be_hidden()  # '@' glued to a word is not a mention
        box.fill("")
        box.press_sequentially("see @agentx")
        pop.get_by_role("option").first.click()
        expect(box).to_have_value("see @agentx ")
        box.press_sequentially("and @agentz")
        expect(pop).to_be_visible()
        box.press("Enter")
        expect(box).to_have_value("see @agentx and @agentz ")
    finally:
        ctx.close()


def test_attachments_thumbnail_lightbox_and_download(server, browser):
    human, _ = seed_users(server)
    area = call(server, "POST", "/api/areas", human, {"name": "Files", "description": "d"})
    ctx, page = open_page(browser, server, human)
    try:
        page.goto(f"{server}/#/area/files")
        page.get_by_role("button", name="New thread").click()
        page.fill("#th-title", "With files")
        page.fill("#th-body", "see attached")
        form = page.locator("form.sheet")
        form.locator("input[type=file]").set_input_files(
            [{"name": "pic.png", "mimeType": "image/png", "buffer": PNG},
             {"name": "notes.txt", "mimeType": "text/plain", "buffer": b"hello notes"}]
        )
        expect(form.get_by_text("notes.txt (11 B)")).to_be_visible()
        form.get_by_role("button", name="Remove notes.txt").click()
        expect(form.get_by_text("notes.txt")).to_have_count(0)
        form.locator("input[type=file]").set_input_files(
            [{"name": "notes.txt", "mimeType": "text/plain", "buffer": b"hello notes"}]
        )
        form.get_by_role("button", name="Create thread").click()
        expect(page.get_by_role("heading", name="With files")).to_be_visible()

        thumb = page.get_by_role("button", name="Open image pic.png")
        expect(thumb).to_be_visible()
        img = thumb.locator("img")
        expect(img).to_have_attribute("src", re.compile("^blob:"))
        page.wait_for_function("document.querySelector('.thumb').naturalWidth > 0")
        # thumbnail sits right below the message body
        order = page.evaluate(
            "() => { const b = document.querySelector('.msgbody'); return [...b.children].map(c => c.className).filter(c => c !== 'oplabel').slice(0, 4); }"
        )
        assert order[1].startswith("md body") and order[2] == "attachments", order

        thumb.click()
        box = page.locator("#lightbox")
        expect(box).to_be_visible()
        expect(box.locator("img")).to_have_attribute("alt", "pic.png")
        page.keyboard.press("Escape")
        expect(box).to_have_count(0)
        thumb.click()
        expect(box).to_be_visible()
        box.click()
        expect(box).to_have_count(0)

        with page.expect_download() as dl:
            page.get_by_role("link", name="notes.txt (11 B)").click()
        assert dl.value.suggested_filename == "notes.txt"

        # reply with an attachment
        reply = page.locator("form.compose")
        page.get_by_role("button", name="Reply to thread").click()
        page.fill("#top-reply", "second")
        reply.locator("input[type=file]").set_input_files(
            [{"name": "again.png", "mimeType": "image/png", "buffer": PNG}]
        )
        reply.get_by_role("button", name="Send", exact=True).click()
        expect(page.get_by_role("button", name="Open image again.png")).to_be_visible()
        page.goto(f"{server}/#/context/2")
        expect(page.get_by_role("button", name="Open image again.png")).to_be_visible()

        # the file URL itself needs the bearer header
        status = page.evaluate("fetch('/api/attachments/1').then(r => r.status)")
        assert status == 401
    finally:
        ctx.close()


def test_editing_and_modified_indicator(server, browser):
    human, agent = seed_users(server)
    area = call(server, "POST", "/api/areas", human, {"name": "Edits", "description": "d"})
    thread = make_thread(server, human, area["id"], "Original title", "original body")
    other = call(server, "POST", f"/api/threads/{thread['id']}/messages", agent, {"body": "agent says"})
    ctx, page = open_page(browser, server, human)
    actx, apage = open_page(browser, server, agent)
    try:
        page.goto(f"{server}/#/thread/{thread['id']}")
        expect(page.get_by_text("(modified)")).to_have_count(0)
        # the superadmin has a More actions menu on every live message
        expect(page.get_by_role("button", name="More actions")).to_have_count(2)
        op = page.locator(".msg.op > .msgbody")
        op.get_by_role("button", name="More actions").click()
        page.get_by_role("menuitem", name="Edit").click()
        page.get_by_label("Edit message").fill("changed **body**")
        page.get_by_role("button", name="Save edit").click()
        msg = page.locator(".msgbody").first
        expect(msg.locator(".md strong")).to_have_text("body")
        expect(msg.get_by_text("(modified)")).to_be_visible()
        assert "Edited" in msg.get_by_text("(modified)").get_attribute("title")
        # cancel leaves text untouched
        op.get_by_role("button", name="More actions").click()
        page.get_by_role("menuitem", name="Edit").click()
        page.get_by_label("Edit message").fill("nope")
        page.get_by_role("button", name="Cancel").click()
        page.get_by_role("button", name="Keep editing").click()
        expect(page.get_by_label("Edit message")).to_have_value("nope")
        page.get_by_role("button", name="Cancel").click()
        page.get_by_role("button", name="Discard").click()
        expect(msg.locator(".md strong")).to_have_text("body")

        # thread title
        page.get_by_role("button", name="Edit title").click()
        page.get_by_label("Edit title", exact=True).fill("Better title")
        page.get_by_role("button", name="Save title").click()
        expect(page.get_by_role("heading", name="Better title")).to_be_visible()
        expect(page.locator("h1").get_by_text("(modified)")).to_be_visible()

        # agent sees both indicators but cannot edit the human's content
        apage.goto(f"{server}/#/thread/{thread['id']}")
        expect(apage.get_by_text("(modified)")).to_have_count(2)
        expect(apage.get_by_role("button", name="Edit title")).to_have_count(0)
        expect(apage.get_by_role("button", name="More actions")).to_have_count(1)  # own message only
        # list row shows it too
        page.goto(f"{server}/#/area/edits")
        expect(page.locator(".li.thread").get_by_text("(modified)")).to_be_visible()

        # closed thread: edit buttons disabled
        call(server, "POST", f"/api/threads/{thread['id']}/close", human, {"reason": "completed"})
        page.goto(f"{server}/#/thread/{thread['id']}")
        expect(page.get_by_role("button", name="More actions")).to_have_count(0)
        expect(page.get_by_role("button", name="Edit title")).to_have_count(0)
        assert other["author"]["username"] == "agentx"
    finally:
        ctx.close()
        actx.close()


def test_superadmin_moderates_other_authors_messages(server, browser):
    human, agent = seed_users(server)
    member = call(server, "POST", "/api/register", body={"username": "alice", "account_type": "human"})
    call(server, "POST", f"/api/admin/users/{member['id']}/approve", human)
    area = call(server, "POST", "/api/areas", human, {"name": "Moderation", "description": "d"})
    thread = make_thread(server, member["token"], area["id"], "Moderated thread", "human OP")
    call(server, "POST", f"/api/threads/{thread['id']}/messages", member["token"], {"body": "human reply"})
    call(server, "POST", f"/api/threads/{thread['id']}/messages", agent, {"body": "agent reply"})
    ctx, page = open_page(browser, server, human)
    mctx, mpage = open_page(browser, server, member["token"])
    actx, apage = open_page(browser, server, agent)
    try:
        url = f"{server}/#/thread/{thread['id']}"
        mpage.goto(url)
        expect(mpage.get_by_role("button", name="More actions")).to_have_count(2)
        expect(mpage.locator(".msgbody").filter(has_text="agent reply").get_by_role("button", name="More actions")).to_have_count(0)
        apage.goto(url)
        expect(apage.get_by_role("button", name="More actions")).to_have_count(1)
        expect(apage.locator(".msgbody").filter(has_text="human OP").get_by_role("button", name="More actions")).to_have_count(0)
        page.goto(url)
        expect(page.get_by_role("button", name="More actions")).to_have_count(3)
        for index, original in enumerate(("human OP", "human reply", "agent reply")):
            card = page.locator(".msgbody").nth(index)
            expect(card).to_contain_text(original)
            card.get_by_role("button", name="More actions").click()
            page.get_by_role("menuitem", name="Edit", exact=True).click()
            expect(card.get_by_label("Edit message")).to_have_value(original)
            card.get_by_label("Edit message").fill("corrected " + original)
            card.get_by_role("button", name="Save edit").click()
            expect(card.locator(".md")).to_have_text("corrected " + original)
            expect(card.get_by_text("(modified)")).to_be_visible()
            card.get_by_role("button", name="More actions").click()
            page.get_by_role("menuitem", name="Delete", exact=True).click()
            dialog = page.get_by_role("dialog")
            expect(dialog).to_contain_text("Delete message?")
            dialog.get_by_role("button", name="Cancel", exact=True).click()
            expect(card.locator(".md")).to_have_text("corrected " + original)
            card.get_by_role("button", name="More actions").click()
            page.get_by_role("menuitem", name="Delete", exact=True).click()
            dialog.get_by_role("button", name="Delete", exact=True).click()
            expect(card.get_by_text("message deleted")).to_be_visible()
            expect(card.get_by_role("button", name="More actions")).to_have_count(0)
        page.reload()
        expect(page.get_by_text("message deleted", exact=True)).to_have_count(3)
        expect(page.get_by_role("button", name="More actions")).to_have_count(0)
    finally:
        ctx.close()
        mctx.close()
        actx.close()


def test_symmetric_vote_buttons(server, browser):
    human, _ = seed_users(server)
    area = call(server, "POST", "/api/areas", human, {"name": "Votes", "description": "d"})
    thread = make_thread(server, human, area["id"], "Vote thread")
    ctx, page = open_page(browser, server, human)
    try:
        page.goto(f"{server}/#/thread/{thread['id']}")
        stepper = page.locator(".msgbody .vote").first
        expect(stepper).to_be_visible()
        labels = stepper.locator("button").all_inner_texts()
        assert labels == ["-5", "-1", "+1", "+5"]
        page.get_by_role("button", name="Vote -5", exact=True).first.click()
        expect(page.get_by_label("score -5").first).to_be_visible()
        page.get_by_role("button", name="Vote -1", exact=True).first.click()
        page.get_by_role("button", name="Toggle inspector").click()
        expect(page.locator("#insp").get_by_label("Importance score")).to_have_text("-6")
        page.get_by_role("button", name="Toggle inspector").click()
    finally:
        ctx.close()


def test_slug_urls(server, browser):
    human, _ = seed_users(server)
    area = call(server, "POST", "/api/areas", human, {"name": "Deep Research!", "description": "d"})
    assert area["slug"] == "deep-research"
    thread = make_thread(server, human, area["id"], "Slug thread")
    ctx, page = open_page(browser, server, human)
    try:
        page.get_by_role("link", name="Deep Research!").click()
        expect(page).to_have_url(f"{server}/#/area/deep-research")
        expect(page.get_by_role("heading", name="Deep Research!")).to_be_visible()
        expect(page.get_by_role("link", name="Slug thread")).to_be_visible()
        page.goto(f"{server}/#/area/{area['id']}")  # old numeric route still works
        expect(page.get_by_role("heading", name="Deep Research!")).to_be_visible()
        expect(page.get_by_role("link", name="Slug thread")).to_be_visible()
        page.locator("#sortsel").select_option("created")
        expect(page).to_have_url(f"{server}/#/area/{area['id']}?state=active&sort=created")
        page.goto(f"{server}/#/area/deep-research")
        page.locator("#sortsel").select_option("activity")
        expect(page).to_have_url(f"{server}/#/area/deep-research?state=active&sort=activity")
        expect(page.get_by_role("link", name="Slug thread")).to_be_visible()
        page.goto(f"{server}/#/thread/{thread['id']}")
        link = page.get_by_role("link", name="Deep Research!")
        assert link.get_attribute("href") == "#/area/deep-research"
        link.click()
        expect(page).to_have_url(f"{server}/#/area/deep-research")
        page.goto(f"{server}/#/area/no-such-area")
        expect(page.get_by_role("alert")).to_contain_text("does not exist")
        # renaming changes the slug used by links
        call(server, "PATCH", f"/api/areas/{area['id']}", human, {"name": "Renamed"})
        page.goto(f"{server}/#/areas")
        assert page.get_by_role("link", name="Renamed").get_attribute("href") == "#/area/renamed"
    finally:
        ctx.close()


def test_users_page_and_descriptions(server, browser):
    human, agent = seed_users(server)
    ctx, page = open_page(browser, server, human)
    try:
        page.get_by_role("link", name="Users").click()
        expect(page.get_by_role("heading", name="Users")).to_be_visible()
        cards = page.locator(".card.user")
        expect(cards).to_have_count(2)
        expect(cards.filter(has_text="agentx")).to_contain_text("d")
        expect(cards.filter(has_text="agentx").locator(".badge.agent")).to_be_visible()
        expect(cards.filter(has_text="hanna")).to_contain_text("(no description)")
        expect(cards.filter(has_text="agentx").get_by_role("button")).to_have_count(0)
        cards.filter(has_text="hanna").get_by_role("button", name="Edit description").click()
        page.get_by_label("Your description").fill("I review **things**")
        page.get_by_role("button", name="Save description").click()
        expect(cards.filter(has_text="hanna")).to_contain_text("I review **things**")
        page.reload()
        expect(page.locator(".card.user").filter(has_text="hanna")).to_contain_text("I review")

        assert call(server, "GET", "/api/me", human)["description"] == "I review **things**"
    finally:
        ctx.close()


def test_auth_screen_points_agents_to_skill(server, browser):
    ctx = browser.new_context(reduced_motion="reduce")
    page = ctx.new_page()
    try:
        page.goto(server + "/")
        expect(page.locator('a[href$="/SKILL.md"]')).to_be_visible()
        assert page.request.get(server + "/SKILL.md").ok
    finally:
        ctx.close()


def test_logout_shows_login_screen(server, browser):
    human, _ = seed_users(server)
    area = call(server, "POST", "/api/areas", human, {"name": "Out", "description": "d"})
    make_thread(server, human, area["id"], "Private thread")
    ctx, page = open_page(browser, server, human)
    try:
        expect(page.get_by_text("Private thread")).to_be_visible()
        page.get_by_role("button", name="Log out").click()
        expect(page.get_by_label("Token")).to_be_visible()
        expect(page.get_by_text("Private thread")).to_have_count(0)
    finally:
        ctx.close()


def test_agent_registration_requires_description(server, browser):
    ctx = browser.new_context(reduced_motion="reduce")
    page = ctx.new_page()
    try:
        page.goto(server + "/")
        page.fill("#reg-name", "robot")
        page.select_option("#reg-type", "agent")
        page.get_by_role("button", name="Register").click()
        expect(page.locator(".tokenbox")).to_have_count(0)
        assert page.evaluate("document.getElementById('reg-desc').validity.valueMissing")
        page.fill("#reg-desc", "Does robot things")
        page.get_by_role("button", name="Register").click()
        expect(page.locator(".tokenbox")).to_be_visible()
    finally:
        ctx.close()


def test_area_rename_from_area_page_shows_renamed_area(server, browser):
    human, _ = seed_users(server)
    call(server, "POST", "/api/areas", human, {"name": "Before", "description": "d"})
    ctx, page = open_page(browser, server, human)
    try:
        page.goto(f"{server}/#/area/before")
        page.get_by_role("button", name="Edit area").click()
        page.get_by_label("Name").fill("After Rename")
        page.get_by_role("button", name="Save", exact=True).click()
        expect(page.get_by_role("heading", name="After Rename")).to_be_visible()
        assert page.url.endswith("#/area/after-rename")
    finally:
        ctx.close()


def test_vote_keeps_in_progress_edit_draft(server, browser):
    human, _ = seed_users(server)
    area = call(server, "POST", "/api/areas", human, {"name": "Drafts", "description": "d"})
    thread = make_thread(server, human, area["id"], "T", "orig")
    ctx, page = open_page(browser, server, human)
    try:
        page.goto(f"{server}/#/thread/{thread['id']}")
        page.get_by_role("button", name="More actions").click()
        page.get_by_role("menuitem", name="Edit").click()
        page.get_by_label("Edit message").fill("my draft")
        page.get_by_role("button", name="Vote +1").first.click()
        expect(page.get_by_label("score 1").first).to_be_visible()
        expect(page.get_by_label("Edit message")).to_have_value("my draft")
    finally:
        ctx.close()


def wait_until_held(page, held):
    """Wait until the route handler received a request, so the request is held."""
    for _ in range(500):
        if held:
            return
        page.wait_for_timeout(10)
    raise AssertionError("route handler did not receive the request")


def test_file_picker_disabled_during_upload(server, browser):
    human, _ = seed_users(server)
    area = call(server, "POST", "/api/areas", human, {"name": "Up", "description": "d"})
    ctx, page = open_page(browser, server, human)
    try:
        held = []
        page.route("**/api/attachments?*", lambda route: held.append(route), times=1)
        page.goto(f"{server}/#/area/up")
        expect(page.get_by_role("heading", name="Up", exact=True)).to_be_visible()  # area loaded, so the form preselects it
        page.get_by_role("button", name="New thread").click()
        page.get_by_label("Title").fill("with files")
        page.get_by_label("Opening post (use @username to notify an agent)").fill("body")
        picker = page.get_by_label("Attach files (max 10, 10 MB each)")
        picker.set_input_files([
            {"name": "a.png", "mimeType": "image/png", "buffer": PNG},
            {"name": "b.png", "mimeType": "image/png", "buffer": PNG},
        ])
        with page.expect_request("**/api/attachments?*"):
            page.get_by_role("button", name="Create thread").click()
        wait_until_held(page, held)
        expect(picker).to_be_disabled()
        expect(page.get_by_role("button", name="Remove a.png")).to_be_disabled()
        expect(page.get_by_role("heading", name="with files")).to_have_count(0)
        for route in held:
            route.continue_()
        expect(page.get_by_role("heading", name="with files")).to_be_visible()
        assert len(call(server, "GET", f"/api/threads?area_id={area['id']}", human)["threads"]) == 1
    finally:
        ctx.close()


DROP_FILES = """(form, names) => {
    const dt = new DataTransfer();
    names.forEach((n) => dt.items.add(new File(['x'], n, { type: 'text/plain' })));
    for (const type of ['dragenter', 'dragover', 'drop']) {
        form.dispatchEvent(new DragEvent(type, { bubbles: true, cancelable: true, dataTransfer: dt }));
    }
}"""


def test_attach_toggle_and_drag_drop_multiple_files(server, browser):
    human, _ = seed_users(server)
    area = call(server, "POST", "/api/areas", human, {"name": "Drop", "description": "d"})
    thread = make_thread(server, human, area["id"], "drop here")
    ctx, page = open_page(browser, server, human)
    try:
        page.goto(f"{server}/#/thread/{thread['id']}")
        page.get_by_role("button", name="Reply to thread").click()
        form = page.locator("form.compose")
        picker = form.get_by_label("Attach files (max 10, 10 MB each)")
        toggle = form.get_by_role("button", name="Toggle attachments")
        expect(picker).to_be_hidden()
        toggle.click()
        expect(picker).to_be_visible()
        expect(toggle).to_have_attribute("aria-expanded", "true")
        toggle.click()
        expect(picker).to_be_hidden()

        form.evaluate(DROP_FILES, ["one.txt", "two.txt"])
        expect(form.get_by_text("one.txt (1 B)")).to_be_visible()
        expect(form.get_by_text("two.txt (1 B)")).to_be_visible()
        expect(form).not_to_have_class(re.compile("dragover"))
        form.locator("textarea").fill("dropped files")
        form.get_by_role("button", name="Send").click()
        expect(page.get_by_role("link", name="one.txt")).to_be_visible()
        msgs = call(server, "GET", f"/api/threads/{thread['id']}", human)["messages"]
        assert sorted(a["filename"] for a in msgs[-1]["attachments"]) == ["one.txt", "two.txt"]
    finally:
        ctx.close()


def test_drafts_survive_reload_and_clear_after_send(server, browser):
    human, _ = seed_users(server)
    area = call(server, "POST", "/api/areas", human, {"name": "Drafts", "description": "d"})
    thread = make_thread(server, human, area["id"], "draft thread")
    ctx, page = open_page(browser, server, human)
    try:
        page.goto(f"{server}/#/thread/{thread['id']}")
        page.get_by_role("button", name="Reply to thread").click()
        top = page.get_by_label("Add top-level reply (@username to notify an agent)")
        top.fill("half-written reply")
        page.reload()
        expect(top).to_have_value("half-written reply")
        page.get_by_role("button", name="Send").click()
        expect(page.locator(".msg").filter(has_text="half-written reply")).to_have_count(1)
        page.reload()
        expect(top).to_have_value("")

        area_loaded = page.get_by_role("heading", name="Drafts", exact=True)  # drafts are kept per area
        page.goto(f"{server}/#/area/drafts")
        expect(area_loaded).to_be_visible()
        page.get_by_role("button", name="New thread").click()
        page.fill("#th-title", "draft title")
        page.fill("#th-body", "draft body")
        page.reload()
        expect(area_loaded).to_be_visible()
        page.get_by_role("button", name="New thread").click()
        expect(page.locator("#th-title")).to_have_value("draft title")
        expect(page.locator("#th-body")).to_have_value("draft body")
        page.get_by_role("button", name="Create thread").click()
        expect(page.get_by_role("heading", name="draft title")).to_be_visible()
        page.goto(f"{server}/#/area/drafts")
        page.get_by_role("button", name="New thread").click()
        expect(page.locator("#th-title")).to_have_value("")
    finally:
        ctx.close()


def test_new_thread_form_cancel_dismisses_and_discards_draft(server, browser):
    human, _ = seed_users(server)
    call(server, "POST", "/api/areas", human, {"name": "Cancel", "description": "d"})
    ctx, page = open_page(browser, server, human)
    try:
        page.goto(f"{server}/#/area/cancel")
        page.get_by_role("button", name="New thread").click()
        page.fill("#th-title", "never mind")
        page.get_by_role("button", name="Cancel", exact=True).click()
        page.get_by_role("button", name="Discard").click()
        expect(page.locator("#th-title")).to_have_count(0)
        page.get_by_role("button", name="New thread").click()
        expect(page.locator("#th-title")).to_have_value("")
    finally:
        ctx.close()


def test_bare_urls_become_links(server, browser):
    human, _ = seed_users(server)
    area = call(server, "POST", "/api/areas", human, {"name": "Links", "description": "d"})
    body = (
        "Report at https://docs.example.com/d/1EN9-_IsTa/edit?tab=t.d2o (need account).\n"
        "Wiki https://en.wikipedia.org/wiki/Foo_(bar), and `https://not.a.link` in code."
    )
    thread = make_thread(server, human, area["id"], "see https://title.example", body)
    ctx, page = open_page(browser, server, human)
    try:
        page.goto(f"{server}/#/thread/{thread['id']}")
        msg = page.locator(".msg").first
        links = msg.locator(".msgbody a[target=_blank]")
        expect(links).to_have_count(2)
        assert [links.nth(i).get_attribute("href") for i in range(2)] == [
            "https://docs.example.com/d/1EN9-_IsTa/edit?tab=t.d2o",
            "https://en.wikipedia.org/wiki/Foo_(bar)",
        ]
        assert links.first.get_attribute("rel") == "noopener noreferrer"
        expect(msg.locator("code")).to_have_text("https://not.a.link")
        expect(page.get_by_role("heading", name="see https://title.example")).to_be_visible()
    finally:
        ctx.close()


def test_cmd_enter_submits_message_and_edit(server, browser):
    human, _ = seed_users(server)
    area = call(server, "POST", "/api/areas", human, {"name": "Keys", "description": "d"})
    thread = make_thread(server, human, area["id"], "keyboard")
    ctx, page = open_page(browser, server, human)
    try:
        page.goto(f"{server}/#/thread/{thread['id']}")
        page.get_by_role("button", name="Reply to thread").click()
        top = page.get_by_label("Add top-level reply (@username to notify an agent)")
        top.fill("sent with keys")
        top.press("Meta+Enter")
        expect(page.locator(".msg").filter(has_text="sent with keys")).to_have_count(1)
        expect(top).to_have_value("")
        page.locator(".msg").filter(has_text="sent with keys").get_by_role("button", name="More actions").click()
        page.get_by_role("menuitem", name="Edit").click()
        edit = page.get_by_label("Edit message")
        edit.fill("edited with keys")
        edit.press("Control+Enter")
        expect(page.locator(".msg").filter(has_text="edited with keys")).to_have_count(1)
        expect(page.get_by_label("Edit message")).to_have_count(0)
        msgs = call(server, "GET", f"/api/threads/{thread['id']}", human)["messages"]
        assert [m["body"] for m in msgs[1:]] == ["edited with keys"]
    finally:
        ctx.close()


def test_area_sidebar_and_quick_vote_from_list(server, browser):
    human, _ = seed_users(server)
    area = call(server, "POST", "/api/areas", human, {"name": "Side", "description": "**Rules** here"})
    thread = make_thread(server, human, area["id"], "vote me")
    closed = make_thread(server, human, area["id"], "done one")
    call(server, "POST", f"/api/threads/{closed['id']}/close", human, {"reason": "completed"})
    ctx = browser.new_context(viewport={"width": 1280, "height": 800}, reduced_motion="reduce")
    page = ctx.new_page()
    login(page, server, human)
    try:
        page.goto(f"{server}/#/area/side?state=all")
        side = page.get_by_role("complementary", name="Area description")
        expect(side.locator("strong")).to_have_text("Rules")
        row = page.locator(".li.thread").filter(has_text="vote me")
        assert side.bounding_box()["x"] > row.bounding_box()["x"] + row.bounding_box()["width"] - 1

        page.get_by_role("button", name="Upvote vote me").click()
        expect(row.locator(".imp")).to_contain_text("1")
        page.get_by_role("button", name="Upvote vote me").click()
        page.get_by_role("button", name="Downvote vote me").click()
        expect(row.locator(".imp output")).to_have_text("1")
        got = call(server, "GET", f"/api/threads/{thread['id']}", human)["thread"]
        assert got["importance"] == 1
        expect(page.get_by_role("button", name="Upvote done one")).to_have_count(0)

        page.set_viewport_size({"width": 600, "height": 800})
        assert side.bounding_box()["y"] > row.bounding_box()["y"]  # stacked below the list
    finally:
        ctx.close()


def test_list_score_colors_and_debounced_importance_resort(server, browser):
    human, _ = seed_users(server)
    area = call(server, "POST", "/api/areas", human, {"name": "Rank", "description": "d"})
    low = make_thread(server, human, area["id"], "low one")
    top = make_thread(server, human, area["id"], "top one")
    call(server, "POST", f"/api/messages/{top['op_message_id']}/votes", human, {"delta": 1})
    ctx, page = open_page(browser, server, human)
    try:
        page.clock.install()
        page.goto(f"{server}/#/area/rank")
        titles = page.locator(".li.thread a.t")
        expect(titles).to_have_text(["top one", "low one"])
        top_imp = page.locator(".li.thread").filter(has_text="top one").locator(".imp")
        top_score = top_imp.locator("output")
        expect(top_imp).to_have_class(re.compile("sc-warm"))
        low_imp = page.locator(".li.thread").filter(has_text="low one").locator(".imp")
        low_score = low_imp.locator("output")
        expect(low_imp).to_have_class("vote v imp sc")
        up = page.get_by_role("button", name="Upvote low one")
        up.click()
        expect(low_score).to_have_text("1")
        up.click()
        expect(low_score).to_have_text("2")
        expect(titles).to_have_text(["top one", "low one"])  # not yet: debounce pending
        page.clock.fast_forward(2001)
        expect(titles).to_have_text(["low one", "top one"])
        for _ in range(4):
            up.click()
        expect(low_score).to_have_text("6")
        expect(low_imp).to_have_class(re.compile("sc-hot"))
        down = page.get_by_role("button", name="Downvote top one")
        down.click()
        down.click()
        expect(top_score).to_have_text("-1")
        expect(top_imp).to_have_class(re.compile("sc-cool"))
        for _ in range(5):
            down.click()
        expect(top_score).to_have_text("-6")
        expect(top_imp).to_have_class(re.compile("sc-cold"))
        assert low["id"] != top["id"]
    finally:
        ctx.close()


def test_home_hot_list_paging_and_area_link(server, browser):
    human, _ = seed_users(server)
    one = call(server, "POST", "/api/areas", human, {"name": "Alpha", "description": "d"})
    two = call(server, "POST", "/api/areas", human, {"name": "Beta", "description": "d"})
    ctx, page = open_page(browser, server, human)
    try:
        expect(page.get_by_text("No active threads yet.")).to_be_visible()
        first = make_thread(server, human, one["id"], "alpha-first")
        make_thread(server, human, two["id"], "beta-second")
        call(server, "POST", f"/api/messages/{first['op_message_id']}/votes", human, {"delta": 5})
        page.goto(f"{server}/#/")
        page.reload()
        rows = page.locator(".li.thread")
        expect(rows).to_have_count(2)
        expect(rows.nth(0)).to_contain_text("alpha-first")
        expect(rows.nth(1)).to_contain_text("beta-second")
        for i in range(21):
            make_thread(server, human, two["id"], f"bulk {i}")
        page.reload()
        expect(rows).to_have_count(20)
        expect(page.get_by_role("link", name="Previous")).to_have_count(0)
        page.get_by_role("link", name="Next").click()
        expect(page).to_have_url(f"{server}/#/?page=2")
        expect(rows).to_have_count(3)
        expect(page.get_by_role("link", name="Next")).to_have_count(0)
        page.get_by_role("link", name="Previous").click()
        expect(rows).to_have_count(20)
        rows.nth(0).get_by_role("link", name="Alpha", exact=True).click()
        expect(page).to_have_url(f"{server}/#/area/alpha")
    finally:
        ctx.close()


def test_thread_page_op_block_and_reply_count(server, browser):
    human, _ = seed_users(server)
    area = call(server, "POST", "/api/areas", human, {"name": "Ops", "description": "d"})
    thread = make_thread(server, human, area["id"], "With replies", "the op text")
    empty = make_thread(server, human, area["id"], "No replies")
    first = [call(server, "POST", f"/api/threads/{thread['id']}/messages", human, {"body": t}) for t in ("reply one", "reply two")][0]
    call(server, "POST", f"/api/threads/{thread['id']}/messages", human, {"body": "nested child", "parent_id": first["id"]})
    ctx, page = open_page(browser, server, human)
    try:
        page.goto(f"{server}/#/thread/{thread['id']}")
        expect(page.get_by_role("heading", name="Replies (3)")).to_be_visible()
        expect(page.locator(".msg.op")).to_have_count(1)
        expect(page.locator(".msg.op")).to_contain_text("the op text")
        tops = page.locator(".msg.top")
        expect(tops).to_have_count(3)
        expect(tops.nth(0)).to_have_class(re.compile(r"\bop\b"))
        expect(tops.nth(1)).to_contain_text("reply one")
        expect(tops.nth(2)).to_contain_text("reply two")
        page.goto(f"{server}/#/thread/{empty['id']}")
        expect(page.get_by_text("No replies yet")).to_be_visible()
    finally:
        ctx.close()


def test_theme_toggle_persists_and_system_follows_scheme(server, browser):
    human, _ = seed_users(server)
    ctx = browser.new_context(color_scheme="light", reduced_motion="reduce")
    page = ctx.new_page()
    try:
        login(page, server, human)
        html = page.locator("html")
        expect(html).to_have_attribute("data-theme", "light")
        expect(page.get_by_role("radio", name="System")).to_have_attribute("aria-checked", "true")
        page.get_by_role("radio", name="Dark").click()
        expect(html).to_have_attribute("data-theme", "dark")
        page.reload()
        expect(html).to_have_attribute("data-theme", "dark")
        expect(page.get_by_role("radio", name="Dark")).to_have_attribute("aria-checked", "true")
        page.get_by_role("radio", name="Light").click()
        page.reload()
        expect(html).to_have_attribute("data-theme", "light")
        page.get_by_role("radio", name="System").click()
        page.emulate_media(color_scheme="dark")
        expect(html).to_have_attribute("data-theme", "dark")
        page.emulate_media(color_scheme="light")
        expect(html).to_have_attribute("data-theme", "light")
    finally:
        ctx.close()


def test_shell_nav_attention_badge_toolbar_and_collapse(server, browser):
    human, agent = seed_users(server)
    area = call(server, "POST", "/api/areas", human, {"name": "Shell", "description": "d"})
    thread = make_thread(server, agent, area["id"], "Ping", "hello @hanna")
    call(server, "POST", f"/api/threads/{thread['id']}/messages", agent, {"body": "again @hanna"})
    ctx, page = open_page(browser, server, human)
    try:
        nav = page.get_by_role("navigation", name="Main")
        expect(nav.get_by_role("link", name="Home")).to_have_attribute("aria-current", "page")
        expect(nav.get_by_role("link", name="Admin")).to_be_visible()
        expect(nav.get_by_role("link", name="Attention").locator(".navcount")).to_have_text("2")
        expect(page.locator("#bartitle")).to_have_text("Home")
        expect(page.locator("#newbtn")).to_be_visible()
        nav.get_by_role("link", name="Areas").click()
        expect(nav.get_by_role("link", name="Areas")).to_have_attribute("aria-current", "page")
        expect(page.locator("#bartitle")).to_have_text("Areas")
        page.goto(f"{server}/#/area/shell")
        expect(page.locator("#bartitle")).to_have_text("Shell")
        page.get_by_role("button", name="New thread").click()
        expect(page.get_by_label("Title")).to_be_focused()
        page.set_viewport_size({"width": 900, "height": 700})
        expect(nav.get_by_role("link", name="Users")).to_be_visible()
        expect(nav.get_by_role("link", name="Users").locator(".t")).to_be_hidden()
        assert page.locator(".sidebar").bounding_box()["width"] < 80
        page.get_by_role("button", name="Log out").click()
        expect(page.locator(".sidebar")).to_be_hidden()
    finally:
        ctx.close()


def test_thread_list_cards_show_meta_and_area_controls(server, browser):
    human, agent = seed_users(server)
    area = call(server, "POST", "/api/areas", human, {"name": "Cards", "description": "d"})
    pinned = make_thread(server, human, area["id"], "pin me")
    call(server, "PUT", f"/api/threads/{pinned['id']}/pin", human, {"pinned": True})
    mentioned = make_thread(server, agent, area["id"], "needs hanna", "hi @hanna")
    call(server, "POST", f"/api/threads/{mentioned['id']}/messages", agent, {"body": "a reply"})
    make_thread(server, human, area["id"], "plain one")
    ctx, page = open_page(browser, server, human)
    try:
        page.goto(f"{server}/#/area/cards")
        pin_row = page.locator(".li.thread").filter(has_text="pin me")
        expect(pin_row.locator(".meta .pin")).to_have_text("Pinned")
        expect(pin_row.get_by_label("0 replies")).to_be_visible()
        row = page.locator(".li.thread").filter(has_text="needs hanna")
        expect(row.locator(".need")).to_have_text("Needs you · 1")
        expect(row.locator(".who")).to_contain_text("agentx")
        expect(row.locator(".who .ag")).to_be_visible()
        expect(row.get_by_label("1 reply")).to_be_visible()
        expect(row.get_by_role("link", name="Cards")).to_have_attribute("href", "#/area/cards")
        for sel in ("#sortsel", "#ordersel", "#statesel"):
            if sel == "#ordersel":
                page.locator("#sortsel").select_option("created")
            expect(page.locator(sel)).to_be_visible()
        assert row.bounding_box()["y"] > 0
        expect(page.locator(".li.thread")).to_have_count(3)
        gap = page.locator(".li.thread").first.evaluate("e => getComputedStyle(e.parentElement).rowGap")
        assert gap == "8px"
        page.goto(f"{server}/#/")
        expect(page.locator(".li.thread")).to_have_count(3)
    finally:
        ctx.close()


def test_thread_header_pin_toggle_and_close_popover(server, browser):
    human, agent = seed_users(server)
    area = call(server, "POST", "/api/areas", human, {"name": "Head", "description": "d"})
    thread = make_thread(server, human, area["id"], "Header thread")
    ctx, page = open_page(browser, server, human)
    actx, apage = open_page(browser, server, agent)
    try:
        page.goto(f"{server}/#/thread/{thread['id']}")
        expect(page.get_by_role("heading", name="Header thread")).to_be_visible()
        expect(page.locator(".crumb").get_by_role("link", name="Head")).to_be_visible()
        expect(page.locator(".oplabel")).to_have_text("Original post")
        size = page.locator("h1.ttitle").evaluate("e => [getComputedStyle(e).fontSize, getComputedStyle(e).fontWeight]")
        assert size == ["30px", "800"]

        pin = page.get_by_role("button", name="Pin", exact=False)
        expect(pin).to_have_attribute("aria-pressed", "false")
        pin.click()
        expect(page.get_by_role("button", name="Pinned")).to_have_attribute("aria-pressed", "true")
        page.get_by_role("button", name="Pinned").click()
        expect(page.get_by_role("button", name="Pin", exact=False)).to_have_attribute("aria-pressed", "false")

        # hover pencil: Esc cancels, Enter saves
        page.locator(".ttl").hover()
        page.get_by_role("button", name="Edit title").click()
        field = page.get_by_label("Edit title", exact=True)
        field.fill("Discarded")
        field.press("Escape")
        page.get_by_role("button", name="Discard").click()
        expect(page.get_by_role("heading", name="Header thread")).to_be_visible()
        page.get_by_role("button", name="Edit title").click()
        field = page.get_by_label("Edit title", exact=True)
        field.fill("Saved by enter")
        field.press("Enter")
        expect(page.get_by_role("heading", name="Saved by enter")).to_be_visible()

        # close popover: Esc closes it and gives the focus back
        close = page.get_by_role("button", name="Close thread")
        close.click()
        expect(page.get_by_role("menuitem", name="Close as completed")).to_be_visible()
        expect(page.get_by_role("menuitem", name="Close as archived")).to_be_visible()
        page.keyboard.press("Escape")
        expect(page.get_by_role("menu")).to_have_count(0)
        expect(close).to_be_focused()
        close.click()
        page.mouse.click(5, 5)
        expect(page.get_by_role("menu")).to_have_count(0)

        # non-owners get no pin toggle and no pencil
        apage.goto(f"{server}/#/thread/{thread['id']}")
        expect(apage.get_by_role("heading", name="Saved by enter")).to_be_visible()
        expect(apage.get_by_role("button", name="Pin", exact=False)).to_have_count(0)
        expect(apage.get_by_role("button", name="Edit title")).to_have_count(0)
    finally:
        ctx.close()
        actx.close()


def test_message_card_head_stepper_react_popover_and_reply(server, browser):
    human, agent = seed_users(server)
    area = call(server, "POST", "/api/areas", human, {"name": "Cardy", "description": "d"})
    thread = make_thread(server, human, area["id"], "Card thread", "op body")
    call(server, "POST", f"/api/threads/{thread['id']}/messages", agent, {"body": "ping @hanna"})
    ctx, page = open_page(browser, server, human)
    try:
        page.goto(f"{server}/#/thread/{thread['id']}")
        agent_card = page.locator(".msgbody").filter(has_text="ping @hanna")
        expect(agent_card.locator(".avatar.agent")).to_be_visible()
        expect(agent_card.locator(".who .ag")).to_be_visible()
        expect(agent_card.locator(".need")).to_have_text("Needs you")
        expect(agent_card).to_have_class(re.compile(r"\bpending\b"))
        op = page.locator(".msg.op .msgbody")
        expect(op.locator(".avatar:not(.agent)")).to_be_visible()

        # the score pill sits top right and turns into the stepper on hover
        pill = op.locator(".vscore")
        stepper = op.locator(".vote")
        expect(pill).to_be_visible()
        page.mouse.move(0, 0)
        expect(stepper).to_have_css("opacity", "0")
        card_box = op.bounding_box()
        pill_box = pill.bounding_box()
        assert card_box["x"] + card_box["width"] - (pill_box["x"] + pill_box["width"]) < 20
        assert pill_box["y"] - card_box["y"] < 40
        op.hover()
        expect(stepper).to_have_css("opacity", "1")
        op.get_by_role("button", name="Vote +5").click()
        expect(op.get_by_label("score 5")).to_be_attached()

        # hover actions also show on keyboard focus
        reply_btn = op.get_by_role("button", name="Reply", exact=True)
        page.mouse.move(0, 0)
        expect(op.locator(".hov")).to_have_css("opacity", "0")
        reply_btn.focus()
        expect(op.locator(".hov")).to_have_css("opacity", "1")

        # react popover: Esc closes it and returns focus, a pick adds a chip
        react = op.get_by_role("button", name="☺ React")
        react.click()
        expect(page.get_by_role("menuitem", name="React 🎉")).to_be_visible()
        page.keyboard.press("Escape")
        expect(page.get_by_role("menu")).to_have_count(0)
        expect(react).to_be_focused()
        react.click()
        page.get_by_role("menuitem", name="React 🎉").click()
        expect(op.get_by_role("button", name="🎉 1")).to_have_attribute("aria-pressed", "true")
        react = op.get_by_role("button", name="☺ React")
        react.click()
        page.get_by_label("Custom emoji reaction").fill("🔥")
        page.get_by_label("Custom emoji reaction").press("Enter")
        expect(op.get_by_role("button", name="🔥 1")).to_be_visible()
        op.get_by_role("button", name="🎉 1").click()
        expect(op.get_by_role("button", name="🎉 1")).to_have_count(0)

        # inline reply composer expands under the card
        agent_card.hover()
        agent_card.get_by_role("button", name="Reply", exact=True).click()
        page.get_by_label("Reply to agentx").fill("nested answer")
        page.get_by_role("button", name="Send reply").click()
        expect(page.locator(".children .msgbody").filter(has_text="nested answer")).to_be_visible()
    finally:
        ctx.close()


def test_composer_is_docked_sends_with_shortcut_and_disables_when_closed(server, browser):
    human, agent = seed_users(server)
    area = call(server, "POST", "/api/areas", human, {"name": "Dock", "description": "d"})
    thread = make_thread(server, human, area["id"], "Dock thread")
    for i in range(14):
        call(server, "POST", f"/api/threads/{thread['id']}/messages", human, {"body": f"filler reply {i}"})
    ctx, page = open_page(browser, server, human)
    try:
        page.goto(f"{server}/#/thread/{thread['id']}")
        # the composer starts hidden behind the "Reply to thread" button; Esc hides it again
        opener = page.get_by_role("button", name="Reply to thread")
        top = page.get_by_label("Add top-level reply (@username to notify an agent)")
        expect(top).to_be_hidden()
        opener.click()
        expect(top).to_be_focused()
        top.press("Escape")
        expect(top).to_be_hidden()
        opener.click()
        composer = page.locator("form.compose")
        expect(composer).to_be_visible()
        assert composer.evaluate("e => getComputedStyle(e).backdropFilter") != "none"
        viewport_h = page.evaluate("window.innerHeight")
        box = composer.bounding_box()
        assert viewport_h - (box["y"] + box["height"]) < 40, box
        page.locator("#scroll").evaluate("e => e.scrollTop = 0")
        box = composer.bounding_box()
        assert viewport_h - (box["y"] + box["height"]) < 40, box

        # @ autocomplete opens above the docked capsule and fills the name
        top.fill("hello @agent")
        option = page.locator(".mention-item").first
        expect(option).to_be_visible()
        assert option.bounding_box()["y"] < composer.bounding_box()["y"]
        option.click()
        expect(top).to_have_value("hello @agentx ")

        # Cmd/Ctrl+Enter sends, the draft clears
        top.press("ControlOrMeta+Enter")
        expect(page.locator(".msg").filter(has_text="hello @agentx")).to_have_count(1)
        expect(top).to_have_value("")

        # closed thread: the reply button is disabled
        call(server, "POST", f"/api/threads/{thread['id']}/close", human, {"reason": "completed"})
        page.reload()
        expect(opener).to_be_disabled()
        expect(top).to_be_hidden()
    finally:
        ctx.close()


def test_inspector_toggle_sections_and_outside_click(server, browser):
    human, agent = seed_users(server)
    area = call(server, "POST", "/api/areas", human, {"name": "Insp", "description": "Area **rules** here"})
    thread = make_thread(server, human, area["id"], "Inspect me", "hello @agentx")
    call(server, "POST", f"/api/threads/{thread['id']}/messages", agent, {"body": "reply from agent @hanna"})
    ctx, page = open_page(browser, server, human)
    try:
        page.goto(f"{server}/#/thread/{thread['id']}")
        expect(page.get_by_role("heading", name="Inspect me")).to_be_visible()
        panel = page.locator("#insp")
        toggle = page.get_by_role("button", name="Toggle inspector")
        expect(panel).to_be_hidden()
        toggle.click()
        expect(panel).to_be_visible()
        expect(toggle).to_have_attribute("aria-pressed", "true")
        for heading in ["Importance", "Attention", "Participants", "Actions", "Details"]:
            expect(panel.get_by_role("heading", name=heading, exact=True)).to_be_visible()
        expect(panel.get_by_role("heading", name="Area · Insp")).to_be_visible()
        expect(panel.locator("strong")).to_have_text("rules")
        expect(panel.get_by_role("link", name="agentx: reply from agent")).to_have_attribute("href", re.compile(r"\?m=2$"))
        expect(panel.locator(".ppl").filter(has_text="agentx")).to_contain_text("d")
        expect(panel.locator(".kv").filter(has_text="Messages")).to_contain_text("2")
        expect(panel.locator(".kv").filter(has_text="Created")).to_contain_text("just now")
        expect(panel.locator(".kv").filter(has_text="Last activity")).to_contain_text("just now")

        panel.get_by_role("button", name="Importance +5").click()
        expect(panel.get_by_label("Importance score")).to_have_text("5")
        expect(page.locator(".msg.op .vscore")).to_have_text("5")

        panel.get_by_role("button", name="Pin").click()
        expect(panel.get_by_role("button", name="Pinned")).to_be_visible()

        page.mouse.click(300, 300)
        expect(panel).to_be_hidden()
        toggle.click()
        expect(panel).to_be_visible()
        page.keyboard.press("Escape")
        expect(panel).to_be_hidden()

        page.goto(f"{server}/#/")
        expect(toggle).to_be_hidden()
    finally:
        ctx.close()


def test_command_palette_finds_thread_by_id(server, browser):
    human, _ = seed_users(server)
    area = call(server, "POST", "/api/areas", human, {"name": "Id Lab", "description": "d"})
    target = make_thread(server, human, area["id"], "Archived target")
    call(server, "POST", f"/api/threads/{target['id']}/close", human, {"reason": "archived"})
    make_thread(server, human, area["id"], "Unrelated topic")
    ctx, page = open_page(browser, server, human)
    try:
        box = page.get_by_role("combobox", name="Search threads, areas, screens and actions")
        for query in (str(target["id"]), f"#{target['id']}"):
            page.keyboard.press("ControlOrMeta+k")
            box.fill(query)
            expect(page.get_by_role("option", name=re.compile("^Archived target"))).to_have_attribute("aria-selected", "true")
            page.keyboard.press("Enter")
            expect(page).to_have_url(re.compile(rf"#/thread/{target['id']}$"))
            page.goto(server + "/#/")
    finally:
        ctx.close()


def test_command_palette_open_filter_enter_and_actions(server, browser):
    human, _ = seed_users(server)
    area = call(server, "POST", "/api/areas", human, {"name": "Palette Lab", "description": "d"})
    make_thread(server, human, area["id"], "Zebra crossing plan")
    make_thread(server, human, area["id"], "Other topic")
    ctx, page = open_page(browser, server, human)
    try:
        box = page.get_by_role("combobox", name="Search threads, areas, screens and actions")
        expect(box).to_have_count(0)
        page.keyboard.press("ControlOrMeta+k")
        expect(box).to_be_focused()
        expect(page.get_by_role("dialog", name="Command palette")).to_be_visible()
        # empty query: hot threads, screens and actions
        expect(page.get_by_role("option", name="Other topic")).to_be_visible()
        expect(page.get_by_role("option", name="Toggle inspector")).to_have_count(0)  # not on a thread page
        page.keyboard.press("Escape")
        expect(box).to_have_count(0)

        # sidebar field opens it too; filter, arrows, Enter opens the thread
        page.get_by_role("button", name="Search", exact=True).click()
        box.fill("zebra")
        thread_opt = page.get_by_role("option", name=re.compile("^Zebra crossing plan"))
        expect(thread_opt).to_be_visible()
        expect(page.get_by_role("option", name="Other topic")).to_have_count(0)
        expect(thread_opt).to_have_attribute("aria-selected", "true")
        expect(box).to_have_attribute("aria-activedescendant", thread_opt.get_attribute("id"))
        box.press("Enter")
        expect(page).to_have_url(re.compile(r"#/thread/1$"))
        expect(page.locator("h1.ttitle")).to_have_text("Zebra crossing plan")
        expect(box).to_have_count(0)

        # areas and screens group, arrows move, theme action
        page.keyboard.press("ControlOrMeta+k")
        box.fill("palette")
        area_opt = page.get_by_role("option", name=re.compile("^Palette Lab"))
        expect(area_opt).to_be_visible()
        area_opt.hover()
        expect(area_opt).to_have_attribute("aria-selected", "true")
        box.press("Enter")
        expect(page).to_have_url(re.compile(r"#/area/palette-lab$"))
        page.keyboard.press("ControlOrMeta+k")
        box.fill("users")
        box.press("ArrowDown")
        expect(page.get_by_role("dialog", name="Command palette").get_by_role("option").nth(1)).to_have_attribute("aria-selected", "true")
        box.press("ArrowUp")
        box.press("Enter")
        expect(page).to_have_url(re.compile(r"#/users$"))

        page.keyboard.press("ControlOrMeta+k")
        box.fill("dark")
        page.get_by_role("option", name="Switch to dark mode").click()
        expect(page.locator("html")).to_have_attribute("data-theme", "dark")
        page.keyboard.press("ControlOrMeta+k")
        box.fill("light")
        page.get_by_role("option", name="Switch to light mode").click()
        expect(page.locator("html")).to_have_attribute("data-theme", "light")

        # on a thread page: toggle inspector action; outside click closes the palette
        page.goto(f"{server}/#/thread/1")
        expect(page.locator("h1.ttitle")).to_have_text("Zebra crossing plan")
        page.keyboard.press("ControlOrMeta+k")
        box.fill("inspector")
        box.press("Enter")
        expect(page.locator("#insp")).to_be_visible()
        page.keyboard.press("ControlOrMeta+k")
        expect(box).to_be_visible()
        page.mouse.click(5, 5)
        expect(box).to_have_count(0)
        expect(page.locator(".scrim")).to_have_count(0)
    finally:
        ctx.close()


def test_new_thread_sheet_default_area_filter_and_create(server, browser):
    human, _ = seed_users(server)
    alpha = call(server, "POST", "/api/areas", human, {"name": "Alpha", "description": "First **area** here. More."})
    call(server, "POST", "/api/areas", human, {"name": "Beta", "description": "Second place"})
    call(server, "POST", "/api/areas", human, {"name": "Gamma", "description": "Third place"})
    make_thread(server, human, alpha["id"], "seed thread")
    ctx, page = open_page(browser, server, human)
    try:
        sheet = page.get_by_role("dialog", name="New thread")
        new = page.get_by_role("button", name="New thread")
        filt = page.get_by_role("combobox", name="Filter areas")

        # no current area and no last area: the list opens
        new.click()
        expect(sheet).to_be_visible()
        expect(filt).to_be_focused()
        expect(page.get_by_role("option")).to_have_count(3)
        expect(page.get_by_role("option", name=re.compile("^Alpha First area here"))).to_contain_text("1 active")
        filt.fill("gam")
        expect(page.get_by_role("option")).to_have_count(1)
        filt.press("Enter")
        expect(filt).to_have_count(0)
        expect(sheet.get_by_role("button", name="Area: Gamma")).to_be_visible()
        expect(page.get_by_label("Title")).to_be_focused()
        page.keyboard.press("Escape")
        expect(sheet).to_have_count(0)
        expect(new).to_be_focused()

        # the last area is the default away from an area page
        new.click()
        expect(sheet.get_by_role("button", name="Area: Gamma")).to_be_visible()
        page.get_by_label("Title").fill("kept draft")
        page.mouse.click(5, 5)
        expect(sheet).to_have_count(0)

        # an area page wins over the last area; arrows and Enter pick another area
        page.goto(f"{server}/#/area/alpha")
        expect(page.locator("#bartitle")).to_have_text("Alpha")
        new.click()
        expect(sheet.get_by_role("button", name="Area: Alpha")).to_be_visible()
        sheet.get_by_role("button", name="Area: Alpha").click()
        expect(page.get_by_role("option", name=re.compile("^Alpha"))).to_have_attribute("aria-selected", "true")
        filt.press("ArrowDown")
        filt.press("Enter")
        expect(sheet.get_by_role("button", name="Area: Beta")).to_be_visible()
        # drafts are kept for each area
        sheet.get_by_role("button", name="Area: Beta").click()
        filt.fill("gamma")
        filt.press("Enter")
        expect(page.get_by_label("Title")).to_have_value("kept draft")

        # create in Beta from Cmd-K; on success go to the new thread
        page.keyboard.press("Escape")
        page.get_by_role("button", name="Discard").click()
        expect(sheet).to_have_count(0)
        page.keyboard.press("ControlOrMeta+k")
        page.get_by_role("combobox", name="Search threads, areas, screens and actions").fill("create thread in beta")
        page.get_by_role("option", name=re.compile("^Create thread in Beta")).click()
        expect(sheet.get_by_role("button", name="Area: Beta")).to_be_visible()
        page.get_by_label("Title").fill("Made in sheet")
        page.get_by_label("Opening post (use @username to notify an agent)").fill("body text")
        page.get_by_label("Opening post (use @username to notify an agent)").press("ControlOrMeta+Enter")
        expect(page.locator("h1.ttitle")).to_have_text("Made in sheet")
        expect(sheet).to_have_count(0)
        expect(page.locator(".crumb")).to_have_text("Beta")
    finally:
        ctx.close()


def test_auth_screen_is_one_glass_card_without_shell(server, browser):
    page = browser.new_page()
    page.goto(server + "/")
    card = page.locator(".authcard")
    expect(card).to_have_count(1)
    expect(card.get_by_role("heading", name="Log in")).to_be_visible()
    expect(card.get_by_role("heading", name="Register")).to_be_visible()
    expect(page.locator(".sidebar")).to_be_hidden()
    page.close()


def test_new_thread_sheet_keeps_typed_text_and_files_when_choosing_area(server, browser):
    human, _ = seed_users(server)
    call(server, "POST", "/api/areas", human, {"name": "Alpha", "description": "First"})
    call(server, "POST", "/api/areas", human, {"name": "Beta", "description": "Second"})
    ctx, page = open_page(browser, server, human)
    try:
        sheet = page.get_by_role("dialog", name="New thread")
        page.get_by_role("button", name="New thread").click()
        expect(page.get_by_role("combobox", name="Filter areas")).to_be_focused()
        # dismiss the list, type, attach, then choose an area
        page.keyboard.press("Escape")
        expect(page.get_by_role("combobox", name="Filter areas")).to_have_count(0)
        sheet.get_by_label("Title").fill("typed title")
        sheet.get_by_label("Opening post (use @username to notify an agent)").fill("typed body")
        sheet.locator("input[type=file]").set_input_files({"name": "pic.png", "mimeType": "image/png", "buffer": PNG})
        expect(sheet.locator(".filelist li")).to_contain_text("pic.png")
        sheet.get_by_role("button", name="Area: choose one").click()
        page.get_by_role("option", name=re.compile("^Beta")).click()
        expect(sheet.get_by_role("button", name="Area: Beta")).to_be_visible()
        expect(sheet.get_by_label("Title")).to_have_value("typed title")
        expect(sheet.get_by_label("Opening post (use @username to notify an agent)")).to_have_value("typed body")
        expect(sheet.locator(".filelist li")).to_contain_text("pic.png")
        sheet.get_by_role("button", name="Create thread").click()
        expect(page.locator("h1.ttitle")).to_have_text("typed title")
        expect(page.get_by_role("button", name="Open image pic.png")).to_be_visible()
    finally:
        ctx.close()


CONTRAST_JS = """([fgSel, bgSel]) => {
  const parse = c => c.match(/[\\d.]+/g).map(Number);
  const f = v => { v /= 255; return v <= .03928 ? v / 12.92 : Math.pow((v + .055) / 1.055, 2.4); };
  const lum = c => .2126 * f(c[0]) + .7152 * f(c[1]) + .0722 * f(c[2]);
  const fg = parse(getComputedStyle(document.querySelector(fgSel)).color);
  const bg = parse(getComputedStyle(document.querySelector(bgSel)).backgroundColor);
  const [hi, lo] = [lum(fg), lum(bg)].sort((a, b) => b - a);
  return (hi + .05) / (lo + .05);
}"""


def test_filled_controls_and_faded_scores_meet_contrast(server, browser):
    human, _ = seed_users(server)
    area = call(server, "POST", "/api/areas", human, {"name": "Contrast", "description": "d"})
    cool = make_thread(server, human, area["id"], "cool thread")
    cold = make_thread(server, human, area["id"], "cold thread")
    call(server, "POST", f"/api/messages/{cool['op_message_id']}/votes", human, {"delta": -1})
    call(server, "POST", f"/api/messages/{cold['op_message_id']}/votes", human, {"delta": -5})
    ctx, page = open_page(browser, server, human)
    try:
        for theme in ("light", "dark"):
            page.goto(f"{server}/#/area/contrast")
            page.evaluate("t => document.documentElement.setAttribute('data-theme', t)", theme)
            for cls in ("sc-cool", "sc-cold"):
                score = f".imp.{cls} output"
                expect(page.locator(score)).to_have_count(1)
                assert page.evaluate("s => getComputedStyle(document.querySelector(s)).opacity", score) == "1"
                ratio = page.evaluate(CONTRAST_JS, [score, ".li"])
                assert ratio >= 4.5, (theme, cls, ratio)
            page.get_by_role("button", name="New thread").click()
            ratio = page.evaluate(CONTRAST_JS, ["button.primary", "button.primary"])
            assert ratio >= 4.5, (theme, "primary", ratio)
            page.keyboard.press("Escape")
    finally:
        ctx.close()


def test_close_menu_action_removes_popover(server, browser):
    human, _ = seed_users(server)
    area = call(server, "POST", "/api/areas", human, {"name": "Closing", "description": "d"})
    thread = make_thread(server, human, area["id"], "To close")
    ctx, page = open_page(browser, server, human)
    try:
        page.goto(f"{server}/#/thread/{thread['id']}")
        page.get_by_role("button", name="Close thread").click()
        page.get_by_role("menuitem", name="Close as completed").click()
        expect(page.get_by_role("button", name="Reopen thread")).to_be_visible()
        expect(page.get_by_role("menu")).to_have_count(0)
    finally:
        ctx.close()


def test_attention_badge_update_keeps_nav_focus(server, browser):
    human, agent = seed_users(server)
    area = call(server, "POST", "/api/areas", human, {"name": "Badge", "description": "d"})
    thread = make_thread(server, human, area["id"], "Ping")
    call(server, "POST", f"/api/threads/{thread['id']}/messages", agent, {"body": "hi @hanna", "parent_id": thread["op_message_id"]})
    ctx, page = open_page(browser, server, human)
    try:
        held = []
        page.route("**/api/attention?*", lambda route: held.append(route), times=1)
        with page.expect_request("**/api/attention?*"):
            page.goto(f"{server}/#/users")
        wait_until_held(page, held)
        expect(page.get_by_role("heading", name="Users")).to_be_visible()
        link = page.locator("#nav a", has_text="Users")
        link.focus()
        page.evaluate("document.querySelector('#nav a[href=\"#/users\"]').dataset.keep = '1'")
        for route in held:
            route.continue_()
        expect(page.locator("#nav .navcount")).to_have_text("1")
        expect(link).to_be_focused()
        expect(link).to_have_attribute("data-keep", "1")
    finally:
        ctx.close()


def test_back_closes_palette_and_action_returns_focus(server, browser):
    human, _ = seed_users(server)
    ctx, page = open_page(browser, server, human)
    try:
        palette = page.get_by_role("dialog", name="Command palette")
        box = page.get_by_role("combobox", name="Search threads, areas, screens and actions")
        page.goto(f"{server}/#/areas")
        expect(page.get_by_role("heading", name="Areas")).to_be_visible()
        page.goto(f"{server}/#/users")
        page.keyboard.press("ControlOrMeta+k")
        expect(palette).to_be_visible()
        page.go_back()
        expect(page.locator("#bartitle")).to_have_text("Areas")
        expect(palette).to_have_count(0)
        # the page title changes at once, but the view finishes later and focuses <main>
        expect(page.get_by_role("heading", name="Areas")).to_be_visible()
        expect(page.locator("#main")).to_be_focused()

        # a theme action neither navigates nor opens a dialog: focus goes back
        sidebar_search = page.get_by_role("button", name="Search", exact=True)
        sidebar_search.focus()
        page.keyboard.press("ControlOrMeta+k")
        box.fill("dark mode")
        box.press("Enter")
        expect(palette).to_have_count(0)
        expect(page.locator("html")).to_have_attribute("data-theme", "dark")
        expect(sidebar_search).to_be_focused()
    finally:
        ctx.close()


def test_toolbar_shows_thread_title(server, browser):
    human, _ = seed_users(server)
    area = call(server, "POST", "/api/areas", human, {"name": "Bar", "description": "d"})
    thread = make_thread(server, human, area["id"], "A rather specific title " + "long " * 30)
    ctx, page = open_page(browser, server, human)
    try:
        page.goto(f"{server}/#/thread/{thread['id']}")
        expect(page.locator("#bartitle")).to_have_text(thread["title"])
        style = page.locator("#bartitle").evaluate("e => [getComputedStyle(e).textOverflow, getComputedStyle(e).whiteSpace]")
        assert style == ["ellipsis", "nowrap"]
    finally:
        ctx.close()


def test_sidebar_footer_is_compact_and_reply_count_uses_icon(server, browser):
    human, _ = seed_users(server)
    area = call(server, "POST", "/api/areas", human, {"name": "Foot", "description": "d"})
    make_thread(server, human, area["id"], "icon row")
    ctx, page = open_page(browser, server, human)
    try:
        page.goto(f"{server}/#/area/foot")
        rc = page.locator(".li.thread .rc")
        expect(rc).to_have_text("0")
        expect(rc.locator("svg")).to_have_count(1)
        who = page.locator("#whoami")
        expect(who).to_contain_text("superadmin")
        expect(who).not_to_contain_text("human")
        expect(who.locator(".ag")).to_have_count(0)
        logout = who.get_by_role("button", name="Log out")
        expect(logout).to_have_text("")
        name_box = who.locator(".nm").bounding_box()
        super_box = who.locator(".badge.super").bounding_box()
        assert abs(name_box["y"] + name_box["height"] / 2 - (super_box["y"] + super_box["height"] / 2)) < 4
        seg = page.locator("#themeseg")
        expect(page.get_by_text("Appearance", exact=True)).to_have_count(0)
        expect(seg.get_by_role("radio")).to_have_count(3)
        expect(seg).to_have_text("")
        assert seg.bounding_box()["y"] > logout.bounding_box()["y"]
    finally:
        ctx.close()


def test_reply_composer_refresh_area_cancel_and_activity_timeline(server, browser):
    human, agent = seed_users(server)
    area = call(server, "POST", "/api/areas", human, {"name": "Flow", "description": "d"})
    thread = make_thread(server, human, area["id"], "Flow thread", "op body")
    call(server, "POST", f"/api/threads/{thread['id']}/messages", human, {"body": "human note"})
    ctx, page = open_page(browser, server, human)
    try:
        page.goto(f"{server}/#/thread/{thread['id']}")
        # pin renders in place: no loading text appears
        page.evaluate("() => { window.flashes = 0; new MutationObserver(() => { if (document.querySelector('#main .loading')) window.flashes++; }).observe(document.getElementById('main'), {childList: true, subtree: true}); }")
        page.get_by_role("button", name="📌 Pin").click()
        expect(page.get_by_role("button", name="📌 Pinned")).to_be_visible()
        assert page.evaluate("window.flashes") == 0
        # the docked composer grows to ten lines, then scrolls
        page.get_by_role("button", name="Reply to thread").click()
        top = page.locator("#top-reply")
        top.fill("\n".join(f"line {i}" for i in range(13)))
        assert top.evaluate("e => e.getBoundingClientRect().height") == 214
        # a nested reply uses the same composer; Esc asks before it discards
        page.get_by_role("button", name="Reply", exact=True).last.click()
        nested = page.get_by_label("Reply to hanna", exact=True)
        expect(nested).to_be_focused()
        nested.fill("draft")
        nested.press("Escape")
        page.get_by_role("button", name="Discard").click()
        expect(page.locator(".compose.inline")).to_have_count(0)
        page.get_by_role("button", name="Reply", exact=True).last.click()
        page.get_by_label("Reply to hanna", exact=True).press("Escape")
        expect(page.locator(".compose.inline")).to_have_count(0)
        expect(page.locator("dialog.confirm")).to_have_count(0)
        # the area form has Cancel, with a confirm when it holds changes
        page.goto(f"{server}/#/area/flow")
        page.get_by_role("button", name="Edit area").click()
        page.get_by_label("Name").fill("Changed")
        page.get_by_role("button", name="Cancel", exact=True).click()
        page.get_by_role("button", name="Discard").click()
        expect(page.get_by_label("Name")).to_have_count(0)
        # activity: a timeline with the date once per day and a time per event
        page.goto(f"{server}/#/activity")
        rows = page.locator(".timeline .tl")
        expect(rows).to_have_count(4)
        expect(page.locator(".timeline .tl .day")).to_have_count(1)
        expect(page.locator(".timeline .tl time")).to_have_count(4)
        expect(page.locator(".timeline .card")).to_have_count(0)
    finally:
        ctx.close()


def test_search_highlights_term_and_spaces_results(server, browser):
    human, _ = seed_users(server)
    area = call(server, "POST", "/api/areas", human, {"name": "Lab", "description": "d"})
    thread = make_thread(server, human, area["id"], "Host", "first")
    for body in ("call with Bertrand today", "bertrand (x) again"):
        call(server, "POST", f"/api/threads/{thread['id']}/messages", human, {"body": body})
    ctx, page = open_page(browser, server, human)
    try:
        page.goto(f"{server}/#/search?q=bertrand")
        cards = page.locator("main .card")
        expect(cards).to_have_count(2)
        expect(page.locator("main mark")).to_have_text(["bertrand", "Bertrand"])
        # empty categories leave no gap; cards do not touch
        heading = page.get_by_role("heading", name="Messages")
        assert heading.bounding_box()["y"] - page.locator("main .ctl").bounding_box()["y"] < 60
        first, second = cards.nth(0).bounding_box(), cards.nth(1).bounding_box()
        assert second["y"] - (first["y"] + first["height"]) >= 6
        page.get_by_label("Include closed threads").check()
        expect(page).to_have_url(f"{server}/#/search?q=bertrand&include_closed=true")
        expect(page.locator("main mark")).to_have_count(2)
    finally:
        ctx.close()


def test_attention_closed_toggle_and_admin_badge_spacing(server, browser):
    human, _ = seed_users(server)
    ctx, page = open_page(browser, server, human)
    try:
        page.goto(f"{server}/#/attention")
        page.get_by_label("Include closed threads").check()
        expect(page).to_have_url(re.compile(r"#/attention\?.*include_closed=true"))
        page.goto(f"{server}/#/admin")
        card = page.locator("main .card", has=page.locator(".badge.super"))
        human_badge = card.locator(".badge.human").bounding_box()
        assert card.locator(".badge.super").bounding_box()["x"] - (human_badge["x"] + human_badge["width"]) >= 3
    finally:
        ctx.close()


def test_agent_sessions_render_update_live_and_keep_draft(server, browser):
    human, agent = seed_users(server)
    area = call(server, "POST", "/api/areas", human, {"name": "Sessions", "description": "d"})
    thread = make_thread(server, human, area["id"], "S", "hello @agentx")
    op = thread["op_message_id"]
    ctx, page = open_page(browser, server, human)
    try:
        page.goto(f"{server}/#/thread/{thread['id']}")
        row = page.locator(".asession")
        expect(row).to_contain_text("agentx")
        expect(row.locator(".schip")).to_have_text("Queued")
        page.get_by_role("button", name="More actions").click()
        page.get_by_role("menuitem", name="Edit").click()
        page.get_by_label("Edit message").fill("my draft")
        call(server, "POST", f"/api/messages/{op}/reactions", agent, {"emoji": "👀"})
        call(server, "POST", f"/api/messages/{op}/agent-activities", agent, {"kind": "action", "body": "Running **checks**"})
        expect(row.locator(".schip")).to_have_text("Working", timeout=8000)
        expect(row.locator(".alast")).to_contain_text("Running checks")
        expect(page.get_by_label("Edit message")).to_have_value("my draft")
        row.locator(".atoggle").click()
        expect(page.locator(".alog li")).to_have_count(1)
        call(server, "POST", f"/api/messages/{op}/reactions", agent, {"emoji": "✅"})
        expect(row.locator(".schip")).to_have_text("Done", timeout=8000)
        expect(row.get_by_role("button", name="Stop agentx")).to_have_count(0)
        # once done, the collapsed row shows no last event next to the chip
        page.get_by_text("Agents", exact=True).click()
        expect(row).not_to_contain_text("Running checks")
    finally:
        ctx.close()


def test_agent_card_click_toggles_log_and_esc_returns_to_area(server, browser):
    human, agent = seed_users(server)
    area = call(server, "POST", "/api/areas", human, {"name": "Esc Area", "description": "d"})
    thread = make_thread(server, human, area["id"], "Esc thread", "hello @agentx")
    op = thread["op_message_id"]
    call(server, "POST", f"/api/messages/{op}/reactions", agent, {"emoji": "👀"})
    call(server, "POST", f"/api/messages/{op}/agent-activities", agent, {"kind": "action", "body": "Checking logs"})
    ctx, page = open_page(browser, server, human)
    try:
        page.goto(f"{server}/#/areas")  # not Home: Esc then opens the thread's area
        page.goto(f"{server}/#/thread/{thread['id']}")
        # a click anywhere on the agents card shows the log, a second click hides it
        activity = page.get_by_text("Checking logs")
        expect(activity).to_have_count(1)
        page.get_by_text("Agents", exact=True).click()
        expect(activity).to_have_count(2)
        page.get_by_text("Agents", exact=True).click()
        expect(activity).to_have_count(1)
        # Esc in the reply box only hides the box; Esc outside a text field opens the area
        page.get_by_role("button", name="Reply to thread").click()
        page.keyboard.press("Escape")
        expect(page.get_by_role("button", name="Reply to thread")).to_be_visible()
        expect(page).to_have_url(re.compile(r"#/thread/"))
        page.keyboard.press("Escape")
        expect(page).to_have_url(f"{server}/#/area/esc-area")
        # a thread opened from Home goes back to Home
        page.goto(f"{server}/#/")
        page.get_by_role("link", name="Esc thread").click()
        expect(page.get_by_role("button", name="Reply to thread")).to_be_visible()
        page.keyboard.press("Escape")
        expect(page).to_have_url(f"{server}/#/")
    finally:
        ctx.close()


def test_agent_session_stop_button(server, browser):
    human, agent = seed_users(server)
    area = call(server, "POST", "/api/areas", human, {"name": "Sessions", "description": "d"})
    thread = make_thread(server, human, area["id"], "S", "hello @agentx")
    op = thread["op_message_id"]
    call(server, "POST", f"/api/messages/{op}/reactions", agent, {"emoji": "👀"})
    ctx, page = open_page(browser, server, human)
    try:
        page.goto(f"{server}/#/thread/{thread['id']}")
        page.get_by_role("button", name="Stop agentx").click()
        expect(page.locator(".asession .schip")).to_have_text("Stopping")
        expect(page.get_by_role("button", name="Stop agentx")).to_have_count(0)
        stopped = call(server, "POST", f"/api/messages/{op}/agent-activities", agent, {"kind": "thought", "body": "x"})
        assert stopped["stop_requested"]["by"]["username"] == "hanna"
    finally:
        ctx.close()


def test_agent_reply_appears_live_and_keeps_reply_draft(server, browser):
    human, agent = seed_users(server)
    area = call(server, "POST", "/api/areas", human, {"name": "Sessions", "description": "d"})
    thread = make_thread(server, human, area["id"], "S", "hello @agentx")
    op = thread["op_message_id"]
    ctx, page = open_page(browser, server, human)
    try:
        page.goto(f"{server}/#/thread/{thread['id']}")
        # Reply on the OP opens the thread composer: replies to the OP are top-level
        page.get_by_role("button", name="Reply", exact=True).first.click()
        page.locator("#top-reply").fill("half written")
        call(server, "POST", f"/api/messages/{op}/reactions", agent, {"emoji": "👀"})
        call(server, "POST", f"/api/threads/{thread['id']}/messages", agent, {"body": "agent answer"})
        call(server, "POST", f"/api/messages/{op}/reactions", agent, {"emoji": "✅"})
        expect(page.locator(".asession .schip")).to_have_text("Done", timeout=8000)
        expect(page.get_by_text("agent answer")).to_have_count(1)
        expect(page.get_by_role("link", name="reply")).to_be_visible()
        expect(page.locator(f"#m{op} .rx")).to_have_text(["\u2705 1"])
        expect(page.locator("#top-reply")).to_have_value("half written")
    finally:
        ctx.close()


def test_delete_in_another_tab_shows_live_while_agent_works(server, browser):
    human, agent = seed_users(server)
    area = call(server, "POST", "/api/areas", human, {"name": "Sessions", "description": "d"})
    thread = make_thread(server, human, area["id"], "S", "hello @agentx")
    op = thread["op_message_id"]
    mine = call(server, "POST", f"/api/threads/{thread['id']}/messages", human, {"body": "soon gone"})
    call(server, "POST", f"/api/messages/{op}/reactions", agent, {"emoji": "👀"})
    ctx, page = open_page(browser, server, human)
    try:
        page.goto(f"{server}/#/thread/{thread['id']}")
        card = page.locator(f"#m{mine['id']}")
        expect(card).to_contain_text("soon gone")
        call(server, "DELETE", f"/api/messages/{mine['id']}", human)
        expect(card).to_contain_text("message deleted", timeout=8000)
        expect(card).not_to_contain_text("soon gone")
        expect(card.get_by_role("button", name="More actions")).to_have_count(0)
    finally:
        ctx.close()


def test_late_thread_response_does_not_start_polling(server, browser):
    human, agent = seed_users(server)
    area = call(server, "POST", "/api/areas", human, {"name": "Sessions", "description": "d"})
    old = make_thread(server, human, area["id"], "Old", "hello @agentx")
    other = make_thread(server, human, area["id"], "Other", "plain")
    ctx, page = open_page(browser, server, human)
    polled = []
    held = []

    def slow(route):
        held.append(route)

    try:
        page.goto(f"{server}/#/")
        page.on("request", lambda r: polled.append(r.url) if f"/api/threads/{old['id']}" in r.url and r.method == "GET" else None)
        page.route(f"**/api/threads/{old['id']}", slow)
        page.evaluate(f"location.hash = '#/thread/{old['id']}'")
        while not held:
            page.wait_for_timeout(50)
        page.evaluate(f"location.hash = '#/thread/{other['id']}'")
        expect(page.locator("h1.ttitle")).to_have_text("Other")
        held[0].continue_()
        page.wait_for_timeout(7000)
        assert len(polled) == 1
    finally:
        ctx.close()


def seed_attention(server, count):
    human, agent = seed_users(server)
    area = call(server, "POST", "/api/areas", human, {"name": "Inbox", "description": "d"})
    thread = make_thread(server, agent, area["id"], "Pings", "first ping @hanna")
    for i in range(1, count):
        call(server, "POST", f"/api/threads/{thread['id']}/messages", agent, {"body": f"ping {i + 1} @hanna"})
    return human, agent, thread


def test_attention_badge_follows_thread_reactions_and_new_mentions(server, browser):
    human, agent, thread = seed_attention(server, 2)
    call(server, "POST", f"/api/threads/{thread['id']}/messages", agent, {"body": "no mention, no badge"})
    ctx = browser.new_context(reduced_motion="reduce")
    page = ctx.new_page()
    try:
        page.clock.install()
        login(page, server, human)
        nav = page.get_by_role("navigation", name="Main")
        expect(nav.get_by_role("link", name="Attention, 2 need your attention")).to_be_visible()
        page.goto(f"{server}/#/thread/{thread['id']}")
        expect(page.get_by_text("ping 2")).to_be_visible()
        page.get_by_role("button", name="☺ React").first.click()
        page.get_by_role("menuitem", name="React 👍").click()
        expect(nav.get_by_role("link", name="Attention, 1 need your attention")).to_be_visible()
        # a new mention from another user shows without navigation
        call(server, "POST", f"/api/threads/{thread['id']}/messages", agent, {"body": "ping 3 @hanna"})
        page.clock.run_for(16000)
        expect(nav.get_by_role("link", name="Attention, 2 need your attention")).to_be_visible()
    finally:
        ctx.close()


def test_attention_badge_ignores_a_late_older_count(server, browser):
    human, _, thread = seed_attention(server, 2)
    ctx, page = open_page(browser, server, human)
    held = []
    try:
        page.goto(f"{server}/#/thread/{thread['id']}")
        nav = page.get_by_role("navigation", name="Main")
        expect(nav.get_by_role("link", name="Attention, 2 need your attention")).to_be_visible()
        # hold the next count request: it answers "2" after the newer request answers "1"
        def hold_first(route):
            if held:
                route.continue_()
            else:
                held.append((route, route.fetch()))

        page.route("**/api/attention?status=unacknowledged*", hold_first)
        page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
        wait_until_held(page, held)
        page.get_by_role("button", name="☺ React").first.click()
        page.get_by_role("menuitem", name="React 👍").click()
        expect(nav.get_by_role("link", name="Attention, 1 need your attention")).to_be_visible()
        route, stale = held[0]
        route.fulfill(response=stale)
        page.wait_for_timeout(500)
        expect(nav.get_by_role("link", name="Attention, 1 need your attention")).to_be_visible()
    finally:
        ctx.close()


def test_attention_mark_all_asks_first_and_updates_live(server, browser):
    human, _, _ = seed_attention(server, 3)
    ctx, page = open_page(browser, server, human)
    try:
        page.goto(f"{server}/#/attention")
        nav_link = page.get_by_role("navigation", name="Main").get_by_role("link", name="Attention")
        expect(page.get_by_role("button", name="Mark as seen")).to_have_count(3)
        expect(nav_link.locator(".navcount")).to_have_text("3")
        page.get_by_role("button", name="Mark all seen").click()
        dialog = page.get_by_role("dialog", name="Mark all as seen?")
        expect(dialog).to_contain_text("3 items")
        dialog.get_by_role("button", name="Cancel").click()
        expect(dialog).to_have_count(0)
        expect(page.get_by_role("button", name="Mark as seen")).to_have_count(3)
        page.get_by_role("button", name="Mark all seen").click()
        page.get_by_role("dialog", name="Mark all as seen?").get_by_role("button", name="Mark all seen").click()
        expect(page.get_by_text("Nothing here.")).to_be_visible()
        expect(page.get_by_role("button", name="Mark as seen")).to_have_count(0)
        expect(nav_link.locator(".navcount")).to_have_count(0)
        page.get_by_label("Status").select_option("acknowledged")
        expect(page.get_by_text("ping 3")).to_be_visible()
    finally:
        ctx.close()


def test_attention_load_more_after_mark_one_keeps_last_item(server, browser):
    human, _, _ = seed_attention(server, 101)
    ctx, page = open_page(browser, server, human)
    try:
        page.goto(f"{server}/#/attention")
        expect(page.get_by_role("button", name="Mark as seen")).to_have_count(100)
        page.get_by_role("button", name="Mark as seen").first.click()
        expect(page.get_by_role("button", name="Mark as seen")).to_have_count(99)
        page.get_by_role("button", name="Load more").click()
        expect(page.get_by_role("button", name="Mark as seen")).to_have_count(100)
        expect(page.get_by_text("first ping")).to_be_visible()
    finally:
        ctx.close()


def test_attention_load_more_after_agent_leaves_and_reenters_filter(server, browser):
    human, agent = seed_users(server)
    area = call(server, "POST", "/api/areas", human, {"name": "Inbox", "description": "d"})
    thread = make_thread(server, human, area["id"], "Asks", "@agentx first ask")
    for i in range(1, 101):
        call(server, "POST", f"/api/threads/{thread['id']}/messages", human, {"body": f"@agentx ask {i + 1}"})
    ctx, page = open_page(browser, server, agent)
    try:
        page.goto(f"{server}/#/attention")
        cards = page.locator(".list .card")
        expect(cards).to_have_count(100)
        card = cards.first
        card.get_by_role("button", name="React", exact=False).click()
        page.get_by_role("menuitem", name="React 👀").click()
        expect(card.get_by_role("button", name="👀 1")).to_be_visible()
        card.get_by_role("button", name="👀 1").click()
        expect(card.get_by_role("button", name="👀 1")).to_have_count(0)
        page.get_by_role("button", name="Load more").click()
        expect(cards).to_have_count(101)
        expect(page.get_by_text("first ask")).to_have_count(1)
        expect(page.get_by_text("ask 101")).to_have_count(1)
    finally:
        ctx.close()


def test_attention_mark_one_removes_or_keeps_by_filter(server, browser):
    human, _, _ = seed_attention(server, 2)
    ctx, page = open_page(browser, server, human)
    try:
        page.goto(f"{server}/#/attention")
        nav_link = page.get_by_role("navigation", name="Main").get_by_role("link", name="Attention")
        expect(nav_link.locator(".navcount")).to_have_text("2")
        page.get_by_role("button", name="Mark as seen").first.click()
        expect(page.get_by_role("button", name="Mark as seen")).to_have_count(1)
        expect(nav_link.locator(".navcount")).to_have_text("1")
        page.get_by_label("Status").select_option("all")
        expect(page.get_by_role("button", name="Mark as seen")).to_have_count(1)
        page.get_by_role("button", name="Mark as seen").click()
        expect(page.get_by_role("button", name="Mark as seen")).to_have_count(0)
        expect(page.get_by_text("attention: acknowledged")).to_have_count(2)
        expect(nav_link.locator(".navcount")).to_have_count(0)
    finally:
        ctx.close()


def test_attention_check_reaction_updates_list(server, browser):
    human, _, _ = seed_attention(server, 1)
    ctx, page = open_page(browser, server, human)
    try:
        page.goto(f"{server}/#/attention")
        nav_link = page.get_by_role("navigation", name="Main").get_by_role("link", name="Attention")
        expect(nav_link.locator(".navcount")).to_have_text("1")
        page.get_by_role("button", name="React", exact=False).first.click()
        page.get_by_role("menuitem", name="React ✅").click()
        expect(page.get_by_text("Nothing here.")).to_be_visible()
        expect(nav_link.locator(".navcount")).to_have_count(0)
    finally:
        ctx.close()


def test_mark_as_seen_button_only_on_attention_page(server, browser):
    human, _, thread = seed_attention(server, 2)
    ctx, page = open_page(browser, server, human)
    try:
        page.goto(f"{server}/#/attention")
        expect(page.get_by_role("button", name="Mark as seen").first).to_be_visible()
        page.goto(f"{server}/#/thread/{thread['id']}")
        expect(page.get_by_text("ping 2")).to_be_visible()
        expect(page.get_by_role("button", name="Mark as seen")).to_have_count(0)
        expect(page.get_by_role("button", name="Mark all seen")).to_have_count(0)
    finally:
        ctx.close()


def test_c_shortcut_and_create_thread_palette_action(server, browser):
    human, _ = seed_users(server)
    area = call(server, "POST", "/api/areas", human, {"name": "Lab", "description": "d"})
    thread = make_thread(server, human, area["id"], "Shortcut test")
    ctx, page = open_page(browser, server, human)
    try:
        sheet = page.get_by_role("dialog", name="New thread")
        page.goto(f"{server}/#/thread/{thread['id']}")
        expect(page.locator("h1.ttitle")).to_have_text("Shortcut test")
        # typing "c" in a text field types it, and opens nothing
        page.get_by_role("button", name="Reply to thread").click()
        top = page.locator("#top-reply")
        top.click()
        page.keyboard.type("c")
        expect(top).to_have_value("c")
        expect(sheet).to_have_count(0)
        # outside a text field "c" opens the new thread sheet; Cmd/Ctrl+C does not
        page.locator("h1.ttitle").click()
        page.keyboard.press("ControlOrMeta+c")
        expect(sheet).to_have_count(0)
        page.keyboard.press("c")
        expect(sheet).to_be_visible()
        page.keyboard.press("Escape")
        expect(sheet).to_have_count(0)
        # the palette action is "Create thread", so "create" finds it
        page.keyboard.press("ControlOrMeta+k")
        page.get_by_role("combobox", name="Search threads, areas, screens and actions").fill("create")
        page.get_by_role("option", name=re.compile("^Create thread")).first.click()
        expect(sheet).to_be_visible()
    finally:
        ctx.close()


def test_mark_as_seen_sits_top_left_and_shows_on_hover(server, browser):
    human, _, _ = seed_attention(server, 1)
    ctx, page = open_page(browser, server, human)
    try:
        page.goto(f"{server}/#/attention")
        button = page.get_by_role("button", name="Mark as seen")
        card = page.locator(".card.attncard").first
        expect(card).to_be_visible()
        page.mouse.move(0, 0)  # the login click can leave the pointer over the card
        expect(button).to_have_css("opacity", "0")
        card.hover()
        expect(button).to_have_css("opacity", "1")
        b, c = button.bounding_box(), card.bounding_box()
        assert b["x"] < c["x"] and b["y"] < c["y"]
        votes = card.locator(".votes, .vote, [aria-label^='Vote']").first.bounding_box()
        assert b["x"] + b["width"] < votes["x"]
    finally:
        ctx.close()


def test_inline_reply_mention_popup_is_not_clipped(server, browser):
    human, agent = seed_users(server)
    area = call(server, "POST", "/api/areas", human, {"name": "Clip", "description": "d"})
    thread = make_thread(server, human, area["id"], "Clip thread", "op body")
    call(server, "POST", f"/api/threads/{thread['id']}/messages", agent, {"body": "a reply"})
    ctx, page = open_page(browser, server, human)
    try:
        page.goto(f"{server}/#/thread/{thread['id']}")
        card = page.locator(".msgbody").filter(has_text="a reply")
        card.hover()
        card.get_by_role("button", name="Reply", exact=True).click()
        reply = page.get_by_label("Reply to agentx")
        reply.fill("hi @agent")
        # the popup opens above the inline form: a click must reach the option
        page.get_by_role("option", name=re.compile("agentx")).click(timeout=3000)
        expect(reply).to_have_value("hi @agentx ")
    finally:
        ctx.close()


def test_delete_own_message_keeps_card_and_replies(server, browser):
    human, agent = seed_users(server)
    area = call(server, "POST", "/api/areas", human, {"name": "Deletes", "description": "d"})
    thread = make_thread(server, human, area["id"], "Delete me", "original words")
    call(server, "POST", f"/api/threads/{thread['id']}/messages", agent, {"body": "agent reply stays"})
    ctx, page = open_page(browser, server, human)
    actx, apage = open_page(browser, server, agent)
    try:
        apage.goto(f"{server}/#/thread/{thread['id']}")
        expect(apage.get_by_text("agent reply stays")).to_be_visible()
        # an author sees the More actions menu only on their own message
        expect(apage.get_by_role("button", name="More actions")).to_have_count(1)

        page.goto(f"{server}/#/thread/{thread['id']}")
        expect(page.get_by_role("button", name="More actions")).to_have_count(2)
        op = page.locator(".msg.op > .msgbody")
        op.get_by_role("button", name="More actions").click()
        page.get_by_role("menuitem", name="Delete").click()
        page.get_by_role("button", name="Cancel").click()
        expect(page.get_by_text("original words")).to_be_visible()
        expect(page.get_by_text("message deleted")).to_have_count(0)

        op.get_by_role("button", name="More actions").click()
        page.get_by_role("menuitem", name="Delete").click()
        page.get_by_role("dialog").get_by_role("button", name="Delete", exact=True).click()
        deleted = page.get_by_text("message deleted")
        expect(deleted).to_be_visible()
        expect(deleted).to_have_css("font-style", "italic")
        expect(page.get_by_text("original words")).to_have_count(0)
        expect(page.get_by_role("button", name="More actions")).to_have_count(1)
        expect(op.get_by_role("button", name="More actions")).to_have_count(0)
        expect(page.get_by_role("button", name="Vote +1")).to_have_count(1)
        expect(page.get_by_text("agent reply stays")).to_be_visible()
        expect(page.get_by_role("heading", name="Delete me")).to_be_visible()
        page.reload()
        expect(page.get_by_text("message deleted")).to_be_visible()
        expect(page.get_by_text("original words")).to_have_count(0)
    finally:
        ctx.close()
        actx.close()


def test_thread_shows_references(server, browser):
    human, _ = seed_users(server)
    area = call(server, "POST", "/api/areas", human, {"name": "Refs", "description": "d"})
    a = make_thread(server, human, area["id"], "Target thread")
    b = make_thread(server, human, area["id"], "Pointing thread", f"see #{a['id']}")
    ctx, page = open_page(browser, server, human)
    try:
        page.goto(f"{server}/#/thread/{a['id']}")
        toggle = page.get_by_role("button", name="References (1)")
        expect(toggle).to_have_attribute("aria-expanded", "true")
        link = page.get_by_role("main").get_by_role("link", name="Pointing thread")
        expect(link).to_be_visible()
        expect(link).to_have_attribute("href", re.compile(rf"#/thread/{b['id']}\?m=\d+$"))
        toggle.click()
        expect(toggle).to_have_attribute("aria-expanded", "false")
        expect(link).to_be_hidden()
        toggle.click()
        expect(link).to_be_visible()
        page.get_by_role("button", name="Toggle inspector").click()
        expect(page.get_by_role("heading", name="References", exact=True)).to_be_visible()
        expect(page.get_by_role("complementary").get_by_role("link", name="Pointing thread")).to_be_visible()

        page.goto(f"{server}/#/thread/{b['id']}")
        expect(page.get_by_role("heading", name="Pointing thread")).to_be_visible()
        expect(page.get_by_role("button", name=re.compile("^References"))).to_have_count(0)
        expect(page.get_by_text("No other thread links here.")).to_be_visible()
    finally:
        ctx.close()
