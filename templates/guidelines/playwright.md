---
tag: playwright
keywords: playwright, e2e, end-to-end, browser, chromium, firefox, webkit, page object, fixture, trace, screenshot, recording, ui test
---

# Guidelines: Playwright (web e2e)

## When to use

- **Always as the last task of a phase with a web UI** (`tech: react`, `vue`, `angular`, `svelte` in the same phase)
- End-to-end scenarios from the user's perspective (login → action → logout)
- **Not** for testing individual components — that is what RTL/Vitest is for (`tech: react`)
- **Not** for testing an API without a UI — that is what supertest/pytest on the backend is for

## Project structure

- `e2e/` or `tests/e2e/` — all Playwright tests (separate from unit tests)
- `e2e/fixtures/` — custom fixtures (auth, database seed, API mocks)
- `e2e/pages/` — Page Object Models (one file per significant view)
- `e2e/specs/<feature>/` — specs per feature (e.g. `auth/login.spec.ts`, `auth/register.spec.ts`)
- `playwright.config.ts` in the project root

## Selectors — order of preference

1. **Role-based**: `page.getByRole('button', { name: 'Log in' })` — the most resilient
2. **Label/Placeholder**: `page.getByLabel('Email')`, `page.getByPlaceholder('jane@example.com')`
3. **Text**: `page.getByText('Forgot your password?')`
4. **Test ID**: `page.getByTestId('login-submit')` — **only** when the above are not enough; they require a `data-testid` attribute in the UI code
5. **CSS/XPath** — last resort, fragile against style changes

## Page Object Pattern

Every significant view gets a class that encapsulates its selectors and actions:

```typescript
// e2e/pages/LoginPage.ts
export class LoginPage {
  constructor(private page: Page) {}

  readonly emailInput = this.page.getByLabel('Email');
  readonly passwordInput = this.page.getByLabel('Password');
  readonly submitButton = this.page.getByRole('button', { name: 'Log in' });

  async goto() { await this.page.goto('/login'); }
  async login(email: string, password: string) {
    await this.emailInput.fill(email);
    await this.passwordInput.fill(password);
    await this.submitButton.click();
  }
}
```

The test uses only the methods and never reaches into the DOM directly.

## Fixtures — isolation and test data

- **Your own `test` with fixtures**: `import { test as base } from '@playwright/test'`
- A fixture for a logged-in user (avoids logging in in every test)
- A fixture for seeding the database: create the data before the test, clean up after it (or a transaction with rollback)
- **Never** share state between tests — each one must work on its own
- `test.beforeEach` for per-test setup, not `beforeAll` (shared state breaks isolation)

## Assertions

- `expect(locator).toBeVisible()` / `toHaveText()` / `toHaveURL()` — **auto-retry** (waits up to the timeout)
- **Never** `expect(await locator.textContent()).toBe(...)` — turns auto-retry into a snapshot, flaky
- Custom matchers in a separate file if you need domain-specific assertions
- `await expect.soft(...)` for several independent assertions in one test (does not stop at the first failure)

## Waiting

- **Never** `page.waitForTimeout(ms)` — an arbitrary sleep, flaky
- **Never** `waitForLoadState('networkidle')` — discouraged by Playwright; wait for what the user sees instead
- `await expect(locator).toBeVisible()` — waits until the element appears in the DOM
- `page.waitForResponse(url)` / `page.waitForRequest(url)` — set up BEFORE the action that triggers the call (`Promise.all` or a variable holding the promise)

## Configuration

- `playwright.config.ts`: projects per browser (Chromium, Firefox, WebKit)
- `use.baseURL` — the application URL defined centrally (dev server / staging)
- `use.trace: 'on-first-retry'` — trace recorded on retry, helpful for debugging
- `use.screenshot: 'only-on-failure'`, `use.video: 'retain-on-failure'` (default; for artifact recordings → see the Recording section)
- `workers` — parallelism; set it to `1` for tests writing to the same database, otherwise it is scheduled chaos
- `retries: 2` in CI, `0` locally — lets you detect flakiness in CI without slowing down the dev loop

## Recording (visual artifacts — section 0.5 of the Telesma instructions)

When `telesma/config.md` has `Screenshots: yes` or `Recordings: yes`, Playwright produces artifacts for each task tagged `(screen: ...)` / `(flow: ...)`.

### Screenshots per screen

A task tagged `(screen: B1_ProjectOverview)` → add a screenshot at the end of an existing e2e test that renders that screen:

```typescript
test('Project Overview — renders from the fixture', async ({ page }) => {
  await page.goto('/projects/123');
  await expect(page.getByRole('heading', { name: 'My project' })).toBeVisible();
  await page.screenshot({
    path: 'telesma/artifacts/screens/B1_ProjectOverview.png',
    fullPage: true,
  });
});
```

If the task has no e2e test of its own (only unit/integration RTL) → create a dedicated short spec in `tests/screenshots/<id>.spec.ts` that mounts the screen with a fixture and takes the screenshot. Do not use `@playwright/experimental-ct-react` unless it is already in the project — a plain `page.goto()` to a route with a fixture is enough.

### Video per Step

An e2e task tagged `(flow: telesma/spec/APP_FLOW.md#step-1)` → turn recording on in the config and move the file into `telesma/artifacts/flows/`:

```typescript
// playwright.config.ts — a config dedicated to flow tests
import { defineConfig } from '@playwright/test';

export default defineConfig({
  projects: [
    {
      name: 'flows',
      testMatch: /e2e\/specs\/flows\/.*\.spec\.ts/,
      use: {
        video: 'on',                     // ALWAYS record
        viewport: { width: 1280, height: 720 },  // deterministic size
        screenshot: 'off',               // not needed — the video is enough
        trace: 'off',                    // cleaner artifact
      },
      outputDir: 'telesma/artifacts/flows-raw',  // by default Playwright writes to test-results/
    },
    // other projects (chromium, firefox, ...) keep their defaults
  ],
});
```

After the run, Playwright leaves the video in `outputDir/<test-name>/video.webm`. **Rename it and move it to `telesma/artifacts/flows/`** (Bash in teardown or in a separate post-test step):

```typescript
// e2e/specs/flows/step-1-registration.spec.ts
import { test, expect } from '@playwright/test';
import { rename, mkdir } from 'node:fs/promises';
import path from 'node:path';

test.afterEach(async ({ }, testInfo) => {
  const video = testInfo.attachments.find(a => a.contentType === 'video/webm');
  if (video?.path) {
    await mkdir('telesma/artifacts/flows', { recursive: true });
    const slug = testInfo.title.toLowerCase().replace(/[^a-z0-9]+/g, '-').slice(0, 60);
    await rename(video.path, path.join('telesma/artifacts/flows', `step-1-${slug}.webm`));
  }
});

test('step-1: registration and first login', async ({ page }) => {
  // ...mirrors the prose of telesma/spec/APP_FLOW.md#step-1
});
```

### Naming convention

- Screenshots: `telesma/artifacts/screens/<id>.png` (id = as in the `(screen: <id>)` tag)
- Flow video: `telesma/artifacts/flows/step-<N>-<slug>.webm` (slug = title in kebab-case, max 60 characters)
- Do not commit `telesma/artifacts/` when the config has `Commit artifacts: no` — check `.gitignore`

### Deterministic recordings

- **Fixed viewport** (`1280x720` or `1920x1080`) — without it the same test produces a different video on each machine
- **Turn off animations** for flow tests if they are visually distracting: `await page.emulateMedia({ reducedMotion: 'reduce' })`
- **Mock timestamps** if they appear in the UI: `await page.addInitScript(() => Date.now = () => 1700000000000)`
- **Always the same database seed** for flow tests — the video is meant to demonstrate behaviour, not different data

## Running

- Locally: `npx playwright test` (headless) or `--headed` for debugging; one test: `npx playwright test e2e/specs/auth/login.spec.ts -g 'name' --project=chromium`
- Debug: `npx playwright test --debug` — Inspector with step-through
- UI mode: `npx playwright test --ui` — interactive preview; `npx playwright show-trace` for a trace from CI
- CI: `npx playwright install --with-deps` before the run, headless, with trace/video for failures
- **Before marking an e2e task ✅**: run `npx playwright test` and see green on every browser in the config

## Database seed / initial state

- A dedicated test database (not dev, not prod) — isolation
- A `setup` project with `dependencies: ['setup']` on the browser projects (preferred over `globalSetup`) migrates the schema + seeds the base data (roles, dictionaries) and saves the logged-in `storageState` that the auth fixture reuses
- `webServer` in the config starts the app under test (`reuseExistingServer: !process.env.CI`) — no hand-started dev server before the run
- A per-test fixture adds the data specific to the scenario
- After the whole run: drop the test database or leave it in the last good state

## Mocking / stubbing

- External third-party APIs (payments, e-mail, SMS): `page.route('**/api.payment-provider.example/**', route => route.fulfill({...}))`
- **Do not mock** your own backend — e2e is meant to check the front-back integration
- Exception: asynchronous events (webhooks, queues) — mock them if they are unpredictable in tests

## What to avoid

- Testing implementation details (CSS classes, DOM structure)
- `page.locator('.css-abc123')` — generated classes, fragile
- Long tests that test everything at once (1 scenario = 1 test, max 30s)
- Shared state between tests (no global variables)
- `console.log` in tests — use `test.step('name', async () => { ... })` to structure the report
- Skipping tests with `test.skip` without a comment giving the reason + a review date
- Committing e2e tests without running them locally to GREEN
