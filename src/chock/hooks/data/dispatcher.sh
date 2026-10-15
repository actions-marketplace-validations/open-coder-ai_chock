#!/bin/sh
__MARKER__
# Runs every executable script in __EVENT__.d/.
set -e
HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"
STDIN_FILE=$(mktemp)
trap 'rm -f "$STDIN_FILE"' EXIT
cat > "$STDIN_FILE"
# `chock stop`: while .chock/stop.json is in force, an agent's commit or push is refused; a person's passes.
# A stop in the work tree, in the main checkout (a bare repository is its own), or in any folder above either.
TOP="$(git rev-parse --show-toplevel || true)"
[ -z "$TOP" ] || TOP_REAL="$(cd "$TOP" && pwd -P)"
COMMON="$(cd "$(git rev-parse --git-common-dir)" && pwd -P)"
BARE=""
if [ "$(basename "$COMMON")" = ".git" ]; then MAIN="$(dirname "$COMMON")"; else MAIN="$COMMON"; BARE=1; fi
STOPPED=""
for DIR in "$TOP" "${TOP_REAL:-}" "$MAIN"; do
    while [ -n "$DIR" ]; do
        if [ -e "$DIR/.chock/stop.json" ] || [ -L "$DIR/.chock/stop.json" ]; then STOPPED=1; fi
        PARENT="$(dirname "$DIR")"
        [ "$PARENT" != "$DIR" ] || break
        DIR="$PARENT"
    done
done
if [ -n "$STOPPED" ]; then
    # Only the main checkout's gate.py tells an agent from a person: a work tree may carry an edited copy.
    GATE="$MAIN/.chock/bin/gate.py"
    if [ -n "$BARE" ] || [ ! -f "$GATE" ]; then
        echo "chock: .chock/stop.json is in force and the main checkout has no .chock/bin/gate.py to tell an agent from a person; refused. A person runs chock resume to lift the stop." >&2
        exit 1
    fi
    PY="$(command -v python3 || command -v python || command -v py || true)"
    if [ -z "$PY" ]; then
        echo "chock: .chock/stop.json is in force and no python is on PATH to tell an agent from a person; refused. A person runs chock resume to lift the stop." >&2
        exit 1
    fi
    "$PY" "$GATE" stop-check --event __EVENT__ < "$STDIN_FILE"
fi
for hook in "$HOOK_DIR/__EVENT__.d/"*; do
    [ -e "$hook" ] || continue
    [ -x "$hook" ] || continue
    "$hook" "$@" < "$STDIN_FILE"
done
