#!/bin/bash
# Specky integration wizard (requirement tracker over MCP). Run by wizard.sh
# with env: CONFIG_FILE, PROJECT_DIR, SCRIPT_DIR. Writes only to telesma/config.md.

set -e
source "$SCRIPT_DIR/templates/integrations/lib.sh"
HERE="$SCRIPT_DIR/templates/integrations/tracker/specky"

echo ""
echo -e "${GREEN}── Integration: requirement tracker (Specky) ──${NC}"

# 1. MCP servers. The recommended way is the Specky plugin (two servers: core + record, one token);
#    the claude.ai connector (mcp__claude_ai_Specky__*) is a client that cannot decide and is not
#    always visible from `claude mcp list` — so a missing entry is a warning, not a blocker.
if command -v claude &> /dev/null && claude plugin list 2>/dev/null | grep -qi 'specky'; then
    echo -e "  ${GREEN}✓${NC} Specky plugin installed (servers: specky, specky-record)"
elif command -v claude &> /dev/null && claude mcp list 2>/dev/null | grep -qi specky; then
    echo -e "  ${GREEN}✓${NC} Specky MCP server visible in 'claude mcp list'"
else
    echo -e "  ${YELLOW}•${NC} No Specky plugin or MCP server found. Recommended (in a Claude Code session):"
    echo -e "      ${CYAN}/plugin marketplace add SpeckyContractCheck/specky-plugin${NC}"
    echo -e "      ${CYAN}/plugin install specky@specky${NC}"
    echo -e "    Without the plugin (core server only): ${CYAN}claude mcp add --transport http specky $(config_field Integrations 'Tracker MCP')${NC}"
    echo -e "    If you use the claude.ai connector, this message is normal — it is not listed here."
fi

# 2. Project in Specky
echo -e "You will find the project_id in the project's URL in Specky (a ULID, 26 characters), or ask Claude: list_projects."
PROJECT=$(ask_value "Specky project_id" "$(config_field Integrations 'Tracker project')")
if [[ ! "$PROJECT" =~ ^[0-9A-HJKMNP-TV-Z]{26}$ ]]; then
    echo -e "${YELLOW}This does not look like a ULID ($PROJECT) — saving it, but the startup validator will report it if Specky does not know it.${NC}"
fi
MCP=$(ask_value "Specky MCP address" "$(config_field Integrations 'Tracker MCP')")

# 3. Write + permissions (core, record and the connector — see permissions.txt)
set_field Integrations Tracker specky
set_field Integrations "Tracker project" "$PROJECT"
set_field Integrations "Tracker MCP" "$MCP"
echo -e "  ${GREEN}✓${NC} ## Integrations: Tracker specky, project $PROJECT"
add_permissions "$HERE/permissions.txt"

# 4. Cursor file — committed, so a new session does not start from zero
SPECKY_FILE="$PROJECT_DIR/telesma/state/SPECKY.md"
if [[ ! -f "$SPECKY_FILE" ]]; then
    cat > "$SPECKY_FILE" <<EOF
# telesma/state/SPECKY.md — sync state with the Specky tracker

Read and updated by Telesma (section 18 of the instructions). Committed.

- **Project**: $PROJECT
- **Cursor (since_seq)**: 0
  <!-- The first session passes since_seq=0 to what_changed explicitly; Telesma moves the cursor -->
  <!-- to next_seq only after the change files are written (18.1).                              -->
- **Last sync**: never

## Requirements → tasks

<!-- Filled in during planning and while processing telesma/changes/: one requirement = one row. -->
<!-- A proposal made with external_ref "telesma:<task>" fills its row once the human accepts it. -->

| Requirement (id) | Version @hash | Tasks in PLAN.md |
|------------------|---------------|------------------|
EOF
    echo -e "  ${GREEN}✓${NC} created telesma/state/SPECKY.md (sync cursor + requirement → task map)"
fi

show_description "$HERE/DESCRIPTION.txt"
