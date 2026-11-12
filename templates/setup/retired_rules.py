#!/usr/bin/env python3
"""Allow rules Telesma used to write and no longer does (format 23).

Since format 21 the task tool commits, tags the phases, pushes and opens the PRs, and the "code
only" guard refuses those commands from the agent. The rules that used to allow them are dead
weight: they show up in the trust gate as things that "run on this machine", and they invite the
model to try a command that will be refused. The format gate removes them once from
telesma/config.md (## Permissions → Allowed commands) and from .claude/settings.local.json —
from both, or the permission sync would bring them back from the other one.

    retired_rules.py apply <project>     prints the number of rules removed

When ## Permissions was confirmed on this machine before, it is confirmed again after: removing a
rule only takes a right away, and the trust gate would otherwise ask about a section whose only
change is what it no longer allows.

Python 3.9+, standard library only.
"""
import json
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import trust  # noqa: E402

RETIRED = [
    # the task tool commits and tags (formats 21, 22)
    'Bash(git add:*)', 'Bash(git commit:*)',
    'Bash(git tag -f telesma/phase-:*)', 'Bash(git tag telesma/phase-:*)',
    # the GitHub integration: the task tool pushes, rebases and opens the PR (section 17)
    'Bash(git push -u origin task-:*)', 'Bash(git push origin task-:*)',
    'Bash(git push --force-with-lease origin task-:*)',
    'Bash(git pull:*)', 'Bash(git rebase:*)', 'Bash(gh pr create:*)',
    # written by versions before the narrower tag rules
    'Bash(git tag:*)',
]
MD_ESCAPE = re.compile(r'\\([*_\[\]()#.`-])')


def rule_of(line):
    m = re.match(r'^\s+-\s+(.+?)\s*$', line)
    return MD_ESCAPE.sub(r'\1', m.group(1).strip('`')) if m else None


def strip_config(text):
    """`Allowed commands` of ## Permissions without the retired rules; (text, removed)."""
    lines = text.split('\n')
    out, inside, field, removed = [], False, False, 0
    for line in lines:
        if line.startswith('## '):
            inside = line.rstrip() == '## Permissions'
            field = False
        elif inside and line.startswith('- **'):
            field = line.startswith('- **Allowed commands**:')
        elif inside and field and rule_of(line) in RETIRED:
            removed += 1
            continue
        out.append(line)
    return '\n'.join(out), removed


def atomic_write(path, text):
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix='.telesma-')
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write(text)
    try:
        os.chmod(tmp, os.stat(path).st_mode & 0o777)
    except OSError:
        pass
    os.replace(tmp, path)


def apply(project):
    removed = 0
    config = trust.config_path(project)
    text = trust.read_config(project)
    if text is not None:
        was_trusted = 'Permissions' not in trust.untrusted(project)
        new, n = strip_config(text)
        if n:
            atomic_write(config, new)
            removed += n
            if was_trusted:
                trust.stamp(project, ['Permissions'])
    settings = os.path.join(project, '.claude', 'settings.local.json')
    try:
        with open(settings, encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = None
    perms = data.get('permissions') if isinstance(data, dict) else None
    allow = perms.get('allow') if isinstance(perms, dict) else None
    if isinstance(allow, list):
        kept = [r for r in allow if r not in RETIRED]
        if len(kept) != len(allow):
            removed += len(allow) - len(kept)
            perms['allow'] = kept
            atomic_write(settings, json.dumps(data, indent=2, ensure_ascii=False) + '\n')
    return removed


def main(argv):
    if len(argv) == 3 and argv[1] == 'apply':
        print(apply(argv[2]))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv))
