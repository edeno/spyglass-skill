#!/usr/bin/env python3
"""Source-only code-graph traversal for Spyglass.

Lifecycle
---------

Prototype here. Upstream candidate: ``spyglass.utils.code_graph`` (or
``spyglass.cli.code_graph``) — Spyglass has no equivalent today. The
three subcommands shipped here (``describe`` / ``path`` /
``find-method``) form a self-contained CLI family. DB-resolved
variants (live ``Table.descendants()`` / ``dj.Diagram``) are out of
scope for this source-only tool — the user's analysis session is the
authoritative source for those. When upstream merges, retire the
local module and update ``feedback_loops.md`` to route at
``python -m spyglass.code_graph``. The companion `_index.py` migrates
together; see its own Lifecycle paragraph.

Three subcommands, all consuming ``_index.py``:

* ``code_graph.py describe <Class>`` — node view (bases, methods,
  schema fields, FK edges).
* ``code_graph.py path (--to A B | --up CLASS | --down CLASS)`` — FK
  edge traversal. ``--to`` BFS bridges master-part containment in
  both directions; ``--up`` / ``--down`` walk the directional graph
  only.
* ``code_graph.py find-method <method-name>`` — reverse method index
  ("which classes define METHOD_NAME at body level?") plus mixin
  inherited-availability summary.

What ``path`` catches well
--------------------------

* The FK chain between two classes named explicitly. Walks the static
  parent map built from ``definition`` strings; bridges master-part
  containment so cascade chains through merge masters (LFPV1 →
  LFPOutput.LFPV1 → LFPOutput → LFPBandSelection → LFPBandV1) are
  findable rather than dead-ending at the master.
* Every hop carries ``file:line`` plus an ``evidence`` string (the
  source line that justified the hop) so the agent has a citation per
  edge, not a paraphrase.
* Multi-file class names ("BodyPart" — defined 6+ times in the position
  pipeline) surface as exit-3 ambiguity rather than silent first-match.

What ``path`` does NOT catch
----------------------------

1. **Mixin / base-class FKs.** ``SpyglassMixin``, ``_Merge``, etc. don't
   add FKs but DO add inherited methods. ``path`` only walks FKs, so
   mixin-only relationships are invisible. Read the base class file
   when method-availability matters; ``code_graph.py describe`` is the
   right tool.
2. **Cross-pipeline merges via dynamic part registration.** Static AST
   scan sees only what's in the source tree at scan time; runtime
   ``setattr``-style part registration (rare in Spyglass) is invisible.
3. **Runtime-overridden FKs.** A table whose ``key_source`` is overridden
   in Python rather than declared in ``definition`` won't be reflected.
4. **Path ambiguity.** When multiple FK paths exist between two classes,
   the script prints the shortest. Read the source for full topology.
5. **Cross-class redesigns.** v0 ``Curation`` is not the same node as v1
   ``CurationV1``; the graph won't link them. Read both class declarations
   directly when comparing across versions.
6. **Inheritance in ``definition``.** Classes that inherit a parent's
   ``definition`` via Python class inheritance (rather than re-declaring
   FKs) are invisible — ``_extract_definition`` returns ``None``.
7. **Expression-form refs.** DataJoint resolves ``->`` ref-tables via
   Python ``eval()`` against the import namespace; static parse handles
   ``Name`` / ``Name.Name`` / ``Name.proj(...)`` only. Aliased imports
   and module-qualified refs are unresolvable from source alone.
8. **Custom tables outside ``$SPYGLASS_SRC``.** Lab-member-defined or
   external-package-defined tables that subclass Spyglass tables (or
   register parts on Spyglass merge masters) are invisible to this
   tool. The scan only walks ``$SPYGLASS_SRC/spyglass/``; tables in a
   colleague's analysis repo, an institute fork, or a downstream pip
   package are not in the index. The DB graph (the user's live DataJoint
   session) is the authoritative source for these *when the user has
   imported their analysis repo in the current Python session* — DJ's
   ``Table.descendants()`` and ``dj.Diagram`` only know about classes
   that have been imported, so a table defined in code that hasn't
   been ``import``-ed in this session is invisible to the DB graph too.
   When the agent's question involves a custom table name and
   ``code_graph.py`` reports ``not_found``, the right fallback is
   "ask the user to import their custom-table module, then query
   ``Table.descendants()``." Don't conclude the table doesn't exist;
   conclude that this tool can't see it from source.

Exit codes
----------

* ``0`` — happy path (path found, or "no path between A and B" — both
  are well-formed answers to a well-formed query).
* ``2`` — usage error (argparse default).
* ``3`` — unresolved ambiguity. Output (human or JSON) lists candidates;
  re-run with ``--from-file`` / ``--to-file`` / ``--file``.
* ``4`` — class not found in the index.
* ``5`` — traversal needed a heuristic to disambiguate a same-qualname
  collision (multiple records with the same qualname; same-package
  preference picked one). Only emitted when the user opts in via
  ``--fail-on-heuristic``; otherwise the heuristic resolution is
  reported in the JSON payload's top-level ``warnings`` block.
  Distinct from exit ``3`` (which means the user-supplied input was
  ambiguous, not the internal traversal).
"""

from __future__ import annotations

import argparse
import difflib
import json
import sys
from collections import deque
from pathlib import Path

# Co-located helper module; same directory as this script.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _index  # noqa: E402

SCHEMA_VERSION = _index.SCHEMA_VERSION
EXIT_OK = 0
EXIT_USAGE = 2
EXIT_AMBIGUOUS = 3
EXIT_NOT_FOUND = 4
# A traversal needed a heuristic to disambiguate a same-qualname collision
# (multiple records with the same qualname; same-package preference picked
# one). Distinct from EXIT_AMBIGUOUS (which is "user-supplied input
# ambiguous, please re-run with --file"). Only emitted when the user
# opts in via ``--fail-on-heuristic``; otherwise the heuristic resolution
# is reported in the payload's top-level ``warnings`` block instead.
EXIT_HEURISTIC = 5

# Top-level provenance fields stamped on every JSON payload. ``graph``
# distinguishes this from a future DB-truth payload; ``authority`` is
# the agent-readable warning that this is source-only (not runtime/DB).
GRAPH_KIND = "code"
AUTHORITY = "source-only"


def _record_id(rec: _index.ClassRecord) -> str:
    """Stable identifier for a record across invocations.

    Format: ``<file>:<line>:<qualname>`` — the file+line uniquely
    identifies a class declaration, and including the qualname keeps
    the id self-describing for human readers and grep targets.
    """
    return f"{rec.file}:{rec.line}:{rec.qualname}"


# Enumeration of `node_kind` values the agent can branch on. Order
# is priority: a record matching multiple categories is labeled by
# the first match. ``info`` subcommand dumps this enum so consumers
# don't have to memorize the strings.
NODE_KIND_VALUES = (
    "merge_master",   # subclasses _Merge / Merge; lives at the top of a merge.
    "merge_part",     # nested part whose master is a merge_master.
    "nested_master",  # not a merge, but has nested parts (e.g. a Group).
    "nested_part",    # nested part whose master is NOT a merge.
    "lookup",         # dj.Lookup tier.
    "manual",         # dj.Manual tier.
    "computed",       # dj.Computed tier.
    "imported",       # dj.Imported tier.
    "table",          # has a `definition` but no recognizable tier or shape.
    "unknown",        # not derivable from index (placeholder / unscanned class).
)

# Enumeration of `kind` values on FKEdge / hop / walk-edge entries.
# Surfaced via `info --json` so the agent has a single source of truth.
FK_EDGE_KIND_VALUES = ("fk", "proj", "merge_part", "nested_part")

# Enumeration of `ownership_kind` values on `find-method` entries.
# Defined here so `cmd_info` and `_ownership_kind` share the same vocabulary.
OWNERSHIP_KIND_VALUES = ("body", "mixin", "inherits_mixin", "merge")


def _node_kind(idx: _index.ClassIndex, rec: _index.ClassRecord) -> str:
    """Classify a record for agent-readable routing.

    Lets the LLM branch on shape ("is this a merge master? a part?
    a lookup?") without re-deriving from `bases` / `master` / `tier`.
    The order matches NODE_KIND_VALUES (first match wins).
    """
    if _is_merge_master(rec):
        return "merge_master"
    if rec.master is not None:
        master_rec = _resolve_target_record(idx, rec.master, anchor_rec=rec)
        if master_rec is not None and _is_merge_master(master_rec):
            return "merge_part"
        return "nested_part"
    if _parts_of_master(idx, rec):
        return "nested_master"
    if rec.tier in ("Lookup", "Manual", "Computed", "Imported"):
        return rec.tier.lower()
    return "table"


class _HeuristicLog:
    """Accumulates same-qualname heuristic resolutions made during a
    single CLI invocation.

    ``_resolve_target_record`` calls ``record(...)`` whenever it picks
    one record from multiple candidates sharing a qualname (same-package
    preference). The log is then attached to the payload as a top-level
    ``warnings`` array so consumers (and ``--fail-on-heuristic``) can
    see exactly which calls used a heuristic.

    De-duplicated per ``(qualname, anchor_file, selected_id)`` tuple to
    keep the warnings array bounded for walks that traverse the same
    intermediate many times.
    """

    def __init__(self) -> None:
        self._seen: set[tuple[str, str, str]] = set()
        self.entries: list[dict] = []

    def record(
        self,
        qualname: str,
        anchor_rec: _index.ClassRecord,
        candidates: list[_index.ClassRecord],
        selected: _index.ClassRecord,
    ) -> None:
        key = (qualname, anchor_rec.file, _record_id(selected))
        if key in self._seen:
            return
        self._seen.add(key)
        self.entries.append({
            "kind": "heuristic_resolution",
            "qualname": qualname,
            "anchor": _record_id(anchor_rec),
            "candidates": [_record_id(c) for c in candidates],
            "selected": _record_id(selected),
            "reason": "same-package preference (longest shared file-path prefix to anchor)",
        })

    def __bool__(self) -> bool:
        return bool(self.entries)


def _provenance_fields(source_root: Path) -> dict:
    """Top-level provenance stamp shared by every JSON payload."""
    return {
        "graph": GRAPH_KIND,
        "authority": AUTHORITY,
        "source_root": str(source_root),
    }


def _stamp_payload(
    payload: dict,
    source_root: Path,
    log: _HeuristicLog | None = None,
) -> dict:
    """Add top-level provenance + heuristic warnings to a payload.

    Stamped at emit time so every payload (path, walk, describe,
    find-method, ambiguous, not_found, no_path) carries consistent
    provenance fields without each builder needing to thread them.
    The ``warnings`` field is only added when the log has entries —
    a clean payload stays clean.
    """
    payload.update(_provenance_fields(source_root))
    if log is not None and log:
        payload["warnings"] = list(log.entries)
    return payload


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(__doc__ or "").split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="See module docstring for full usage and limits.",
    )
    parser.add_argument(
        "--src",
        default=None,
        help="Path to the directory containing the `spyglass/` package "
        "(overrides $SPYGLASS_SRC).",
    )

    sub = parser.add_subparsers(dest="cmd", required=True)

    # path
    p_path = sub.add_parser(
        "path",
        help="FK edge traversal: --to A B | --up CLASS | --down CLASS",
        description="FK path-finder. Walks `definition`-derived edges plus "
        "master-part containment so merge-master hops are surfaced "
        "explicitly rather than elided.",
    )
    g = p_path.add_mutually_exclusive_group(required=True)
    g.add_argument(
        "--to", nargs=2, metavar=("FROM", "TO"),
        help="Find FK path between two classes.",
    )
    g.add_argument("--up", metavar="CLASS", help="Enumerate all upstream ancestors.")
    g.add_argument("--down", metavar="CLASS", help="Enumerate all downstream descendants.")
    p_path.add_argument(
        "--from-file", default=None,
        help="Disambiguate FROM in --to mode (path relative to --src).",
    )
    p_path.add_argument(
        "--to-file", default=None,
        help="Disambiguate TO in --to mode (path relative to --src).",
    )
    p_path.add_argument(
        "--file", default=None,
        help="Disambiguate the single class in --up / --down mode.",
    )
    def _nonneg_int(s: str) -> int:
        n = int(s)
        if n < 0:
            raise argparse.ArgumentTypeError(
                f"--max-depth must be ≥ 0, got {n} "
                f"(0 = src must equal dst; 12 is the default)"
            )
        return n

    p_path.add_argument(
        "--max-depth", type=_nonneg_int, default=12,
        help="Cap path length / walk depth (default 12; longest known real "
        "Spyglass chain is ~8 hops). Must be ≥ 0; 0 means src must equal dst.",
    )
    p_path.add_argument(
        "--json", action="store_true",
        help="Emit machine-readable JSON instead of human-readable arrows / tree.",
    )
    p_path.add_argument(
        "--fail-on-heuristic", action="store_true",
        help="Exit %(prog)s with code 5 if any same-qualname collision was "
        "resolved by the same-package heuristic during traversal. Use this "
        "in validators or agents that should refuse to guess; rerun with "
        "--from-file/--to-file/--file to disambiguate explicitly. The "
        "resolution(s) are also reported in the JSON 'warnings' block.",
    )

    # describe — node view + structured fields + mixin resolution.
    p_describe = sub.add_parser(
        "describe",
        help="Node view: tier, bases, structured PK / non-PK / FK / renames, "
        "body methods, methods inherited from registered Spyglass mixins.",
    )
    p_describe.add_argument("class_name", metavar="CLASS_NAME")
    p_describe.add_argument(
        "--file", default=None,
        help="Disambiguate ambiguous names (path relative to --src).",
    )
    p_describe.add_argument(
        "--no-inherited", action="store_true",
        help="Suppress inherited-methods sections.",
    )
    p_describe.add_argument(
        "--json", action="store_true",
        help="Emit machine-readable JSON.",
    )

    # find-method — reverse method index ("where is method Y defined?").
    p_find = sub.add_parser(
        "find-method",
        help="Reverse method index: list every class that defines METHOD_NAME "
        "at body level, plus mixin inherited-availability summary.",
    )
    p_find.add_argument("method_name", metavar="METHOD_NAME")
    # No --include-private flag on any subcommand. The shared scan in
    # _index.py filters private methods (except `__lshift__` /
    # `__rshift__`, the DataJoint operator overloads kept by
    # `_KEPT_DUNDERS`) before they land in `ClassRecord.methods`. The
    # scan is `lru_cache`d, so a CLI flag that "re-scanned with
    # privates included" would invalidate the cached index for every
    # other consumer in the same process — a tradeoff with no
    # documented workflow on the other side. If a future need
    # genuinely requires private methods, change `_extract_methods` to
    # keep them and filter at the consumer site instead.
    p_find.add_argument(
        "--no-inherited", action="store_true",
        help="Suppress the inherited-via summary "
        "(default: shown when the owner is a registered mixin).",
    )
    p_find.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")

    # info — machine-readable contract dump (subcommand purposes, exit
    # codes, enums). The agent can call this once to learn the tool's
    # contract instead of consulting prose docs.
    p_info = sub.add_parser(
        "info",
        help="Dump tool contract: subcommand purposes, exit codes, "
        "node_kind / kind / ownership_kind enums, warnings vocabulary. "
        "Use this for machine-readable introspection.",
    )
    p_info.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    return parser


# ---------------------------------------------------------------------------
# Class resolution (multi-file disambiguation)
# ---------------------------------------------------------------------------


def _resolve_class(
    name: str,
    idx: _index.ClassIndex,
    file_hint: str | None = None,
) -> tuple[_index.ClassRecord | None, str | None, list[_index.ClassRecord]]:
    """Look up a class by short name, optionally narrowed by file hint.

    Returns ``(record, error_kind, candidates)``:

    * ``(record, None, [])`` — unique match.
    * ``(None, "not_found", [])`` — name not in the index.
    * ``(None, "ambiguous", candidates)`` — multiple matches; caller
      formats the candidate list for exit-3 output.
    """
    # Accept dotted-qualname input (e.g., "LFPOutput.LFPV1",
    # "LFPBandSelection.LFPBandElectrode") by splitting on the last dot
    # and filtering the index by qualname. The index keys on short names
    # only, so a raw lookup of the dotted form returns nothing.
    if "." in name:
        short = name.rsplit(".", 1)[-1]
        raw = [r for r in idx.get(short, ()) if r.qualname == name]
    else:
        raw = list(idx.get(name, ()))
    if not raw:
        return None, "not_found", []
    # Filter out placeholder/shadow records (e.g. `common/custom_nwbfile.py`'s
    # `AnalysisNwbfile` shadow with a "managed by SpyglassAnalysis"
    # sentinel definition) before counting candidates. The schema-side
    # resolution does the same via `idx.schema_records`; without filtering
    # here the path/describe CLIs would surface a real-vs-shadow pair as
    # exit-3 ambiguous despite there being only one real record.
    raw = [r for r in raw if not _index.is_placeholder(r)]
    if not raw:
        return None, "not_found", []
    if file_hint:
        narrowed = [
            r for r in raw
            if r.file == file_hint or r.file.endswith(file_hint.lstrip("/"))
        ]
        if len(narrowed) == 1:
            return narrowed[0], None, []
        if not narrowed:
            return None, "ambiguous", raw  # hint missed; show all candidates.
        return None, "ambiguous", narrowed
    if len(raw) == 1:
        return raw[0], None, []
    # For undotted names: prefer top-level (qualname == name) when uniquely
    # identified. For dotted names this is a no-op because the dotted-branch
    # filter already required `qualname == name`, so every candidate passes.
    top_level = [r for r in raw if r.qualname == name]
    if len(top_level) == 1:
        return top_level[0], None, []
    return None, "ambiguous", raw


# ---------------------------------------------------------------------------
# Graph construction (parent / child maps + master-part bridge for cascades)
# ---------------------------------------------------------------------------


def _path_graph(idx: _index.ClassIndex) -> dict[str, list[str]]:
    """Return ``bfs_parent_map`` for ``path --to`` BFS-from-dst.

    Master-part containment is structural, not FK — DataJoint links
    them by sharing primary keys. For BFS-from-dst, master-part edges
    are BIDIRECTIONAL: BFS from a downstream class upward toward an
    upstream merge-master must transit master-part containment from
    either direction (a part is a parent of its master via the part's
    ``-> master`` FK; a master is a parent of its part via this added
    reverse hop). Without the reverse, chains dead-end at masters,
    which have no FKs of their own.

    ``--up`` and ``--down`` walks use the record-aware traversal
    helpers (``_record_ancestors`` / ``_record_descendants``) instead
    of qualname-keyed maps — those handle v0/v1 disambiguation and
    sibling-part fan-out correctly.
    """
    parent_map = _index.parent_map(idx)
    # Add master → parts so BFS-from-dst can transit master-part
    # containment downward when needed. Apply to ALL nested parts
    # (merge masters AND non-merge containers like
    # UnitWaveformFeaturesGroup).
    for records in idx.values():
        for rec in records:
            master = rec.master
            if master is None:
                continue
            existing = parent_map.setdefault(master, [])
            if rec.qualname not in existing:
                existing.append(rec.qualname)
    # De-dup while preserving insertion order (dict preserves it since 3.7).
    for k, v in parent_map.items():
        parent_map[k] = list(dict.fromkeys(v))
    return parent_map


# ---------------------------------------------------------------------------
# BFS path-finding
# ---------------------------------------------------------------------------


def _bfs_to(
    parent_map: dict[str, list[str]],
    src_qualname: str,
    dst_qualname: str,
    max_depth: int,
) -> tuple[list[str] | None, bool]:
    """BFS from ``dst`` walking parents until ``src`` is hit.

    Returns ``(path, truncated)``: ``path`` is ``[src, ..., dst]`` if
    found within ``max_depth``, else None. ``truncated`` is True when
    the BFS hit ``max_depth`` with unexplored nodes — i.e. a longer
    path may exist; rerun with a larger ``--max-depth`` to find it.
    Algorithm: BFS from TO walking parent edges, then reverse for
    printing.
    """
    if src_qualname == dst_qualname:
        return [src_qualname], False
    queue: deque[tuple[str, list[str]]] = deque([(dst_qualname, [dst_qualname])])
    visited: set[str] = {dst_qualname}
    truncated = False
    while queue:
        cls, path = queue.popleft()
        if len(path) > max_depth + 1:
            # If this node has any unvisited parent, we could've
            # reached deeper — flag truncation honestly.
            if not truncated and any(
                p not in visited for p in parent_map.get(cls, [])
            ):
                truncated = True
            continue
        for parent in parent_map.get(cls, []):
            if parent == src_qualname:
                return list(reversed(path + [parent])), truncated
            if parent in visited:
                continue
            visited.add(parent)
            queue.append((parent, path + [parent]))
    return None, truncated


# ---------------------------------------------------------------------------
# Record-aware traversal helpers (for --up / --down walks).
#
# The qualname-keyed `_path_graph` was sufficient for `path --to` (where
# `_edge_meta` resolves the right record per hop), but mixed v0/v1 records
# in `--up`/`--down` walks: BFS visited a qualname once and walked the
# union of all same-qualname records' edges. That produced (a) wrong
# file:line for parent nodes in `--up` (first-record-wins rendering),
# (b) v0 child leakage in `--down` (e.g. `--down LFPV1` reaching v0
# `LFPBand`), and (c) sibling-part fan-out (e.g. `LFPV1 --down` cascading
# through `LFPOutput` to `LFPOutput.ImportedLFP`/`CommonLFP`).
#
# The fix: keep a record-keyed BFS for walks. FK target resolution uses
# same-package preference (longest shared file-path prefix), matching
# DataJoint's runtime import-namespace semantics. The part→master bridge
# in `--down` carries a `skip_parts` flag so masters reached via the
# bridge don't fan out to siblings.
# ---------------------------------------------------------------------------


def _shared_path_components(file_a: str, file_b: str) -> int:
    """Count of shared leading path components.

    Used to score same-package preference: ``spyglass/lfp/analysis/v1/lfp_band.py``
    matches itself with score 5; against ``spyglass/common/common_ephys.py``
    the shared prefix is just ``("spyglass",)`` so score 1.
    """
    parts_a = file_a.split("/")
    parts_b = file_b.split("/")
    score = 0
    for a, b in zip(parts_a, parts_b):
        if a != b:
            break
        score += 1
    return score


def _resolve_target_record(
    idx: _index.ClassIndex,
    qualname: str,
    anchor_rec: _index.ClassRecord,
    log: _HeuristicLog | None = None,
) -> _index.ClassRecord | None:
    """Pick the record matching ``qualname`` with longest shared package
    prefix to ``anchor_rec.file``.

    DataJoint resolves ``-> Foo`` via Python's import namespace at
    runtime, so the actual binding depends on the FK-owner's imports.
    Same-package preference is the static heuristic that matches
    runtime resolution most reliably (lab-internal pipelines tend to
    import their own package's class, not a same-named one in a
    sibling package). Tiebreaker: alphabetical file path (deterministic).

    When ``log`` is provided AND multiple candidates exist, the
    resolution is recorded so the caller can surface it as a top-level
    ``warnings`` entry. Single-candidate lookups don't log because
    they're not heuristic — there was nothing to disambiguate.
    """
    candidates = _records_for_qualname(idx, qualname)
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    selected = max(
        candidates,
        key=lambda c: (_shared_path_components(c.file, anchor_rec.file), c.file),
    )
    if log is not None:
        log.record(qualname, anchor_rec, list(candidates), selected)
    return selected


def _is_merge_master(rec: _index.ClassRecord) -> bool:
    return any(b in _index.MERGE_BASE_NAMES for b in rec.bases)


# ---------------------------------------------------------------------------
# Reverse-direction precomputed maps (FK consumers, master→parts).
#
# Both ``_resolve_consumers(target)`` and ``_parts_of_master(master)`` need
# to find records pointing at a target qualname. A naive implementation
# scans ``idx.values()`` per call — fine for one lookup, but a ``--down``
# walk visits N records and calls these helpers O(N) times, making the
# total cost O(N · |idx|). That dominated walk runtime in profiling.
#
# We precompute both maps once per ClassIndex on first use:
#   * consumers_by_qualname: target_qualname → [(child_rec, edge), ...]
#   * parts_by_master_qualname: master_qualname → [part_rec, ...]
#
# ClassIndex is unhashable (Mapping field) so we can't ``functools.cache``.
# A module-level dict keyed on ``id(idx)`` is the cleanest option:
# ``_index.scan`` is ``lru_cache(maxsize=1)`` per process, so usually only
# one entry is live; tests that call ``cache_clear`` create a new ClassIndex
# with a new ``id``, so the stale cache entry just becomes orphaned and is
# GC'd along with the old index.
# ---------------------------------------------------------------------------

_DERIVED_INDEX_CACHE: dict[
    int,
    tuple[
        dict[str, tuple[tuple[_index.ClassRecord, _index.FKEdge], ...]],
        dict[str, tuple[_index.ClassRecord, ...]],
    ],
] = {}


def _derived_indices(
    idx: _index.ClassIndex,
) -> tuple[
    dict[str, tuple[tuple[_index.ClassRecord, _index.FKEdge], ...]],
    dict[str, tuple[_index.ClassRecord, ...]],
]:
    """Return ``(consumers_by_qualname, parts_by_master_qualname)``,
    computed once per ClassIndex via a single pass over ``idx.values()``.
    """
    cached = _DERIVED_INDEX_CACHE.get(id(idx))
    if cached is not None:
        return cached
    consumers_acc: dict[str, list[tuple[_index.ClassRecord, _index.FKEdge]]] = {}
    parts_acc: dict[str, list[_index.ClassRecord]] = {}
    for records in idx.values():
        for rec in records:
            for edge in rec.fk_edges:
                consumers_acc.setdefault(edge.qualname_target, []).append((rec, edge))
            if rec.master is not None:
                parts_acc.setdefault(rec.master, []).append(rec)
    consumers = {k: tuple(v) for k, v in consumers_acc.items()}
    parts = {k: tuple(v) for k, v in parts_acc.items()}
    _DERIVED_INDEX_CACHE[id(idx)] = (consumers, parts)
    return consumers, parts


def _master_record_of(
    idx: _index.ClassIndex,
    part_rec: _index.ClassRecord,
    log: _HeuristicLog | None = None,
) -> _index.ClassRecord | None:
    """Return the master record for ``part_rec`` (None if not a part)."""
    master_qualname = part_rec.master
    if master_qualname is None:
        return None
    return _resolve_target_record(idx, master_qualname, anchor_rec=part_rec, log=log)


def _parts_of_master(
    idx: _index.ClassIndex,
    master_rec: _index.ClassRecord,
    log: _HeuristicLog | None = None,
) -> list[_index.ClassRecord]:
    """Return the records whose ``.master`` resolves to ``master_rec``."""
    _, parts_index = _derived_indices(idx)
    candidates = parts_index.get(master_rec.qualname, ())
    out: list[_index.ClassRecord] = []
    for rec in candidates:
        # `rec.master == master_rec.qualname` is guaranteed by the index
        # bucket we just looked up; we still need the same-package
        # preference check to filter v0/v1 collisions on master qualname.
        resolved = _resolve_target_record(idx, master_rec.qualname, anchor_rec=rec, log=log)
        if resolved is not None and resolved == master_rec:
            out.append(rec)
    return out


def _resolve_consumers(
    idx: _index.ClassIndex,
    target_rec: _index.ClassRecord,
    log: _HeuristicLog | None = None,
) -> list[tuple[_index.ClassRecord, _index.FKEdge]]:
    """Records whose ``fk_edges`` resolve to ``target_rec``.

    A record's FK qualname-targets ``target_rec.qualname`` AND, when
    that qualname has multiple records, same-package preference picks
    ``target_rec`` (not a same-named sibling). Filters out the v0/v1
    leakage where ``child_map[qualname]`` would naively merge both
    versions' consumers.
    """
    consumers_index, _ = _derived_indices(idx)
    out: list[tuple[_index.ClassRecord, _index.FKEdge]] = []
    for child, edge in consumers_index.get(target_rec.qualname, ()):
        resolved = _resolve_target_record(
            idx, edge.qualname_target, anchor_rec=child, log=log,
        )
        if resolved is not None and resolved == target_rec:
            out.append((child, edge))
    return out


def _record_ancestors(
    idx: _index.ClassIndex,
    rec: _index.ClassRecord,
    log: _HeuristicLog | None = None,
) -> list[tuple[_index.ClassRecord, str, str]]:
    """Yield ``(parent_rec, kind, evidence)`` neighbors for ``--up``.

    Two sources of ancestor edges:

    1. Each FK edge in ``rec.fk_edges`` resolves to a parent record
       (same-package preference for v0/v1 disambiguation).
    2. Parts-as-upstream-contributors: if ``rec`` is itself a master
       (a record with parts), surface its parts as ancestors so
       ``--up Master`` reaches the upstream pipelines feeding into a
       merge master through its parts.
    """
    out: list[tuple[_index.ClassRecord, str, str]] = []
    for edge in rec.fk_edges:
        parent_rec = _resolve_target_record(
            idx, edge.qualname_target, anchor_rec=rec, log=log,
        )
        if parent_rec is not None:
            out.append((parent_rec, edge.kind, edge.evidence))
    parts = _parts_of_master(idx, rec, log=log)
    if parts:
        kind = "merge_part" if _is_merge_master(rec) else "nested_part"
        for part_rec in parts:
            out.append((part_rec, kind, ""))
    return out


def _record_descendants(
    idx: _index.ClassIndex,
    rec: _index.ClassRecord,
    skip_parts: bool,
    log: _HeuristicLog | None = None,
) -> list[tuple[_index.ClassRecord, str, str, bool]]:
    """Yield ``(child_rec, kind, evidence, next_skip_parts)`` neighbors
    for ``--down`` (FK-impact cascade).

    Three sources of descendant edges:

    1. FK consumers: records that FK to ``rec`` (resolved by same-
       package preference; filters v0/v1 leakage).
    2. Master containment: if ``rec`` is a master, parts are
       descendants — UNLESS we entered ``rec`` via a part-bridge,
       in which case we skip parts to avoid sibling-part fan-out.
    3. Part-bridge: if ``rec`` is a part, its master is a downstream
       impact (modifying the part changes the master's contents).
       The hop carries ``next_skip_parts=True`` so the master, when
       expanded, won't fan out to its siblings.
    """
    out: list[tuple[_index.ClassRecord, str, str, bool]] = []
    for child_rec, edge in _resolve_consumers(idx, rec, log=log):
        # When entered via part-bridge, suppress siblings: any consumer
        # that is itself a part of `rec` is a sibling we already filter
        # via the master-containment branch below; but FK consumers
        # whose master==rec are also siblings (rare — parts usually
        # don't have FK consumers, but be conservative).
        if skip_parts and child_rec.master == rec.qualname:
            continue
        out.append((child_rec, edge.kind, edge.evidence, False))
    if not skip_parts:
        parts = _parts_of_master(idx, rec, log=log)
        if parts:
            kind = "merge_part" if _is_merge_master(rec) else "nested_part"
            for part_rec in parts:
                out.append((part_rec, kind, "", False))
    master_rec = _master_record_of(idx, rec, log=log)
    if master_rec is not None:
        kind = "merge_part" if _is_merge_master(master_rec) else "nested_part"
        # Mark the next hop so the master, when expanded, skips its
        # siblings (the other parts) and only walks normal FK consumers.
        out.append((master_rec, kind, "", True))
    return out


def _bfs_walk_records(
    idx: _index.ClassIndex,
    root_rec: _index.ClassRecord,
    direction: str,  # "ancestors" or "descendants"
    max_depth: int,
    log: _HeuristicLog | None = None,
) -> tuple[
    list[tuple[_index.ClassRecord, int]],
    list[tuple[_index.ClassRecord, _index.ClassRecord, str, str]],
    bool,
]:
    """Record-keyed BFS for ``--up`` / ``--down`` walks.

    Returns ``(nodes, edges, truncated)``:

    * ``nodes`` is ``[(record, depth), ...]`` — the visited records
      in BFS order (root excluded; root is rendered separately).
    * ``edges`` is ``[(parent_rec, child_rec, kind, evidence), ...]``
      where the relationship is parent→child in graph terms (so for
      ``--up`` the "parent" is the one closer to root).
    * ``truncated`` is ``True`` if at least one node at ``max_depth``
      had unvisited neighbors that BFS refused to expand. The agent
      can rerun with a larger ``--max-depth`` to see them.

    The visited set keys on ``ClassRecord`` itself (frozen dataclass,
    hashable). ``skip_parts`` propagates through the queue so a master
    reached via the part-bridge in descendant mode doesn't fan out to
    its sibling parts.
    """
    is_ancestors = direction == "ancestors"
    nodes: list[tuple[_index.ClassRecord, int]] = []
    edges: list[tuple[_index.ClassRecord, _index.ClassRecord, str, str]] = []
    visited: set[_index.ClassRecord] = {root_rec}
    truncated = False
    # Queue: (rec, depth, skip_parts). skip_parts only meaningful for
    # descendants; ancestors always pass False through.
    queue: deque[tuple[_index.ClassRecord, int, bool]] = deque([(root_rec, 0, False)])
    while queue:
        rec, depth, skip_parts = queue.popleft()
        if depth >= max_depth:
            # Don't expand, but check whether expansion *would have*
            # added a new node — if so, the result is truncated. This
            # answers "is there more deeper?" honestly without paying
            # to walk it (the neighbor lookup is what we'd skip).
            if not truncated:
                if is_ancestors:
                    peek = [n for n, _, _ in _record_ancestors(idx, rec, log=None)]
                else:
                    peek = [
                        n for n, _, _, _ in _record_descendants(
                            idx, rec, skip_parts=skip_parts, log=None,
                        )
                    ]
                if any(n not in visited for n in peek):
                    truncated = True
            continue
        if is_ancestors:
            neighbors = [
                (n, k, e, False) for n, k, e in _record_ancestors(idx, rec, log=log)
            ]
        else:
            neighbors = _record_descendants(idx, rec, skip_parts=skip_parts, log=log)
        for nbr_rec, kind, evidence, next_skip in neighbors:
            if nbr_rec in visited:
                # Skip back-edges (renderer walks edges to build the
                # tree; back-edges produce cycle-shaped output even
                # though BFS terminates).
                continue
            visited.add(nbr_rec)
            nodes.append((nbr_rec, depth + 1))
            if is_ancestors:
                # In --up, the newly visited node is the PARENT in graph
                # terms (closer to root in walk = closer to leaf in graph).
                edges.append((nbr_rec, rec, kind, evidence))
            else:
                edges.append((rec, nbr_rec, kind, evidence))
            queue.append((nbr_rec, depth + 1, next_skip))
    return nodes, edges, truncated


# ---------------------------------------------------------------------------
# Edge metadata (kind / evidence) lookup for rendering
# ---------------------------------------------------------------------------


def _master_part_kind(idx, master_qualname: str) -> str:
    """Return ``"merge_part"`` if the master inherits from ``_Merge``, else ``"nested_part"``."""
    master_rec = _record_for_qualname(idx, master_qualname)
    if master_rec is not None and any(b in _index.MERGE_BASE_NAMES for b in master_rec.bases):
        return "merge_part"
    return "nested_part"


def _records_for_qualname(
    idx: _index.ClassIndex, qualname: str,
) -> tuple[_index.ClassRecord, ...]:
    """Return ALL records matching ``qualname``. Multi-version classes
    share a qualname (e.g. v0 and v1 ``LFPBandSelection`` both have
    qualname == 'LFPBandSelection'); the FK edge of interest may live
    on only one of them. Callers that pick the first record via
    ``by_qualname`` will miss the edge."""
    short = qualname.rsplit(".", 1)[-1]
    return tuple(r for r in idx.get(short, ()) if r.qualname == qualname)


def _edge_meta(
    idx: _index.ClassIndex,
    parent_qualname: str,
    child_qualname: str,
    log: _HeuristicLog | None = None,
) -> tuple[str, str, _index.ClassRecord | None]:
    """Return ``(kind, evidence, child_record)`` for an edge from parent to child.

    ``child_record`` is the specific ClassRecord that participates in
    this edge (the one whose ``fk_edges`` contains the matched edge,
    or — for master-part bridges — the part record). Callers must use
    this record's ``file``/``line`` for the destination hop's citation,
    not whichever record ``by_qualname`` returns first: when v0 and v1
    classes share a qualname (e.g. both ``LFPBandSelection``), only one
    carries the relevant FK, and rendering the wrong file:line desyncs
    the citation from the evidence string. ``None`` only on the
    reverse part->master case where the master record is looked up by
    qualname (masters at top level are typically unique-by-qualname).

    Every edge produced by ``_path_graph`` originates from an FK edge
    or a master-part bridge, so a fall-through indicates the path graph
    and the index have desynced (e.g. a future bridge type added to
    ``_path_graph`` without updating this resolver). Raises
    ``RuntimeError`` rather than emitting a generic-looking
    ``("fk", "", None)`` that consumers can't distinguish from a real FK.
    """
    child_recs = _records_for_qualname(idx, child_qualname)
    for child_rec in child_recs:
        for edge in child_rec.fk_edges:
            if edge.qualname_target == parent_qualname:
                return edge.kind, edge.evidence, child_rec
        # No matching FK edge on this child record — could be a
        # master-part bridge from the master side. ``child_rec`` is
        # the part; its ``file:line`` is the part declaration.
        if child_rec.master == parent_qualname:
            return _master_part_kind(idx, parent_qualname), "", child_rec
    # Reverse direction: parent might be a part with the child being
    # its master. Resolve the master record so the destination hop
    # renders the master's declaration, not the part's. Use
    # same-package preference (anchored on the part) so a master
    # qualname collision picks the master in the part's package.
    for parent_rec in _records_for_qualname(idx, parent_qualname):
        if parent_rec.master == child_qualname:
            return (
                _master_part_kind(idx, child_qualname),
                "",
                _resolve_target_record(
                    idx, child_qualname, anchor_rec=parent_rec, log=log,
                ),
            )
    raise RuntimeError(
        f"_edge_meta: graph/index desync — edge {parent_qualname!r} -> "
        f"{child_qualname!r} is in _path_graph but neither an FK edge nor "
        f"a master-part bridge in the index. Likely a new bridge type was "
        f"added to _path_graph without a matching resolver here."
    )


def _record_for_qualname(
    idx: _index.ClassIndex, qualname: str
) -> _index.ClassRecord | None:
    """Look up a ClassRecord by qualname. Thin shim over
    ``ClassIndex.by_qualname`` retained because the module also calls
    this from many sites where the import alias is local."""
    return idx.by_qualname(qualname)


# ---------------------------------------------------------------------------
# Renderers (human-readable + JSON)
# ---------------------------------------------------------------------------


def _ambiguous_payload(name: str, candidates: list[_index.ClassRecord], hint: str) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "ambiguous",
        "name": name,
        "candidates": [
            {
                "qualname": r.qualname,
                "master": r.master,
                "file": r.file,
                "line": r.line,
                "tier": r.tier,
            }
            for r in candidates
        ],
        "hint": hint,
    }


def _suggest_class_names(
    name: str, idx: _index.ClassIndex, max_n: int = 5,
) -> list[str]:
    """Close-match candidates for a misspelled class name.

    Searches both short names (the index keys) and full qualnames so a
    typo of either ``"LFPV1"`` or ``"LFPOutput.LFPV1"`` gets useful
    suggestions. Cutoff 0.7 (difflib default 0.6) keeps obvious typos
    in and rejects unrelated names.
    """
    short_names = list(idx.keys())
    qualnames = [r.qualname for records in idx.values() for r in records]
    candidates = sorted(set(short_names) | set(qualnames))
    return difflib.get_close_matches(name, candidates, n=max_n, cutoff=0.7)


def _suggest_method_names(
    name: str, idx: _index.ClassIndex, max_n: int = 5,
) -> list[str]:
    """Close-match candidates for a misspelled method name."""
    rev = _index.reverse_method_index(idx)
    return difflib.get_close_matches(name, list(rev.keys()), n=max_n, cutoff=0.7)


def _not_found_payload(
    name: str, hint: str, suggestions: list[str] | None = None,
) -> dict:
    payload: dict = {
        "schema_version": SCHEMA_VERSION,
        "kind": "not_found",
        "name": name,
        "hint": hint,
        "suggestions": suggestions or [],
    }
    return payload


def _print_ambiguous_human(name: str, candidates: list[_index.ClassRecord]) -> None:
    print(f"Class '{name}' is ambiguous (defined in {len(candidates)} files):")
    for r in candidates:
        tier = f" (tier: {r.tier})" if r.tier else ""
        master = f" master: {r.master}" if r.master else ""
        print(f"  {r.file}:{r.line}{tier}{master}")
    print("Re-run with --from-file / --to-file (path mode) or --file (other modes).")


def _print_not_found_human(
    name: str, hint: str, suggestions: list[str] | None = None,
) -> None:
    print(f"Class '{name}' not found in the Spyglass index.")
    print(f"Hint: {hint}")
    if suggestions:
        print(f"Did you mean: {', '.join(suggestions)}")


def _node_dict(
    idx,
    qualname: str,
    depth: int | None = None,
    record: _index.ClassRecord | None = None,
) -> dict:
    """Render a node entry (no kind / evidence — those are edge attributes).

    Pass ``record`` (the user-resolved or edge-resolved ClassRecord) so
    multi-version qualname collisions cite the right ``file:line`` —
    the default ``by_qualname`` lookup returns the first match and may
    pick the wrong v0/v1 record. Always includes a ``node_kind`` from
    NODE_KIND_VALUES so the agent can branch on shape without
    re-deriving it.
    """
    rec = record if record is not None else _record_for_qualname(idx, qualname)
    if rec is None:
        out: dict = {
            "name": qualname.split(".")[-1],
            "qualname": qualname,
            "file": "?",
            "line": 0,
            "record_id": f"?:0:{qualname}",
            "node_kind": "unknown",
        }
        if depth is not None:
            out["depth"] = depth
        return out
    return _node_dict_from_record(rec, depth=depth, idx=idx)


def _hop_dict(
    idx,
    qualname: str,
    kind: str,
    evidence: str,
    record: _index.ClassRecord | None = None,
) -> dict:
    """Render one hop. Pass ``record`` (the ClassRecord that participates
    in the traversed edge) so multi-version qualname collisions don't
    desync ``file:line`` from ``evidence`` — the default ``by_qualname``
    fallback returns the first match and may pick the wrong v0/v1 record.
    """
    out = _node_dict(idx, qualname, record=record)
    out["kind"] = kind
    out["evidence"] = evidence
    return out


def _path_to_payload(
    idx,
    src_rec: _index.ClassRecord,
    dst_rec: _index.ClassRecord,
    path: list[str],
    log: _HeuristicLog | None = None,
) -> dict:
    """Build the path payload. Takes resolved ``src_rec``/``dst_rec``
    rather than bare qualnames so the source hop and the from/to node
    citations come from the user-disambiguated records, not from
    ``by_qualname`` (which returns the first match for multi-version
    qualname collisions)."""
    hops: list[dict] = []
    # First hop: the source. Use class declaration as evidence; default kind=fk.
    src_evidence = f"class {src_rec.name}({', '.join(src_rec.bases)}):"
    hops.append(_hop_dict(idx, src_rec.qualname, "fk", src_evidence, record=src_rec))
    # Subsequent hops: ``_edge_meta`` returns the record that owns the
    # traversed edge — pass it through so file:line and evidence agree.
    for i in range(1, len(path)):
        kind, evidence, child_rec = _edge_meta(
            idx, parent_qualname=path[i - 1], child_qualname=path[i], log=log,
        )
        hops.append(_hop_dict(idx, path[i], kind, evidence, record=child_rec))
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "path",
        "from": _node_dict(idx, src_rec.qualname, record=src_rec),
        "to": _node_dict(idx, dst_rec.qualname, record=dst_rec),
        "hops": hops,
    }


def _print_path_human(payload: dict) -> None:
    src = payload["from"]
    print(f"{src['name']} ({src['file']}:{src['line']})")
    indent = "  "
    for hop in payload["hops"][1:]:
        annotation = (
            f" [{hop['kind']}]" if hop["kind"] in ("proj", "merge_part", "nested_part") else ""
        )
        print(f"{indent}└─> {hop['qualname']}{annotation}  ({hop['file']}:{hop['line']})")
        indent += "    "


def _walk_payload(
    root_rec: _index.ClassRecord,
    walk_kind_label: str,
    max_depth: int,
    nodes: list[tuple[_index.ClassRecord, int]],
    edges: list[tuple[_index.ClassRecord, _index.ClassRecord, str, str]],
    truncated: bool = False,
    idx: _index.ClassIndex | None = None,
) -> dict:
    """Build the JSON payload from record-keyed BFS output.

    All file:line citations come directly from the records returned by
    `_bfs_walk_records` — no by-qualname fallback, so multi-version
    same-qualname collisions can't desync rendering from edge resolution.

    ``truncated`` is True when at least one node at ``max_depth`` had
    unvisited neighbors. The agent can rerun with a larger
    ``--max-depth`` to explore further.
    """
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": walk_kind_label,
        "root": _node_dict_from_record(root_rec, idx=idx),
        "max_depth": max_depth,
        "truncated": truncated,
        "truncated_at_depth": max_depth if truncated else None,
        "nodes": [
            _node_dict_from_record(rec, depth=d, idx=idx) for rec, d in nodes
        ],
        "edges": [
            {
                "child": child_rec.qualname,
                "parent": parent_rec.qualname,
                "kind": kind,
                "evidence": evidence,
            }
            for parent_rec, child_rec, kind, evidence in edges
        ],
    }


def _node_dict_from_record(
    rec: _index.ClassRecord,
    depth: int | None = None,
    idx: _index.ClassIndex | None = None,
) -> dict:
    """Render a node entry directly from a ClassRecord (no qualname lookup).

    Source-of-truth for the node-shape envelope (``_node_dict`` and
    ``_hop_dict`` both delegate here for the non-None record path).
    ``idx`` is required for ``node_kind`` derivation; when omitted it
    defaults to ``"unknown"`` so the field is still present on every
    payload (consistent shape for the agent's branching contract).
    """
    out: dict = {
        "name": rec.name,
        "qualname": rec.qualname,
        "file": rec.file,
        "line": rec.line,
        "record_id": _record_id(rec),
        "node_kind": _node_kind(idx, rec) if idx is not None else "unknown",
    }
    if depth is not None:
        out["depth"] = depth
    return out


def _print_walk_human(payload: dict, walk_label: str) -> None:
    root = payload["root"]
    print(f"{root['name']} ({root['file']}:{root['line']})")
    print(f"  {walk_label} (depth ≤ {payload['max_depth']}):")
    # Build a child→parent or parent→child map from edges to render an indented tree.
    is_ancestors = payload["kind"] == "ancestors"
    adj: dict[str, list[tuple[str, str]]] = {}
    for e in payload["edges"]:
        if is_ancestors:
            adj.setdefault(e["child"], []).append((e["parent"], e["kind"]))
        else:
            adj.setdefault(e["parent"], []).append((e["child"], e["kind"]))
    by_qualname = {n["qualname"]: n for n in payload["nodes"]}
    by_qualname[root["qualname"]] = {**root, "depth": 0}
    seen: set[str] = set()

    def _walk(q: str, prefix: str) -> None:
        children = adj.get(q, [])
        for i, (cq, kind) in enumerate(children):
            is_last = i == len(children) - 1
            connector = "└── " if is_last else "├── "
            tag = f" [{kind}]" if kind in ("proj", "merge_part", "nested_part") else ""
            node = by_qualname.get(cq, {"qualname": cq, "file": "?", "line": 0})
            print(f"{prefix}{connector}{cq}{tag}  {node['file']}:{node['line']}")
            if cq in seen:
                continue
            seen.add(cq)
            extension = "    " if is_last else "│   "
            _walk(cq, prefix + extension)

    _walk(root["qualname"], "  ")


# ---------------------------------------------------------------------------
# Subcommand dispatch
# ---------------------------------------------------------------------------


def cmd_path(args: argparse.Namespace) -> int:
    src_root = _index.resolve_src_root(args.src)
    idx = _index.scan(src_root)  # exits if src_root has no `spyglass/` package
    bfs_parent_m = _path_graph(idx)
    json_out = bool(args.json)
    fail_on_heuristic = bool(getattr(args, "fail_on_heuristic", False))
    log = _HeuristicLog()

    def _finish(payload: dict, exit_code: int, *, human_render=None) -> int:
        """Stamp provenance + warnings, emit, and apply --fail-on-heuristic."""
        _stamp_payload(payload, src_root, log)
        if exit_code == EXIT_OK and fail_on_heuristic and log:
            exit_code = EXIT_HEURISTIC
        if json_out:
            print(json.dumps(payload))
        elif human_render is not None:
            human_render(payload)
        # Surface warnings on the human path even when JSON is off, so
        # an interactive user notices the heuristic resolution.
        if not json_out and log:
            print(
                f"\n(note: {len(log.entries)} same-qualname resolution(s) "
                f"used same-package preference; pass --json to inspect "
                f"the warnings block, or --fail-on-heuristic to refuse)"
            )
        return exit_code

    def _resolve_or_emit(name: str, file_hint: str | None) -> _index.ClassRecord | int:
        rec, err, candidates = _resolve_class(name, idx, file_hint)
        if rec is not None:
            return rec
        if err == "not_found":
            payload = _not_found_payload(
                name,
                "class not in this Spyglass index — check spelling, "
                "or read the v0/v1 source files directly if asking about a specific version",
                suggestions=_suggest_class_names(name, idx),
            )
            return _finish(
                payload, EXIT_NOT_FOUND,
                human_render=lambda p: _print_not_found_human(
                    name, p["hint"], p.get("suggestions"),
                ),
            )
        # ambiguous
        payload = _ambiguous_payload(
            name, candidates,
            "re-run with --from-file/--to-file (--to mode) or --file (--up/--down mode)",
        )
        return _finish(
            payload, EXIT_AMBIGUOUS,
            human_render=lambda p: _print_ambiguous_human(name, candidates),
        )

    if args.to:
        from_name, to_name = args.to
        src_rec = _resolve_or_emit(from_name, args.from_file)
        if isinstance(src_rec, int):
            return src_rec
        dst_rec = _resolve_or_emit(to_name, args.to_file)
        if isinstance(dst_rec, int):
            return dst_rec
        path, truncated = _bfs_to(
            bfs_parent_m, src_rec.qualname, dst_rec.qualname, args.max_depth,
        )
        if path is None:
            reason = f"no FK chain found within max-depth {args.max_depth}"
            if truncated:
                reason += (
                    " (BFS hit max-depth with unexplored nodes; "
                    "rerun with larger --max-depth)"
                )
            payload = {
                "schema_version": SCHEMA_VERSION,
                "kind": "no_path",
                # Match the happy-path shape so callers can iterate over
                # `payload["from"]["file"]` regardless of whether a path was
                # found. Bare strings would force every consumer to type-check.
                "from": _node_dict(idx, src_rec.qualname, record=src_rec),
                "to": _node_dict(idx, dst_rec.qualname, record=dst_rec),
                "max_depth": args.max_depth,
                "truncated": truncated,
                "truncated_at_depth": args.max_depth if truncated else None,
                "reason": reason,
            }

            def _no_path_human(p: dict) -> None:
                print(f"No FK path from {src_rec.qualname} to {dst_rec.qualname}.")
                print(f"(Try the reverse: {dst_rec.qualname} → {src_rec.qualname}.)")
                if truncated:
                    print(
                        f"(BFS truncated at depth {args.max_depth}; "
                        f"rerun with larger --max-depth to keep searching.)"
                    )

            return _finish(payload, EXIT_OK, human_render=_no_path_human)
        payload = _path_to_payload(idx, src_rec, dst_rec, path, log=log)
        # Path payload also carries truncated/truncated_at_depth for shape
        # consistency. A successful path is by definition NOT truncated.
        payload["max_depth"] = args.max_depth
        payload["truncated"] = False
        payload["truncated_at_depth"] = None
        return _finish(payload, EXIT_OK, human_render=_print_path_human)

    if args.up or args.down:
        target_name = args.up or args.down
        target_rec = _resolve_or_emit(target_name, args.file)
        if isinstance(target_rec, int):
            return target_rec
        walk_label = "ancestors" if args.up else "descendants"
        nodes, edges, truncated = _bfs_walk_records(
            idx, target_rec, walk_label, args.max_depth, log=log,
        )
        payload = _walk_payload(
            target_rec, walk_label, args.max_depth, nodes, edges,
            truncated=truncated, idx=idx,
        )
        return _finish(
            payload, EXIT_OK,
            human_render=lambda p: _print_walk_human(p, walk_label),
        )

    return EXIT_USAGE  # unreachable: argparse guards


def _classify_base(name: str) -> str:
    """Map a textual base name to the bases-list `kind` enum."""
    canonical = _index.MIXIN_ALIASES.get(name, name)
    if canonical in _index.MIXIN_REGISTRY:
        return "inherits_resolved"
    if name in _index.DATAJOINT_BASES:
        return "inherits_annotated"
    return "inherits_unresolved"


def _describe_payload(
    idx: _index.ClassIndex,
    rec: _index.ClassRecord,
    no_inherited: bool,
) -> dict:
    """Build the JSON payload for `describe <CLASS>`."""
    # bases: each carries kind + evidence (the textual class declaration line).
    class_decl = f"class {rec.name}({', '.join(rec.bases)}):"
    bases_out: list[dict] = []
    for base in rec.bases:
        kind = _classify_base(base)
        entry: dict = {"name": base, "kind": kind, "evidence": class_decl}
        if kind == "inherits_resolved":
            base_rec = _index.resolve_base(base, idx)
            if base_rec is not None:
                entry["file"] = base_rec.file
                entry["line"] = base_rec.line
            else:
                # Registry-path miss; treat as unresolved per resolve_base contract.
                entry["kind"] = "inherits_unresolved"
        elif kind == "inherits_annotated":
            entry["annotation"] = "datajoint API reference"
        bases_out.append(entry)

    # body_methods: rec.methods is already private-filtered by _index.scan
    # (kept: public + __lshift__/__rshift__ via _KEPT_DUNDERS). No
    # consumer-side filter needed; same applies to `inherited` below.
    body_methods = [{"name": m.name, "line": m.line} for m in rec.methods]

    # inherited_methods: walk every non-datajoint base. If a base is in
    # MIXIN_REGISTRY (e.g. SpyglassMixin) the registry-path is authoritative;
    # otherwise fall back to a unique top-level class lookup. Recurse on each
    # resolved base's own bases — real Spyglass's SpyglassMixin inherits from
    # CautiousDeleteMixin / ExportMixin / etc., and `fetch_nwb` lives on a
    # sub-mixin. Visited set guards diamond inheritance; max_depth keeps the
    # walk bounded.
    inherited: list[dict] = []
    # Walk warnings surface in the JSON payload (top-level `warnings`
    # field) so an agent reading only --json sees them. De-duped per
    # (kind, base) within a single describe call: a wide diamond chain
    # emits one warning per problematic base, not one per visiting path.
    walk_warnings: list[dict] = []
    if not no_inherited:
        # Per-call scope: multiple describe() invocations in the same
        # process must walk independently. A module-level visited set
        # would silently suppress bases on subsequent calls.
        visited: set[str] = set()
        warned_truncated: set[str] = set()
        warned_unresolved: set[str] = set()
        max_depth = 4

        def _walk_base(base_name: str, depth: int) -> None:
            if base_name in _index.DATAJOINT_BASES:
                return
            base_rec = _index.resolve_base(base_name, idx)
            if base_rec is None:
                # Top-level bases are already demoted to
                # `inherits_unresolved` in `bases_out`; this path catches
                # a *sub*-base failing to resolve (e.g. SpyglassMixin's
                # parent renamed upstream without a MIXIN_REGISTRY
                # update) — methods inherited from it disappear silently
                # otherwise.
                if base_name not in warned_unresolved:
                    warned_unresolved.add(base_name)
                    walk_warnings.append({
                        "kind": "unresolved_transitive_base",
                        "base": base_name,
                        "message": (
                            f"could not resolve transitive base "
                            f"{base_name!r}; methods inherited from it "
                            f"(and its parents) are missing from "
                            f"`inherited_methods`. Add to MIXIN_REGISTRY "
                            f"if it's a known mixin."
                        ),
                    })
                return
            if base_rec.qualname in visited:
                return
            if depth > max_depth:
                # Real Spyglass mixin chains are 1-2 deep; truncation
                # means a refactor extended the chain past the cap.
                if base_name not in warned_truncated:
                    warned_truncated.add(base_name)
                    walk_warnings.append({
                        "kind": "depth_truncated",
                        "base": base_name,
                        "max_depth": max_depth,
                        "message": (
                            f"inheritance walk truncated at depth "
                            f"{max_depth} for {base_name!r}; methods "
                            f"deeper in the chain are missing from "
                            f"`inherited_methods`. Bump max_depth if "
                            f"needed."
                        ),
                    })
                return
            visited.add(base_rec.qualname)
            # base_rec.methods is already filtered by _index.scan.
            methods_out = [{"name": m.name, "line": m.line} for m in base_rec.methods]
            if methods_out:
                inherited.append({
                    "from_base": base_name,
                    "from_file": base_rec.file,
                    "methods": methods_out,
                })
            for parent_base in base_rec.bases:
                _walk_base(parent_base, depth + 1)

        for base in rec.bases:
            _walk_base(base, 0)

    # parts: list of nested ClassDef qualnames with file/line (so the agent
    # can navigate to each part's declaration without re-querying).
    part_kind = (
        "merge_part" if any(b in _index.MERGE_BASE_NAMES for b in rec.bases)
        else "nested_part"
    )
    parts_out = []
    for part_qn in rec.parts:
        part_rec = _record_for_qualname(idx, part_qn)
        parts_out.append({
            "name": part_qn.split(".")[-1],
            "qualname": part_qn,
            "file": part_rec.file if part_rec else rec.file,
            "line": part_rec.line if part_rec else 0,
            "kind": part_kind,
        })

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "describe",
        "class": {
            "name": rec.name,
            "qualname": rec.qualname,
            "master": rec.master,
            "file": rec.file,
            "line": rec.line,
            "tier": rec.tier,
            "definition": rec.definition,
        },
        "bases": bases_out,
        "pk_fields": [
            {"name": f.name, "type": f.type,
             "default": f.default, "auto_increment": f.auto_increment}
            for f in rec.pk_fields
        ],
        "non_pk_fields": [
            {"name": f.name, "type": f.type,
             "default": f.default, "auto_increment": f.auto_increment}
            for f in rec.non_pk_fields
        ],
        "fk_edges": [
            {
                "parent": e.parent,
                "qualname_target": e.qualname_target,
                "kind": e.kind,
                "in_pk": e.in_pk,
                "renames": e.renames_dict(),
                "evidence": e.evidence,
                "evidence_line": e.evidence_line,
            }
            for e in rec.fk_edges
        ],
        "body_methods": body_methods,
        "inherited_methods": inherited,
        "parts": parts_out,
        # Inheritance-walk warnings (unresolved transitive bases or
        # depth-truncation). Empty list when the walk completed cleanly.
        # Lives in the JSON so an agent reading only --json sees it; the
        # human renderer prints them under a "Warnings:" section too.
        "warnings": walk_warnings,
    }


def _print_describe_human(payload: dict) -> None:
    cls = payload["class"]
    tier = f"  tier: {cls['tier']}" if cls.get("tier") else ""
    print(f"{cls['qualname']}   {cls['file']}:{cls['line']}{tier}")
    print("  bases:")
    for b in payload["bases"]:
        if b["kind"] == "inherits_resolved":
            print(f"    {b['name']}   {b['file']}:{b['line']}    (resolved)")
        elif b["kind"] == "inherits_annotated":
            print(f"    {b['name']}    ({b.get('annotation', 'datajoint')} — see API reference)")
        else:
            print(f"    {b['name']}    (unresolved — not in registry, not a known dj base)")
    if cls.get("definition"):
        print("  definition:")
        for line in cls["definition"].splitlines():
            if line.strip():
                print(f"    {line}")
    if payload["pk_fields"] or payload["fk_edges"]:
        print("  primary key:")
        for e in (e for e in payload["fk_edges"] if e["in_pk"]):
            extra = (
                f" [{e['kind']}]" if e["kind"] in ("proj", "merge_part", "nested_part") else ""
            )
            renames = ""
            if e["renames"]:
                renames = " " + ", ".join(f"{k}={v!r}" for k, v in e["renames"].items())
            print(f"    fk: -> {e['parent']}{extra}{renames}")
        for f in payload["pk_fields"]:
            default = f"  default={f['default']}" if f["default"] is not None else ""
            ai = "  auto_increment" if f["auto_increment"] else ""
            print(f"    field: {f['name']}: {f['type']}{default}{ai}")
    if payload["non_pk_fields"] or any(not e["in_pk"] for e in payload["fk_edges"]):
        print("  non-PK fields:")
        for e in (e for e in payload["fk_edges"] if not e["in_pk"]):
            print(f"    fk: -> {e['parent']}")
        for f in payload["non_pk_fields"]:
            default = f"  default={f['default']}" if f["default"] is not None else ""
            print(f"    {f['name']}: {f['type']}{default}")
    if payload["parts"]:
        print("  parts:")
        for p in payload["parts"]:
            tag = f"  [{p['kind']}]"
            print(f"    {p['qualname']}   {p['file']}:{p['line']}{tag}")
    if payload["body_methods"]:
        print("  body-level methods:")
        for m in payload["body_methods"]:
            print(f"    {m['name']}   line {m['line']}")
    for entry in payload.get("inherited_methods", []):
        print(f"  inherited from {entry['from_base']} ({entry['from_file']}):")
        for m in entry["methods"]:
            print(f"    {m['name']}   line {m['line']}")
    if payload.get("warnings"):
        print("  warnings:")
        for w in payload["warnings"]:
            print(f"    [{w['kind']}] {w['message']}")


def cmd_describe(args: argparse.Namespace) -> int:
    src_root = _index.resolve_src_root(args.src)
    idx = _index.scan(src_root)  # exits if src_root has no `spyglass/` package
    json_out = bool(args.json)

    rec, err, candidates = _resolve_class(args.class_name, idx, args.file)
    if rec is None:
        if err == "not_found":
            payload = _not_found_payload(
                args.class_name,
                "class not in this Spyglass index — check spelling, "
                "or read the v0/v1 source files directly if asking about a specific version",
                suggestions=_suggest_class_names(args.class_name, idx),
            )
            _stamp_payload(payload, src_root)
            if json_out:
                print(json.dumps(payload))
            else:
                _print_not_found_human(
                    args.class_name, payload["hint"], payload.get("suggestions"),
                )
            return EXIT_NOT_FOUND
        payload = _ambiguous_payload(
            args.class_name, candidates,
            "re-run with --file <path>",
        )
        _stamp_payload(payload, src_root)
        if json_out:
            print(json.dumps(payload))
        else:
            _print_ambiguous_human(args.class_name, candidates)
        return EXIT_AMBIGUOUS

    payload = _describe_payload(idx, rec, args.no_inherited)
    _stamp_payload(payload, src_root)
    if json_out:
        print(json.dumps(payload))
    else:
        _print_describe_human(payload)
    return EXIT_OK


def _ownership_kind(rec: _index.ClassRecord) -> str:
    """Classify a body-level method definition's owner.

    Four buckets, in priority order:

    * ``"merge"`` — the class itself inherits from `_Merge` / `Merge`
      (it is a merge master). Method shows up as "defined on a merge
      master" in find-method output.
    * ``"mixin"`` — the class itself IS a registered mixin
      (`SpyglassMixin`, `SpyglassAnalysis`, etc. in MIXIN_REGISTRY).
      The method is part of the mixin's API and inherited by every
      subclass.
    * ``"inherits_mixin"`` — the class inherits from a registered
      mixin but isn't itself one (typical concrete table like
      `CurationV1`, `RawPosition`, `Nwbfile`). The method is body-
      level on this specific table — NOT inherited from the mixin.
      Distinct from ``"mixin"`` so the agent can tell "this method
      lives on a concrete table" from "this method lives on a mixin
      and propagates to every subclass."
    * ``"body"`` — everything else (the class doesn't touch the
      registered mixin chain).
    """
    if any(b in _index.MERGE_BASE_NAMES for b in rec.bases):
        return "merge"
    if rec.qualname in _index.MIXIN_REGISTRY or rec.name in _index.MIXIN_REGISTRY:
        return "mixin"
    for base in rec.bases:
        canonical = _index.MIXIN_ALIASES.get(base, base)
        if canonical in _index.MIXIN_REGISTRY:
            return "inherits_mixin"
    return "body"


def _findmethod_payload(
    idx: _index.ClassIndex,
    src_root: Path,
    method_name: str,
    include_inherited: bool,
) -> dict | None:
    """Build the find-method JSON payload, or None if the method is unknown.

    ``src_root`` is the directory containing the ``spyglass/`` package
    (passed in from ``cmd_find_method`` after one resolution); reusing it
    here avoids a second ``$SPYGLASS_SRC`` lookup that could target a
    different directory than the scan if the env var changed mid-process.
    Note that ``entry["class"]["line"]`` is the class declaration line and
    ``entry["line"]`` is the method's definition line — distinct fields
    by design.
    """
    rev = _index.reverse_method_index(idx)
    owners = rev.get(method_name) or []
    if not owners:
        return None

    defined_at = []
    for rec in owners:
        # Look up the (name, lineno) tuple for this method on the owner.
        method_lineno = next(
            (m.line for m in rec.methods if m.name == method_name), rec.line
        )
        # Evidence: try to read the actual `def` line from source for a
        # readable snippet. Fall back to a synthetic line if read fails.
        try:
            full_path = src_root / rec.file
            evidence_lines = full_path.read_text().splitlines()
            evidence = (
                evidence_lines[method_lineno - 1].rstrip()
                if 1 <= method_lineno <= len(evidence_lines)
                else f"def {method_name}(...):"
            )
        except (OSError, UnicodeDecodeError):
            evidence = f"def {method_name}(...):"
        defined_at.append({
            "class": {
                "name": rec.name,
                "qualname": rec.qualname,
                "file": rec.file,
                "line": rec.line,
            },
            "line": method_lineno,
            "ownership_kind": _ownership_kind(rec),
            "evidence": evidence,
        })

    inherited_via: list[dict] = []
    if include_inherited:
        # Surface a per-mixin-base summary (don't enumerate every subclass —
        # that's noisy. The agent uses describe <ClassName> to confirm on a
        # specific class).
        for entry in defined_at:
            # If the owner IS a registered mixin (canonical or aliased),
            # emit a summary keyed on the alias name agents would type.
            for base_name in _index.MIXIN_REGISTRY:
                rec = _index.resolve_base(base_name, idx)
                if rec is None or rec.qualname != entry["class"]["qualname"]:
                    continue
                # Find any aliases that resolve to this canonical name.
                aliases = [a for a, c in _index.MIXIN_ALIASES.items() if c == base_name]
                key = aliases[0] if aliases else base_name
                inherited_via.append({
                    "base": key,
                    "summary": (
                        f"{method_name} is inherited by every class that "
                        f"subclasses {key} (transitive). Use "
                        f"`code_graph.py describe <ClassName>` to confirm "
                        f"on a specific class."
                    ),
                })

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "find-method",
        "method": method_name,
        "defined_at": defined_at,
        "inherited_via": inherited_via,
    }


def _print_findmethod_human(payload: dict) -> None:
    print(f"{payload['method']} defined on:")
    for entry in payload["defined_at"]:
        cls = entry["class"]
        kind = entry["ownership_kind"]
        print(f"  {cls['qualname']}   {cls['file']}:{entry['line']}  ({kind})")
        if entry.get("evidence"):
            print(f"    evidence: {entry['evidence']!r}")
    if payload.get("inherited_via"):
        print()
        print("inherited via:")
        for entry in payload["inherited_via"]:
            print(f"  {entry['base']} → {entry['summary']}")


def cmd_find_method(args: argparse.Namespace) -> int:
    src_root = _index.resolve_src_root(args.src)
    idx = _index.scan(src_root)  # exits if src_root has no `spyglass/` package
    json_out = bool(args.json)

    payload = _findmethod_payload(
        idx, src_root, args.method_name, include_inherited=not args.no_inherited
    )
    if payload is None:
        not_found = {
            "schema_version": SCHEMA_VERSION,
            "kind": "not_found",
            "method": args.method_name,
            "hint": (
                "no class in this Spyglass index defines a method by this name. "
                "The method may come from a datajoint base class (fetch, fetch1, "
                "insert, populate, …) — check datajoint docs. Or it may live in "
                "a custom table outside $SPYGLASS_SRC; if so, the user must "
                "import that module before live-DB tools can find it either."
            ),
            "suggestions": _suggest_method_names(args.method_name, idx),
        }
        _stamp_payload(not_found, src_root)
        if json_out:
            print(json.dumps(not_found))
        else:
            print(
                f"No class in this Spyglass index defines a method named "
                f"{args.method_name!r}."
            )
            print(f"Hint: {not_found['hint']}")
            if not_found["suggestions"]:
                print(f"Did you mean: {', '.join(not_found['suggestions'])}")
        return EXIT_NOT_FOUND

    _stamp_payload(payload, src_root)
    if json_out:
        print(json.dumps(payload))
    else:
        _print_findmethod_human(payload)
    return EXIT_OK


def cmd_info(args: argparse.Namespace) -> int:
    """Dump the tool's machine-readable contract.

    Lets an agent learn the subcommand surface, exit-code semantics,
    enums, and warning kinds in one structured JSON call rather than
    consulting prose documentation. Static — no index scan, no Spyglass
    source needed.
    """
    payload = {
        "schema_version": SCHEMA_VERSION,
        "kind": "info",
        "graph": GRAPH_KIND,
        "authority": AUTHORITY,
        # info is static — no Spyglass source tree is required to call it,
        # so source_root is null. Every other payload kind populates this
        # with the resolved $SPYGLASS_SRC; see `payload_envelopes` below.
        "source_root": None,
        "subcommands": {
            "path": {
                "purpose": "FK edge traversal between classes.",
                "modes": {
                    "--to A B": (
                        "Find the FK chain from A to B (BFS bridges master-part "
                        "containment in both directions)."
                    ),
                    "--up X": (
                        "Containment-ancestor walk; surfaces parts as upstream "
                        "contributors so --up Master reaches the pipelines "
                        "feeding into a merge."
                    ),
                    "--down X": (
                        "FK-impact cascade ('what breaks if I modify X?'); "
                        "follows FK consumers plus a part->master bridge, with "
                        "skip_parts so masters reached via the bridge don't fan "
                        "out to sibling parts."
                    ),
                },
                "hints": [
                    "--from-file / --to-file / --file disambiguate same-named classes.",
                    (
                        "--max-depth caps walk depth (default 12); look for "
                        "'truncated': true in the payload."
                    ),
                    (
                        "--fail-on-heuristic exits 5 if any same-qualname "
                        "collision was resolved via same-package preference."
                    ),
                ],
            },
            "describe": {
                "purpose": (
                    "Node view: tier, bases, structured PK/non-PK/FK with "
                    "projected renames, body methods, methods inherited from "
                    "registered mixins, parts."
                ),
                "hints": [
                    "--file to disambiguate; --no-inherited to suppress "
                    "inherited-method walk."
                ],
            },
            "find-method": {
                "purpose": (
                    "Reverse method index: every class that defines METHOD_NAME "
                    "at body level, plus mixin inherited-availability summary."
                ),
                "hints": ["Returns suggestions on close-match misses."],
            },
            "info": {
                "purpose": "This call: dump the tool's machine-readable contract.",
                "hints": [],
            },
        },
        "exit_codes": {
            "0": "ok (path found, no_path is also a well-formed answer).",
            "2": "usage error (argparse default).",
            "3": (
                "user-supplied input ambiguous — re-run with "
                "--from-file / --to-file / --file."
            ),
            "4": (
                "class or method not found in the index. Payload carries "
                "`suggestions` (close-name matches)."
            ),
            "5": (
                "traversal needed a heuristic to disambiguate a same-qualname "
                "collision; only emitted under --fail-on-heuristic. Otherwise "
                "the resolution(s) appear in the payload's top-level "
                "`warnings` block."
            ),
        },
        "node_kind_values": list(NODE_KIND_VALUES),
        "fk_edge_kinds": list(FK_EDGE_KIND_VALUES),
        "ownership_kinds": list(OWNERSHIP_KIND_VALUES),
        # Warning kinds emitted in payload `warnings` arrays. Top-level
        # `warnings` on path/walk payloads carries `heuristic_resolution`
        # entries from same-package preference. The describe payload
        # carries `unresolved_transitive_base` and `depth_truncated`
        # entries from the inheritance walk.
        "warning_kinds": [
            "heuristic_resolution",       # path/walk: same-qualname disambiguated
            "unresolved_transitive_base", # describe: inheritance chain dead-end
            "depth_truncated",            # describe: inheritance walk hit depth cap
        ],
        # Every payload kind's top-level field set. ``info`` itself is
        # static, so ``source_root`` is always null on info payloads;
        # all other payloads populate it with the resolved source tree.
        # `every_payload` is the universal envelope.
        "payload_envelopes": {
            "every_payload": [
                "schema_version", "kind", "graph", "authority", "source_root",
            ],
            "path": [
                "from", "to", "hops", "max_depth", "truncated", "truncated_at_depth",
            ],
            "no_path": [
                "from", "to", "reason", "max_depth", "truncated",
                "truncated_at_depth",
            ],
            "ancestors": [
                "root", "max_depth", "truncated", "truncated_at_depth",
                "nodes", "edges",
            ],
            "descendants": [
                "root", "max_depth", "truncated", "truncated_at_depth",
                "nodes", "edges",
            ],
            "describe": [
                "class", "bases", "pk_fields", "non_pk_fields", "fk_edges",
                "body_methods", "inherited_methods", "parts", "warnings",
            ],
            "find-method": ["method", "defined_at", "inherited_via"],
            "not_found": ["name_or_method", "hint", "suggestions"],
            "ambiguous": ["name", "candidates", "hint"],
            "info": [
                "subcommands", "exit_codes", "node_kind_values",
                "fk_edge_kinds", "ownership_kinds", "warning_kinds",
                "payload_envelopes",
            ],
        },
    }
    if args.json:
        print(json.dumps(payload))
    else:
        # Human-readable: still useful as a quick contract reminder.
        print("code_graph.py — source-only Spyglass code-graph navigation")
        print(f"\nGraph: {payload['graph']}    Authority: {payload['authority']}")
        print("\nSubcommands:")
        for name, info in payload["subcommands"].items():
            print(f"  {name}: {info['purpose']}")
        print("\nExit codes:")
        for code, meaning in payload["exit_codes"].items():
            print(f"  {code} — {meaning}")
        print(f"\nnode_kind values: {', '.join(payload['node_kind_values'])}")
        print(f"fk_edge kinds: {', '.join(payload['fk_edge_kinds'])}")
        print("\n(Pass --json for the full machine-readable payload.)")
    return EXIT_OK


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    if args.cmd == "path":
        return cmd_path(args)
    if args.cmd == "describe":
        return cmd_describe(args)
    if args.cmd == "find-method":
        return cmd_find_method(args)
    if args.cmd == "info":
        return cmd_info(args)
    parser.error("subcommand required")  # exits with code 2


if __name__ == "__main__":
    sys.exit(main())
