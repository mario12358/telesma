#!/bin/bash
# GitHub integration wizard. Run by wizard.sh (bash setup.sh) with env:
# CONFIG_FILE, PROJECT_DIR, SCRIPT_DIR. Writes only to telesma/config.md.
# Exit code 1 = aborted (no gh / not logged in) — the section stays at "none".

set -e
source "$SCRIPT_DIR/templates/integrations/lib.sh"
HERE="$SCRIPT_DIR/templates/integrations/git/github"

echo ""
echo -e "${GREEN}── Integration: git repository (GitHub) ──${NC}"

# 1. gh — an integration with a specific host = its CLI. Without it there are no PRs.
if ! command -v gh &> /dev/null; then
    echo -e "${RED}GitHub CLI (gh) is missing.${NC} The GitHub integration requires it to be installed:"
    echo -e "  macOS:  ${CYAN}brew install gh${NC}      Linux: ${CYAN}https://github.com/cli/cli/blob/trunk/docs/install_linux.md${NC}"
    echo -e "  then:   ${CYAN}gh auth login${NC}"
    echo -e "Install it and run again: ${CYAN}$0 --integrations $PROJECT_DIR${NC}"
    exit 1
fi
if ! gh auth status &> /dev/null; then
    echo -e "${RED}gh is not logged in.${NC} Run ${CYAN}gh auth login${NC} and come back: $0 --integrations $PROJECT_DIR"
    exit 1
fi
echo -e "  ${GREEN}✓${NC} gh $(gh --version | head -1 | awk '{print $3}') logged in"

# 2. Repository — from the origin remote or from the user
REPO=""
if git -C "$PROJECT_DIR" rev-parse --is-inside-work-tree &> /dev/null; then
    ORIGIN=$(git -C "$PROJECT_DIR" remote get-url origin 2>/dev/null || true)
    if [[ "$ORIGIN" =~ github\.com[:/]([^/]+/[^/.]+)(\.git)?$ ]]; then
        REPO="${BASH_REMATCH[1]}"
    fi
else
    echo -e "${YELLOW}The project directory is not a git repository — the integration needs a repo with an 'origin' remote on GitHub.${NC}"
    echo -e "  ${CYAN}git init && gh repo create <owner>/<name> --private --source=. --remote=origin${NC}"
    exit 1
fi
REPO=$(ask_value "GitHub repository (owner/name)" "$REPO")
if [[ ! "$REPO" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]]; then
    echo -e "${RED}Invalid repository name: $REPO${NC}"; exit 1
fi
if ! gh repo view "$REPO" --json nameWithOwner &> /dev/null; then
    echo -e "${RED}gh cannot see the repository $REPO${NC} (it does not exist or this account has no access)."
    exit 1
fi
if [[ -z "$ORIGIN" ]]; then
    if ask_yes_no "No 'origin' remote — add https://github.com/$REPO.git?" y; then
        git -C "$PROJECT_DIR" remote add origin "https://github.com/$REPO.git"
    fi
fi

# 3. What GitHub allows on this repo: visibility, auto-merge (Free: public only), branch protection
VISIBILITY=$(gh repo view "$REPO" --json visibility --jq .visibility 2>/dev/null | tr 'A-Z' 'a-z')
DEFAULT_BRANCH=$(gh repo view "$REPO" --json defaultBranchRef --jq .defaultBranchRef.name 2>/dev/null || echo main)
DEFAULT_BRANCH=${DEFAULT_BRANCH:-main}   # an empty repository has no default branch yet
AUTO_MERGE=$(gh api "repos/$REPO" --jq .allow_auto_merge 2>/dev/null || echo false)
PROTECTION=false
if gh api "repos/$REPO/branches/$DEFAULT_BRANCH/protection" &> /dev/null; then
    PROTECTION=true
elif [[ "$(gh api "repos/$REPO/rules/branches/$DEFAULT_BRANCH" --jq 'length' 2>/dev/null || echo 0)" != "0" ]]; then
    PROTECTION=true
fi
echo -e "  repo: ${CYAN}$REPO${NC} ($VISIBILITY), default branch: ${CYAN}$DEFAULT_BRANCH${NC}, auto-merge: ${CYAN}$AUTO_MERGE${NC}, branch protection: ${CYAN}$PROTECTION${NC}"

# 4. Merge mode — the default depends on what the repo can do
echo ""
echo -e "Merge mode:"
echo -e "  ${CYAN}auto${NC}   — GitHub auto-merge after green required checks (needs auto-merge + branch protection;"
echo -e "           on Free only in a public repo)"
echo -e "  ${CYAN}agent${NC}  — Telesma waits for the checks and merges itself (works everywhere; GitHub enforces nothing —"
echo -e "           the 'merge only on green checks' rule is enforced by Telesma's permission judge)"
echo -e "  ${CYAN}manual${NC} — the PR waits for a human (counts toward the open PR limit)"
if [[ "$AUTO_MERGE" == "true" && "$PROTECTION" == "true" ]]; then DEFAULT_MERGE=auto; else DEFAULT_MERGE=agent; fi
while :; do
    MERGE=$(ask_value "Merge (auto/agent/manual)" "$DEFAULT_MERGE")
    case "$MERGE" in
        auto)
            if [[ "$AUTO_MERGE" != "true" ]]; then
                echo -e "${YELLOW}Repo $REPO does not have auto-merge enabled${NC} (a private repo on GitHub Free does not have it)."
                if ask_yes_no "Try to enable it (gh api PATCH allow_auto_merge=true)?" n; then
                    if gh api -X PATCH "repos/$REPO" -F allow_auto_merge=true --silent 2>/dev/null; then
                        AUTO_MERGE=true; echo -e "  ${GREEN}✓${NC} auto-merge enabled"
                    else
                        echo -e "${RED}It did not work — the GitHub plan does not include it. Choose 'agent'.${NC}"; continue
                    fi
                else
                    continue
                fi
            fi
            if [[ "$PROTECTION" != "true" ]]; then
                echo -e "${YELLOW}No protection on branch $DEFAULT_BRANCH — auto-merge would merge a PR without waiting for checks.${NC}"
                echo -e "Create a rule in GitHub → Settings → Rules (required status checks), then come back. Or choose 'agent'."
                continue
            fi
            break ;;
        agent|manual) break ;;
        *) echo -e "${RED}auto, agent or manual${NC}" ;;
    esac
done

# 5. Required checks — job names from the workflows as a hint
HINT=""
if ls "$PROJECT_DIR"/.github/workflows/*.yml &> /dev/null; then
    HINT=$(grep -h -E '^\s{2}[A-Za-z0-9_-]+:\s*$' "$PROJECT_DIR"/.github/workflows/*.yml 2>/dev/null \
           | sed -E 's/^\s*//; s/:\s*$//' | grep -v -E '^(on|jobs|env|permissions|concurrency|defaults)$' | sort -u | paste -sd ',' - | sed 's/,/, /g')
fi
CHECKS=$(config_field Integrations "Required checks"); [[ "$CHECKS" == "none" ]] && CHECKS=""
CHECKS=$(ask_value "Required checks (comma-separated names; empty = none)" "${CHECKS:-$HINT}")
if [[ -z "$CHECKS" && "$MERGE" == "agent" ]]; then
    echo -e "${YELLOW}In agent mode the check list cannot be empty — Telesma would have nothing to wait for. Writing 'test' (fix it in the config).${NC}"
    CHECKS="test"
fi
# Quality checks enabled → their result goes to the PR as a commit status (post-push hook).
# As a required check: the judge will not merge a PR whose commits have no local evidence.
CHECKS_STATUS="Telesma: checks (local)"
if [[ "$(config_field Checks Enabled)" =~ ^(yes|true)$ && "$(config_field Checks 'PR status')" != "no" \
      && "$CHECKS" != *"$CHECKS_STATUS"* ]]; then
    if [[ -z "$CHECKS" ]]; then CHECKS="$CHECKS_STATUS"; else CHECKS="$CHECKS, $CHECKS_STATUS"; fi
    echo -e "  ${GREEN}✓${NC} quality checks enabled — \"$CHECKS_STATUS\" is added to the required checks (status from the post-push hook)"
fi
LIMIT=$(ask_value "Open PR limit" "$(config_field Integrations 'Open PR limit')")
[[ "$LIMIT" =~ ^[0-9]+$ ]] || LIMIT=3

# 6. Write to the config + Auto-push + permissions
set_field Integrations Repository github
set_field Integrations Repo "$REPO"
set_field Integrations Merge "$MERGE"
set_field Integrations "Required checks" "${CHECKS:-none}"
set_field Integrations "Open PR limit" "$LIMIT"
set_field Git Auto-push yes
echo -e "  ${GREEN}✓${NC} ## Integrations: Repository github, Repo $REPO, Merge $MERGE, checks: ${CHECKS:-none}, limit $LIMIT"
echo -e "  ${GREEN}✓${NC} ## Git: Auto-push: yes (push to task branches only — the judge and the permissions do not cover $DEFAULT_BRANCH)"
add_permissions "$HERE/permissions.txt"
if [[ "$(config_field 'Auto-approval' Auto-approve)" != "yes" ]]; then
    echo -e "${YELLOW}Note:${NC} the permission judge is off (Auto-approve: no) — every PR merge will ask you."
    echo -e "That is safe, but with 'agent' it will stop the loop on every task. Enable the judge in ## Auto-approval."
fi
show_description "$HERE/DESCRIPTION.txt"
