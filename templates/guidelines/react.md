---
tag: react
keywords: react, jsx, tsx, hooks, component, state, props, vite, spa, frontend, ui, zustand, tanstack query, react-router
---

# Guidelines: React

## Components

- Functional with hooks — NOT class components
- File name = component name, PascalCase (`UserList.tsx`)
- One component per file (plus tightly coupled sub-components)
- Props typed with an interface: `interface Props { ... }` (TypeScript)
- `ref` is a regular prop (React 19) — no `forwardRef`; `<Context value={...}>` instead of `<Context.Provider>`
- ESLint with `eslint-plugin-react-hooks` + Prettier (or Biome) — run them; do not argue with them

## Structure

- `src/components/` — shared, presentational components
- `src/features/<name>/` — feature-based organisation: component + hook + test + styles
- `src/hooks/` — custom hooks shared between features
- `src/lib/` — utilities/helpers with no dependency on React

## Hooks

- `useEffect` ALWAYS with a dependency list (never without — it causes loops); no `useEffect` for data fetching or for deriving state — compute during render or use a query library
- A custom hook for reusable logic (`use` prefix)
- Do not call hooks conditionally / in loops (rules of hooks)
- `useMemo` / `useCallback` / `React.memo` only for a measured perf problem; with the React Compiler enabled, not at all
- Forms and mutations: `useActionState` / `useTransition` for pending and error state instead of hand-rolled `isLoading` flags

## State

- `useState` for local state, Context for cross-component, a store (Zustand / Redux Toolkit) for global client state
- Server state (anything fetched): TanStack Query — not `useEffect` + `useState` caches, not the global store
- Prop drilling > 2 levels → context or store
- State lifted to the lowest common ancestor
- Form state: `react-hook-form` + a zod resolver > a manual `useState` per field
- Routing: `react-router` (or TanStack Router) with lazy route modules — URL is state for filters, pages, selected ids

## Tests

- React Testing Library + Vitest (`*.test.tsx` next to the component; one test: `vitest run src/x.test.tsx -t "name"`)
- Test behaviour (what the user sees/clicks), not implementation
- `screen.getByRole` > `getByLabelText` > `getByText` > `getByTestId`; never `container.querySelector`
- `userEvent` > `fireEvent` (simulates real interactions); `await screen.findBy...` for async UI, no `act()` by hand
- Mock the network at the boundary (`msw`), not the hooks or the query client

## Performance

- Virtualisation for lists > 100 items (`@tanstack/react-virtual` or `react-window`)
- Lazy-loaded routes: `React.lazy` + `Suspense`
- Suspense boundaries + an error boundary around every async region, not one at the root

## Working with mockups from `telesma/spec/ux_ui/`

If a task has a `(ui-tokens: ...)`, `(ui-component: ...)` or `(ui-screen: ...)` tag, the files in `telesma/spec/ux_ui/` are a **design reference**, not code to import. The loading procedure is in section 0.4 of the instructions.

- **Tokens (`tokens.css`)** — copy 1:1 to `src/styles/tokens.css`, wire it globally (`import './styles/tokens.css'` in `main.tsx` or the root component). `theme-dark` / `theme-light` classes on `<html>` or the root `<div>`.
- **Components (`*.jsx`)** — these are Babel-in-browser prototypes (global `window.X`, no ES module imports, JSX without TypeScript). **Do NOT copy them 1:1** — rewrite each component as a separate file `src/components/<Name>.tsx`:
  - `interface Props { ... }` instead of untyped props
  - Imports instead of global variables
  - A named default export or a named export — consistently across the project
  - Styles through `var(--*)` from `tokens.css` — never a hardcoded hex/px when a token exists
- **Screens (`screens-*.jsx`)** — implement as `src/screens/<Name>.tsx` (or `src/features/<Name>/<Name>Screen.tsx`). Use the components that already exist in `src/components/` (from earlier setup tasks) — do NOT go back to the prototype to learn a component's API, read the production files.
- **Behaviour faithful to the mockup**: layout, hierarchy, states (hover/active/disabled/loading/error), animations, interactions. Pixel-aware — keep the dimensions from the mockup.
- **Element missing from SPEC_INDEX** or a mismatched line range → TELESMA BLOCKED. Do not guess the look.

## What to avoid

- Business logic in components (extract into hooks/services)
- Inline styles when you have a system (CSS modules / Tailwind) — runtime CSS-in-JS libraries are in maintenance mode, do not add one
- `dangerouslySetInnerHTML` without sanitisation (DOMPurify)
- `index` as `key` in dynamic lists
- Storing derived values in state (`useState(items.length)`) — derive during render
- `useEffect` chains that set state from other state
- **Copying code from `telesma/spec/ux_ui/*.jsx` 1:1** — always rewrite to TS + ES modules
- **Hardcoded colours/spacing** when a matching token exists in `tokens.css`
