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
  *Through Batch B class resolution is implemented end-to-end; the
  query stage (heading validation, restriction, fetch, set ops,
  aggregation) lands in Batch C+ per
  docs/plans/db-graph-impl-plan.md. A successfully-resolved query
  returns ``kind: "not_implemented"`` with ``query.stage="resolved"``
  until then.*

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

Top-of-module imports stay stdlib + ``_index`` + ``code_graph``. Both
co-located helpers are stdlib-only (no ``datajoint``, no ``spyglass``).
DataJoint and Spyglass are imported only when the resolver actually
needs them: ``importlib.import_module`` runs inside ``_import_walk``
when a class needs to be retrieved, and the ``UserTable`` predicate
inside ``_is_datajoint_user_table`` imports ``datajoint.user_tables``.
Resolution paths that fail before the predicate (ambiguous, malformed
input, missing module) never pay the DataJoint or Spyglass import cost,
and ``info --json`` runs on a Python where neither is installed. This is
the property that lets an LLM call ``info`` to introspect the tool
before paying import + connection cost.
"""

from __future__ import annotations

import argparse
import importlib
import inspect
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

# Co-located helper modules; same directory as this script. Both are stdlib-
# only — no datajoint, no spyglass — so importing them does not violate the
# "info runs on a Python without DataJoint installed" discipline. The
# `code_graph` import is intentional: db_graph reuses code_graph's
# class-resolution logic (`_resolve_class`) rather than duplicating the
# same-qualname-disambiguation rules. The leading-underscore convention
# marks it as module-private, but the cross-script reuse is sanctioned
# by the implementation plan ("use the existing source-index helpers").
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _index  # noqa: E402
import code_graph  # noqa: E402

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
# Class resolution
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Resolved:
    """Successful class-resolution result.

    Carries enough provenance for the find-instance payload to cite which
    resolution path won (so an LLM can see why a particular class was
    chosen, especially when the same short name resolves to different
    things via stock-index vs module-path).
    """

    # ``cls`` is a DataJoint ``UserTable`` subclass. Annotated as ``object``
    # because the type checker cannot follow the ``_is_datajoint_user_table``
    # runtime narrowing across the dataclass boundary; expressing this with
    # a Protocol would require importing DataJoint at type-check time, which
    # the lazy-import discipline forbids.
    cls: object
    name: str  # the user-supplied --class argument, verbatim
    qualname: str  # dotted Spyglass qualname (e.g., "LFPOutput.LFPV1")
    module: str  # importable Python module path
    source: str  # "module_path" | "stock_index" | "imported_module"
    src_root: Path | None  # populated when source == "stock_index"


class _ClassResolutionError(Exception):
    """Base for class-resolution failures.

    Subclass declares `exit_code` and the structured payload bits the
    find-instance handler should emit. Using exceptions rather than a
    tagged union keeps the happy path readable and lets each error site
    short-circuit at the point of failure.
    """

    exit_code: int = EXIT_NOT_FOUND


class _AmbiguousClass(_ClassResolutionError):
    exit_code = EXIT_AMBIGUOUS

    def __init__(self, name: str, candidates: list) -> None:
        super().__init__(f"{name!r} resolves to multiple classes")
        self.name = name
        self.candidates = candidates


class _ClassNotFound(_ClassResolutionError):
    exit_code = EXIT_NOT_FOUND

    def __init__(
        self,
        name: str,
        hint: str = "",
        suggestions: tuple[str, ...] = (),
    ) -> None:
        super().__init__(f"{name!r} not found")
        self.name = name
        self.hint = hint
        self.suggestions = tuple(suggestions)


class _NotADataJointTable(_ClassResolutionError):
    exit_code = EXIT_NOT_FOUND

    def __init__(
        self, name: str, qualname: str, module: str, actual_kind: str
    ) -> None:
        super().__init__(f"{qualname!r} is not a DataJoint table")
        self.name = name
        self.qualname = qualname
        self.module = module
        self.actual_kind = actual_kind


class _DataJointUnavailable(_ClassResolutionError):
    """DataJoint cannot be imported, blocking the UserTable predicate.

    Distinct from ``_NotADataJointTable`` (class exists but is the wrong
    type): this signals the runtime environment cannot run the type
    check at all. Maps to the canonical exit-5 ``db_error`` shape with
    ``error.kind="datajoint_import"`` so an LLM can distinguish "your
    class is the wrong type" from "I can't even check the type."
    """

    exit_code = EXIT_DB

    def __init__(self, name: str, original: ImportError) -> None:
        super().__init__(f"DataJoint not importable: {original}")
        self.name = name
        self.original = original


def _select_src_root(arg_src: str | None) -> Path | None:
    """Pick a Spyglass source root, with installed-package fallback.

    Plan order:

    1. ``--src PATH`` if supplied (highest priority).
    2. Installed-package parent: ``Path(spyglass.__file__).resolve().parent.parent``.
       This is the directory containing the ``spyglass/`` package, which is
       what ``_index.scan`` requires (it looks up ``src_root / "spyglass"``).
    3. ``$SPYGLASS_SRC`` (lowest priority).

    Returns ``None`` when none of the above resolve. The caller is then
    free to skip the stock-index lookup and fall back to module-path
    resolution — custom-table users who supply ``--import`` or
    ``module:Class`` can still proceed without a Spyglass source tree.

    Diverges intentionally from ``_index.resolve_src_root``, which exits
    ``2`` instead of returning ``None`` and lacks the installed-package
    fallback. The divergence is documented in ``info --json.comparison``.
    """
    if arg_src:
        candidate = Path(arg_src).resolve()
        if (candidate / "spyglass").is_dir():
            return candidate
        # User asked for a specific src_root that does not contain
        # spyglass/ — fall through so the resolver can surface a clear
        # error rather than silently swallowing the bogus path.
        return candidate
    try:
        import spyglass

        spyglass_file = getattr(spyglass, "__file__", None)
        if spyglass_file is not None:
            candidate = Path(spyglass_file).resolve().parent.parent
            if (candidate / "spyglass").is_dir():
                return candidate
    except ImportError:
        pass
    env = os.environ.get("SPYGLASS_SRC")
    if env:
        return Path(env).resolve()
    return None


def _record_module_path(record: _index.ClassRecord) -> str:
    """Convert ``ClassRecord.file`` (rel-to-src_root) to an importable module path.

    ``file`` looks like ``"spyglass/common/common_session.py"``; output
    is ``"spyglass.common.common_session"``. ``__init__.py`` files map
    to the package itself.
    """
    f = record.file
    if f.endswith(".py"):
        f = f[:-3]
    parts = f.split("/")
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _is_datajoint_user_table(obj: object, *, name_hint: str) -> bool:
    """Predicate for the DataJoint-table check.

    Plan: ``inspect.isclass(cls) and issubclass(cls, UserTable)``.
    Avoids ``isinstance(cls(), dj.Table)`` because instantiation can
    connect to the database, which would defeat the no-DB guarantee of
    class resolution.

    ``UserTable`` is the public superclass for ``dj.Manual``, ``dj.Lookup``,
    ``dj.Imported``, ``dj.Computed``, and ``dj.Part`` in the currently
    installed DataJoint version (verified against
    ``datajoint==0.14.6``).

    Raises ``_DataJointUnavailable`` (exit 5 ``db_error``) when datajoint
    cannot be imported — distinct from returning ``False`` (which means
    the class loaded but is not a UserTable subclass, exit 4
    ``not_a_table``). Keeping the import lazy means resolution paths that
    fail before reaching the predicate (ambiguous, not_found,
    malformed-input) do not pay the DataJoint import cost. ``name_hint``
    propagates the user-supplied class name into the exception so the
    payload can cite it.
    """
    try:
        # IDE type-checker may not see conda site-packages; runtime path
        # uses --python-env so this resolves correctly when invoked.
        from datajoint.user_tables import UserTable  # ty: ignore[unresolved-import]
    except ImportError as exc:
        raise _DataJointUnavailable(name=name_hint, original=exc) from exc
    return inspect.isclass(obj) and issubclass(obj, UserTable)


def _import_walk(
    user_name: str,
    module_name: str,
    qualname_tail: str,
    *,
    source: str,
    src_root: Path | None = None,
) -> _Resolved:
    """Import ``module_name`` and walk the dotted ``qualname_tail`` to a class.

    Used by every resolution path: stock-index lookup converts
    ``ClassRecord`` to ``(module, qualname)`` and dispatches here;
    explicit ``module:Class`` form passes them in directly; dotted
    fallback splits on the last ``.`` and dispatches here.

    Walking the qualname tail (rather than treating it as a flat
    attribute name) lets a single import resolve nested classes like
    ``LFPOutput.LFPV1`` — which is a part-table whose master class is
    the importable top-level symbol.

    Raises ``_ClassNotFound`` for missing module/attribute and
    ``_NotADataJointTable`` when the resolved object is not a
    ``UserTable`` subclass.
    """
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise _ClassNotFound(
            user_name,
            hint=f"module {module_name!r} not importable: {exc}",
        ) from exc

    obj: object = module
    for piece in qualname_tail.split("."):
        try:
            obj = getattr(obj, piece)
        except AttributeError as exc:
            raise _ClassNotFound(
                user_name,
                hint=(
                    f"module {module_name!r} has no attribute path "
                    f"{qualname_tail!r}; failed at {piece!r}"
                ),
            ) from exc

    if not _is_datajoint_user_table(obj, name_hint=user_name):
        actual_kind = (
            obj.__name__ if inspect.isclass(obj) else type(obj).__name__
        )
        raise _NotADataJointTable(
            name=user_name,
            qualname=qualname_tail,
            module=module_name,
            actual_kind=actual_kind,
        )

    return _Resolved(
        cls=obj,  # `_Resolved.cls` is annotated `object`; runtime is UserTable.
        name=user_name,
        qualname=qualname_tail,
        module=module_name,
        source=source,
        src_root=src_root,
    )


def resolve_class(
    name: str,
    src: str | None = None,
    imports: tuple[str, ...] | list[str] = (),
) -> _Resolved:
    """Resolve a user-supplied ``--class`` argument to a live DataJoint class.

    Resolution order (per docs/plans/db-graph-impl-plan.md):

    1. Run user ``--import MODULE`` statements first so any custom-table
       module is in ``sys.modules`` before the stock-name lookup or the
       module-path fallback runs.
    2. Explicit ``module:Class`` syntax — split on ``:``, import, walk.
    3. Stock-index lookup against ``--src`` / installed-package /
       ``$SPYGLASS_SRC``. Reuses ``code_graph._resolve_class`` for the
       same-qualname-disambiguation rules so the two CLIs report the
       same set of ambiguity / not-found cases.
    4. Dotted module-path fallback (``a.b.c.D`` → import ``a.b.c``,
       getattr ``D``).
    5. Otherwise raise ``_ClassNotFound``.

    Raises ``_ClassResolutionError`` subclasses on every failure mode.
    """
    # Step 1: user --import. Failures here surface as not_found because
    # the user's intent was "find this class via this module" — module
    # import failure is a precondition, not a separate error class.
    for mod_name in imports:
        try:
            importlib.import_module(mod_name)
        except ImportError as exc:
            raise _ClassNotFound(
                name,
                hint=f"--import {mod_name!r} failed: {exc}",
            ) from exc

    # Step 2: explicit `module:Class` form.
    if ":" in name:
        module_name, _, class_name = name.rpartition(":")
        if not module_name or not class_name:
            raise _ClassNotFound(
                name,
                hint=f"malformed module:Class form: {name!r}",
            )
        return _import_walk(
            name, module_name, class_name, source="module_path"
        )

    # Step 3: stock _index lookup (also handles dotted qualnames like
    # `LFPOutput.LFPV1` — see code_graph._resolve_class for the rules).
    # Track failure modes separately so the not_found hint can name the
    # specific recovery the user needs (rather than a generic message
    # that mis-blames an unset --src when the user actually supplied a
    # bogus one).
    src_root = _select_src_root(src)
    index_attempted = False
    src_root_invalid = False
    if src_root is not None:
        if (src_root / "spyglass").is_dir():
            index_attempted = True
            idx = _index.scan(src_root)
            record, error_kind, candidates = code_graph._resolve_class(name, idx)
            if error_kind is None and record is not None:
                module_name = _record_module_path(record)
                return _import_walk(
                    name,
                    module_name,
                    record.qualname,
                    source="stock_index",
                    src_root=src_root,
                )
            if error_kind == "ambiguous":
                raise _AmbiguousClass(name, list(candidates))
            # `error_kind == "not_found"` — fall through to module-path attempt.
        else:
            # `src_root` resolved (from --src, installed package, or env)
            # but does not actually contain a `spyglass/` package. Most
            # commonly: user passed --src to a wrong directory.
            src_root_invalid = True

    # Step 4: dotted module-path fallback (only if no `:`, since that
    # branch already returned).
    if "." in name:
        module_name, _, class_name = name.rpartition(".")
        return _import_walk(
            name, module_name, class_name, source="module_path"
        )

    # Step 5: genuine not_found. Pick the hint that describes what was
    # actually tried, not a generic "no source root" message.
    if src_root_invalid:
        hint = (
            f"resolved source root {str(src_root)!r} does not contain "
            "a 'spyglass/' package. If --src was supplied, point it at "
            "the directory CONTAINING `spyglass/` (e.g. the `src/` dir "
            "of an editable Spyglass checkout). Otherwise pass --import "
            "MODULE plus module:Class (or a dotted module path) to "
            "resolve a non-stock class without an _index lookup."
        )
    elif not index_attempted:
        hint = (
            "No Spyglass source root resolved: --src not given, "
            "spyglass package not importable, $SPYGLASS_SRC unset. "
            "Pass --src PATH, or use --import MODULE plus module:Class "
            "(or a dotted module path) to resolve a non-stock class."
        )
    else:
        hint = (
            "Tried _index lookup against the resolved Spyglass source "
            "root and found no records matching this short name. For a "
            "custom or lab-specific class, use --import MODULE plus "
            "module:Class (or a dotted module path) — --import alone "
            "does not make a short name resolvable."
        )
    raise _ClassNotFound(name, hint=hint)


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
    # Error envelopes carry ``timings_ms`` because resolution-stage failures
    # (ambiguous, not_found, not_a_table) still pay for the index scan, and
    # the diagnostic value of seeing where time went outweighs the per-key
    # cost. db_error is the canonical example; the others mirror it for
    # contract symmetry.
    "not_found": [
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
        "timings_ms",
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
        "timings_ms",
    ],
    # Field-validation / restriction-malformed shape (Batch C): the class
    # was resolved successfully but the user-supplied query is malformed
    # in a way DataJoint would silently no-op (unknown field, blob
    # restriction, --key-json with non-JSON value). Maps to exit 2 — a
    # usage error in the same family as "argparse complained" — but the
    # structured payload lets an LLM see exactly which field was bad and
    # what the valid alternatives are.
    "invalid_query": [
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
        default=None,
        help=(
            "Class short name, dotted module path, or `module:Class`. "
            "Required for non-merge queries. In merge mode "
            "(`--merge-master M --part P`), --class is optional and "
            "ignored if supplied."
        ),
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
        help=(
            "Import a custom/lab module before class resolution "
            "(repeatable). Pair with `--class module:Class` or a dotted "
            "module path — --import alone does NOT make a short name "
            "resolvable; the resolver still needs to know which symbol "
            "in the module is the target."
        ),
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
                    "--merge-master MASTER --part PART. Restricts the part "
                    "by user keys, resolves master keys via the part's "
                    "`.master` class attribute (DataJoint sets this on "
                    "every Part at schema-decoration time), and returns "
                    "master rows + part-evidence in `merge`. No shared-PK "
                    "fallback: if `.master` is unset, the call is refused "
                    "with exit 3 rather than guessing the link."
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
                (
                    "--import MODULE is not a standalone resolution path: "
                    "pair it with `--class module:Class` (or a dotted "
                    "module path). --import alone runs the module's "
                    "import side effects but does not register a short "
                    "name."
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
            "class resolution ambiguous; re-run with a dotted qualname "
            "(e.g. `Master.Part`) or `module:Class`. --import alone does "
            "not disambiguate; pair it with module:Class."
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
# Resolution-failure payload emitters (Batch B)
# ---------------------------------------------------------------------------


def _failure_query_block(args: argparse.Namespace) -> dict:
    """Build the standard ``query`` block for failure payloads.

    All emitters route through this helper so error payloads carry the
    same context regardless of which classes the user named. In merge
    mode we include ``merge_master`` and ``part`` so an LLM reading a
    failure can see the full picture (the master *and* the part the
    user supplied), not just the conflated ``query.class``.
    ``args.class_name`` already falls back to ``args.merge_master`` in
    main(), so ``query.class`` is non-null in merge mode.
    """
    query: dict[str, object] = {"class": args.class_name}
    if args.merge_master:
        query["merge_master"] = args.merge_master
    if args.part:
        query["part"] = args.part
    return query


def _record_summary(rec: _index.ClassRecord) -> dict:
    """Render a ``ClassRecord`` for the candidates list of an ambiguous payload.

    Mirrors the agent-readable shape ``code_graph.py`` uses for
    same-name candidates so the LLM can rely on a stable per-record
    structure across both tools.
    """
    return {
        "qualname": rec.qualname,
        "file": rec.file,
        "line": rec.line,
        "tier": rec.tier,
    }


def _emit_ambiguous(
    *,
    args: argparse.Namespace,
    timer: _Timer,
    exc: _AmbiguousClass,
    src_root: Path | None,
) -> int:
    """Print the ambiguous-class payload, return exit 3."""
    payload = _stamp_envelope("ambiguous", source_root=src_root)
    payload["db"] = None
    payload["query"] = _failure_query_block(args)
    payload["candidates"] = [_record_summary(r) for r in exc.candidates]
    payload["hint"] = (
        f"{exc.name!r} matches multiple records in the source index. "
        "Re-run with a dotted qualname (e.g. `Master.Part`), the explicit "
        "`module:Class` form, or `--import MODULE` plus `module:Class` "
        "if this is a custom table — `--import` alone does not make a "
        "short name resolvable."
    )
    payload["timings_ms"] = timer.finalize()
    print(json.dumps(payload))
    return EXIT_AMBIGUOUS


def _emit_not_found(
    *,
    args: argparse.Namespace,
    timer: _Timer,
    exc: _ClassNotFound,
    src_root: Path | None,
) -> int:
    """Print the not_found payload, return exit 4."""
    payload = _stamp_envelope("not_found", source_root=src_root)
    payload["db"] = None
    payload["query"] = _failure_query_block(args)
    payload["error"] = {
        "kind": "not_found",
        "message": f"class {exc.name!r} not found",
        "hint": exc.hint,
        "suggestions": list(exc.suggestions),
    }
    payload["timings_ms"] = timer.finalize()
    print(json.dumps(payload))
    return EXIT_NOT_FOUND


def _emit_not_a_table(
    *,
    args: argparse.Namespace,
    timer: _Timer,
    exc: _NotADataJointTable,
    src_root: Path | None,
) -> int:
    """Print the not-a-DataJoint-table payload, return exit 4.

    Reuses the ``not_found`` envelope shape but distinguishes the case via
    ``error.kind="not_a_table"`` so an LLM can tell "I couldn't find the
    class" apart from "the class exists but is not a DataJoint table".
    """
    payload = _stamp_envelope("not_found", source_root=src_root)
    payload["db"] = None
    query = _failure_query_block(args)
    query["module"] = exc.module
    query["qualname"] = exc.qualname
    payload["query"] = query
    payload["error"] = {
        "kind": "not_a_table",
        "message": (
            f"{exc.qualname!r} from module {exc.module!r} is not a "
            f"DataJoint table; got {exc.actual_kind!r}. "
            "find-instance requires a class that subclasses "
            "datajoint.user_tables.UserTable."
        ),
        "hint": "",
        "suggestions": [],
    }
    payload["timings_ms"] = timer.finalize()
    print(json.dumps(payload))
    return EXIT_NOT_FOUND


def _emit_db_error(
    *,
    args: argparse.Namespace,
    timer: _Timer,
    error_kind: str,
    message: str,
    src_root: Path | None,
    resolved: _Resolved | None = None,
) -> int:
    """Print the db_error payload, return exit 5.

    ``error_kind`` discriminates the failure mode for the LLM:
    ``datajoint_import`` (DataJoint not installed), ``connection``
    (refused / lost), ``auth``, ``schema`` (missing table or column),
    or ``runtime`` (unclassified). When a ``_Resolved`` is supplied,
    the payload's ``query`` block carries the resolution provenance so
    a follow-up tool call can see *which class* triggered the failure
    rather than just the raw ``--class`` argument.
    """
    payload = _stamp_envelope("db_error", source_root=src_root)
    payload["db"] = _build_db_envelope() if resolved is not None else None
    query: dict[str, object] = _failure_query_block(args)
    if resolved is not None:
        query.update(
            {
                "resolved_class": f"{resolved.module}.{resolved.qualname}",
                "module": resolved.module,
                "qualname": resolved.qualname,
                "resolution_source": resolved.source,
            }
        )
    payload["query"] = query
    payload["error"] = {
        "kind": error_kind,
        "message": message,
    }
    payload["timings_ms"] = timer.finalize()
    print(json.dumps(payload))
    return EXIT_DB


# ---------------------------------------------------------------------------
# Batch C — restriction parsing, fetch path, safe serialization
# ---------------------------------------------------------------------------


class _InvalidQuery(Exception):
    """Field-validation or restriction error before the query reaches DataJoint.

    Distinct from ``_ClassResolutionError`` (which fires before we have a
    table to query) and from ``_DataJointUnavailable`` (which fires when
    the runtime can't even check the type). ``_InvalidQuery`` means the
    class was resolved, the runtime is healthy, but the user-supplied
    query is malformed in a way DataJoint would silently no-op
    (unknown field, blob restriction, etc.). Maps to the ``invalid_query``
    envelope and exit ``2`` so an LLM does not interpret it as a runtime
    failure.
    """

    exit_code: int = EXIT_USAGE

    def __init__(self, kind: str, message: str, **extra: object) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.extra = extra


def _parse_scalar_value(raw: str) -> str | int | float | bool:
    """Parse a ``--key field=VALUE`` value into a Python scalar.

    Order of attempts: bool, int, float, string. ``null`` / ``None`` is
    intentionally rejected at the parser level (DataJoint silently drops
    ``{f: None}`` from a restriction; emitting SQL ``IS NULL`` is out of
    MVP scope). Strings are the catch-all so ``--key
    nwb_file_name=j1620210710_.nwb`` parses without quoting.
    """
    if raw == "":
        return ""
    lowered = raw.lower()
    if lowered in ("null", "none"):
        raise _InvalidQuery(
            "null_restriction_refused",
            (
                "--key field=null is refused in MVP. DataJoint silently "
                "drops {field: None} from a restriction; supporting NULL "
                "filtering correctly requires a SQL string restriction "
                "which expands the surface this MVP keeps small. Filter "
                "NULLs in a follow-up step."
            ),
        )
    if lowered in ("true", "false"):
        return lowered == "true"
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        parsed_float = float(raw)
    except ValueError:
        return raw
    # Reject non-finite floats. NaN / Inf are not valid SQL restriction
    # operands (DataJoint can't generate the right comparison) AND
    # ``json.dumps`` emits them as the non-strict literals ``NaN`` /
    # ``Infinity``, which break LLM consumers that pipe through
    # strict JSON parsers. Refuse them here so the contract stays
    # ``allow_nan=False``-compatible end-to-end.
    import math

    if not math.isfinite(parsed_float):
        raise _InvalidQuery(
            "non_finite_restriction",
            (
                f"--key value {raw!r} parses to a non-finite float "
                f"({parsed_float}); DataJoint cannot restrict on NaN / "
                "Inf and the value would emit non-strict JSON."
            ),
            received=raw,
        )
    return parsed_float


def _parse_key_args(
    key_args: list[str], key_json_args: list[str]
) -> dict[str, object]:
    """Parse ``--key`` and ``--key-json`` flags into a single restriction dict.

    Each flag value is ``FIELD=VALUE``; the FIELD before ``=`` is the
    DataJoint attribute name and VALUE is parsed as a scalar (``--key``)
    or as JSON (``--key-json``). Duplicate FIELDs across both flag types
    are rejected because the restriction would be ambiguous.
    """
    out: dict[str, object] = {}
    for flag, items in (("--key", key_args), ("--key-json", key_json_args)):
        for raw in items:
            if "=" not in raw:
                raise _InvalidQuery(
                    "malformed_key",
                    f"{flag} expected FIELD=VALUE, got {raw!r}",
                    flag=flag,
                    received=raw,
                )
            field, _, value = raw.partition("=")
            if not field:
                raise _InvalidQuery(
                    "malformed_key",
                    f"{flag} {raw!r} has empty FIELD",
                    flag=flag,
                    received=raw,
                )
            if field in out:
                raise _InvalidQuery(
                    "duplicate_key",
                    f"field {field!r} given twice in --key/--key-json",
                    field=field,
                )
            if flag == "--key-json":
                try:
                    out[field] = json.loads(value)
                except json.JSONDecodeError as exc:
                    raise _InvalidQuery(
                        "malformed_key",
                        f"--key-json {field}=... value is not valid JSON: {exc}",
                        field=field,
                        received=value,
                    ) from exc
            else:
                out[field] = _parse_scalar_value(value)
    return out


def _parse_fields_arg(fields_raw: str) -> list[str]:
    """Parse ``--fields f1,f2`` into a list. ``KEY`` is the primary-key sentinel.

    Empty entries (e.g. trailing commas) are dropped silently because
    DataJoint accepts ``KEY`` and field-name strings interchangeably and
    a stray empty string would surface as a confusing fetch error. The
    sentinel ``KEY`` is preserved verbatim — DataJoint's fetch API takes
    it directly.
    """
    fields = [f.strip() for f in fields_raw.split(",") if f.strip()]
    return fields or ["KEY"]


def _validate_restriction_fields(
    restriction: dict[str, object],
    heading_names: tuple[str, ...],
) -> None:
    """Refuse restriction keys that DataJoint would silently drop.

    The unknown-attribute footgun: ``(rel & {"unknown": "x"})`` returns
    the unrestricted relation, which an LLM would then mis-cite as
    "filter applied, no rows match." Validating field names against the
    actual heading closes the footgun before it can fire.
    """
    unknown = sorted(set(restriction.keys()) - set(heading_names))
    if unknown:
        raise _InvalidQuery(
            "unknown_field",
            (
                f"restriction fields {unknown!r} are not in the table heading. "
                "DataJoint silently drops unknown-attribute restrictions "
                "(returning the whole relation), which is the wrong-count "
                "footgun this tool exists to close."
            ),
            unknown_fields=unknown,
            valid_fields=list(heading_names),
        )


def _validate_blob_restrictions(
    restriction: dict[str, object],
    heading_attributes: dict,
) -> None:
    """Reject restrictions on blob/longblob attributes.

    DataJoint cannot restrict on blob attributes server-side; the
    restriction would either silently no-op or raise an opaque error
    deep in the SQL layer. Refusing here gives the LLM a clear message
    pointing to the actual cause.
    """
    blob_types = ("blob", "longblob", "tinyblob", "mediumblob")
    bad: list[str] = []
    for field in restriction:
        attr = heading_attributes.get(field)
        if attr is None:
            continue
        attr_type = getattr(attr, "type", "") or ""
        if any(blob_type in str(attr_type).lower() for blob_type in blob_types):
            bad.append(field)
    if bad:
        raise _InvalidQuery(
            "blob_restriction_refused",
            (
                f"fields {bad!r} are blob/longblob types; DataJoint cannot "
                "restrict on blob attributes server-side. Use --key-json for "
                "DataJoint json-typed attributes only."
            ),
            blob_fields=bad,
        )


def _validate_fetch_fields(
    fetch_fields: list[str], heading_names: tuple[str, ...]
) -> None:
    """Refuse ``--fields`` entries that don't exist on the heading.

    The ``KEY`` sentinel is always valid (DataJoint expands it to the
    primary key). All other entries must be in ``heading_names``.
    """
    unknown = [f for f in fetch_fields if f != "KEY" and f not in heading_names]
    if unknown:
        raise _InvalidQuery(
            "unknown_field",
            (
                f"fetch fields {unknown!r} are not in the table heading."
            ),
            unknown_fields=unknown,
            valid_fields=list(heading_names),
        )


def _safe_serialize_value(value: object) -> object:
    """Coerce DataJoint fetch values to JSON-safe forms, per-field.

    Per the plan: per-field substitution, never aborting the whole
    payload. UUID → string, bytes → ``{type:"bytes", length}``, ndarray
    → ``{type:"ndarray", shape, dtype}``, datetime → ISO-8601, NumPy
    scalars → Python scalars, everything else falls back to ``repr`` if
    ``json.dumps`` cannot handle it.
    """
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        # NaN / inf are not JSON-representable; substitute structured envelope.
        import math

        if math.isnan(value) or math.isinf(value):
            return {
                "_unserializable": True,
                "type": "float",
                "value": str(value),
            }
        return value
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {
            "_unserializable": True,
            "type": "bytes",
            "length": len(bytes(value)),
        }
    # datetime / date / time. Importing locally avoids a top-level dep.
    import datetime as _dt

    if isinstance(value, (_dt.datetime, _dt.date, _dt.time)):
        return value.isoformat()
    # uuid.UUID: string repr.
    import uuid as _uuid

    if isinstance(value, _uuid.UUID):
        return str(value)
    # NumPy: imported lazily; many DataJoint scalars are numpy types.
    try:
        import numpy as np  # ty: ignore[unresolved-import]
    except ImportError:
        np = None  # type: ignore[assignment]
    if np is not None:
        if isinstance(value, np.generic):
            # Recurse so a NumPy NaN/Inf scalar (np.float32("nan") etc.)
            # picks up the float-NaN/Inf envelope path; otherwise
            # ``value.item()`` returns a Python float that ``json.dumps``
            # serializes as the non-strict ``NaN`` literal.
            return _safe_serialize_value(value.item())
        if isinstance(value, np.ndarray):
            return {
                "_unserializable": True,
                "type": "ndarray",
                "shape": list(value.shape),
                "dtype": str(value.dtype),
            }
    # Last resort: repr so the payload still serializes. Mark it so the
    # LLM does not interpret repr text as the actual value.
    try:
        json.dumps(value)
    except TypeError:
        return {
            "_unserializable": True,
            "type": type(value).__name__,
            "repr": repr(value)[:200],
        }
    return value


def _build_db_envelope() -> dict:
    """Populate the ``db`` field with sanitized DataJoint config + versions.

    Pulls host / user from ``dj.config`` (no password / connection URL),
    schema prefix from ``dj.config['database.prefix']`` or
    ``custom['database.prefix']`` if set, and version strings via
    ``__version__`` with importlib-metadata fallback. Never raises:
    a malformed or absent value emits ``null`` in the corresponding
    field rather than aborting the whole payload.
    """
    info: dict[str, object] = {
        "host": None,
        "user": None,
        "database": None,
        "spyglass_version": None,
        "datajoint_version": None,
    }
    try:
        import datajoint as dj  # ty: ignore[unresolved-import]

        cfg = getattr(dj, "config", {}) or {}
        info["host"] = cfg.get("database.host")
        info["user"] = cfg.get("database.user")
        prefix = cfg.get("database.prefix")
        if not prefix:
            custom = cfg.get("custom") or {}
            prefix = custom.get("database.prefix")
        info["database"] = prefix or None
        info["datajoint_version"] = getattr(dj, "__version__", None)
    except Exception:
        pass
    try:
        import spyglass

        info["spyglass_version"] = getattr(spyglass, "__version__", None)
    except Exception:
        pass
    if info["spyglass_version"] is None:
        try:
            import importlib.metadata as _md

            info["spyglass_version"] = _md.version("spyglass-neuro")
        except Exception:
            pass
    return info


def _emit_invalid_query(
    *,
    args: argparse.Namespace,
    timer: _Timer,
    resolved: _Resolved | None,
    exc: _InvalidQuery,
    src_root: Path | None,
) -> int:
    """Print the invalid_query payload, return exit 2.

    Reuses the find-instance envelope shape with an explicit ``error``
    block so an LLM sees both the resolved-class context (when the
    resolution succeeded but the query was malformed) and the specific
    field that caused the rejection.
    """
    payload = _stamp_envelope("invalid_query", source_root=src_root)
    payload["db"] = _build_db_envelope() if resolved is not None else None
    payload["query"] = _failure_query_block(args)
    if resolved is not None:
        payload["query"].update(
            {
                "module": resolved.module,
                "qualname": resolved.qualname,
                "resolution_source": resolved.source,
            }
        )
    payload["error"] = {
        "kind": exc.kind,
        "message": exc.message,
        **{k: v for k, v in exc.extra.items()},
    }
    payload["timings_ms"] = timer.finalize()
    print(json.dumps(payload))
    return EXIT_USAGE


# ---------------------------------------------------------------------------
# Batch D — merge-aware lookup
# ---------------------------------------------------------------------------


def _identify_master_key_fields(
    part_cls: object,
    master_cls: object,
    _part_heading,
    master_heading,
) -> tuple[str, ...]:
    """Identify the part columns that link to the master.

    DataJoint sets ``Part.master`` on every Part class at
    schema-decoration time. Spyglass tables rely on this attribute,
    and lab/custom Parts that wrap Spyglass merges set it the same
    way. Resolution policy:

    1. If ``part_cls.master`` is set and equals the user-supplied
       master class, return ``master_heading.primary_key`` as the
       link-field tuple.
    2. If ``part_cls.master`` is set but disagrees, raise
       ``_MergeLinkUndecidable``: the user named the wrong master,
       and silently using their pick would defeat the structural
       check.
    3. If ``part_cls.master`` is absent, refuse with
       ``_MergeLinkUndecidable`` rather than fall back to a shared-PK
       heuristic. The plan explicitly excluded the
       single-shared-PK-name case as a false-positive risk for
       custom/lab classes (see docs/plans/db-graph-impl-plan.md
       merge-master section); when in doubt, force the user to
       configure ``master`` on the Part. ``heading.foreign_keys``
       inspection is intentionally NOT used because the shape varies
       by DataJoint version.

    Raises ``_MergeLinkUndecidable`` (exit 3 ambiguous-shaped payload)
    in cases 2 and 3. The hint includes a fix suggestion so an LLM
    can act on it without re-reading source.

    ``part_heading`` is unused today (kept in the signature for the
    future heading.foreign_keys path).
    """
    declared_master = getattr(part_cls, "master", None)
    if declared_master is None:
        raise _MergeLinkUndecidable(
            "part class has no `.master` attribute. Spyglass Part "
            "tables and lab/custom Parts that wrap Spyglass merges "
            "should set `master = <MasterClass>` on the Part class "
            "(DataJoint does this automatically when the Part is a "
            "nested class of the master). If this is genuinely not a "
            "DataJoint Part, do not use --merge-master/--part — use "
            "--class with a direct restriction instead."
        )
    if declared_master is master_cls:
        return tuple(master_heading.primary_key)
    master_name = getattr(master_cls, "__name__", str(master_cls))
    declared_name = getattr(
        declared_master, "__name__", str(declared_master)
    )
    raise _MergeLinkUndecidable(
        f"part.master ({declared_name!r}) disagrees with "
        f"--merge-master ({master_name!r}); the user named the "
        "wrong master for this part. Use --merge-master with the "
        f"class the part actually points to ({declared_name!r})."
    )


class _MergeLinkUndecidable(Exception):
    """Master / part link cannot be identified unambiguously.

    Maps to exit 3 (ambiguous family). Distinct from ``_AmbiguousClass``
    because no source-index records are involved — the ambiguity is
    structural in the DataJoint metadata.
    """

    exit_code: int = EXIT_AMBIGUOUS

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _emit_merge_link_undecidable(
    *,
    args: argparse.Namespace,
    timer: _Timer,
    master: _Resolved | None,
    part: _Resolved | None,
    exc: _MergeLinkUndecidable,
    src_root: Path | None,
) -> int:
    """Emit an ambiguous-shaped payload for a merge-link failure, exit 3."""
    payload = _stamp_envelope("ambiguous", source_root=src_root)
    payload["db"] = _build_db_envelope()
    query: dict[str, object] = {"class": args.merge_master or args.class_name}
    if master is not None:
        query["merge_master_resolved"] = f"{master.module}.{master.qualname}"
    if part is not None:
        query["part_resolved"] = f"{part.module}.{part.qualname}"
    payload["query"] = query
    # Empty candidates list — the ambiguity is structural, not
    # source-index ambiguity. The hint carries the actionable info.
    payload["candidates"] = []
    payload["hint"] = exc.message
    payload["timings_ms"] = timer.finalize()
    print(json.dumps(payload))
    return EXIT_AMBIGUOUS


def _cmd_find_instance_merge(
    args: argparse.Namespace,
    *,
    restriction: dict,
    fetch_fields: list[str],
    src_root_used: Path | None,
    timer: _Timer,
) -> int:
    """Merge-aware find-instance: ``--merge-master MASTER --part PART``.

    Closes the silent-wrong-count footgun structurally: restrictions
    are applied to the part (whose heading carries the part-only
    fields the user wants to filter on), the part-master link is
    identified via DataJoint's structural metadata, and the master is
    queried by the resolved key set rather than by the user's keys
    directly. ``query.restriction`` echoes the user's keys verbatim;
    the ``merge`` block records which class actually saw them.

    Failure modes:

    * Either class fails to resolve → kind=ambiguous / not_found /
      not_a_table / db_error, exit 3 / 4 / 4 / 5 (Batch B paths).
    * Restriction names a field absent from the part heading →
      kind=invalid_query / error.kind=unknown_field, exit 2. This is
      the eval #50 silent-wrong-count footgun.
    * part.master disagrees with --merge-master → kind=ambiguous with
      a structural hint, exit 3.
    * No structural link identifiable → same.
    """
    timer.mark("resolve")
    try:
        master = resolve_class(
            args.merge_master, src=args.src, imports=tuple(args.imports)
        )
        part = resolve_class(
            args.part, src=args.src, imports=tuple(args.imports)
        )
    except _AmbiguousClass as exc:
        return _emit_ambiguous(
            args=args, timer=timer, exc=exc, src_root=src_root_used
        )
    except _NotADataJointTable as exc:
        return _emit_not_a_table(
            args=args, timer=timer, exc=exc, src_root=src_root_used
        )
    except _DataJointUnavailable as exc:
        return _emit_db_error(
            args=args,
            timer=timer,
            error_kind="datajoint_import",
            message=f"DataJoint is not importable: {exc.original}",
            src_root=src_root_used,
        )
    except _ClassNotFound as exc:
        return _emit_not_found(
            args=args, timer=timer, exc=exc, src_root=src_root_used
        )

    timer.mark("heading")
    try:
        master_callable = master.cls
        part_callable = part.cls
        master_rel = master_callable()  # ty: ignore[call-non-callable]
        part_rel = part_callable()  # ty: ignore[call-non-callable]
        master_heading = master_rel.heading
        part_heading = part_rel.heading
        part_heading_names: tuple[str, ...] = tuple(part_heading.names)
        part_heading_attrs = dict(part_heading.attributes)
    except Exception as exc:
        return _emit_db_error(
            args=args,
            timer=timer,
            error_kind=_classify_dj_error(exc),
            message=_scrub_secrets(str(exc)),
            src_root=src_root_used,
            resolved=part,
        )

    # Validate restriction against the PART heading. This is the merge
    # algorithm's central discipline: every user key must be a real
    # part-heading attribute. Restrictions on master-only fields are
    # caught here, not silently applied to the master and lost.
    try:
        _validate_restriction_fields(restriction, part_heading_names)
        _validate_blob_restrictions(restriction, part_heading_attrs)
        _validate_fetch_fields(fetch_fields, tuple(master_heading.names))
    except _InvalidQuery as exc:
        return _emit_invalid_query(
            args=args,
            timer=timer,
            resolved=part,
            exc=exc,
            src_root=src_root_used,
        )

    # Identify the part→master link.
    try:
        master_key_fields = _identify_master_key_fields(
            part.cls,
            master.cls,
            part_heading,
            master_heading,
        )
    except _MergeLinkUndecidable as exc:
        return _emit_merge_link_undecidable(
            args=args, timer=timer, master=master, part=part,
            exc=exc, src_root=src_root_used,
        )

    timer.mark("query")
    try:
        restricted_part = part_rel & restriction if restriction else part_rel
        # Fetch master-key tuples from the restricted part to detect truncation.
        fetched_master_keys = restricted_part.fetch(
            *master_key_fields, as_dict=True, limit=args.limit + 1
        )
        truncated = len(fetched_master_keys) > args.limit
        fetched_master_keys = fetched_master_keys[: args.limit]
        master_keys_for_restrict = [
            {k: r[k] for k in master_key_fields} for r in fetched_master_keys
        ]
        if master_keys_for_restrict:
            master_restricted = master_rel & master_keys_for_restrict
            count = len(master_restricted)
            if not args.count:
                fetched_rows = master_restricted.fetch(
                    *fetch_fields, as_dict=True, limit=args.limit + 1
                )
                truncated = truncated or (len(fetched_rows) > args.limit)
                fetched_rows = fetched_rows[: args.limit]
            else:
                fetched_rows = []
        else:
            count = 0
            fetched_rows = []
    except _InvalidQuery as exc:
        return _emit_invalid_query(
            args=args, timer=timer, resolved=part,
            exc=exc, src_root=src_root_used,
        )
    except Exception as exc:
        return _emit_db_error(
            args=args,
            timer=timer,
            error_kind=_classify_dj_error(exc),
            message=_scrub_secrets(str(exc)),
            src_root=src_root_used,
            resolved=part,
        )

    timer.mark("serialize")
    serialized_rows = [
        {k: _safe_serialize_value(v) for k, v in row.items()}
        for row in fetched_rows
    ]
    serialized_merge_ids = [
        {k: _safe_serialize_value(v) for k, v in r.items()}
        for r in fetched_master_keys
    ]

    payload = _stamp_envelope(
        "merge", source_root=master.src_root or part.src_root
    )
    payload["db"] = _build_db_envelope()
    payload["query"] = {
        "class": args.merge_master,
        "merge_master_resolved": f"{master.module}.{master.qualname}",
        "part_resolved": f"{part.module}.{part.qualname}",
        "restriction": restriction,
        "fields": fetch_fields,
        "mode": "count" if args.count else "rows",
    }
    payload["merge"] = {
        "master": args.merge_master,
        "part": args.part,
        "restriction_applied_to": "part",
        "master_key_fields": list(master_key_fields),
        "merge_ids": serialized_merge_ids,
    }
    payload["count"] = count
    payload["limit"] = args.limit
    payload["truncated"] = truncated
    payload["incomplete"] = False
    payload["timings_ms"] = timer.finalize()
    payload["rows"] = serialized_rows

    print(json.dumps(payload))
    if count == 0 and args.fail_on_empty:
        return EXIT_EMPTY
    return EXIT_OK


# ---------------------------------------------------------------------------
# Subcommand: find-instance (Batch C — basic restriction + fetch + count)
# ---------------------------------------------------------------------------


def cmd_find_instance(args: argparse.Namespace) -> int:
    """Resolve the class, validate the query, fetch bounded rows.

    Batch C scope (per docs/plans/db-graph-impl-plan.md):

    * Scalar ``--key`` restrictions, JSON-typed ``--key-json`` restrictions.
    * Heading-based field validation (refuses unknown / blob restrictions).
    * ``--count`` returns count-only payload with ``rows: []``.
    * Default fetch returns up to ``--limit`` rows; ``truncated`` set when
      the relation has more rows than the limit.
    * Per-field safe serialization for DataJoint blob / NumPy / UUID /
      datetime values.
    * Empty result is exit ``0`` with ``count: 0`` (the canonical scientific
      answer); ``--fail-on-empty`` opts into exit ``7``.

    Direct-relation discipline: this code path never references
    ``RestrGraph`` or ``TableChain``. Source-text grep over db_graph.py
    confirms (``tests/test_db_graph.py`` pins this).

    Failure modes (stable from Batch B): ambiguous=3, not_found=4,
    not_a_table=4, datajoint_import=5. New in Batch C: invalid_query=2
    for malformed restrictions / unknown fields.
    """
    timer = _Timer()

    # Step 0: parse user input BEFORE anything that imports Spyglass or
    # DataJoint. Malformed --key / --key-json / --fields are detected
    # synchronously, with no cold Spyglass init cost — the entire
    # invalid_query path stays under ~10 ms even on a slow interpreter.
    # ``_select_src_root`` is intentionally NOT called here because its
    # installed-package fallback does ``import spyglass``; resolving it
    # eagerly would defeat the parser-fast-path discipline.
    try:
        restriction = _parse_key_args(args.key, args.key_json)
        fetch_fields = _parse_fields_arg(args.fields)
    except _InvalidQuery as exc:
        return _emit_invalid_query(
            args=args,
            timer=timer,
            resolved=None,
            exc=exc,
            src_root=None,
        )

    # Step 1: now resolve src_root (may import spyglass for the
    # installed-package fallback) and resolve the class.
    src_root_used = _select_src_root(args.src)

    # Merge-aware lookup branches off here. The merge handler shares
    # the parser-fast-path above and the src_root resolution; from
    # this point it has its own resolution + heading + restriction
    # logic, returning a kind="merge" payload instead of "find-instance".
    if args.merge_master:
        return _cmd_find_instance_merge(
            args,
            restriction=restriction,
            fetch_fields=fetch_fields,
            src_root_used=src_root_used,
            timer=timer,
        )

    timer.mark("resolve")
    try:
        resolved = resolve_class(
            args.class_name, src=args.src, imports=tuple(args.imports)
        )
    except _AmbiguousClass as exc:
        return _emit_ambiguous(
            args=args, timer=timer, exc=exc, src_root=src_root_used
        )
    except _NotADataJointTable as exc:
        return _emit_not_a_table(
            args=args, timer=timer, exc=exc, src_root=src_root_used
        )
    except _DataJointUnavailable as exc:
        return _emit_db_error(
            args=args,
            timer=timer,
            error_kind="datajoint_import",
            message=f"DataJoint is not importable: {exc.original}",
            src_root=src_root_used,
        )
    except _ClassNotFound as exc:
        return _emit_not_found(
            args=args, timer=timer, exc=exc, src_root=src_root_used
        )

    timer.mark("heading")

    # Step 2: build the relation and read its heading. Both can raise
    # DataJoint connection / auth / schema errors; surface them as
    # db_error with the `error.kind` discriminator that ``info --json``
    # documents.
    try:
        # `_Resolved.cls` is annotated `object` (the lazy-import discipline
        # forbids importing UserTable at type-check time). Runtime
        # narrowing via `_is_datajoint_user_table` already proved this is
        # callable; the cast satisfies the type checker without changing
        # behavior.
        cls_callable = resolved.cls
        rel = cls_callable()  # ty: ignore[call-non-callable]
        heading = rel.heading
        heading_names: tuple[str, ...] = tuple(heading.names)
        heading_attributes = dict(heading.attributes)
    except Exception as exc:
        return _emit_db_error(
            args=args,
            timer=timer,
            error_kind=_classify_dj_error(exc),
            message=_scrub_secrets(str(exc)),
            src_root=src_root_used,
            resolved=resolved,
        )

    # Step 3: validate fields against the runtime heading. Both
    # restriction keys and fetch fields are checked here; either being
    # malformed is exit 2 invalid_query.
    try:
        _validate_restriction_fields(restriction, heading_names)
        _validate_blob_restrictions(restriction, heading_attributes)
        _validate_fetch_fields(fetch_fields, heading_names)
    except _InvalidQuery as exc:
        return _emit_invalid_query(
            args=args,
            timer=timer,
            resolved=resolved,
            exc=exc,
            src_root=src_root_used,
        )

    # Step 4: apply restriction and run the query.
    timer.mark("query")
    try:
        restricted = rel & restriction if restriction else rel
        count = len(restricted)
        rows: list[dict] = []
        truncated = False
        if not args.count:
            # Fetch limit + 1 so we can detect truncation without a
            # second round-trip.
            fetched = restricted.fetch(
                *fetch_fields, as_dict=True, limit=args.limit + 1
            )
            truncated = len(fetched) > args.limit
            fetched = fetched[: args.limit]
            timer.mark("serialize")
            rows = [
                {k: _safe_serialize_value(v) for k, v in row.items()}
                for row in fetched
            ]
    except _InvalidQuery as exc:
        return _emit_invalid_query(
            args=args,
            timer=timer,
            resolved=resolved,
            exc=exc,
            src_root=src_root_used,
        )
    except Exception as exc:
        return _emit_db_error(
            args=args,
            timer=timer,
            error_kind=_classify_dj_error(exc),
            message=_scrub_secrets(str(exc)),
            src_root=src_root_used,
            resolved=resolved,
        )

    # Step 5: build the success payload. Shape and field order match
    # ``PAYLOAD_ENVELOPES["find-instance"]``; the Batch A schema-envelope
    # fixture pins this so Batch C cannot drift it.
    payload = _stamp_envelope("find-instance", source_root=resolved.src_root)
    payload["db"] = _build_db_envelope()
    payload["query"] = {
        "class": args.class_name,
        "resolved_class": f"{resolved.module}.{resolved.qualname}",
        "module": resolved.module,
        "qualname": resolved.qualname,
        "resolution_source": resolved.source,
        "restriction": restriction,
        "fields": fetch_fields,
        "mode": "count" if args.count else "rows",
    }
    payload["count"] = count
    payload["limit"] = args.limit
    payload["truncated"] = truncated
    # ``incomplete`` is reserved for set-op fallbacks (Batch E); a basic
    # find-instance is always complete within --limit.
    payload["incomplete"] = False
    payload["timings_ms"] = timer.finalize()
    payload["rows"] = rows

    print(json.dumps(payload))
    if count == 0 and args.fail_on_empty:
        return EXIT_EMPTY
    return EXIT_OK


def _classify_dj_error(exc: BaseException) -> str:
    """Map a DataJoint / pymysql exception to a stable ``error.kind``.

    The discriminator promised by ``info --json``: ``connection`` /
    ``auth`` / ``schema`` / ``datajoint_import``. Falls back to a
    generic ``runtime`` for anything we cannot classify.

    Auth-message check goes BEFORE the class-name check because pymysql
    raises ``OperationalError("(1045, 'Access denied...')")`` for
    auth failures — classifying that as ``connection`` would point an
    LLM at the wrong recovery (network / VPN troubleshooting instead
    of credential review). Message-text wins on the auth path; the
    class-name list is the second-pass guard for true network failures.
    """
    name = type(exc).__name__
    msg = str(exc).lower()
    if name == "AccessError" or "access denied" in msg:
        return "auth"
    if name in ("LostConnectionError", "OperationalError", "InterfaceError"):
        return "connection"
    if "schema" in msg or "table" in msg:
        return "schema"
    return "runtime"


def _scrub_secrets(text: str) -> str:
    """Best-effort redaction of credentials in DataJoint error messages.

    Plan: never print raw passwords, connection URLs with credentials,
    or full tracebacks. DataJoint error text occasionally embeds parts
    of the connection string (especially ``OperationalError`` from
    pymysql). Replace anything that looks like ``user:password@host``.
    """
    import re

    # Replace `name:secret@host` with `name:***@host`.
    text = re.sub(r"([\w\-.]+):[^@\s]+@", r"\1:***@", text)
    # Replace bare-password mentions.
    text = re.sub(
        r"(password|secret|token|credential|api_key)[^\s]*[:=]\s*\S+",
        r"\1=***",
        text,
        flags=re.IGNORECASE,
    )
    return text


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
        # One-of: --class XOR (--merge-master + --part). Merge mode names
        # both classes via --merge-master/--part, so --class is optional;
        # non-merge queries require --class.
        if not args.merge_master and not args.class_name:
            parser.error(
                "--class is required (or use --merge-master MASTER --part PART "
                "for merge-aware lookup)"
            )
        # In merge mode, ``args.class_name`` is what shared emitters
        # print as ``query.class``. Default it to merge_master so error
        # payloads always carry a non-null class identifier even when
        # the user did not pass --class.
        if args.merge_master and not args.class_name:
            args.class_name = args.merge_master
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
        # Batch E (set ops + grouped counts) is not yet implemented;
        # reject the flags loudly until the implementation lands.
        # Argparse exposes the flags so ``info --json`` can advertise
        # the planned surface, but accepting them silently and
        # falling through to a basic find-instance call would emit a
        # plausible-looking but wrong payload — exactly the kind of
        # silent-no-op footgun this tool exists to close.
        unimplemented_flags = []
        if args.intersect:
            unimplemented_flags.append(f"--intersect {args.intersect}")
        if args.except_class:
            unimplemented_flags.append(f"--except {args.except_class}")
        if args.join:
            unimplemented_flags.append(f"--join {args.join}")
        if args.group_by:
            unimplemented_flags.append(f"--group-by {args.group_by}")
        if args.group_by_table:
            unimplemented_flags.append(
                f"--group-by-table {args.group_by_table}"
            )
        if args.count_distinct:
            unimplemented_flags.append(
                f"--count-distinct {args.count_distinct}"
            )
        if unimplemented_flags:
            parser.error(
                "set-op and grouped-count flags are not yet implemented "
                "(Batch E per docs/plans/db-graph-impl-plan.md): "
                f"{', '.join(unimplemented_flags)}. The flags are "
                "advertised in `info --json` so an LLM can plan for "
                "Batch E, but accepting them silently in this build "
                "would emit a plausible-looking wrong-shape payload."
            )
        return cmd_find_instance(args)
    # Argparse's `required=True` on the subparsers makes this unreachable
    # at runtime; `parser.error` raises SystemExit, so no return is needed.
    parser.error(f"unknown subcommand {args.cmd!r}")


if __name__ == "__main__":
    sys.exit(main())
