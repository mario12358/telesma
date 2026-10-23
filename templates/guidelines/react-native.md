---
tag: react-native
keywords: react-native, rn, expo, expo-router, react-navigation, android, ios, mobile, app, native, flatlist, stylesheet, navigation, hermes
---

# Guidelines: React Native

## Components

- Functional with hooks — NOT class components
- File name = component name, PascalCase (`LoginScreen.tsx`)
- One component per file (plus tightly coupled sub-components)
- Props typed with an interface: `interface Props { ... }` (TypeScript)
- Use native primitives (`View`, `Text`, `Pressable`) — not HTML (`div`, `span`); `Pressable`, not the legacy `Touchable*`
- **Never** render a bare string outside `<Text>` (crash on Android)
- Expo (managed workflow, `npx expo`) is the default for a new project; the New Architecture is on — do not add libraries that still need the legacy bridge/interop

## Project structure

- `src/screens/` — screens (full views wired to navigation)
- `src/components/` — shared presentational components
- `src/navigation/` — React Navigation configuration (stack, tabs, drawer)
- `src/features/<name>/` — feature-based organisation: screen + hook + test + styles
- `src/hooks/` — custom hooks shared between features
- `src/lib/` — utilities/helpers with no dependency on React
- `src/services/` — API client, storage, push notifications

## Navigation

- `expo-router` (file-based, `app/` directory) in Expo projects; `@react-navigation/native` with native-stack / bottom-tabs / drawer otherwise — one of the two per project
- Typed routes: a `ParamList` for every navigator + `NativeStackScreenProps<ParamList, 'Screen'>` (or typed routes in `expo-router`)
- Deep linking configured in `linking` on `NavigationContainer` (automatic with `expo-router`)
- Do not keep application state in route params — only identifiers / filters

## State

- `useState` for local state, Context for cross-screen, a store (Redux Toolkit / Zustand) for global
- Server state: `@tanstack/react-query` — do not hand-roll a cache in `useState`
- Persistence: `@react-native-async-storage/async-storage` (never store tokens there unencrypted)
- Secrets / tokens: `expo-secure-store` (iOS Keychain, Android Keystore)

## Styling

- `StyleSheet.create({ ... })` instead of inline objects (validation, a small perf boost)
- Alternatively: `nativewind` (Tailwind) or `tamagui` — **one convention per project**
- Units: `dp` by default (numbers without `px`); percentages for flexible layouts
- Safe area: `react-native-safe-area-context` (`SafeAreaView` from that package or `useSafeAreaInsets`) — the core `SafeAreaView` is deprecated
- Avoid fixed heights — use `flex`, `flexDirection`, `gap`

## Lists and performance

- `FlatList` / `SectionList` (or `@shopify/flash-list` for long, uniform lists — one list library per project) — **never** `ScrollView` + `map` for >20 items
- `keyExtractor` always set (stable IDs, not `index`)
- `getItemLayout` when item height is constant (a big boost)
- `React.memo` on the item component + stable callbacks (`useCallback`)
- Images: `expo-image` (cache, progressive loading, blurhash) — not `Image` from core for remote images
- Animations: `react-native-reanimated` + `react-native-gesture-handler`; never `Animated` with `useNativeDriver: false` for layout work

## Platform-specific

- `Platform.OS === 'ios'` / `'android'` for branching
- `*.ios.tsx` / `*.android.tsx` files for large differences — the bundler picks the variant itself
- Check on **both platforms** before marking a task ✅ — RN does not guarantee pixel parity
- iOS: test on the simulator + a real device (permissions, haptics)
- Android: Hermes is the engine (do not switch it off) + handle the back button (`BackHandler` / navigation's own handling)

## Forms

- `react-hook-form` + `@hookform/resolvers/zod` — NOT a manual `useState` per field
- Validation: a Zod schema shared with the backend where possible
- Keyboard: `KeyboardAvoidingView` (iOS: `padding`, Android: `height`) + `react-native-keyboard-controller` for complex cases
- `keyboardType`, `autoCapitalize`, `autoCorrect`, `returnKeyType` — always set deliberately

## API and network

- `fetch` or `axios` — one choice per project
- Always set a timeout (plain fetch has none — use `AbortController`)
- Retry with backoff for 5xx / network errors (react-query does this)
- Offline: `@react-native-community/netinfo` for detection; a mutation queue for critical actions

## Tests

- Jest (`jest-expo` preset in Expo) + `@testing-library/react-native` — test behaviour, not implementation; `__tests__/` or `*.test.tsx` next to the component; one test: `npx jest src/x.test.tsx -t "name"`
- `screen.getByRole` / `getByText` > `getByTestId`
- `userEvent` from `@testing-library/react-native` (not the web `@testing-library/user-event`) > `fireEvent`; `await screen.findBy...` for async UI
- E2E: **Detox** (preferred) or **Maestro** — test the critical flows (login, checkout)
- Mock native modules with `jest.mock` in `jest-setup.ts`; never mock your own hooks/components to make a test pass

## Device permissions

- Ask for a permission **at the moment it is needed** (not all of them at start-up)
- Explain the purpose in `Info.plist` (iOS) and `AndroidManifest.xml` (Android) — required for store review
- Handle refusal — the app must work in a limited mode, not crash

## Working with mockups from `telesma/spec/ux_ui/`

If a task has a `(ui-tokens: ...)`, `(ui-component: ...)` or `(ui-screen: ...)` tag, the files in `telesma/spec/ux_ui/` are a **design reference**, not code to import. The loading procedure is in section 0.4 of the instructions.

**React Native specifics** (different from web React mockups):

- Mockups are usually web ones (HTML/CSS/JSX with `<div>`, `<svg>`, `style={{...}}`) — in RN you **must rewrite** them using native primitives:
  - `<div>` → `<View>`, `<span>` / text → `<Text>` (never a bare string outside `<Text>` — crash on Android)
  - `<button>` / `onClick` → `<Pressable>` / `onPress`
  - `<svg>` from the mockup → `react-native-svg` (`<Svg>`, `<Path>`)
- **Tokens (`tokens.css`)** — CSS variables do NOT work in RN. Rewrite `tokens.css` as `src/styles/tokens.ts`:
  ```ts
  export const tokens = {
    colors: { accent: '#6B6BF2', /* ... */ },
    fonts: { sans: 'IBMPlexSans', mono: 'JetBrainsMono' },
    /* ... */
  };
  export const theme = {
    dark: { bgSurface: '#0E0F13', textPrimary: '#ECEDF1', /* ... */ },
    light: { bgSurface: '#FAFAF7', textPrimary: '#18181B', /* ... */ },
  };
  ```
  Theme through Context (`ThemeProvider`) + a `useTheme()` hook. Or `nativewind` if the stack uses Tailwind — then generate `tailwind.config.js` from the token mapping.
- **Components (`*.jsx`)** — rewrite to `src/components/<Name>.tsx` using `View`/`Text`/`Pressable`. Styles through `StyleSheet.create({...})` referring to `theme` (or `nativewind` classes).
- **Screens (`screens-*.jsx`)** — implement as `src/screens/<Name>.tsx`, wire them into the navigator. Use the components that already exist in `src/components/`.
- **Pixel mismatches**: treat dimensions from the web mockup (e.g. a 44px top bar) as `dp` in RN. Check on both platforms (iOS + Android) — RN does not guarantee pixel parity with the web.
- **Fonts from tokens.css** — bundle them in `assets/fonts/`, register them through `expo-font` (Expo) or `react-native.config.js` (bare RN). Do not assume the mockup's font is available on the system.
- **Element missing from SPEC_INDEX** or a mismatched line range → TELESMA BLOCKED. Do not guess the look.

## What to avoid

- Business logic in screens (extract into hooks / services)
- **Copying code from `telesma/spec/ux_ui/*.jsx` 1:1** — it is web JSX (`<div>`, CSS variables); in RN it has to be rewritten with native primitives
- **CSS variables (`var(--*)`) in RN styles** — they do not work, use theme/Context or nativewind
- `console.log` in production code (use a `__DEV__` guard; debug with React Native DevTools — Flipper is no longer supported)
- Inline styles when you have `StyleSheet` / nativewind
- `Dimensions.get('window')` without a listener (does not react to rotation / split screen) — use `useWindowDimensions`
- Adding a native dependency without a rebuild (`npx expo prebuild` / `npx expo run:ios|android`, or `pod install` in bare RN) — report TELESMA BLOCKED if a native build is required and not possible
- Expo Go for anything with custom native modules — use a development build
- Commits not tested on **both platforms**
