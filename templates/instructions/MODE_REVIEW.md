## 12. Code review mode (chosen in the console at start)

After loading the context, the `telesma.sh` script asks the user for the working mode (a console menu or the `-m 1/2/3` flag). **Code review** mode (mode=3) is a local, context-aware code review — Claude uses `telesma/spec/`, `telesma/guidelines/` and `PROJECT_CONTEXT.md` as **criteria** (which external tooling/`/ultrareview` does not know about). The result is written to `telesma/state/REVIEWS.md` (write-only, append).

You recognise the mode by the `MODE: review` directive at the end of the startup prompt.

### Rules on entering review mode

1. Do NOT run the cycle of section 1 (autonomous task selection)
2. Do NOT process `telesma/changes/` (section 0.3 skipped)
3. Do NOT modify PLAN.md (TODOs from a review are **suggestions** for the user; the user takes them up in mode 1)
4. Greet the user briefly and present the scope options (step 1 below)
5. Wait for the choice of scope

### Step 1: Choosing the scope

Ask the user:
```
Code review mode active. Choose the scope:
  a) Uncommitted changes (git diff)
  b) The last commit (HEAD)
  c) Branch vs main (git diff main...HEAD)
  d) A specific task from PLAN.md (give the number, e.g. 3.2)
  e) Selected files (give a list of paths)
```

After the answer:
- **a** → `git diff` (Bash) + `git diff --stat` (file list)
- **b** → `git show HEAD --stat` + `git show HEAD` (diff)
- **c** → `git merge-base HEAD main` → `git diff <base>...HEAD` + file list
- **d** → find the commit hash for that task in `telesma/state/REPORT.md` (or with `git log --grep="Telesma: ... X.Y"`), then `git show <hash>`; also read the task description from PLAN.md (tags `spec:`, `tech:`, `requires:`)
- **e** → read the given files with the Read tool

If the scope is empty (e.g. no uncommitted changes) → tell the user and go back to the choice.

### Step 2: Mapping the context and loading the criteria

For each changed file:

1. **Find the task in PLAN.md** that changes this file (through commits: `git log --oneline --stat -- <file>` — Telesma's commits carry the task description in the message)
2. **From the task** extract the tags `(spec: ...)`, `(tech: ...)`, `(ui-*: ...)`
3. **Load the criteria** (before the analysis):
   - The spec fragment through SPEC_INDEX (section 0.1) — only the sections relevant to the task
   - `telesma/guidelines/general.md` + one file per `(tech: ...)` tag (section 0.2)
   - `telesma/state/PROJECT_CONTEXT.md` — architectural decisions (if the file concerns an area described there)
4. **No mapping to a task** (files outside PLAN.md, e.g. configuration, dotfiles) → load only `general.md` + guidelines deduced from the file extension (`.py` → `python.md`, `.tsx` → `react.md` + `typescript.md`)

### Step 3: Raising findings

Analyse the scope along these dimensions (you MUST consider EACH):

| Dimension | What to check |
|--------|--------------|
| **Conformance with the spec** | Does the implementation fulfil the requirement from the relevant spec section? Was an edge case described in the spec left out? |
| **Conformance with the guidelines** | Naming, structure, error handling, tests — per telesma/guidelines/ |
| **Tests** | Are there tests? Do they cover the scenarios from the spec? Are the assertions meaningful (not just "does not throw")? No regression in the full suite? |
| **Security** | OWASP top 10 where relevant: command injection, XSS, SQL injection, auth bypass, secrets in code, unvalidated input |
| **Clean code** | Function length, duplication, readability, naming, dead code, premature abstractions |
| **Consistency with the rest of the code** | Does it use the patterns already used in the project (PROJECT_CONTEXT)? Does it introduce a new convention without a reason? |
| **Performance** | Obvious traps: N+1 queries, unnecessary loops, sync I/O on a hot path, missing indexes |

Classify every finding by severity:

- 🔴 **Blocker** — a functional bug, security, a broken contract, a violation of a spec requirement, a missing test of a critical path
- 🟡 **Important** — a guideline violation, a missing edge-case test, a code smell affecting maintainability, inconsistency with the rest of the code
- 🟢 **Suggestion** — cosmetics, a naming nit, a small refactor, formatting, a comment to tidy up

**Finding format** (for presenting to the user):
```
🔴 src/auth/login.py:42-50
Problem: the password is not hashed before comparison — login compares plain text with the DB.
Spec: auth-requirements.md:120-135 requires bcrypt.
Suggestion: use bcrypt.checkpw(password.encode(), user.password_hash).
```

### Step 4: Interaction per finding (fix policy)

**Batch policy for 🟢 (suggestions):**
1. After raising all findings, show the user the LIST of 🟢 in one go (1 line per finding)
2. Ask: "Auto-fix all 🟢 as a batch? (yes/no/choose)"
   - **yes** → apply ALL 🟢 changes + ONE commit `Telesma: review-fix (cosmetic) [scope]`
   - **no** → mark them all as "accepted (skipped batch)"
   - **choose** → go per finding as for 🟡 below
3. After the batch run the tests from `telesma/config.md` — if there is a regression, revert the commit (`git revert`) and report to the user

**Gated policy for 🔴🟡 (per finding):**
For each 🔴 and 🟡 ask the user for a decision:
- **fix** → apply the change, run the tests of the area, commit as `Telesma: review-fix [short description]` (if `Auto-commit: yes`)
- **skip / accept** → record as "accepted as-is" + a short comment from the user (why)
- **task** → propose the task content for PLAN.md (phase, tags, description), record as "TODO" — the user adds it themselves in mode 1
- **question** → answer, go back to the decision

Order: 🔴 first (blockers), then 🟡, then the 🟢 batch at the end.

### Step 5: Writing to `telesma/state/REVIEWS.md`

After going through all findings, append an entry (Edit, append):

```markdown
## YYYY-MM-DD HH:MM — Review [scope]
**Scope**: [git range / file list / task X.Y]
**Command**: [the exact git diff command or the source]
**Criteria**: [spec sections, tech guidelines: ..., PROJECT_CONTEXT decisions]
**Files**: [list of changed files, max 10 — beyond that "... +N more"]
**Findings**: 🔴 N | 🟡 N | 🟢 N

### Findings
- 🔴 file.py:42 — [short description] → fixed (commit abc1234)
- 🟡 file.ts:88 — [short description] → accepted (user's comment: "deliberate decision, performance")
- 🟢 file.py:120 — [short description] → auto-fixed (commit def5678, batch)

### Actions
- **Fix**: [list of commits with fixes — hash + title]
- **TODO**: [list of findings → new tasks for PLAN.md, e.g. "Phase 4: add rate limiting for /api/auth"]
- **Accepted**: [findings as-is + the user's reason]

### Verdict
[2-3 sentences: is the scope ready to merge, what needs completing, is it worth running /ultrareview for a wider context]
```

Date format from `date '+%Y-%m-%d %H:%M'`.

After writing — stay in review mode, wait for the user's next instruction (a new scope, a question, finishing).

### What NOT to do in review mode

- Do not modify PLAN.md (TODOs are only suggestions — the user adds them themselves in mode 1)
- Do not modify `telesma/spec/`, `telesma/changes/`
- Do not log to `DECISIONS.md` (section 10) or `BUGFIXES.md` (section 11)
- Do not commit 🔴🟡 without the user's explicit OK
- Do not run the 🟢 batch if the scope is large (>50 🟢 findings) — then ask the user for a decision per subgroup
- Do not try to run `/ultrareview` or other user-triggered tools from bash/a Tool

### Boundary vs `/ultrareview`

`/ultrareview` is a **user-triggered, billed, multi-agent cloud review** (Anthropic) — Claude in the session **cannot run it**. Mode 3 is the **local + context-aware** counterpart:

| Feature | Mode 3 (local) | /ultrareview (cloud) |
|-------|------------------|----------------------|
| Started by | `./telesma.sh -m 3` | The user types `/ultrareview` in the CLI |
| Context | Full (spec, guidelines, PROJECT_CONTEXT) | The branch's code only |
| Criteria | Project-specific | Universal best practices |
| Multi-agent | No (one session) | Yes (many agents) |
| Cost | A standard session | Billed on top |
| Result | `telesma/state/REVIEWS.md` | Cloud UI |

Complementary tools. In the verdict mode 3 may **suggest** that the user run `/ultrareview` for:
- Large scopes (a whole branch with a diff >2000 lines)
- Critical modules (auth, payment, security)
- A second, independent opinion before merging into main

NEVER try to run `/ultrareview` yourself (through Bash or a tool) — it needs a user gesture in the CLI.

---
