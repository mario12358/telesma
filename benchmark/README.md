# Telesma's frozen benchmark

The same small project, built from scratch on a given framework version and judged by tests
Telesma never sees. It answers one question: **did a framework change improve the result of the
work** — regardless of the team's projects growing and the models changing.

```bash
python3 benchmark/bench.py run --telesma <git ref or tag> --label before -n 3   # version before the change
python3 benchmark/bench.py run --telesma current          --label after  -n 3   # version after the change
python3 benchmark/bench.py compare
```

To compare two Telesma versions, run one series per version with `--telesma` pointing at each of them
(a tag, a branch, a commit, or `current` for the working tree) and a `--label` that names the series,
then `compare` prints them side by side. The default label is `v<TELESMA_FORMAT>` of the version run.

**Cost — read this before you start a series.** Every run is a real Telesma session on your Claude
subscription. The first full run (Fable 5.1, 2026-09-19) used 1.1M output tokens in 48 minutes and
**exhausted the session limit** halfway through stage B — until the limit renewed, no work was
possible outside the benchmark either. That is why the default mode starts from the frozen state after
stage A (half the cost), and the harness recognises the limit message, flags the result as interrupted,
leaves it out of the comparison and stops the series. Run series when you do not need Claude for
anything else, or on a cheaper model (`--model`).

`--telesma` takes a git ref (the harness creates a separate working tree in `~/.cache/telesma-bench/telesma/`,
the current repo stays untouched), a path, or `current`. `--model` sets `ANTHROPIC_MODEL` —
**compare series run on the same model**, otherwise you measure the model, not the framework.

## What is frozen

| Directory | What | Does Telesma see it? |
|---|---|---|
| `project/telesma/spec/` | specification of the "Library" service (REST, Python standard library only, system time stored in the database — zero dependencies and zero clock) | yes |
| `project/telesma/state/PLAN.md`, `SPEC_INDEX.md` | a ready plan of 12 tasks and the index — clarification is skipped, because its outcome depends on a human's answers | yes |
| `start_b/` | the project's state AFTER stage A: code, 117 tests and state files from a run that passed the stage A judge at 100% — the default starting point | yes |
| `changes/` | four change requests, copied into the project's `telesma/changes/` in stage B | yes, in stage B |
| `hidden/test_stage_*.py` | the judge: 23 tests for stage A, 43 for stage B, over HTTP only | **no** |
| `hidden/reference/` | reference implementation — it exists so the judge has something to prove its own correctness on | **no** |

The workspace is created in `~/.cache/telesma-bench/runs/` and the harness copies into it only
`project/` and `changes/`. Any change in `project/`, `changes/` or `hidden/` changes the **benchmark
fingerprint**; `compare` flags results with a different fingerprint, because they are not comparable.

## Two stages

By default a run covers **stage B only**, starting from `start_b/`. Stage A costs half a run, the
rules about `telesma/changes/` do not act in it, and a shared starting codebase reduces the spread between
runs — the difference is then made by the framework, not by how the skeleton happened to turn out.
`--full` starts from an empty project (A + B); the results of the two modes are compared separately.

- **A** — spec + plan → `telesma.sh -m 1`, resumed until the plan is checked off → stage A judge.
- **B** — the four change requests land in `telesma/changes/` → Telesma once more → A+B judge (regression
  included; two fine tests from stage A are replaced in B, because a change request deliberately changes the rule).

Stage B matters more: `telesma/changes/` is the main channel through which projects grow, and the change requests
were built around the defect classes from the first retro session:

| Change request | Trap |
|---|---|
| reminders | a mechanism triggered by the day change — easy to build as a tested service and never wire to `POST /system/day`; a jump of several days and "at most once" |
| audiobooks | a new type in **seven** places: creation, filter, limit, fine, report, CSV, notifications — the classic "added in one place, missed in another" |
| grace day | a change to a completed task (rework phase) — and a boundary: the grace applies to money, not to the due date |
| reservations | a queue with 2+ entries, expiry on the day change (wiring again), a copy set aside ≠ available |

## Can the judge be trusted

```bash
python3 benchmark/hidden/check_judge.py
```

Two conditions: the reference implementation passes everything (the judge requires nothing beyond
the spec and the change requests), and each of the reference's five deliberate faults is caught (the
judge catches what it was built for). Run it after every change in `hidden/`.

## How to read the result

- **judge A %, judge B %** — the main measure: how many behaviours seen from outside work.
- **own tests** next to the judge — "green at my end" versus the result from outside is exactly the gap
  the benchmark is meant to measure.
- **minutes, out tokens** — cost. A rule that raises the judge score by 2 points and doubles the time
  is a different decision from the same improvement for free.
- **AC entry** — how many `- AC: entry` lines Telesma wrote into the plan; it checks whether the rule
  from section 0.3 fired at all, before you start crediting it with an effect.
- **Ceiling effect.** If every series reaches 100% (23/23 and 43/43), the benchmark on that model does
  not separate quality — only the cost comparison is left. Then: a weaker model (on it the framework's
  rules weigh more) or harder change requests, i.e. a new fingerprint.
- **One run is an anecdote.** The model is not deterministic — a series of `-n 3` is the minimum,
  and a difference smaller than the spread within a series proves nothing.

**History.** The first series (stage B, internal framework versions 7 and 8 interleaved, three runs
each) hit the ceiling: every run scored 43/43, so the benchmark is too easy to separate quality. What it
did show was cost — the rules added in version 8 were actually executed and cost about four minutes per stage.

Result files (`results/*.json`) land in `benchmark/results/`: they are the measurement you come back to
with the next version. Telesma's log and the whole workspace stay in `~/.cache/telesma-bench/runs/`.
