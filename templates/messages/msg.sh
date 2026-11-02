#!/bin/bash
# Launcher messages in the user's language (## Project → Language).
#
#   msg KEY 'English text with %s' [args…]   → the translation of KEY from <lang>.txt, or the
#                                              English text when there is none. printf semantics,
#                                              no trailing newline: callers wrap it in echo -e.
#
# The English text stays in the code, next to its use, so the code reads as before and every
# message works without a catalog. A catalog (templates/messages/<lang>.txt, `KEY = text` lines)
# covers what a person sees on the way from the idea to the first build — the interview, the
# beginner settings, telemetry, the clarification questions, the next step. Messages without a
# key (the developer-only wizard steps, diagnostics) stay English. tools/test-setup.py checks
# that every key used in the code exists in every catalog with the same %s placeholders.
# Sourced by telesma.sh (and by the wizard through it); plain Bash 3.2, one awk per message.

MSG_DIR="$SCRIPT_DIR/templates/messages"
MSG_LANG=en

# A Language value → a catalog code: `pl`, `PL`, `pl-PL`, `polski`, `Polish` → pl. Anything without
# a catalog → en (the model still talks in that language; only the launcher's lines are English).
msg_set_language() {
    local l
    l=$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')
    case "$l" in
        polski|polish) l=pl ;;
        *-*|*_*) l=${l%%[-_]*} ;;
    esac
    MSG_LANG=en
    [[ -n "$l" && "$l" != en && -f "$MSG_DIR/$l.txt" ]] && MSG_LANG=$l
    return 0
}

# The system's language as a code (`pl_PL.UTF-8` → pl; C/POSIX/empty → en): the default the
# first start and --new propose for ## Project → Language, catalog or not. A macOS terminal
# often runs with LANG=C.UTF-8 while the system is set to another language — then the
# system's own locale (AppleLocale) decides. Git Bash on Windows exports no LANG at all (the
# desktop shortcut's menu came up in English on a Polish PC) — there the user's Windows locale
# from the registry decides (`pl-PL`; reg.exe is always there, ~0.1 s; MSYS_NO_PATHCONV keeps
# Bash from turning `/v` into a path).
msg_system_language() {
    local l
    l=$(printf '%s' "${LC_ALL:-${LC_MESSAGES:-${LANG:-}}}" | cut -d. -f1)
    case "$l" in
        ""|C|c|POSIX|posix)
            l=""
            case "$(uname -s 2>/dev/null)" in
                Darwin) l=$(defaults read -g AppleLocale 2>/dev/null) ;;
                MINGW*|MSYS*|CYGWIN*)
                    l=$(MSYS_NO_PATHCONV=1 reg query 'HKCU\Control Panel\International' /v LocaleName 2>/dev/null \
                        | tr -d '\r' | awk '$1 == "LocaleName" { print $3 }') ;;
            esac ;;
    esac
    l=$(printf '%s' "$l" | cut -d_ -f1 | cut -d- -f1 | cut -d@ -f1 | tr '[:upper:]' '[:lower:]')
    printf '%s' "${l:-en}"
}

# msg_load_language <config.md> — reads ## Project → Language. No file yet (a new project): the
# language set before (the system's) stays — the --new language question is asked in it.
msg_load_language() {
    local v=""
    [[ -f "$1" ]] || return 0
    v=$(grep -m1 '^- \*\*Language\*\*:' "$1" | sed 's/^[^:]*:[[:space:]]*//')
    msg_set_language "$v"
}

msg() {
    local key="$1" text="$2" t
    shift 2
    if [[ "$MSG_LANG" != en ]]; then
        t=$(awk -v k="$key" 'substr($0, 1, length(k) + 3) == k " = " { print substr($0, length(k) + 4); exit }' \
            "$MSG_DIR/$MSG_LANG.txt" 2>/dev/null)
        [[ -n "$t" ]] && text="$t"
    fi
    # shellcheck disable=SC2059  # the text IS the format: translations carry their own %s
    printf -- "$text" "$@"
}
