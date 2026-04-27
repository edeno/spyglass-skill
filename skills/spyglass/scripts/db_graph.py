#!/usr/bin/env python3
"""DB-resolved Spyglass inspection (read-only).

Lifecycle
---------

Prototype here. Upstream candidate: ``spyglass.utils.db_graph`` or
``spyglass.cli.db_graph``. Sibling to ``code_graph.py`` (source-only): this
script answers "what rows / runtime DataJoint tables exist in the
configured session?" rather than "what does the checked-out source
declare?"

Read-only by construction. The script never inserts, deletes, updates,
populates, alters, drops, or executes raw SQL. The CLI surface intentionally
exposes no path that could mutate state.

Subcommands
-----------

* ``db_graph.py info --json`` — static contract dump. Does NOT import
  DataJoint or Spyglass; works on a system Python where neither is
  installed. Use this to discover the tool's surface (subcommands, exit
  codes, payload envelopes, security profile) without paying connection
  cost.
* ``db_graph.py find-instance --class CLS [...]`` — bounded row lookup,
  count, merge-key resolution, conservative set ops, and grouped counts.
  *Implementation lands in Batch C+ per docs/plans/db-graph-impl-plan.md;
  this build (Batch A) ships the scaffold and contract only.*

Exit codes
----------

* ``0`` — query succeeded. ``count: 0`` is a successful answer; opt into
  non-zero on empty via ``--fail-on-empty`` (exit ``7``).
* ``2`` — usage error (argparse default; also missing required flag combos
  like ``--merge-master`` without ``--part``).
* ``3`` — class resolution ambiguous; re-run with module path or
  ``--import``.
* ``4`` — class/table not found (distinct from "0 rows": this means the
  thing the user named could not be located at all).
* ``5`` — DB/session error: connection, auth, schema, or DataJoint import
  failure. Distinct from ``code_graph.py``'s exit ``5`` (heuristic
  refusal). The ``info --json.comparison`` block flags this divergence.
* ``6`` — refused unsafe request.
* ``7`` — query succeeded but ``--fail-on-empty`` was set and ``count == 0``.

Lazy-import discipline
----------------------

Top-of-module imports stay stdlib + ``_index``. DataJoint and Spyglass are
imported inside ``cmd_find_instance`` only, so ``info`` and parser-error
paths run on a Python without DataJoint installed. This is the property
that lets an LLM call ``info`` to introspect the tool before paying
import + connection cost.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# Co-located helper module; same directory as this script.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _index  # noqa: E402  -- stdlib-only, no datajoint, no spyglass

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCHEMA_VERSION = _index.SCHEMA_VERSION  # = 1, shared with code_graph.py.
GRAPH_KIND = "db"
AUTHORITY = "runtime-db"

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_AMBIGUOUS = 3
EXIT_NOT_FOUND = 4
# DB / session error: connection, auth, schema, datajoint import. Distinct
# from code_graph.py's EXIT_HEURISTIC=5; the divergence is documented in
# the ``comparison`` block of ``info --json`` so an LLM that already knows
# code_graph.py's contract does not carry over the wrong assumption.
EXIT_DB = 5
EXIT_UNSAFE = 6
# Opt-in via ``--fail-on-empty``; default behavior on empty is exit 0 with
# ``count: 0`` because "I checked; there are zero rows" is a valid answer.
EXIT_EMPTY = 7

LIMIT_DEFAULT = 100
LIMIT_HARD_MAX = 1000

# Result-shape enum surfaced via ``info --json.result_shapes``.
RESULT_SHAPE_VALUES = ("rows", "count", "merge", "grouped_count", "error")

# Timings keys promised by the contract: every successful DB-reaching
# payload has all of these populated (integer milliseconds; ``total >=
# sum(parts) - 1`` to allow rounding).
TIMINGS_KEYS = (
    "import",
    "connect",
    "resolve",
    "heading",
    "query",
    "serialize",
    "total",
)


# ---------------------------------------------------------------------------
# Provenance / payload helpers
# ---------------------------------------------------------------------------


def _provenance_fields(source_root: Path | str | None) -> dict:
    """Top-level provenance stamp shared by every JSON payload.

    Mirrors ``code_graph._provenance_fields`` but stamps DB-graph
    identity. ``source_root`` is the resolved Spyglass source tree (used
    for stock short-name resolution); ``None`` is the right value for
    static payloads like ``info`` that never touch the source tree.
    """
    return {
        "graph": GRAPH_KIND,
        "authority": AUTHORITY,
        "source_root": str(source_root) if source_root is not None else None,
    }


def _stamp_envelope(
    kind: str,
    *,
    source_root: Path | str | None = None,
    extra: dict | None = None,
) -> dict:
    """Build the canonical top-of-payload envelope in stable order.

    Order matters: LLM consumers benefit from consistent field placement
    when reading payloads (especially comparing two payloads in a diff).
    Insertion order is preserved by Python's ``dict``; do not refactor
    to ``sort_keys=True`` in callers' ``json.dumps``.
    """
    payload: dict = {
        "schema_version": SCHEMA_VERSION,
        "kind": kind,
    }
    payload.update(_provenance_fields(source_root))
    if extra:
        payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# Timer
# ---------------------------------------------------------------------------


class _Timer:
    """Cumulative ms timer tracked across the canonical phases.

    The keys mirror ``TIMINGS_KEYS``; ``total`` is filled by ``finalize()``
    rather than tracked as a phase, because the phases may overlap (e.g.,
    serialize starts before query fully closes when streaming) and ``total``
    is wall-clock. Use ``mark(name)`` to start a phase and ``stop()`` to
    end the most recently started one. Missing phases stay ``0``.
    """

    def __init__(self) -> None:
        self._start = time.perf_counter()
        self._phase: str | None = None
        self._phase_start: float | None = None
        self._accum: dict[str, int] = {k: 0 for k in TIMINGS_KEYS}

    def mark(self, phase: str) -> None:
        """Start a phase. Closes any currently open phase first."""
        if phase not in self._accum:
            raise ValueError(
                f"Unknown timer phase {phase!r}; expected one of {TIMINGS_KEYS!r}"
            )
        self.stop()
        self._phase = phase
        self._phase_start = time.perf_counter()

    def stop(self) -> None:
        """Close the currently open phase, if any."""
        if self._phase is None or self._phase_start is None:
            return
        elapsed_ms = int((time.perf_counter() - self._phase_start) * 1000)
        self._accum[self._phase] += elapsed_ms
        self._phase = None
        self._phase_start = None

    def finalize(self) -> dict[str, int]:
        """Stop any open phase, fill ``total`` from wall-clock, return dict."""
        self.stop()
        self._accum["total"] = int((time.perf_counter() - self._start) * 1000)
        return dict(self._accum)


# ---------------------------------------------------------------------------
# Payload envelope catalogue (the contract surfaced by ``info``)
# ---------------------------------------------------------------------------

# Every payload kind's top-level field set, in stable order. Field validation
# errors (exit 2) and empty-success results (exit 0, count: 0) reuse the
# ``find-instance`` envelope; the values differ but the shape does not.
PAYLOAD_ENVELOPES: dict[str, list[str]] = {
    "every_payload": [
        "schema_version",
        "kind",
        "graph",
        "authority",
        "source_root",
    ],
    "find-instance": [
        "schema_version",
        "kind",
        "graph",
        "authority",
        "source_root",
        "db",
        "query",
        "count",
        "limit",
        "truncated",
        "incomplete",
        "timings_ms",
        "rows",
    ],
    "merge": [
        "schema_version",
        "kind",
        "graph",
        "authority",
        "source_root",
        "db",
        "query",
        "merge",
        "count",
        "limit",
        "truncated",
        "incomplete",
        "timings_ms",
        "rows",
    ],
    "grouped_count": [
        "schema_version",
        "kind",
        "graph",
        "authority",
        "source_root",
        "db",
        "query",
        "count",
        "limit",
        "truncated",
        "incomplete",
        "timings_ms",
        "groups",
    ],
    "info": [
        "schema_version",
        "kind",
        "graph",
        "authority",
        "source_root",
        "subcommands",
        "exit_codes",
        "payload_envelopes",
        "result_shapes",
        "timings_keys",
        "security_profile",
        "null_policy",
        "comparison",
    ],
    "not_found": [
        "schema_version",
        "kind",
        "graph",
        "authority",
        "source_root",
        "db",
        "query",
        "error",
    ],
    "ambiguous": [
        "schema_version",
        "kind",
        "graph",
        "authority",
        "source_root",
        "db",
        "query",
        "candidates",
        "hint",
    ],
    "db_error": [
        "schema_version",
        "kind",
        "graph",
        "authority",
        "source_root",
        "db",
        "query",
        "error",
        "timings_ms",
    ],
    "unsafe": [
        "schema_version",
        "kind",
        "graph",
        "authority",
        "source_root",
        "db",
        "query",
        "error",
    ],
    # Build-time scaffolding shape: emitted by the find-instance stub
    # while implementation lands in Batch C+. Documenting it here keeps
    # `info --json` the source of truth for every JSON shape the tool
    # can emit, including this one. The kind value is "not_implemented"
    # rather than the generic "error" so an LLM that sees the payload
    # can distinguish a build-incomplete stub from a runtime DB error
    # (which uses the `db_error` envelope).
    "not_implemented": [
        "schema_version",
        "kind",
        "graph",
        "authority",
        "source_root",
        "db",
        "query",
        "error",
        "timings_ms",
    ],
}


# ---------------------------------------------------------------------------
# Argparse
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(__doc__ or "").split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "See module docstring for full usage and limits. "
            "`db_graph.py info --json` dumps the machine-readable contract."
        ),
    )

    sub = parser.add_subparsers(dest="cmd", required=True)

    # info
    p_info = sub.add_parser(
        "info",
        help="Dump the tool's machine-readable contract (no DataJoint import).",
        description=(
            "Static contract dump. Does not import DataJoint or Spyglass — "
            "available even when the user's DB environment is broken."
        ),
    )
    p_info.add_argument("--json", action="store_true", help="Emit JSON.")

    # find-instance — full argparse surface so info advertises the planned
    # contract accurately. Implementation lands in Batch C+; this build
    # returns a structured 'not_implemented' error when invoked.
    p_fi = sub.add_parser(
        "find-instance",
        help=(
            "Bounded row lookup / count / merge-key resolution / set ops / "
            "grouped counts. Read-only."
        ),
        description=(
            "Read-only DataJoint inspection: resolve a class, restrict by "
            "scalar key, fetch bounded rows or counts, route merge-master "
            "lookups through the part, and run conservative set operations. "
            "Implementation arrives in Batch C+; this build is a scaffold."
        ),
    )
    p_fi.add_argument(
        "--class",
        dest="class_name",
        required=True,
        help="Class short name, dotted module path, or `module:Class`.",
    )
    p_fi.add_argument(
        "--src",
        default=None,
        help=(
            "Spyglass source root override for stock short-name resolution. "
            "Default is the installed `spyglass` package's parent directory; "
            "fall back to $SPYGLASS_SRC when the package cannot be imported."
        ),
    )
    p_fi.add_argument(
        "--import",
        dest="imports",
        action="append",
        default=[],
        metavar="MODULE",
        help="Import a custom/lab module before class resolution (repeatable).",
    )
    p_fi.add_argument(
        "--key",
        action="append",
        default=[],
        metavar="FIELD=VALUE",
        help=(
            "Equality restriction (repeatable). Scalar literals only "
            "(string, int, float, bool); `null` is refused in MVP."
        ),
    )
    p_fi.add_argument(
        "--key-json",
        action="append",
        default=[],
        metavar="FIELD=JSON",
        help=(
            "JSON-typed restriction (repeatable). For DataJoint `json` "
            "attribute types only; blob restrictions are refused."
        ),
    )
    p_fi.add_argument(
        "--fields",
        default="KEY",
        help="Comma-separated fields to fetch. Default `KEY` (primary key only).",
    )
    p_fi.add_argument(
        "--count",
        action="store_true",
        help="Return count only, not rows.",
    )
    p_fi.add_argument(
        "--limit",
        type=_limit_int,
        default=LIMIT_DEFAULT,
        help=f"Row cap (default {LIMIT_DEFAULT}, hard max {LIMIT_HARD_MAX}).",
    )
    p_fi.add_argument(
        "--merge-master",
        default=None,
        metavar="MASTER",
        help="Merge master class. Requires --part.",
    )
    p_fi.add_argument(
        "--part",
        default=None,
        metavar="PART",
        help="Merge part class. Required when --merge-master is set.",
    )
    p_fi.add_argument(
        "--intersect",
        default=None,
        metavar="CLASS",
        help="DB-side intersection: `L & R.proj()` along shared attributes.",
    )
    p_fi.add_argument(
        "--except",
        dest="except_class",
        default=None,
        metavar="CLASS",
        help="DB-side antijoin: `L - R.proj()` along shared attributes.",
    )
    p_fi.add_argument(
        "--join",
        default=None,
        metavar="CLASS",
        help="DataJoint natural join: `L * R`. Requires shared attributes.",
    )
    p_fi.add_argument(
        "--group-by",
        default=None,
        metavar="f1,f2",
        help="Bounded grouped count by explicit fields (with --count-distinct).",
    )
    p_fi.add_argument(
        "--group-by-table",
        default=None,
        metavar="CLASS",
        help=(
            "Bounded grouped count keyed by another class's primary key "
            "(with --count-distinct)."
        ),
    )
    p_fi.add_argument(
        "--count-distinct",
        default=None,
        metavar="FIELD",
        help="Field to count distinct values of, paired with --group-by[-table].",
    )
    p_fi.add_argument(
        "--fail-on-empty",
        action="store_true",
        help=(
            "Exit 7 instead of 0 when the query succeeds with count == 0. "
            "Default on empty is exit 0 with `count: 0`."
        ),
    )
    p_fi.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON (the only output format in MVP).",
    )

    return parser


def _limit_int(s: str) -> int:
    """Validator for ``--limit``: positive int, no greater than the hard max."""
    try:
        n = int(s)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"--limit must be an integer, got {s!r}"
        ) from exc
    if n <= 0:
        raise argparse.ArgumentTypeError(f"--limit must be > 0, got {n}")
    if n > LIMIT_HARD_MAX:
        raise argparse.ArgumentTypeError(
            f"--limit hard max is {LIMIT_HARD_MAX}, got {n}"
        )
    return n


# ---------------------------------------------------------------------------
# Subcommand: info
# ---------------------------------------------------------------------------


def cmd_info(args: argparse.Namespace) -> int:
    """Static machine-readable contract dump.

    Must not import DataJoint or Spyglass — exists so an LLM can introspect
    this tool even when the user's DB environment is broken (which is when
    the agent most needs to know the tool's contract).
    """
    payload = _stamp_envelope("info", source_root=None)
    payload["subcommands"] = {
        "find-instance": {
            "purpose": (
                "Read-only DataJoint inspection: resolve a class, restrict "
                "by scalar key, fetch bounded rows or counts, route merge-"
                "master lookups through the part, run conservative set ops, "
                "and emit bounded grouped counts."
            ),
            "modes": {
                "rows": "Default. Returns up to --limit rows in `rows`.",
                "count": "--count. Returns `count` only; `rows: []`.",
                "merge": (
                    "--merge-master MASTER --part PART. Restricts the part by "
                    "user keys, resolves master keys via DataJoint structural "
                    "metadata (part.master / heading.foreign_keys), returns "
                    "master rows + part-evidence in `merge`."
                ),
                "intersect/except/join": (
                    "--intersect / --except / --join CLASS. DB-side relational "
                    "operations along shared attributes; refuses zero-overlap."
                ),
                "grouped_count": (
                    "--group-by f1,f2 --count-distinct FIELD or "
                    "--group-by-table CLASS --count-distinct FIELD."
                ),
            },
            "hints": [
                "Default --limit is 100; hard max is 1000.",
                "Empty result is exit 0 with count: 0; opt into exit 7 via --fail-on-empty.",
                "--key field=null is refused in MVP (DataJoint silently drops it).",
                "--merge-master requires --part; either alone exits 2.",
                (
                    "Source resolution order: --src > installed `spyglass` "
                    "package parent > $SPYGLASS_SRC."
                ),
            ],
        },
        "info": {
            "purpose": "This call: dump the tool's machine-readable contract.",
            "modes": {"--json": "Emit machine-readable JSON."},
            "hints": [
                "Static — does not import DataJoint or Spyglass.",
                "Use this to introspect the tool before paying connection cost.",
            ],
        },
    }
    payload["exit_codes"] = {
        "0": (
            "ok. Empty rows count as success — `count: 0` is a valid answer."
        ),
        "2": (
            "usage error (argparse default; also missing required flag combos "
            "such as --merge-master without --part)."
        ),
        "3": (
            "class resolution ambiguous; re-run with module path or --import."
        ),
        "4": (
            "class/table not found in the resolved source/runtime. Distinct "
            "from `count: 0`: this means the thing the user named could not "
            "be located at all."
        ),
        "5": (
            "DB/session error: connection, auth, schema unavailable, or "
            "DataJoint import failure. Payload's `error.kind` discriminates "
            "(`connection|auth|schema|datajoint_import`). NOTE: differs from "
            "`code_graph.py`'s exit 5 (heuristic refusal); see `comparison`."
        ),
        "6": (
            "refused unsafe request (e.g., write method invocation, raw SQL)."
        ),
        "7": (
            "query succeeded but --fail-on-empty was set and count == 0. "
            "Opt-in only; default on empty is exit 0."
        ),
    }
    payload["payload_envelopes"] = {
        k: list(v) for k, v in PAYLOAD_ENVELOPES.items()
    }
    payload["result_shapes"] = list(RESULT_SHAPE_VALUES)
    payload["timings_keys"] = list(TIMINGS_KEYS)
    payload["security_profile"] = {
        "read_only": True,
        "writes_refused": [
            "insert",
            "insert1",
            "delete",
            "delete_quick",
            "drop",
            "drop_quick",
            "populate",
            "alter",
        ],
        "raw_sql": False,
        "python_eval": False,
        "import_side_effects": (
            "Modules named via --import execute their normal Python import "
            "side effects. The user supplies these names; no eval is provided."
        ),
        "secrets_policy": (
            "Connection passwords, credentials, and full tracebacks are never "
            "printed. Use scrub_dj_config.py to inspect a DataJoint config."
        ),
    }
    payload["null_policy"] = {
        "key_null_refused": True,
        "reason": (
            "`{field: None}` is silently dropped by DataJoint — it does not "
            "generate `field IS NULL`. Refusing it in MVP avoids the silent-"
            "no-op footgun. Workaround: filter NULLs in a follow-up step."
        ),
        "blob_restriction_refused": True,
        "blob_reason": (
            "DataJoint cannot restrict on blob/longblob attributes server-"
            "side. --key-json is for `json` attribute types only."
        ),
    }
    payload["comparison"] = {
        "sibling_tool": "code_graph.py",
        "shared": {
            "schema_version": SCHEMA_VERSION,
            "exit_codes_0_2_3_4": (
                "Same semantics: ok / usage / ambiguous / not-found."
            ),
        },
        "differences": {
            "graph": "db_graph='db'; code_graph='code'.",
            "authority": "db_graph='runtime-db'; code_graph='source-only'.",
            "exit_code_5": (
                "db_graph=DB/session error; code_graph=heuristic refusal "
                "(--fail-on-heuristic). Same number, different cause."
            ),
            "src_root_resolution": (
                "db_graph adds an installed-package fallback "
                "(Path(spyglass.__file__).resolve().parent.parent) before "
                "$SPYGLASS_SRC. code_graph requires --src or $SPYGLASS_SRC. "
                "Backporting the fallback to a shared helper is a deferred "
                "follow-up; until then the divergence is intentional."
            ),
        },
    }
    if args.json:
        print(json.dumps(payload))
    else:
        print("db_graph.py — read-only DB-resolved Spyglass inspection")
        print(f"\nGraph: {payload['graph']}    Authority: {payload['authority']}")
        print("\nSubcommands:")
        for name, info in payload["subcommands"].items():
            purpose = str(info["purpose"])
            print(f"  {name}: {purpose.splitlines()[0]}")
        print("\nExit codes:")
        for code, meaning in payload["exit_codes"].items():
            print(f"  {code} — {meaning.splitlines()[0]}")
        print("\n(Pass --json for the full machine-readable payload.)")
    return EXIT_OK


# ---------------------------------------------------------------------------
# Subcommand: find-instance (Batch A scaffold; full impl lands in Batch C+)
# ---------------------------------------------------------------------------


def cmd_find_instance(args: argparse.Namespace) -> int:
    """Stub for Batch A: emit a structured 'not_implemented' error.

    Argparse already validates the surface, so the stub focuses on
    surfacing the contract failure cleanly: ``error.kind="not_implemented"``
    with a pointer to ``info --json`` for the planned shape.

    Replaced in Batch C with the real implementation. Tests for this stub
    pin the envelope shape so Batch C does not silently drift the contract.
    """
    timer = _Timer()
    # `kind: "not_implemented"` matches the `not_implemented` envelope
    # documented in info --json.payload_envelopes. Distinct from the
    # `db_error` envelope (which is for runtime DataJoint failures) so
    # an LLM sees "build incomplete" vs "DB unavailable" as separate
    # conditions.
    payload = _stamp_envelope("not_implemented", source_root=None)
    payload["db"] = None
    payload["query"] = {
        "class": args.class_name,
        "stage": "scaffold",
    }
    payload["error"] = {
        "kind": "not_implemented",
        "message": (
            "find-instance is not implemented in this build (Batch A scaffold "
            "per docs/plans/db-graph-impl-plan.md). The contract is stable; "
            "see `db_graph.py info --json` for subcommand surface, exit "
            "codes, and payload envelopes."
        ),
        "next_batch": "Batch C (basic find-instance) per implementation plan.",
    }
    payload["timings_ms"] = timer.finalize()
    print(json.dumps(payload), file=sys.stderr)
    return EXIT_USAGE


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    if args.cmd == "info":
        return cmd_info(args)
    if args.cmd == "find-instance":
        # Cross-flag validation that argparse cannot express. Keep these in
        # sync with `info --json`'s `subcommands.find-instance.hints` and
        # `subcommands.find-instance.modes`. Pin each rule with a fixture
        # so Batch C+ cannot drift into accepting malformed combinations.
        if bool(args.merge_master) != bool(args.part):
            parser.error("--merge-master and --part must be supplied together")
        if args.group_by and args.group_by_table:
            parser.error(
                "--group-by and --group-by-table are mutually exclusive; "
                "pick one grouping form"
            )
        if (args.group_by or args.group_by_table) and not args.count_distinct:
            parser.error(
                "--group-by / --group-by-table require --count-distinct FIELD; "
                "free-form aggregates are out of MVP"
            )
        if args.count_distinct and not (args.group_by or args.group_by_table):
            parser.error(
                "--count-distinct requires --group-by FIELDS or "
                "--group-by-table CLASS"
            )
        return cmd_find_instance(args)
    # Argparse's `required=True` on the subparsers makes this unreachable
    # at runtime; `parser.error` raises SystemExit, so no return is needed.
    parser.error(f"unknown subcommand {args.cmd!r}")


if __name__ == "__main__":
    sys.exit(main())
