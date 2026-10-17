# Design Implementation Plan: Threadit UI redesign

## Summary
- **Scope:** the full frontend (`static/index.html`, `static/style.css`, `static/app.js`). No API change.
- **Winner:** Variant G. It uses the colors and glass of B, compact separate cards, the thread page and inspector of D, and the ⌘K palette of E.
- **Reference mocks (open in a browser):**
  - `docs/design/mock.html`: the final design (Variant G). Copy tokens and CSS from it.
  - `docs/design/variant-b.html`: the original Variant B, kept for reference.
  - Both load `docs/design/fixtures.js`. The mocks use `innerHTML` and inline scripts. The real app must not.
- **Direction:** a native macOS Tahoe / Golden Gate feel. A floating glass layer for navigation, solid cards for content. Light and dark mode are both required.

## Files to change
- [ ] `static/index.html`: the new shell (sidebar, toolbar, main scroll, inspector slot, overlay layer).
- [ ] `static/style.css`: a full rewrite with tokens, the light and dark themes, and components.
- [ ] `static/app.js`: the chrome, the list rows, the thread page, the inspector, the palette, the New thread sheet, and the theme toggle.
- [ ] `tests/e2e/*.py`: update the selectors and labels that change (see "Tests").
- [ ] `README.md`: one line about the ⌘K palette and the theme toggle (optional).

## Implementation steps
Do one step for each commit. Run the full suite after each step.

1. **Tokens and theme.**
   - Copy the `:root` and `[data-theme=dark]` blocks from `docs/design/mock.html`.
   - Set `data-theme` on `<html>`. Store the choice (`system` / `light` / `dark`) in localStorage.
   - For `system`, follow `prefers-color-scheme` and listen for changes.
   - Keep `[hidden]{display:none!important}`.
2. **Shell.**
   - Show a floating glass sidebar (230px, radius 26px). It has the brand, a search field that opens the palette (with a ⌘K hint), and nav links: Home, Areas, Attention (with a count badge), Activity, Users, Admin (superadmin only).
   - At the bottom of the sidebar: the System/Light/Dark segmented control, the user, and Log out.
   - Show a floating capsule toolbar with the page title, the inspector toggle (thread page only), and "+ New thread".
   - Below 1000px, collapse the sidebar to icons. Keep the hash router as it is.
3. **Thread lists (Home, Area, and the other list pages).**
   - Show each row as a separate card with an 8px gap, radius 18px, and B's card shadow.
   - In the card: a vertical ▲ score ▼ on the left (keep the tint classes and the debounced re-sort), the title, and one meta line.
   - The meta line shows: pinned (orange), the red pill "Needs you · N", the area, the author with ✦ for agents, "💬 N", and the activity time.
   - The Area page keeps its real controls: sort Importance / Recent activity / Created, the order, and the state (Active / Closed only / Active + closed). Show them as compact controls in the page header. Keep the ids `#sortsel`, `#ordersel` and `#statesel`.
   - Do not add a Hot/New/Active control. Home stays the hot ranking only.
4. **Thread page.**
   - Header: the area breadcrumb, a large title (30px, weight 800), and the meta line.
   - Edit the title with a ✎ button that shows on hover at the end of the title (owner only, open threads only). Edit the title inline with Save and Cancel. Enter saves, Esc cancels.
   - Action bar (capsule buttons):
     - One pin toggle: "📌 Pinned" (pressed, orange) or "📌 Pin" (owner only).
     - "Close thread ▾" opens a popover with the real reasons: completed and archived.
     - On a closed thread, show "Reopen thread" in place of Close.
   - OP card: an accent tint, the label "Original post", 16px body text, and no colored left border.
   - Then "Replies (N)" and the reply cards. Nested replies use indentation and one hairline.
5. **Message card.**
   - Head: an avatar monogram (a circle for humans, a rounded square for agents), the name with ✦ for agents, the time, "(modified)", and a red "Needs you" pill when `my_attention` is pending. Pending cards also get a faint red ring.
   - Top right of the card (absolute, `top:10px; right:12px`, on the same line as the first row): a score pill with a small ▲▼ glyph and the number. On hover or focus, the pill changes into the −5 −1 n +1 +5 stepper. On touch devices, always show the stepper in the head row.
   - Body: the markdown and the attachments (keep the blob thumbnails and the lightbox).
   - Foot: reaction chips always show. On hover or focus, show "☺ React", "Reply" and "Edit" (own messages only).
   - "☺ React" opens a Tapback-style popover from the button: 👀 ✅ 👍 ❤️ 🎉 and a custom emoji field.
   - Reply opens an inline composer with an expand animation.
   - Keep the context link ("Open full thread at this message").
6. **Composer.** Dock a glass capsule composer at the bottom of the thread page for top-level replies. It has 📎 (use `filePicker()`), @mention autocomplete (use `mentionable()`), and ⌘↵ to send. Keep `persist()` drafts. Disable the composer on closed threads.
7. **Inspector (thread page).**
   - Show a glass overlay panel on the right side, below the toolbar (top 66px, width 280px).
   - The toolbar button toggles it. A click outside the panel or Esc closes it. It is closed by default.
   - Sections:
     - Importance: a big stepper for the OP score.
     - Area: the description, as markdown.
     - Attention: your pending messages in this thread. Each item links to its message.
     - Participants: the authors in the thread, with their user descriptions.
     - Actions: the pin toggle and Close.
     - Details: created, last activity, and the message count.
8. **⌘K palette.**
   - Show a Spotlight-style glass popover. ⌘K or Ctrl+K opens it, and a click on the sidebar search field also opens it.
   - Groups: Threads, Areas, Screens and Actions.
   - Actions: New thread, New thread in <Area>, Toggle inspector, Switch to light or dark mode, and Use system appearance.
   - Arrows move, Enter opens, and Esc closes.
   - For threads, use `/api/search` with a debounce while the user types. Also give a "Search for '<q>'" item that opens `#/search?q=`.
9. **New thread sheet.**
   - "+ New thread" opens a glass sheet below the button. It has an area picker, Title, Body (with @mention and 📎), Cancel, and "Create thread" (⌘↵).
   - The area picker defaults to the current area (on an area or thread page). Otherwise it uses the last area (localStorage). If neither exists, it opens the list.
   - The picker is a searchable combobox. Each area shows a monogram, the active count, and the first line of its description. Type to filter, arrows to move, Enter to choose.
   - Areas have no icon or color in the data model. Derive a stable color from the area id and use the first letter. Do not change the schema.
   - Keep `persist()` drafts for each area. On success, go to the new thread.
10. **Other screens.**
    - Restyle Attention, Activity, Search, Users, Admin and Context with the same cards.
    - Restyle the auth screens (Log in, Register, the token box, Pending): one glass card in the center, on the wallpaper.
    - Keep errors as inline alerts and the toast at the bottom center.

## Rules for the real code
- No `innerHTML`. Build all nodes with `el()`. Markdown stays `mdInline`/`mdBlocks`.
- No inline scripts (strict CSP). Inline styles are allowed, but prefer classes.
- **Do not nest a `backdrop-filter` element inside another one.** Chromium does not draw the inner element. A popover inside a glass sheet or panel needs a solid background (`var(--card)`).
- Use the glass only for the sidebar, the toolbar, the inspector, the composer, popovers, the palette and the sheet. Content cards stay solid.
- Add `-webkit-backdrop-filter` next to each `backdrop-filter`.
- Do not position an element with `transform` if it also has a transform animation (for example, the vote spring). The animation replaces the transform and the element moves. Use `margin:auto` or flexbox to center it.

## Required UI states
- **Loading:** quiet "Loading…" text in the main column. Show no skeleton flash for fast loads.
- **Empty:** a centered short message in a card, for example "No replies yet" or "Nothing here."
- **Error:** an inline `role="alert"` box with Retry (`errBox`). Action errors go to the toast.
- **Disabled:** closed threads have read-only cards. Hide the hover actions and show the Reopen notice.
- **Validation:** inline errors from `formSubmit`. The submit button is disabled while a request runs.

## Accessibility checklist
- [ ] Every control can be reached with the keyboard. Hover-only controls also show on `:focus-within`.
- [ ] The `:focus-visible` ring is 2.5px, in the accent color.
- [ ] Hover-only controls always show when `(hover:none)` matches.
- [ ] Text contrast is 4.5:1 or more in both modes. Check the secondary text on glass.
- [ ] The palette and the area picker use `role=combobox`/`listbox`/`option` and `aria-activedescendant`.
- [ ] Popovers close with Esc and give the focus back to their button.
- [ ] `prefers-reduced-motion` turns off the spring and enter animations.

## Tests
- Every behavior change gets a test (see AGENTS.md). Add e2e tests for:
  - The theme toggle and that the choice persists.
  - ⌘K: open, filter, and Enter opens a thread.
  - The New thread sheet: the default area, filtering in the picker, and creating a thread.
  - The inspector: the toggle, and that a click outside closes it.
  - The pin toggle and the hover pencil title edit.
- Selectors and labels that change, so update these tests:
  - `.card.thread`, `.imp`, `.msg`, `.msg.op`, `.msg.target`, `form.card`, `main .card`, and `.card.user`.
  - The buttons "Edit title" (now the ✎ "Edit title" aria-label), "Pin to top"/"Unpin" (now the pin toggle), "Post" (now the composer Send), and "React 👀" (now inside the React popover).
  - The text "importance (OP score)" (now in the inspector).
  - Keep the accessible names where possible, for example `aria-label="Edit title"` and `aria-label="Vote +1"`.

## Design tokens
Copy them from `docs/design/mock.html`. The main tokens:
- `--accent` is #0071e3 (light) and #0a84ff (dark). `--link` is #0059b8 (light) and #6cb4ff (dark).
- `--text` and `--text2` (68–72% alpha), `--card`, `--card2`, `--sep`, `--hover`.
- `--glass`, `--glass-strong`, `--spec`, `--edge`, `--ring`, `--shadow`, `--op`, `--op-ring`.
- `--bg`: the sunset wallpaper, with radial gradients and one linear gradient. There is one version for light mode and one for dark mode.
- The "Needs you" red is #d70015 with white text. Pinned uses `--orange`.
- Radii: sidebar 26px, list cards 18px, message cards 16px, controls 999px (capsule).
- Font: the system stack (SF Pro). Body 14.5px. Page title 28px/800. Thread title 30px/800.
- Motion: 150–250ms, `cubic-bezier(.2,.8,.2,1)`, with a small spring on votes and reactions.
