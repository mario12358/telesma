---
tag: accessibility
keywords: accessibility, a11y, wcag, aria, screen reader, keyboard, focus, contrast, semantic html, alt text, axe, voiceover, talkback, accessibilitylabel
---

# Guidelines: Accessibility (web and mobile UI)

## Style

- Semantic HTML first: `<button>` for actions, `<a href>` for navigation, `<nav>`, `<main>`, `<header>`, `<footer>`, `<section aria-labelledby>`, `<ul>/<li>` for lists, `<table>` with `<th scope>` for data; a `<div onClick>` is never a control
- ARIA only when no native element exists (tabs, combobox, tree, custom dialog); a native element with the right attributes beats `role=` on a `div`; no redundant ARIA (`role="button"` on `<button>`, `aria-required` next to `required`)
- Every form control has a visible label associated in code: `<label for="email">` + `<input id="email">`; placeholder is not a label; icon-only buttons get `aria-label="Close"`
- Headings form an outline: exactly one `<h1>` per view, no skipped levels; the level is chosen by structure and styled with CSS
- `<html lang="en">`; `<title>` unique per route and updated on client-side navigation
- Images: informative `alt="Chart: revenue up 12% in Q3"`; decorative `alt=""` (empty, never missing); inline SVG icons `aria-hidden="true"` next to text, `role="img"` + `<title>` when standalone; never `alt="image"` or the file name
- Focus is always visible: `:focus-visible { outline: 2px solid var(--focus); outline-offset: 2px }`; `outline: none` without a replacement is a defect
- Accessible name = visible text ("Download the report (PDF)", not "click here"); voice-control users speak what they see
- Colour never carries meaning alone: an error has an icon and text, chart series differ by label or pattern as well
- Contrast ≥ 4.5:1 for text, ≥ 3:1 for large text, icons and control borders — verified once on the token pairs, not per component
- Motion inside `@media (prefers-reduced-motion: no-preference)`; nothing auto-advances without a pause control; nothing flashes more than 3 times per second
- Touch targets ≥ 44×44 CSS px (≥ 48 dp on mobile); font sizes in `rem`; 200% zoom and a 320 px viewport show everything without horizontal scroll

## Project structure

- `src/components/` primitives (`Button`, `Dialog`, `Combobox`, `Tabs`, `Toast`) implement each pattern once; features compose them and never re-implement focus or ARIA logic
- Complex widgets from a headless, accessibility-tested library (Radix, React Aria, Headless UI, Ark) rather than a hand-written `role="listbox"`
- `src/styles/tokens.*` holds pre-verified foreground/background pairs and the focus-ring token; components use only those pairs
- `src/lib/a11y/`: `useFocusTrap`, `useReturnFocus`, `VisuallyHidden`, and one `LiveRegion` mounted at the app root with an `announce(message, 'polite' | 'assertive')` function
- Route components own the `<title>`, the `<h1>` and moving focus to the `<h1>` (or a skip target) after client-side navigation
- A "Skip to main content" link is the first focusable element of every layout

## Tests

- Accessible queries are the default selectors in unit, integration and e2e tests: `getByRole('button', { name: 'Save' })`, `getByLabelText('Email')`, `getByRole('heading', { level: 1 })`; needing `getByTestId` means an accessible name is missing — fix the component first
- `axe-core` runs automatically: `vitest-axe` / `jest-axe` (`expect(await axe(container)).toHaveNoViolations()`) in every component render test, and `@axe-core/playwright` on every e2e page after load and after each dialog/menu opens; a violation fails the build, no `disableRules` without a linked issue
- `eslint-plugin-jsx-a11y` (web) / `eslint-plugin-react-native-a11y` (mobile) with the recommended rules as errors
- Keyboard e2e: Tab order follows reading order, Enter/Space activate buttons, Escape closes dialogs, arrows move within tabs/menus/radiogroups, focus never lands on a hidden element (`await expect(page.locator(':focus')).toBeVisible()`)
- Focus management asserted on every modal and route change: on open `expect(screen.getByRole('dialog')).toHaveFocus()` (or its first focusable), on close `expect(openerButton).toHaveFocus()`
- Live regions: after an async action `await screen.findByRole('status')` (polite) or `findByRole('alert')` (assertive) contains the message
- axe runs against the real DOM with real CSS loaded (contrast and visibility rules need it); nothing accessibility-related is mocked
- A manual pass per release on the critical flows with keyboard only and a real screen reader (VoiceOver + Safari, NVDA + Firefox, TalkBack) — recorded in the release test scenarios

## Interaction patterns

- Dialogs: `<dialog>` + `showModal()`, or `role="dialog" aria-modal="true" aria-labelledby`; focus moves inside on open and is trapped, Escape closes, focus returns to the trigger, background content gets `inert`
- Menus, tabs, listbox and combobox follow the WAI-ARIA Authoring Practices keyboard model (roving `tabindex`, arrows, Home/End, type-ahead); one Tab stop per composite widget
- Dynamic content: `aria-live="polite"` for status ("3 results"), `role="alert"` only for errors needing attention; the region exists in the DOM before the message is written and its text is replaced, not appended
- Loading: `aria-busy="true"` on the refreshing region; a spinner is `role="status"` with visually hidden text ("Loading results")
- Forms: errors linked with `aria-describedby`, `aria-invalid="true"`, visible and specific text ("Enter a date after today"); on submit with errors, focus the first invalid field or an error summary with `role="alert"`
- Tooltips open on focus as well as hover, close with Escape, and never hold the only copy of essential information
- Tables: `<caption>`, `<th scope="col|row">`, `aria-sort` on sortable headers; a data grid is the last resort

## Mobile (React Native / native)

- Every interactive element: `accessibilityRole` (`button`, `link`, `header`, `checkbox`, …), `accessibilityLabel` (what it does — "Delete note", not "trash icon"), `accessibilityState` (`{ disabled, selected, checked }`), `accessibilityHint` only when the result is not obvious
- `testID` is for automation (Detox/Maestro) only and never replaces `accessibilityLabel`; a screen is usable with VoiceOver/TalkBack before any `testID` is added
- A card is one focusable element: `accessible={true}` on the container with a composed label; decorative images `accessibilityElementsHidden` / `importantForAccessibility="no-hide-descendants"`
- Announcements via `AccessibilityInfo.announceForAccessibility()`; check `isReduceMotionEnabled()` before disorienting animations
- Font scaling stays on (`allowFontScaling` default); flex layouts let text at 200% wrap instead of truncating; `maxFontSizeMultiplier` only on fixed chrome like tab bars
- Touch targets ≥ 48×48 dp, with `hitSlop` where the visual element is smaller

## What to avoid

- `<div>`/`<span>` with `onClick`, `role="button"`, `tabindex="0"` and a key handler — that is a `<button>`
- `aria-label` on a `<div>` without a role (ignored); `role="button"` on a link that navigates; `tabindex` greater than 0
- `outline: none` without a `:focus-visible` replacement; `aria-hidden="true"` on a focusable element
- Placeholder as the only label; labels that vanish on input; `title` as the accessibility mechanism
- Focus stolen on page load; focus dropped to `<body>` after a dialog closes or a list item is deleted
- Hover-only menus and tooltips with no keyboard equivalent; infinite scroll with no "load more" and no announcement of new items
- `user-scalable=no` / `maximum-scale=1` in the viewport meta
- Treating a green axe run as "accessible" — automated checks catch roughly a third of the issues; keyboard and screen-reader passes catch the rest
- `data-testid` added to dodge writing an accessible name; `getByTestId` as the default selector
