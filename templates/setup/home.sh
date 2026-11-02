#!/bin/bash
# The start menu behind the desktop shortcut the installer creates (telesma.sh --home [folder]):
# a person who never typed a path picks "a new idea" or one of their projects, and the launcher
# goes on with it — --new for an idea or an interview that was interrupted, a plain start for the
# rest (which for a beginner is the "what now?" menu). Projects live in one folder, by default
# ~/Telesma — not Documents, which iCloud or OneDrive often sync: a synced project loses file
# contents to the cloud and breaks. Sourced by telesma.sh after preflight; plain Bash 3.2.

HOME_DEFAULT_ROOT="$HOME/Telesma"

# The interview of a beginner project has not finished (the same test as interview_complete)
home_interview_open() {
    local spec="$1/telesma/spec"
    grep -qi '^- \*\*Experience\*\*:[[:space:]]*beginner' "$1/telesma/config.md" 2>/dev/null || return 1
    [[ -f "$spec/IDEA.md" && -f "$spec/REQUIREMENTS.md" ]] || return 0
    head -1 "$spec/TECHNICAL_GUIDELINES.md" 2>/dev/null | grep -qF "TELESMA_SPEC_TEMPLATE"
}

# One line about where a project stands
home_status() {
    local left
    if home_interview_open "$1"; then
        msg home.st.idea 'the idea is not fully described yet'
    elif ! grep -qi '^- \*\*Clarified\*\*:.*yes' "$1/telesma/config.md" 2>/dev/null; then
        msg home.st.plan 'a few questions and the plan come next'
    else
        left=$(grep -c '^- \[ \]' "$1/telesma/state/PLAN.md" 2>/dev/null) || left=0
        if [[ "$left" -gt 0 ]]; then
            msg home.st.left 'steps still to do: %s' "$left"
        else
            msg home.st.done 'every step is done'
        fi
    fi
}

# The program's name from the interview (the first heading of IDEA.md), else the folder's
home_name() {
    local n
    n=$(sed -n 's/^# //p' "$1/telesma/spec/IDEA.md" 2>/dev/null | head -1 | tr -d '\r')
    printf '%s' "${n:-$(basename "$1")}"
}

# A folder name from what the person typed: ASCII letters, digits and dashes
home_slug() {
    python3 -c '
import re, sys, unicodedata
s = sys.argv[1].translate(str.maketrans("łŁøØßæÆ", "lLoOsaA"))
s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
while len(s) > 40 and "-" in s:          # whole words only
    s = s.rsplit("-", 1)[0]
print(s[:40])' "$1"
}

home_menu() {
    local root="${1:-$HOME_DEFAULT_ROOT}" p n i choice name slug dir
    local projects=()
    if ! { true < /dev/tty; } 2>/dev/null; then
        echo -e "${RED}--home needs a terminal: it is a menu.${NC}"
        exit 1
    fi
    mkdir -p "$root"
    # Most recently worked on first (the telesma/ folder changes with every session)
    while IFS= read -r p; do
        [[ -f "$p/config.md" ]] && projects+=("${p%/telesma}")
    done < <(ls -1td "$root"/*/telesma 2>/dev/null)

    echo -e "${GREEN}$(msg home.title '=== Telesma ===')${NC}"
    echo -e "$(msg home.where 'Your projects are in: %s' "$root")"
    echo ""
    echo -e "  ${CYAN}1)${NC} $(msg home.new 'A new idea — tell Telesma what program you need')"
    i=2
    for p in ${projects[@]+"${projects[@]}"}; do
        echo -e "  ${CYAN}$i)${NC} $(home_name "$p") — $(home_status "$p")"
        i=$((i + 1))
    done
    echo -e "  ${CYAN}q)${NC} $(msg home.quit 'Close')"
    echo ""
    local def=1
    [[ ${#projects[@]} -gt 0 ]] && def=2
    read -r -p "$(msg home.prompt 'Choice') [$def]: " choice < /dev/tty || exit 0
    choice=${choice:-$def}
    case "$choice" in
        q|Q) exit 0 ;;
        1)
            echo ""
            read -r -p "$(msg home.name 'A working name for the idea (a few words, it names the folder)'): " name < /dev/tty || exit 0
            slug=$(home_slug "$name")
            [[ -n "$slug" ]] || slug="idea-$(date +%Y%m%d)"
            dir="$root/$slug"
            i=2
            while [[ -e "$dir" ]]; do dir="$root/$slug-$i"; i=$((i + 1)); done
            TELESMA_FROM_HOME=1 exec bash "$SCRIPT_DIR/telesma.sh" --new "$dir"
            ;;
        *)
            if [[ "$choice" =~ ^[0-9]+$ ]] && (( choice >= 2 && choice < 2 + ${#projects[@]} )); then
                dir="${projects[$((choice - 2))]}"
                if home_interview_open "$dir"; then
                    TELESMA_FROM_HOME=1 exec bash "$SCRIPT_DIR/telesma.sh" --new "$dir"
                fi
                TELESMA_FROM_HOME=1 exec bash "$SCRIPT_DIR/telesma.sh" "$dir"
            fi
            echo -e "${RED}$(msg home.bad 'There is no such choice.')${NC}"
            exit 1
            ;;
    esac
}
