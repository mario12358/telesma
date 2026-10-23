---
kind: rule
run: python3 run.py
when: commit, phase, release, ci
scope: changed
on_failure: block
---

# Check: weakenings

A **weakening** is a place where a safeguard was deliberately switched off or a workaround
added "for a moment": a TOTP code shown under the login form, TLS verification disabled,
debug mode, a login bypass for manual testing, a mutant from a mutation test. It is sometimes
needed — but it must not reach a release unnoticed.

## Marker

Every weakening gets a comment in the code, on the same line or the line above:

```
telesma: weakening <id> — <reason and removal condition>
```

e.g. `# telesma: weakening totp-preview — TOTP code under the login form, the owner lost
their authenticator; remove before deployment`. The marker is the register: the list of open
weakenings is `grep -rn "telesma: weakening"`.

## What blocks and what warns

| Point | Blocks | Warns |
|---|---|---|
| commit | marker without an id or without a reason; `MUTANT` in code | a weakening pattern **without** a marker (TLS off, debug, `csrf_exempt`, `skip_auth`…) |
| phase | `MUTANT` | every open weakening (a reminder) + patterns without a marker |
| release | **every open weakening**, `MUTANT` | patterns without a marker |

Patterns in test files (`tests/`, `*_test.*`, `*.spec.*`, `test_*`) are skipped — tests
legitimately do all of this. `MUTANT` is not skipped: a mutant left in a test also means
someone abandoned a mutation test halfway.

A weakening is removed together with its marker. A release with a weakening that is meant to
stay (e.g. a demo environment) needs an exception by fingerprint in `telesma/state/CHECK_EXCEPTIONS.md` —
written by the human.
