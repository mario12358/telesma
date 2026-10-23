<!-- TELESMA_UX_LINKS_TEMPLATE — delete this line after adding the first real entry -->
# Mockup link registry

One place for the whole interface designed outside the repo — to begin with, Claude Design canvases;
the format works for other tools too (Figma etc.). File-based mockups in `telesma/spec/ux_ui/` keep working
as before; both sources can coexist in one project.

<!--
Rules:
- One entry = one mockup/canvas. Header: `## <id> — Title`.
  `<id>` lowercase letters/digits/hyphens, STABLE — tasks in PLAN.md reference it with the tag:
  (ui-screen: telesma/spec/ux_ui/LINKS.md#<id>)
- The `- link:` field is mandatory. The link must be SHARED (public / share link) —
  Telesma cannot fetch a private artifact with WebFetch. telesma.sh checks that the links
  are reachable at startup (warning only).
- `- type:` one of: screen | flow | tokens | components
- `- scope:` what the mockup shows (screens, states) — helps with indexing and tagging tasks
- This file is NOT frozen like telesma/spec/ — you can add entries during the project.
  telesma.sh detects unindexed entries and Telesma refreshes the ## UX/UI guidelines section
  in telesma/state/SPEC_INDEX.md at the start of the session.

Example entry (indentation on purpose — remove it in a real entry):

  ## b1-project-overview — Project overview
  - link: https://claude.ai/public/artifacts/00000000-0000-0000-0000-000000000000
  - type: screen
  - scope: project list, cards with metrics; states: empty / loaded / error
-->
