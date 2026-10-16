# Design Memory

## Brand tone
- **Adjectives:** native macOS (Tahoe / Golden Gate), calm, crisp, a little joyful.
- **Avoid:** an email-client layout (three panes), spreadsheet or database tables, Finder/Reminders copies of the sidebar, too much skeuomorphism, colored left borders on cards, controls that map to no real feature.

## Layout and spacing
- A floating glass sidebar and a capsule toolbar over a sunset wallpaper. The content is in solid cards.
- **Density:** compact cards with small gaps (8px). Do not use one merged list.
- **Corner radius:** sidebar 26px, cards 16–18px, controls in capsule shape.
- **Shadows:** soft and layered, as on B cards. Glass has a thin top highlight and a darker bottom edge.

## Typography
- System font stack (SF Pro). Bold, left-aligned large titles (28–30px, weight 800, tight tracking).
- Body 14.5px. Metadata 12.5px in the secondary label color.

## Color
- Blue accent (#0071e3 / #0a84ff). A red "Needs you" pill (#d70015). Pinned is orange. Agents get a purple ✦.
- Light and dark mode are both required, with a System/Light/Dark toggle.

## Interaction patterns
- Hover reveals the secondary actions (☺ React, Reply, Edit, the vote stepper, the title ✎). They also show on focus and on touch devices.
- Use one toggle button for each state (for example, Pinned/Pin), not two buttons.
- Popovers and sheets come out of the control that opens them. Overlays close on a click outside them and on Esc.
- ⌘K command palette for navigation and actions. A global "+ New thread" button with a good area picker.
- An inspector overlay on the thread page for the thread metadata.

## Accessibility rules
- A 2.5px accent focus ring. 4.5:1 contrast in both modes. Respect reduced motion.

## Repo conventions
- Vanilla JS, no build step, a strict CSP. Use `el()` and never `innerHTML`.
- Do not nest `backdrop-filter` elements. Give an inner popover a solid background.
- The reference mocks are in `docs/design/` (`mock.html` = final, `variant-b.html` = the original B).
