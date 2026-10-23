---
tag: github-actions
keywords: github actions, workflow, ci, cd, pipeline, runner, job, matrix, cache, artifact, secrets, pull_request, release, actionlint
---

# Guidelines: GitHub Actions

## Style

- One workflow file per concern in `.github/workflows/`: `ci.yml` (lint, test, build on every PR), `release.yml` (tags), `deploy-<env>.yml`, `scheduled.yml`; the workflow `name:` equals the file name
- Job and step ids in `kebab-case`; every `run:` step has a `name:` that is a verb phrase ("Run unit tests")
- Every third-party action pinned to a full commit SHA with the tag as a trailing comment: `uses: actions/checkout@<40-hex-sha> # v4.2.2`; Dependabot (`package-ecosystem: github-actions`) bumps them
- `permissions: { contents: read }` at the top of every workflow; a job that needs more declares its own `permissions:` — never `write-all`
- `defaults: { run: { shell: bash } }` so `set -eo pipefail` applies to every `run`; a script longer than ~10 lines moves to `scripts/ci/<name>.sh` and is called from the step
- `timeout-minutes:` on every job (15–20 for CI); never the 6-hour default
- `${{ }}` only in `with:`, `env:` and `if:` — never inside a `run:` body (see Security)
- `runs-on: ubuntu-latest` unless a job needs another OS; an OS matrix is a deliberate decision
- Format with `prettier --parser yaml`, lint with `actionlint`; run them, do not argue with them

## Project structure

- `.github/workflows/` — workflows; `.github/actions/<name>/action.yml` — local composite actions for repeated step sequences (toolchain setup, registry login); `.github/workflows/_reusable-<name>.yml` — reusable workflows (`on: workflow_call`) shared across jobs or repositories
- `ci.yml` has parallel jobs (`lint`, `test`, `build`) and a final `ci-ok` job with `needs: [lint, test, build]`, `if: always()`, that fails when any `needs.*.result != 'success'`; branch protection requires only `ci-ok`
- Triggers: `pull_request` + `push: branches: [main]` for CI; `workflow_dispatch` with typed `inputs:` on anything a human may rerun; `schedule` only in its own workflow (drift, audits)
- `concurrency: { group: ${{ github.workflow }}-${{ github.ref }}, cancel-in-progress: true }` on CI; on deploy workflows the same group **without** `cancel-in-progress` — a deploy is queued, never cancelled mid-way
- `paths:` filters for monorepos (`paths: ['backend/**', '.github/workflows/ci.yml']`); when a filter can skip a required check, a sibling workflow with the same job names exits 0 so branch protection stays satisfiable
- Deploy jobs use `environment: production` (required reviewers, environment-scoped secrets), `needs:` the build job and consume its artifact — they never rebuild
- Matrix: `strategy: { fail-fast: false, matrix: { node: [20, 22] } }`; `include:` for one extra combination, `exclude:` for one broken one; artifacts from matrix jobs carry the matrix key in their name

## Tests

- `actionlint` is the unit test of a workflow: it runs in `ci.yml` on `.github/**` changes and in pre-commit
- `act -j <job>` locally for `run`-step logic before pushing; what `act` cannot run (OIDC, environments) is tested with a `workflow_dispatch` run on a branch
- Test results as JUnit XML (`pytest --junitxml=…`, `vitest --reporter=junit`, `go test … | go-junit-report`) uploaded with `actions/upload-artifact` under `if: always()` and rendered on the PR by a test-reporter action
- `actions/upload-artifact` always with `name:`, `path:`, `retention-days:` (short for CI, 90 for releases) and `if-no-files-found: error`; later jobs `actions/download-artifact` by the same name
- Lint, typecheck, unit tests and coverage as separate jobs so a failure is readable in the checks list, not buried in one log
- A reusable workflow has its own `test-<name>.yml` caller that runs on PRs touching it
- A flaky job is fixed, not wrapped in a retry action — the retry hides the failure it was added for

## Caching and speed

- Toolchain setup through `actions/setup-node` / `setup-python` / `setup-go` / `setup-java` with `cache:` on and `cache-dependency-path:` pointing at the lockfile in monorepos; no hand-rolled `actions/cache` for package managers these actions cover
- `actions/cache` only for what setup actions do not cover (build outputs, Docker layers via `cache-from: type=gha`); key = OS + a version prefix you bump to invalidate + lockfile hash: `key: ${{ runner.os }}-build-v2-${{ hashFiles('**/package-lock.json') }}`, with `restore-keys:`
- Install with the frozen command (`npm ci`, `pnpm install --frozen-lockfile`, `uv sync --locked`, `pip install -r requirements.txt` with hashes) — CI never updates a lockfile
- Default shallow clone; `fetch-depth: 0` only in jobs that need history (changelog, version from tags)
- Container images built once in `build`, pushed by digest, the digest passed as a job `outputs:` value to `deploy`

## Security

- `pull_request_target` only when a job must label or comment on fork PRs, and then: `permissions` limited to `pull-requests: write` / `issues: write`, no checkout of the PR head (`ref: ${{ github.event.pull_request.head.sha }}` is forbidden there), no build or test of fork code, no secrets in steps that read PR content
- Script injection: PR titles, bodies, branch names (`github.head_ref`), commit messages, issue and review text are attacker-controlled. Pass them through `env:` and use the variable in the script (`env: { TITLE: ${{ github.event.pull_request.title }} }` → `"$TITLE"`), never interpolate them into `run:`
- Cloud credentials through OIDC: `permissions: { id-token: write }` + the provider's credentials action with a role identifier; no long-lived cloud keys in secrets
- Secrets only from `secrets.*`, injected via `env:` into the one step that needs them; never echoed, never written to artifacts or job outputs (masking is best-effort)
- `actions/checkout` with `persist-credentials: false` unless the job pushes; a PAT only for unavoidable cross-repo access, stored as an environment secret
- Release artifacts and images get provenance (`actions/attest-build-provenance`, `cosign`); version tags are created by the release workflow from a reviewed commit and never force-moved
- Public repositories never run `pull_request` jobs on self-hosted runners

## What to avoid

- `uses: org/action@main` or `@v1` without a SHA — a compromised tag is a compromised pipeline
- `${{ github.event.* }}` inside `run:`; `pull_request_target` with a checkout of the PR head; no `permissions:` block or `write-all`
- `continue-on-error: true` on a test or lint step to make the check green; `if: false` to "temporarily" disable a job
- `npm install` / `pip install` without a lockfile in CI; caching `node_modules` instead of the package-manager cache
- Secrets in `echo`, in `set -x` output, in job outputs, in artifacts
- A deploy job that rebuilds instead of promoting the tested artifact; deploying from a `pull_request` run
- `cancel-in-progress: true` on a deploy workflow; `schedule` on a workflow that also runs on `pull_request`
- A 400-line `run:` script in YAML — move it to `scripts/ci/` where it can be linted and run locally
- `workflow_run` chains to pass data between workflows when `needs:` plus artifacts within one workflow do the job
- A matrix job whose artifacts all upload under the same name (the last one wins)
