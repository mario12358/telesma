#!/bin/bash
# What Telesma needs on this machine, checked before anything touches the project:
#
#   preflight          silent when everything is there; otherwise one line per missing piece with
#                      what to install or run, for this system — and the launcher stops
#   preflight verbose  the same with a ✓ line per piece (telesma.sh --doctor)
#
# Needed: git, Python 3.9+ as `python3` (hooks, checks and tools call it by that name), the
# Claude Code CLI and a signed-in Claude account. On Windows Telesma runs in Git Bash (Claude Code
# needs it there too); python.org installs `python` and `py`, while `python3` is usually the
# Microsoft Store placeholder — the most common snag, so it gets its own advice and an offer to
# fix it. Sourced by telesma.sh after msg.sh; plain Bash 3.2.

PREFLIGHT_OS=other
case "$(uname -s 2>/dev/null)" in
    Darwin) PREFLIGHT_OS=mac ;;
    Linux) PREFLIGHT_OS=linux ;;
    MINGW*|MSYS*|CYGWIN*) PREFLIGHT_OS=windows ;;
esac

# python3 works and is 3.9+ (the Store placeholder exits with an error or prints nothing)
preflight_python_ok() {
    [[ "$("${1:-python3}" -c 'import sys; print(sys.version_info >= (3, 9))' 2>/dev/null | tr -d '\r')" == "True" ]]
}

# Windows: a working `python` / `py -3` exists but `python3` does not → offer a python3.exe copy
# next to python.exe (every process then finds it: Git Bash, Claude Code, the hooks).
preflight_fix_windows_python() {
    local exe="" dir answer cand
    for cand in python "py -3"; do
        # shellcheck disable=SC2086  # "py -3" is a command with an argument
        if preflight_python_ok $cand; then
            # shellcheck disable=SC2086
            exe=$($cand -c 'import sys; print(sys.executable)' 2>/dev/null | tr -d '\r')
            break
        fi
    done
    [[ -n "$exe" ]] || return 1
    command -v cygpath > /dev/null 2>&1 && exe=$(cygpath -u "$exe")
    dir=$(dirname "$exe")
    echo -e "$(msg pre.py.win1 'Python is installed (%s), but under the name python, and Telesma calls python3.' "$exe")"
    read -r -p "$(msg pre.py.win.ask 'Create python3.exe next to it (a copy of python.exe)?') [$(msg yes.no 'Y/n')]: " answer < /dev/tty || answer=n
    case "$(printf '%s' "$answer" | tr '[:upper:]' '[:lower:]')" in
        ""|y|yes|"$(msg yes.short 'y')"|"$(msg yes.word 'yes')") ;;
        *) return 1 ;;
    esac
    cp "$exe" "$dir/python3.exe" 2>/dev/null || return 1
    hash -r
    preflight_python_ok
}

# The programs the project's own commands call (## Tests in telesma/config.md): the first word of
# each command — `dotnet`, `uv`, `npm` … — space-separated, each once.
#   preflight_stack_tools <config>            every command of ## Tests
#   preflight_stack_tools --command "<cmd>"   one command only (the baseline at adoption runs just
#                                             the suite: a missing linter must not stop it)
preflight_stack_tools() {
    python3 - "$1" "${2:-}" <<'PYTOOLS'
import re, sys
from pathlib import Path
values = []
if sys.argv[1] == "--command":
    values = [sys.argv[2]]
else:
    try:
        text = Path(sys.argv[1]).read_text(encoding="utf-8")
    except OSError:
        sys.exit()
    section = re.search(r"^## Tests[ \t]*\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    for field in ("Test command", "Full suite command", "Smoke suite", "Linter/formatter", "Typecheck command"):
        m = re.search(r"^- \*\*" + re.escape(field) + r"\*\*:[ \t]*(.*)$", section.group(1) if section else "", re.M)
        values.append((m.group(1) if m else ""))
seen = []
for value in values:
    value = value.strip().strip("`")
    if not value or value.startswith("[") or value.lower().startswith("none"):
        continue
    for part in re.split(r"&&|\|\||[;|]", value):
        words = part.split()
        while words and (words[0] in ("env", "time", "command") or re.match(r"^[A-Za-z_]\w*=", words[0])):
            words.pop(0)
        tool = words[0].strip("`'\"") if words else ""
        if not tool or tool in ("cd", "export", "echo", "true") or tool.startswith((".", "/", "$")):
            continue
        if tool not in seen:
            seen.append(tool)
print(" ".join(seen))
PYTOOLS
}

# Where a tool comes from: "<winget id>|<brew arguments>|<a page, or a shell command for elsewhere>"
preflight_tool_source() {
    case "$1" in
        dotnet) echo "Microsoft.DotNet.SDK.10|--cask dotnet-sdk|https://dotnet.microsoft.com/download" ;;
        uv|uvx) echo "astral-sh.uv|uv|curl -LsSf https://astral.sh/uv/install.sh | sh" ;;
        node|npm|npx) echo "OpenJS.NodeJS.LTS|node|https://nodejs.org/" ;;
        cargo|rustc) echo "Rustlang.Rustup||https://rustup.rs/" ;;
        go) echo "GoLang.Go|go|https://go.dev/dl/" ;;
        *) echo "||" ;;
    esac
}

# Smart App Control (Windows 11): on | evaluation | off | "" (not Windows, or no such setting).
# HKLM\SYSTEM\CurrentControlSet\Control\CI\Policy → VerifiedAndReputablePolicyState: 1 on,
# 2 evaluation (watches, blocks nothing), 0 off. MSYS_NO_PATHCONV keeps Bash from turning /v
# into a path.
preflight_smart_app_control() {
    local v
    [[ "$PREFLIGHT_OS" == windows ]] || return 0
    v=$(MSYS_NO_PATHCONV=1 reg query 'HKLM\SYSTEM\CurrentControlSet\Control\CI\Policy' /v VerifiedAndReputablePolicyState 2>/dev/null \
        | tr -d '\r' | awk '$1 == "VerifiedAndReputablePolicyState" { print $3 }')
    case "$v" in
        0x1|1) echo on ;;
        0x2|2) echo evaluation ;;
        0x0|0) echo off ;;
    esac
}

# A stack that compiles its own executables and libraries (.NET, Rust, Go, C/C++, Flutter): with
# Smart App Control on, Windows refuses to run what was just built — the program, and the tests,
# which load the project's own unsigned DLLs. It has no "run anyway" (unlike SmartScreen), and the
# first Windows beginner project stopped half-way on it three times. Interpreted stacks (Python,
# Node) run in a signed interpreter and pass; their packaged .exe is the guideline's matter.
preflight_sac_blocks() {
    local tool
    for tool in $1; do
        case "$tool" in
            dotnet|cargo|rustc|go|cmake|msbuild|cl|flutter|dart|gradle|gradlew) return 0 ;;
        esac
    done
    return 1
}

# The project's tools (preflight_stack_tools) are on this machine. The stack is chosen in the
# interview or the wizard, so this runs before a session that builds, not before everything.
# A missing tool: what to install on this system; with winget (Windows) or Homebrew (macOS) and a
# terminal, an offer to install it now — run only after "yes". Returns 1 when one is still missing.
#   preflight_stack <config> [verbose] [command]   with a command: only the tools that command calls
preflight_stack() {
    local config="$1" verbose="${2:-}" only="${3:-}" tool tools missing=0 offered="" src winget brew other cmd answer sac
    local ok="${GREEN}✓${NC}" no="${RED}✗${NC}"
    if [[ -n "$only" ]]; then
        tools=$(preflight_stack_tools --command "$only")
    else
        tools=$(preflight_stack_tools "$config")
    fi
    sac=$(preflight_smart_app_control)
    if [[ "$sac" == on ]] && preflight_sac_blocks "$tools"; then
        echo -e "  $no $(msg pre.sac 'Smart App Control is on in this Windows: it refuses to run programs that are not signed — and what Telesma builds here is not, the tests included.')"
        echo -e "    $(msg pre.sac.off 'To build on this computer, turn it off: Windows Security → App & browser control → Smart App Control settings → Off.')"
        echo -e "    $(msg pre.sac.back 'On many Windows versions it cannot be turned back on without reinstalling Windows — the choice is yours.')"
        echo -e "    $(msg pre.sac.else 'Or build on another computer, or pick a technology that runs inside a signed program (Python, a web app).')"
        missing=1
    elif [[ -n "$sac" && -n "$verbose" ]]; then
        case "$sac" in
            on) sac=$(msg pre.sac.onword 'on — this project runs in a signed interpreter, it is not affected') ;;
            evaluation) sac=$(msg pre.sac.eval 'evaluation (blocks nothing)') ;;
            *) sac=$(msg pre.sac.offword 'off') ;;
        esac
        echo -e "  $ok $(msg pre.sac.state 'Smart App Control: %s' "$sac")"
    fi
    for tool in $tools; do
        if command -v "$tool" > /dev/null 2>&1; then
            [[ -n "$verbose" ]] && echo -e "  $ok $tool"
            continue
        fi
        src=$(preflight_tool_source "$tool")
        winget=${src%%|*}; src=${src#*|}; brew=${src%%|*}; other=${src#*|}
        # npm and npx come with the same Node.js: one offer
        if [[ -n "$winget$brew$other" && " $offered " == *" $winget$brew "* ]]; then
            continue
        fi
        offered+=" $winget$brew"
        echo -e "  $no $(msg pre.tool '%s is not installed — this project is built and tested with it.' "$tool")"
        cmd=""
        if [[ "$PREFLIGHT_OS" == windows && -n "$winget" ]] && command -v winget > /dev/null 2>&1; then
            cmd="winget install --id $winget -e --accept-source-agreements --accept-package-agreements"
        elif [[ "$PREFLIGHT_OS" == mac && -n "$brew" ]] && command -v brew > /dev/null 2>&1; then
            cmd="brew install $brew"
        fi
        if [[ -n "$cmd" ]] && { true < /dev/tty; } 2>/dev/null; then
            read -r -p "    $(msg pre.tool.ask 'Install it now with %s?' "$cmd") [$(msg yes.no 'Y/n')]: " answer < /dev/tty || answer=n
            case "$(printf '%s' "$answer" | tr '[:upper:]' '[:lower:]')" in
                ""|y|yes|"$(msg yes.short 'y')"|"$(msg yes.word 'yes')")
                    # shellcheck disable=SC2086  # $cmd is one of the fixed commands above
                    if $cmd; then
                        hash -r
                        if command -v "$tool" > /dev/null 2>&1; then
                            echo -e "  $ok $tool"
                            continue
                        fi
                        echo -e "    $(msg pre.tool.reopen 'Installed. A new program is seen only in a new window: close this one and start Telesma again.')"
                    fi ;;
            esac
        elif [[ -n "$cmd" ]]; then
            echo -e "    $(msg pre.tool.cmd 'Install it with: %s' "${CYAN}$cmd${NC}")"
        elif [[ "$other" == http* ]]; then
            echo -e "    $(msg pre.tool.page 'Install it from %s, then open a new window.' "${CYAN}$other${NC}")"
        elif [[ -n "$other" ]]; then
            echo -e "    $(msg pre.tool.cmd 'Install it with: %s' "${CYAN}$other${NC}")"
        else
            echo -e "    $(msg pre.tool.any 'Install it (the commands in ## Tests of telesma/config.md call it), then open a new window.')"
        fi
        missing=1
    done
    return "$missing"
}

preflight() {
    local verbose="${1:-}" missing=0 out
    local ok="${GREEN}✓${NC}" no="${RED}✗${NC}"

    # `git --version`, not `command -v`: macOS ships a /usr/bin/git that only offers to install it.
    if git --version > /dev/null 2>&1; then
        [[ -n "$verbose" ]] && echo -e "  $ok git"
    else
        missing=1
        echo -e "  $no $(msg pre.git 'git is not installed.')"
        case "$PREFLIGHT_OS" in
            mac) echo -e "    $(msg pre.git.mac 'Install it with: %s (a system window asks you to confirm).' "${CYAN}xcode-select --install${NC}")" ;;
            windows) echo -e "    $(msg pre.git.win 'Install Git for Windows: %s — and start Telesma from Git Bash.' "${CYAN}https://git-scm.com/download/win${NC}")" ;;
            *) echo -e "    $(msg pre.git.other 'Install it with your system package manager (e.g. %s).' "${CYAN}sudo apt install git${NC}")" ;;
        esac
    fi

    if preflight_python_ok; then
        [[ -n "$verbose" ]] && echo -e "  $ok $(python3 --version 2>&1 | tr -d '\r')"
    elif [[ "$PREFLIGHT_OS" == windows ]] && { true < /dev/tty; } 2>/dev/null && preflight_fix_windows_python; then
        echo -e "  $ok $(msg pre.py.fixed 'python3 is ready.')"
    else
        missing=1
        if command -v python3 > /dev/null 2>&1 && "python3" -c 'import sys' > /dev/null 2>&1; then
            echo -e "  $no $(msg pre.py.old 'Python is too old: %s — Telesma needs 3.9 or newer.' "$(python3 --version 2>&1 | tr -d '\r')")"
        else
            echo -e "  $no $(msg pre.py 'Python 3 (python3) is not installed.')"
        fi
        case "$PREFLIGHT_OS" in
            mac) echo -e "    $(msg pre.py.mac 'Install it from %s (the macOS installer) and open a new Terminal window.' "${CYAN}https://www.python.org/downloads/${NC}")" ;;
            windows)
                echo -e "    $(msg pre.py.win2 'Install it from %s — tick «Add python.exe to PATH» in the first window.' "${CYAN}https://www.python.org/downloads/windows/${NC}")"
                echo -e "    $(msg pre.py.win3 'Then turn off the Store placeholders: Settings → Apps → Advanced app settings → App execution aliases → python.exe and python3.exe off.')"
                echo -e "    $(msg pre.py.win4 'Open a new Git Bash window and start Telesma again — it offers to finish the setup.')" ;;
            *) echo -e "    $(msg pre.py.other 'Install it with your system package manager (e.g. %s).' "${CYAN}sudo apt install python3${NC}")" ;;
        esac
    fi

    if command -v claude > /dev/null 2>&1; then
        # `claude auth status` prints JSON; only an explicit "loggedIn": false counts as missing —
        # an older CLI without the command, or an API key in the environment, passes.
        out=$(claude auth status 2>/dev/null | tr -d '\r' || true)
        if [[ -z "${ANTHROPIC_API_KEY:-}" ]] && grep -q '"loggedIn":[[:space:]]*false' <<<"$out"; then
            missing=1
            echo -e "  $no $(msg pre.login 'Claude Code is installed but not signed in.')"
            echo -e "    $(msg pre.login.how 'Sign in with: %s (a browser window opens), then start Telesma again.' "${CYAN}claude auth login${NC}")"
        elif [[ -n "$verbose" ]]; then
            echo -e "  $ok Claude Code ($(claude --version 2>/dev/null | head -1 | tr -d '\r'))"
        fi
    else
        missing=1
        echo -e "  $no $(msg pre.claude 'Claude Code (claude) is not installed.')"
        case "$PREFLIGHT_OS" in
            windows) echo -e "    $(msg pre.claude.win 'In PowerShell: %s — then open a new Git Bash window.' "${CYAN}irm https://claude.ai/install.ps1 | iex${NC}")" ;;
            *) echo -e "    $(msg pre.claude.unix 'In Terminal: %s — then open a new Terminal window.' "${CYAN}curl -fsSL https://claude.ai/install.sh | bash${NC}")" ;;
        esac
        echo -e "    $(msg pre.claude.plan 'It needs a Claude account with a paid plan (Pro or Max) or an API key.')"
    fi

    # A copy with Windows line endings breaks Bash on the first line that has one.
    if grep -q $'\r' "$SCRIPT_DIR/templates/messages/msg.sh" 2>/dev/null; then
        missing=1
        echo -e "  $no $(msg pre.crlf 'Telesma was copied with Windows line endings, which Bash cannot read.')"
        echo -e "    $(msg pre.crlf.how 'Clone it again with: %s' "${CYAN}git clone -c core.autocrlf=false …${NC}")"
    fi

    if [[ "$missing" -eq 0 ]]; then
        [[ -n "$verbose" ]] && echo -e "${GREEN}$(msg pre.ready 'Everything Telesma needs is in place.')${NC}"
        return 0
    fi
    echo ""
    echo -e "${YELLOW}$(msg pre.missing 'Telesma cannot start until the pieces above are in place. Then run the same command again.')${NC}"
    return 1
}
