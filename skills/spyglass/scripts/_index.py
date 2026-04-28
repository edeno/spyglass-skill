"""Source-only AST index of Spyglass classes.

Imported by `code_graph.py` (its three subcommands all consume this module's
`scan()` output). No CLI; runs an in-module smoke test under ``__main__`` so
a developer can sanity-check the AST walk against ``$SPYGLASS_SRC`` before
building consumers.

Lifecycle
---------

Prototype here. Upstream candidate: ``spyglass.utils.code_graph._index``
(or wherever Spyglass eventually exposes a structured class-index API).
Once Spyglass ships an equivalent, retire this module locally and have
``code_graph.py`` import the upstream module. The three dataclasses
(``ClassRecord`` / ``FKEdge`` / ``FieldSpec``) and the ``MIXIN_REGISTRY``
/ ``MIXIN_ALIASES`` shape are stable enough to migrate as-is; the
``parse_definition`` and ``scan`` functions overlap with what the
validator's hand-curated ``KNOWN_CLASSES`` does, so an upstream merge
would naturally fold ``KNOWN_CLASSES`` auto-derivation in at the same
time (see ``docs/plans/code-graph-impl-plan.md`` § Out-of-scope).

Contract guarantees (per docs/plans/code-graph-impl-plan.md):

* Pure: no ``import spyglass`` or ``import datajoint`` — runs against a
  checked-out source tree on a machine with neither installed.
* Bounded: ignores ``__pycache__/``, hidden dirs, and files with
  ``SyntaxError`` (rather than crashing the whole index on one bad file).
* Cached per-process via ``lru_cache(maxsize=1)``. Multiple CLI invocations
  each pay the ~0.4s walk once.
* Multi-file class returns a list, not a single record. Consumers decide
  whether to disambiguate, error, or union.

Schema is at ``schema_version == 1``. The fields below are part of the
contract; renaming/removing fields is a breaking change and requires a
version bump.
"""

import ast
import os
import re
import sys
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Literal

FKEdgeKind = Literal["fk", "proj", "nested_part", "merge_part"]
TableTier = Literal["Manual", "Lookup", "Computed", "Imported", "Part"]
AmbiguityReason = Literal["ambiguous", "version_mismatch"]
SchemaStatus = Literal["ok", "unknown", "ambiguous", "version_mismatch", "placeholder"]

_VERSION_FROM_PATH_RE = re.compile(r"/v(\d+)/")

# Substrings that mark a `definition` as a non-DataJoint sentinel rather
# than a real schema string. Spyglass's `common/custom_nwbfile.py` uses
# "managed by SpyglassAnalysis" for its `AnalysisNwbfile` shadow; future
# placeholders will use similar prose. Detection is content-based (not
# parse-output-based) so a `parse_definition` regression that produced
# empty fields for a real class is NOT silenced by the same filter.
_PLACEHOLDER_DEFINITION_MARKERS = (
    "managed by SpyglassAnalysis",
    "managed by SpyglassMixin",
)
# A real DataJoint schema always contains at least one of these tokens.
_DJ_DEFINITION_TOKENS = (":", "->", "---")


def _version_from_path(path: str | None) -> str | None:
    """Return the version segment for a Spyglass source path, e.g.
    ``"v1"`` for ``"spyglass/spikesorting/v1/sorting.py"``. Returns
    None for paths without a ``/v<N>/`` segment (most non-pipeline
    modules)."""
    if not path:
        return None
    m = _VERSION_FROM_PATH_RE.search(path)
    return f"v{m.group(1)}" if m else None


def is_placeholder(rec: "ClassRecord") -> bool:
    """True when ``rec.definition`` is a sentinel placeholder rather
    than a real DataJoint schema. Public because ``code_graph.py``
    consumes it cross-module — the previous underscore prefix lied
    about scope."""
    if rec.definition is None:
        return True
    text = rec.definition
    if any(marker in text for marker in _PLACEHOLDER_DEFINITION_MARKERS):
        return True
    if not any(tok in text for tok in _DJ_DEFINITION_TOKENS):
        return True
    return False

SCHEMA_VERSION = 1

MIXIN_REGISTRY: MappingProxyType[str, str] = MappingProxyType({
    # First-party Spyglass mixins. Two roles each entry plays:
    #
    # * `code_graph.py describe`'s `_walk_base` resolves these names
    #   when they appear as direct bases of a class. Concrete tables
    #   only declare the entry-point mixins (`SpyglassMixin`,
    #   `SpyglassAnalysis`, `SpyglassIngestion`, `Merge`) as bases;
    #   transitive sub-mixins are reached by recursing into the
    #   entry mixins' own base chains.
    # * `code_graph.py find-method`'s `_ownership_kind` labels a
    #   class's role. Registered classes get `"mixin"`; tables that
    #   inherit from one get `"inherits_mixin"`. The sub-mixins
    #   below are listed so a method defined on (e.g.) `FetchMixin`
    #   itself shows up as `kind="mixin"` rather than `"body"`.
    #
    # Hand-curated; resist pre-populating. Add entries when smoke-
    # testing against live Spyglass surfaces a label or walk gap.
    #
    # Entry-point mixins (declared as direct bases of concrete tables):
    "SpyglassMixin": "spyglass/utils/dj_mixin.py",
    "SpyglassAnalysis": "spyglass/utils/dj_mixin.py",
    "SpyglassIngestion": "spyglass/utils/dj_mixin.py",
    "Merge": "spyglass/utils/dj_merge_tables.py",
    # Sub-mixins (reached via SpyglassMixin's base chain):
    "CautiousDeleteMixin": "spyglass/utils/mixins/cautious_delete.py",
    "ExportMixin": "spyglass/utils/mixins/export.py",
    "FetchMixin": "spyglass/utils/mixins/fetch.py",
    "HelperMixin": "spyglass/utils/mixins/helpers.py",
    "PopulateMixin": "spyglass/utils/mixins/populate.py",
    "RestrictByMixin": "spyglass/utils/mixins/restrict_by.py",
    "AnalysisMixin": "spyglass/utils/mixins/analysis.py",
    "IngestionMixin": "spyglass/utils/mixins/ingestion.py",
})

# The merge-master base names that appear in ``ClassRecord.bases`` for
# classes inheriting from the Merge mixin. Includes the ``_Merge`` alias
# (see MIXIN_ALIASES below) so ``"_Merge" in MERGE_BASE_NAMES`` is the
# single membership test downstream consumers use. Hardcoded both forms
# rather than deriving from MIXIN_ALIASES because future merge bases
# might not all live behind aliases.
MERGE_BASE_NAMES = frozenset({"Merge", "_Merge"})

MIXIN_ALIASES: MappingProxyType[str, str] = MappingProxyType({
    # Textual-base names Spyglass code uses that resolve to a different
    # canonical class. `_Merge` is exported from `dj_merge_tables.py` as
    # an alias of the `Merge` class (last line of that module:
    # `_Merge = Merge`). Without this mapping, classes like
    # `class LFPOutput(_Merge, SpyglassMixin):` would have an unresolved
    # base, and merge-master inherited methods (`merge_get_part`,
    # `merge_restrict`) wouldn't surface in describe.
    #
    # Maintenance: to verify whether new aliases need to be added or
    # this entry needs to be updated, grep for module-level alias
    # assignments:
    #   grep -nE '^[A-Z_][A-Za-z_0-9]* = [A-Z][A-Za-z_0-9]*$' \
    #       $SPYGLASS_SRC/spyglass/utils/*.py
    # An entry like `_Merge = Merge` indicates a base-class alias.
    # Direct callers of `MIXIN_ALIASES.get`: this module's
    # `resolve_base`, plus `_classify_base`, `_ownership_kind`, and
    # `_findmethod_payload` in `code_graph.py`. The merge-base
    # detection site (`_finalize_fk_kinds` here, `_edge_meta` /
    # `_master_part_kind` in code_graph.py) consults `MERGE_BASE_NAMES`
    # above directly — renaming an alias requires editing both this
    # dict AND the frozenset.
    "_Merge": "Merge",
})

# Module-load-time invariant: every alias value must be a registered
# canonical name. Catches drift if someone adds an alias to a mixin
# the registry doesn't know about.
assert all(v in MIXIN_REGISTRY for v in MIXIN_ALIASES.values()), (
    f"MIXIN_ALIASES values must be registered MIXIN_REGISTRY keys; "
    f"got aliases pointing to {sorted(MIXIN_ALIASES.values())}, "
    f"registry has {sorted(MIXIN_REGISTRY)}"
)

DATAJOINT_BASES = frozenset(
    {
        # Annotated, not walked. describe.py prints "see datajoint API
        # reference" rather than enumerating these classes' methods.
        "dj.Manual", "dj.Lookup", "dj.Computed", "dj.Imported", "dj.Part",
        "Manual", "Lookup", "Computed", "Imported", "Part",
    }
)

_TIER_FROM_BASE: dict[str, TableTier] = {
    "dj.Manual": "Manual", "Manual": "Manual",
    "dj.Lookup": "Lookup", "Lookup": "Lookup",
    "dj.Computed": "Computed", "Computed": "Computed",
    "dj.Imported": "Imported", "Imported": "Imported",
    "dj.Part": "Part", "Part": "Part",
}


@dataclass(frozen=True)
class FieldSpec:
    """A single body-level attribute parsed from a `definition` string."""
    name: str
    type: str
    default: str | None
    auto_increment: bool


@dataclass(frozen=True)
class MethodSpec:
    """A body-level method declaration parsed from a class body.

    Carries enough signature metadata for callers (notably the validator)
    to check classmethod-vs-instance dispatch and required-arg presence
    without re-parsing the source. ``params`` excludes ``self``/``cls`` —
    the validator's ``Class.method(...)`` shape check is interested in
    the user-visible argument set, not the receiver.
    """
    name: str
    line: int
    params: tuple[str, ...] = ()
    has_kwargs: bool = False
    is_classmethod: bool = False
    is_staticmethod: bool = False


@dataclass(frozen=True)
class FKEdge:
    """A foreign-key edge parsed from a `->` line in a `definition` string.

    ``renames`` is stored as ``tuple[tuple[str, str], ...]`` rather than
    ``dict`` to keep the frozen guarantee honest: a frozen dataclass
    holding a mutable dict still leaks a mutation surface
    (``edge.renames["x"] = "y"``) that would corrupt the lru_cached
    scan output. Consumers needing dict semantics call
    ``edge.renames_dict()`` (returns a fresh dict per call).
    """
    parent: str
    qualname_target: str  # falls back to `parent` when not resolvable
    kind: FKEdgeKind
    in_pk: bool
    renames: tuple[tuple[str, str], ...] = ()
    evidence: str = ""
    evidence_line: int = 0

    def renames_dict(self) -> dict[str, str]:
        """Return ``{new: old}`` as a fresh dict for consumer ergonomics."""
        return dict(self.renames)


@dataclass(frozen=True)
class ClassRecord:
    """One AST-derived record per Spyglass class declaration.

    Multi-file classes (e.g. ``BodyPart``) produce one record per
    declaration; consumers see them as a list under the same dict key.
    ``qualname`` and ``master`` are first-class so part-tables and
    merge-master parts have unambiguous identity without re-deriving from
    nesting context.
    """
    name: str
    qualname: str
    master: str | None
    file: str
    line: int
    bases: tuple[str, ...]
    tier: TableTier | None
    definition: str | None
    pk_fields: tuple[FieldSpec, ...]
    non_pk_fields: tuple[FieldSpec, ...]
    fk_edges: tuple[FKEdge, ...]
    methods: tuple[MethodSpec, ...]
    parts: tuple[str, ...]


@dataclass(frozen=True)
class ClassIndex(Mapping[str, tuple[ClassRecord, ...]]):
    """Frozen, tuple-backed index returned by ``scan()``.

    Wraps ``{class_name: tuple[ClassRecord, ...]}`` with first-class
    helpers (`by_qualname`, `parent_map`, `child_map`,
    `reverse_methods`, `resolve_base`) so consumers don't reach for
    free functions in this module. Implements ``Mapping`` so existing
    callers using ``idx.get(name)``, ``idx.items()``, ``idx.values()``,
    ``name in idx`` continue to work.

    Tuple values keep the cached instance honestly immutable: a
    mutable-list shape would let `idx["Foo"].append(...)` corrupt
    the lru_cached scan output for every subsequent caller.
    """
    _by_name: Mapping[str, tuple[ClassRecord, ...]]

    def __getitem__(self, name: str) -> tuple[ClassRecord, ...]:
        return self._by_name[name]

    def __iter__(self) -> Iterator[str]:
        return iter(self._by_name)

    def __len__(self) -> int:
        return len(self._by_name)

    def by_qualname(self, qualname: str) -> ClassRecord | None:
        """Look up the unique ClassRecord by qualname, or None."""
        short = qualname.rsplit(".", 1)[-1]
        for rec in self._by_name.get(short, ()):
            if rec.qualname == qualname:
                return rec
        return None

    def child_map(self) -> dict[str, list[str]]:
        return _child_map(self)

    def parent_map(self) -> dict[str, list[str]]:
        return _parent_map(self)

    def reverse_methods(self) -> dict[str, list[ClassRecord]]:
        return _reverse_method_index(self)

    def resolve_base(self, name: str) -> ClassRecord | None:
        return _resolve_base(name, self)

    # ---------- Schema resolution (validator-facing) ----------------

    def schema_records(self, class_name: str) -> tuple[ClassRecord, ...]:
        """Return top-level non-placeholder records for ``class_name``.

        Filters to top-level (`qualname == name`) — nested parts are
        reachable via `by_qualname`. Filters out placeholder/shadow
        records (e.g. `common/custom_nwbfile.py`'s `AnalysisNwbfile`
        with a "managed by SpyglassAnalysis" sentinel definition).
        """
        return tuple(
            r for r in self._by_name.get(class_name, ())
            if r.qualname == class_name and not is_placeholder(r)
        )

    def resolve_record(
        self, class_name: str, version: str | None = None,
    ) -> ClassRecord | None:
        """Pick a single ClassRecord, given an optional version context.

        Resolution policy is intentionally STRICT:

        * Class not in index (no schema records): None
        * Singleton: return it (version is moot when there's nothing
          to disambiguate)
        * Multi-record + version specified: filter to the matching
          version, return that one. None if no record matches.
        * Multi-record + no version: None (FAIL-LOUD signal). Caller
          surfaces as "ambiguous multi-version reference; add a
          ``<!-- pipeline-version: vN -->`` marker."

        Strict by design — schema SHAPE is a per-version contract that
        must not be silently merged. Compare with `methods_for`, which
        unions across versions (method existence is a yes/no question
        that unions cleanly).
        """
        records = self.schema_records(class_name)
        if not records:
            return None
        if len(records) == 1:
            return records[0]
        if version is None:
            return None
        matching = [r for r in records if _version_from_path(r.file) == version]
        return matching[0] if len(matching) == 1 else None

    def fields_for(
        self,
        class_name: str,
        version: str | None = None,
        _seen: set[str] | None = None,
    ) -> set[str] | None:
        """Field names accepted in restrictions on ``class_name`` (PK +
        non-PK + projected FK new-names, walking transitive parents).

        Returns None on any unresolvable parent (matching
        ``insert_fields_for``) so callers can distinguish "unknown"
        from "ambiguous." Without that propagation a single-version
        child whose multi-version transitive parent is unmarked would
        field-check against an incomplete set and warn on legitimately-
        inherited keys.
        """
        if _seen is None:
            _seen = set()
        if class_name in _seen:
            return set()  # cycle guard
        _seen.add(class_name)
        rec = self.resolve_record(class_name, version)
        if rec is None:
            return None
        fields = {f.name for f in rec.pk_fields} | {f.name for f in rec.non_pk_fields}
        for edge in rec.fk_edges:
            for new_name, _src in edge.renames:
                fields.add(new_name)
            parent_fields = self.fields_for(edge.parent, version, set(_seen))
            if parent_fields is None:
                return None
            fields |= parent_fields
        return fields

    def insert_fields_for(
        self,
        class_name: str,
        version: str | None = None,
        _seen: set[str] | None = None,
    ) -> set[str] | None:
        """Field names valid for inserting into ``class_name``. Like
        ``fields_for`` but applies projection renames properly:
        ``-> Parent.proj(new='src')`` excludes ``src`` from the
        accepted set and includes ``new``.

        Critical for the Apr 2026 linearization bug where
        ``LinearizationSelection.insert1({"merge_id": ...})`` used the
        un-projected parent field name (real name: ``pos_merge_id``).

        Returns None on any unresolvable parent (vs. partial union) so
        callers don't emit false positives when the chain is partially
        ambiguous.
        """
        if _seen is None:
            _seen = set()
        if class_name in _seen:
            return set()
        _seen.add(class_name)
        rec = self.resolve_record(class_name, version)
        if rec is None:
            return None
        fields = {f.name for f in rec.pk_fields} | {f.name for f in rec.non_pk_fields}
        for edge in rec.fk_edges:
            parent_fields = self.insert_fields_for(edge.parent, version, set(_seen))
            if parent_fields is None:
                return None
            # `renames` is {new: old} per FKEdge contract: a parent field
            # `old` is exposed on this child as `new`. Drop `old` from the
            # acceptable set and add `new`.
            renames = edge.renames_dict()
            adjusted = set(parent_fields)
            for old_name in renames.values():
                adjusted.discard(old_name)
            fields |= adjusted
            fields |= set(renames.keys())
        return fields

    def pk_fields_for(
        self,
        class_name: str,
        version: str | None = None,
        _seen: set[str] | None = None,
    ) -> set[str] | None:
        """Field names in ``class_name``'s primary key (transitively).

        DataJoint propagates a parent's PK into a child's PK only for FK
        edges declared above the ``---`` divider (``in_pk=True`` on the
        FKEdge). Edges below ``---`` add non-PK FK columns. Walks only
        the in_pk subset and applies projection renames the same way as
        ``insert_fields_for``.

        Used by the partial-PK populate guard: a ``Table.populate({...})``
        whose dict is a strict subset of this set runs against every
        combination of the missing PK fields — usually wider scope than
        intended.

        Returns None on any unresolvable parent (matching the rest of
        the index API) so callers fail open rather than emit false
        positives on partially-ambiguous chains.
        """
        if _seen is None:
            _seen = set()
        if class_name in _seen:
            return set()
        _seen.add(class_name)
        rec = self.resolve_record(class_name, version)
        if rec is None:
            return None
        fields = {f.name for f in rec.pk_fields}
        for edge in rec.fk_edges:
            if not edge.in_pk:
                continue  # non-PK FK; doesn't propagate to PK
            parent_pk = self.pk_fields_for(edge.parent, version, set(_seen))
            if parent_pk is None:
                return None
            renames = edge.renames_dict()
            adjusted = set(parent_pk)
            for old_name in renames.values():
                adjusted.discard(old_name)
            fields |= adjusted
            fields |= set(renames.keys())
        return fields

    def find_ambiguous_in_chain(
        self,
        class_name: str,
        version: str | None = None,
        _seen: set[str] | None = None,
    ) -> tuple[str | None, AmbiguityReason | None]:
        """Walk ``class_name``'s FK chain and return ``(culprit, reason)``
        when the chain contains a class that caused ``resolve_record``
        to return None for an actionable reason. Returns
        ``(None, None)`` when the chain only contains "class not in
        index" failures (caller skips silently).

        ``reason``:

        * ``"ambiguous"`` — multi-record + ``version`` is None; add a
          marker to the file.
        * ``"version_mismatch"`` — the file declares ``version`` but
          no record matches (typo, wrong marker, prose names a class
          only present at the other version).
        """
        if _seen is None:
            _seen = set()
        if class_name in _seen:
            return None, None
        _seen.add(class_name)
        records = self.schema_records(class_name)
        if len(records) > 1:
            if version is None:
                return class_name, "ambiguous"
            matching = [r for r in records if _version_from_path(r.file) == version]
            if not matching:
                return class_name, "version_mismatch"
        elif len(records) == 1 and version is not None:
            rec_version = _version_from_path(records[0].file)
            if rec_version is not None and rec_version != version:
                return class_name, "version_mismatch"
        rec = self.resolve_record(class_name, version)
        if rec is None:
            return None, None
        for edge in rec.fk_edges:
            culprit, reason = self.find_ambiguous_in_chain(
                edge.parent, version, set(_seen),
            )
            if culprit is not None:
                return culprit, reason
        return None, None


def resolve_src_root(arg_src: str | None) -> Path:
    """Pick the Spyglass src/ directory: --src flag wins, else $SPYGLASS_SRC.

    Public because ``code_graph.py`` consumes it cross-module — the
    previous underscore prefix lied about scope.
    """
    if arg_src:
        return Path(arg_src).resolve()
    env = os.environ.get("SPYGLASS_SRC")
    if env:
        return Path(env).resolve()
    # Exit 2 = usage error per code_graph.py's documented exit codes.
    print(
        "ERROR: pass --src PATH or set $SPYGLASS_SRC to the directory "
        "containing the `spyglass/` package.\n"
        "  Git checkout: $SPYGLASS_SRC=/path/to/spyglass-repo/src\n"
        "  Pip install:  $SPYGLASS_SRC=$(python -c "
        "'import spyglass, os; "
        "print(os.path.dirname(os.path.dirname(spyglass.__file__)))')",
        file=sys.stderr,
    )
    sys.exit(2)


def _base_to_str(node: ast.AST) -> str:
    """Render an ast base-class expression back to its textual form."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_base_to_str(node.value)}.{node.attr}"
    return ast.unparse(node)


def _tier_from_bases(bases: tuple[str, ...]) -> TableTier | None:
    """Map an immediate base-list to a DJ tier, if one is present.

    Returns the first matching tier (Manual / Lookup / Computed / Imported /
    Part) or None. Consumers handle transitive resolution (e.g. _Merge → Manual)
    via the inheritance walk in describe.py.
    """
    for b in bases:
        if b in _TIER_FROM_BASE:
            return _TIER_FROM_BASE[b]
    return None


def is_foreign_key(line: str) -> bool:
    """Mirror ``datajoint.declare.is_foreign_key`` (declare.py:144).

    True when the line contains ``->`` and that arrow isn't preceded by a
    quote or comment character. The official rule rather than re-derived.
    """
    arrow = line.find("->")
    return arrow >= 0 and not any(c in line[:arrow] for c in "\"#'")


def _strip_inline_comment(line: str) -> str:
    """Remove inline ``#`` comments while respecting quoted strings."""
    in_q: str | None = None
    for i, ch in enumerate(line):
        if in_q is None:
            if ch in "\"'":
                in_q = ch
            elif ch == "#":
                return line[:i].rstrip()
        else:
            if ch == in_q and (i == 0 or line[i - 1] != "\\"):
                in_q = None
    return line.rstrip()


def _flatten_multiline_projections(definition: str) -> str:
    """Collapse ``-> Foo.proj(\\n  ...\\n)`` into one logical line.

    Only counts parens on FK lines so that non-FK fields with unbalanced
    parens (e.g. an `enum` field whose closing paren is on a separate line
    after a comment) can't accidentally trigger continuation buffering.
    Non-FK lines pass through verbatim.
    """
    out: list[str] = []
    buf: list[str] = []
    depth = 0
    for raw in definition.splitlines():
        if depth == 0:
            if not is_foreign_key(raw):
                out.append(raw)
                continue
            depth = raw.count("(") - raw.count(")")
            if depth > 0:
                buf.append(raw)
            else:
                out.append(raw)
                depth = 0
        else:
            buf.append(raw.strip())
            depth += raw.count("(") - raw.count(")")
            if depth <= 0:
                out.append(" ".join(buf))
                buf = []
                depth = 0
    if buf:
        out.append(" ".join(buf))
    return "\n".join(out)


def _parse_proj_renames(proj_body: str) -> dict[str, str]:
    """Extract ``{new: old}`` renames from a ``Foo.proj(new='old', ...)`` body.

    Uses ``ast.parse`` rather than regex so multi-kwarg, nested expressions,
    and string-vs-Name args are handled correctly. Returns empty dict for
    bare ``proj(...)`` with no kwargs.
    """
    try:
        tree = ast.parse(f"f({proj_body})", mode="eval")
    except SyntaxError:
        return {}
    call = tree.body
    if not isinstance(call, ast.Call):
        return {}
    out: dict[str, str] = {}
    for kw in call.keywords:
        if kw.arg is None:  # **kwargs unpack — out of scope
            continue
        if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
            out[kw.arg] = kw.value.value
    return out


def _parse_fk_line(line: str, in_pk: bool, base_lineno: int, line_offset: int) -> FKEdge | None:
    """Parse a single ``-> ...`` line into an FKEdge.

    Returns None if the line doesn't shape-match an FK reference. Strips
    the optional ``[option]`` block (``[nullable]``, ``[unique]``) before
    extracting the parent name.
    """
    stripped = _strip_inline_comment(line).strip()
    if not stripped.startswith("->"):
        return None
    body = stripped[2:].strip()
    # Strip optional [nullable] / [unique] block.
    if body.startswith("["):
        close = body.find("]")
        if close < 0:
            return None
        body = body[close + 1:].strip()
    # Split off .proj(...) suffix.
    proj_open = body.find(".proj(")
    if proj_open >= 0:
        parent = body[:proj_open].strip()
        # Find matching close paren — body may have trailing chars after.
        depth = 0
        proj_close = -1
        for i in range(proj_open, len(body)):
            if body[i] == "(":
                depth += 1
            elif body[i] == ")":
                depth -= 1
                if depth == 0:
                    proj_close = i
                    break
        if proj_close < 0:
            return None
        proj_body = body[proj_open + len(".proj("):proj_close]
        renames_tuple: tuple[tuple[str, str], ...] = tuple(
            _parse_proj_renames(proj_body).items()
        )
        kind: FKEdgeKind = "proj"
    else:
        # Plain reference (possibly Foo.Bar for nested parts).
        parent = body.strip()
        renames_tuple = ()
        kind = "fk"
    if not parent:
        return None
    return FKEdge(
        parent=parent,
        qualname_target=parent,  # consumers may upgrade after the scan
        kind=kind,
        in_pk=in_pk,
        renames=renames_tuple,
        evidence=stripped,
        evidence_line=base_lineno + line_offset,
    )


def _parse_field_line(line: str) -> FieldSpec | None:
    """Parse ``name [= default]: type`` into a FieldSpec.

    Handles auto_increment, parameterized types (``varchar(64)``,
    ``enum('a','b')``), defaults (string and numeric), and inline comments.
    Returns None for blank lines, divider lines, or shape-mismatched input.
    """
    stripped = _strip_inline_comment(line).strip()
    if not stripped or stripped.startswith("#") or stripped == "---":
        return None
    if stripped.startswith("->"):
        return None  # FK line; caller handles separately.
    if ":" not in stripped:
        return None
    name_part, _, type_part = stripped.partition(":")
    type_part = type_part.strip()
    name_part = name_part.strip()
    default: str | None = None
    if "=" in name_part:
        name, _, default = name_part.partition("=")
        name = name.strip()
        default = default.strip()
    else:
        name = name_part
    auto_increment = False
    if "auto_increment" in type_part:
        auto_increment = True
        type_part = type_part.replace("auto_increment", "").strip()
    if not name or not type_part:
        return None
    return FieldSpec(name=name, type=type_part, default=default, auto_increment=auto_increment)


def parse_definition(
    definition: str,
    base_lineno: int,
) -> tuple[tuple[FieldSpec, ...], tuple[FieldSpec, ...], tuple[FKEdge, ...]]:
    """Parse a `definition` string into structured fields + FK edges.

    Splits on the ``---`` divider. Above-divider lines are PK; below are
    non-PK. Each ``->`` line becomes an FKEdge with kind ``"fk"`` (or
    ``"proj"`` when ``.proj(...)`` is present, with the rename dict
    extracted via ``ast.parse``). The ``kind`` is upgraded to
    ``"nested_part"`` / ``"merge_part"`` by the scanner after
    cross-referencing with the AST's nested-ClassDef structure.

    Returns (pk_fields, non_pk_fields, fk_edges).
    """
    flat = _flatten_multiline_projections(definition)
    lines = flat.splitlines()
    in_pk = True
    pk_fields: list[FieldSpec] = []
    non_pk_fields: list[FieldSpec] = []
    fk_edges: list[FKEdge] = []
    for offset, line in enumerate(lines):
        # DataJoint accepts any run of 3+ dashes as the PK / non-PK divider.
        # Real Spyglass source uses both `---` and `----` styles (e.g. four
        # dashes in `ripple/v1/ripple.py:140` for `RippleParameters`).
        # Matching only exactly `---` would silently classify trailing
        # blob/secondary fields as PK and produce false positives in any
        # downstream check that distinguishes PK from non-PK
        # (e.g. `pk_fields_for` and the partial-PK populate guard).
        stripped = line.strip()
        if stripped and all(c == "-" for c in stripped) and len(stripped) >= 3:
            in_pk = False
            continue
        if is_foreign_key(line):
            edge = _parse_fk_line(line, in_pk, base_lineno, offset)
            if edge is not None:
                fk_edges.append(edge)
            continue
        spec = _parse_field_line(line)
        if spec is None:
            continue
        (pk_fields if in_pk else non_pk_fields).append(spec)
    return tuple(pk_fields), tuple(non_pk_fields), tuple(fk_edges)


def _extract_definition(class_node: ast.ClassDef) -> str | None:
    """Return the literal `definition` string assigned in a class body.

    Handles plain single-quoted and triple-quoted ``definition = "..."``
    assignments. Returns None if no such assignment exists or the value
    isn't a constant string (concatenated / interpolated definitions are
    out of scope — rare in Spyglass).
    """
    for stmt in class_node.body:
        if not isinstance(stmt, ast.Assign):
            continue
        if len(stmt.targets) != 1:
            continue
        target = stmt.targets[0]
        if not (isinstance(target, ast.Name) and target.id == "definition"):
            continue
        value = stmt.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return value.value
    return None


_KEPT_DUNDERS = frozenset({"__lshift__", "__rshift__"})


def _decorator_name(node: ast.expr) -> str:
    """Best-effort decorator name string for ``classmethod`` /
    ``staticmethod`` recognition. Anything else returns ``""``."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _extract_methods(class_node: ast.ClassDef) -> tuple[MethodSpec, ...]:
    """Return body-level method declarations as ``MethodSpec`` records.

    Skips nested-ClassDef bodies (those become parts in their own right).
    Includes both regular and async function definitions. Filters private
    methods (leading ``_``) except for the DataJoint operator dunders
    ``__lshift__`` / ``__rshift__`` which are first-class API surface.

    Captures signature metadata (params, **kwargs, classmethod /
    staticmethod decorators) so the validator's
    ``Class.method(...)`` vs ``Class().method(...)`` dispatch check
    doesn't need to re-parse the source.
    """
    out: list[MethodSpec] = []
    for stmt in class_node.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if stmt.name.startswith("_") and stmt.name not in _KEPT_DUNDERS:
                continue
            decorators = [_decorator_name(d) for d in stmt.decorator_list]
            is_classmethod = "classmethod" in decorators
            is_staticmethod = "staticmethod" in decorators
            # Strip the receiver (`self` / `cls`) from the user-visible
            # arg list so callers can compare against the actual call
            # signature without bookkeeping. Static methods have no
            # receiver so all args are user-visible.
            args = [a.arg for a in stmt.args.args]
            kwonly = [a.arg for a in stmt.args.kwonlyargs]
            if not is_staticmethod and args:
                args = args[1:]
            params = tuple(args + kwonly)
            out.append(MethodSpec(
                name=stmt.name,
                line=stmt.lineno,
                params=params,
                has_kwargs=stmt.args.kwarg is not None,
                is_classmethod=is_classmethod,
                is_staticmethod=is_staticmethod,
            ))
    return tuple(out)


def _walk_class_defs(
    tree: ast.AST,
    rel_path: str,
    parent_chain: tuple[str, ...] = (),
) -> list[ClassRecord]:
    """Yield ClassRecord per ClassDef, tracking nested-class qualnames."""
    out: list[ClassRecord] = []
    for stmt in ast.iter_child_nodes(tree):
        if not isinstance(stmt, ast.ClassDef):
            continue
        name = stmt.name
        qualname = ".".join(parent_chain + (name,))
        master = parent_chain[-1] if parent_chain else None
        bases = tuple(_base_to_str(b) for b in stmt.bases)
        tier = _tier_from_bases(bases)
        definition = _extract_definition(stmt)
        if definition is not None:
            pk, non_pk, fks = parse_definition(definition, stmt.lineno)
        else:
            pk, non_pk, fks = (), (), ()
        # Promote FK kind for nested-part references when the parent is one
        # of our nested ClassDefs (handled at index-finalization time, not
        # here — the scan needs to see the full class universe first).
        nested_parts = tuple(
            ".".join(parent_chain + (name, child.name))
            for child in stmt.body
            if isinstance(child, ast.ClassDef)
        )
        methods = _extract_methods(stmt)
        out.append(
            ClassRecord(
                name=name,
                qualname=qualname,
                master=master,
                file=rel_path,
                line=stmt.lineno,
                bases=bases,
                tier=tier,
                definition=definition,
                pk_fields=pk,
                non_pk_fields=non_pk,
                fk_edges=fks,
                methods=methods,
                parts=nested_parts,
            )
        )
        # Recurse into nested ClassDefs so part tables get their own records.
        out.extend(_walk_class_defs(stmt, rel_path, parent_chain + (name,)))
    return out


@lru_cache(maxsize=1)
def scan(src_root: Path) -> ClassIndex:
    """AST-walk ``src_root/spyglass/`` and return a ``ClassIndex``.

    Multi-file class names map to a tuple of records (no silent
    first-wins). Files that fail to parse (rare) are skipped rather
    than aborting the whole walk. Cached per-process via ``lru_cache`` so
    consumers calling repeatedly pay the ~0.4s walk once. ``src_root``
    is normalized via ``.resolve()`` so callers passing equivalent
    paths (``Path("/x")`` vs ``Path("/x/")``) hit the same cache entry.

    The returned ``ClassIndex`` is frozen and tuple-backed — consumers
    cannot mutate the cached value. Use the index's methods
    (`parent_map`, `child_map`, `reverse_methods`, `resolve_base`,
    `by_qualname`) rather than reaching for module-level free
    functions; the free functions are kept as thin shims for backward
    compatibility.
    """
    src_root = src_root.resolve()
    pkg = src_root / "spyglass"
    if not pkg.is_dir():
        # Exit 2 = usage error per code_graph.py's documented exit codes.
        print(
            f"ERROR: {src_root} does not contain a `spyglass/` package. "
            f"Pass --src pointing at the directory containing it.",
            file=sys.stderr,
        )
        sys.exit(2)
    building: dict[str, list[ClassRecord]] = {}
    for py_file in sorted(pkg.rglob("*.py")):
        # Skip __pycache__ and hidden dirs (rglob already skips dotfiles
        # at top level but not nested .pyc directories).
        if any(part.startswith(".") or part == "__pycache__" for part in py_file.parts):
            continue
        try:
            tree = ast.parse(py_file.read_text(), filename=str(py_file))
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
        rel_path = str(py_file.relative_to(src_root))
        for record in _walk_class_defs(tree, rel_path):
            building.setdefault(record.name, []).append(record)
    _finalize_fk_kinds(building)
    return ClassIndex(_by_name=MappingProxyType({
        name: tuple(records) for name, records in building.items()
    }))


def _finalize_fk_kinds(index: dict[str, list[ClassRecord]]) -> None:
    """Upgrade FK ``kind`` from ``"fk"`` to ``"nested_part"`` / ``"merge_part"``.

    A second pass once the index is built. For each FK edge whose target is
    a nested ClassDef (the parent has it in its `parts` list), set kind to
    ``"nested_part"``. If the master class inherits from ``_Merge``, upgrade
    further to ``"merge_part"``. Plain ``-> Foo`` references where Foo is a
    top-level class stay ``"fk"``; ``-> Foo.proj(...)`` references stay
    ``"proj"``.
    """
    # Build lookup: which qualnames are nested parts, and which masters are
    # merge masters. A merge master is a class whose bases include `_Merge`
    # (the alias) or `Merge` (the canonical name) — Spyglass code uses the
    # alias, so check both forms.
    parts_set: set[str] = set()
    merge_masters: set[str] = set()
    for records in index.values():
        for rec in records:
            parts_set.update(rec.parts)
            if any(b in MERGE_BASE_NAMES for b in rec.bases):
                merge_masters.add(rec.qualname)

    # Promote FK edges:
    #   * Resolve `-> master` (DJ keyword in part tables) to the master's qualname.
    #     Mark merge_part when master inherits from _Merge, else nested_part.
    #   * Promote `-> Foo.Bar` plain refs to nested_part / merge_part when
    #     the dotted name is in the index's parts set.
    for records in index.values():
        for i, rec in enumerate(records):
            if not rec.fk_edges:
                continue
            new_edges = []
            for edge in rec.fk_edges:
                if edge.kind == "fk" and edge.parent == "master" and rec.master is not None:
                    new_edges.append(replace(
                        edge,
                        parent=rec.master,
                        qualname_target=rec.master,
                        kind="merge_part" if rec.master in merge_masters else "nested_part",
                    ))
                elif edge.kind == "fk" and "." in edge.parent and edge.parent in parts_set:
                    master = edge.parent.rsplit(".", 1)[0]
                    new_edges.append(replace(
                        edge,
                        qualname_target=edge.parent,
                        kind="merge_part" if master in merge_masters else "nested_part",
                    ))
                else:
                    new_edges.append(edge)
            # Replace the immutable record with the kind-promoted edges.
            records[i] = replace(rec, fk_edges=tuple(new_edges))


# ---------------------------------------------------------------------------
# Index queries — implemented as private functions so ClassIndex can call
# them, then re-exported as module-level shims for backward compatibility.
# ---------------------------------------------------------------------------


def _child_map(
    index: Mapping[str, tuple[ClassRecord, ...]],
) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for records in index.values():
        for rec in records:
            for edge in rec.fk_edges:
                out.setdefault(edge.qualname_target, []).append(rec.qualname)
    return out


def _parent_map(
    index: Mapping[str, tuple[ClassRecord, ...]],
) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for records in index.values():
        for rec in records:
            out.setdefault(rec.qualname, [])
            for edge in rec.fk_edges:
                out[rec.qualname].append(edge.qualname_target)
    return out


def _reverse_method_index(
    index: Mapping[str, tuple[ClassRecord, ...]],
) -> dict[str, list[ClassRecord]]:
    out: dict[str, list[ClassRecord]] = {}
    for records in index.values():
        for rec in records:
            for method in rec.methods:
                out.setdefault(method.name, []).append(rec)
    for method_name, owners in out.items():
        out[method_name] = sorted(owners, key=lambda r: (r.file, r.line))
    return out


def _resolve_base(
    name: str,
    index: Mapping[str, tuple[ClassRecord, ...]],
    mixin_registry: MappingProxyType[str, str] = MIXIN_REGISTRY,
    mixin_aliases: MappingProxyType[str, str] = MIXIN_ALIASES,
) -> ClassRecord | None:
    canonical = mixin_aliases.get(name, name)
    if canonical in mixin_registry:
        target_path = mixin_registry[canonical]
        for rec in index.get(canonical, ()):
            if rec.file == target_path:
                return rec
        return None  # Registry path missed — caller annotates rather than guesses.
    records = index.get(canonical, ())
    if len(records) == 1:
        return records[0]
    return None


# Backward-compat shims (callers still use these as `_index.parent_map(idx)`
# etc; new code should prefer `idx.parent_map()` / `idx.resolve_base(...)`).
def child_map(index):
    """Inverse of the parent map: parent qualname → list of child qualnames.

    Keys are ``edge.qualname_target`` (consistent qualname space) — for plain
    ``-> Foo`` references where Foo is a top-level class, qualname_target ==
    parent == "Foo"; for ``-> master`` resolved edges, qualname_target is
    the master's qualname; for ``-> Foo.Bar`` part references,
    qualname_target is ``"Foo.Bar"``. Used by ``code_graph.py path --down``.
    Multi-file parent names map to multiple child entries; consumers should
    disambiguate before calling.

    Prefer ``ClassIndex.child_map()`` in new code.
    """
    return _child_map(index)


def parent_map(index):
    """Forward map: child qualname → list of parent qualnames.

    Used by ``code_graph.py path --to`` (BFS from TO walking parents) and
    ``--up`` (collect all ancestors). Symmetric with ``child_map``.

    Prefer ``ClassIndex.parent_map()`` in new code.
    """
    return _parent_map(index)


def reverse_method_index(index):
    """Build ``{method_name: [classes that define it at body level]}``.

    Used by ``code_graph.py find-method``. Owners sorted by ``(file,
    line)`` for cross-platform determinism. Prefer
    ``ClassIndex.reverse_methods()`` in new code.
    """
    return _reverse_method_index(index)


def resolve_base(
    name: str,
    index,
    mixin_registry: MappingProxyType[str, str] = MIXIN_REGISTRY,
    mixin_aliases: MappingProxyType[str, str] = MIXIN_ALIASES,
) -> ClassRecord | None:
    """Resolve a base-class name to its ClassRecord, when possible.

    Used by ``code_graph.py describe`` to walk inheritance through
    ``SpyglassMixin`` / ``Merge``. Resolution order:

    1. If ``name`` is a known alias (e.g. ``_Merge`` → ``Merge``), look
       up the canonical name in the registry.
    2. If the (resolved) name is in ``mixin_registry``, the registry path
       is authoritative — if no record matches the registered path,
       return None rather than silently picking a same-named class
       elsewhere.
    3. For names not in the registry, return the unique top-level record
       if there's exactly one match. Otherwise return None and let the
       caller annotate or warn.

    Prefer ``ClassIndex.resolve_base(name)`` in new code; the registries
    are consulted via the module-level constants either way.
    """
    return _resolve_base(name, index, mixin_registry, mixin_aliases)


def _smoke() -> int:
    """Two-line sanity check for the AST walk.

    Run with ``python skills/spyglass/scripts/_index.py`` (after exporting
    ``$SPYGLASS_SRC``). Prints class count + scan time. Anything richer
    is intentionally out of scope per the impl plan — deeper validation
    lands with the consumer subcommands.
    """
    import time

    src_root = resolve_src_root(None)
    t0 = time.perf_counter()
    index = scan(src_root)
    elapsed = time.perf_counter() - t0
    total = sum(len(v) for v in index.values())
    print(f"classes: {total} ({len(index)} unique names) under {src_root}")
    print(f"scan_time: {elapsed:.3f}s")
    return 0


if __name__ == "__main__":
    sys.exit(_smoke())
