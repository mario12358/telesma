---
kind: rule
run: python3 run.py
when: commit, ci
scope: changed
on_failure: block
---

# Check: tests

A green suite in which part of the tests were quietly switched off is worse than a red one — someone
looks at a red one. The retro showed where this comes from: 53 of 134 problem-log entries were changes
to existing tests (a test pinned to the implementation, not to the rule), and the benchmark put 208
green tests of Telesma's own next to an outside judge. This check catches weakened tests at commit
time, before they reach history.

## What blocks and what warns

| Rule | Severity | What it catches |
|---|---|---|
| `only` | block | `.only(`, `fit(`, `fdescribe(` in a JS/TS test file — switches off the rest of the suite |
| `skip-without-reason` | block | `@pytest.mark.skip` / `skipif` without `reason=`, `@unittest.skip()` without text, `it.skip(` / `test.skip(` / `describe.skip(` / `xit(` / `xdescribe(` without a `// skip:` / `// reason:` comment on the same line or the line above, Go `t.Skip()` without an argument, Rust `#[ignore]` without `= "…"`, Java/Kotlin `@Disabled` / `@Ignore` without text |
| `skip-with-reason` | warn | the same constructs with a justification — a reminder that the suite is green without this test |
| `test-deleted` | block | a test file deleted in this commit while the tested module (by name: `test_foo.py` ↔ `foo.py`, `Foo.test.tsx` ↔ `Foo.tsx`, `foo.spec.ts` ↔ `foo.ts`, `foo_test.go` ↔ `foo.go`, `FooTest.java` ↔ `Foo.java`) still exists in the repo; the module disappearing together with the test → cleanup, passes |
| `test-without-assertion` | warn | a test function (`def test_…`, `it(`, `test(`, `func Test…`) without `assert` / `expect(` / `should` / `t.Error` / `t.Fatal` / `require.` / `pytest.raises` / `toThrow`; also an empty assertion: `assert True`, `assert 1`, `expect(true).toBe(true)`, `expect(1).toBe(1)` |
| `code-without-test` | warn | the commit has a code file in a code directory and no test file at all — **one** finding per commit, fingerprint from the file list |
| `test-pinned-to-code` | warn | a code ↔ test pair (by name) and **both** modified (status M); a line with test content was removed or changed in the test — if the test change follows from the implementation, not from the rule, the test guards the implementation. New code with a new test (A + A) is the norm; a test that only got new cases is too — changed imports, blank lines and comments do not count (an extended import gave a false warning on a production project) |
| `fewer-assertions` | warn | in a modified test file the number of `assert` / `expect(` dropped compared to the base version |

**Test files** are recognised by the same rule as in `weakenings` (`tests/`, `__tests__/`, `spec/`,
`e2e/`, `test_*`, `*.test.*`, `*.spec.*`, `*_test.*`). Rust `#[ignore]` is checked in every
`.rs` — Rust tests live in `#[cfg(test)]` inside the module file.

**Code directories** (`code-without-test`): `src`, `app`, `lib`, `backend`, `frontend`, `server`, `client`,
`api`, `pkg`, `internal`, `cmd`, `packages`, `apps`, `services`, `core`, `domain`, `web`, `mobile`
and files in the repo root (flat project). The list can be overridden in the config: `- **Code directories**:
src, app` in the `### tests` subsection. Skipped as files without logic: names starting with a dot, `*config*`,
`settings.py`, `conftest.py`, `__init__.py`, `setup.py`, `manage.py`, `types.ts` / `constants.py` /
`enums.py`, `*.d.ts`, an `index.ts` that only re-exports, directories `migrations/`, `alembic/`,
`scripts/`, `tools/`, `docs/`, `.github/`; Markdown / JSON / CSS / YAML are not code.

## Comparison base

At `commit` the base is `HEAD` (status A/M = whether the file is in HEAD; previous version =
`git show HEAD:<file>`; deletions = index ∪ working tree, because deleted files do not come
on stdin from the runner). In CI the base is the merge-base with `TELESMA_SINCE` (when set), `origin/main` or
`origin/master`; without any of them the rules that depend on the previous version (`test-deleted`,
`test-pinned-to-code`, `fewer-assertions`) are skipped — the content rules (`only`, skips, assertions)
and `code-without-test` always run.

## What it does not do

It does not run the tests and does not read their results — the suite does that. An asserting helper is
recognised by name only (`self.check_…`, `self.verify_…`, `self.ensure_…`) — any other helper gives a false
warning; hence `test-without-assertion` only warns. It does not
recognise `pytest.skip()` called inside a test body (a skip conditional on the environment can be legitimate).
It does not treat `fit:` as a focus (an object key `{ fit: 'cover' }` in a fixture would give a false block).
Code ↔ test pairing goes by file name, not by imports: a test `tests/test_api_flow.py`
without a module `api_flow.py` has no pair and takes no part in `test-pinned-to-code` or `test-deleted`.

False positive (e.g. `.only` in a fixture that is itself the text of a test) → an exception by fingerprint
in `telesma/state/CHECK_EXCEPTIONS.md`, written by a human. The fingerprint of `only` / skips is the line content without
whitespace — it survives line shifts; the fingerprint of `code-without-test` is the file list, not a location.
