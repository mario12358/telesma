#!/usr/bin/env python3
"""Per-machine trust record for telesma/config.md — the launcher's half.

config.md is committed, so it travels with a clone or a pull request, and it holds values that
run on the machine that starts the project: test commands, the permission mode and the allow
rules, the judge's and the telemetry's endpoint and key command, extra directories. A value
nobody on THIS machine has seen must not run here. The launcher keeps one record per project per
machine with a hash of each such section; a section whose hash differs is shown to the person and
confirmed once (telesma.sh, trust gate).

    path = ${XDG_CONFIG_HOME:-$HOME/.config}/telesma/trust/<key>.json
    key  = sha256(realpath(project_dir))[:32]
    body = {"project": "<realpath>", "sections": {"<Section>": "<sha256>", ...}}

Section hash: the lines of `## <Section>` that start (after indentation) with "- ", right-stripped,
joined with "\n", sha256. Comments and blank lines do not count; a missing section hashes "".
The telemetry collector and the permission judge compute the same hash and only read the record;
this file is the only writer.

    trust.py check <project>                       untrusted section names, one per line
    trust.py stamp <project> [Section ...]         record the current hash (all sections by default)
    trust.py show  <project> --template <config> [Section ...]
                                                   the values that run or connect, for a person
    trust.py mode  <project>                       ## Permissions → Mode; exit 3 when Claude Code
                                                   has no such mode

Python 3.9+, standard library only.
"""

import hashlib
import json
import os
import re
import sys
import tempfile

SECTIONS = ['Tests', 'Integrations', 'Working directories', 'Sandbox', 'Auto-approval', 'Telemetry', 'Permissions']
KNOWN_MODES = ('default', 'acceptEdits', 'plan', 'auto', 'dontAsk', 'bypassPermissions')
FIELD_RE = re.compile(r'^- \*\*(.+?)\*\*:[ \t]*(.*?)[ \t]*$')
ITEM_RE = re.compile(r'^\s+-\s+(.+?)\s*$')
CONTROL_RE = re.compile(r'[\x00-\x08\x0b-\x1f\x7f\x9b]')
# A Markdown editor escapes `*`, `_`, brackets …: `Bash(ls:\*)` is the rule `Bash(ls:*)`.
MD_ESCAPE = re.compile(r'\\([*_\[\]()#.`-])')


def config_path(project):
    return os.path.join(project, 'telesma', 'config.md')


def read_config(project):
    try:
        with open(config_path(project), encoding='utf-8', errors='replace') as f:
            return f.read()
    except OSError:
        return None


def section_lines(text, name):
    out, inside = [], False
    for line in text.split('\n'):
        if line.startswith('## '):
            if inside:
                break
            inside = line.rstrip() == '## ' + name
            continue
        if inside:
            out.append(line)
    return out


def section_hash(text, name):
    kept = [l.rstrip() for l in section_lines(text, name) if l.lstrip().startswith('- ')]
    return hashlib.sha256('\n'.join(kept).encode('utf-8')).hexdigest()


def record_path(project):
    base = os.environ.get('XDG_CONFIG_HOME') or os.path.join(os.path.expanduser('~'), '.config')
    key = hashlib.sha256(os.path.realpath(project).encode()).hexdigest()[:32]
    return os.path.join(base, 'telesma', 'trust', key + '.json')


def load_record(project):
    try:
        with open(record_path(project), encoding='utf-8') as f:
            rec = json.load(f)
    except (OSError, ValueError):
        return {}
    sections = rec.get('sections') if isinstance(rec, dict) else None
    return sections if isinstance(sections, dict) else {}


def untrusted(project):
    text = read_config(project)
    if text is None:
        return []
    stored = load_record(project)
    # A section the config does not have and the record never saw holds nothing that runs: a record
    # written before the section existed is not a reason to ask (the merge adds it, then stamps).
    return [s for s in SECTIONS if stored.get(s) != section_hash(text, s)
            and (s in stored or ('## ' + s) in text.split('\n'))]


def stamp(project, names):
    text = read_config(project)
    if text is None:
        return
    sections = load_record(project)
    for name in names or SECTIONS:
        if name in SECTIONS:
            sections[name] = section_hash(text, name)
    path = record_path(project)
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix='.trust-')
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        json.dump({'project': os.path.realpath(project), 'sections': sections}, f, indent=2, sort_keys=True)
        f.write('\n')
    os.replace(tmp, path)


# --- what a person is shown ---------------------------------------------------------------------

def fields(lines):
    """({label: value}, {label: [list items]}) of one section."""
    values, lists, cur = {}, {}, None
    for line in lines:
        m = FIELD_RE.match(line)
        if m:
            cur = m.group(1).strip()
            values.setdefault(cur, m.group(2).strip())
            lists.setdefault(cur, [])
            continue
        if line.lstrip().startswith('<!--') or line.strip().startswith('#'):
            continue
        m = ITEM_RE.match(line)
        if m and cur:
            lists[cur].append(MD_ESCAPE.sub(r'\1', m.group(1).strip().strip('`')))
    return values, lists


def clean(value):
    return CONTROL_RE.sub('', value)


def key_form(spec):
    """A key as a person may see it: where it comes from, never a literal secret."""
    s = spec.strip()
    if not s or s.lower() in ('none', '-', 'auto') or s.startswith(('env:', 'file:', 'cmd:', '/', '~/')):
        return s or '(empty)'
    return '(a literal value — not shown)'


def unset(value):
    return not value or (value.startswith('[') and value.endswith(']')) or value.lower() == 'none'


def show(project, template, names):
    text = read_config(project) or ''
    try:
        with open(template, encoding='utf-8') as f:
            template_text = f.read()
    except OSError:
        template_text = ''
    out = []

    def add(section, label, value):
        out.append(f'  {section} → {label}: {clean(value)}')

    for name in names or SECTIONS:
        values, lists = fields(section_lines(text, name))
        if name == 'Tests':
            for label in ('Test command', 'Full suite command', 'Smoke suite', 'Linter/formatter', 'Typecheck command'):
                if not unset(values.get(label, '')):
                    add(name, label, values[label])
        elif name == 'Permissions':
            add(name, 'Mode', values.get('Mode', '') or 'acceptEdits')
            known = set(fields(section_lines(template_text, name))[1].get('Allowed commands', []))
            try:
                with open(os.path.join(project, '.claude', 'settings.local.json'), encoding='utf-8') as f:
                    known |= set((json.load(f).get('permissions') or {}).get('allow') or [])
            except (OSError, ValueError, AttributeError):
                pass
            for rule in lists.get('Allowed commands', []):
                if rule not in known:
                    add(name, 'Allowed commands (new)', rule)
        elif name == 'Auto-approval':
            if values.get('Auto-approve', 'no').lower() in ('yes', 'true'):
                add(name, 'Judge', values.get('Judge', '') or 'command')
                for label in ('Endpoint (command)', 'Fallback endpoint (command)'):
                    if not unset(values.get(label, '')):
                        add(name, label, values[label])
                add(name, 'API key (command)', key_form(values.get('API key (command)', '')))
            else:
                add(name, 'Auto-approve', 'no')
        elif name == 'Telemetry':
            add(name, 'Send', values.get('Send', '') or 'no')
            if values.get('Send', 'no').lower() == 'yes':
                add(name, 'Endpoint', values.get('Endpoint', '') or 'none')
                add(name, 'API key', key_form(values.get('API key', '')))
        elif name == 'Working directories':
            for d in lists.get('Extra directories', []):
                add(name, 'Extra directories', d)
        elif name == 'Integrations':
            # Merge / Tracker MCP of an integration that is not configured run nothing
            repo, tracker = values.get('Repository', ''), values.get('Tracker', '')
            for label in ('Repository', 'Repo', 'Merge', 'Tracker', 'Tracker MCP'):
                live = (label in ('Repository', 'Tracker') or (label in ('Repo', 'Merge') and not unset(repo))
                        or (label == 'Tracker MCP' and not unset(tracker)))
                if live and not unset(values.get(label, '')):
                    add(name, label, values[label])
        elif name == 'Sandbox':
            add(name, 'Enabled', values.get('Enabled', '') or 'no')
            for label in ('Allowed hosts', 'Writable paths', 'Excluded commands'):
                for item in lists.get(label, []):
                    if not unset(item):
                        add(name, label, item)
    print('\n'.join(out))


def mode(project):
    text = read_config(project) or ''
    value = fields(section_lines(text, 'Permissions'))[0].get('Mode', '') or 'acceptEdits'
    print(clean(value))
    return 0 if value in KNOWN_MODES else 3


def main(argv):
    if len(argv) < 3 or argv[1] not in ('check', 'stamp', 'show', 'mode'):
        print(__doc__, file=sys.stderr)
        return 2
    cmd, project, rest = argv[1], argv[2], argv[3:]
    if cmd == 'check':
        names = untrusted(project)
        if names:
            print('\n'.join(names))
    elif cmd == 'stamp':
        stamp(project, rest)
    elif cmd == 'show':
        template = ''
        if '--template' in rest:
            i = rest.index('--template')
            template = rest[i + 1] if i + 1 < len(rest) else ''
            rest = rest[:i] + rest[i + 2:]
        show(project, template, rest)
    else:
        return mode(project)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
