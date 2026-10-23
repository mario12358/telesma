---
kind: command
run: python3 run.py
when: commit, ci
scope: changed
on_failure: block
---

# Check: dependencies

Code written by a model has a supply-chain door of its own: the model can "invent" a package
with a plausible name that does not exist in the registry — and anyone can register such a
name, including someone waiting for exactly that (*slopsquatting*). Add to that typos in the
names of popular packages (*typosquatting*) and packages only a few days old.

**What it checks.** Every package that **appeared** in a manifest in this commit
(`package.json`, `requirements*.txt`, `pyproject.toml`, `deno.json`) — compared with the
version in HEAD, so old dependencies are not checked on every commit.

| Signal | Severity |
|---|---|
| the package is not in the registry (npm, PyPI, JSR) | block |
| the package is younger than 7 days | block |
| name 1–2 characters away from a popular package **and** the package is young or rarely downloaded | block |
| name similar to a popular package | warn |
| package younger than 30 days, fewer than 50 weekly downloads (npm), marked deprecated | warn |
| install scripts (`preinstall`/`install`/`postinstall`) — code run on `npm install` | warn |
| dependency from outside the registry (git, URL) — bypasses the registry and its version history | warn |
| an extra package index (`--extra-index-url`, `registry=` in `.npmrc`) — the classic *dependency confusion* route | warn |
| registry unreachable | warn ("not checked") — offline work does not stop |

**What leaves the machine.** Names of new packages go to the public registries — just as
they do on install. Packages from scopes that `.npmrc` points to a private registry
(`@company:registry=…`) are skipped. Results are cached in `~/.cache/telesma/` (one day).

A package that is fine despite a signal (fresh but your own; a deliberately similar name) →
an exception by fingerprint in `telesma/state/CHECK_EXCEPTIONS.md`, written by the human.
