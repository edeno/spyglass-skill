#!/usr/bin/env bash
# Pre-commit wrapper: run the full skill validator if a Spyglass checkout
# is discoverable (via $SPYGLASS_SRC or sibling clone), otherwise skip
# gracefully rather than blocking commits on missing local setup.
#
# Rationale: contributors without Spyglass cloned shouldn't be forced to
# install it just to commit a typo fix. CI runs the authoritative check
# against live LorenFrankLab/spyglass master regardless.

set -u

REPO_ROOT="$(git rev-parse --show-toplevel)"

if [[ -z "${SPYGLASS_SRC:-}" && ! -d "$REPO_ROOT/../spyglass/src" ]]; then
    echo "[pre-commit] skipping validator: no Spyglass source found."
    echo "  To enable, set SPYGLASS_SRC or clone spyglass next to this repo:"
    echo "    git clone https://github.com/LorenFrankLab/spyglass.git $(dirname "$REPO_ROOT")/spyglass"
    exit 0
fi

exec "$REPO_ROOT/skills/spyglass/scripts/validate_all.sh" --baseline-warnings 3
