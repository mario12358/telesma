#!/bin/bash
# Shared functions of the integrations wizard — sourced by wizard.sh and every setup.sh.
# Depends on variables set by telesma.sh: CONFIG_FILE, PROJECT_DIR, SCRIPT_DIR
# and on the colors (RED/GREEN/YELLOW/CYAN/NC). Works without them, just without colors.

: "${RED:=}" "${GREEN:=}" "${YELLOW:=}" "${CYAN:=}" "${NC:=}"

# Value of the field "- **Label**: value" in the "## Section" section of the config (without comments).
config_field() {
    local section="$1" label="$2"
    awk -v sec="## $section" -v lb="- **$label**:" '
        /^## / { w = ($0 == sec) }
        w && index($0, lb) == 1 {
            v = substr($0, length(lb) + 1)
            sub(/^[ \t]+/, "", v); sub(/[ \t]+$/, "", v)
            print v; exit
        }' "$CONFIG_FILE" 2>/dev/null
}

# Sets the value of a field in a section (the comments under the field stay). The field must exist —
# sections come from the template, so it always exists after the config merge.
set_field() {
    local section="$1" label="$2" value="$3"
    python3 - "$CONFIG_FILE" "$section" "$label" "$value" <<'PYSET'
import sys
from pathlib import Path
p, section, label, value = Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]
t = p.read_text(encoding="utf-8").split("\n")
w = False
for i, l in enumerate(t):
    if l.startswith("## "):
        w = l.strip() == f"## {section}"
    elif w and l.startswith(f"- **{label}**:"):
        t[i] = f"- **{label}**: {value}".rstrip()
        break
else:
    sys.exit(1)
p.write_text("\n".join(t), encoding="utf-8")
PYSET
}

# Appends rules from a file (one per line, # = comment) to the "Allowed commands" list
# in ## Permissions — only the ones not there yet. Syncing to
# .claude/settings.local.json happens on its own at startup.
add_permissions() {
    local file="$1" added=0
    [[ -f "$file" ]] || return 0
    while IFS= read -r rule; do
        rule="${rule%%#*}"; rule="${rule#"${rule%%[![:space:]]*}"}"; rule="${rule%"${rule##*[![:space:]]}"}"
        [[ -z "$rule" ]] && continue
        grep -Fq -- "- $rule" "$CONFIG_FILE" && continue
        awk -v r="  - $rule" '{ print } /^- \*\*Allowed commands\*\*:/ && !d { print r; d = 1 }' \
            "$CONFIG_FILE" > "$CONFIG_FILE.tmp" && mv "$CONFIG_FILE.tmp" "$CONFIG_FILE"
        added=$((added + 1))
    done < "$file"
    (( added > 0 )) && echo -e "  ${GREEN}✓${NC} permissions: added $added rules to 'Allowed commands'"
    return 0
}

# Question with a default value: ask_value "Text" default → answer (stdout)
ask_value() {
    local text="$1" default="$2" answer
    if [[ -n "$default" ]]; then
        read -r -p "$text [$default]: " answer < /dev/tty || answer=""
    else
        read -r -p "$text: " answer < /dev/tty || answer=""
    fi
    echo "${answer:-$default}"
}

# Yes/no question: ask_yes_no "Text" y|n → exit code 0 = yes
ask_yes_no() {
    local text="$1" default="${2:-n}" answer
    if [[ "$default" == "y" ]]; then
        read -r -p "$text [Y/n]: " answer < /dev/tty || answer=""
        [[ ! "$answer" =~ ^[nN] ]]
    else
        read -r -p "$text [y/N]: " answer < /dev/tty || answer=""
        [[ "$answer" =~ ^[yY] ]]
    fi
}

# Prints the integration's DESCRIPTION.txt (how this will work) — the same text goes into the docs.
show_description() {
    local file="$1"
    [[ -f "$file" ]] || return 0
    echo ""
    echo -e "${CYAN}── How this will work ─────────────────────────────────────────────${NC}"
    sed 's/^/  /' "$file"
    echo -e "${CYAN}──────────────────────────────────────────────────────────────────${NC}"
    echo ""
}
