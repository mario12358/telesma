---
kind: command
run: python3 run.py
check: python3 run.py --check
when: commit, ci
scope: changed
on_failure: block
---

# Check: secrets

A secret in the repository stays in git history forever — deleting it in the next commit
does not undo it, it has to be revoked. That is why this check runs **before** the commit.

**What it catches.** Keys in known formats (AWS, GitHub, GitLab, Slack, OpenAI/Anthropic,
Google, Stripe, JWT, PEM private keys) and files that are secrets by name (`.env`,
`*.pem`, `id_rsa`…) — these block. A password/token assignment in code (`password = "…"`) only
warns: in tests and fixtures it is often deliberate.

**Tool.** When `gitleaks` is in PATH, the check uses it (several hundred rules) and adds
its own file-name rules. Without it the built-in mode runs — a dozen rules from this module.
The validator at startup says which mode is active.

**What it does not do.** It never prints the secret's content — the log and the message for
Claude carry the rule, file, line and a fingerprint (a SHA digest). It does not scan git history
(only the files in scope for the point).

False positive (e.g. a test key from a vendor's documentation) → an exception in
`telesma/state/CHECK_EXCEPTIONS.md` by fingerprint, written by the human.
