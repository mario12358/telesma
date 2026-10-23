---
tag: typescript
keywords: typescript, ts, tsx, types, interfaces, generics, tsconfig, strict, eslint, prettier, biome, zod, esm
---

# Guidelines: TypeScript

## Configuration

- `"strict": true` in `tsconfig.json` — mandatory
- `"noUncheckedIndexedAccess": true`
- `"noImplicitReturns": true`
- `"verbatimModuleSyntax": true` — forces `import type`, keeps ESM semantics explicit
- Target >= ES2022; `"module": "NodeNext"` (Node) or `"Bundler"` (Vite and friends)
- ESM only (`"type": "module"` in `package.json`) — no `require`, no mixed module systems
- Formatter: Prettier or Biome, linter: typescript-eslint or Biome — one pair per project; run them, do not argue with them
- In a Deno project: the same options in `compilerOptions` in `deno.json` — do NOT create a separate `tsconfig.json`

## Types

- `interface` for objects / API contracts, `type` for unions / intersections / aliases
- Prefer `unknown` over `any` (forces narrowing)
- Narrowing through type guards (`function isUser(x): x is User`) — not `as` casts
- Exhaustive `switch` with a `never` exhaustiveness check:
  ```ts
  const _exhaustive: never = variant
  ```
- `satisfies` to validate a literal against a type without widening it (`const cfg = {...} satisfies Config`)
- Parse external data (HTTP bodies, env, JSON files) with a schema library (zod or similar) — a type annotation is not validation

## Naming

- PascalCase for types/interfaces (no `I` prefix — that is a C# convention)
- camelCase for variables/functions
- Semantic suffixes: `Props`, `State`, `Config`, `Dto`

## Generics

- Use them when a type depends on an argument
- Unambiguous names (`TItem`, `TKey`) instead of `T`, `U` when there is more than one generic
- A constraint (`T extends X`) when you require some properties — not a bare `T`

## Modules

- `import type { ... }` for type-only imports (easier tree-shaking)
- Be careful with barrel files (`index.ts` with re-exports) — they easily create import cycles

## Tests

- Vitest outside Deno (`*.test.ts` next to the source; one test: `vitest run src/x.test.ts -t "name"`); `Deno.test` in Deno
- `tsc --noEmit` in CI next to the tests — a type error is a failing build

## What to avoid

- `any` — if you must, `unknown` + narrowing
- Non-null assertion `!` — prefer a check + early return
- `@ts-ignore` — use `@ts-expect-error` with a comment explaining why
- `enum` — prefer union types (`type Role = "admin" | "user"`) or an `as const` object
- Excessive generics when a concrete type is enough
- `as unknown as T` casts to silence the compiler — fix the type or parse the data
