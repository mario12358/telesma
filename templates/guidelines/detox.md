---
tag: detox
keywords: detox, e2e, mobile, react-native, expo, ios, android, simulator, emulator, testid, gray box, maestro
---

# Guidelines: Detox (React Native mobile e2e)

## When to use

- **Always as the last task of a phase with a mobile UI** (`tech: react-native` in the same phase)
- End-to-end scenarios: login → navigation → action → logout
- **Not** for testing individual components — that is what `@testing-library/react-native` is for (`tech: react-native`)
- **Not** for testing the API layer without a UI — that is what backend tests are for
- Alternative: **Maestro** (simpler YAML, less setup, weaker control over assertions) — ask during the clarification phase if it is not settled

## Project structure

- `e2e/` — all Detox tests (separate from the unit tests in `__tests__/`)
- `e2e/jest.config.js` — a separate Jest configuration for e2e (different testMatch, longer timeout)
- `e2e/helpers/` — data factories, login helpers, state reset helpers
- `e2e/<feature>.e2e.ts` — specs per feature (e.g. `auth.e2e.ts`)
- `.detoxrc.js` in the project root — device/app configuration per platform (`apps`, `devices`, `configurations`, `testRunner: { args: { config: 'e2e/jest.config.js' } }`)
- Expo: Detox needs a native build (`npx expo prebuild`, then a development build) — it cannot drive Expo Go

## Configuration per platform

- **iOS**: `ios.sim.debug` (Debug build on an iPhone simulator), `ios.sim.release` for CI
- **Android**: `android.emu.debug` (Debug APK on an emulator), `android.emu.release` for CI
- Build the APK/IPA before the first run: `detox build --configuration ios.sim.debug`
- **Both** configs must be maintained — test on both platforms before ✅

## Selectors — testID only

React Native has no HTML/ARIA semantics, so there is a single selector:

```tsx
<Pressable testID="login-submit" onPress={handleLogin}>
  <Text>Log in</Text>
</Pressable>
```

```typescript
await element(by.id('login-submit')).tap();
```

- **Never** `by.text('Log in')` as the only strategy — it breaks with i18n/localisation
- `by.id()` = `testID` — stable, enforced by code convention
- Text is acceptable only as an additional assertion, not for selection
- Assign `testID`s hierarchically: `auth.login.submit`, `auth.login.email-input`

## Actions

- `.tap()`, `.longPress()`, `.swipe('up' | 'down' | 'left' | 'right')`
- `.typeText('text')` — simulates the keyboard, slower but realistic
- `.replaceText('text')` — fast but skips `onKeyPress` events (do not test per-character validation with it)
- `.scrollTo('bottom')` / `.scroll(distance, direction)` — for lists
- `waitFor(element).toBeVisible().withTimeout(5000)` — instead of an arbitrary sleep

## Assertions

- `await expect(element(by.id('x'))).toBeVisible()`
- `await expect(element(by.id('x'))).toHaveText('...')`
- `await expect(element(by.id('x'))).toExist()` — in the tree, not necessarily visible
- `.not.toBeVisible()` to verify that something has disappeared

## Waiting

- **Never** `new Promise(r => setTimeout(r, 1000))` — flaky
- `waitFor(element(by.id('x'))).toBeVisible().withTimeout(ms)` — for things that appear asynchronously
- Detox synchronises with the RN runtime automatically (waits for animations, requests and timers to finish) — an endless `setInterval` or looping animation in the app blocks it forever; gate those behind a test flag
- Exception: `device.disableSynchronization()` for long animations/WebView — `device.enableSynchronization()` right after

## Resetting state between tests

- `device.launchApp({ newInstance: true, delete: true })` in `beforeEach` for full isolation (slow, but reliable)
- Or `device.reloadReactNative()` — faster, resets only the JS bundle
- Clear AsyncStorage / SecureStore through a deep link / a test endpoint
- Backend test database: reset by a helper that calls a test reset endpoint (never the prod DB!)

## Login helpers

Do not log in through the UI in every test — too slow. Write a helper that sets the token programmatically:

```typescript
// e2e/helpers/auth.ts
export async function loginAs(user: TestUser) {
  await device.launchApp({
    newInstance: true,
    url: `myapp://test-login?token=${user.token}`, // deep link only in __DEV__
  });
}
```

Logging in through the UI is kept for **one** test that validates it (`auth.e2e.ts` → login flow). All other scenarios use the helper.

## Permissions

- `device.launchApp({ permissions: { camera: 'YES', notifications: 'YES', location: 'inuse' }})`
- Also test refusal: `permissions: { camera: 'NO' }` → the app must work in a limited mode
- iOS and Android use different names — check the Detox documentation

## Running

- Locally on iOS: `detox test --configuration ios.sim.debug`
- Locally on Android: `detox test --configuration android.emu.debug`
- One spec: append its path (`detox test -c ios.sim.debug e2e/auth.e2e.ts`); one test: add `-t 'name'`
- CI: `--configuration *.release`, with `--record-videos failing --record-logs failing --take-screenshots failing`
- **Before ✅**: green runs on the iOS sim + the Android emu, not just on one platform

## Recording (visual artifacts — section 0.5 of the Telesma instructions)

When `telesma/config.md` has `Screenshots: yes` or `Recordings: yes`, Detox produces artifacts for each task tagged `(screen: ...)` / `(flow: ...)`.

### Screenshots per screen

A task tagged `(screen: LoginScreen)` → add `device.takeScreenshot()` at the end of a test that shows that screen:

```typescript
import { promises as fs } from 'fs';
import path from 'path';

it('Login screen — renders for a logged-out user', async () => {
  await device.launchApp({ newInstance: true });
  await expect(element(by.id('login.title'))).toBeVisible();

  const tempPath = await device.takeScreenshot('LoginScreen');
  await fs.mkdir('telesma/artifacts/screens', { recursive: true });
  await fs.copyFile(tempPath, path.join('telesma/artifacts/screens', 'LoginScreen.png'));
});
```

`device.takeScreenshot(name)` returns the path to a temporary file in the Detox artifacts; copy/move it into `telesma/artifacts/screens/` under a deterministic name.

### Video per Step

An e2e task tagged `(flow: telesma/spec/APP_FLOW.md#step-1)` → turn on `--record-videos all` for the run + organise the output:

```javascript
// .detoxrc.js — artifacts section for flow tests
module.exports = {
  // ...
  configurations: {
    'ios.sim.debug': {
      // ...
      artifacts: {
        rootDir: 'telesma/artifacts/flows-raw',
        plugins: {
          video: { enabled: true, keepOnlyFailedTestsArtifacts: false },
          screenshot: 'manual',
        },
      },
    },
  },
};
```

Run with `--record-videos all` (overrides the config) when generating recordings:

```bash
detox test --configuration ios.sim.debug \
  --record-videos all \
  --artifacts-location telesma/artifacts/flows-raw \
  e2e/flows/step-1-registration.e2e.ts
```

After the run, Detox produces a video in `telesma/artifacts/flows-raw/<run-id>/<test-name>.mp4`. Rename it and move it to `telesma/artifacts/flows/`:

```typescript
// e2e/flows/step-1-registration.e2e.ts
import { promises as fs } from 'fs';
import path from 'path';
import { glob } from 'glob';

afterEach(async () => {
  const videos = await glob('telesma/artifacts/flows-raw/**/*.mp4');
  for (const video of videos) {
    await fs.mkdir('telesma/artifacts/flows', { recursive: true });
    const platform = device.getPlatform();  // 'ios' or 'android'
    await fs.rename(video, path.join('telesma/artifacts/flows', `step-1-registration-${platform}.mp4`));
  }
});

describe('step-1: registration and first login', () => {
  it('happy path', async () => {
    // ...mirrors the prose of telesma/spec/APP_FLOW.md#step-1
  });
});
```

### Naming convention

- Screenshots: `telesma/artifacts/screens/<id>.png` (one file per id; if you test iOS + Android, add a `-ios` / `-android` suffix)
- Flow video: `telesma/artifacts/flows/step-<N>-<slug>-<platform>.mp4` (`<platform>` = `ios` or `android`)
- Detox produces `.mp4` (not `.webm` like Playwright) — that is fine, Telesma recognises both

### Deterministic recordings

- **One platform per recording** — do not mix iOS + Android in one video. Record them separately; REPORT.md keeps 2 entries per Step (`-ios` and `-android`).
- **Always the same database seed** for flow tests
- **Reset state in `beforeEach`**: `await device.launchApp({ newInstance: true, delete: true })`
- **Turn off push notifications** in the test config — so they do not show up in the video with ads
- **Fixed orientation** (portrait for mobile-first apps; explicit if landscape)

## Flaky tests — what to do

- Passing locally 5 times in a row = not flaky
- If it is flaky in CI: increase the `waitFor` timeouts, check synchronisation (animations, network)
- **Never** `retries: 3` in the config as a workaround — flakiness is a bug in the test or in the app
- `device.disableSynchronization()` with care — sometimes it solves the problem, sometimes it masks a real bug

## What to avoid

- Testing implementation details (class names, tree structure)
- `by.text()` as the only selection strategy
- `setTimeout` / `sleep` — use `waitFor`
- Shared state between tests (global variables, a persisted session)
- Logging in through the UI in every test — a helper with a deep link or the token written straight into storage
- Committing without running e2e on **both platforms** (iOS + Android)
- Tests longer than 60s — split the scenario
- Hardcoding localised texts — use i18n keys or testIDs
