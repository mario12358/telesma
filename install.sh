#!/bin/bash
# Telesma installer for macOS (Linux: everything but the shortcut). Gets what Telesma needs, then
# Telesma itself (plus the `telesma` command in ~/.local/bin), signs in to Claude and puts a
# «Telesma» shortcut on the desktop that opens the
# start menu (telesma.sh --home) — after this a person never types a path or a command:
#
#   curl -fsSL https://raw.githubusercontent.com/mario12358/telesma/main/install.sh | bash
#
# Every installation asks first. Running it again keeps what is there and updates Telesma.
# The script arrives on stdin, so every answer is read from /dev/tty. Its lines come from
# templates/messages/<lang>.txt (fetched before the clone, English when there is none).
# Installed is the latest release (the newest vX.Y.Z tag on the branch); TELESMA_FOLLOW_BRANCH=1
# installs the branch tip instead and makes the launcher's update follow the branch too.
# Overrides (tests, forks): TELESMA_REPO (a URL or a local clone), TELESMA_BRANCH,
# TELESMA_INSTALL_DIR, TELESMA_PROJECTS, TELESMA_DESKTOP, TELESMA_APPS.

set -e

REPO="${TELESMA_REPO:-https://github.com/mario12358/telesma.git}"
BRANCH="${TELESMA_BRANCH:-main}"
DEST="${TELESMA_INSTALL_DIR:-$HOME/.telesma}"
# Not in Documents: iCloud syncs it on many Macs and moves file contents to the cloud ("dataless"),
# which breaks a project's Python environment and its git history
PROJECTS="${TELESMA_PROJECTS:-$HOME/Telesma}"
DESKTOP="${TELESMA_DESKTOP:-$HOME/Desktop}"
APPS="${TELESMA_APPS:-$HOME/Applications}"
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'; NC='\033[0m'

# --- messages: the same catalog and lookup as templates/messages/msg.sh ---------------------------
MSG_LANG=$(printf '%s' "${LC_ALL:-${LC_MESSAGES:-${LANG:-}}}" | cut -c1-2 | tr '[:upper:]' '[:lower:]')
CATALOG=$(mktemp)
trap 'rm -f "$CATALOG"' EXIT
if [[ -n "$MSG_LANG" && "$MSG_LANG" != en ]]; then
    if [[ -d "$REPO" ]]; then
        cp "$REPO/templates/messages/$MSG_LANG.txt" "$CATALOG" 2>/dev/null || true
    else
        curl -fsSL "https://raw.githubusercontent.com/mario12358/telesma/$BRANCH/templates/messages/$MSG_LANG.txt" \
            -o "$CATALOG" 2>/dev/null || true
    fi
fi
msg() {
    local key="$1" text="$2" t
    shift 2
    t=$(awk -v k="$key" 'substr($0, 1, length(k) + 3) == k " = " { print substr($0, length(k) + 4); exit }' "$CATALOG" 2>/dev/null)
    [[ -n "$t" ]] && text="$t"
    # shellcheck disable=SC2059  # the text IS the format: translations carry their own %s
    printf -- "$text" "$@"
}

# yes/no with "yes" as the default
ask() {
    local a
    read -r -p "$1 [$(msg yes.no 'Y/n')]: " a < /dev/tty || return 1
    case "$(printf '%s' "$a" | tr '[:upper:]' '[:lower:]')" in
        ""|y|yes|"$(msg yes.short 'y')"|"$(msg yes.word 'yes')") return 0 ;;
    esac
    return 1
}
step() { echo ""; echo -e "${GREEN}$1${NC}"; }
fail() { echo -e "${RED}$1${NC}"; exit 1; }

# What to install from the commit just fetched ($1: FETCH_HEAD or HEAD): the newest release tag
# (vX.Y.Z) reachable from it — a release is what was announced, not whatever the branch holds past
# it. No release yet, or TELESMA_FOLLOW_BRANCH=1 (developers, forks): that commit itself.
install_ref() {
    local tag=""
    [[ -n "${TELESMA_FOLLOW_BRANCH:-}" ]] || tag=$(git -C "$DEST" describe --tags --abbrev=0 --match 'v*' "$1" 2>/dev/null || true)
    if [[ -n "$tag" ]]; then echo "refs/tags/$tag"; else echo "$1"; fi
}

if ! { true < /dev/tty; } 2>/dev/null; then
    echo "The Telesma installer asks before it installs anything: run it in a Terminal window."
    exit 1
fi
# What Claude Code and Telesma get as stdin: the terminal's own device. On macOS kqueue cannot watch
# one opened by the name /dev/tty, and Claude Code dies on it ("EINVAL … kqueue").
TTY_DEV="/dev/$(ps -o tty= -p $$ 2>/dev/null | tr -d ' ')"
[[ -c "$TTY_DEV" ]] || TTY_DEV=/dev/tty

# Everything runs from main(), called on the last line: bash reads a piped script as it goes, so a
# command reading stdin would swallow the rest of it — the whole function is read before it starts.
main() {
    local OS=other shortcut app
    case "$(uname -s)" in
        Darwin) OS=mac ;;
        Linux) OS=linux ;;
    esac

    echo -e "${GREEN}$(msg inst.title '=== Telesma — installation ===')${NC}"
    echo -e "$(msg inst.intro 'Telesma builds programs with Claude Code. This installs what it needs and asks before each step.')"

    # --- 1. git (and Python): Apple's command line tools ------------------------------------------------
    step "$(msg inst.s.git '1/4  git and Python')"
    if git --version > /dev/null 2>&1; then
        echo -e "  ✓ $(git --version)"
    elif [[ "$OS" == mac ]]; then
        echo -e "  $(msg inst.git.mac 'Apple command line tools are needed (they bring git and Python). A system window asks you to install them.')"
        ask "  $(msg inst.ok 'Go ahead?')" || fail "$(msg inst.stop 'Stopped. Run the installer again when you are ready.')"
        xcode-select --install > /dev/null 2>&1 || true
        echo -e "  $(msg inst.git.wait 'Click «Install» in that window and wait — this window carries on when it is done.')"
        # not forever: a cancelled system window would leave this one waiting with nothing to say
        local waited=0
        until git --version > /dev/null 2>&1; do
            sleep 5
            waited=$((waited + 5))
            (( waited < 1800 )) || fail "  $(msg inst.git.timeout 'The command line tools did not arrive. Run %s yourself, then the installer again.' 'xcode-select --install')"
        done
        echo -e "  ✓ $(git --version)"
    else
        fail "  $(msg inst.git.other 'Install git and python3 with your system package manager (e.g. %s), then run the installer again.' 'sudo apt install git python3')"
    fi
    if [[ "$(python3 -c 'import sys; print(sys.version_info >= (3, 9))' 2>/dev/null)" == "True" ]]; then
        echo -e "  ✓ $(python3 --version 2>&1)"
    else
        fail "  $(msg inst.py 'Python 3.9 or newer is needed: install it from %s and run the installer again.' 'https://www.python.org/downloads/')"
    fi

    # --- 2. Telesma itself --------------------------------------------------------------------------------
    step "$(msg inst.s.telesma '2/4  Telesma')"
    # The source and branch asked for, not the ones of the last run (another TELESMA_REPO/BRANCH).
    # A clone that cannot get there (another history, files git does not know, edits) is moved
    # aside whole — nothing in it is lost — and Telesma is downloaded again.
    # The release tags come with the fetch; the clone moves to the newest one (install_ref).
    if [[ -d "$DEST/.git" ]] && ! { git -C "$DEST" remote set-url origin "$REPO" \
            && git -C "$DEST" fetch -q origin "$BRANCH" 'refs/tags/v*:refs/tags/v*' \
            && { git -C "$DEST" checkout -q "$BRANCH" 2>/dev/null \
                 || { ! git -C "$DEST" show-ref --verify --quiet "refs/heads/$BRANCH" \
                      && git -C "$DEST" checkout -q -b "$BRANCH" FETCH_HEAD; }; } \
            && git -C "$DEST" merge -q --ff-only "$(install_ref FETCH_HEAD)"; } 2>/dev/null; then
        local aside
        aside="$DEST.old-$(date +%Y%m%d-%H%M%S)"
        mv "$DEST" "$aside" || fail "  $(msg inst.pull 'Telesma in %s could not be updated (changed by hand?).' "$DEST")"
        echo -e "  $(msg inst.aside 'The Telesma in %s could not be updated; it is kept as %s.' "$DEST" "$aside")"
    fi
    if [[ -d "$DEST/.git" ]]; then
        echo -e "  ✓ $(msg inst.updated 'Telesma updated: %s' "$DEST")"
    elif [[ -e "$DEST" ]]; then
        fail "  $(msg inst.exists '%s already exists and is not Telesma — move it away and run the installer again.' "$DEST")"
    else
        git clone -q --branch "$BRANCH" "$REPO" "$DEST"
        # a fresh clone sits on the branch tip: put the branch on the release (nothing local yet)
        git -C "$DEST" checkout -q -B "$BRANCH" "$(install_ref HEAD)"
        echo -e "  ✓ $(msg inst.cloned 'Telesma downloaded: %s' "$DEST")"
    fi
    # The `telesma` command for the terminal, next to where Claude Code's installer puts `claude`
    mkdir -p "$HOME/.local/bin"
    ln -sfn "$DEST/telesma.sh" "$HOME/.local/bin/telesma"
    echo -e "  ✓ $(msg inst.command 'The command %s is in %s' telesma "$HOME/.local/bin")"
    case ":$PATH:" in
        *":$HOME/.local/bin:"*) ;;
        *) echo -e "  $(msg inst.command.path 'Add that folder to your PATH (in ~/.zshrc or ~/.bashrc): %s' 'export PATH="$HOME/.local/bin:$PATH"')" ;;
    esac

    # --- 3. Claude Code and the sign-in ---------------------------------------------------------------------
    step "$(msg inst.s.claude '3/4  Claude Code')"
    export PATH="$HOME/.local/bin:$PATH"
    if ! command -v claude > /dev/null 2>&1; then
        echo -e "  $(msg inst.claude 'Claude Code is not installed. It needs a Claude account with a paid plan (Pro or Max).')"
        ask "  $(msg inst.claude.ask 'Install it now (the official installer from claude.ai)?')" \
            || fail "$(msg inst.stop 'Stopped. Run the installer again when you are ready.')"
        curl -fsSL https://claude.ai/install.sh | bash
        command -v claude > /dev/null 2>&1 || fail "  $(msg inst.claude.fail 'Claude Code did not install — see the lines above.')"
    fi
    echo -e "  ✓ Claude Code ($(claude --version 2>/dev/null | head -1))"
    if [[ -z "${ANTHROPIC_API_KEY:-}" ]] && claude auth status 2>/dev/null | grep -q '"loggedIn":[[:space:]]*false'; then
        echo -e "  $(msg inst.login 'Now sign in to your Claude account: a browser window opens.')"
        claude auth login < "$TTY_DEV" || true
        if claude auth status 2>/dev/null | grep -q '"loggedIn":[[:space:]]*false'; then
            echo -e "  ${YELLOW}$(msg inst.login.later 'Not signed in yet — Telesma asks again when it starts.')${NC}"
        fi
    fi

    # --- 4. the projects folder and the shortcut --------------------------------------------------------------
    step "$(msg inst.s.shortcut '4/4  The shortcut')"
    mkdir -p "$PROJECTS"
    if [[ "$OS" == mac ]]; then
        mkdir -p "$DESKTOP"
        shortcut="$DESKTOP/Telesma.command"
        # Made here, not downloaded: no quarantine, a double-click opens it in Terminal.
        cat > "$shortcut" <<EOF
#!/bin/bash
# Telesma — the start menu (made by the Telesma installer)
export PATH="\$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:\$PATH"
exec "$DEST/telesma.sh" --home "$PROJECTS"
EOF
        chmod +x "$shortcut"
        # The same as an app in ~/Applications: Spotlight and Launchpad find it, and it is there
        # when desktop icons are switched off (Desktop & Dock → Show Items: On Desktop). A script
        # as the bundle's executable needs no signature; made here, it carries no quarantine.
        app="$APPS/Telesma.app"
        rm -rf "$app"
        mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources"
        cp "$shortcut" "$app/Contents/Resources/Telesma.command"
        cat > "$app/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key><string>Telesma</string>
    <key>CFBundleIdentifier</key><string>dev.telesma.start</string>
    <key>CFBundleExecutable</key><string>Telesma</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleShortVersionString</key><string>1.0</string>
</dict>
</plist>
PLIST
        cat > "$app/Contents/MacOS/Telesma" <<'LAUNCH'
#!/bin/bash
# Opens the start menu in a Terminal window
exec open -a Terminal "$(dirname "$0")/../Resources/Telesma.command"
LAUNCH
        chmod +x "$app/Contents/MacOS/Telesma"
        echo -e "  ✓ $(msg inst.shortcut 'On the desktop: «Telesma». Your projects will be in %s.' "$PROJECTS")"
        echo -e "  ✓ $(msg inst.app 'Also in Applications: press ⌘ Space and type Telesma.')"
        if [[ "$(defaults read com.apple.WindowManager HideDesktop 2>/dev/null)" == 1 ]]; then
            echo -e "  ${YELLOW}$(msg inst.hidden 'Desktop icons are switched off on this Mac, so the desktop shortcut is not visible — use ⌘ Space → Telesma.')${NC}"
        fi
    else
        echo -e "  $(msg inst.shortcut.cmd 'Start Telesma with: %s' "${CYAN}$DEST/telesma.sh --home \"$PROJECTS\"${NC}")"
    fi

    echo ""
    echo -e "${GREEN}$(msg inst.done 'Done. From now on: double-click «Telesma» on the desktop.')${NC}"
    if ask "$(msg inst.start 'Start Telesma now?')"; then
        rm -f "$CATALOG"
        exec "$DEST/telesma.sh" --home "$PROJECTS" < "$TTY_DEV"
    fi
}

main "$@" < "$TTY_DEV"
