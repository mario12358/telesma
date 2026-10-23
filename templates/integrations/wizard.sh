#!/bin/bash
# Integrations wizard — choice menu + running setup.sh of the chosen integrations.
# Sourced by telesma.sh (the first time config.md is created, or with the
# --integrations flag). Needs a terminal (/dev/tty) — without one it stays silent so CI does not hang.
# Writes ONLY to telesma/config.md (sections ## Integrations, ## Git, ## Permissions)
# and — with both integrations at once — to .github/workflows/ (CI template for Specky).

INTEGRATIONS_DIR="$SCRIPT_DIR/templates/integrations"
# shellcheck source=lib.sh
source "$INTEGRATIONS_DIR/lib.sh"

integrations_wizard() {
    # -r is not enough: /dev/tty exists without a controlling terminal, and opening it fails.
    if ! { true < /dev/tty; } 2>/dev/null; then
        echo -e "${YELLOW}Integrations wizard skipped — no terminal. Run: $0 --integrations $PROJECT_DIR${NC}"
        return 0
    fi
    local repo_now tracker_now
    repo_now=$(config_field Integrations Repository); repo_now=${repo_now:-none}
    tracker_now=$(config_field Integrations Tracker); tracker_now=${tracker_now:-none}

    echo ""
    echo -e "${GREEN}=== Telesma — integrations ===${NC}"
    echo -e "By default Telesma works without integrations: it commits locally, never pushes, knows no tracker."
    echo -e "An integration changes the definition of \"task done\" — below you choose what the project connects to."
    echo -e "Current state: repository = ${CYAN}${repo_now}${NC}, tracker = ${CYAN}${tracker_now}${NC}"
    echo ""
    echo -e "  ${CYAN}1)${NC} Git repository (GitHub): a branch per task → PR → checks → merge; task closed after merge"
    echo -e "  ${CYAN}2)${NC} Requirement tracker (Specky): requirement anchors, trailer in commits, criterion tests, sync → telesma/changes/"
    echo -e "  ${CYAN}3)${NC} Both (full contract: the PR gets the \"Specky contract check\" status)"
    echo -e "  ${CYAN}N)${NC} None — standard behaviour (you can come back: $0 --integrations $PROJECT_DIR)"
    echo ""
    local choice
    read -r -p "Choice [N]: " choice < /dev/tty || choice=""
    # Each setup.sh is a separate bash process that needs these three (see its header comment).
    export SCRIPT_DIR PROJECT_DIR CONFIG_FILE
    case "$choice" in
        1) bash "$INTEGRATIONS_DIR/git/github/setup.sh" || return 0 ;;
        2) bash "$INTEGRATIONS_DIR/tracker/specky/setup.sh" || return 0 ;;
        3) bash "$INTEGRATIONS_DIR/git/github/setup.sh" || return 0
           bash "$INTEGRATIONS_DIR/tracker/specky/setup.sh" || return 0 ;;
        *) echo -e "No integrations. The ${CYAN}## Integrations${NC} section in telesma/config.md stays with 'none' values."
           return 0 ;;
    esac

    # Both at once → CI template that gives Specky a JUnit report (contract in the file's header)
    if [[ "$(config_field Integrations Repository)" == "github" && "$(config_field Integrations Tracker)" == "specky" ]]; then
        local wf_dir="$PROJECT_DIR/.github/workflows" wf="$PROJECT_DIR/.github/workflows/specky-ci.yml"
        if [[ ! -f "$wf" ]]; then
            mkdir -p "$wf_dir"
            cp "$INTEGRATIONS_DIR/tracker/specky/specky-ci.yml" "$wf"
            echo -e "  ${GREEN}✓${NC} copied the CI template: .github/workflows/specky-ci.yml (Telesma adapts the steps to the stack in task 1.1)"
        fi
        local checks
        checks=$(config_field Integrations "Required checks")
        if [[ "$checks" != *"Specky contract check"* ]]; then
            if [[ -z "$checks" || "$checks" == "none" ]]; then checks="Specky contract check, test"
            else checks="Specky contract check, $checks"; fi
            set_field Integrations "Required checks" "$checks"
            echo -e "  ${GREEN}✓${NC} Required checks: $checks"
        fi
    fi
    echo ""
    echo -e "${GREEN}Integrations saved in telesma/config.md (section ## Integrations).${NC} Change them by hand or with $0 --integrations."
}
