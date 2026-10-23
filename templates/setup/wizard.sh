#!/bin/bash
# Configuration wizard — the interactive half (the edits live in configure.py).
# Sourced by telesma.sh: on the first start of a project (right after config.md is created) and
# with the --setup flag. Needs a terminal (/dev/tty); without one it applies the "recommended"
# profile silently, so CI and scripts never hang on a question.
# Writes ONLY to telesma/config.md (and, through the integrations wizard, to the files that one
# writes); creates telesma/spec/APP_FLOW.md and telesma/spec/ux_ui/LINKS.md only when the user
# turns visual artifacts on.
#
# One step = one module = one question, with the recommended answer in brackets (ENTER accepts
# it), one sentence of what it does and one of what it needs. Every step can be revisited later
# with: telesma.sh --setup <project>.

SETUP_DIR="$SCRIPT_DIR/templates/setup"
CONFIGURE="$SETUP_DIR/configure.py"
CONFIG_TEMPLATE="$SCRIPT_DIR/templates/config.md"
# shellcheck source=../integrations/lib.sh
source "$SCRIPT_DIR/templates/integrations/lib.sh"

cfg() { python3 "$CONFIGURE" "$@"; }

# KEY=value lines → shell variables with a prefix: load_kv DET "$(cfg detect …)" → $DET_stack …
load_kv() {
    local prefix="$1" line
    while IFS= read -r line; do
        [[ "$line" == *=* ]] || continue
        printf -v "${prefix}_${line%%=*}" '%s' "${line#*=}"
    done <<< "$2"
}

has_tty() { { true < /dev/tty; } 2>/dev/null; }

step_header() {
    echo ""
    echo -e "${CYAN}── $1 ─────────────────────────────────────────────${NC}"
}

# --- steps -------------------------------------------------------------------------------------

step_git() {
    [[ "$DET_git" == "yes" ]] && return 0
    step_header "Git repository"
    echo "Telesma commits after every task and tags every finished phase — it needs a git repository."
    if ask_yes_no "Run 'git init' in $PROJECT_DIR?" y; then
        git -C "$PROJECT_DIR" init -q && echo -e "  ${GREEN}✓${NC} git init" && DET_git=yes
    else
        echo -e "  ${YELLOW}Without git Telesma cannot commit; run 'git init' before the first task.${NC}"
    fi
}

step_tests() {
    step_header "Stack and tests"
    echo "Green tests are Telesma's definition of \"done\": it runs them after every task and refuses"
    echo "to guess the command. The linter and typechecker feed the lint-types check (standard tier)."
    local stack="$DET_stack"
    if [[ -n "$DET_parts" ]]; then
        echo -e "Detected: ${GREEN}${DET_parts}${NC}"
        if ask_yes_no "Use the detected stack?" y; then
            cfg tests "$CONFIG_FILE" --stack auto --project "$PROJECT_DIR" | sed 's/^/  /'
        else
            stack=""
        fi
    fi
    if [[ -z "$DET_parts" || -z "$stack" ]]; then
        echo "No code yet (the specification only) or a stack I do not recognise. Pick the one the"
        echo "project will be built in — the commands are proposals you can edit below:"
        echo "  python · node · deno · rust · go · java · dotnet · php · ruby · swift · flutter · other"
        stack=$(ask_value "Stack" "${stack:-python}")
        cfg tests "$CONFIG_FILE" --stack "$stack" --project "$PROJECT_DIR" | sed 's/^/  /' \
            || { echo -e "  ${YELLOW}unknown stack — fill in ## Tests by hand${NC}"; return 0; }
    fi
    local label value
    for label in "Test command" "Full suite command" "Linter/formatter" "Typecheck command"; do
        value=$(config_field Tests "$label")
        value=$(ask_value "  $label" "$value")
        cfg set "$CONFIG_FILE" Tests "$label" "$value" > /dev/null
    done
    if [[ "$(config_field Tests 'Smoke suite')" == "none" ]]; then
        echo "A smoke suite is a fast subset run after EVERY task (a regression shows up at once, not"
        echo "at the end of the phase). Small project: the same as the test command."
        value=$(ask_value "  Smoke suite (none = skip)" "none")
        cfg set "$CONFIG_FILE" Tests "Smoke suite" "$value" > /dev/null
    fi
}

step_permissions() {
    step_header "Permission prompts"
    echo "Claude Code asks before every command. Telesma runs with 'acceptEdits' (file edits inside"
    echo "the project do not ask; every Bash command does). The permission judge is a hook that"
    echo "answers the prompts you would approve anyway — it only removes prompts, never adds blocks."
    echo "  rules    recommended: no model; provable reads pass, everything else still asks you"
    echo "  command  a model over an OpenAI-compatible API decides the gray zone (needs an endpoint)"
    echo "  off      every Bash prompt goes to you"
    local cur="$STATUS_judge" choice
    [[ "$cur" == "off" ]] && cur="off" || cur="${cur:-rules}"
    [[ "$DET_ollama" == "yes" ]] && echo -e "  (a local model server answers on port 11434 — 'command' is an option)"
    choice=$(ask_value "Judge" "${cur/off/off}")
    case "$choice" in
        off|no|none)
            cfg set "$CONFIG_FILE" Auto-approval Auto-approve no | sed 's/^/  /' ;;
        command)
            cfg set "$CONFIG_FILE" Auto-approval Auto-approve yes | sed 's/^/  /'
            cfg set "$CONFIG_FILE" Auto-approval Judge command | sed 's/^/  /'
            local ep model
            ep=$(ask_value "  Endpoint (command)" "$(config_field Auto-approval 'Endpoint (command)')")
            model=$(ask_value "  Model (command)" "$(config_field Auto-approval 'Model (command)')")
            cfg set "$CONFIG_FILE" Auto-approval "Endpoint (command)" "$ep" > /dev/null
            cfg set "$CONFIG_FILE" Auto-approval "Model (command)" "$model" > /dev/null
            echo -e "  Before trusting the model, run the evaluation set: ${CYAN}python3 $SCRIPT_DIR/tools/telesma-judge-eval.py --endpoint $ep --model $model${NC}"
            echo    "  Required result: FALSE ALLOWS: 0. The API key goes into 'API key (command)' as env:NAME or file:<path>." ;;
        *)
            cfg set "$CONFIG_FILE" Auto-approval Auto-approve yes | sed 's/^/  /'
            cfg set "$CONFIG_FILE" Auto-approval Judge rules | sed 's/^/  /' ;;
    esac
}

step_checks() {
    step_header "Quality checks"
    echo "Checks fire on git operations (before a commit, a phase tag, a release tag), not when the"
    echo "model remembers to run them. A blocking finding stops the operation; you can waive a false"
    echo "alarm by fingerprint. Three tiers:"
    echo "  basic     secrets, deliberate weakenings, weakened tests, repository hygiene — no network, no tools"
    echo "  standard  + hallucinated or vulnerable dependencies (registry/OSV lookups), SAST, lint/types, dead entry points"
    echo "  security  + attack-surface map and red-team markers (applications with HTTP routes)"
    echo "  none      off"
    local tools=""
    [[ "$DET_tool_gitleaks" == "no" ]] && tools+=" gitleaks (wider secret detection)"
    [[ "$DET_tool_semgrep" == "no" ]] && tools+=" semgrep (OWASP rule packs for SAST)"
    [[ -n "$tools" ]] && echo -e "  Optional tools not installed — the checks work without them:${tools}"
    local cur="$STATUS_checks" tier
    [[ "$cur" == "custom" ]] && echo -e "  (the current set of checks is custom — picking a tier replaces it)"
    tier=$(ask_value "Tier" "${cur/custom/standard}")
    case "$tier" in none|basic|standard|security) ;; *) tier=basic ;; esac
    cfg checks "$CONFIG_FILE" "$tier" --template "$CONFIG_TEMPLATE" | sed 's/^/  /'
    [[ "$tier" == "security" ]] && echo -e "  The attack-surface map ${CYAN}telesma/state/SECURITY_MAP.md${NC} is written as a skeleton at the next start; review its roles and routes."
    return 0
}

step_integrations() {
    step_header "Integrations"
    echo "By default Telesma commits to the current branch and never pushes. Optional: GitHub (a branch"
    echo "and a pull request per task, merged on green checks) and Specky (requirements tracker)."
    if ask_yes_no "Connect an integration now?" n; then
        # shellcheck source=../integrations/wizard.sh
        source "$SCRIPT_DIR/templates/integrations/wizard.sh"
        integrations_wizard
    else
        echo -e "  none — later: ${CYAN}$0 --integrations $PROJECT_DIR${NC}"
    fi
}

step_visual() {
    step_header "Visual artifacts"
    echo "Optional: a screenshot per implemented screen and a video per user flow, taken by the e2e"
    echo "tests (Playwright / Detox). Needs a UI, mockups in telesma/spec/ux_ui/ for screenshots and"
    echo "flows written as '## Step N' in telesma/spec/APP_FLOW.md for recordings."
    local shots recs
    if ask_yes_no "Screenshots per screen?" "$([[ "$STATUS_screenshots" == "yes" ]] && echo y || echo n)"; then shots=yes; else shots=no; fi
    if ask_yes_no "Video recordings per flow?" "$([[ "$STATUS_recordings" == "yes" ]] && echo y || echo n)"; then recs=yes; else recs=no; fi
    cfg set "$CONFIG_FILE" "Visual artifacts" Screenshots "$shots" | sed 's/^/  /'
    cfg set "$CONFIG_FILE" "Visual artifacts" Recordings "$recs" | sed 's/^/  /'
    local spec="$PROJECT_DIR/telesma/spec"
    if [[ "$recs" == "yes" && ! -f "$spec/APP_FLOW.md" ]]; then
        cp "$SCRIPT_DIR/templates/APP_FLOW_TEMPLATE.md" "$spec/APP_FLOW.md"
        echo -e "  ${GREEN}+${NC} telesma/spec/APP_FLOW.md — describe one user flow per '## Step N', then delete the marker in line 1"
    fi
    if [[ "$shots" == "yes" ]]; then
        mkdir -p "$spec/ux_ui"
        if [[ ! -f "$spec/ux_ui/LINKS.md" ]]; then
            cp "$SCRIPT_DIR/templates/UX_LINKS_TEMPLATE.md" "$spec/ux_ui/LINKS.md"
            echo -e "  ${GREEN}+${NC} telesma/spec/ux_ui/LINKS.md — links to mockups kept outside the repo; files go straight into ux_ui/"
        fi
    fi
}

step_language() {
    step_header "Language"
    echo "The language Telesma talks to you in and writes prose into the state files (reports,"
    echo "decisions, test scenarios). Any code works: en, pl, de, … Structure stays English."
    local lang
    lang=$(ask_value "Language" "$(config_field Project Language)")
    cfg set "$CONFIG_FILE" Project Language "$lang" | sed 's/^/  /'
    return 0
}

step_telemetry() {
    step_header "Telemetry"
    echo "Optional quality events about Telesma's own work, sent to a server YOU host. Off = nothing"
    echo "leaves this machine. Turn it on only if you run such a server."
    if ask_yes_no "Send telemetry?" n; then
        local ep
        ep=$(ask_value "  Endpoint" "$(config_field Telemetry Endpoint)")
        cfg set "$CONFIG_FILE" Telemetry Send yes | sed 's/^/  /'
        cfg set "$CONFIG_FILE" Telemetry Endpoint "$ep" | sed 's/^/  /'
    else
        cfg set "$CONFIG_FILE" Telemetry Send no > /dev/null
    fi
}

finish() {
    echo ""
    echo -e "${GREEN}=== Configuration (telesma/config.md) ===${NC}"
    cfg summary "$CONFIG_FILE"
    echo ""
    echo -e "Change any of it later: ${CYAN}$0 --setup $PROJECT_DIR${NC} (or edit the file — every key is commented)."
}

next_steps() {
    echo ""
    echo -e "${GREEN}=== Next steps ===${NC}"
    if [[ "$(config_field Project Clarified)" == "yes" ]]; then
        echo -e "  Start the loop:    ${CYAN}$0 $PROJECT_DIR -m 1${NC}"
    else
        echo -e "  1. Put the specification into ${CYAN}telesma/spec/${NC} (any format) — if you have not yet."
        echo -e "  2. Clarify and plan: ${CYAN}$0 $PROJECT_DIR -i${NC}"
        echo    "     Telesma reads the spec, asks about contradictions and gaps, then writes the plan."
        echo -e "  3. Build:            ${CYAN}$0 $PROJECT_DIR -m 1${NC}"
    fi
}

# --- entry points ------------------------------------------------------------------------------

# First start: profile question → every step with the profile's defaults → summary + next steps.
# Without a terminal: the recommended profile, detected stack, no questions.
setup_wizard_first_run() {
    load_kv DET "$(cfg detect "$PROJECT_DIR")"
    if ! has_tty; then
        cfg profile "$CONFIG_FILE" recommended --template "$CONFIG_TEMPLATE" > /dev/null
        [[ -n "$DET_parts" ]] && cfg tests "$CONFIG_FILE" --stack auto --project "$PROJECT_DIR" > /dev/null
        echo -e "${CYAN}No terminal — applied the 'recommended' profile${NC} (judge: rules, checks: basic)."
        cfg summary "$CONFIG_FILE"
        echo -e "Adjust it with: $0 --setup $PROJECT_DIR"
        return 0
    fi
    echo ""
    echo -e "${GREEN}=== Telesma — first start: configuration ===${NC}"
    echo "A few questions, one per module. ENTER accepts the answer in brackets; everything can be"
    echo "changed later with --setup or by editing telesma/config.md."
    echo ""
    echo "  minimal      the loop only: every permission prompt comes to you, no quality checks"
    echo "  recommended  + permission judge (rules: reads pass, the rest asks) + basic quality checks"
    echo "  full         + standard quality checks, and the questions about integrations and visual artifacts"
    local profile
    profile=$(ask_value "Profile" "recommended")
    case "$profile" in minimal|recommended|full) ;; *) profile=recommended ;; esac
    cfg profile "$CONFIG_FILE" "$profile" --template "$CONFIG_TEMPLATE" > /dev/null
    load_kv STATUS "$(cfg status "$CONFIG_FILE")"

    step_git
    step_tests
    step_permissions
    step_checks
    if [[ "$profile" == "full" ]]; then
        step_integrations
        step_visual
        step_telemetry
    elif [[ "$DET_ux_files" != "0" || "$DET_app_flow" == "filled" ]]; then
        step_visual
    fi
    step_language
    finish
    next_steps
}

# --setup on an existing project: a menu with the state of every module; pick one to change.
setup_wizard_menu() {
    if ! has_tty; then
        echo -e "${YELLOW}--setup needs a terminal.${NC}"
        cfg summary "$CONFIG_FILE"
        return 0
    fi
    load_kv DET "$(cfg detect "$PROJECT_DIR")"
    while true; do
        load_kv STATUS "$(cfg status "$CONFIG_FILE")"
        echo ""
        echo -e "${GREEN}=== Telesma — setup ($PROJECT_DIR) ===${NC}"
        echo -e "  ${CYAN}1)${NC} Stack and tests        ${STATUS_test_command}"
        echo -e "  ${CYAN}2)${NC} Permission prompts     judge: ${STATUS_judge}"
        echo -e "  ${CYAN}3)${NC} Quality checks         ${STATUS_checks}"
        echo -e "  ${CYAN}4)${NC} Integrations           repository: ${STATUS_repository}, tracker: ${STATUS_tracker}"
        echo -e "  ${CYAN}5)${NC} Visual artifacts       screenshots: ${STATUS_screenshots}, recordings: ${STATUS_recordings}"
        echo -e "  ${CYAN}6)${NC} Language               ${STATUS_language}"
        echo -e "  ${CYAN}7)${NC} Telemetry              ${STATUS_telemetry}"
        echo -e "  ${CYAN}q)${NC} Done"
        local choice
        read -r -p "Change [q]: " choice < /dev/tty || choice=q
        case "$choice" in
            1) step_tests ;;
            2) step_permissions ;;
            3) step_checks ;;
            4) step_integrations; load_integrations 2>/dev/null || true ;;
            5) step_visual ;;
            6) step_language ;;
            7) step_telemetry ;;
            ""|q|Q) break ;;
            *) echo -e "${YELLOW}1–7 or q${NC}" ;;
        esac
    done
    finish
}
