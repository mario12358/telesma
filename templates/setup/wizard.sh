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
# with: telesma.sh --setup <project>. Every line a person reads goes through msg (the catalog in
# templates/messages/): the language is the first question, so the rest of the wizard is asked
# in it.

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
    step_header "$(msg wiz.git.header 'Git repository')"
    echo "$(msg wiz.git.1 'Telesma commits after every task and tags every finished phase — it needs a git repository.')"
    if ask_yes_no "$(msg wiz.git.ask "Run 'git init' in %s?" "$PROJECT_DIR")" y; then
        git -C "$PROJECT_DIR" init -q && echo -e "  ${GREEN}✓${NC} git init" && DET_git=yes
    else
        echo -e "  ${YELLOW}$(msg wiz.git.no "Without git Telesma cannot commit; run 'git init' before the first task.")${NC}"
    fi
}

# The ## Tests labels are structure (English in the file); the person sees them translated.
tests_label() {
    case "$1" in
        "Test command")       msg wiz.tests.cmd 'Test command' ;;
        "Full suite command") msg wiz.tests.full 'Full suite command' ;;
        "Linter/formatter")   msg wiz.tests.lint 'Linter/formatter' ;;
        "Typecheck command")  msg wiz.tests.types 'Typecheck command' ;;
        *)                    printf '%s' "$1" ;;
    esac
}

step_tests() {
    step_header "$(msg wiz.tests.header 'Stack and tests')"
    echo "$(msg wiz.tests.1 'Green tests are what Telesma calls done: it runs them after every task and refuses')"
    echo "$(msg wiz.tests.2 'to guess the command. The linter and typechecker feed the lint-types check (standard tier).')"
    local stack="$DET_stack"
    if [[ -n "$DET_parts" ]]; then
        echo -e "$(msg wiz.tests.detected 'Detected: %s' "${GREEN}${DET_parts}${NC}")"
        if ask_yes_no "$(msg wiz.tests.use 'Use the detected stack?')" y; then
            cfg tests "$CONFIG_FILE" --stack auto --project "$PROJECT_DIR" | sed 's/^/  /'
        else
            stack=""
        fi
    fi
    if [[ -z "$DET_parts" || -z "$stack" ]]; then
        echo "$(msg wiz.tests.pick1 'No code yet (the specification only) or a stack I do not recognise. Pick the one the')"
        echo "$(msg wiz.tests.pick2 'project will be built in — the commands are proposals you can edit below:')"
        echo "  python · node · deno · rust · go · java · dotnet · php · ruby · swift · flutter · other"
        echo "  $(msg wiz.tests.later 'later = the clarification picks the stack and writes it into the plan; Telesma then proposes the commands and asks once')"
        stack=$(ask_value "$(msg wiz.tests.stack 'Stack')" "${stack:-later}")
        if [[ "$stack" == "later" ]]; then
            echo "  $(msg wiz.tests.later.ok 'The test commands come from the plan — asked at the first start after it.')"
            return 0
        fi
        cfg tests "$CONFIG_FILE" --stack "$stack" --project "$PROJECT_DIR" | sed 's/^/  /' \
            || { echo -e "  ${YELLOW}$(msg wiz.tests.unknown 'unknown stack — fill in ## Tests by hand')${NC}"; return 0; }
    fi
    local label value
    for label in "Test command" "Full suite command" "Linter/formatter" "Typecheck command"; do
        value=$(config_field Tests "$label")
        value=$(ask_value "  $(tests_label "$label")" "$value")
        cfg set "$CONFIG_FILE" Tests "$label" "$value" > /dev/null
    done
    if [[ "$(config_field Tests 'Smoke suite')" == "none" ]]; then
        echo "$(msg wiz.tests.smoke1 'A smoke suite is a fast subset run after EVERY task (a regression shows up at once, not')"
        echo "$(msg wiz.tests.smoke2 'at the end of the phase). Small project: the same as the test command.')"
        value=$(ask_value "  $(msg wiz.tests.smoke 'Smoke suite (none = skip)')" "none")
        cfg set "$CONFIG_FILE" Tests "Smoke suite" "$value" > /dev/null
    fi
}

step_permissions() {
    step_header "$(msg wiz.perm.header 'Permission prompts')"
    echo "$(msg wiz.perm.1 'Claude Code asks before every command. Telesma runs with acceptEdits (file edits inside')"
    echo "$(msg wiz.perm.2 'the project do not ask; every Bash command does). The permission judge is a hook that')"
    echo "$(msg wiz.perm.3 'answers the prompts you would approve anyway — it only removes prompts, never adds blocks.')"
    echo "  $(msg wiz.perm.rules 'rules    recommended: no model; provable reads pass, everything else still asks you')"
    echo "  $(msg wiz.perm.command 'command  a model over an OpenAI-compatible API decides the gray zone (needs an endpoint)')"
    echo "  $(msg wiz.perm.off 'off      every Bash prompt goes to you')"
    local cur="$STATUS_judge" choice
    [[ "$cur" == "off" ]] && cur="off" || cur="${cur:-rules}"
    [[ "$DET_ollama" == "yes" ]] && echo -e "  $(msg wiz.perm.ollama '(a local model server answers on port 11434 — command is an option)')"
    choice=$(ask_value "$(msg wiz.perm.ask 'Judge')" "${cur/off/off}")
    case "$choice" in
        off|no|none)
            cfg set "$CONFIG_FILE" Auto-approval Auto-approve no | sed 's/^/  /' ;;
        command)
            cfg set "$CONFIG_FILE" Auto-approval Auto-approve yes | sed 's/^/  /'
            cfg set "$CONFIG_FILE" Auto-approval Judge command | sed 's/^/  /'
            local ep model
            ep=$(ask_value "  $(msg wiz.perm.endpoint 'Endpoint (command)')" "$(config_field Auto-approval 'Endpoint (command)')")
            model=$(ask_value "  $(msg wiz.perm.model 'Model (command)')" "$(config_field Auto-approval 'Model (command)')")
            cfg set "$CONFIG_FILE" Auto-approval "Endpoint (command)" "$ep" > /dev/null
            cfg set "$CONFIG_FILE" Auto-approval "Model (command)" "$model" > /dev/null
            echo -e "  $(msg wiz.perm.eval 'Before trusting the model, run the evaluation set: %s' "${CYAN}python3 $SCRIPT_DIR/tools/telesma-judge-eval.py --endpoint $ep --model $model${NC}")"
            echo    "  $(msg wiz.perm.eval2 'Required result: FALSE ALLOWS: 0. The API key goes into API key (command) as env:NAME or file:<path>.')" ;;
        *)
            cfg set "$CONFIG_FILE" Auto-approval Auto-approve yes | sed 's/^/  /'
            cfg set "$CONFIG_FILE" Auto-approval Judge rules | sed 's/^/  /' ;;
    esac
}

step_checks() {
    step_header "$(msg wiz.checks.header 'Quality checks')"
    echo "$(msg wiz.checks.1 'Checks fire on git operations (before a commit, a phase tag, a release tag), not when the')"
    echo "$(msg wiz.checks.2 'model remembers to run them. A blocking finding stops the operation; you can waive a false')"
    echo "$(msg wiz.checks.3 'alarm by fingerprint. Three tiers:')"
    echo "  $(msg wiz.checks.basic 'basic     secrets, deliberate weakenings, weakened tests, repository hygiene — no network, no tools')"
    echo "  $(msg wiz.checks.standard 'standard  + hallucinated or vulnerable dependencies (registry/OSV lookups), SAST, lint/types, dead entry points')"
    echo "  $(msg wiz.checks.security 'security  + attack-surface map and red-team markers (applications with HTTP routes)')"
    echo "  $(msg wiz.checks.none 'none      off')"
    local tools=""
    [[ "$DET_tool_gitleaks" == "no" ]] && tools+=" gitleaks ($(msg wiz.checks.gitleaks 'wider secret detection'))"
    [[ "$DET_tool_semgrep" == "no" ]] && tools+=" semgrep ($(msg wiz.checks.semgrep 'OWASP rule packs for SAST'))"
    [[ -n "$tools" ]] && echo -e "  $(msg wiz.checks.tools 'Optional tools not installed — the checks work without them:%s' "$tools")"
    local cur="$STATUS_checks" tier
    [[ "$cur" == "custom" ]] && echo -e "  $(msg wiz.checks.custom '(the current set of checks is custom — picking a tier replaces it)')"
    tier=$(ask_value "$(msg wiz.checks.ask 'Tier')" "${cur/custom/standard}")
    case "$tier" in none|basic|standard|security) ;; *) tier=basic ;; esac
    cfg checks "$CONFIG_FILE" "$tier" --template "$CONFIG_TEMPLATE" | sed 's/^/  /'
    [[ "$tier" == "security" ]] && echo -e "  $(msg wiz.checks.map 'The attack-surface map %s is written as a skeleton at the next start; review its roles and routes.' "${CYAN}telesma/state/SECURITY_MAP.md${NC}")"
    return 0
}

step_integrations() {
    step_header "$(msg wiz.int.header 'Integrations')"
    echo "$(msg wiz.int.1 'By default Telesma commits to the current branch and never pushes. Optional: GitHub (a branch')"
    echo "$(msg wiz.int.2 'and a pull request per task, merged on green checks) and Specky (requirements tracker).')"
    if ask_yes_no "$(msg wiz.int.ask 'Connect an integration now?')" n; then
        # shellcheck source=../integrations/wizard.sh
        source "$SCRIPT_DIR/templates/integrations/wizard.sh"
        integrations_wizard
    else
        echo -e "  $(msg wiz.int.none 'none — later: %s' "${CYAN}$0 --integrations $PROJECT_DIR${NC}")"
    fi
}

step_visual() {
    step_header "$(msg wiz.vis.header 'Visual artifacts')"
    echo "$(msg wiz.vis.1 'Optional: a screenshot per implemented screen and a video per user flow, taken by the e2e')"
    echo "$(msg wiz.vis.2 'tests (Playwright / Detox). Needs a UI, mockups in telesma/spec/ux_ui/ for screenshots and')"
    echo "$(msg wiz.vis.3 'flows written as ## Step N in telesma/spec/APP_FLOW.md for recordings.')"
    local shots recs
    if ask_yes_no "$(msg wiz.vis.shots 'Screenshots per screen?')" "$([[ "$STATUS_screenshots" == "yes" ]] && echo y || echo n)"; then shots=yes; else shots=no; fi
    if ask_yes_no "$(msg wiz.vis.recs 'Video recordings per flow?')" "$([[ "$STATUS_recordings" == "yes" ]] && echo y || echo n)"; then recs=yes; else recs=no; fi
    cfg set "$CONFIG_FILE" "Visual artifacts" Screenshots "$shots" | sed 's/^/  /'
    cfg set "$CONFIG_FILE" "Visual artifacts" Recordings "$recs" | sed 's/^/  /'
    local spec="$PROJECT_DIR/telesma/spec"
    if [[ "$recs" == "yes" && ! -f "$spec/APP_FLOW.md" ]]; then
        cp "$SCRIPT_DIR/templates/APP_FLOW_TEMPLATE.md" "$spec/APP_FLOW.md"
        echo -e "  ${GREEN}+${NC} $(msg wiz.vis.flow 'telesma/spec/APP_FLOW.md — describe one user flow per ## Step N, then delete the marker in line 1')"
    fi
    if [[ "$shots" == "yes" ]]; then
        mkdir -p "$spec/ux_ui"
        if [[ ! -f "$spec/ux_ui/LINKS.md" ]]; then
            cp "$SCRIPT_DIR/templates/UX_LINKS_TEMPLATE.md" "$spec/ux_ui/LINKS.md"
            echo -e "  ${GREEN}+${NC} $(msg wiz.vis.links 'telesma/spec/ux_ui/LINKS.md — links to mockups kept outside the repo; files go straight into ux_ui/')"
        fi
    fi
}

# step_language [first] — `first`: the first start proposes the system language, not the
# template's `en`; afterwards the current value. The rest of the wizard is asked in the answer.
step_language() {
    step_header "$(msg wiz.lang.header 'Language and experience')"
    echo "$(msg wiz.lang.1 'The language Telesma talks to you in and writes prose into the state files (reports,')"
    echo "$(msg wiz.lang.2 'decisions, test scenarios). Any code works: en, pl, de, … Structure stays English.')"
    local lang exp cur
    cur=$(config_field Project Language)
    [[ "${1:-}" == "first" ]] && cur=$(msg_system_language)
    lang=$(ask_value "$(msg wiz.lang.ask 'Language')" "${cur:-en}")
    cfg set "$CONFIG_FILE" Project Language "$lang" | sed 's/^/  /'
    msg_load_language "$CONFIG_FILE"
    echo "$(msg wiz.exp.1 'Who is Telesma talking to? developer = like a colleague (file names, section numbers);')"
    echo "$(msg wiz.exp.2 'beginner = plain words, one question at a time with a default, effects instead of commands.')"
    echo "$(msg wiz.exp.3 'Same mechanics and permission prompts either way — only the language changes.')"
    exp=$(ask_value "$(msg wiz.exp.ask 'Experience (developer / beginner)')" "$(config_field Project Experience)")
    [[ "$exp" == "beginner" ]] || exp=developer
    cfg set "$CONFIG_FILE" Project Experience "$exp" | sed 's/^/  /'
    return 0
}

beginner() { [[ "$(config_field Project Experience | tr '[:upper:]' '[:lower:]')" == "beginner" ]]; }

# The opt-in for the shared hub is per person and machine (~/.config/telesma/hub), not per repo:
# config.md is committed, so `Send: yes` only says the project MAY be reported. The question
# lists everything that goes out — consent to something unnamed is not consent.
step_telemetry() {
    step_header "$(msg tel.header 'Telemetry')"
    local tool="$SCRIPT_DIR/tools/telesma-telemetry.py" hub answer scope out
    hub=$(python3 "$tool" --shared-hub)
    if beginner; then
        step_telemetry_beginner "$tool" "$hub"
        return 0
    fi
    echo "  $(msg tel.1 'Telesma can send events about the quality of ITS OWN work to the shared Telesma hub')"
    echo "  $(msg tel.2 "(run by the project's author) so the framework can be improved from real projects.")"
    echo "  $(msg tel.3 'Sent: task outcomes and timings, test results, problem/pitfall/decision entries from')"
    echo "  $(msg tel.4 'telesma/state (titles and text, secrets removed), check findings, permission counters,')"
    echo "  $(msg tel.5 "framework version, technology tags, a hash of the project's origin URL and of your")"
    echo "  $(msg tel.6 'git e-mail. Never sent: your spec, code, telesma/changes/, commands, prompts.')"
    echo "  $(msg tel.7 'Privacy and deletion: %s — delete any time: %s' "$hub/privacy" "telesma.sh --telemetry-forget")"
    read -r -p "$(msg tel.ask 'Send telemetry? [y/N/own server]'): " answer < /dev/tty || answer=""
    case "$answer" in
        [yYtT]*)
            echo "  $(msg tel.scope1 'Titles and text of the entries are what framework improvements are made from;')"
            echo "  $(msg tel.scope2 "'metrics' sends only numbers, types and dates.")"
            scope=$(ask_value "  $(msg tel.scope 'Scope (full / metrics)')" "full")
            [[ "$scope" == "metrics" ]] || scope=full
            if python3 "$tool" --register --scope "$scope" | sed 's/^/  /'; [[ ${PIPESTATUS[0]} -eq 0 ]]; then
                cfg set "$CONFIG_FILE" Telemetry Send yes | sed 's/^/  /'
                cfg set "$CONFIG_FILE" Telemetry Endpoint shared | sed 's/^/  /'
            else
                echo -e "  ${YELLOW}$(msg tel.stays_off 'Telemetry stays off.')${NC}"
            fi
            ;;
        o*|O*|w*|W*)
            local ep
            echo "  $(msg tel.own1 'A server you run yourself; the payload is in docs/TELEMETRY.md. The key comes from')"
            echo "  $(msg tel.own2 '`API key` (env:/file:/cmd:) on each machine — never written into config.md.')"
            ep=$(ask_value "  Endpoint" "$(config_field Telemetry Endpoint)")
            cfg set "$CONFIG_FILE" Telemetry Send yes | sed 's/^/  /'
            cfg set "$CONFIG_FILE" Telemetry Endpoint "$ep" | sed 's/^/  /'
            ;;
        *)
            cfg set "$CONFIG_FILE" Telemetry Send no > /dev/null
            if [[ -f "${XDG_CONFIG_HOME:-$HOME/.config}/telesma/hub" ]]; then
                echo "  $(msg tel.still1 'Off for this project. This machine is still opted in for other projects;')"
                echo -e "  $(msg tel.still2 'to withdraw and delete what was sent: %s' "${CYAN}$0 --telemetry-forget${NC}")"
            fi
            ;;
    esac
}

# The same consent in plain words: what goes out, what never does, how to delete it. One yes/no
# (scope full — the text of the notes is what improvements are made from; `metrics` and an own
# server stay in --setup). A hub that does not answer is said in one sentence, not as an
# exception; nothing is switched on then.
step_telemetry_beginner() {
    local tool="$1" hub="$2" answer
    echo "  $(msg tel.b1 'Telesma can send notes on how well IT did its work (not on your program) to the')"
    echo "  $(msg tel.b2 'people who make Telesma, so that it gets better. What goes out: how each step went,')"
    echo "  $(msg tel.b3 'test results and the notes Telesma writes about problems (passwords and keys removed);')"
    echo "  $(msg tel.b4 'your e-mail and the project address only as a hash, never as they are.')"
    echo "  $(msg tel.b5 'Never: your description, your program, what you type.')"
    echo "  $(msg tel.b6 'You can delete it all at any time. Details: %s' "$hub/privacy")"
    read -r -p "$(msg tel.b.ask 'Send these notes? [y/N]'): " answer < /dev/tty || answer=""
    case "$answer" in
        [yYtT]*)
            if python3 "$tool" --register --scope full > /dev/null 2>&1; then
                cfg set "$CONFIG_FILE" Telemetry Send yes > /dev/null
                cfg set "$CONFIG_FILE" Telemetry Endpoint shared > /dev/null
                echo -e "  ${GREEN}✓${NC} $(msg tel.b.on 'Thank you — the notes will be sent.')"
            else
                cfg set "$CONFIG_FILE" Telemetry Send no > /dev/null
                echo -e "  ${YELLOW}$(msg tel.b.fail "Telesma's server is not answering right now, so nothing was switched on — you can try again in the settings.")${NC}"
            fi
            ;;
        *)
            cfg set "$CONFIG_FILE" Telemetry Send no > /dev/null
            echo "  $(msg tel.b.off 'Nothing will be sent.')"
            ;;
    esac
}

finish() {
    echo ""
    echo -e "${GREEN}$(msg cfg.title '=== Configuration (telesma/config.md) ===')${NC}"
    cfg summary "$CONFIG_FILE" --lang "$MSG_LANG"
    echo ""
    echo -e "$(msg cfg.later 'Change any of it later: %s (or edit the file — every key is commented).' "${CYAN}$0 --setup $PROJECT_DIR${NC}")"
}

next_steps() {
    echo ""
    echo -e "${GREEN}$(msg next.title '=== Next steps ===')${NC}"
    if [[ "$(config_field Project Clarified)" == "yes" ]]; then
        echo -e "  $(msg next.loop 'Start the loop:    %s' "${CYAN}$0 $PROJECT_DIR -m 1${NC}")"
    elif [[ "$(config_field Project Adopted | tr '[:upper:]' '[:lower:]')" == "yes" ]]; then
        # --adopt: the code exists; the survey describes it (telesma.sh, section -3)
        echo -e "  $(msg wiz.next.survey1 'Survey the code: %s — Telesma runs the tests once (the baseline), then reads' "${CYAN}$0 $PROJECT_DIR${NC}")"
        echo    "     $(msg wiz.next.survey2 'the code module by module and writes what it found into telesma/spec/AS_BUILT.md. It changes no code.')"
        echo    "     $(msg wiz.next.survey3 'Afterwards you correct that file, add what should happen next to telesma/spec/, and start again.')"
        WIZARD_NEXT=survey
    else
        echo -e "  $(msg next.1 'Put the specification into %s (any format) — if you have not yet.' "${CYAN}telesma/spec/${NC}")"
        echo -e "  $(msg next.tg 'Technical guidelines: %s — left as it is, the defaults from telesma/guidelines/ apply;' "${CYAN}telesma/spec/TECHNICAL_GUIDELINES.md${NC}")"
        echo    "     $(msg next.tg2 'fill in only what is imposed on the project (a stack, hosting, compliance).')"
        echo -e "  $(msg next.go 'Go on: %s — the same command continues after a break.' "${CYAN}$0 $PROJECT_DIR${NC}")"
        echo    "     $(msg next.go2 'Telesma reads the spec, asks about contradictions and gaps, writes the plan and asks whether to build.')"
        WIZARD_NEXT=clarify
    fi
}

# --- entry points ------------------------------------------------------------------------------

# First start: language and experience → profile question → every step with the profile's
# defaults → summary + next steps. Without a terminal: the recommended profile, detected stack,
# no questions.
setup_wizard_first_run() {
    load_kv DET "$(cfg detect "$PROJECT_DIR")"
    if ! has_tty; then
        msg_load_language "$CONFIG_FILE"       # the template's `en`: one language for the whole summary
        cfg profile "$CONFIG_FILE" recommended --template "$CONFIG_TEMPLATE" > /dev/null
        [[ -n "$DET_parts" ]] && cfg tests "$CONFIG_FILE" --stack auto --project "$PROJECT_DIR" > /dev/null
        echo -e "${CYAN}No terminal — applied the 'recommended' profile${NC} (judge: rules, checks: basic)."
        cfg summary "$CONFIG_FILE"
        echo -e "Adjust it with: $0 --setup $PROJECT_DIR"
        # an adopted project (--adopt) has a next step of its own: the survey
        [[ "$(config_field Project Adopted | tr '[:upper:]' '[:lower:]')" == "yes" ]] && next_steps
        return 0
    fi
    # Language and experience come first: every later line is asked in that language, and a
    # beginner gets the short path below instead of the questions a beginner cannot answer.
    # --new set both before the interview — they are not asked twice.
    if ! beginner; then
        echo ""
        echo -e "${GREEN}$(msg wiz.first.title '=== Telesma — first start: configuration ===')${NC}"
        echo "$(msg wiz.first.1 'A few questions, one per module. ENTER accepts the answer in brackets; everything can be')"
        echo "$(msg wiz.first.2 'changed later with --setup or by editing telesma/config.md.')"
        step_language first
    fi
    # Experience: beginner: the recommended profile without the questions a beginner cannot
    # answer — profile, judge, check tier are the defaults; git is started; the test commands
    # came with the technology the interview picked. What is still asked is what only they can
    # answer: the telemetry opt-in. No summary table and no list of commands: the launcher asks
    # whether to go on (WIZARD_NEXT → continue_or_stop in telesma.sh).
    if beginner; then
        cfg profile "$CONFIG_FILE" recommended --template "$CONFIG_TEMPLATE" > /dev/null
        echo ""
        echo -e "${GREEN}$(msg set.title '=== Telesma — settings ===')${NC}"
        echo "$(msg set.usual1 'Telesma picked the usual settings: it asks you before anything risky and checks its')"
        echo "$(msg set.usual2 'own work after every step.')"
        if [[ "$DET_git" != "yes" ]]; then
            git -C "$PROJECT_DIR" init -q && echo -e "  ${GREEN}✓${NC} $(msg set.git 'a history of every change is kept in the project')" && DET_git=yes
        fi
        load_kv STATUS "$(cfg status "$CONFIG_FILE")"
        if [[ "$STATUS_tests" == "set" ]]; then
            echo -e "  ${GREEN}✓${NC} $(msg set.tests "the program's own checks will run with: %s" "$STATUS_test_command")"
        else
            step_tests
        fi
        step_telemetry
        echo ""
        echo "$(msg set.later 'All settings can be changed later with: %s' "$0 --setup $PROJECT_DIR")"
        WIZARD_NEXT=clarify
        return 0
    fi
    echo ""
    echo "  $(msg wiz.profile.min 'minimal      the loop only: every permission prompt comes to you, no quality checks')"
    echo "  $(msg wiz.profile.rec 'recommended  + permission judge (rules: reads pass, the rest asks) + basic quality checks')"
    echo "  $(msg wiz.profile.full 'full         + standard quality checks, and the questions about integrations and visual artifacts')"
    local profile
    profile=$(ask_value "$(msg wiz.profile.ask 'Profile')" "recommended")
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
    elif [[ "$DET_ux_files" != "0" || "$DET_app_flow" == "filled" ]]; then
        step_visual
    fi
    # Every profile: an opt-in that only `full` users ever see is not a question asked.
    step_telemetry
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
        echo -e "${GREEN}$(msg wiz.menu.title '=== Telesma — setup (%s) ===' "$PROJECT_DIR")${NC}"
        echo -e "  ${CYAN}1)${NC} $(msg wiz.menu.tests 'Stack and tests        %s' "${STATUS_test_command}")"
        echo -e "  ${CYAN}2)${NC} $(msg wiz.menu.perm 'Permission prompts     judge: %s' "${STATUS_judge}")"
        echo -e "  ${CYAN}3)${NC} $(msg wiz.menu.checks 'Quality checks         %s' "${STATUS_checks}")"
        echo -e "  ${CYAN}4)${NC} $(msg wiz.menu.int 'Integrations           repository: %s, tracker: %s' "${STATUS_repository}" "${STATUS_tracker}")"
        echo -e "  ${CYAN}5)${NC} $(msg wiz.menu.vis 'Visual artifacts       screenshots: %s, recordings: %s' "${STATUS_screenshots}" "${STATUS_recordings}")"
        echo -e "  ${CYAN}6)${NC} $(msg wiz.menu.lang 'Language, experience   %s, %s' "${STATUS_language}" "${STATUS_experience}")"
        echo -e "  ${CYAN}7)${NC} $(msg wiz.menu.tel 'Telemetry              %s' "${STATUS_telemetry}")"
        echo -e "  ${CYAN}q)${NC} $(msg wiz.menu.done 'Done')"
        local choice
        read -r -p "$(msg wiz.menu.ask 'Change [q]'): " choice < /dev/tty || choice=q
        case "$choice" in
            1) step_tests ;;
            2) step_permissions ;;
            3) step_checks ;;
            4) step_integrations; load_integrations 2>/dev/null || true ;;
            5) step_visual ;;
            6) step_language ;;
            7) step_telemetry ;;
            ""|q|Q) break ;;
            *) echo -e "${YELLOW}$(msg wiz.menu.bad '1–7 or q')${NC}" ;;
        esac
    done
    finish
}
