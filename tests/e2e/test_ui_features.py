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
        expect(page.locator(".li.thread").get_by_text("(modified)")).to_be_visible()

        # closed thread: edit buttons disabled
        call(server, "POST", f"/api/threads/{thread['id']}/close", human, {"reason": "completed"})
        page.goto(f"{server}/#/thread/{thread['id']}")
        expect(page.get_by_role("button", name="Edit", exact=True)).to_have_count(0)
        expect(page.get_by_role("button", name="Edit title")).to_have_count(0)
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
        top = page.get_by_label("Add top-level reply (@username to notify an agent)")
        top.fill("half-written reply")
        page.reload()
        expect(top).to_have_value("half-written reply")
        page.get_by_role("button", name="Send").click()
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
        page.get_by_role("button", name="Cancel", exact=True).click()
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
    for text in ("reply one", "reply two"):
        call(server, "POST", f"/api/threads/{thread['id']}/messages", human, {"body": text})
    call(server, "POST", f"/api/threads/{thread['id']}/messages", human, {"body": "op child", "parent_id": thread["op_message_id"]})
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
    ctx = browser.new_context(color_scheme="light")
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
    call(server, "POST", f"/api/threads/{mentioned['id']}/messages", human, {"body": "a reply"})
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
        first = page.locator(".li.thread").nth(1).bounding_box()
        second = page.locator(".li.thread").nth(2).bounding_box()
        assert 7 <= second["y"] - (first["y"] + first["height"]) <= 9
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
        page.get_by_role("button", name="Post reply").click()
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
        top = page.get_by_label("Add top-level reply (@username to notify an agent)")
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

        # closed thread: the composer is disabled
        call(server, "POST", f"/api/threads/{thread['id']}/close", human, {"reason": "completed"})
        page.reload()
        expect(page.get_by_label("Add top-level reply (@username to notify an agent)")).to_be_disabled()
        expect(page.get_by_role("button", name="Send")).to_be_disabled()
        expect(page.get_by_role("button", name="Toggle attachments")).to_be_disabled()
        expect(page.get_by_placeholder("Thread closed: reopen to reply")).to_be_visible()
    finally:
        ctx.close()


def test_inspector_toggle_sections_and_outside_click(server, browser):
    human, agent = seed_users(server)
    area = call(server, "POST", "/api/areas", human, {"name": "Insp", "description": "Area **rules** here"})
    thread = make_thread(server, human, area["id"], "Inspect me", "hello @agentx")
    call(server, "POST", f"/api/threads/{thread['id']}/messages", agent, {"body": "reply from agent"})
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
        expect(page.get_by_role("option").nth(1)).to_have_attribute("aria-selected", "true")
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
        page.keyboard.press("ControlOrMeta+k")
        page.get_by_role("combobox", name="Search threads, areas, screens and actions").fill("new thread in beta")
        page.get_by_role("option", name=re.compile("^New thread in Beta")).click()
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
