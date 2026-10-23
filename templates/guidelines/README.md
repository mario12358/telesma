# telesma/guidelines/

Technology guidelines that Telesma loads while working on tasks from telesma/state/PLAN.md.

## How it works

1. `telesma.sh` copies this whole directory into the project on the first run (`project/telesma/guidelines/`)
2. While generating `telesma/state/PLAN.md`, Claude assigns `(tech: <tag>, ...)` tags to every task, based on the guidelines index and the task's context
3. When working on a task, Claude loads `general.md` + one file per tag
4. The guidelines steer the style of the generated code (conventions, structure, tests, what to avoid)

## File format

Every guideline file has YAML frontmatter:

```markdown
---
tag: react
keywords: react, hooks, jsx, tsx
---

# Guidelines: React
...
```

- `tag` — the **unique name** used in telesma/state/PLAN.md: `(tech: react)`; equal to the file name without `.md`
- `keywords` — 8–14 lowercase, comma-separated terms a task description would contain (libraries, tools, concepts); they are the only thing Claude sees in the index when assigning tags, so they decide the match

The index lists every `*.md` file in this directory that has a `tag:` line (README.md is skipped). No `tag:` = the file is left out of the index.

Recommended sections: `## Style`, `## Project structure`, `## Tests`, one to three technology-specific sections, `## What to avoid`. 50–90 lines of bullets, one rule per bullet, no prose. A guideline must not repeat what `general.md` already says.

## general.md

`general.md` is **always loaded**, regardless of the task's tags. It holds universal rules (clean code, tests, git, error handling) that apply to every language.

## Adding your own guidelines

1. Create a new file `<tag>.md` in `telesma/guidelines/`
2. Add frontmatter with `tag` and `keywords`
3. Describe: conventions, project structure, tests, what to avoid
4. Restart Telesma — the new tag shows up in the index and Claude will use it

## Modifying existing ones

Edit the files in `telesma/guidelines/` freely — **your local changes win**. On every start Telesma compares each project file with the template version it last delivered (hash in `telesma/state/.telesma-manifest`): a file you have not edited is updated to the newer template silently; a file with local changes is left alone and you get a one-time warning with a `diff` command to merge by hand. New template files are copied in.

## Priorities on conflict

The more specific guideline wins over the general one:

- `python.md` (language) > `general.md` (universal)
- Project guideline (local edits) > default template from `templates/guidelines/`
- When a guideline conflicts with the specification → the spec wins (but Claude should ask)

## Behaviour on a missing tag

If a task has `(tech: xyz)` and there is no `xyz.md` in `telesma/guidelines/` → Claude stops with `TELESMA BLOCKED` and asks whether to add the guideline. It does not guess conventions for an unknown technology.
