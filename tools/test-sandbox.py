#!/usr/bin/env python3
"""Self-test of templates/setup/sandbox.py (## Sandbox → the `sandbox` key of
.claude/settings.local.json, change plan K1), of the `Sandbox` section in the trust record, and of
the launcher's sandbox block. Temp directories only; the machine's own availability is mocked where
it matters."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TELESMA = Path(__file__).resolve().parent.parent
SETUP = TELESMA / "templates" / "setup"
TEMPLATE = (TELESMA / "templates" / "config.md").read_text(encoding="utf-8")
SCRIPT = (TELESMA / "telesma.sh").read_text(encoding="utf-8")
sys.path.insert(0, str(SETUP))
import sandbox  # noqa: E402
import trust  # noqa: E402

FAILURES = []


def ok(cond, desc):
    print(("  ✓ " if cond else "  ✗ ") + desc)
    if not cond:
        FAILURES.append(desc)


def field(text, section, label, value):
    out, inside = [], False
    for line in text.split("\n"):
        if line.startswith("## "):
            inside = line.strip() == f"## {section}"
        if inside and line.startswith(f"- **{label}**:"):
            line = f"- **{label}**: {value}".rstrip()
        out.append(line)
    return "\n".join(out)


def items(text, section, label, values):
    """List items under a field (after its comment lines)."""
    lines = text.split("\n")
    inside = False
    for i, line in enumerate(lines):
        if line.startswith("## "):
            inside = line.strip() == f"## {section}"
        if inside and line.startswith(f"- **{label}**:"):
            j = i + 1
            while j < len(lines) and lines[j].lstrip().startswith("<!--"):
                j += 1
            lines[j:j] = [f"  - {v}" for v in values]
            break
    return "\n".join(lines)


def project(enabled="yes", plan="", fields=None):
    d = Path(tempfile.mkdtemp(prefix="telesma-sandbox-"))
    (d / "telesma" / "state").mkdir(parents=True)
    (d / ".git").mkdir()
    cfg = field(TEMPLATE, "Sandbox", "Enabled", enabled)
    for (section, label), value in (fields or {}).items():
        cfg = field(cfg, section, label, value)
    (d / "telesma" / "config.md").write_text(cfg, encoding="utf-8")
    (d / "telesma" / "state" / "PLAN.md").write_text(plan, encoding="utf-8")
    return d


def configure(d, transform):
    p = d / "telesma" / "config.md"
    p.write_text(transform(p.read_text(encoding="utf-8")), encoding="utf-8")


def run(d, autonomous=True, avail=(True, "")):
    sandbox.available = lambda: avail
    settings = d / ".claude" / "settings.local.json"
    from io import StringIO
    out, real = StringIO(), sys.stdout
    sys.stdout = out
    try:
        rc = sandbox.sync(str(d), str(settings), autonomous)
    finally:
        sys.stdout = real
    data = json.loads(settings.read_text(encoding="utf-8")) if settings.exists() else None
    return rc, out.getvalue().strip(), data


print("sandbox.py — the settings Telesma writes")
d = project(enabled="no")
rc, out, data = run(d)
ok(rc == 0 and out == "off" and data is None, "Enabled: no on a project Telesma never sandboxed writes nothing")

d = project(plan="### Phase 1: A\n\n- [ ] Task 1.1: x (tech: python)\n")
(d / ".claude").mkdir()
(d / ".claude" / "settings.local.json").write_text(json.dumps({"permissions": {"allow": ["Bash(ls:*)"]}}), encoding="utf-8")
rc, out, data = run(d)
sb = (data or {}).get("sandbox") or {}
ok(rc == 0 and out == "on" and data["permissions"] == {"allow": ["Bash(ls:*)"]}, "Enabled: yes → on; the rest of the file stays")
ok(sb.get("enabled") is True and sb.get("allowUnsandboxedCommands") is False and sb.get("autoAllowBashIfSandboxed") is False,
   "fixed: never retried outside the sandbox, questions stay")
ok(sb.get("failIfUnavailable") is False, "yes (not required): Claude Code still starts where the sandbox cannot run")
net, fs = sb.get("network") or {}, sb.get("filesystem") or {}
ok("pypi.org" in net.get("allowedDomains", []) and "files.pythonhosted.org" in net["allowedDomains"],
   "a stack named only by the plan's (tech: python) tag gets PyPI before any manifest exists")
ok("~/.cache/uv" in fs.get("allowWrite", []) and "~/.cache/telesma" in fs["allowWrite"],
   "the stack's package caches and Telesma's check cache are writable")
ok("~/.ssh" in fs.get("denyRead", []) and "~/.config/gh" in fs["denyRead"]
   and not any("telesma" in p for p in fs["denyRead"]),
   "keys are not readable; ~/.config/telesma is (the task tool reads the trust record inside the sandbox)")
ok(net.get("strictAllowlist") is True, "an autonomous session refuses an unknown host")
ok(not any("github" in h for h in net["allowedDomains"]) and "api.osv.dev" not in net["allowedDomains"],
   "no GitHub and no check hosts without the integration and the checks")
rc, out, data = run(d, autonomous=False)
ok(data["sandbox"]["network"]["strictAllowlist"] is False, "a chat asks about an unknown host")

print("sandbox.py — integrations, checks, the config's lists")
d = project(fields={("Integrations", "Repository"): "github", ("Checks", "Enabled"): "yes"})
configure(d, lambda t: items(t, "Sandbox", "Allowed hosts", ["api.example.com", "bad host; rm -rf", "[e.g. x]"]))
configure(d, lambda t: items(t, "Sandbox", "Excluded commands", ["docker compose *"]))
configure(d, lambda t: items(t, "Sandbox", "Writable paths", ["~/.cache/my-tool"]))
(d / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
rc, out, data = run(d)
sb = data["sandbox"]
hosts = sb["network"]["allowedDomains"]
ok("github.com" in hosts and "api.github.com" in hosts and "~/.config/gh" not in sb["filesystem"]["denyRead"],
   "Repository: github → GitHub's hosts, and gh's config stays readable (gh runs from the task tool)")
ok("api.osv.dev" in hosts and "pypi.org" in hosts, "Checks enabled → the registries and OSV the checks call")
ok("api.example.com" in hosts and not any(" " in h for h in hosts) and "[e.g. x]" not in hosts,
   "Allowed hosts from the config; a line that is not a host name is dropped, a template placeholder too")
ok(sb["excludedCommands"] == ["docker compose *"] and "~/.cache/my-tool" in sb["filesystem"]["allowWrite"],
   "Excluded commands and Writable paths from the config")

print("sandbox.py — what the person added stays, what Telesma wrote and no longer wants goes")
p = d / ".claude" / "settings.local.json"
data = json.loads(p.read_text(encoding="utf-8"))
data["sandbox"]["network"]["allowedDomains"].append("person.example.org")
p.write_text(json.dumps(data), encoding="utf-8")
configure(d, lambda t: t.replace("  - api.example.com\n", ""))
rc, out, data = run(d)
hosts = data["sandbox"]["network"]["allowedDomains"]
ok("person.example.org" in hosts and "api.example.com" not in hosts,
   "a host allowed in Claude Code survives the next start; one removed from the config is gone")
configure(d, lambda t: field(t, "Sandbox", "Enabled", "no"))
rc, out, data = run(d)
ok(out == "off" and "sandbox" not in data, "Enabled: no removes the key Telesma wrote (unchanged since)")
ok(not (d / ".git" / "telesma-task" / "sandbox.json").exists(), "… and forgets it")
d = project()
run(d)
data = json.loads((d / ".claude" / "settings.local.json").read_text(encoding="utf-8"))
data["sandbox"]["excludedCommands"] = ["make *"]
(d / ".claude" / "settings.local.json").write_text(json.dumps(data), encoding="utf-8")
configure(d, lambda t: field(t, "Sandbox", "Enabled", "no"))
rc, out, data = run(d)
ok(out == "off" and data["sandbox"]["excludedCommands"] == ["make *"],
   "Enabled: no leaves a sandbox key the person changed in Claude Code")

print("sandbox.py — where it cannot run")
d = project(enabled="required")
rc, out, data = run(d, avail=(False, "missing: bwrap"))
ok(out == "required-unavailable missing: bwrap" and data["sandbox"]["failIfUnavailable"] is True,
   "required + not available → the launcher stops; failIfUnavailable stops Claude Code too")
d = project()
rc, out, data = run(d, avail=(False, "missing: socat"))
ok(out.startswith("unavailable ") and data["sandbox"]["enabled"] is True, "yes + not available → a warning, the settings are still written")
d = project()
(d / ".claude").mkdir()
(d / ".claude" / "settings.local.json").write_text("{broken", encoding="utf-8")
rc, out, data = None, None, None
sandbox.available = lambda: (True, "")
rc = sandbox.sync(str(d), str(d / ".claude" / "settings.local.json"), True)
ok(rc == 1 and (d / ".claude" / "settings.local.json").read_text(encoding="utf-8") == "{broken",
   "a settings file that does not parse is left as it is")

print("trust — the Sandbox section")
d = project(enabled="yes")
configure(d, lambda t: items(t, "Sandbox", "Excluded commands", ["docker compose *"]))
old = {s: trust.section_hash((d / "telesma" / "config.md").read_text(encoding="utf-8"), s)
       for s in trust.SECTIONS if s != "Sandbox"}
xdg = Path(tempfile.mkdtemp(prefix="telesma-sandbox-xdg-"))
os.environ["XDG_CONFIG_HOME"] = str(xdg)
rec = Path(trust.record_path(str(d)))
rec.parent.mkdir(parents=True)
rec.write_text(json.dumps({"project": str(d), "sections": old}), encoding="utf-8")
ok(trust.untrusted(str(d)) == ["Sandbox"], "a record from before the section: a config with ## Sandbox is asked about")
configure(d, lambda t: re.sub(r"\n## Sandbox\n.*?(?=\n## )", "\n", t, flags=re.S))
ok(trust.untrusted(str(d)) == [], "a config without ## Sandbox and a record that never saw it: nothing to ask")
d2 = project(enabled="yes", fields={("Integrations", "Repository"): "none"})
configure(d2, lambda t: items(t, "Sandbox", "Excluded commands", ["docker compose *"]))
from io import StringIO
buf, real = StringIO(), sys.stdout
sys.stdout = buf
trust.show(str(d2), str(TELESMA / "templates" / "config.md"), ["Sandbox", "Integrations"])
sys.stdout = real
shown = buf.getvalue()
ok("Sandbox → Enabled: yes" in shown and "Sandbox → Excluded commands: docker compose *" in shown,
   "the person sees Enabled and every hole (Excluded commands)")
ok("Merge" not in shown and "Tracker MCP" not in shown, "Merge / Tracker MCP of an integration that is not set are not shown")

print("a config saved by a Markdown editor (`\\*` for `*`)")
d3 = project(enabled="no")
cfg = (d3 / "telesma" / "config.md").read_text(encoding="utf-8")
cfg = re.sub(r"(- \*\*Allowed commands\*\*:\n(?:  <!--.*\n)*)", lambda m: m.group(1) + "  - Bash(git log:\\*)\n  - Bash(my\\_tool:\\*)\n", cfg, count=1)
(d3 / "telesma" / "config.md").write_text(cfg, encoding="utf-8")
_, lists = trust.fields(trust.section_lines(cfg, "Permissions"))
ok("Bash(git log:*)" in lists["Allowed commands"] and "Bash(my_tool:*)" in lists["Allowed commands"],
   "trust reads `Bash(git log:\\*)` as the rule `Bash(git log:*)` (not shown as a new rule)")
block = SCRIPT.split("PERMISSION_MODE=$(python3 - \"$CONFIG_FILE\" \"$SETTINGS_FILE\" <<'PYEOF'\n", 1)[1].split("\nPYEOF\n", 1)[0]
(d3 / ".claude").mkdir(exist_ok=True)
settings3 = d3 / ".claude" / "settings.local.json"
r = subprocess.run([sys.executable, "-", str(d3 / "telesma" / "config.md"), str(settings3)], input=block,
                   capture_output=True, text=True)
allow = json.loads(settings3.read_text(encoding="utf-8"))["permissions"]["allow"] if settings3.exists() else []
ok(r.returncode == 0 and "Bash(git log:*)" in allow and "Bash(my_tool:*)" in allow and not any("\\" in a for a in allow),
   "the launcher's permission sync writes the unescaped rules into settings.local.json")

print("launcher — the sandbox block")
ok("templates/setup/sandbox.py\" sync" in SCRIPT and "--autonomous" in SCRIPT,
   "the launcher syncs the sandbox with the session's kind")
ok(SCRIPT.index("sandbox.py\" sync") > SCRIPT.index('[[ "$MODE" == "2" ]] && INTERACTIVE=true'),
   "… after the mode is final (an autonomous session gets strictAllowlist)")
ok(SCRIPT.count("sandbox_default ") >= 2, "both places that create a config start it with the sandbox on")
ok("21) PROJECT_FORMAT=22" in SCRIPT, "format 22 (the sandbox) has its gate step")

if FAILURES:
    print(f"\nFAILED: {len(FAILURES)}")
    sys.exit(1)
print("\nAll green.")
