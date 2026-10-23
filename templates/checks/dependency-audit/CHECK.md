---
kind: command
run: python3 run.py
when: phase, release, ci
scope: all
on_failure: block
---

# Check: dependency audit

Known vulnerabilities in the installed versions of dependencies, according to the
[OSV](https://osv.dev) database (the same one `osv-scanner` uses; it aggregates GitHub
Advisories, PyPA, npm and others). No tool needs to be installed.

**What it reads.** Lockfiles tracked in the repo — regardless of what changed: a vulnerability
in a dependency appears in the database without any change in the project, so this check always
looks at everything. Supported: `package-lock.json`, `npm-shrinkwrap.json`, `pnpm-lock.yaml`,
`yarn.lock`, `deno.lock` (npm packages), `poetry.lock`, `uv.lock`, `Pipfile.lock`,
`requirements*.txt` (only versions pinned with `==`).

| Vulnerability | Severity |
|---|---|
| critical or high, **a fixed version exists**, production dependency | block |
| critical or high without a fix, or in a development dependency | warn |
| medium, low, unrated | warn |
| database unreachable | warn ("not checked") |

It blocks only what can be fixed: a version bump. A vulnerability without a fix is a decision
(a workaround, replacing the package, accepting the risk) — it belongs to the human, not to the loop.

**What leaves the machine.** Package names and versions from the lockfiles go to `api.osv.dev`.
Results are cached in `~/.cache/telesma/` (12 hours).

Accepting the risk (the vulnerability does not apply to how the package is used, the fix breaks
compatibility) → an exception by fingerprint in `telesma/state/CHECK_EXCEPTIONS.md`, written by the human.
The fingerprint is per vulnerability set and package — a new vulnerability in the same package
blocks again.
