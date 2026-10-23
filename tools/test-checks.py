#!/usr/bin/env python3
"""Tests of the quality checks (`templates/checks/`) — without running Claude.

Builds a temporary repository with the modules in `telesma/checks/`, feeds the runner a PreToolUse
hook input and checks the decision. Every check has a case it MUST catch and one it MUST let
through — a check earns trust before it reaches projects. It also makes sure that the content of
a secret reaches neither the log nor the message for Claude, and that a project without checks
enabled sees no difference at all.

Run: python3 tools/test-checks.py
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TELESMA = Path(__file__).resolve().parent.parent
CHECKS = TELESMA / "templates" / "checks"
LAUNCHER = (TELESMA / "telesma.sh").read_text(encoding="utf-8")
TEMPLATE = (TELESMA / "templates" / "config.md").read_text(encoding="utf-8")
FAILURES = []

# Fictitious but syntactically valid — canaries that must not appear in any output
AWS = "AKIA" + "ZQ3K7WRT2X9PLM4Q"
GH = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"


def ok(cond, desc):
    print(("  ✓ " if cond else "  ✗ ") + desc)
    if not cond:
        FAILURES.append(desc)


def checks_section(enabled="yes", extra=""):
    m = re.search(r"^## Checks\n.*?(?=^## )", TEMPLATE, re.M | re.S)
    s = m.group(0).replace("- **Enabled**: no", f"- **Enabled**: {enabled}")
    return s + extra


def new_repo(enabled="yes", extra=""):
    d = Path(tempfile.mkdtemp(prefix="telesma-checks-test-"))
    subprocess.run(["git", "init", "-q", str(d)], check=True)
    subprocess.run(["git", "-C", str(d), "config", "user.email", "t@example.com"], check=True)
    subprocess.run(["git", "-C", str(d), "config", "user.name", "t"], check=True)
    shutil.copytree(CHECKS, d / "telesma" / "checks", ignore=shutil.ignore_patterns("__pycache__"))
    (d / "telesma" / "state").mkdir(parents=True)
    (d / "telesma" / "config.md").write_text(
        "# Config\n\n## Git\n\n- **Auto-commit**: yes\n\n" + checks_section(enabled, extra)
        + "\n## Permissions\n", encoding="utf-8")
    (d / "README.md").write_text("start\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(d), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(d), "commit", "-qm", "start"], check=True)
    return d


def hook(d, tool, tool_input):
    r = subprocess.run([sys.executable, str(d / "telesma" / "checks" / "telesma-checks.py"), "--pretooluse"],
                       input=json.dumps({"tool_name": tool, "tool_input": tool_input, "cwd": str(d)}),
                       capture_output=True, text=True, env={**os.environ, "CLAUDE_PROJECT_DIR": str(d)})
    out = json.loads(r.stdout) if r.stdout.strip() else {}
    hso = out.get("hookSpecificOutput", {})
    return hso.get("permissionDecision"), hso.get("permissionDecisionReason") or hso.get("additionalContext") or "", r


def bash(d, cmd):
    return hook(d, "Bash", {"command": cmd})


def write(d, rel, content):
    p = d / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def log(d):
    p = d / "telesma" / "state" / "CHECKS.jsonl"
    return p.read_text(encoding="utf-8") if p.exists() else ""


FP = r"fingerprint `([0-9a-f]{12})`"

# --- Command parsing -------------------------------------------------------------------
print("Recognizing points from the command")
sys.dont_write_bytecode = True     # do not leave __pycache__ in templates/checks/
import importlib.util
spec = importlib.util.spec_from_file_location("rc", CHECKS / "telesma-checks.py")
rc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rc)

ok(set(rc.points_from_command('git add a.py b.py && git commit -m "x"')) == {"commit"}, "add && commit → commit")
ok(rc.points_from_command('git add a.py src/ && git commit -m "x"')["commit"]["added"] == ["a.py", "src/"],
   "files from git add in the same command go into the commit plan")
ok(rc.points_from_command('git -C /x commit -am "x"')["commit"]["all_tracked"], "commit -am → all tracked")
ok(rc.points_from_command("git status && git log --grep commit") == {}, "status/log with the word commit → nothing")
ok(set(rc.points_from_command("git tag -f telesma/phase-3")) == {"phase"}, "tag telesma/phase-3 → phase")
ok(set(rc.points_from_command('git tag -a v1.4.0 -m "Release"')) == {"release"}, "tag -a v1.4.0 → release")
ok(rc.points_from_command('git tag -a x -m v1.0.0') == {}, "v1.0.0 as the -m message is not a tag name")
ok(rc.points_from_command("git tag -d v1.0.0") == {}, "deleting a tag → nothing")
ok(set(rc.points_from_command("git commit -m \"$(cat <<'EOF'\nTitle\n\nBody with an 'apostrophe\nEOF\n)\"")) == {"commit"},
   "commit with a heredoc (unparseable for shlex) → commit from the regex")

print("Command shape (the hook reads files before the command runs)")
op = rc.order_problem
ok(op('git add a.py b.py && git commit -m "x"') is None, "add && commit — fine")
ok(op('cd backend && git add x.py && git status && git commit -m x') is None, "cd / status before the commit — fine")
ok(op("printf 'AWS_KEY=1' >> config.py && git add config.py && git commit -m x") == "order",
   "a file write and a commit in one command → rejected (a case from Specky)")
ok(op("sed -i s/a/b/ x.py && git commit -am x") == "order", "sed -i && commit → rejected")
ok(op("printf x >> f && git add f && git commit -m \"$(cat <<'EOF'\nTitle with an 'apostrophe\nEOF\n)\"") == "order",
   "write + commit with a heredoc (path without shlex) → rejected")
ok(op("git add f && git commit -m \"$(cat <<'EOF'\nTitle with an 'apostrophe\nEOF\n)\"") is None,
   "add + commit with a heredoc → fine")
ok(op('git commit -m x && git tag -f telesma/phase-2') == "order", "a commit and a phase tag in one command → rejected")
ok(op('git tag -f telesma/phase-2') is None, "a phase tag alone — fine")
ok(op('bash -c "git commit -m x"') == "wrapper", "bash -c 'git commit' → rejected")
ok(op('FOO=1 env git commit -m x') == "wrapper", "env git commit → rejected")
ok(op('grep -rn "git commit" docs/') is None, "grep searching for the text 'git commit' — not applicable")
ok(op('npm test && npm run build') is None, "a command without a commit — not applicable")
ok(op("echo x >> f && git ci -m x", {"ci": "commit -v"}) == "order", "a git alias expanded to commit")
ok(op("git save", {"save": "!git add -A && git commit -m wip"}) == "alias", "a shell-script alias with a commit → rejected")
ok(set(rc.points_from_command("git ci -m x", {"ci": "commit"})) == {"commit"}, "alias ci → point commit")

d = new_repo()
write(d, "config.py", "X = 1\n")
subprocess.run(["git", "-C", str(d), "add", "config.py"], check=True)
subprocess.run(["git", "-C", str(d), "commit", "-qm", "c"], check=True)
dec, txt, _ = bash(d, f"printf 'AWS_KEY = \"{AWS}\"\\n' >> config.py && git add config.py && git commit -m test")
ok(dec == "deny" and "Split it" in txt, "hook: write + commit in one command rejected with an instruction to split it")
shutil.rmtree(d)

# --- Disabled = no difference ------------------------------------------------------------
print("Checks disabled")
d = new_repo(enabled="no")
write(d, "a.py", f'KEY = "{AWS}"\n')
dec, txt, r = bash(d, "git add a.py && git commit -m x")
ok(dec is None and r.stdout.strip() == "" and r.returncode == 0, "Enabled: no → the hook is silent even with a secret")
ok(not log(d), "Enabled: no → writes nothing to the log")
shutil.rmtree(d)

# --- secrets -------------------------------------------------------------------------------
print("Check: secrets")
d = new_repo()
write(d, "app/config.py", f'AWS_KEY = "{AWS}"\nTOKEN = "{GH}"\n')
dec, txt, _ = bash(d, "git add app/config.py && git commit -m x")
ok(dec == "deny", "an AWS key in an added file blocks the commit")
ok("aws-access-key" in txt or "gitleaks" in txt, "the reason names the rule")
ok(AWS not in txt and GH not in txt, "the message for Claude does not contain the secret")
ok(AWS not in log(d) and GH not in log(d), "the log does not contain the secret")
write(d, "app/config.py", 'import os\nAWS_KEY = os.environ["AWS_KEY"]\n')
dec, _, _ = bash(d, "git add app/config.py && git commit -m x")
ok(dec is None, "a key from an environment variable passes")
write(d, ".env", "DB_PASSWORD=supersecret123\n")
dec, txt, _ = bash(d, "git add .env && git commit -m x")
ok(dec == "deny" and "secret-file" in txt, "a .env file blocks the commit")
write(d, ".env.example", "DB_PASSWORD=\n")
dec, _, _ = bash(d, "git add .env.example && git commit -m x")
ok(dec is None, ".env.example passes")
write(d, "scripts/probe.py", 'password = "CalibrationPass1"\n')
dec, txt, _ = bash(d, "git add scripts/probe.py && git commit -m x")
ok(dec is None and "secret-assignment" in txt, "a password in code only warns (additionalContext)")
write(d, "scripts/password_check.py", 'password = "Test1234Password"\n')
dec, txt, _ = bash(d, "git add scripts/password_check.py && git commit -m x")
ok(dec is None and "secret-assignment" in txt, "a password starting with 'Test' warns (a case from Specky)")
write(d, "app/settings.py", 'password = "changeme"\nsecret = "testing"\n')
dec, txt, _ = bash(d, "git add app/settings.py && git commit -m x")
ok("secret-assignment" not in txt, "placeholders changeme / testing do not warn")
write(d, "tests/fixtures.py", 'password = "hunter2hunter2"\n')
dec, txt, _ = bash(d, "git add tests/fixtures.py && git commit -m x")
ok(dec is None and "secret-assignment" not in txt, "a password in a test file does not warn")
write(d, "notes.py", f'X = "{AWS}"\n')
dec, _, _ = bash(d, "git status")
ok(dec is None, "a command without a commit does not run the checks")
dec, _, _ = bash(d, "git add README.md && git commit -m x")
ok(dec is None, "a commit of another file does not scan the unstaged notes.py")

print("False alarms found on Specky")
write(d, "docs/app.md", "Expected: ~1700 characters and `-----BEGIN RSA PRIVATE KEY-----`\n")
dec, _, _ = bash(d, "git add docs/app.md && git commit -m x")
ok(dec is None, "a bare PEM key header in documentation does not block")
write(d, "keys/deploy.txt", "-----BEGIN RSA PRIVATE KEY-----\n" + "MIIEowIBAAKCAQEAu1SU1LfVLPHCozMxH2Mo4lgOEePzNm0tRgeLezV6ffAt0gun" + "\n-----END RSA PRIVATE KEY-----\n")
dec, _, _ = bash(d, "git add keys/deploy.txt && git commit -m x")
ok(dec == "deny", "a PEM key with a body blocks")
write(d, "web/Keys.test.tsx", 'const k = "sk-ant-api03-test-key-xxxxxxxxxxxxxxxxxxxx";\n')
dec, _, _ = bash(d, "git add web/Keys.test.tsx && git commit -m x")
ok(dec is None, "a crafted key with 'test' in it does not block")
write(d, "app/aws.py", 'K = "AKIAIOSFODNN7EXAMPLE"\n')
dec, _, _ = bash(d, "git add app/aws.py && git commit -m x")
ok(dec is None, "the sample key from the AWS documentation does not block")

print("Exceptions")
dec, txt, _ = bash(d, "git add notes.py && git commit -m x")
fp = re.search(FP, txt).group(1)
write(d, "telesma/state/CHECK_EXCEPTIONS.md", f"# Exceptions\n\n- `{fp}` secrets notes.py — key from the AWS documentation (owner, 2026-10-05)\n")
dec, _, _ = bash(d, "git add notes.py && git commit -m x")
ok(dec is None, "a finding with an exception by fingerprint does not block")
ok('"decision": "exception"' in log(d), "the log records the exception")
shutil.rmtree(d)

# --- weakenings ------------------------------------------------------------------------------
print("Check: weakenings")
d = new_repo()
write(d, "src/auth.py", "def login():\n    # MUTANT: return True\n    return check()\n")
dec, txt, _ = bash(d, "git add src/auth.py && git commit -m x")
ok(dec == "deny" and "mutant" in txt, "MUTANT blocks the commit")
write(d, "src/auth.py", "def login():\n    # telesma: weakening\n    return True\n")
dec, txt, _ = bash(d, "git add src/auth.py && git commit -m x")
ok(dec == "deny" and "incomplete-marker" in txt, "a marker without an id and a reason blocks")
write(d, "src/auth.py", "def login():\n    # telesma: weakening totp-preview — TOTP code under the form; remove before deployment\n    return True\n")
dec, _, _ = bash(d, "git add src/auth.py && git commit -m x")
ok(dec is None, "a full marker does not block the commit")
subprocess.run(["git", "-C", str(d), "add", "src/auth.py"], check=True)
subprocess.run(["git", "-C", str(d), "commit", "-qm", "auth"], check=True)
dec, txt, _ = bash(d, "git tag -f telesma/phase-1")
ok(dec is None and "totp-preview" in txt, "phase: an open weakening warns")
dec, txt, _ = bash(d, 'git tag -a v0.1.0 -m "First release"')
ok(dec == "deny" and "totp-preview" in txt, "release: an open weakening blocks the tag")
for path in ("src/main.py", "tests/test_guard.py"):
    write(d, path, "# telesma: weakening totp-preview — the same back door, second place\nx = 1\n")
    subprocess.run(["git", "-C", str(d), "add", path], check=True)
subprocess.run(["git", "-C", str(d), "commit", "-qm", "many places"], check=True)
dec, txt, _ = bash(d, 'git tag -a v0.1.1 -m "x"')
ok(dec == "deny" and txt.count("totp-preview") == 1 and "also in:" in txt,
   "one weakening in three files = one finding with a list of places")
fp_w = re.search(r"totp-preview.*?" + FP, txt, re.S).group(1)
write(d, "telesma/state/CHECK_EXCEPTIONS.md", f"- `{fp_w}` weakenings totp-preview — deliberate demo release (owner)\n")
dec, _, _ = bash(d, 'git tag -a v0.1.1 -m "x"')
ok(dec is None, "one exception lets through a weakening marked in many files")
(d / "telesma" / "state" / "CHECK_EXCEPTIONS.md").unlink()
write(d, "src/http.py", "import requests\nr = requests.get(url, verify=False)\n")
dec, txt, _ = bash(d, "git add src/http.py && git commit -m x")
ok(dec is None and "tls-disabled" in txt, "verify=False without a marker warns, does not block")
write(d, "app/mcp_auth.py", "if settings.mcp_dev_bypass_token and token == settings.mcp_dev_bypass_token:\n    return first_user()\n")
dec, txt, _ = bash(d, "git add app/mcp_auth.py && git commit -m x")
ok(dec is None and "bypass-token" in txt, "a dev-bypass token without a marker warns (a case from Specky)")
write(d, "tests/test_http.py", "r = requests.get(url, verify=False)\n")
dec, txt, _ = bash(d, "git add tests/test_http.py && git commit -m x")
ok(dec is None and "tls-disabled" not in txt, "the pattern in a test file is skipped")
shutil.rmtree(d)

# --- Fake registries and OSV ------------------------------------------------------------------
import datetime
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

NOW = datetime.datetime.now(datetime.timezone.utc)
OLD = "2015-01-01T00:00:00.000Z"
FRESH = (NOW - datetime.timedelta(days=2)).isoformat()
NPM = {
    "express": {"created": OLD, "downloads": 10_000_000},
    "expres": {"created": OLD, "downloads": 8588},
    "react": {"created": OLD, "downloads": 30_000_000},
    "preact": {"created": OLD, "downloads": 5_000_000},
    "new-package": {"created": FRESH, "downloads": 5000},
    "with-postinstall": {"created": OLD, "downloads": 90_000, "scripts": {"postinstall": "node x.js"}},
}
PYPI = {"requests": OLD, "httpx": OLD}
VULNS = {
    "GHSA-aaaa": {"id": "GHSA-aaaa", "aliases": ["CVE-2026-1"], "summary": "JWT bypass",
                  "database_specific": {"severity": "CRITICAL"},
                  "affected": [{"package": {"ecosystem": "PyPI", "name": "pyjwt"},
                                "ranges": [{"events": [{"introduced": "0"}, {"fixed": "2.14.0"}]}]}]},
    "PYSEC-aaaa": {"id": "PYSEC-aaaa", "aliases": ["CVE-2026-1"],
                   "affected": [{"package": {"ecosystem": "PyPI", "name": "pyjwt"},
                                 "ranges": [{"events": [{"introduced": "0"}, {"fixed": "2.14.0"}]}]}]},
    "GHSA-dev": {"id": "GHSA-dev", "database_specific": {"severity": "HIGH"},
                 "affected": [{"package": {"ecosystem": "npm", "name": "vitest"},
                               "ranges": [{"events": [{"introduced": "0"}, {"fixed": "3.2.6"}]}]}]},
    "GHSA-old-branch": {"id": "GHSA-old-branch", "database_specific": {"severity": "HIGH"},
                        "affected": [{"package": {"ecosystem": "PyPI", "name": "litellm"},
                                      "ranges": [{"events": [{"introduced": "0"}, {"fixed": "1.88.6"}]}]}]},
}
VULNERABLE = {("PyPI", "pyjwt", "2.13.0"): ["GHSA-aaaa", "PYSEC-aaaa"], ("npm", "vitest", "1.6.1"): ["GHSA-dev"],
              ("PyPI", "litellm", "1.94.0"): ["GHSA-old-branch"]}
REQUESTS = []


class FakeServer(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def reply(self, code, data=None):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        if data is not None:
            self.wfile.write(json.dumps(data).encode())

    def do_GET(self):
        REQUESTS.append(self.path)
        parts = self.path.strip("/").split("/")
        if parts[0] == "npm":
            n = "/".join(parts[1:]).replace("%2F", "/")
            if n not in NPM:
                return self.reply(404)
            w = NPM[n]
            return self.reply(200, {"dist-tags": {"latest": "1.0.0"}, "time": {"created": w["created"]},
                                     "versions": {"1.0.0": {"scripts": w.get("scripts", {})}}})
        if parts[0] == "npmdl":
            n = "/".join(parts[1:])
            return self.reply(200, {"downloads": NPM.get(n, {}).get("downloads", 0)})
        if parts[0] == "pypi":
            if parts[1] not in PYPI:
                return self.reply(404)
            return self.reply(200, {"releases": {"1.0": [{"upload_time_iso_8601": PYPI[parts[1]]}]}})
        if parts[0] == "jsr":
            return self.reply(200, {"createdAt": OLD}) if parts[2:] == ["std", "packages", "assert"] else self.reply(404)
        if parts[:3] == ["osv", "v1", "vulns"]:
            return self.reply(200, VULNS[parts[3]]) if parts[3] in VULNS else self.reply(404)
        self.reply(404)

    def do_POST(self):
        REQUESTS.append(self.path)
        d = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        results = []
        for q in d["queries"]:
            ids = VULNERABLE.get((q["package"]["ecosystem"], q["package"]["name"], q["version"]), [])
            results.append({"vulns": [{"id": i} for i in ids]} if ids else {})
        self.reply(200, {"results": results})


server = HTTPServer(("127.0.0.1", 0), FakeServer)
threading.Thread(target=server.serve_forever, daemon=True).start()
U = f"http://127.0.0.1:{server.server_port}"
CACHE = tempfile.mkdtemp(prefix="telesma-checks-cache-")
os.environ.update({"TELESMA_REGISTRY_NPM": U + "/npm", "TELESMA_REGISTRY_NPM_DOWNLOADS": U + "/npmdl",
                   "TELESMA_REGISTRY_PYPI": U + "/pypi", "TELESMA_REGISTRY_JSR": U + "/jsr",
                   "TELESMA_OSV": U + "/osv", "TELESMA_CACHE": CACHE})


def commit_file(d, rel, content):
    write(d, rel, content)
    subprocess.run(["git", "-C", str(d), "add", rel], check=True)
    subprocess.run(["git", "-C", str(d), "commit", "-qm", rel], check=True)


print("Check: dependencies")
d = new_repo()
commit_file(d, "package.json", json.dumps({"dependencies": {"express": "^4.0.0"}}))
REQUESTS.clear()
write(d, "package.json", json.dumps({"dependencies": {"express": "^4.0.0", "expres": "^1.0.0"}}))
dec, txt, _ = bash(d, "git add package.json && git commit -m x")
ok(dec == "deny" and "similar-to-popular" in txt,
   "a typo with 8.5k downloads next to an original with 10M blocks (expres passed as a warning on Specky)")
write(d, "package.json", json.dumps({"dependencies": {"express": "^4.0.0", "preact": "^10.0.0"}}))
dec, txt, _ = bash(d, "git add package.json && git commit -m x")
ok(dec is None and "similar-to-popular" in txt, "similar, but with a large share of downloads (preact), only warns")
ok(not any(z.endswith("/npm/express") for z in REQUESTS), "a package already in HEAD is not checked again")
write(d, "package.json", json.dumps({"dependencies": {"express": "^4.0.0", "react-dom-helper-xyz": "^1.0.0"}}))
dec, txt, _ = bash(d, "git add package.json && git commit -m x")
ok(dec == "deny" and "not-found" in txt, "a package missing from the registry blocks (made-up name)")
write(d, "package.json", json.dumps({"dependencies": {"express": "^4.0.0", "new-package": "^1.0.0"}}))
dec, txt, _ = bash(d, "git add package.json && git commit -m x")
ok(dec == "deny" and "fresh-package" in txt, "a package from 2 days ago blocks")
write(d, "package.json", json.dumps({"dependencies": {"express": "^4.0.0", "with-postinstall": "^1.0.0",
                                                       "my-lib": "github:someone/my-lib",
                                                       "monorepo-sibling": "file:../monorepo-sibling"}}))
dec, txt, _ = bash(d, "git add package.json && git commit -m x")
ok(dec is None and "install-scripts" in txt and "outside-registry" in txt,
   "postinstall and a dependency from git warn, do not block")
ok("monorepo-sibling" not in txt, "a file: dependency (monorepo) is skipped")
write(d, "requirements.txt", "--extra-index-url https://pypi.example.com/simple\nrequests==2.32.0\nreqeusts==1.0\n")
dec, txt, _ = bash(d, "git add requirements.txt && git commit -m x")
ok(dec == "deny" and "reqeusts" in txt and "extra-index" in txt,
   "requirements: a typo with no package on PyPI blocks, --extra-index-url warns")
ok("requests:" not in txt, "a correct PyPI package gives no finding")
write(d, "deno.json", '{\n  // comment\n  "imports": {"@std/assert": "jsr:@std/assert@^1", "x": "jsr:@std/no-such@^1"}\n}\n')
dec, txt, _ = bash(d, "git add deno.json && git commit -m x")
ok(dec == "deny" and "@std/no-such" in txt and "@std/assert:" not in txt, "deno.json: a package missing from JSR blocks, an existing one passes")
write(d, ".npmrc", "@acme:registry=https://npm.example.com/\n")
write(d, "package.json", json.dumps({"dependencies": {"express": "^4.0.0", "@acme/internal-lib": "^1.0.0"}}))
dec, txt, _ = bash(d, "git add package.json && git commit -m x")
ok(dec is None and "internal-lib" not in txt, "a package from a scope with a private registry (.npmrc) is not checked against npm")
os.environ["TELESMA_REGISTRY_NPM"] = "http://127.0.0.1:9/npm"
os.environ["TELESMA_CACHE"] = tempfile.mkdtemp()
write(d, "package.json", json.dumps({"dependencies": {"express": "^4.0.0", "anything-goes": "^1.0.0"}}))
dec, txt, _ = bash(d, "git add package.json && git commit -m x")
ok(dec is None and "not-checked" in txt, "registry unreachable → a warning, offline work does not stop")
os.environ["TELESMA_REGISTRY_NPM"] = U + "/npm"
os.environ["TELESMA_CACHE"] = CACHE
shutil.rmtree(d)

print("dependencies: a binary file in the commit (WAV, PNG)")
# On a production project WAV recordings in tests/fixtures/ crashed the check (UnicodeDecodeError) —
# it read every changed file as text before checking whether it was a manifest.
d = new_repo()
(d / "tests" / "fixtures").mkdir(parents=True)
(d / "tests" / "fixtures" / "en.wav").write_bytes(b"RIFF\xff\xfe\x00\x80WAVEfmt " + bytes(range(256)) * 4)
(d / "icon.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\xff" * 64)
dec, txt, _ = bash(d, "git add tests/fixtures/en.wav icon.png && git commit -m x")
ok(dec is None and not re.search(r'"check": "dependencies", "decision": "error"', log(d)),
   "binary files in the commit: dependencies reports no error (does not read files that are not manifests)")
shutil.rmtree(d)

print("Check: dependency-audit")
d = new_repo()
commit_file(d, "backend/poetry.lock",
            '[[package]]\nname = "PyJWT"\nversion = "2.13.0"\n\n[[package]]\nname = "httpx"\nversion = "0.27.0"\n\n'
            '[[package]]\nname = "litellm"\nversion = "1.94.0"\n')
commit_file(d, "frontend/package-lock.json", json.dumps({"lockfileVersion": 3, "packages": {
    "": {"name": "app"}, "node_modules/vitest": {"version": "1.6.1", "dev": True}}}))
dec, txt, _ = bash(d, "git tag -f telesma/phase-1")
ok(dec == "deny" and "pyjwt 2.13.0" in txt and "bump to ≥ 2.14.0" in txt,
   "a critical vulnerability with a fix in a production dependency blocks the phase tag")
ok(txt.count("pyjwt") == 1 and "1 vuln." in txt, "GHSA and PYSEC with the same CVE are one vulnerability, one finding")
ok("vitest" in txt.split("Also warnings")[-1] and "development dependency" in txt,
   "the same severity in a development dependency only warns")
ok("litellm 1.94.0" in txt and "no fixed version" in txt,
   "a fix only in a branch older than the installed one → no fix, warns")
dec, _, _ = bash(d, "git add README.md && git commit -m x")
ok(dec is None, "the audit does not run at commit (default: phase, release, ci)")
fp = re.search(r"pyjwt 2\.13\.0.*?" + FP, txt).group(1)
write(d, "telesma/state/CHECK_EXCEPTIONS.md", f"- `{fp}` dependency-audit pyjwt — risk accepted (owner)\n")
dec, _, _ = bash(d, "git tag -f telesma/phase-1")
ok(dec is None, "an exception by fingerprint lets the tag through")
VULNERABLE[("PyPI", "pyjwt", "2.13.0")] = ["GHSA-aaaa", "PYSEC-aaaa", "GHSA-new"]
VULNS["GHSA-new"] = {"id": "GHSA-new", "database_specific": {"severity": "HIGH"},
                     "affected": [{"package": {"ecosystem": "PyPI", "name": "pyjwt"},
                                   "ranges": [{"events": [{"introduced": "0"}, {"fixed": "2.15.0"}]}]}]}
os.environ["TELESMA_CACHE"] = tempfile.mkdtemp()
dec, txt, _ = bash(d, "git tag -f telesma/phase-1")
ok(dec == "deny" and "bump to ≥ 2.15.0" in txt, "a new vulnerability in the same package blocks despite the exception")
os.environ["TELESMA_OSV"] = "http://127.0.0.1:9/osv"
os.environ["TELESMA_CACHE"] = tempfile.mkdtemp()
dec, txt, _ = bash(d, "git tag -f telesma/phase-1")
ok(dec is None and "not-checked" in txt, "OSV unreachable → a warning, not a block")
os.environ["TELESMA_OSV"] = U + "/osv"
shutil.rmtree(d)
server.shutdown()

print("Check: tests")
d = new_repo()
# only — blocks in a test file, an exception by fingerprint lets it through
write(d, "tests/api.test.ts", "describe('api', () => {\n  it.only('x', () => {\n    expect(1).toBe(2);\n  });\n});\n")
dec, txt, _ = bash(d, "git add tests/api.test.ts && git commit -m x")
ok(dec == "deny" and "only" in txt, ".only in a test file under tests/ blocks the commit")
fp_t = re.search(r"\[tests/only\].*?" + FP, txt).group(1)
write(d, "telesma/state/CHECK_EXCEPTIONS.md", f"- `{fp_t}` tests api.test.ts — a fixture with test text (owner)\n")
dec, txt, _ = bash(d, "git add tests/api.test.ts && git commit -m x")
ok(dec is None, "an exception by fingerprint lets .only through")
(d / "telesma" / "state" / "CHECK_EXCEPTIONS.md").unlink()
write(d, "tests/api.test.ts", "describe('api', () => {\n  it('x', () => {\n    expect(1).toBe(1 + 0);\n  });\n});\n")
dec, txt, _ = bash(d, "git add tests/api.test.ts && git commit -m x")
ok(dec is None and "[tests" not in txt, "a plain it() with an assertion passes without findings")
# skip — Python with a reason warns, without a reason blocks
write(d, "tests/test_api.py", 'import pytest\n\n@pytest.mark.skip(reason="waiting for the API")\ndef test_a():\n    assert 1 == 1\n')
dec, txt, _ = bash(d, "git add tests/test_api.py && git commit -m x")
ok(dec is None and "skip-with-reason" in txt, "@pytest.mark.skip(reason=…) warns")
write(d, "tests/test_api.py", "import pytest\n\n@pytest.mark.skip\ndef test_a():\n    assert 1 == 1\n")
dec, txt, _ = bash(d, "git add tests/test_api.py && git commit -m x")
ok(dec == "deny" and "skip-without-reason" in txt, "@pytest.mark.skip without reason blocks")
write(d, "tests/test_api.py", "import pytest\n\n@pytest.mark.skipif(sys.platform == 'win32')\ndef test_a():\n    assert 1 == 1\n")
dec, txt, _ = bash(d, "git add tests/test_api.py && git commit -m x")
ok(dec == "deny" and "skip-without-reason" in txt, "skipif without reason= blocks (a condition is not a reason)")
write(d, "tests/test_u.py", 'import unittest\n\nclass T(unittest.TestCase):\n    @unittest.skip("no sandbox")\n    def test_a(self):\n        self.assertEqual(1, 1)\n')
dec, txt, _ = bash(d, "git add tests/test_u.py && git commit -m x")
ok(dec is None and "skip-with-reason" in txt and "skip-without-reason" not in txt, "@unittest.skip(\"…\") with text warns")
# skip — JS has no place for a reason: a comment on the line above saves it
write(d, "tests/ui.spec.ts", "// skip: flaky until #42 is fixed\nit.skip('a', () => { expect(1).toBe(1); });\nxit('b', () => { expect(2).toBe(2); });\n")
dec, txt, _ = bash(d, "git add tests/ui.spec.ts && git commit -m x")
ok(dec == "deny" and "skip-without-reason" in txt and "xit(" in txt, "xit() without a comment blocks, it.skip with `// skip:` does not")
write(d, "tests/ui.spec.ts", "// skip: flaky until #42 is fixed\nit.skip('a', () => { expect(1).toBe(1); });\n")
dec, txt, _ = bash(d, "git add tests/ui.spec.ts && git commit -m x")
ok(dec is None and "skip-with-reason" in txt, "it.skip with a `// skip:` comment only warns")
# skip — Go, Rust, Java
write(d, "pkg/x_test.go", "package x\nimport \"testing\"\nfunc TestA(t *testing.T) {\n\tt.Skip()\n\tif 1 != 1 { t.Fatal(\"x\") }\n}\n")
dec, txt, _ = bash(d, "git add pkg/x_test.go && git commit -m x")
ok(dec == "deny" and "skip-without-reason" in txt, "Go t.Skip() without an argument blocks")
write(d, "pkg/x_test.go", "package x\nimport \"testing\"\nfunc TestA(t *testing.T) {\n\tt.Skip(\"needs docker\")\n\tif 1 != 1 { t.Fatal(\"x\") }\n}\n")
dec, txt, _ = bash(d, "git add pkg/x_test.go && git commit -m x")
ok(dec is None and "skip-with-reason" in txt, "Go t.Skip(\"…\") warns")
write(d, "src/lib.rs", "#[cfg(test)]\nmod tests {\n    #[test]\n    #[ignore]\n    fn a() { assert_eq!(1, 1); }\n}\n")
dec, txt, _ = bash(d, "git add src/lib.rs && git commit -m x")
ok(dec == "deny" and "skip-without-reason" in txt, "Rust #[ignore] without a reason blocks (test in the module file, not in tests/)")
write(d, "src/lib.rs", "#[cfg(test)]\nmod tests {\n    #[test]\n    #[ignore = \"slow, nightly only\"]\n    fn a() { assert_eq!(1, 1); }\n}\n")
dec, txt, _ = bash(d, "git add src/lib.rs && git commit -m x")
ok(dec is None and "skip-with-reason" in txt, "Rust #[ignore = \"…\"] warns")
write(d, "src/test/java/FooTest.java", "class FooTest {\n    @Disabled\n    @Test void a() { assertEquals(1, 1); }\n}\n")
dec, txt, _ = bash(d, "git add src/test/java/FooTest.java && git commit -m x")
ok(dec == "deny" and "skip-without-reason" in txt, "Java @Disabled without text blocks")
# test-without-assertion
write(d, "tests/test_blank.py", "def test_a():\n    x = 1\n\ndef test_b():\n    assert True\n\ndef test_c():\n    assert 1 == 1\n")
dec, txt, _ = bash(d, "git add tests/test_blank.py && git commit -m x")
ok(dec is None and "test-without-assertion" in txt and "test_a" in txt and "(+1 more in the file)" in txt,
   "a test without an assertion and a test with `assert True` warn as one finding with a counter")
write(d, "tests/test_ok.py", "import pytest\n\ndef test_a():\n    with pytest.raises(ValueError):\n        int('x')\n\ndef test_b():\n    assert 1 == 1\n")
dec, txt, _ = bash(d, "git add tests/test_ok.py && git commit -m x")
ok(dec is None and "test-without-assertion" not in txt, "pytest.raises counts as an assertion")
write(d, "tests/blank.test.ts", "test('nothing', () => {\n  render();\n});\ntest('trivial', () => {\n  expect(true).toBe(true);\n});\n")
dec, txt, _ = bash(d, "git add tests/blank.test.ts && git commit -m x")
ok(dec is None and "test-without-assertion" in txt and "empty assertion" not in txt.split("test-without-assertion")[1][:80],
   "a JS test without expect warns (the first in the file is the \"no assertion\" one)")
# code-without-test
write(d, "src/foo.py", "def foo():\n    return 1\n")
dec, txt, _ = bash(d, "git add src/foo.py && git commit -m x")
ok(dec is None and "code-without-test" in txt, "a code file in src/ without a test file in the commit warns")
write(d, "src/bar.py", "def bar():\n    return 2\n")
dec, txt, _ = bash(d, "git add src/foo.py src/bar.py && git commit -m x")
ok(txt.count("code-without-test") == 1 and "src/bar.py" in txt and "src/foo.py" in txt,
   "two code files = one finding with a list")
write(d, "tests/test_foo.py", "from src.foo import foo\n\ndef test_foo():\n    assert foo() == 1\n")
dec, txt, _ = bash(d, "git add src/foo.py tests/test_foo.py && git commit -m x")
ok(dec is None and "code-without-test" not in txt and "test-pinned-to-code" not in txt,
   "new code + new test → no code-without-test and no test-pinned-to-code")
write(d, "README.md", "start\nmore\n")
dec, txt, _ = bash(d, "git add README.md && git commit -m x")
ok(dec is None and "[tests" not in txt, "a change to README.md alone → silence")
write(d, "src/types.ts", "export type A = { x: number };\n")
dec, txt, _ = bash(d, "git add src/types.ts && git commit -m x")
ok(dec is None and "code-without-test" not in txt, "src/types.ts alone → no code-without-test")
write(d, "scripts/migrate.py", "print('x')\n")
write(d, "src/index.ts", "export { foo } from './foo';\nexport * from './bar';\n")
dec, txt, _ = bash(d, "git add scripts/migrate.py src/index.ts && git commit -m x")
ok(dec is None and "code-without-test" not in txt, "scripts/ and a re-exporting index.ts → no code-without-test")
# test-pinned-to-code and fewer-assertions — need a version in HEAD
commit_file(d, "src/foo.py", "def foo():\n    return 1\n")
commit_file(d, "tests/test_foo.py", "from src.foo import foo\n\ndef test_foo():\n    assert foo() == 1\n    assert foo() > 0\n")
write(d, "src/foo.py", "def foo():\n    return 2\n")
write(d, "tests/test_foo.py", "from src.foo import foo\n\ndef test_foo():\n    assert foo() == 2\n    assert foo() > 0\n")
dec, txt, _ = bash(d, "git add src/foo.py tests/test_foo.py && git commit -m x")
ok(dec is None and "test-pinned-to-code" in txt and "src/foo.py" in txt,
   "code and its test both modified, something removed from the test → test-pinned-to-code")
ok("fewer-assertions" not in txt, "the same number of assertions → no fewer-assertions")
write(d, "tests/test_foo.py", "from src.foo import foo\n\ndef test_foo():\n    assert foo() == 1\n    assert foo() > 0\n\ndef test_foo_positive():\n    assert foo() >= 1\n")
dec, txt, _ = bash(d, "git add src/foo.py tests/test_foo.py && git commit -m x")
ok(dec is None and "test-pinned-to-code" not in txt, "a test with only added lines (0 removed) → no test-pinned-to-code")
write(d, "tests/test_foo.py", "from src.foo import foo\n\ndef test_foo():\n    assert foo() > 0\n")
dec, txt, _ = bash(d, "git add tests/test_foo.py && git commit -m x")
ok(dec is None and "fewer-assertions" in txt and "2 → 1" in txt, "a drop in the number of assertions in a modified test warns")
write(d, "tests/test_foo.py", "from src.foo import foo\n\ndef test_foo():\n    assert foo() == 1\n    assert foo() > 0\n    assert foo() < 9\n")
dec, txt, _ = bash(d, "git add tests/test_foo.py && git commit -m x")
ok(dec is None and "fewer-assertions" not in txt, "more assertions → no fewer-assertions")
# test-deleted — deleted files do not come on stdin, the module asks git
subprocess.run(["git", "-C", str(d), "checkout", "-q", "--", "tests/test_foo.py", "src/foo.py"], check=True)
subprocess.run(["git", "-C", str(d), "rm", "-q", "tests/test_foo.py"], check=True)
dec, txt, _ = bash(d, "git commit -m x")
ok(dec == "deny" and "test-deleted" in txt and "src/foo.py" in txt, "git rm of a test while its module exists blocks")
subprocess.run(["git", "-C", str(d), "rm", "-q", "src/foo.py"], check=True)
dec, txt, _ = bash(d, "git commit -m x")
ok(dec is None and "test-deleted" not in txt, "module deleted together with its test → tidy-up, passes")
subprocess.run(["git", "-C", str(d), "reset", "-q", "--hard"], check=True)
write(d, "tests/test_foo.py", "x = 1\n")
subprocess.run(["git", "-C", str(d), "add", "tests/test_foo.py"], check=True)
subprocess.run(["git", "-C", str(d), "commit", "-qm", "test"], check=True)
(d / "tests" / "test_foo.py").unlink()
dec, txt, _ = bash(d, "git add -A && git commit -m x")
ok(dec == "deny" and "test-deleted" in txt, "rm + git add -A in the command (deletion only in the working tree) blocks too")
shutil.rmtree(d)

print("Check: hygiene")


def hyg(txt, rule):
    """Finding lines of one hygiene rule — other checks (tests, secrets) also mention file names."""
    return "\n".join(l for l in txt.splitlines() if f"[hygiene/{rule}]" in l)


# Package names in manifests must exist in the fake registry (NPM / PYPI above) — the
# `dependencies` check also runs at commit and an unknown package would block for us.
d = new_repo()
write(d, "dist/app.js", "console.log(1);\n")
write(d, "dist/vendor.js", "console.log(2);\n")
dec, txt, _ = bash(d, "git add dist/app.js dist/vendor.js && git commit -m x")
ok(dec == "deny" and "build-dir" in txt, "a file in dist/ blocks the commit")
ok(txt.count("build-dir") == 1 and "+1 more in dist" in txt, "two files in dist/ = one finding with a counter")
fp = re.search(r"build-dir.*?" + FP, txt, re.S).group(1)
write(d, "telesma/state/CHECK_EXCEPTIONS.md", f"- `{fp}` hygiene dist — this project versions its build on purpose (owner)\n")
write(d, "dist/other.js", "console.log(3);\n")
dec, txt, _ = bash(d, "git add dist/app.js dist/vendor.js dist/other.js && git commit -m x")
ok(dec is None and "build-dir" not in txt, "an exception by the directory's fingerprint also covers a new file in it")
(d / "telesma" / "state" / "CHECK_EXCEPTIONS.md").unlink()
write(d, "src/__pycache__/m.cpython-313.pyc", "x")
write(d, "src/m.py", "x = 1\n")
dec, txt, _ = bash(d, "git add src && git commit -m x")
ok(dec == "deny" and "__pycache__" in txt, "__pycache__/ under src/ blocks")
ok("missing-gitignore" in txt, "a repo without .gitignore warns at the first code file")
write(d, "target/debug/app", "x")
dec, txt, _ = bash(d, "git add target/debug/app && git commit -m x")
ok(dec is None and "build-dir" not in txt, "target/ without Cargo.toml / pom.xml is an ordinary directory")
write(d, "Cargo.toml", '[package]\nname = "a"\nversion = "0.1.0"\n')
dec, txt, _ = bash(d, "git add target/debug/app && git commit -m x")
ok(dec == "deny" and "build-dir" in txt, "target/ next to Cargo.toml blocks")
write(d, ".gitignore", "dist/\n")
write(d, "src/ok.py", "y = 2\n")
dec, txt, _ = bash(d, "git add .gitignore src/ok.py && git commit -m x")
ok(dec is None and "missing-gitignore" not in txt, ".gitignore in the commit — no warning")
shutil.rmtree(d)

print("  bundle / binaries / IDE")
d = new_repo()
write(d, "public/vendor/lib.min.js", "var a=" + "1+" * 3000 + "1;\n")
write(d, "static/app.min.js", "var b=1;\n")
write(d, "src/bundle.js", "var c=" + "2+" * 3000 + "2;\n")
write(d, "src/app.js", "var d = 3;\n")
# the runner strips *.min.js from stdin — the check sees them only in the index
subprocess.run(["git", "-C", str(d), "add", "public/vendor/lib.min.js", "static/app.min.js"], check=True)
dec, txt, _ = bash(d, "git add src/bundle.js src/app.js && git commit -m x")
ok(dec is None and "static/app.min.js" in txt and "minified-bundle" in txt, "*.min.js outside vendor/ warns (from the index)")
ok("public/vendor/lib.min.js" not in hyg(txt, "minified-bundle"), "a bundle in public/vendor/ passes")
ok("src/bundle.js" in hyg(txt, "minified-bundle"), "a .js file with a 6000-character line warns by content")
ok("src/app.js" not in hyg(txt, "minified-bundle"), "an ordinary .js is not a bundle")
subprocess.run(["git", "-C", str(d), "reset", "-q"], check=True)
write(d, "src/assets/logo.png", "\x89PNG\x00\x00binary")
write(d, "src/data/model.bin", "\x00\x01\x02data")
write(d, "tests/fixtures/blob.bin", "\x00\x01")
write(d, "docs/report.pdf", "%PDF\x00")
dec, txt, _ = bash(d, "git add src/assets/logo.png src/data/model.bin tests/fixtures/blob.bin docs/report.pdf && git commit -m x")
ok(dec is None and "src/data/model.bin" in txt and "binary-file" in txt, "a binary file without a known extension in src/ warns")
ok(not any(n in hyg(txt, "binary-file") for n in ("logo.png", "blob.bin", "report.pdf")),
   "an image, a test fixture and a pdf in docs/ pass")
write(d, ".vscode/settings.json", '{"python.defaultInterpreterPath": "/home/user/.venv/bin/python"}\n')
write(d, ".vscode/extensions.json", '{"recommendations": ["ms-python.python"]}\n')
write(d, ".vscode/launch.json", '{"configurations": [{"cwd": "${workspaceFolder}"}]}\n')
write(d, ".idea/workspace.xml", "<project/>\n")
write(d, ".idea/misc.xml", "<project/>\n")
write(d, "notes.txt~", "x")
dec, txt, _ = bash(d, "git add .vscode .idea notes.txt~ && git commit -m x")
ok(dec is None and ".vscode/settings.json:1" in txt and "ide-file" in txt, "settings.json with an absolute home path warns")
ok("extensions.json" not in hyg(txt, "ide-file") and "launch.json" not in hyg(txt, "ide-file"),
   "extensions.json and launch.json with ${workspaceFolder} pass")
ok(hyg(txt, "ide-file").count("IDE directory") == 1 and "+1 more in .idea" in txt, ".idea/ is one finding per directory")
ok("notes.txt~" in hyg(txt, "ide-file"), "an editor backup copy (~) warns")
shutil.rmtree(d)

print("  size")
d = new_repo()
write(d, "data/dump.sql", "INSERT INTO t VALUES (1);\n" * 240_000)      # ~6 MB
ok((d / "data" / "dump.sql").stat().st_size > 5_000_000, "fixture: the file is > 5 MB")
# the runner strips > 1 MB from stdin, and a file from `git add` in the command is not in the index
# yet — we add it separately, like Telesma adding files in several steps
subprocess.run(["git", "-C", str(d), "add", "data/dump.sql"], check=True)
dec, txt, _ = bash(d, "git commit -m x")
ok(dec == "deny" and "file-too-large" in txt and "data/dump.sql" in txt, "a 6 MB file in the index blocks the commit")
os.environ["TELESMA_HYGIENE_MAX_MB"] = "10"
dec, txt, _ = bash(d, "git commit -m x")
ok(dec is None and "file-too-large" not in txt, "the threshold from TELESMA_HYGIENE_MAX_MB=10 lets 6 MB through")
del os.environ["TELESMA_HYGIENE_MAX_MB"]
subprocess.run(["git", "-C", str(d), "reset", "-q"], check=True)
write(d, "small.txt", "x\n")
dec, txt, _ = bash(d, "git add small.txt && git commit -m x")
ok(dec is None and "file-too-large" not in txt, "an untracked large file outside the commit does not block another commit")
shutil.rmtree(d)

print("  lockfile and versions")
d = new_repo()
commit_file(d, "package.json", json.dumps({"name": "a", "version": "1.0.0", "dependencies": {"express": "^4.0.0"}}, indent=2))
write(d, "package.json", json.dumps({"name": "a", "version": "1.0.0", "dependencies": {"express": "^4.0.0", "react": "^18.0.0"}}, indent=2))
dec, txt, _ = bash(d, "git add package.json && git commit -m x")
ok(dec is None and "lockfile-stale" not in txt, "a repo without a lockfile — a new dependency passes")
write(d, "package.json", json.dumps({"name": "a", "version": "1.0.0", "dependencies": {"express": "^4.0.0"}}, indent=2))
commit_file(d, "package-lock.json", json.dumps({"name": "a", "lockfileVersion": 3, "packages": {"": {"dependencies": {"express": "^4.0.0"}}}}))
write(d, "package.json", json.dumps({"name": "a", "version": "1.0.0", "dependencies": {"express": "^4.0.0", "react": "^18.0.0"}}, indent=2))
dec, txt, _ = bash(d, "git add package.json && git commit -m x")
ok(dec == "deny" and "lockfile-stale" in txt and "package-lock.json" in txt,
   "a new dependency in package.json without package-lock.json in the commit blocks")
write(d, "package-lock.json", json.dumps({"name": "a", "lockfileVersion": 3, "packages": {"": {"dependencies": {"express": "^4.0.0", "react": "^18.0.0"}}}}))
dec, txt, _ = bash(d, "git add package.json package-lock.json && git commit -m x")
ok(dec is None and "lockfile-stale" not in txt, "the same change with the lockfile in the commit passes")
subprocess.run(["git", "-C", str(d), "add", "package.json", "package-lock.json"], check=True)
subprocess.run(["git", "-C", str(d), "commit", "-qm", "deps"], check=True)
write(d, "package.json", json.dumps({"name": "a", "version": "1.1.0", "scripts": {"test": "vitest"},
                                     "dependencies": {"express": "^4.0.0", "react": "^18.0.0"}}, indent=2))
dec, txt, _ = bash(d, "git add package.json && git commit -m x")
ok(dec is None and "lockfile-stale" not in txt, "a change of only the version and scripts does not need the lockfile")
write(d, "package.json", json.dumps({"name": "a", "version": "1.1.0", "dependencies": {"express": "*", "react": ">=18"},
                                     "devDependencies": {"preact": "*"}}, indent=2))
write(d, "package-lock.json", json.dumps({"name": "a", "lockfileVersion": 3, "packages": {"": {"dependencies": {"express": "*", "react": ">=18"}}}}))
dec, txt, _ = bash(d, "git add package.json package-lock.json && git commit -m x")
ok(dec is None and "floating-version" in txt and "express" in txt and "react" in txt, "`*` and `>=18` in dependencies warn")
ok("preact" not in hyg(txt, "floating-version"), "`*` in devDependencies does not warn")
subprocess.run(["git", "-C", str(d), "reset", "-q", "--hard"], check=True)
write(d, "requirements.txt", "requests\n")
dec, txt, _ = bash(d, "git add requirements.txt && git commit -m x")
ok(dec is None and "floating-version" in txt and "requests" in txt, "requirements.txt: a package without a version warns")
write(d, "requirements.txt", "requests==2.32.0\nhttpx>=0.27,<1\n")
dec, txt, _ = bash(d, "git add requirements.txt && git commit -m x")
ok("floating-version" not in txt, "requirements.txt: `==` and `>=,<` pass")
commit_file(d, "backend/pyproject.toml",
            '[project]\nname = "b"\nversion = "0.1.0"\ndependencies = [\n  "requests>=2,<3",\n]\n\n[tool.ruff]\nline-length = 100\n')
commit_file(d, "backend/poetry.lock", '[[package]]\nname = "requests"\nversion = "2.32.0"\n')
write(d, "backend/pyproject.toml",
      '[project]\nname = "b"\nversion = "0.2.0"\ndependencies = [\n  "requests>=2,<3",\n]\n\n[tool.ruff]\nline-length = 120\n')
dec, txt, _ = bash(d, "git add backend/pyproject.toml && git commit -m x")
ok(dec is None and "lockfile-stale" not in txt, "pyproject: a change of the version and ruff config without poetry.lock passes")
write(d, "backend/pyproject.toml",
      '[project]\nname = "b"\nversion = "0.2.0"\ndependencies = [\n  "requests>=2,<3",\n  "httpx>=0.27",\n]\n')
dec, txt, _ = bash(d, "git add backend/pyproject.toml && git commit -m x")
ok(dec == "deny" and "lockfile-stale" in txt and "backend/poetry.lock" in txt,
   "pyproject: a new dependency without poetry.lock in the same directory blocks")
ok("httpx" in hyg(txt, "floating-version") and "requests" not in hyg(txt, "floating-version"),
   "pyproject: `>=0.27` without an upper bound warns, `>=2,<3` does not")
shutil.rmtree(d)

print("  visual artifacts")
d = new_repo()
cfg_p = d / "telesma" / "config.md"
cfg = cfg_p.read_text(encoding="utf-8")
write(d, "telesma/artifacts/screens/login.png", "\x89PNG\x00")
dec, txt, _ = bash(d, "git add telesma/artifacts/screens/login.png && git commit -m x")
ok(dec is None and "visual-artifacts" not in txt, "config without a Visual artifacts section — silence")
cfg_p.write_text(cfg.replace("## Permissions", "## Visual artifacts\n\n- **Commit artifacts**: no\n  <!-- yes = into git -->\n\n## Permissions"), encoding="utf-8")
dec, txt, _ = bash(d, "git add telesma/artifacts/screens/login.png && git commit -m x")
ok(dec is None and "visual-artifacts" in txt, "telesma/artifacts/ with Commit artifacts: no warns")
cfg_p.write_text(cfg.replace("## Permissions", "## Visual artifacts\n\n- **Commit artifacts**: yes\n\n## Permissions"), encoding="utf-8")
dec, txt, _ = bash(d, "git add telesma/artifacts/screens/login.png && git commit -m x")
ok(dec is None and "visual-artifacts" not in txt, "telesma/artifacts/ with Commit artifacts: yes passes")
shutil.rmtree(d)

print("Check: dead-entry")
# Point `phase`: diff from the last telesma/phase-* tag, and without a tag — from the first commit (README).
d = new_repo()
commit_file(d, "src/toolbar.py", "def render_toolbar():\n    return '<div/>'\n")
commit_file(d, "tests/test_toolbar.py", "from toolbar import render_toolbar\n\ndef test_it():\n    assert render_toolbar()\n")
dec, txt, _ = bash(d, "git tag -f telesma/phase-2")
ok(dec is None and "symbol-without-entry" in txt and "render_toolbar" in txt,
   "a function called only from its own test warns (a toolbar rendered only in its test — a case from the retro)")
ok("deny" not in (dec or ""), "dead entry never blocks the tag")
dec, txt, _ = bash(d, "git add src/toolbar.py && git commit -m x")
ok("dead-entry" not in txt and not re.search(r'"point": "commit"[^\n]*"check": "dead-entry"', log(d)),
   "a commit does not run this check (When: phase, release, ci)")
print("Exception by fingerprint")
dec, txt, _ = bash(d, "git tag -f telesma/phase-2")
fp_m = re.search(r"render_toolbar.*?" + FP, txt, re.S).group(1)
write(d, "telesma/state/CHECK_EXCEPTIONS.md", f"- `{fp_m}` dead-entry render_toolbar — task 3.4 will wire the entry (owner)\n")
dec, txt, _ = bash(d, "git tag -f telesma/phase-2")
ok(dec is None and "symbol-without-entry" not in txt, "an exception by fingerprint silences the symbol")
(d / "telesma" / "state" / "CHECK_EXCEPTIONS.md").unlink()
commit_file(d, "src/app.py", "from toolbar import render_toolbar\n\nrender_toolbar()\n")
dec, txt, _ = bash(d, "git tag -f telesma/phase-2")
ok(dec is None and "symbol-without-entry" not in txt, "a call from another code file = there is an entry, silence")
print("Routes called from server-side templates")
commit_file(d, "src/views.py", '@app.get("/books/{book_id}")\ndef book_detail(book_id: int):\n    return book_id\n\n\n'
                               '@app.get("/shelves/{shelf_id}")\ndef shelf_detail(shelf_id: int):\n    return shelf_id\n')
commit_file(d, "templates/book.html", '<a href="/books/{{ book.id }}">x</a>\n<div hx-get="/books/{{ book.id }}/notes"></div>\n')
dec, txt, _ = bash(d, "git tag -f telesma/phase-2")
ok(dec is None and "/books/{book_id}" not in txt,
   "a route called from a Jinja template with `{{ book.id }}` in the path has a client (the false alarm from the live trial)")
ok("route-without-client" in txt and "/shelves/{shelf_id}" in txt, "a route no template or client calls still warns")
commit_file(d, "src/util.py", "def _private():\n    return 1\n\n\ndef main():\n    _private()\n\n\nif __name__ == '__main__':\n    main()\n")
dec, txt, _ = bash(d, "git tag -f telesma/phase-2")
ok("symbol-without-entry" not in txt, "_private and main are skipped")
print("Only symbols new since the phase tag")
commit_file(d, "src/old.py", "def old_function():\n    return 1\n")
subprocess.run(["git", "-C", str(d), "tag", "telesma/phase-1"], check=True)
commit_file(d, "src/new.py", "def new_function():\n    return 2\n")
dec, txt, _ = bash(d, "git tag -f telesma/phase-2")
ok("new_function" in txt and "old_function" not in txt, "a symbol from before the telesma/phase-1 tag is not reported, a new one is")
print("A tool as an extra signal (fake vulture)")
BIN = Path(tempfile.mkdtemp(prefix="telesma-vulture-"))
(BIN / "vulture").write_text("#!/bin/sh\necho \"src/new.py:1: unused function 'new_function' (90% confidence)\"\n"
                             "echo \"src/zebra.py:1: unused function 'zebra' (90% confidence)\"\n", encoding="utf-8")
os.chmod(BIN / "vulture", 0o755)
commit_file(d, "src/zebra.py", "def zebra():\n    return 'zebra'\n")
commit_file(d, "src/label.py", "LABEL = 'zebra'\n")       # the name in a string — grep sees it, vulture does not
PATH0 = os.environ["PATH"]
os.environ["PATH"] = f"{BIN}:{PATH0}"
dec, txt, _ = bash(d, "git tag -f telesma/phase-2")
os.environ["PATH"] = PATH0
ok("confirmed by: vulture" in txt and "new_function" in txt, "a symbol without an entry confirmed by vulture")
ok(dec is None and "dead-symbol-tool" in txt and "zebra" in txt,
   "a symbol seen only in a string, and unused according to vulture → dead-symbol-tool (warns)")
shutil.rmtree(BIN)
shutil.rmtree(d)

print("React component")
d = new_repo()
commit_file(d, "src/Foo.tsx", "export function Foo() {\n  return <div>foo</div>;\n}\n")
dec, txt, _ = bash(d, "git tag -f telesma/phase-1")
ok(dec is None and "component-without-parent" in txt and "Foo" in txt, "a component without a parent warns")
commit_file(d, "src/App.tsx", "import { Foo } from './Foo';\n\nexport default function App() {\n  return <Foo />;\n}\n")
commit_file(d, "src/main.tsx", "import App from './App';\nrender(<App />);\n")
dec, txt, _ = bash(d, "git tag -f telesma/phase-1")
ok(dec is None and "component-without-parent" not in txt, "a component rendered in a parent (<Foo />) — silence; main.tsx counts as a reference")
commit_file(d, "src/Foo.test.tsx", "import { Helper } from './x';\nexport function Helper() { return 1; }\n")
dec, txt, _ = bash(d, "git tag -f telesma/phase-1")
ok("Helper" not in txt, "definitions in test files are not judged")
shutil.rmtree(d)

print("HTTP route without a client")
d = new_repo()
commit_file(d, "backend/api.py", "from fastapi import FastAPI\n\napp = FastAPI()\n\n\n@app.get(\"/api/items\")\ndef list_items():\n    return []\n")
dec, txt, _ = bash(d, "git tag -f telesma/phase-1")
ok(dec is None and "route-without-client" not in txt and "list_items" not in txt,
   "a backend alone (repo without a front-end file) — routes are not judged, and the route function is not a symbol without an entry")
commit_file(d, "frontend/src/api.ts", "export const USERS = '/api/users';\nexport function getUsers() { return fetch(USERS); }\n")
dec, txt, _ = bash(d, "git tag -f telesma/phase-1")
ok(dec is None and "route-without-client" in txt and "/api/items" in txt, "a route the front end does not call warns")
commit_file(d, "frontend/src/items.ts", "export async function getItems() { return fetch('/api/items'); }\n")
dec, txt, _ = bash(d, "git tag -f telesma/phase-1")
ok("route-without-client" not in txt, "fetch('/api/items') in the front end = there is a client, silence")
shutil.rmtree(d)

# --- sast ----------------------------------------------------------------------------------
print("Check: sast")
# These tests check the built-in patterns — with semgrep in PATH the result must be the same, so for
# this fragment semgrep is disabled (TELESMA_SEMGREP=none) and restored after it.
_semgrep_env = os.environ.get("TELESMA_SEMGREP")
os.environ["TELESMA_SEMGREP"] = "none"
d = new_repo()
write(d, "app/db.py", 'def fetch(cur, uid):\n    cur.execute(f"SELECT * FROM t WHERE id={uid}")\n')
dec, txt, _ = bash(d, "git add app/db.py && git commit -m x")
ok(dec == "deny" and "sql-concatenation" in txt, "SQL with an f-string in execute blocks the commit")
write(d, "app/db.py", 'def fetch(cur, uid):\n    cur.execute("SELECT * FROM t WHERE id=%s", (uid,))\n')
dec, txt, _ = bash(d, "git add app/db.py && git commit -m x")
ok(dec is None and "sql-concatenation" not in txt, "a parametrized execute passes")
write(d, "app/db.js", "db.query(`SELECT * FROM t WHERE id=${id}`);\n")
dec, txt, _ = bash(d, "git add app/db.js && git commit -m x")
ok(dec == "deny" and "sql-concatenation" in txt, "JS: a template literal with ${} in db.query blocks")
write(d, "migrations/0001_init.py", 'op.execute(f"ALTER TABLE {table} ADD COLUMN x int")\n')
dec, txt, _ = bash(d, "git add migrations/0001_init.py && git commit -m x")
ok(dec is None and "sql-concatenation" not in txt, "an f-string SQL in a migration is not counted")

write(d, "app/sh.py", 'import subprocess\nsubprocess.run(["ls", "-l"])\nsubprocess.run("ls -l", shell=True)\n')
dec, txt, _ = bash(d, "git add app/sh.py && git commit -m x")
ok(dec is None and "shell-command" not in txt, "subprocess with a list and shell=True with a literal pass")
write(d, "app/sh.py", 'import subprocess\nsubprocess.run(f"ls {d}", shell=True)\n')
dec, txt, _ = bash(d, "git add app/sh.py && git commit -m x")
ok(dec == "deny" and "shell-command" in txt, "shell=True with an f-string blocks")

write(d, "app/ser.py", "import pickle\nobj = pickle.loads(data)\n")
dec, txt, _ = bash(d, "git add app/ser.py && git commit -m x")
ok(dec == "deny" and "deserialization" in txt, "pickle.loads blocks")
write(d, "app/ser.py", "import yaml\na = yaml.safe_load(f)\nb = yaml.load(x, Loader=yaml.SafeLoader)\n")
dec, txt, _ = bash(d, "git add app/ser.py && git commit -m x")
ok(dec is None and "deserialization" not in txt, "yaml.safe_load and yaml.load with SafeLoader pass")
write(d, "app/ser.py", "import yaml\nb = yaml.load(x)\n")
dec, txt, _ = bash(d, "git add app/ser.py && git commit -m x")
ok(dec == "deny" and "deserialization" in txt, "yaml.load without SafeLoader blocks")

write(d, "app/files.py", 'from flask import request\nf = open(os.path.join(BASE, request.args.get("f")))\n')
dec, txt, _ = bash(d, "git add app/files.py && git commit -m x")
ok(dec == "deny" and "path-traversal" in txt, "a path from request.args in open(os.path.join) blocks")
write(d, "app/files.py", 'from flask import request\nf = open(os.path.join(BASE, secure_filename(request.args.get("f"))))\n')
dec, txt, _ = bash(d, "git add app/files.py && git commit -m x")
ok(dec is None and "path-traversal" not in txt, "the same line with secure_filename passes")

write(d, "app/calc.py", "def calc(expr):\n    return eval(expr)\n")
dec, txt, _ = bash(d, "git add app/calc.py && git commit -m x")
ok(dec == "deny" and "eval-exec" in txt, "eval on a variable blocks")
write(d, "app/calc.py", 'def calc():\n    return eval("1+1")\n')
dec, txt, _ = bash(d, "git add app/calc.py && git commit -m x")
ok(dec is None and "eval-exec" not in txt, "eval on a literal passes")
write(d, "tests/test_calc.py", "def test_x():\n    assert eval(x) == 2\n")
dec, txt, _ = bash(d, "git add tests/test_calc.py && git commit -m x")
ok(dec is None and "eval-exec" not in txt, "eval in a test file is skipped")
write(d, "app/calc.py", "def calc(expr):\n    return eval(expr)  # nosec — expression from our own config\n")
dec, txt, _ = bash(d, "git add app/calc.py && git commit -m x")
ok(dec is None and "eval-exec" not in txt, "# nosec lets the line through")
write(d, "app/patterns.py", "DANGEROUS = re.compile(r'--exec(=|$)|--upload-pack')\nTEXT = \"pickle.loads(x) is forbidden\"\n")
dec, txt, _ = bash(d, "git add app/patterns.py && git commit -m x")
ok(dec is None and "eval-exec" not in txt and "deserialization" not in txt,
   "exec( / pickle.loads( inside a string literal is text, not a call (the judge's regex in the Telesma repo)")

write(d, "web/view.js", "el.innerHTML = html;\n")
dec, txt, _ = bash(d, "git add web/view.js && git commit -m x")
ok(dec is None and "xss-innerhtml" in txt, "innerHTML = warns, does not block")
write(d, "app/hash.py", "import hashlib\nh = hashlib.md5(password).hexdigest()\n")
dec, txt, _ = bash(d, "git add app/hash.py && git commit -m x")
ok(dec is None and "weak-hash" in txt, "md5 on a password warns")
write(d, "app/hash.py", "import hashlib\nh = hashlib.md5(file_bytes).hexdigest()\n")
dec, txt, _ = bash(d, "git add app/hash.py && git commit -m x")
ok("weak-hash" not in txt, "md5 as a file checksum does not warn")
write(d, "web/token.js", "const token = Math.random().toString(36).slice(2);\n")
dec, txt, _ = bash(d, "git add web/token.js && git commit -m x")
ok(dec is None and "non-crypto-randomness" in txt, "Math.random on a line with token warns")
write(d, "app/log.py", 'logger.info("password changed for %s", user_id)\nprint(token_count)\n')
dec, txt, _ = bash(d, "git add app/log.py && git commit -m x")
ok("secret-in-log" not in txt, "the message 'password changed' in a literal and token_count do not warn")
write(d, "app/log.py", 'logger.info("pw %s", password)\n')
dec, txt, _ = bash(d, "git add app/log.py && git commit -m x")
ok(dec is None and "secret-in-log" in txt, "the password variable in a log warns")

print("sast: exception by fingerprint and the phase point")
write(d, "app/calc.py", "def calc(expr):\n    return eval(expr)\n")
dec, txt, _ = bash(d, "git add app/calc.py && git commit -m x")
fp_s = re.search(r"eval-exec.*?" + FP, txt, re.S).group(1)
write(d, "telesma/state/CHECK_EXCEPTIONS.md", f"- `{fp_s}` sast app/calc.py — expressions only from our own config (owner)\n")
dec, txt, _ = bash(d, "git add app/calc.py && git commit -m x")
ok(dec is None, "an exception by fingerprint lets a sast block through")
write(d, "app/calc.py", "def calc(expr):\n    return eval(expr)\n\ndef calc2(code):\n    exec(code)\n")
dec, txt, _ = bash(d, "git add app/calc.py && git commit -m x")
ok(dec == "deny" and "eval-exec" in txt, "a new hit line in a file with an exception changes the fingerprint and blocks again")
(d / "telesma" / "state" / "CHECK_EXCEPTIONS.md").unlink()
commit_file(d, "app/db.py", 'def fetch(cur, uid):\n    cur.execute(f"SELECT * FROM t WHERE id={uid}")\n')
dec, txt, _ = bash(d, "git tag -f telesma/phase-1")
ok(dec == "deny" and "sql-concatenation" in txt, "a phase without an earlier tag: sast scans tracked files and blocks the tag")
subprocess.run(["git", "-C", str(d), "tag", "telesma/phase-1"], check=True)
commit_file(d, "app/clean.py", "def add(a, b):\n    return a + b\n")
dec, txt, _ = bash(d, "git tag -f telesma/phase-2")
ok(dec is None and "sql-concatenation" not in txt, "phase: the diff from the last tag does not include the old SQL")
dec, txt, _ = bash(d, 'git tag -a v0.1.0 -m "x"')
ok("sql-concatenation" not in txt, "sast does not run at a release (default: commit, phase, ci)")
if _semgrep_env is None:
    del os.environ["TELESMA_SEMGREP"]
else:
    os.environ["TELESMA_SEMGREP"] = _semgrep_env
shutil.rmtree(d)

print("Check: lint-types")
# Fake tools: Python scripts in the test repo. The language heuristic works on the word
# `ruff` / `mypy` in the command, not on the script name — hence `python3 tools/fake_ruff.py check`.
FAKE_RUFF = (
    "import json\nimport sys\n"
    "if 'json' not in ' '.join(sys.argv):\n    print('no json flag'); sys.exit(2)\n"
    "files = [a for a in sys.argv[1:] if not a.startswith('-') and a not in ('check', 'json')]\n"
    "out = []\n"
    "for p in files:\n"
    "    lines = open(p, encoding='utf-8').read().splitlines()\n"
    "    for i, l in enumerate(lines, 1):\n"
    "        if l.strip() == 'import os' and not any('os.' in x for x in lines):\n"
    "            out.append({'code': 'F401', 'message': '`os` imported but unused', 'filename': p,\n"
    "                        'location': {'row': i, 'column': 1}})\n"
    "        if len(l) > 100:\n"
    "            out.append({'code': 'E501', 'message': 'Line too long', 'filename': p,\n"
    "                        'location': {'row': i, 'column': 101}})\n"
    "print(json.dumps(out))\nsys.exit(1 if out else 0)\n")
FAKE_MYPY = "import sys\nprint('src/a.py:3: error: Incompatible types  [assignment]')\nsys.exit(1)\n"


def tests_config(d, linter, types="none"):
    """The harness creates a config without ## Tests — we insert the section before ## Checks."""
    c = (d / "telesma" / "config.md").read_text(encoding="utf-8")
    c = re.sub(r"(?s)## Tests\n.*?(?=^## )", "", c, flags=re.M)
    section = (f"## Tests\n\n- **Test command**: pytest\n- **Linter/formatter**: {linter}\n"
               f"- **Typecheck command**: {types}\n  <!-- a comment to ignore -->\n\n")
    write(d, "telesma/config.md", c.replace("## Checks", section + "## Checks", 1))


d = new_repo()
write(d, "tools/fake_ruff.py", FAKE_RUFF)
write(d, "tools/fake_mypy.py", FAKE_MYPY)
tests_config(d, "python3 tools/fake_ruff.py check")
write(d, "src/a.py", "import os\nx = 1\n")
dec, txt, _ = bash(d, "git add src/a.py && git commit -m x")
ok(dec == "deny" and "linter/F401" in txt, "an unused import (F401) blocks the commit with the rule linter/F401")
ok("src/a.py:1" in txt, "the linter finding points at file:line")
write(d, "src/b.py", 'x = "' + "a" * 120 + '"\n')
dec, txt, _ = bash(d, "git add src/b.py && git commit -m x")
ok(dec is None and "linter/E501" in txt, "a line too long (E501) only warns")
write(d, "docs/note.md", "import os\n" + "a" * 150 + "\n")
dec, txt, _ = bash(d, "git add docs/note.md && git commit -m x")
ok(dec is None and "linter" not in txt, "a commit of a .md alone does not run the linter (silence)")
write(d, "src/c.py", "x = 1\n")
dec, txt, _ = bash(d, "git add src/c.py && git commit -m x")
ok(dec is None and "lint-types" not in txt, "a clean .py file — silence")
tests_config(d, "cd src && python3 ../tools/fake_ruff.py check")
dec, txt, _ = bash(d, "git add src/a.py && git commit -m x")
ok(dec == "deny" and "linter/F401" in txt and "src/a.py:1" in txt,
   "prefix `cd X &&`: files given relative to X, the path in the finding comes back relative to the project")
write(d, "tools/other.py", "import os\n")
dec, txt, _ = bash(d, "git add tools/other.py && git commit -m x")
ok(dec is None and "linter" not in txt, "prefix `cd X &&`: a file outside X does not go to the linter")
tests_config(d, "[e.g. ruff check, eslint, cargo fmt -- none if not used]")
dec, txt, _ = bash(d, "git add src/a.py && git commit -m x")
ok(dec is None and "linter" not in txt, "a placeholder in Linter/formatter → silence, no error")
tests_config(d, "/no/such/ruff check")
dec, txt, _ = bash(d, "git add src/a.py && git commit -m x")
ok(dec is None and "linter-unavailable" in txt, "a non-existent tool → linter-unavailable warns, does not block")
tests_config(d, "my-tool --all")
dec, txt, _ = bash(d, "git add src/a.py && git commit -m x")
ok(dec is None and "linter-unknown" in txt, "an unknown tool at commit → one linter-unknown warning")

print("Hook PATH: a tool from ~/.cargo/bin")
# Claude Code runs the hook without the shell profile — on a production project clippy/fmt/cargo
# check passed as "tool missing", because the hook's PATH lacked ~/.cargo/bin.
dp = new_repo()
write(dp, "tools/fake_ruff.py", FAKE_RUFF)
home = Path(tempfile.mkdtemp(prefix="telesma-home-"))
(home / ".cargo" / "bin").mkdir(parents=True)
(home / ".cargo" / "bin" / "ruff").write_text(f'#!/bin/sh\nexec "{sys.executable}" "{dp}/tools/fake_ruff.py" "$@"\n')
os.chmod(home / ".cargo" / "bin" / "ruff", 0o755)
tests_config(dp, "ruff check")
write(dp, "src/a.py", "import os\nx = 1\n")
(home / "py").mkdir()
os.symlink(sys.executable, home / "py" / "python3")     # python3 alone — the Python directory may hold a real ruff
stripped = {**os.environ, "HOME": str(home), "CLAUDE_PROJECT_DIR": str(dp),
            "PATH": os.pathsep.join([str(home / "py"), "/usr/bin", "/bin"])}
r = subprocess.run([sys.executable, str(dp / "telesma" / "checks" / "telesma-checks.py"), "--pretooluse"],
                   input=json.dumps({"tool_name": "Bash", "tool_input": {"command": "git add src/a.py && git commit -m x"},
                                     "cwd": str(dp)}), capture_output=True, text=True, env=stripped)
out = json.loads(r.stdout or "{}").get("hookSpecificOutput", {})
ok(out.get("permissionDecision") == "deny" and "linter/F401" in (out.get("permissionDecisionReason") or ""),
   "PATH without ~/.cargo/bin: the runner adds tool directories, the linter runs and blocks")
shutil.rmtree(home)
shutil.rmtree(dp)

print("Typechecker only at phase")
tests_config(d, "python3 tools/fake_ruff.py check", "python3 tools/fake_mypy.py src")
commit_file(d, "tools/fake_ruff.py", FAKE_RUFF)
commit_file(d, "tools/fake_mypy.py", FAKE_MYPY)
commit_file(d, "src/a.py", "x: int = 1\ny = 2\nz: int = 'a'\n")
dec, txt, _ = bash(d, "git add src/c.py && git commit -m x")
ok(dec is None and "types/" not in txt, "the typechecker is not run at commit")
dec, txt, _ = bash(d, "git tag -f telesma/phase-1")
ok(dec == "deny" and "types/assignment" in txt and "src/a.py:3" in txt, "phase: a type error blocks the tag with the rule types/assignment")
fp = re.search(r"types/assignment\].*?" + FP, txt).group(1)
write(d, "telesma/state/CHECK_EXCEPTIONS.md", f"- `{fp}` lint-types src/a.py — a known mypy false alarm (owner)\n")
dec, txt, _ = bash(d, "git tag -f telesma/phase-1")
ok(dec is None, "an exception by fingerprint lets the tag through")
(d / "telesma" / "state" / "CHECK_EXCEPTIONS.md").unlink()
tests_config(d, "none", "/no/such/mypy src")
dec, txt, _ = bash(d, "git tag -f telesma/phase-1")
ok(dec is None and "types-unavailable" in txt, "a non-existent typechecker → types-unavailable warns")

print("--check")
tests_config(d, "none", "none")
r = subprocess.run([sys.executable, "run.py", "--check"], cwd=d / "telesma" / "checks" / "lint-types",
                   capture_output=True, text=True, env={**os.environ, "TELESMA_ROOT": str(d)})
ok(r.returncode == 0 and r.stdout.startswith("warning:") and "quote" in r.stdout,
   "--check without a linter and a typechecker → warning: (only the quote rule), exit 0")
r = subprocess.run([sys.executable, "run.py", "--check"], cwd=d / "telesma" / "checks" / "lint-types",
                   capture_output=True, text=True, env={k: v for k, v in os.environ.items() if k != "TELESMA_ROOT"})
ok(r.returncode == 0 and r.stdout.startswith("warning:"), "--check without TELESMA_ROOT finds the config via ../../config.md")
tests_config(d, "python3 tools/fake_ruff.py check", "python3 tools/fake_mypy.py src")
r = subprocess.run([sys.executable, "run.py", "--check"], cwd=d / "telesma" / "checks" / "lint-types",
                   capture_output=True, text=True, env={**os.environ, "TELESMA_ROOT": str(d)})
ok(r.returncode == 0 and r.stdout.startswith("ok:"), "--check with a linter and a typechecker → ok:")
shutil.rmtree(d)

print("Typographic quote (without any tool)")
d = new_repo()
write(d, "src/q.py", "x = „text”\n")
dec, txt, _ = bash(d, "git add src/q.py && git commit -m x")
ok(dec == "deny" and "typographic-quote" in txt, "`x = „text”` in .py blocks")
write(d, "src/q.py", 'x = "text”\n')
dec, txt, _ = bash(d, "git add src/q.py && git commit -m x")
ok(dec == "deny" and "typographic-quote" in txt, "`\"text”` — opened in ASCII, closed typographically — blocks")
write(d, "src/q.py", 'print("He said „yes”")\nmsg = f"Quote: „{x}”"\n')
dec, txt, _ = bash(d, "git add src/q.py && git commit -m x")
ok(dec is None and "typographic-quote" not in txt, "typographic quotes inside a string / f-string pass")
write(d, "src/q.py", "# comment „x”\nx = 1  # and here „y”\n")
dec, txt, _ = bash(d, "git add src/q.py && git commit -m x")
ok(dec is None and "typographic-quote" not in txt, "a quote in a comment passes")
write(d, "src/q.py", 'def f():\n    """Returns „yes”.\n\n    Or „no”.\n    """\n    return 1\n')
dec, txt, _ = bash(d, "git add src/q.py && git commit -m x")
ok(dec is None and "typographic-quote" not in txt, "a docstring with „” passes")
write(d, "web/a.js", "const a = “b”;\n")
dec, txt, _ = bash(d, "git add web/a.js && git commit -m x")
ok(dec == "deny" and "typographic-quote" in txt and "web/a.js:1" in txt, "JS `const a = “b”;` blocks")
write(d, "web/a.js", "const t = `He said „yes”`;\n/* block „x”\n   „y” */\nconst u = 'Quote „z”';\n")
dec, txt, _ = bash(d, "git add web/a.js && git commit -m x")
ok(dec is None and "typographic-quote" not in txt, "a template literal and a block comment with „” pass")
write(d, "web/B.tsx", "export const B = () => (\n  <p>\n    He said „yes”, and then „no”\n  </p>\n);\n")
dec, txt, _ = bash(d, "git add web/B.tsx && git commit -m x")
ok(dec is None and "typographic-quote" not in txt, "JSX text outside a string with „” passes (localized UI)")
write(d, "web/C.tsx", "export const C = () => <Foo title=„x” />;\n")
dec, txt, _ = bash(d, "git add web/C.tsx && git commit -m x")
ok(dec == "deny" and "typographic-quote" in txt, "JSX `title=„x”` blocks")
write(d, "docs/q.md", "x = „text”\nconst a = “b”;\n")
dec, txt, _ = bash(d, "git add docs/q.md && git commit -m x")
ok(dec is None and "typographic-quote" not in txt, "the same text in .md passes")
write(d, "script.sh", 'cat <<EOF\nHe said „yes”\nEOF\necho „ok”\n')
dec, txt, _ = bash(d, "git add script.sh && git commit -m x")
ok(dec is None and "typographic-quote" not in txt, "shell: „” outside a string (heredoc, echo) passes")
write(d, "i18n/de.yaml", "title: „Quote”\nlist:\n  - „one”\n")
dec, txt, _ = bash(d, "git add i18n/de.yaml && git commit -m x")
ok(dec is None and "typographic-quote" not in txt, "YAML with translations in „” passes")
write(d, "src/q.py", "x = „text”\n")
dec, txt, _ = bash(d, "git add src/q.py && git commit -m x")
fp = re.search(r"typographic-quote\].*?" + FP, txt).group(1)
write(d, "telesma/state/CHECK_EXCEPTIONS.md", f"- `{fp}` lint-types src/q.py — on purpose (owner)\n")
write(d, "src/q.py", "import sys\n\nx = „text”\n")
dec, txt, _ = bash(d, "git add src/q.py && git commit -m x")
ok(dec is None, "an exception by fingerprint lets it through, also after the line moved")
shutil.rmtree(d)

# --- Fixes after the first session on Specky (2026-10-08) -------------------------------------
print("Fixes after the first session on Specky")
op = rc.order_problem
ok(op('grep -rn "MUTANT" src tests | head -3; git add a.py && git commit -m x') is None,
   "grep MUTANT before the commit in one command (section 4 of the instructions) — fine")
ok(op('ls src && cat a.py && git add a.py && git commit -m x') is None, "ls / cat before the commit — fine")
ok(op('grep x src > list.txt && git add list.txt && git commit -m x') == "order",
   "grep with a redirect into a file before the commit → rejected (a write)")
ok(op('find . -name "*.orig" -delete && git commit -am x') == "order", "find -delete before the commit → rejected")
ok(op('find src -exec sed -i s/a/b/ {} + && git commit -am x') == "order", "find -exec before the commit → rejected")

d = new_repo()
os.environ["TELESMA_SEMGREP"] = "none"
write(d, ".claude/hooks/telesma-permission-judge.py", "import subprocess\nsubprocess.run(command, shell=True)\neval(x)\n")
dec, txt, _ = bash(d, "git add .claude/hooks/telesma-permission-judge.py && git commit -m x")
ok(dec is None and "sast" not in txt, "a framework file in .claude/ is not scanned (the judge hook with a deliberate shell=True)")
write(d, "scripts/probe.py", "class Compose:\n    def exec(self, service, *args):\n        return self._run(args)\n"
                             "    async def eval(self, expr):\n        return expr\n")
dec, txt, _ = bash(d, "git add scripts/probe.py && git commit -m x")
ok(dec is None and "eval-exec" not in txt, "a method definition `def exec(` / `async def eval(` is not a call")
write(d, "scripts/probe2.py", "def f(code):\n    exec(code)\n")
dec, txt, _ = bash(d, "git add scripts/probe2.py && git commit -m x")
ok(dec == "deny" and "eval-exec" in txt, "a call exec(variable) still blocks")
write(d, "app/auth.py", 'import jwt\n\ndef f(state, s):\n    payload = jwt.decode(\n        state, s, algorithms=["HS256"]\n    )\n')
dec, txt, _ = bash(d, "git add app/auth.py && git commit -m x")
ok("jwt-without-verification" not in txt, "jwt.decode with algorithms= on the next line — no warning")
write(d, "app/auth2.py", "import jwt\n\ndef f(state, s):\n    payload = jwt.decode(\n        state, s\n    )\n")
dec, txt, _ = bash(d, "git add app/auth2.py && git commit -m x")
ok("jwt-without-verification" in txt, "jwt.decode without algorithms= in the whole call — still warns")
write(d, "scripts/catalog.py", 'def f(api_key):\n    print(f"API key: {key_marker(api_key)}")\n    print(f"Key: {api_key}")\n')
dec, txt, _ = bash(d, "git add scripts/catalog.py && git commit -m x")
ok(txt.count("secret-in-log") == 1 and "+1 more" not in txt.split("secret-in-log")[1][:200],
   "a key through a masking function (key_marker) is not a secret in a log; a bare key still warns")
del os.environ["TELESMA_SEMGREP"]

# Semgrep results in migrations: a fake semgrep in PATH (the real one is not required for the tests)
fake = Path(tempfile.mkdtemp(prefix="telesma-fake-semgrep-"))
(fake / "semgrep").write_text("""#!/usr/bin/env python3
import json, sys
files = [a for a in sys.argv[1:] if a.endswith('.py')]
cid = 'python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text'
print(json.dumps({'results': [{'path': p, 'start': {'line': 2}, 'check_id': cid,
    'extra': {'severity': 'WARNING', 'message': 'sqlalchemy.text passes SQL unchanged', 'lines': 'op.execute(text(q))'}}
    for p in files], 'errors': []}))
""", encoding="utf-8")
(fake / "semgrep").chmod(0o755)
old_path = os.environ["PATH"]
os.environ["PATH"] = f"{fake}:{old_path}"
write(d, "backend/alembic/versions/0001_x.py", "from alembic import op\nop.execute(text(q))\n")
write(d, "backend/app/db.py", "from sqlalchemy import text\nsession.execute(text(q))\n")
dec, txt, _ = bash(d, "git add backend/alembic/versions/0001_x.py backend/app/db.py && git commit -m x")
ok("avoid-sqlalchemy-text" in txt and "backend/app/db.py" in txt, "fake semgrep: a result in application code stays")
ok("avoid-sqlalchemy-text] backend/alembic" not in txt, "a semgrep result about SQL in a migration is filtered out (as in the built-in patterns)")
os.environ["PATH"] = old_path
shutil.rmtree(fake)
shutil.rmtree(d)

# test-pinned-to-code: an extended import is not a change to the test
d = new_repo()
commit_file(d, "src/view.ts", "export const a = 1;\n")
commit_file(d, "src/view.test.ts", 'import { render, screen } from "x";\nit("a", () => { expect(1).toBe(2); });\n')
write(d, "src/view.ts", "export const a = 2;\n")
write(d, "src/view.test.ts", 'import { render, screen, within } from "x";\nit("a", () => { expect(1).toBe(2); });\n'
                             'it("b", () => { expect(within).toBeDefined(); });\n')
dec, txt, _ = bash(d, "git add src/view.ts src/view.test.ts && git commit -m x")
ok("test-pinned-to-code" not in txt, "a test with an added case and an extended import — no warning (a case from Specky)")
subprocess.run(["git", "-C", str(d), "commit", "-qam", "x"], check=True)
write(d, "src/view.ts", "export const a = 3;\n")
write(d, "src/view.test.ts", 'import { render, screen, within } from "x";\nit("a", () => { expect(1).toBe(3); });\n'
                             'it("b", () => { expect(within).toBeDefined(); });\n')
dec, txt, _ = bash(d, "git add src/view.ts src/view.test.ts && git commit -m x")
ok("test-pinned-to-code" in txt, "an assertion changed together with the code — still warns")
shutil.rmtree(d)

# lint-types: several commands, each with its own `cd` (the Specky config)
d = new_repo()
write(d, "tools/fake_ruff.py", FAKE_RUFF)
commit_file(d, "backend/app/old.py", "import os\n")
tests_config(d, "`cd backend && python3 ../tools/fake_ruff.py check app` · "
                "`cd frontend && python3 ../tools/fake_ruff.py check src`")
write(d, "backend/app/new.py", "import os\nx = 1\n")
write(d, "frontend/src/view.py", "import os\n")
dec, txt, _ = bash(d, "git add backend/app/new.py frontend/src/view.py && git commit -m x")
ok(dec == "deny" and "backend/app/new.py:1" in txt and "frontend/src/view.py:1" in txt,
   "two commands with `cd` in backticks: each gets the files from its own directory")
ok("old.py" not in txt, "a path written into the command (`check app`) is replaced with the commit's file list")
ok("linter-unknown" not in txt, "a multi-part command is no longer an \"unknown tool\"")
tests_config(d, "cd backend && python3 ../tools/fake_ruff.py check · cd frontend && python3 ../tools/fake_ruff.py check")
dec, txt, _ = bash(d, "git add backend/app/new.py frontend/src/view.py && git commit -m x")
ok(dec == "deny" and "backend/app/new.py:1" in txt and "frontend/src/view.py:1" in txt,
   "two commands separated by ` · ` without backticks")
r = subprocess.run([sys.executable, "run.py", "--check"], cwd=d / "telesma" / "checks" / "lint-types",
                   capture_output=True, text=True, env={**os.environ, "TELESMA_ROOT": str(d)})
ok("compound" not in r.stdout, f"--check understands several commands ({r.stdout.strip()[:120]!r})")
shutil.rmtree(d)

# --- Evidence per commit and the PR status (K1) ---------------------------------------------
print("Evidence per commit and the status \"Telesma: checks (local)\"")
FAKE_GH = Path(tempfile.mkdtemp(prefix="telesma-fake-gh-")) / "gh"
FAKE_GH.write_text("""#!/usr/bin/env python3
import json, os, sys
with open(os.environ["FAKE_GH_LOG"], "a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\\n")
if os.environ.get("FAKE_GH_FAIL"):
    sys.stderr.write("HTTP 422: Validation Failed (https://api.github.com/...)\\n")
    sys.exit(1)
""", encoding="utf-8")
FAKE_GH.chmod(0o755)
GH_LOG = FAKE_GH.parent / "calls.jsonl"
os.environ.update({"TELESMA_GH": str(FAKE_GH), "FAKE_GH_LOG": str(GH_LOG)})


def post(d, cmd):
    r = subprocess.run([sys.executable, str(d / "telesma" / "checks" / "telesma-checks.py"), "--posttooluse"],
                       input=json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd},
                                         "tool_response": {"stdout": "", "stderr": ""}, "cwd": str(d)}),
                       capture_output=True, text=True, env={**os.environ, "CLAUDE_PROJECT_DIR": str(d)})
    out = json.loads(r.stdout) if r.stdout.strip() else {}
    return out.get("hookSpecificOutput", {}).get("additionalContext") or "", r


def g(d, *args):
    return subprocess.run(["git", "-C", str(d), *args], capture_output=True, text=True, check=True).stdout.strip()


def gh_calls():
    if not GH_LOG.exists():
        return []
    w = [json.loads(l) for l in GH_LOG.read_text().splitlines() if l.strip()]
    GH_LOG.unlink()
    return w


def status_of(call):
    """(sha, state, description, context) from the arguments of `gh api repos/x/statuses/<sha> -f state=… -f context=… -f description=…`."""
    sha_ = call[1].rsplit("/", 1)[1]
    fields = dict(a.split("=", 1) for a in call[2:] if "=" in a)
    return sha_, fields.get("state"), fields.get("description"), fields.get("context")


def repo_with_origin(status="yes", required="test"):
    d = new_repo()
    cfg = (d / "telesma" / "config.md").read_text(encoding="utf-8")
    cfg = cfg.replace("## Checks\n", "## Integrations\n\n- **Repository**: github\n- **Repo**: someone/proj\n"
                      f"- **Merge**: agent\n- **Required checks**: {required}\n\n## Checks\n", 1)
    cfg = cfg.replace("- **PR status**: yes", f"- **PR status**: {status}", 1)   # the field is already in the template
    (d / "telesma" / "config.md").write_text(cfg, encoding="utf-8")
    g(d, "branch", "-M", "main")
    bare = Path(tempfile.mkdtemp(prefix="telesma-origin-")) / "proj.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    g(d, "remote", "add", "origin", str(bare))
    g(d, "push", "-q", "-u", "origin", "main")
    return d


d = repo_with_origin()
evd = Path(g(d, "rev-parse", "--git-path", "telesma-checks"))
evd = evd if evd.is_absolute() else d / evd
g(d, "checkout", "-q", "-b", "task-1-model")
write(d, "src/model.py", "def model():\n    return 1\n")
dec, txt, _ = bash(d, "git add src/model.py && git commit -m 'Telesma: 1.1 model'")
ok(dec is None and (evd / "pending.json").exists(), "PreToolUse at a commit writes pending evidence")
pending = json.loads((evd / "pending.json").read_text())
ok(pending["head"] == g(d, "rev-parse", "HEAD") and set(pending["checks"]) >= {"secrets", "weakenings"},
   "the pending evidence knows the HEAD from before the commit and the result of every commit-point check")
g(d, "add", "src/model.py"); g(d, "commit", "-qm", "Telesma: 1.1 model")
sha1 = g(d, "rev-parse", "HEAD")
txt, r = post(d, "git add src/model.py && git commit -m 'Telesma: 1.1 model'")
ok(r.returncode == 0 and (evd / f"{sha1}.json").exists() and not (evd / "pending.json").exists(),
   "PostToolUse after a commit assigns the evidence to the new SHA and removes the pending one")
ev = json.loads((evd / f"{sha1}.json").read_text())
ok(ev["checks"]["secrets"]["decision"] == "clean" and ev["patch_id"], "evidence: check clean + patch-id")
ok(not gh_calls(), "a commit alone does not call gh")

g(d, "push", "-q", "-u", "origin", "task-1-model")
txt, r = post(d, "git push -u origin task-1-model")
w = gh_calls()
ok(len(w) == 1 and w[0][:2] == ["api", "repos/someone/proj/statuses/" + sha1], "after a push one status on the branch tip in the repo from the config")
s_, state, desc, ctx = status_of(w[0])
ok(state == "success" and ctx == "Telesma: checks (local)", "all commits with evidence → success")
ok(("clean" in desc or "warn." in desc) and "secrets" in desc and "1 commit" in desc and len(desc) <= 140,
   f"description: result, checks, commit count, ≤ 140 characters ({desc!r})")
ok("success" in txt and "task-1-model" in txt, "Claude gets the status content as context")
ok('"check": "pr-status"' in log(d) and '"decision": "posted"' in log(d), "the log records the posted status")

# a commit outside the hook = no evidence = red
write(d, "src/b.py", "x = 1\n")
g(d, "add", "src/b.py"); g(d, "commit", "-qm", "manual")
sha2 = g(d, "rev-parse", "HEAD")
g(d, "push", "-q", "origin", "task-1-model")
txt, _ = post(d, "git push origin task-1-model")
s_, state, desc, _ = status_of(gh_calls()[0])
ok(s_ == sha2 and state == "failure" and "no check evidence" in desc and sha2[:7] in desc and "1 of 2" in desc,
   "a commit made outside the hook → a red status with its SHA")
ok("NOT" not in txt and "failure" in txt, "the context for Claude tells about the red status")

# amend through the hook: the evidence moves to the new SHA (parent = parent of the previous HEAD)
# an amend without a content change in the same second gives an IDENTICAL SHA — hence the changed message
dec, txt, r_a = bash(d, "git add src/b.py && git commit --amend -m 'manual, fixed'")
ok(dec is None and not r_a.stderr.strip(), f"an amend through the hook is neither blocked nor crashes the hook ({txt[:200]!r}; stderr: {r_a.stderr[-600:]!r})")
g(d, "commit", "-q", "--amend", "-m", "manual, fixed")
sha2b = g(d, "rev-parse", "HEAD")
post(d, "git add src/b.py && git commit --amend -m 'manual, fixed'")
ok(sha2b != sha2 and (evd / f"{sha2b}.json").exists(),
   f"--amend through the hook: the evidence lands on the new SHA (hook: {txt[:300]!r}; dir: {sorted(p.name for p in evd.glob('*'))}; "
   f"pending: {(evd / 'pending.json').read_text()[:400] if (evd / 'pending.json').exists() else '-'}; sha2={sha2[:7]} parent={g(d, 'rev-parse', 'HEAD~1')[:7]})")
g(d, "push", "-q", "--force-with-lease", "origin", "task-1-model")
txt, _ = post(d, "git push --force-with-lease origin task-1-model")
s_, state, desc, _ = status_of(gh_calls()[0])
ok(s_ == sha2b and state == "success" and "2 commits" in desc, "after amend and force-with-lease: green, 2 commits")

# a rebase changes the SHA — the evidence is found by patch-id
g(d, "checkout", "-q", "main")
write(d, "docs/x.md", "x\n"); g(d, "add", "docs/x.md"); g(d, "commit", "-qm", "main moves on"); g(d, "push", "-q", "origin", "main")
g(d, "checkout", "-q", "task-1-model")
g(d, "rebase", "-q", "origin/main")
sha_after = g(d, "rev-parse", "HEAD")
ok(sha_after != sha2b and not (evd / f"{sha_after}.json").exists(), "after a rebase the SHA is new, no evidence under it yet")
g(d, "push", "-q", "--force-with-lease", "origin", "task-1-model")
txt, _ = post(d, "git push --force-with-lease origin task-1-model")
s_, state, desc, _ = status_of(gh_calls()[0])
ok(s_ == sha_after and state == "success", "evidence found by patch-id → green despite new SHAs")
ok(json.loads((evd / f"{sha_after}.json").read_text()).get("rewritten_from") == sha2b, "the evidence is re-filed under the new SHA with a note where from")

# a check that did not run is red too
write(d, "src/c.py", "y = 2\n")
(d / "telesma" / "checks" / "weakenings" / "run.py").write_text("import sys; sys.exit(7)\n", encoding="utf-8")
dec, txt, _ = bash(d, "git add src/c.py && git commit -m x")
ok(dec is None and "weakenings" in txt, "a check with an error does not block the commit, but is reported")
g(d, "add", "src/c.py"); g(d, "commit", "-qm", "x"); post(d, "git add src/c.py && git commit -m x")
g(d, "push", "-q", "origin", "task-1-model"); post(d, "git push origin task-1-model")
_, state, desc, _ = status_of(gh_calls()[0])
ok(state == "failure" and "did not run" in desc and "weakenings" in desc, "a check that did not run → red")
shutil.copy(CHECKS / "weakenings" / "run.py", d / "telesma" / "checks" / "weakenings" / "run.py")

# gh fails: log + context, exit 0
os.environ["FAKE_GH_FAIL"] = "1"
txt, r = post(d, "git push origin task-1-model")
ok(r.returncode == 0 and "was NOT posted" in txt and "422" in txt, "gh error: the hook does not crash, Claude knows there is no status")
ok(log(d).count('"decision": "error"') >= 1 and '"check": "pr-status"' in log(d).splitlines()[-1], "the posting error in the log")
del os.environ["FAKE_GH_FAIL"]
gh_calls()

# a push to main and a failed push — nothing
g(d, "checkout", "-q", "main"); write(d, "docs/y.md", "y\n"); g(d, "add", "docs/y.md"); g(d, "commit", "-qm", "y"); g(d, "push", "-q", "origin", "main")
txt, _ = post(d, "git push origin main")
ok(not txt and not gh_calls(), "a push to main posts no status")
g(d, "checkout", "-q", "task-1-model"); write(d, "src/d.py", "z\n"); g(d, "add", "src/d.py"); g(d, "commit", "-qm", "d")
txt, _ = post(d, "git push origin task-1-model")       # without an actual push — the remote ref is behind
ok(not txt and not gh_calls(), "a push that did not happen (remote ref behind) → nothing")

# validator
w = rc.validate(str(d))
ok(any(x.startswith("W:") and "Required checks" in x for x in w), "validator: the status name missing from Required checks → a warning")
shutil.rmtree(d)

d = repo_with_origin(required="test, Telesma: checks (local)")
ok(not any("Required checks" in x for x in rc.validate(str(d))), "validator: the status name in the checks → silence")
shutil.rmtree(d)

d = repo_with_origin(status="no")
g(d, "checkout", "-q", "-b", "task-2-x"); write(d, "src/e.py", "e\n")
bash(d, "git add src/e.py && git commit -m x"); g(d, "add", "src/e.py"); g(d, "commit", "-qm", "x")
post(d, "git add src/e.py && git commit -m x")
ok(any(p.name != "pending.json" for p in (d / ".git" / "telesma-checks").glob("*.json")), "PR status: no — evidence is still created (GitLab later)")
g(d, "push", "-q", "-u", "origin", "task-2-x")
txt, _ = post(d, "git push -u origin task-2-x")
ok(not txt and not gh_calls(), "PR status: no → zero gh calls")
shutil.rmtree(d)
del os.environ["TELESMA_GH"]

# --- intent / red-team (E3) ---------------------------------------------------------------
print("Check: intent")


def skeleton(d):
    return subprocess.run([sys.executable, str(d / "telesma" / "checks" / "intent" / "run.py"), "--skeleton"],
                          capture_output=True, text=True, env={**os.environ, "TELESMA_ROOT": str(d)})


API_PY = '''from fastapi import APIRouter, Depends

router = APIRouter(prefix="/projects")


@router.get(
    "/{project_id}/files",
    response_model=list,
)
async def list_files(
    project_id: str,
    membership=Depends(
        require_project_role("OWNER", "CLIENT")
    ),
):
    return []


@router.patch("/{project_id}")
async def update_project(project_id: str, user=Depends(current_active_user)):
    return {}


@router.get("/health")
def health():
    return "ok"
'''
DELETE_ROUTE = '\n\n@router.delete("/{project_id}")\nasync def delete_project(project_id: str, user=Depends(current_active_user)):\n    return {}\n'
d = new_repo()
commit_file(d, "backend/api.py", API_PY)
commit_file(d, "tests/test_api.py", "@router.get('/in-test')\ndef t():\n    pass\n")
write(d, "backend/api.py", API_PY + DELETE_ROUTE)
dec, txt, _ = bash(d, "git add backend/api.py && git commit -m x")
ok(dec is None and "map-missing" in txt, "without a map: a changed route → one map-missing warning, nothing blocks")
subprocess.run(["git", "-C", str(d), "checkout", "-q", "backend/api.py"], check=True)
r = skeleton(d)
smap = (d / "telesma" / "state" / "SECURITY_MAP.md").read_text(encoding="utf-8")
ok(r.returncode == 0 and "3 routes" in r.stdout, "skeleton: 3 routes, a summary on stdout")
ok("| GET /projects/{project_id}/files | require_project_role:OWNER | ? |" in smap,
   "a multi-line decorator + Depends(\\n require_project_role(…)) recognized, the router prefix prepended, Ownership ? with a parameter")
ok("| GET /projects/health | ? | — |" in smap, "a route without a guard → role ?, without a parameter → Ownership —")
ok("/in-test" not in smap, "routes from test files do not go into the map")
ok(smap.index("| anonymous |") < smap.index("| require_project_role:OWNER |"), "anonymous first in ## Roles")
ok(skeleton(d).stdout == "", "a second --skeleton does not overwrite an existing map")
smap = smap.replace("| GET /projects/health | ? |", "| GET /projects/health | anonymous |")
smap = smap.replace("| current_active_user | ? | `current_active_user` |",
                    "| signed_in | any account | `current_active_user` |")
smap = smap.replace("| PATCH /projects/{project_id} | current_active_user |", "| PATCH /projects/{project_id} | signed_in |")
ok("| require_project_role:OWNER | ? | `require_project_role(\"OWNER\")` |" in smap,
   "Python: a factory with a literal also gives a role with the literal")
smap = smap.replace("| require_project_role:OWNER | ? | `require_project_role(\"OWNER\")` |",
                    "| member | project member | `require_project_role(\"OWNER\")` |")
smap = smap.replace("| GET /projects/{project_id}/files | require_project_role:OWNER |", "| GET /projects/{project_id}/files | member |")
commit_file(d, "telesma/state/SECURITY_MAP.md", smap)

new_api = API_PY + DELETE_ROUTE
write(d, "backend/api.py", new_api)
dec, txt, _ = bash(d, "git add backend/api.py && git commit -m x")
ok(dec == "deny" and "route-outside-map" in txt and "DELETE /projects/{project_id}" in txt,
   "a new route without a row in the map blocks the commit")
write(d, "telesma/state/SECURITY_MAP.md", smap.replace("| GET /projects/health | anonymous | — |",
      "| GET /projects/health | anonymous | — |\n| DELETE /projects/{id} | member | project | backend/api.py |"))
dec, txt, _ = bash(d, "git add backend/api.py telesma/state/SECURITY_MAP.md && git commit -m x")
ok(dec == "deny" and "guard-mismatch" in txt and "route-outside-map" not in txt,
   "a row added in the same commit counts (another parameter name), but role member without require_project_role( → blocks")
write(d, "telesma/state/SECURITY_MAP.md", smap.replace("| GET /projects/health | anonymous | — |",
      "| GET /projects/health | anonymous | — |\n| DELETE /projects/{id} | member, signed_in | project | backend/api.py |"))
dec, txt, _ = bash(d, "git add backend/api.py telesma/state/SECURITY_MAP.md && git commit -m x")
ok(dec is None and "guard-mismatch" not in txt, "the alternative \"member, signed_in\" — a guard of one of the roles is enough")
subprocess.run(["git", "-C", str(d), "add", "backend/api.py", "telesma/state/SECURITY_MAP.md"], check=True)
subprocess.run(["git", "-C", str(d), "commit", "-qm", "delete"], check=True)

write(d, "backend/api.py", new_api.replace("async def update_project(project_id: str, user=Depends(current_active_user)):",
                                           "async def update_project(project_id: str):"))
dec, txt, _ = bash(d, "git add backend/api.py && git commit -m x")
ok(dec == "deny" and "guard-mismatch" in txt and "PATCH /projects/{project_id}" in txt,
   "a guard removed from an EXISTING route blocks (what sast cannot see)")
write(d, "telesma/state/SECURITY_MAP.md", smap.replace("| signed_in | any account | `current_active_user` |",
                                               "| signed_in | any account | (global) |"))
dec, txt, _ = bash(d, "git add backend/api.py telesma/state/SECURITY_MAP.md && git commit -m x")
ok("guard-mismatch" not in txt or "PATCH" not in txt, "a role with the guard (global) — the route's code is not checked")
subprocess.run(["git", "-C", str(d), "checkout", "-q", "backend/api.py", "telesma/state/SECURITY_MAP.md"], check=True)

print("  router with dependencies=")
write(d, "backend/admin.py", 'from fastapi import APIRouter, Depends\n\nadmin = APIRouter(\n    prefix="/admin",\n'
      '    dependencies=[Depends(require_superuser)],\n)\n\n\n@admin.get("/stats")\ndef stats():\n    return {}\n')
smap2 = (d / "telesma" / "state" / "SECURITY_MAP.md").read_text(encoding="utf-8").replace(
    "| anonymous | no session | — |", "| anonymous | no session | — |\n| superuser | operator | `require_superuser` |").replace(
    "| GET /projects/health | anonymous | — |", "| GET /projects/health | anonymous | — |\n| GET /admin/stats | superuser | — | backend/admin.py |")
write(d, "telesma/state/SECURITY_MAP.md", smap2)
dec, txt, _ = bash(d, "git add backend/admin.py telesma/state/SECURITY_MAP.md && git commit -m x")
ok(dec is None and "guard-mismatch" not in txt, "a guard from APIRouter(dependencies=[…]) over several lines counts for the route")
subprocess.run(["git", "-C", str(d), "add", "backend/admin.py", "telesma/state/SECURITY_MAP.md"], check=True)
subprocess.run(["git", "-C", str(d), "commit", "-qm", "admin"], check=True)

print("  outbound")
write(d, "backend/client.py", 'import os\nimport httpx\n\n'
      'KEY = os.environ["STRIPE_SECRET_KEY"]\nLEVEL = os.environ.get("LOG_LEVEL")\n'
      'def send(x):\n    return httpx.post("https://collector.io/x", json=x)\n'
      '# https://docs.other-host.dev/about — a comment\n'
      'PHOTO = "' + "QUJD" * 60 + '"\n'
      'def local():\n    return httpx.get("http://localhost:8000/health")\n')
write(d, "backend/migrations/0002.sql", "GRANT SELECT ON patient TO r_report;\nCREATE TABLE x (id int);\n")
dec, txt, _ = bash(d, "git add backend/client.py backend/migrations/0002.sql && git commit -m x")
ok(dec is None and "host-outside-map" in txt and "collector.io" in txt, "a new outbound host warns")
ok("other-host.dev" not in txt and "localhost" not in txt, "a host in a comment and localhost — silence")
ok("secret-outside-map" in txt and "STRIPE_SECRET_KEY" in txt and "LOG_LEVEL" not in txt,
   "a secret from the environment warns, an ordinary variable does not")
ok("encoded-blob" in txt, "a base64 literal > 200 characters warns")
ok("db-privilege" in txt and "GRANT SELECT ON patient" in txt, "GRANT in a migration warns")
write(d, "telesma/state/SECURITY_MAP.md", smap2.replace("| Kind | Value | Purpose |\n|---|---|---|\n",
      "| Kind | Value | Purpose |\n|---|---|---|\n| host | collector.io | analytics |\n| env | STRIPE_SECRET_KEY | payments |\n"
      "| db | grant select on patient to r_report | reports |\n"))
dec, txt, _ = bash(d, "git add backend/client.py backend/migrations/0002.sql telesma/state/SECURITY_MAP.md && git commit -m x")
ok(not re.search(r"host-outside-map|secret-outside-map|db-privilege", txt), "rows in ## Outbound silence the host, the secret and the privilege")
shutil.rmtree(d)

print("  Hono / Express (prefix from app.use) and a front end with axios")
d = new_repo()
commit_file(d, "README.md", "x\n")
HONO = '''import { Hono } from "jsr:@hono/hono";

const app = new Hono();
app.use("/doctor/*", requireRole("physician"));

app.post("/doctor/discharge/:id", async (c) => {
  return c.json({});
});

app.post("/admin/accounts", async (c) => {
  return c.json({});
});
'''
write(d, "src/app.ts", HONO)
write(d, "web/src/api.ts", "import axios from 'axios';\nconst api = axios.create();\nexport const u = () => api.get('/users');\n")
skeleton(d)
m = (d / "telesma" / "state" / "SECURITY_MAP.md").read_text(encoding="utf-8")
ok("| POST /doctor/discharge/:id | requireRole:physician |" in m and "/users" not in m,
   "Hono: a guard from app.use(prefix) in the route window; api.get in a file without a framework is a client, not a route")
ok("| POST /admin/accounts | ? |" in m, "a route outside the middleware prefix → role ?")
m = m.replace("| requireRole:physician | ? | `requireRole(\"physician\")` |", "| physician | physician | `requireRole(\"physician\")` |")
m = m.replace("| POST /doctor/discharge/:id | requireRole:physician |", "| POST /doctor/discharge/:id | physician |")
m = m.replace("| POST /admin/accounts | ? |", "| POST /admin/accounts | physician |")
write(d, "telesma/state/SECURITY_MAP.md", m)
dec, txt, _ = bash(d, "git add src/app.ts web/src/api.ts telesma/state/SECURITY_MAP.md && git commit -m x")
ok(dec == "deny" and "guard-mismatch" in txt and "/admin/accounts" in txt and "/doctor/discharge" not in txt,
   "a route under the prefix with requireRole(\"physician\") passes, a route outside the prefix with role physician blocks")
shutil.rmtree(d)

print("  Nest")
d = new_repo()
write(d, "src/patient.controller.ts", '''import { Controller, Get, UseGuards } from "@nestjs/common";

@UseGuards(JwtGuard)
@Controller("patients")
export class PatientController {
  @Get(":id")
  getOne() {}

  @Roles("admin")
  @Get()
  list() {}
}
''')
skeleton(d)
m = (d / "telesma" / "state" / "SECURITY_MAP.md").read_text(encoding="utf-8")
ok("| GET /patients/:id | JwtGuard |" in m and any(l.startswith("| GET /patients |") and "JwtGuard" in l
       and "Roles:admin" in l for l in m.splitlines()),
   "Nest: class @UseGuards + method @Roles, prefix from @Controller")
shutil.rmtree(d)

print("Check: red-team")
d = new_repo()
API2 = '''from fastapi import APIRouter, Depends

r = APIRouter()


@r.patch("/projects/{project_id}")
async def change(project_id: str, m=Depends(require_member)):
    return {}


@r.get("/health")
def health():
    return "ok"
'''
commit_file(d, "backend/api.py", API2)
MAP_RT = ("# Map\n\n- **Session**: cookie\n\n## Roles\n\n| Role | Who | Guard in code |\n|---|---|---|\n"
          "| anonymous | no session | — |\n| member | member | `require_member` |\n| admin | admin | `require_admin` |\n\n"
          "## Routes\n\n| Route | Roles | Ownership | File |\n|---|---|---|---|\n"
          "| PATCH /projects/{project_id} | member | project | backend/api.py |\n| GET /health | anonymous | — | backend/api.py |\n")
subprocess.run(["git", "-C", str(d), "tag", "telesma/phase-1"], check=True)
commit_file(d, "telesma/state/SECURITY_MAP.md", MAP_RT)
commit_file(d, "backend/api.py", API2.replace("return {}", "return {'ok': 1}"))
dec, txt, _ = bash(d, "git tag telesma/phase-2")
ok(dec is None and "red-team-missing" in txt and "first phase with the map" in txt,
   "the first phase after the map is created: a missing red team only warns")
subprocess.run(["git", "-C", str(d), "tag", "-f", "telesma/phase-2"], check=True)
commit_file(d, "backend/api.py", API2.replace("return {}", "return {'ok': 2}").replace('return "ok"', 'return "ok!"'))
dec, txt, _ = bash(d, "git tag telesma/phase-3")
ok(dec == "deny" and "red-team-missing" in txt and "no-session, foreign-role, foreign-owner, csrf" in txt,
   "the next phase: a changed protected route without a red team blocks the tag; the message lists all cases from the map")
ok("/health" not in txt, "a public route needs no red team")
commit_file(d, "tests/test_rt.py", "# telesma: red-team PATCH /api/projects/{id} — no-session, csrf\ndef test_x():\n    assert 1\n")
dec, txt, _ = bash(d, "git tag telesma/phase-3")
ok(dec == "deny" and "red team missing: foreign-role, foreign-owner" in txt,
   "a marker with an /api prefix and another parameter name matches; the missing cases remain")
commit_file(d, "tests/test_rt2.py", "// telesma: red-team PATCH /projects/:project_id — foreign-role, other-organization\n")
dec, txt, _ = bash(d, "git tag telesma/phase-3")
ok(dec is None and "red-team-missing" not in txt, "markers in two files add up; the alias other-organization = foreign-owner")
commit_file(d, "telesma/state/SECURITY_MAP.md", MAP_RT.replace("- **Session**: cookie", "- **Session**: header"))
(d / "tests" / "test_rt.py").unlink()
commit_file(d, "tests/test_rt3.py", "# telesma: red-team PATCH /projects/{p} — no-session\n")
subprocess.run(["git", "-C", str(d), "rm", "-q", "tests/test_rt.py"], check=True)
subprocess.run(["git", "-C", str(d), "commit", "-qm", "rm"], check=True)
dec, txt, _ = bash(d, "git tag telesma/phase-3")
ok(dec is None and "csrf" not in txt, "Session: header → csrf is not required")
shutil.rmtree(d)

print("  Hono: sub-apps mounted in another file (shape from a medical project)")
d = new_repo()
commit_file(d, "src/main.ts", '''import { Hono } from "jsr:@hono/hono";
import { createDoctorRoutes } from "./doctor.tsx";
import { createAdminRoutes } from "./admin.tsx";

const app = new Hono();
app.use("*", csrf(base));
app.get("/healthz", async (context) => context.json({ ok: true }));
app.route("/doctor", createDoctorRoutes(deps.authorize, deps.admin));
app.route("/admin", createAdminRoutes(deps.authorize));
''')
commit_file(d, "src/doctor.tsx", '''import { Hono } from "jsr:@hono/hono";
import { patientRoutes } from "./patients.tsx";

export function createDoctorRoutes(authorize: AuthorizeDeps, deps: AdminDeps): Hono<AppEnv> {
  const routes = new Hono<AppEnv>();
  routes.use("*", requireAuth(authorize));
  routes.use("*", requireRole("doctor"));
  routes.get("/", async (context) => context.html("doctor"));
  patientRoutes(routes, authorize, deps);
  return routes;
}
''')
commit_file(d, "src/patients.tsx", '''import type { Hono } from "jsr:@hono/hono";

export function patientRoutes(
  routes: Hono<AppEnv>,
  authorize: AuthorizeDeps,
  deps: AdminDeps,
): void {
  routes.get("/patients/:id", async (context) => {
    return context.html("chart");
  });
}
''')
commit_file(d, "src/admin.tsx", '''import { Hono } from "jsr:@hono/hono";

export function createAdminRoutes(authorize: AuthorizeDeps): Hono<AppEnv> {
  const routes = new Hono<AppEnv>();
  routes.use("*", requireAuth(authorize));
  routes.use("*", requireRole("admin"));
  routes.get("/", async (context) => context.html("admin"));
  return routes;
}
''')
skeleton(d)
m = (d / "telesma" / "state" / "SECURITY_MAP.md").read_text(encoding="utf-8")
row = lambda t: next((l for l in m.splitlines() if l.startswith(f"| {t} |")), "")
ok("requireRole:doctor" in row("GET /doctor") and "requireRole:admin" in row("GET /admin")
   and "| GET / |" not in m, "prefix from app.route(\"/doctor\", createDoctorRoutes(…)) — two `GET /` from different modules are two routes")
ok("requireRole:doctor" in row("GET /doctor/patients/:id") and "requireAuth" in row("GET /doctor/patients/:id"),
   "patientRoutes(routes, …): the prefix and guards from the file that passes the routes object (two levels)")
ok("| requireRole:doctor | ? | `requireRole(\"doctor\")` |" in m and "| requireRole:admin |" in m,
   "a factory with a literal gives separate roles (doctor ≠ admin), a token with the literal")
ok("context" not in [l.split("|")[1].strip() for l in m.splitlines() if l.startswith("| ")]
   and "authorize |" not in m, "a handler parameter (context) and a guard argument (authorize) are not roles")
ok("| GET /healthz | ? |" in row("GET /healthz") + " |" or row("GET /healthz").startswith("| GET /healthz | ? |"),
   "a route without a guard in main.ts → role ?")
m = m.replace("| GET /admin | requireAuth + requireRole:admin |", "| GET /admin | requireAuth + requireRole:doctor |")
commit_file(d, "telesma/state/SECURITY_MAP.md", m)
write(d, "src/admin.tsx", (d / "src" / "admin.tsx").read_text().replace('context.html("admin")', 'context.html("admin!")'))
dec, txt, _ = bash(d, "git add src/admin.tsx && git commit -m x")
ok(dec == "deny" and "guard-mismatch" in txt and "GET /admin" in txt,
   "the map assigns the admin route to the doctor — the check sees requireRole(\"admin\") instead of doctor and blocks")
shutil.rmtree(d)

print("  red-team: a marker with a wildcard")
d = new_repo()
commit_file(d, "backend/api.py", API2)
subprocess.run(["git", "-C", str(d), "tag", "telesma/phase-1"], check=True)
commit_file(d, "telesma/state/SECURITY_MAP.md", MAP_RT)
subprocess.run(["git", "-C", str(d), "tag", "-f", "telesma/phase-1"], check=True)
commit_file(d, "backend/api.py", API2.replace("return {}", "return {'ok': 3}"))
commit_file(d, "tests/test_rt.py", "# telesma: red-team * /projects/* — no-session, foreign-role, csrf\n"
                                   "# telesma: red-team * /other/* — foreign-owner\n")
dec, txt, _ = bash(d, "git tag telesma/phase-2")
ok(dec == "deny" and "red team missing: foreign-owner" in txt,
   "`* /projects/*` covers a route under the prefix; a marker under another prefix does not")
shutil.rmtree(d)

print("Protection of the check files")
d = new_repo()
dec, _, _ = hook(d, "Write", {"file_path": str(d / "telesma" / "state" / "CHECK_EXCEPTIONS.md"), "content": "x"})
ok(dec == "ask", "a write to CHECK_EXCEPTIONS.md asks the human")
dec, _, _ = hook(d, "Edit", {"file_path": str(d / "telesma" / "checks" / "secrets" / "run.py"),
                             "old_string": "a", "new_string": "b"})
ok(dec == "ask", "an edit of a check module asks the human")
cfg = (d / "telesma" / "config.md").read_text(encoding="utf-8")
dec, _, _ = hook(d, "Edit", {"file_path": str(d / "telesma" / "config.md"),
                             "old_string": "- **Enabled**: yes", "new_string": "- **Enabled**: no"})
ok(dec == "ask", "disabling the checks in the config asks the human")
dec, _, _ = hook(d, "Edit", {"file_path": str(d / "telesma" / "config.md"),
                             "old_string": "- **Auto-commit**: yes", "new_string": "- **Auto-commit**: no"})
ok(dec is None, "an edit of another config section does not ask")
dec, _, _ = hook(d, "Write", {"file_path": str(d / "telesma" / "config.md"),
                              "content": cfg.replace("### secrets", "### secretsX")})
ok(dec == "ask", "overwriting the config with a changed Checks section asks")
dec, _, _ = hook(d, "Write", {"file_path": str(d / "telesma" / "config.md"),
                              "content": cfg.replace("Auto-commit**: yes", "Auto-commit**: no")})
ok(dec is None, "overwriting the config without changing the Checks section does not ask")
dec, _, _ = bash(d, "echo '- `abcdefabcdef` x' >> telesma/state/CHECK_EXCEPTIONS.md")
ok(dec == "ask", "appending an exception from Bash asks the human")
dec, _, _ = bash(d, "cat telesma/state/CHECK_EXCEPTIONS.md")
ok(dec is None, "reading the exceptions file does not ask")
shutil.rmtree(d)

# --- Validation -------------------------------------------------------------------------------
print("Config validation")
d = new_repo(extra="### unknown-check\n- **When**: commit\n\n### weakenings2\n- **When**: always\n")
(d / "telesma" / "checks" / "weakenings2").mkdir()
shutil.copy(d / "telesma" / "checks" / "weakenings" / "CHECK.md", d / "telesma" / "checks" / "weakenings2" / "CHECK.md")
w = rc.validate(str(d))
ok(any(x.startswith("E:") and "unknown-check" in x for x in w), "a check without a module → an error")
ok(any(x.startswith("E:") and "always" in x for x in w), "an unknown point in When → an error")
ok(not any(x.startswith(("W:## Checks → secrets", "E:## Checks → secrets")) for x in w),
   "secrets: the validator is silent with and without gitleaks (built-in mode is a supported mode)")
shutil.rmtree(d)
d = new_repo(enabled="no")
ok(rc.validate(str(d)) == [], "Enabled: no → the validator is silent")
shutil.rmtree(d)

print("The runner reads every ### subsection of ## Checks")
with tempfile.TemporaryDirectory() as t:
    (Path(t) / "telesma" / "state").mkdir(parents=True)
    (Path(t) / "telesma" / "config.md").write_text(
        "# C\n\n## Checks\n\n- **Enabled**: yes\n  <!-- c -->\n\n### secrets\n- **When**: commit\n\n"
        "### dependencies\n- **When**: commit, ci\n\n### dependency-audit\n- **When**: phase\n\n## Permissions\n",
        encoding="utf-8")
    ok(set(rc.load_config(t)["checks"]) == {"secrets", "dependencies", "dependency-audit"},
       "the runner sees every configured check")

# --- telesma.sh ------------------------------------------------------------------------
# The fragments are found by what they do, not by heredoc names or comments, so the test does
# not depend on how the launcher names its helpers.


def launcher_block(marker):
    """The launcher's `    if …; then … fi` block (4-space indent, with its leading comment) that contains `marker`."""
    i = LAUNCHER.find(marker)
    if i < 0:
        return None
    start = LAUNCHER.rfind("\n    if ", 0, i)
    while True:                                  # step back over the comment lines above the block
        prev = LAUNCHER.rfind("\n", 0, start)
        if LAUNCHER[prev + 1:start].startswith("    #"):
            start = prev
        else:
            break
    end = LAUNCHER.index("\n    fi\n", i) + len("\n    fi\n")
    return LAUNCHER[start:end]


print("Hook installation (settings.local.json)")
hd = next((m for m in re.finditer(r"<<'(\w+)'\n(.*?)\n\1\n", LAUNCHER, re.S)
           if "telesma-checks.py" in m.group(2) and "PostToolUse" in m.group(2)), None)
ok(hd is not None, "the launcher has a heredoc that installs the checks hook")
if hd is not None:
    # the value the heredoc treats as "enabled" (argv[2] == '<value>'); anything else disables
    m_on = re.search(r"== '(\w+)'", hd.group(2))
    on = m_on.group(1) if m_on else "yes"
    off = "off"
    with tempfile.TemporaryDirectory() as t:
        sp = Path(t) / ".claude" / "settings.local.json"
        sp.parent.mkdir()
        sp.write_text(json.dumps({"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
            {"type": "command", "command": "python3 x/telesma-permission-judge.py --pretooluse"}]}]},
            "permissions": {"allow": ["Bash(ls:*)"]}}), encoding="utf-8")
        subprocess.run([sys.executable, "-", str(sp), on], input=hd.group(2), text=True, check=True)
        s = json.loads(sp.read_text())
        blob = json.dumps(s)
        ok("telesma-checks.py" in blob and "telesma-permission-judge" in blob, "enabling adds the hook, the judge stays")
        ok(any("--posttooluse" in json.dumps(h) for h in s["hooks"].get("PostToolUse", [])), "enabling adds the PostToolUse hook (evidence + status)")
        subprocess.run([sys.executable, "-", str(sp), on], input=hd.group(2), text=True, check=True)
        ok(json.dumps(json.loads(sp.read_text())).count("telesma-checks.py") == 2, "a second start does not duplicate the hooks (one per event)")
        subprocess.run([sys.executable, "-", str(sp), off], input=hd.group(2), text=True, check=True)
        s = json.loads(sp.read_text())
        ok("telesma-checks.py" not in json.dumps(s) and "telesma-permission-judge" in json.dumps(s)
           and s["permissions"]["allow"] == ["Bash(ls:*)"] and "PostToolUse" not in s["hooks"], "disabling removes only our hooks (both events)")

print("Start: map skeleton and the attack surface in the VERSIONS line")
block_skel = launcher_block("--skeleton")
block_ver = launcher_block("hash-object -t tree /dev/null")
ok(block_skel is not None and "SECURITY_MAP.md" in block_skel, "the launcher writes the map skeleton (intent --skeleton)")
ok(block_ver is not None and "SECURITY_MAP.md" in block_ver, "the launcher counts map changes for the VERSIONS line")
if block_skel and block_ver:
    d = new_repo()
    commit_file(d, "app.py", "from fastapi import FastAPI\napp = FastAPI()\n\n\n@app.get('/a')\ndef a():\n    return 1\n")
    scr = (f'set -e\nPROJECT_DIR="{d}"\nCONFIG_FILE="{d}/telesma/config.md"\nCHECKS_DIR="{d}/telesma/checks"\n'
           f'GREEN=; YELLOW=; CYAN=; NC=\nif true; then{block_skel}fi\necho REACHED\n')
    r = subprocess.run(["bash", "-c", scr], capture_output=True, text=True)
    ok(r.returncode == 0 and "REACHED" in r.stdout and (d / "telesma" / "state" / "SECURITY_MAP.md").exists()
       and "1 routes" in r.stdout, f"no map + intent check in the config → skeleton at start (under set -e) ({r.stdout[-200:]!r} {r.stderr[-200:]!r})")
    r = subprocess.run(["bash", "-c", scr], capture_output=True, text=True)
    ok("skeleton" not in r.stdout, "the map exists → the start does not touch it")
    commit_file(d, "telesma/state/SECURITY_MAP.md", (d / "telesma" / "state" / "SECURITY_MAP.md").read_text())
    subprocess.run(["git", "-C", str(d), "tag", "v0.1.0"], check=True)
    m = (d / "telesma" / "state" / "SECURITY_MAP.md").read_text()
    m = m.replace("| GET /a | ? | — | app.py |", "| GET /a | anonymous | — | app.py |\n| POST /b | anonymous | — | app.py |\n| GET /c | x | — | app.py |")
    m = m.replace("| anonymous | no session | — |", "| anonymous | no session | — |\n| x | someone | `x` |")
    commit_file(d, "telesma/state/SECURITY_MAP.md", m)
    last_var = re.search(r'="\$\{(\w+):-\$\(git', block_ver).group(1)
    hint_var = re.search(r'(\w+)\+="; ', block_ver).group(1)
    since_start = next(x for x in re.findall(r"\$\{" + last_var + r":-([^}$]+)\}", block_ver))
    scr = (f'set -e\nPROJECT_DIR="{d}"\n{last_var}=v0.1.0\n{hint_var}=start\nif true; then{block_ver}fi\n'
           f'echo "${hint_var}"\n')
    r = subprocess.run(["bash", "-c", scr], capture_output=True, text=True)
    ok(r.returncode == 0 and re.search(r"\+3 / −1 \D*\(2 public\w*\), 1 ", r.stdout) is not None,
       f"the VERSIONS line counts map changes since the version: {r.stdout.strip()[-110:]}")
    scr2 = scr.replace(f"{last_var}=v0.1.0", f"{last_var}=")
    r = subprocess.run(["bash", "-c", scr2], capture_output=True, text=True)
    ok(r.returncode == 0 and since_start in r.stdout, f"no version — from the start of the map ({since_start!r})")
    shutil.rmtree(d)

print()
if FAILURES:
    print(f"FAILURES: {len(FAILURES)}")
    sys.exit(1)
print("All green.")
