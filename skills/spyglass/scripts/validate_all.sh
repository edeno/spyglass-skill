#!/usr/bin/env bash
# Convenience runner: main validator + regression fixtures + (optional)
# runnable-example import harness. Single command instead of remembering
# three invocations.
#
# Usage:
#   spyglass/scripts/validate_all.sh [--spyglass-src PATH] [--python-env PATH]
#     [--baseline-warnings N] [--strict]
#
# If --spyglass-src is omitted we try $SPYGLASS_SRC then ../spyglass/src.
# If --python-env is omitted the harness step runs under the current
# python3; pass a conda env's python to actually verify real imports
# (otherwise the harness skips everything as "spyglass not installed").
#
# Exit status: 1 if the main validator OR the regression suite fails.
# The harness is informational — its failures are printed but do not
# change the exit code because spyglass environment availability is
# not a property of the skill itself.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_ROOT="$(dirname "$SCRIPT_DIR")"

SPYGLASS_SRC="${SPYGLASS_SRC:-}"
PYTHON_ENV=""
VALIDATOR_ARGS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --spyglass-src)
            SPYGLASS_SRC="$2"; shift 2 ;;
        --python-env)
            PYTHON_ENV="$2"; shift 2 ;;
        --baseline-warnings|--strict|-v|--verbose)
            VALIDATOR_ARGS+=("$1")
            # --baseline-warnings takes a value, -v/--strict don't
            if [[ "$1" == "--baseline-warnings" ]]; then
                VALIDATOR_ARGS+=("$2"); shift
            fi
            shift ;;
        -h|--help)
            sed -n '2,20p' "$0"; exit 0 ;;
        *)
            echo "Unknown argument: $1" >&2; exit 2 ;;
    esac
done

if [[ -z "$SPYGLASS_SRC" ]]; then
    # Best-effort guess: sibling checkout of spyglass at ../spyglass/src
    guess="$(cd "$SKILL_ROOT/../.." 2>/dev/null && pwd)/spyglass/src"
    if [[ -d "$guess/spyglass" ]]; then
        SPYGLASS_SRC="$guess"
    else
        echo "ERROR: --spyglass-src not given and no default found." >&2
        echo "  Pass --spyglass-src PATH or set SPYGLASS_SRC env var." >&2
        exit 2
    fi
fi

PY="${PYTHON_ENV:-python3}"

echo "============================================================"
echo "[1/3] Main validator"
echo "============================================================"
"$PY" "$SCRIPT_DIR/validate_skill.py" --spyglass-src "$SPYGLASS_SRC" \
    "${VALIDATOR_ARGS[@]}"
validator_rc=$?

echo
echo "============================================================"
echo "[2/3] Regression fixtures"
echo "============================================================"
"$PY" "$SKILL_ROOT/tests/test_validator_regressions.py" \
    --spyglass-src "$SPYGLASS_SRC"
regression_rc=$?

echo
echo "============================================================"
echo "[3/3] Runnable-example import harness (informational)"
echo "============================================================"
"$PY" "$SKILL_ROOT/tests/test_runnable_imports.py" \
    --spyglass-src "$SPYGLASS_SRC" || true  # harness rc is informational

echo
if [[ $validator_rc -ne 0 || $regression_rc -ne 0 ]]; then
    echo "FAILED: validator=$validator_rc regression=$regression_rc"
    exit 1
fi
echo "All gated checks passed."
