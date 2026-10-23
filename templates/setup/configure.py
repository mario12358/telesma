#!/usr/bin/env python3
"""Engine of the configuration wizard — the deterministic half (the questions live in wizard.sh).

Every subcommand edits `telesma/config.md` in place and prints what it did, one line per change,
so the wizard can show it and a test can assert it. Nothing here asks a question or reads a
terminal. Python 3 standard library only.

    configure.py detect  <project_dir>                    KEY=value lines: git, stack, tools, spec
    configure.py status  <config.md>                      KEY=value lines: the state of every module
    configure.py profile <config.md> <minimal|recommended|full> --template <templates/config.md>
    configure.py checks  <config.md> <none|basic|standard|security> --template <templates/config.md>
    configure.py tests   <config.md> --stack <name|auto> [--project <dir>]
    configure.py set     <config.md> <Section> <Field> <value>
    configure.py summary <config.md>                      human-readable table of the modules

Profiles (what a newcomer gets with ENTER):
    minimal      the loop only — every permission prompt goes to the human, no checks
    recommended  + permission judge in `rules` mode (reads pass, the rest asks) + checks `basic`
    full         + checks `standard`; integrations and visual artifacts are asked about in the wizard

Check tiers (which `### <name>` blocks stay under `## Checks`):
    basic      secrets, weakenings, tests, hygiene — no network, no tools, no map
    standard   + dependencies, dependency-audit, sast, lint-types, dead-entry
    security   + intent, red-team (applications with HTTP routes; attack-surface map)
A check without a block does not run and costs nothing; the config merge at startup respects
removed blocks, so a tier is a plain edit of the file, reversible with `--setup`.
"""

import argparse
import json
import os
import re
import socket
import shutil
import sys

FIELD_RE = re.compile(r'^- \*\*(.+?)\*\*:[ \t]*(.*?)[ \t]*$')
PLACEHOLDER_RE = re.compile(r'^\[.*\]$')

TIERS = {
    'none': [],
    'basic': ['secrets', 'weakenings', 'tests', 'hygiene'],
    'standard': ['secrets', 'weakenings', 'tests', 'hygiene',
                 'dependencies', 'dependency-audit', 'sast', 'lint-types', 'dead-entry'],
    'security': ['secrets', 'weakenings', 'tests', 'hygiene',
                 'dependencies', 'dependency-audit', 'sast', 'lint-types', 'dead-entry',
                 'intent', 'red-team'],
}

PROFILES = {
    'minimal': {('Auto-approval', 'Auto-approve'): 'no', 'checks': 'none'},
    'recommended': {('Auto-approval', 'Auto-approve'): 'yes', ('Auto-approval', 'Judge'): 'rules',
                    'checks': 'basic'},
    'full': {('Auto-approval', 'Auto-approve'): 'yes', ('Auto-approval', 'Judge'): 'rules',
             'checks': 'standard'},
}

# Permission rules every project gets (the loop's own git operations and directory listing).
BASE_ALLOWED = ['Bash(mkdir:*)', 'Bash(ls:*)', 'Bash(git add:*)', 'Bash(git commit:*)', 'Bash(git status)',
                'Bash(git diff:*)', 'Bash(git log:*)', 'Bash(git tag:*)', 'Bash(git describe:*)']

# Per stack: how to recognise it, the commands for ## Tests and the permission rules.
# `greenfield` = the commands proposed when the project has no code yet (the spec only).
STACKS = {
    'python': dict(
        label='Python', manifests=['pyproject.toml', 'requirements.txt', 'setup.py', 'setup.cfg', 'Pipfile'],
        greenfield=dict(test='pytest -q', full='pytest -q', lint='ruff check .', typecheck='mypy .'),
        allowed=['Bash(pytest:*)', 'Bash(python3:*)', 'Bash(python:*)', 'Bash(pip:*)', 'Bash(uv:*)',
                 'Bash(poetry:*)', 'Bash(ruff:*)', 'Bash(mypy:*)', 'Bash(pyright:*)']),
    'node': dict(
        label='Node.js / TypeScript', manifests=['package.json'],
        greenfield=dict(test='npm test', full='npm test', lint='npx eslint .', typecheck='npx tsc --noEmit'),
        allowed=['Bash(npm test:*)', 'Bash(npm run:*)', 'Bash(npm install:*)', 'Bash(npm ci)', 'Bash(npx:*)',
                 'Bash(node:*)', 'Bash(pnpm:*)', 'Bash(yarn:*)']),
    'deno': dict(
        label='Deno', manifests=['deno.json', 'deno.jsonc'],
        greenfield=dict(test='deno test -A', full='deno test -A', lint='deno lint', typecheck='deno check **/*.ts'),
        allowed=['Bash(deno:*)']),
    'rust': dict(
        label='Rust', manifests=['Cargo.toml'],
        greenfield=dict(test='cargo test', full='cargo test', lint='cargo clippy -- -D warnings', typecheck='cargo check'),
        allowed=['Bash(cargo:*)', 'Bash(rustup:*)']),
    'go': dict(
        label='Go', manifests=['go.mod'],
        greenfield=dict(test='go test ./...', full='go test ./...', lint='go vet ./...', typecheck='go build ./...'),
        allowed=['Bash(go:*)', 'Bash(golangci-lint:*)']),
    'java': dict(
        label='Java / Kotlin (JVM)', manifests=['pom.xml', 'build.gradle', 'build.gradle.kts'],
        greenfield=dict(test='./gradlew test', full='./gradlew test', lint='none', typecheck='none'),
        allowed=['Bash(./gradlew:*)', 'Bash(gradle:*)', 'Bash(mvn:*)', 'Bash(./mvnw:*)', 'Bash(java:*)']),
    'dotnet': dict(
        label='C# / .NET', manifests=['*.sln', '*.csproj', 'global.json'],
        greenfield=dict(test='dotnet test', full='dotnet test', lint='dotnet format --verify-no-changes',
                        typecheck='dotnet build'),
        allowed=['Bash(dotnet:*)']),
    'php': dict(
        label='PHP', manifests=['composer.json'],
        greenfield=dict(test='vendor/bin/phpunit', full='vendor/bin/phpunit', lint='vendor/bin/pint --test',
                        typecheck='vendor/bin/phpstan analyse'),
        allowed=['Bash(php:*)', 'Bash(composer:*)', 'Bash(vendor/bin:*)']),
    'ruby': dict(
        label='Ruby', manifests=['Gemfile'],
        greenfield=dict(test='bundle exec rspec', full='bundle exec rspec', lint='bundle exec rubocop', typecheck='none'),
        allowed=['Bash(bundle:*)', 'Bash(ruby:*)', 'Bash(rails:*)', 'Bash(bin/rails:*)', 'Bash(rake:*)']),
    'swift': dict(
        label='Swift', manifests=['Package.swift', '*.xcodeproj'],
        greenfield=dict(test='swift test', full='swift test', lint='none', typecheck='swift build'),
        allowed=['Bash(swift:*)', 'Bash(xcodebuild:*)']),
    'flutter': dict(
        label='Flutter / Dart', manifests=['pubspec.yaml'],
        greenfield=dict(test='flutter test', full='flutter test', lint='dart analyze', typecheck='none'),
        allowed=['Bash(flutter:*)', 'Bash(dart:*)']),
    'other': dict(
        label='Other', manifests=[],
        greenfield=dict(test='[your test command]', full='[your full suite command]', lint='none', typecheck='none'),
        allowed=[]),
}
STACK_ORDER = ['python', 'node', 'deno', 'rust', 'go', 'java', 'dotnet', 'php', 'ruby', 'swift', 'flutter']
STACK_ALLOWED = {rule for s in STACKS.values() for rule in s['allowed']}
# Lockfiles and package managers that refine the Node commands
NODE_PM = [('pnpm-lock.yaml', 'pnpm'), ('yarn.lock', 'yarn'), ('bun.lockb', 'bun'), ('bun.lock', 'bun')]

TOOLS = ['gh', 'gitleaks', 'semgrep', 'pandoc', 'claude']


# =============================================================================
# config.md reading and editing
# =============================================================================

def read(path):
    with open(path, encoding='utf-8') as f:
        return f.read()


def write(path, text):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8', newline='') as f:
        f.write(text)
    os.replace(tmp, path)


def strip_comments(text):
    return re.sub(r'<!--.*?-->', '', text, flags=re.S)


def fields(text):
    """{(section, label): value} without comment bodies; `### name` subsections are
    reported as (section, 'name/label')."""
    out, section, sub = {}, '', ''
    for line in strip_comments(text).split('\n'):
        s = line.strip()
        if s.startswith('## '):
            section, sub = s[3:].strip(), ''
        elif s.startswith('### '):
            sub = s[4:].strip()
        else:
            m = FIELD_RE.match(s)
            if m:
                key = f'{sub}/{m.group(1)}' if sub else m.group(1)
                out[(section, key)] = m.group(2)
    return out


def get(text, section, label):
    return fields(text).get((section, label), '')


def set_field(text, section, label, value):
    """Sets `- **label**: value` inside `## section` (first level, not inside `### `). The line's
    comments below stay. Returns (new text, changed)."""
    lines = text.split('\n')
    in_section, in_sub = False, False
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith('## '):
            in_section = s[3:].strip() == section
            in_sub = False
        elif s.startswith('### '):
            in_sub = True
        elif in_section and not in_sub and s.startswith(f'- **{label}**:'):
            new = f'- **{label}**: {value}'.rstrip()
            if lines[i] == new:
                return text, False
            lines[i] = new
            return '\n'.join(lines), True
    raise KeyError(f'no field "{label}" in section "## {section}"')


def section_span(lines, section):
    """(start, end) line indices of `## section` (end = index of the next `## ` or len)."""
    start = None
    for i, line in enumerate(lines):
        if line.strip().startswith('## '):
            if start is not None:
                return start, i
            if line.strip()[3:].strip() == section:
                start = i
    return (start, len(lines)) if start is not None else (None, None)


def check_blocks(lines, start, end):
    """[(name, first, last)] of the `### name` blocks inside a section span. A block runs to the
    next `### `, to a section-level HTML comment (column 0 — a block's own comments are indented)
    or to the section end."""
    blocks, cur = [], None
    for i in range(start, end):
        s = lines[i].strip()
        if s.startswith('### '):
            if cur:
                blocks.append((cur[0], cur[1], i))
            cur = (s[4:].strip(), i)
        elif cur and lines[i].startswith('<!--'):
            blocks.append((cur[0], cur[1], i))
            cur = None
    if cur:
        blocks.append((cur[0], cur[1], end))
    return blocks


def set_checks(text, tier, template_text):
    """Rebuilds the `### ` blocks of ## Checks for a tier: keeps the project's own block of a kept
    check (user edits win), adds missing ones from the template, drops the rest, in template
    order. Sets `Enabled`. Returns (new text, [change lines])."""
    wanted = TIERS[tier]
    lines = text.split('\n')
    start, end = section_span(lines, 'Checks')
    if start is None:
        raise KeyError('no ## Checks section')
    t_lines = template_text.split('\n')
    t_start, t_end = section_span(t_lines, 'Checks')
    t_blocks = {n: t_lines[a:b] for n, a, b in check_blocks(t_lines, t_start, t_end)}
    blocks = check_blocks(lines, start, end)
    have = {n: lines[a:b] for n, a, b in blocks}
    changes = []
    missing = [n for n in wanted if n not in t_blocks and n not in have]
    if missing:
        raise KeyError(f'the template has no block for: {", ".join(missing)}')
    new_blocks = []
    for name in [n for n in t_blocks if n in wanted] + [n for n in wanted if n not in t_blocks]:
        if name in have:
            new_blocks += have[name]
        else:
            new_blocks += t_blocks[name]
            changes.append(f'+ check {name}')
    for name in have:
        if name not in wanted:
            changes.append(f'- check {name}')
    if blocks:
        first, last = blocks[0][1], blocks[-1][2]
    else:
        # no blocks yet: insert before the trailing comment of the section, or at its end
        last = end
        while last > start and not lines[last - 1].strip():
            last -= 1
        first = last
        for k in range(start, end):
            if lines[k].strip().startswith('<!-- Check fields'):
                first = last = k
                break
    # keep exactly one blank line between the fields and the blocks, and after the blocks
    body = [l.rstrip() for l in new_blocks]
    while body and not body[-1]:
        body.pop()
    if body:
        body.append('')
    lines = lines[:first] + body + lines[last:]
    text = '\n'.join(lines)
    text, changed = set_field(text, 'Checks', 'Enabled', 'no' if tier == 'none' else 'yes')
    if changed:
        changes.append(f'Checks → Enabled: {"no" if tier == "none" else "yes"}')
    return text, changes


def current_tier(text):
    lines = text.split('\n')
    start, end = section_span(lines, 'Checks')
    if start is None:
        return 'none'
    if get(text, 'Checks', 'Enabled').lower() not in ('yes', 'true'):
        return 'none'
    names = {n for n, _, _ in check_blocks(lines, start, end)}
    for tier in ('basic', 'standard', 'security'):
        if names == set(TIERS[tier]):
            return tier
    return 'custom' if names else 'none'


def set_allowed(text, rules):
    """Replaces the stack-specific entries of `Allowed commands` with `rules` (+ the base ones);
    entries the user added that belong to no stack table stay."""
    lines = text.split('\n')
    start, end = section_span(lines, 'Permissions')
    if start is None:
        raise KeyError('no ## Permissions section')
    head = None
    for i in range(start, end):
        if lines[i].strip().startswith('- **Allowed commands**:'):
            head = i
            break
    if head is None:
        raise KeyError('no Allowed commands field')
    j = head + 1
    while j < end and lines[j].startswith('  - '):
        j += 1
    kept = [l for l in lines[head + 1:j] if l[4:].strip() not in STACK_ALLOWED and l[4:].strip() not in BASE_ALLOWED]
    new = [f'  - {r}' for r in BASE_ALLOWED + list(rules)] + kept
    if lines[head + 1:j] == new:
        return text, False
    return '\n'.join(lines[:head + 1] + new + lines[j:]), True


# =============================================================================
# detection
# =============================================================================

def present(root, pattern):
    if '*' in pattern:
        import glob
        return bool(glob.glob(os.path.join(root, pattern)))
    return os.path.exists(os.path.join(root, pattern))


SKIP_DIRS = {'.git', 'node_modules', 'telesma', '.claude', 'vendor', '.venv', 'venv', 'dist', 'build',
             'target', '__pycache__', 'docs', 'spec', 'artifacts'}


def stacks_in(directory):
    found = [name for name in STACK_ORDER if any(present(directory, m) for m in STACKS[name]['manifests'])]
    # package.json next to deno.json: Deno projects often keep one for tooling — Deno wins
    if 'deno' in found and 'node' in found:
        found.remove('node')
    return found


def detect_parts(root):
    """[(stack, subdir)] — the project root first, then one level of subdirectories (a monorepo
    with backend/ and frontend/). subdir '' = the root."""
    parts = [(s, '') for s in stacks_in(root)]
    if not parts:
        try:
            subs = sorted(d for d in os.listdir(root)
                          if os.path.isdir(os.path.join(root, d)) and d not in SKIP_DIRS and not d.startswith('.'))
        except OSError:
            subs = []
        for d in subs:
            parts += [(s, d) for s in stacks_in(os.path.join(root, d))]
    return parts


def detect_stacks(root):
    return [s for s, _ in detect_parts(root)]


def part_commands(root, parts):
    """## Tests commands for several parts: tests chained with ` && `, linters and typecheckers
    listed with ` · ` (the separator the lint-types check understands), each prefixed with its
    `cd <subdir> &&`."""
    per = []
    for stack, sub in parts:
        cmd = stack_commands(os.path.join(root, sub) if sub else root, stack)
        real = lambda v: v not in ('none', '') and not v.startswith('[')
        # tests of several parts run in one shell line: a subshell per part, or the second
        # `cd` would be relative to the first part's directory
        per.append({k: ((f'(cd {sub} && {v})' if k in ('test', 'full') else f'cd {sub} && {v}') if sub and real(v) else v)
                    for k, v in cmd.items()})
    if len(per) == 1:
        return per[0]
    join = lambda key, sep: sep.join(p[key] for p in per if p[key] not in ('none', '') and not p[key].startswith('[')) or 'none'
    return dict(test=join('test', ' && '), full=join('full', ' && '), lint=join('lint', ' · '),
                typecheck=join('typecheck', ' · '))


def stack_commands(root, stack):
    """The ## Tests commands for a stack, refined by what the project already has."""
    cmd = dict(STACKS[stack]['greenfield'])
    if root is None or not os.path.isdir(root):
        return cmd
    has = lambda *p: any(present(root, x) for x in p)
    if stack == 'python':
        pyproject = read(os.path.join(root, 'pyproject.toml')) if present(root, 'pyproject.toml') else ''
        if not ('[tool.ruff' in pyproject or has('ruff.toml', '.ruff.toml')):
            cmd['lint'] = 'ruff check .' if not has('setup.cfg', 'tox.ini', '.flake8') or not any(
                'flake8' in read(os.path.join(root, f)) for f in ('setup.cfg', 'tox.ini', '.flake8') if present(root, f)) else 'flake8'
        if '[tool.mypy' in pyproject or has('mypy.ini', '.mypy.ini'):
            cmd['typecheck'] = 'mypy .'
        elif has('pyrightconfig.json') or '[tool.pyright' in pyproject:
            cmd['typecheck'] = 'pyright'
        elif not has('pyproject.toml', 'setup.py'):
            cmd['typecheck'] = 'none'
    elif stack == 'node':
        pm = next((p for lock, p in NODE_PM if present(root, lock)), 'npm')
        try:
            pkg = json.loads(read(os.path.join(root, 'package.json')))
        except (OSError, ValueError):
            pkg = {}
        scripts = pkg.get('scripts') or {}
        run = {'npm': 'npm run', 'pnpm': 'pnpm', 'yarn': 'yarn', 'bun': 'bun run'}[pm]
        test = {'npm': 'npm test', 'pnpm': 'pnpm test', 'yarn': 'yarn test', 'bun': 'bun test'}[pm]
        cmd['test'] = cmd['full'] = test if 'test' in scripts else f'npx vitest run' if 'vitest' in json.dumps(pkg) else test
        if 'test:all' in scripts:
            cmd['full'] = f'{run} test:all'
        if 'lint' in scripts:
            cmd['lint'] = f'{run} lint'
        elif not (has('eslint.config.js', 'eslint.config.mjs', 'eslint.config.ts', '.eslintrc', '.eslintrc.js',
                      '.eslintrc.cjs', '.eslintrc.json') or 'eslint' in json.dumps(pkg)):
            cmd['lint'] = 'none'
        if 'typecheck' in scripts:
            cmd['typecheck'] = f'{run} typecheck'
        elif not has('tsconfig.json'):
            cmd['typecheck'] = 'none'
    elif stack == 'go':
        if has('.golangci.yml', '.golangci.yaml', '.golangci.toml'):
            cmd['lint'] = 'golangci-lint run'
    elif stack == 'java':
        if has('pom.xml') and not has('build.gradle', 'build.gradle.kts'):
            cmd['test'] = cmd['full'] = './mvnw -q test' if present(root, 'mvnw') else 'mvn -q test'
        elif not present(root, 'gradlew'):
            cmd['test'] = cmd['full'] = 'gradle test'
    elif stack == 'php':
        if present(root, 'artisan'):
            cmd['test'] = cmd['full'] = 'php artisan test'
        if not has('vendor/bin/pint', 'pint.json'):
            cmd['lint'] = 'none'
        if not has('phpstan.neon', 'phpstan.neon.dist', 'phpstan.dist.neon'):
            cmd['typecheck'] = 'none'
    elif stack == 'ruby':
        gemfile = read(os.path.join(root, 'Gemfile')) if present(root, 'Gemfile') else ''
        if 'rspec' not in gemfile and present(root, 'bin/rails'):
            cmd['test'] = cmd['full'] = 'bin/rails test'
        if 'rubocop' not in gemfile:
            cmd['lint'] = 'none'
    return cmd


def port_open(host, port, timeout=0.3):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def detect(root):
    root = os.path.abspath(root)
    out = {}
    out['git'] = 'yes' if os.path.isdir(os.path.join(root, '.git')) else 'no'
    parts = detect_parts(root)
    out['stacks'] = ' '.join(s for s, _ in parts)
    out['parts'] = ' '.join(f'{s}:{d}' if d else s for s, d in parts)
    out['stack'] = parts[0][0] if parts else ''
    for tool in TOOLS:
        out[f'tool_{tool}'] = 'yes' if shutil.which(tool) else 'no'
    out['ollama'] = 'yes' if port_open('127.0.0.1', 11434) else 'no'
    spec = os.path.join(root, 'telesma', 'spec')
    ux = os.path.join(spec, 'ux_ui')
    out['ux_files'] = str(sum(1 for _, _, fs in os.walk(ux) for f in fs if f != 'LINKS.md')) if os.path.isdir(ux) else '0'
    flow = os.path.join(spec, 'APP_FLOW.md')
    out['app_flow'] = 'filled' if os.path.isfile(flow) and 'TELESMA_APP_FLOW_TEMPLATE' not in read(flow).split('\n', 1)[0] \
        else 'template' if os.path.isfile(flow) else 'none'
    code = 0
    for dirpath, dirnames, files in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in ('.git', 'node_modules', 'telesma', '.claude', 'vendor', '.venv', 'venv')]
        code += sum(1 for f in files if os.path.splitext(f)[1] in
                    ('.py', '.ts', '.tsx', '.js', '.jsx', '.rs', '.go', '.java', '.kt', '.cs', '.php', '.rb', '.swift', '.dart'))
        if code > 50:
            break
    out['code_files'] = str(code)
    return out


# =============================================================================
# subcommands
# =============================================================================

def cmd_detect(a):
    for k, v in detect(a.project_dir).items():
        print(f'{k}={v}')
    return 0


def status(text):
    f = fields(text)
    g = lambda s, l: f.get((s, l), '')
    out = {}
    out['clarified'] = g('Project', 'Clarified') or 'no'
    out['language'] = g('Project', 'Language') or 'en'
    test = g('Tests', 'Test command')
    out['tests'] = 'placeholder' if not test or PLACEHOLDER_RE.match(test) else 'set'
    out['test_command'] = test
    out['full_command'] = g('Tests', 'Full suite command')
    out['lint_command'] = g('Tests', 'Linter/formatter')
    out['typecheck_command'] = g('Tests', 'Typecheck command')
    out['smoke'] = g('Tests', 'Smoke suite') or 'none'
    out['permission_mode'] = g('Permissions', 'Mode') or 'default'
    judge_on = g('Auto-approval', 'Auto-approve').lower() in ('yes', 'true')
    out['judge'] = (g('Auto-approval', 'Judge') or 'rules') if judge_on else 'off'
    out['judge_model'] = g('Auto-approval', 'Model (command)')
    out['checks'] = current_tier(text)
    out['repository'] = g('Integrations', 'Repository') or 'none'
    out['tracker'] = g('Integrations', 'Tracker') or 'none'
    out['screenshots'] = g('Visual artifacts', 'Screenshots') or 'no'
    out['recordings'] = g('Visual artifacts', 'Recordings') or 'no'
    out['telemetry'] = g('Telemetry', 'Send') or 'no'
    return out


def cmd_status(a):
    for k, v in status(read(a.config)).items():
        print(f'{k}={v}')
    return 0


def cmd_set(a):
    text, changed = set_field(read(a.config), a.section, a.field, a.value)
    if changed:
        write(a.config, text)
        print(f'{a.section} → {a.field}: {a.value}')
    return 0


def cmd_checks(a):
    text, changes = set_checks(read(a.config), a.tier, read(a.template))
    if changes:
        write(a.config, text)
        for c in changes:
            print(c)
    return 0


def cmd_tests(a):
    text = read(a.config)
    if a.stack == 'auto':
        if not a.project:
            print('tests --stack auto needs --project', file=sys.stderr)
            return 2
        parts = detect_parts(os.path.abspath(a.project))
        if not parts:
            print('no stack detected — pass --stack <name>', file=sys.stderr)
            return 2
        cmd = part_commands(os.path.abspath(a.project), parts)
        rules, label = [], ' + '.join(STACKS[s]['label'] for s, _ in parts)
        for s, _ in parts:
            rules += [r for r in STACKS[s]['allowed'] if r not in rules]
    else:
        stack = a.stack
        if stack not in STACKS:
            print(f'unknown stack {stack}; known: {", ".join(STACKS)}, auto', file=sys.stderr)
            return 2
        cmd = stack_commands(a.project, stack)
        rules, label = STACKS[stack]['allowed'], STACKS[stack]['label']
    changes = []
    for field_label, key in (('Test command', 'test'), ('Full suite command', 'full'),
                             ('Linter/formatter', 'lint'), ('Typecheck command', 'typecheck')):
        text, ch = set_field(text, 'Tests', field_label, cmd[key])
        if ch:
            changes.append(f'Tests → {field_label}: {cmd[key]}')
    text, ch = set_allowed(text, rules)
    if ch:
        changes.append(f'Permissions → Allowed commands: {len(BASE_ALLOWED) + len(rules)} rules for {label}')
    if changes:
        write(a.config, text)
        for c in changes:
            print(c)
    return 0


def cmd_profile(a):
    text = read(a.config)
    changes = []
    for key, value in PROFILES[a.profile].items():
        if key == 'checks':
            text, ch = set_checks(text, value, read(a.template))
            changes += ch
        else:
            text, ch = set_field(text, key[0], key[1], value)
            if ch:
                changes.append(f'{key[0]} → {key[1]}: {value}')
    if changes:
        write(a.config, text)
        for c in changes:
            print(c)
    return 0


def cmd_summary(a):
    s = status(read(a.config))
    rows = [
        ('Tests', s['test_command'] if s['tests'] == 'set' else 'NOT SET — Telesma will stop until you fill ## Tests',
         '## Tests'),
        ('Permission prompts', {'off': 'every Bash command asks you', 'rules': 'judge on (rules): reads pass, the rest asks you',
                                'command': f'judge on (model {s["judge_model"] or "?"}): gray zone goes to the model',
                                'none': 'hook on, no judge: command-shape fixes only',
                                'prompt': 'judge on (Claude Code prompt judge)', 'agent': 'judge on (Claude Code agent judge)'}
         .get(s['judge'], s['judge']), '## Auto-approval'),
        ('Quality checks', {'none': 'off', 'basic': 'basic (secrets, weakenings, tests, hygiene)',
                            'standard': 'standard (+ dependencies, audit, sast, lint/types, dead entries)',
                            'security': 'security (+ attack-surface map, red team)', 'custom': 'custom set'}[s['checks']],
         '## Checks'),
        ('Integrations', ', '.join(x for x in (
            f'GitHub' if s['repository'] == 'github' else '', f'Specky' if s['tracker'] == 'specky' else '') if x) or 'none',
         '## Integrations'),
        ('Visual artifacts', ', '.join(x for x in ('screenshots' if s['screenshots'] == 'yes' else '',
                                                   'recordings' if s['recordings'] == 'yes' else '') if x) or 'off',
         '## Visual artifacts'),
        ('Language', s['language'], '## Project'),
        ('Telemetry', 'on' if s['telemetry'] == 'yes' else 'off (nothing leaves this machine)', '## Telemetry'),
    ]
    w = max(len(r[0]) for r in rows)
    for name, value, where in rows:
        print(f'  {name:<{w}}  {value}  [{where}]')
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('detect'); p.add_argument('project_dir'); p.set_defaults(fn=cmd_detect)
    p = sub.add_parser('status'); p.add_argument('config'); p.set_defaults(fn=cmd_status)
    p = sub.add_parser('summary'); p.add_argument('config'); p.set_defaults(fn=cmd_summary)
    p = sub.add_parser('set'); p.add_argument('config'); p.add_argument('section'); p.add_argument('field')
    p.add_argument('value'); p.set_defaults(fn=cmd_set)
    p = sub.add_parser('checks'); p.add_argument('config'); p.add_argument('tier', choices=sorted(TIERS))
    p.add_argument('--template', required=True); p.set_defaults(fn=cmd_checks)
    p = sub.add_parser('tests'); p.add_argument('config'); p.add_argument('--stack', required=True)
    p.add_argument('--project'); p.set_defaults(fn=cmd_tests)
    p = sub.add_parser('profile'); p.add_argument('config'); p.add_argument('profile', choices=sorted(PROFILES))
    p.add_argument('--template', required=True); p.set_defaults(fn=cmd_profile)
    a = ap.parse_args(argv)
    try:
        return a.fn(a)
    except (OSError, KeyError) as e:
        print(f'configure: {e}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
