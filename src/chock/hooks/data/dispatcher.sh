#!/bin/sh
__MARKER__
# Runs every executable script in __EVENT__.d/.
set -e
HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"
STDIN_FILE=$(mktemp)
trap 'rm -f "$STDIN_FILE"' EXIT
cat > "$STDIN_FILE"
# `chock stop`: while .chock/stop.json is in force, an agent's commit or push is refused; a person's passes.
TOP="$(git rev-parse --show-toplevel)"
if [ -e "$TOP/.chock/stop.json" ] || [ -L "$TOP/.chock/stop.json" ]; then
    if [ -f "$TOP/.chock/bin/gate.py" ]; then
        PY="$(command -v python3 || command -v python || command -v py || true)"
        if [ -z "$PY" ]; then
            echo "chock: .chock/stop.json is in force and no python is on PATH to tell an agent from a person; refused. A person runs chock resume to lift the stop." >&2
            exit 1
        fi
        "$PY" "$TOP/.chock/bin/gate.py" stop-check --event __EVENT__ < "$STDIN_FILE"
    fi
fi
for hook in "$HOOK_DIR/__EVENT__.d/"*; do
    [ -e "$hook" ] || continue
    [ -x "$hook" ] || continue
    "$hook" "$@" < "$STDIN_FILE"
done
