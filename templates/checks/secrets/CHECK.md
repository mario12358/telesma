---
kind: command
run: python3 run.py
check: python3 run.py --check
when: commit, ci
scope: changed
on_failure: block
filter: none
---

# Check: secrets

A secret in the repository stays in git history forever — deleting it in the next commit
does not undo it, it has to be revoked. That is why this check runs **before** the commit.

**What it catches.** Keys in known formats (AWS, GitHub incl. `github_pat_`, GitLab, Slack tokens and
webhooks, OpenAI/Anthropic, Google, Stripe, Hugging Face, npm, PyPI, SendGrid, DigitalOcean, PEM / PGP
private keys — also inside quoted strings), the same formats split into adjacent string literals
(`"AKIA" + "…"`, also across a line end: `<rule>-split`) or wrapped in base64 (`<rule>-base64`), a login
in an address (`scheme://user:password@host` → `url-credentials`) and files that are secrets by name
(`.env`, `*.env`, `*.env.*`, `*.pem`, `id_rsa`…) — these block. `url-credentials` to localhost or a bare
service name, a JWT, and a password/token assignment in code only warn. The assignment rule reads the
NAME with any prefix (`password`, `DB_PASSWORD`, `aws_secret_access_key`, `SECRET_KEY`, `stripe.apiKey`)
and, in env files, a bare `NAME=value`; in a test file (by name **and** by content) it is silent.

**What it reads.** Every file in scope (`filter: none`): no size limit, long lines in overlapping
windows, lockfiles, minified bundles, binaries and `.claude/` included.

**Tool.** The built-in rules always run. When `gitleaks` is in PATH its rules (several hundred) are
added; the project's `.gitleaks.toml` / `.gitleaksignore` can silence gitleaks only — a line gitleaks
did not report is still read by the built-in rules. The validator at startup says which mode is active.

**What it does not do.** It never prints any part of the secret — the log and the message for Claude
carry the rule, file, line, the **length** of the value and a fingerprint. For `secret-assignment` and
`url-credentials` the fingerprint is computed from the name / the address, not from the value (a short
hash of a weak password can be guessed, and the exceptions file is committed) — so an exception covers
that name in that file. It does not scan git history (only the files in scope for the point). No pattern
finds a secret assembled at run time or encoded in a way of its own.

False positive (e.g. a test key from a vendor's documentation) → an exception in
`telesma/state/CHECK_EXCEPTIONS.md` by fingerprint, written by the human.
