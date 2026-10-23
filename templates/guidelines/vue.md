---
tag: vue
keywords: vue, vue3, composition api, script setup, pinia, vue router, composable, vite, vitest, vue test utils, sfc, nuxt, reactive, ref
---

# Guidelines: Vue 3

## Style

- Single-file components with `<script setup lang="ts">` — no Options API, no `defineComponent` wrappers in new code
- Component files `PascalCase.vue` with multi-word names (`UserList.vue`, never `List.vue`); the same PascalCase tag in templates (`<UserList />`)
- Props: `defineProps<{ userId: string; compact?: boolean }>()` with `withDefaults` for defaults; emits: `defineEmits<{ select: [id: string] }>()`; two-way binding: `defineModel<string>()`
- `ref` for primitives and values you replace, `reactive` only for objects you never reassign; `computed` for every derived value — never compute in the template
- Block order `<script setup>`, `<template>`, `<style scoped>`; scoped styles or CSS modules by default
- `v-for` always with a stable `:key` (an id, never the index); `v-if` and `v-for` never on the same element — wrap in `<template v-for>`
- ESLint with `eslint-plugin-vue` (`flat/recommended`) + `@vue/eslint-config-typescript` + Prettier; `vue-tsc --noEmit` for types — run them; do not argue with them
- Emitted events camelCase in `defineEmits`, kebab-case in templates (`@item-selected`); handler functions in the parent named `onItemSelected`

## Project structure

- Vite layout (`npm create vue@latest`): `src/main.ts`, `src/App.vue`, `src/router/index.ts`, `src/stores/<name>.ts`, `src/composables/use<Name>.ts`, `src/components/` (shared), `src/views/` or `src/features/<name>/` (route level), `src/api/` (typed HTTP clients)
- One composable per concern in `src/composables/useX.ts`: takes refs or plain values, returns an object of refs and functions, cleans up in `onScopeDispose`
- Pinia for state shared across routes or distant components, as setup stores (`defineStore("cart", () => { const items = ref<Item[]>([]); ...; return { items, add } })`); local state stays in the component
- Vue Router in `src/router/index.ts`: named routes, lazy views (`component: () => import("@/views/OrdersView.vue")`), auth in `router.beforeEach`, not in components
- Environment through `import.meta.env.VITE_*` only, validated once in `src/config.ts`; nothing secret ever goes into a Vite app
- Alias `@/` → `src/` configured in both `vite.config.ts` and `tsconfig.json`

## Tests

- Vitest + `@testing-library/vue` for behaviour tests, `@vue/test-utils` (`mount`) for prop/emit contracts; `environment: "jsdom"` in `vitest.config.ts`
- Files `*.spec.ts` next to the component; run one: `pnpm vitest run src/components/OrderForm.spec.ts`
- Test what the user sees: `getByRole`, `await user.click(...)` from `@testing-library/user-event`, then assert the DOM or `wrapper.emitted("select")`
- Pinia: `setActivePinia(createPinia())` in `beforeEach` for store tests; `createTestingPinia({ stubActions: false })` as a global plugin when mounting components that use stores
- Router: a real `createRouter({ history: createMemoryHistory(), routes })`, `await router.push(...)`, `await router.isReady()`; mock `useRoute`/`useRouter` only when the component needs nothing else from the router
- Composables tested by calling them inside `effectScope()` or a tiny wrapper component; `await nextTick()` / `flushPromises()` after reactive changes before asserting
- HTTP mocked at the boundary (`msw` or `vi.mock("@/api/orders")`); never mock Vue reactivity or `computed`
- Playwright for end-to-end flows against `vite preview` of a production build

## Reactivity

- Destructuring `props` or a `reactive` object loses reactivity — use `toRefs(props)` / `storeToRefs(store)` or read `props.x` inside `computed`
- `watch` with an explicit source (`watch(() => props.id, load, { immediate: true })`); `watchEffect` only when every dependency is read inside; cancel async work with `onCleanup`
- Never mutate props; emit an event or use `defineModel`
- Reassigning a `reactive()` variable (`state = {...}`) breaks reactivity — mutate in place or use `ref`
- `shallowRef` for large data structures and third-party instances (maps, editors) that need no deep tracking
- Top-level `await` in `<script setup>` requires `<Suspense>` in the parent — otherwise fetch in `onMounted` or in a composable with a `loading` ref
- Template refs: `const input = useTemplateRef<HTMLInputElement>("input")`, read after `onMounted`

## What to avoid

- Options API, mixins, `this` in new components; `Vue.set`/`Vue.delete`
- `v-html` with unsanitised content (use DOMPurify)
- Business logic inside components — move it to composables, stores or `src/api`
- A `watch` that copies one ref into another instead of a `computed`; deep `watch` on large objects
- Global event buses and `provide/inject` for app-wide state — that is what Pinia is for
- `any` in props, untyped `defineProps`, `:key="index"`
- Tests asserting `wrapper.vm.someInternal` instead of rendered output or emitted events
- `import.meta.env` read all over the code instead of one config module
