<!-- TELESMA_APP_FLOW_TEMPLATE: delete this line once you start filling in the template -->

# APP_FLOW.md — Application flows (user → system scenarios)

> **What is this file for?**
> It describes **what the user does step by step and how the system responds** — from the user's perspective, without technical details.
> Every `## Step N — ...` is **a separate e2e scenario + one video recording** (1:1 mapping).
>
> **The file is optional.** It is used only if you set `Recordings: yes` in the `## Visual artifacts`
> section of `telesma/config.md`. Without this file Telesma records no video (info in REPORT.md, not a blocker).
>
> Once filled in, DELETE the `TELESMA_APP_FLOW_TEMPLATE` marker from the first line of the file.

---

## How to fill it in

- **One `## Step N — Title` = one video recording.** Precise granularity: one Step = one user flow from start to finish (sign-up, login, creating an object, etc.). Do not bundle several unrelated actions into one Step.
- **Step title** short and descriptive (e.g. `Sign-up and project creation`, `Multi-upload of the specification`). It becomes the identifier in `(flow: APP_FLOW.md#step-N)` tags in `telesma/state/PLAN.md`.
- **Write from the user's perspective**: *"The user clicks X. The system shows Y."* — not *"the POST /api/foo endpoint returns JSON"*. Describe technical goals in other `telesma/spec/` documents (api-spec.md, db-schema.md, ...).
- **Name concrete UI/interactions**: button names, field labels, error messages, status badges. These are the elements the e2e test will look up (`getByRole`, `getByText`, `testID`).
- **Sub-paths** (Path A / Path B / etc.) go **within the same Step** — it is still one e2e test, which can contain a `test.describe()` with variants. Do not split them into separate Steps unless they really are different user flows.
- **Error states / edge cases** — list the ones you want covered by a test (e.g. *"if the email is taken → message: This email is already registered"*). Each becomes an additional assertion in the test.
- **Personas** (if the application has roles) — list them once at the top of the file, then refer to them by name/role.

---

## Personas (example — adapt to the project or delete)

- **Admin** — full access, creates projects, manages users
- **User** — a standard user of the application
- **Guest** — not logged in, limited access

---

## Step 1 — Sign-up and first login

**User**: opens the home page, clicks **"Sign up"**. Fills in the form (email, password, repeat password), clicks **"Create account"**.

**System**:
- Validates the fields (email format, password ≥ 8 characters, passwords must match)
- If the email is taken → message: *"This email is already registered"* (red, under the email field)
- If OK → creates the account, sends a verification email, shows a *"Check your inbox"* screen with a **"Resend"** button

**User**: clicks the link in the email → lands on the login screen with a *"Email confirmed"* toast. Enters the credentials and clicks **"Log in"**.

**System**: verifies the credentials, sets the session, redirects to the **dashboard** with a greeting.

### Edge cases to cover with a test

- Email in an invalid format → message *"Invalid email format"*
- Password too short → message *"Password must be at least 8 characters"*
- Passwords do not match → message *"Passwords do not match"*
- Login attempt without email verification → message *"Confirm your email before logging in"*

---

## Step 2 — Creating the first object (project / document / anything)

**User**: on the dashboard clicks **"+ New project"**. A modal with fields: name (required), description (optional), category (dropdown).

**User** types the name *"My first project"*, picks a category, clicks **"Create"**.

**System**:
- Creates the project with a generated ID
- Redirects to the project screen (`/projects/<id>`)
- Toast: *"Project created"*
- The project list on the dashboard updates on the next visit

### Path A: creating an empty project

The user skips the optional fields and clicks **"Create"** right after typing the name — the project is created, the project screen shows a *"Add your first content"* CTA.

### Path B: creating a project with a description and a category

The user fills in every field — the project screen shows the description under the name + a category badge.

### Edge cases

- Empty name → the **"Create"** button is disabled
- Name > 100 characters → message *"Name too long (max 100)"*

---

## Step 3 — [Title of the next flow]

**User**: [what the user does]

**System**: [what the system does]

[...further steps as the project needs — typically 5-12 Steps for the whole application]

---

## Notes for Telesma (read as AI)

- Every `## Step N — ...` is **a separate e2e test** with the tag `(flow: APP_FLOW.md#step-N)` in PLAN.md. The tag is mapped to a fragment of the file through `telesma/state/SPEC_INDEX.md`, section `## Flows` (line range per Step).
- When implementing the test, treat the prose as a scenario: *"The user types X into field Y"* → `await page.getByLabel('Y').fill('X')`.
- Edge cases from the `### Edge cases to cover with a test` section must go in as separate `test()` or `test.describe()` blocks in the same file.
- Recording file name: `telesma/artifacts/flows/step-N-<slug>.<ext>` (slug = the step title in kebab-case, e.g. `step-1-sign-up-and-first-login.webm`).
