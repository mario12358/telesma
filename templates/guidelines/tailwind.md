---
tag: tailwind
keywords: tailwind, tailwindcss, utility classes, @apply, @theme, css variables, design tokens, responsive, dark mode, prettier-plugin-tailwindcss, clsx, cva, tailwind-merge, postcss
---

# Guidelines: Tailwind CSS

## Style

- Utilities in markup are the default; one element's class string describes its appearance completely — no sibling stylesheet carrying "the rest"
- Class order by `prettier-plugin-tailwindcss`: run it, do not argue with it; never hand-sort
- Conditional classes with `cn()` (`clsx` + `tailwind-merge`): `className={cn("rounded-md px-3", isActive && "bg-primary text-primary-foreground", className)}`; the `className` prop is merged last so callers can override
- Full class names only — `bg-${color}-500` is invisible to the compiler and produces no CSS; map variants to complete strings in an object or `cva`
- Variants with `class-variance-authority`: `const button = cva("inline-flex items-center justify-center rounded-md", { variants: { intent: { primary: "bg-primary text-primary-foreground", ghost: "hover:bg-muted" }, size: { sm: "h-8 px-3 text-sm", md: "h-10 px-4" } }, defaultVariants: { intent: "primary", size: "md" } })`
- Spacing and sizing from the scale (`p-4`, `gap-2`, `max-w-prose`); an arbitrary value (`w-[347px]`) only for a one-off the tokens genuinely do not cover
- Semantic colour tokens in components (`bg-background`, `text-muted-foreground`, `border-border`, `bg-destructive`), never raw palette names (`bg-gray-100`, `text-blue-600`)
- Every interactive element: `focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring`, `disabled:pointer-events-none disabled:opacity-50`, `transition-colors`

## Project structure

- One entry stylesheet `src/styles/globals.css` with `@import "tailwindcss";` (v4) and the theme; imported once at the app root; no per-component CSS files
- Tokens as CSS variables: `@theme { --color-primary: var(--primary); --radius-md: 0.5rem; --font-sans: ui-sans-serif, system-ui, sans-serif; }` with light values on `:root` and dark values on `.dark`, plus `@custom-variant dark (&:where(.dark, .dark *))`; on v3 the same variables referenced from `theme.extend` in `tailwind.config.ts`
- A designer-delivered `tokens.css` is wired through those variables, never copied into component classes
- UI primitives (`Button`, `Input`, `Card`, `Dialog`) in `src/components/ui/`, each with `cva` variants and a `className` passthrough; feature components compose primitives instead of repeating 20-class strings
- `@layer base` only for element defaults (`body { @apply bg-background text-foreground; }`); `@layer components` only for classes that must exist as CSS (third-party markup, rendered Markdown), not for buttons
- Build integration through `@tailwindcss/vite` or the PostCSS plugin only; no Sass pipeline; if a class never appears, the compiler did not see the file or the name was dynamic
- `@tailwindcss/typography` (`prose`) for rendered Markdown; `@tailwindcss/forms` only when the design wants native form resets

## Tests

- Styling is asserted through behaviour and accessibility, not class strings: `toBeVisible()`, `toBeDisabled()`, `toHaveAccessibleName()`; never `expect(el.className).toContain("bg-primary")`
- Visual regression with Playwright `toHaveScreenshot()` per primitive variant, per breakpoint (`page.setViewportSize`), in light and dark; snapshots generated in the CI container so fonts match
- `@axe-core/playwright` (or `vitest-axe`) on every page or story; contrast of theme pairs (`text-muted-foreground` on `bg-muted`) is a failing test, not a review note
- A Storybook or `/dev/components` route rendering each primitive in every variant and state (default, hover, focus-visible, disabled, loading) is the fixture for screenshot tests
- Run one: `npx playwright test tests/visual/button.spec.ts`; `--update-snapshots` only after an intentional, reviewed change
- Dark-mode test: add `.dark` to `document.documentElement` and re-screenshot — a component with a hardcoded `bg-white` fails here

## Responsive and dark mode

- Mobile first: unprefixed classes are the phone layout, `md:` / `lg:` add structure (`grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3`); `max-md:` only for exceptions
- Breakpoints from the theme only; container queries (`@container` on the parent, `@md:flex-row` on children) for components that live in several layouts
- Dark mode by class strategy, toggled and persisted by the app; every colour either uses a semantic token that switches or has an explicit `dark:` pair — a component is done only when it reads correctly in both themes
- `motion-safe:transition-transform motion-reduce:transition-none` on anything that animates
- Type scale from `text-sm` … `text-xl` with `leading-*`; `rem`-based tokens so browser zoom works

## Accessibility of styled elements

- `sr-only` for visually hidden labels, not `hidden` (which removes the node from the accessibility tree); `focus:not-sr-only` for skip links
- Never `outline-none` without a `focus-visible:ring-*` replacement
- Interactive elements are `<button>` or `<a>`, not a `<div>` with `cursor-pointer` and `onClick`; state styled from attributes — `aria-expanded:rotate-180`, `data-[state=open]:bg-muted`, `aria-invalid:border-destructive`
- Touch targets `min-h-11 min-w-11` on mobile controls; `touch-manipulation` on buttons
- Body text pairs ≥ 4.5:1 contrast; `text-muted-foreground` for secondary text only — never for labels, errors or anything required

## What to avoid

- `@apply` to write "normal CSS" (`.btn { @apply ... }` for every button) — extract a component instead
- Arbitrary values everywhere (`text-[#333]`, `mt-[13px]`, `w-[347px]`) — they bypass the tokens and the dark theme
- Dynamic class construction (`\`text-${size}\``) — a lookup object of full class names
- Inline `style={{}}` for anything a utility covers; the same long class string pasted across files instead of a primitive
- `bg-white`, `text-black`, raw palette colours in feature components
- `!` important modifiers (`!px-4`) to win a merge conflict — fix the order with `tailwind-merge` or remove the clash
- A second CSS framework (Bootstrap, component-library stylesheets) in the same tree
- Overriding Preflight globally instead of `@layer base`
