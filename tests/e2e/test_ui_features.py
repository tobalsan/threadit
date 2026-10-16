import base64
import re
import time

from playwright.sync_api import expect
from test_ui_integration import call, login, make_thread, seed_users

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


def open_page(browser, server, token):
    ctx = browser.new_context()
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
        expect(page.locator(".card.thread a.t strong")).to_have_text("Bold")
        expect(page.locator(".card.thread a.t i")).to_have_count(0)

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
        page.get_by_role("button", name="Edit", exact=True).first.click()
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
        form = page.locator("form.card").filter(has_text="New thread in")
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
            "() => { const b = document.querySelector('.msgbody'); return [...b.children].map(c => c.className).slice(0, 4); }"
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
        reply = page.locator("form.card").filter(has_text="Add top-level reply")
        page.fill("#top-reply", "second")
        reply.locator("input[type=file]").set_input_files(
            [{"name": "again.png", "mimeType": "image/png", "buffer": PNG}]
        )
        reply.get_by_role("button", name="Post", exact=True).click()
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
        # only own messages have an Edit button
        expect(page.get_by_role("button", name="Edit", exact=True)).to_have_count(1)
        page.get_by_role("button", name="Edit", exact=True).click()
        page.get_by_label("Edit message").fill("changed **body**")
        page.get_by_role("button", name="Save edit").click()
        msg = page.locator(".msgbody").first
        expect(msg.locator(".md strong")).to_have_text("body")
        expect(msg.get_by_text("(modified)")).to_be_visible()
        assert "Edited" in msg.get_by_text("(modified)").get_attribute("title")
        # cancel leaves text untouched
        page.get_by_role("button", name="Edit", exact=True).click()
        page.get_by_label("Edit message").fill("nope")
        page.get_by_role("button", name="Cancel").click()
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
        expect(apage.get_by_role("button", name="Edit", exact=True)).to_have_count(1)  # own message only
        # list row shows it too
        page.goto(f"{server}/#/area/edits")
        expect(page.locator(".card.thread").get_by_text("(modified)")).to_be_visible()

        # closed thread: edit buttons disabled
        call(server, "POST", f"/api/threads/{thread['id']}/close", human, {"reason": "completed"})
        page.goto(f"{server}/#/thread/{thread['id']}")
        expect(page.get_by_role("button", name="Edit", exact=True).first).to_be_disabled()
        expect(page.get_by_role("button", name="Edit title")).to_be_disabled()
        assert other["author"]["username"] == "agentx"
    finally:
        ctx.close()
        actx.close()


def test_symmetric_vote_buttons(server, browser):
    human, _ = seed_users(server)
    area = call(server, "POST", "/api/areas", human, {"name": "Votes", "description": "d"})
    thread = make_thread(server, human, area["id"], "Vote thread")
    ctx, page = open_page(browser, server, human)
    try:
        page.goto(f"{server}/#/thread/{thread['id']}")
        actions = page.locator(".msgbody .actions").first
        labels = actions.locator("button").all_inner_texts()
        assert labels == ["-5", "-1", "+1", "+5"]
        page.get_by_role("button", name="Vote -5", exact=True).first.click()
        expect(page.get_by_label("score -5").first).to_be_visible()
        page.get_by_role("button", name="Vote -1", exact=True).first.click()
        expect(page.get_by_text("importance (OP score): -6")).to_be_visible()
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
        page.goto(f"{server}/#/")
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


def test_agent_registration_requires_description(server, browser):
    ctx = browser.new_context()
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
        page.get_by_role("button", name="Edit", exact=True).click()
        page.get_by_label("Edit message").fill("my draft")
        page.get_by_role("button", name="Vote +1").first.click()
        expect(page.get_by_label("score 1").first).to_be_visible()
        expect(page.get_by_label("Edit message")).to_have_value("my draft")
    finally:
        ctx.close()


def test_file_picker_disabled_during_upload(server, browser):
    human, _ = seed_users(server)
    area = call(server, "POST", "/api/areas", human, {"name": "Up", "description": "d"})
    ctx, page = open_page(browser, server, human)
    try:
        page.route("**/api/attachments?*", lambda route: (time.sleep(0.5), route.continue_()))
        page.goto(f"{server}/#/area/up")
        page.get_by_role("button", name="New thread").click()
        page.get_by_label("Title").fill("with files")
        page.get_by_label("Opening post (use @username to notify an agent)").fill("body")
        picker = page.get_by_label("Attach files (max 10, 10 MB each)")
        picker.set_input_files([
            {"name": "a.png", "mimeType": "image/png", "buffer": PNG},
            {"name": "b.png", "mimeType": "image/png", "buffer": PNG},
        ])
        page.get_by_role("button", name="Create thread").click()
        expect(picker).to_be_disabled()
        expect(page.get_by_role("button", name="Remove a.png")).to_be_disabled()
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
        form = page.locator("form.card").filter(has_text="Add top-level reply")
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
        form.get_by_role("button", name="Post").click()
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
        top = page.get_by_label("Add top-level reply (@username to notify an agent)")
        top.fill("half-written reply")
        page.reload()
        expect(top).to_have_value("half-written reply")
        page.get_by_role("button", name="Post").click()
        expect(page.locator(".msg").filter(has_text="half-written reply")).to_have_count(1)
        page.reload()
        expect(top).to_have_value("")

        page.goto(f"{server}/#/area/drafts")
        page.get_by_role("button", name="New thread").click()
        page.fill("#th-title", "draft title")
        page.fill("#th-body", "draft body")
        page.reload()
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
        page.get_by_role("button", name="Cancel").click()
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
        top = page.get_by_label("Add top-level reply (@username to notify an agent)")
        top.fill("sent with keys")
        top.press("Meta+Enter")
        expect(page.locator(".msg").filter(has_text="sent with keys")).to_have_count(1)
        expect(top).to_have_value("")
        page.locator(".msg").filter(has_text="sent with keys").get_by_role("button", name="Edit").click()
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
    ctx = browser.new_context(viewport={"width": 1280, "height": 800})
    page = ctx.new_page()
    login(page, server, human)
    try:
        page.goto(f"{server}/#/area/side?state=all")
        side = page.get_by_role("complementary", name="Area description")
        expect(side.locator("strong")).to_have_text("Rules")
        row = page.locator(".card.thread").filter(has_text="vote me")
        assert side.bounding_box()["x"] > row.bounding_box()["x"] + row.bounding_box()["width"] - 1

        page.get_by_role("button", name="Upvote vote me").click()
        expect(row.locator(".imp")).to_contain_text("1")
        page.get_by_role("button", name="Upvote vote me").click()
        page.get_by_role("button", name="Downvote vote me").click()
        expect(row.locator(".imp span")).to_have_text("1")
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
        page.goto(f"{server}/#/area/rank")
        titles = page.locator(".card.thread a.t")
        expect(titles).to_have_text(["top one", "low one"])
        top_imp = page.locator(".card.thread").filter(has_text="top one").locator(".imp")
        top_score = top_imp.locator("span")
        expect(top_imp).to_have_class(re.compile("sc-warm"))
        low_imp = page.locator(".card.thread").filter(has_text="low one").locator(".imp")
        low_score = low_imp.locator("span")
        expect(low_imp).to_have_class("imp sc ")
        up = page.get_by_role("button", name="Upvote low one")
        up.click()
        expect(low_score).to_have_text("1")
        up.click()
        expect(low_score).to_have_text("2")
        expect(titles).to_have_text(["top one", "low one"])  # not yet: debounce pending
        expect(titles).to_have_text(["low one", "top one"], timeout=5000)
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
