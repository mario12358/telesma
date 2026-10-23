#!/usr/bin/env bash
# Runs every Telesma self-test (tools/test-*.py) and reports a summary.
# Usage: tools/test-all.sh [name-filter]
# Each test builds its fixtures in a temporary directory and never touches this repo.
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1
filter="${1:-}"
failed=()
total=0
for t in tools/test-*.py; do
    [[ -n "$filter" && "$t" != *"$filter"* ]] && continue
    total=$((total + 1))
    start=$(date +%s)
    log=$(mktemp)
    if python3 -I "$t" >"$log" 2>&1; then
        printf '  ok    %-36s %4ss\n' "$t" "$(( $(date +%s) - start ))"
    else
        printf '  FAIL  %-36s %4ss\n' "$t" "$(( $(date +%s) - start ))"
        tail -20 "$log" | sed 's/^/        /'
        failed+=("$t")
    fi
    rm -f "$log"
done
echo
if (( ${#failed[@]} )); then
    echo "${#failed[@]} of $total test files failed: ${failed[*]}"
    exit 1
fi
echo "All $total test files passed."
