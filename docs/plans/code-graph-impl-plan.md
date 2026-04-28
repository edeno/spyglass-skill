# Implementation plan — `code_graph.py` (source-only code-graph traversal)

**Date drafted:** 2026-04-25
**Date last updated:** 2026-04-26
**Status:** **Historical / shipped — superseded by the actual code.** Treat this plan as the design rationale that justified the work; for current behavior consult the code and tests, not this file. Routing copy in [skills/spyglass/references/feedback_loops.md](../../skills/spyglass/references/feedback_loops.md) ("Three graphs, three primitive families") and the machine-readable contract via `python3 skills/spyglass/scripts/code_graph.py info --json` are the user-facing source of truth.

**What shipped vs. what this plan said.** Most of the original plan landed as written; the divergences below all came from review-driven course corrections during execution and are not yet reflected in the body of this document.

- **`compare_versions.py` references stripped.** The plan assumed PR #15 would land first. It didn't, so the script doesn't exist in this PR. All references to it in user-facing skill content (and the not-found hint copy) were removed; the version-asymmetry workflow now routes through `describe --file <v0 path>` + `describe --file <v1 path>` plus reading the source.
- **Walks are record-aware, not qualname-keyed.** The plan described walks built on `parent_map` / `child_map` keyed by qualname. That design mixed v0/v1 records (e.g. both `LFPBandSelection` records merged in `child_map`), produced wrong file:line citations on `--up`, and over-cascaded through merge masters to sibling parts on `--down`. The shipped walk is a record-keyed BFS (`_bfs_walk_records`) with same-package preference for FK target resolution and a `skip_parts` marker through the part→master bridge.
- **`--down` semantic clarified as FK-impact cascade**, not containment-pure. Modifying a part propagates to its master and downstream consumers; entering a master via the part-bridge does NOT fan out to sibling parts (a separate marker prevents this). `--up` remains containment-ancestor with parts-as-upstream-contributors so `--up Master` surfaces the upstream pipelines feeding into a merge.
- **Provenance + warnings shipped.** Every JSON payload carries top-level `graph: "code"`, `authority: "source-only"`, `source_root` (or `null` for the static `info` payload), `truncated`, `truncated_at_depth`. Each node carries `record_id` (`<file>:<line>:<qualname>`) and `node_kind` (`merge_master` / `merge_part` / `nested_master` / `nested_part` / `lookup` / `manual` / `computed` / `imported` / `table` / `unknown`). A top-level `warnings` block lists same-qualname collisions resolved via same-package preference; `--fail-on-heuristic` (exit 5) refuses to guess. `not_found` payloads carry `suggestions` (Levenshtein close-matches).
- **Fourth subcommand: `info`.** `code_graph.py info --json` dumps the machine-readable contract — subcommand purposes, exit codes, enums (`node_kind_values`, `fk_edge_kinds`, `ownership_kinds`, `warning_kinds`), and per-payload-kind envelopes. Not in the original plan; added to make the contract self-describing for LLM consumption.
- **Exit codes: 0/2/3/4/5.** `5` = traversal needed a heuristic (only emitted under `--fail-on-heuristic`). `4` payloads now carry `suggestions`.
- **Real-Spyglass smoke fixtures.** Four fixtures gated on a real `--spyglass-src` (presence of `spyglass/lfp/v1/lfp.py`) cover the failure modes the qualname-keyed design missed: `--up LFPBandV1` cites v1, `--down LFPV1` reaches `RippleTimesV1`, `--down LFPV1` excludes sibling parts and v0 leaks, position pipelines chain to `LinearizedPositionV1`. Plus a schema-stability fixture that cross-checks `info`'s declared envelopes against actual top-level fields.

**Total fixtures shipped:** 37 (including 4 real-Spyglass smoke gates). 37/37 passing as of 5148d34.

---

**Original plan below; left as-is for design context.**

**Date:** 2026-04-25
**Status:** Historical — original pre-implementation draft.
**Branch:** continue on `feature/inquiry-time-navigation` (currently holds only the parent plan, [inquiry-time-navigation-plan.md](inquiry-time-navigation-plan.md)).
**Predecessors (still DRAFT, not merged to master at time of writing):**

- PR #15 `feature/version-discovery-script` — ships `compare_versions.py`, the script-style template this plan follows. Merge order will be `#15 → #14 → this`.
- PR #14 `feature/version-hallucination-policy` — ships SKILL.md Core Directive #2 ("read source before answering"). The directive is what makes a navigation primitive load-bearing rather than optional.

## Framing — three graphs, hallucinations from confusing them

The original motivation in [inquiry-time-navigation-plan.md](inquiry-time-navigation-plan.md) was to **prevent hallucinations by giving the agent fast traversal of the structures it would otherwise guess about.** Spyglass exposes at least three overlapping graphs to the agent, and most of the hallucinations we've measured come from one of two failure modes: (a) the agent confuses one graph for another, or (b) the agent has no way to traverse the relevant graph quickly enough to verify before answering.

| Graph | Authoritative source | Agent's access today | This plan |
| --- | --- | --- | --- |
| **Code graph** — classes, methods, bases, `definition` strings, `->` declarations | `src/spyglass/` AST | `Read`, `grep` — slow per-question, agent doesn't always do it | **In scope.** Ships `code_graph.py`. |
| **DB graph** — what DataJoint actually wired up at import time, including dynamic parts and runtime overrides | live DB connection (`Table.parents()` / `Table.descendants()` / `dj.Diagram`) | None at inquiry time (no DB) | **Deferred.** Design slot reserved; see [§ Deferred — other graphs and tools](#deferred--other-graphs-and-tools). |
| **Disk graph** — where artifacts live on disk (raw NWBs, analysis NWBs, kachery sandboxes, DLC dirs) | `$SPYGLASS_BASE_DIR` + path conventions in `settings.py` / `AnalysisNwbfile` | None at inquiry time (no fs access to user data) | **Deferred.** Same. |

The code graph and the DB graph are structurally similar but **not identical** — DataJoint resolves FK references via Python `eval()` against the import namespace at table-declaration time, so dynamic parts, aliased imports, and runtime FK overrides will diverge between source and DB. For most agent questions the code-graph approximation is sufficient; when it isn't, the agent must know the limit so it can flag the answer as code-grounded rather than DB-truthful.

This branch ships **`code_graph.py`**, a single source-only CLI with three subcommands anchored at three distinct code-graph question shapes:

1. **`code_graph.py describe <Class>`** — node view. Tier, bases, body-level methods, methods inherited from a curated set of Spyglass mixins (`SpyglassMixin`, `_Merge`), **plus structured field/key/rename introspection**: primary-key fields, non-PK fields, FK parents with projected-rename dicts (`merge_id → pos_merge_id`), and nested part tables. The structured output directly attacks the largest non-path hallucination class — wrong field names, projected-FK rename misses, merge-master vs part-table key shape confusion. Empirical justification: 11 evals likely closed (21, 51, 52, 54, 56, 57, 74, 75, 78, 80, 89 — see [§ Eval coverage](#eval-coverage) for the per-eval breakdown of "decisive" vs "absence-inference" closures). *Not* a complete method universe: datajoint base-class methods are annotated as "see datajoint API reference," not enumerated; dynamically-injected methods are invisible; aliased-import bases unresolved unless added to the registry.
2. **`code_graph.py path`** — edge traversal. Three modes: `--to A B` finds the FK path between two classes (closes eval 81's merge-hop elision); `--up CLASS` enumerates all upstream FK ancestors (closes evals 72, 73 — the dep-trace shape); `--down CLASS` enumerates all downstream FK descendants (closes eval 68 — the counterfactual cascade shape). Names every merge-master hop explicitly. AST-parsed from `definition` strings. Empirical justification: 5 evals likely closed (68, 72, 73, 76, 81 — see [§ Eval coverage](#eval-coverage)).
3. **`code_graph.py find-method <method-name>`** — reverse method index. Lists every class that defines `method-name` at body level, plus inherited-availability via `MIXIN_REGISTRY`. Closes the "where does this method come from?" / "is method ownership X or Y?" hallucination shape — different question from `describe`'s "what methods does class X have?" Direction, not the same lookup transposed. Empirical justification: 4 evals it provides decisive evidence for (21, 51, 80, 89 — overlapping with `describe` but answering the inverse direction; see [§ Eval coverage](#eval-coverage)).

The naming carries weight: `code_graph.py` makes the agent commit to *which graph* before reaching for the tool. Future `db_graph.py` and `disk_paths.py` (deferred) will mirror the same subcommand shape so the agent's mental model maps 1:1 across graphs.

Shared AST + FK-parsing + structured-field-parsing surface lives in `_index.py` ([§ Shared module — `_index.py`](#shared-module--_indexpy)). All three subcommands consume the same index.

A separate, lower-risk work item — extending `feedback_loops.md` to teach the manual three-step mixin lookup chain — is **not** in this branch's scope; it's a documentation-only intervention that lands independently and helps even users who can't run the scripts. See [§ Out-of-scope work items](#out-of-scope-work-items).

## Goals and non-goals

**Goals.**

- Ship `skills/spyglass/scripts/code_graph.py` — single CLI with three subcommands (`describe`, `path`, `find-method`) anchored at the code graph. No `import spyglass`, no DB connection, no cache.
  - `code_graph.py describe <Class>` prints file:line, tier, bases, body-level methods, methods inherited from registered Spyglass mixins, **plus structured field/key/rename output**: PK fields (with types and any auto-increment / default), non-PK fields, FK parents (with projected-rename dicts like `{"merge_id": "lfp_merge_id"}` parsed from `Foo.proj(...)` kwargs), and nested part tables. The literal `definition` string still ships verbatim for callers who want to see the raw source. Datajoint bases annotated, not enumerated. Output is exhaustive within scope; everything outside scope is annotated, not omitted-without-warning.
  - `code_graph.py path` has three modes: `--to A B` (FK path between two classes), `--up CLASS` (all upstream ancestors), `--down CLASS` (all downstream descendants). All three AST-parse `definition` strings under `src/spyglass/`. Names every merge-master hop explicitly — `LFPV1 → LFPBandV1` is wrong; `--to LFPV1 LFPBandV1` must produce `LFPV1 → LFPOutput.LFPV1 → LFPBandSelection → LFPBandV1`.
  - `code_graph.py find-method <method-name>` prints every class that defines the method at body level (with file:line), plus inherited-availability for methods on registered mixins (e.g., `fetch_nwb` defined on `SpyglassMixin` → "available on every subclass that inherits from SpyglassMixin"). Closes "method ownership" hallucinations: `where does this come from`, `mixin vs concrete`, `did this method move/disappear in v1`.
- Ship `skills/spyglass/scripts/_index.py` — shared module that AST-walks `src/spyglass/` once per process invocation, returning `{class_name: [ClassRecord]}`. All three subcommands consume it. `ClassRecord` carries structured PK / non-PK / FK / rename fields (not just the raw `definition` string), built by parsing `definition` once at scan time.
- Document blind spots per subcommand in the script's docstring, with the same candor as `compare_versions.py`'s "What this catches / does NOT catch" sections. Be explicit that `code_graph.py` answers code-graph questions only — when the agent needs DB-resolved truth (dynamic parts, runtime FK overrides) or on-disk paths, the docstring points at the deferred `db_graph.py` / `disk_paths.py` slots.
- Land routing copy in `feedback_loops.md` that teaches the **three-graph orientation** (code / DB / disk), so the agent picks the right graph before the right question shape. Reserve named slots for the deferred graph primitives even though only the code-graph one ships now.
- Ship regression fixtures in a new `tests/test_code_graph.py` (separate from `test_validator_regressions.py` — see [§ Tests](#tests--new-file-teststest_code_graphpy)) following the `compare_versions.py` fixture-style (synthetic fake-spyglass tree, subprocess invocation, assert on parsed JSON). Four fixtures for `code_graph.py path` (`--to` direct, `--to` merge-hop, multi-file ambiguity, `--up`/`--down` tree walk), four for `code_graph.py describe` (mixin methods, datajoint annotation, multi-file ambiguity, structured PK/FK-rename parsing), two for `code_graph.py find-method` (body-level hit + mixin inherited-availability, no-class-defines exit-4 path).

**Non-goals.**

- Building `db_graph.py` (DB-resolved structure) or `disk_paths.py` (artifact-path resolution). Both deferred with design slots reserved — see [§ Deferred — other graphs and tools](#deferred--other-graphs-and-tools).
- (No longer a non-goal — `--up`/`--down` un-deferred. Three real evals — 68 `counterfactual-ripple-electrode-set`, 72 `dep-trace-decoding-output`, 73 `dep-trace-lfpbandv1` — demand tree mode. The "defer until eval shape demands it" trigger has been met.)
- Caching. AST walk is 0.4s; a JSON cache costs more in invalidation footguns than it saves in latency. `_index.py` caches within a single process invocation via `lru_cache(maxsize=1)`, but does not persist across invocations.
- Walking *third-party* (datajoint) base classes. `code_graph.py describe` annotates `dj.Computed`, `dj.Manual`, `dj.Lookup`, `dj.Imported`, `dj.Part` as "see datajoint API reference" but does not AST-walk into datajoint source. The mixin registry covers Spyglass's own mixins (`SpyglassMixin`, `_Merge`) where the highest-leverage gap lives.
- Resolving aliased imports of base classes (`from .utils import SpyglassMixin as Mixin` then `class X(Mixin, ...):`). Documented blind spot. Add aliased forms to the registry as the need arises.
- Auto-deriving `KNOWN_CLASSES` from the index. Tempting (closes the manual-curation drift gap) but separable; defer to its own follow-up commit only after `_index.py` proves it handles parts / `_Merge` / mixins correctly.

## Out-of-scope work items

These are real improvements but lower-risk and independently shippable; not in this branch.

- **Strategy-C feedback_loops.md prose extension.** A ~12-line addition to the "Verify behavior, trust identity" loop teaching the manual three-step mixin lookup chain (grep the class file → grep `dj_mixin.py` → grep `dj_merge_tables.py` → fall back to datajoint reference). Helps even users who can't run the scripts. Lands as its own PR after this branch merges.
- **SKILL.md discovery one-liner fix.** The current `python -c "import spyglass, os; print(os.path.dirname(spyglass.__file__))"` returns the package dir, not the parent dir that `--src` consumers want. A separate one-line edit to call out the double-`dirname` form for tooling. Independent.
- **`KNOWN_CLASSES` auto-derivation from `_index.py`.** Closes the validator's manual-curation drift gap. Lands as a separate commit after `_index.py` is proven against `code_graph.py describe`'s mixin registry — at that point `_index.py` already produces every record `KNOWN_CLASSES` needs (`name`, `file`, `line`, `tier`, `bases`). The migration is roughly: `validate_skill.py` imports `_index.scan` instead of reading the hand-curated dict; `_classify_method_call` and `check_class_files_exist` re-key on `qualname` to handle parts cleanly; the existing `KNOWN_CLASSES` dict becomes an override / opt-out list for any class the auto-scan can't handle. Estimated <100 lines + migration of the existing 60-ish manual entries. Out of scope for this branch because it couples two unrelated reviews (toolkit correctness + validator gate behavior).

## Eval coverage

Empirical justification for what ships in this branch. Each tool's case is grounded in specific evals from `skills/spyglass/evals/evals.json`, not abstract problem categories.

**Caveat on "addressable."** The tooling provides decisive evidence — file:line citations, structured fields, exit-code-4 contracts — that the agent can use to answer correctly. It does not *force* a correct answer. Closure depends on: (a) the agent reaching for the right subcommand, (b) interpreting the output conservatively (e.g., "method absent from the listed inherited set" → "no" rather than guessing), and (c) the routing copy in `feedback_loops.md` being loaded for the relevant question shape. Eval coverage below is "likely closes given correct tool use," not "guaranteed correct answer."

### `code_graph.py describe` — 11 evals likely closed by structured output + mixin resolution

| Eval | Name | What describe surfaces |
| --- | --- | --- |
| **21** | `adversarial-hallucination-resistance` | "Does `Session` have `fetch_timeseries()`?" — body-level + SpyglassMixin-inherited methods listed; `fetch_timeseries` absent. Agent must infer "no" from absence in the listed sets. |
| **51** | `merge-method-misattribution` | "Does `PositionOutput` have `get_restricted_merge_ids`?" — `_Merge`-inherited methods listed; the method is SpikeSortingOutput-only, so absent. Same absence-inference shape as 21. |
| **52** | `is-this-a-merge-lookalike` | "Why does `MuaEventsV1.merge_get_part(...)` raise AttributeError?" — bases don't include `_Merge`; explanation is "not a merge table." |
| **54** | `classify-lfpselection` | "Is `LFPSelection` Manual/Lookup/Computed/Imported?" — `tier` field is decisive. |
| **56** | `classify-positionoutput-merge` | "What kind of table is `PositionOutput`? No `populate()`." — `_Merge` base + tier. Decisive. |
| **57** | `classify-lfpband-role` | "Is `LFPBandV1` compute or output?" — tier. Decisive. |
| **74** | `schema-pk-electrode` | "Primary key of `Electrode`?" — `pk_fields` array is decisive (was previously parsed from the literal `definition` string; now structured). |
| **75** | `schema-pk-firfilterparameters` | Same shape. Decisive. |
| **78** | `schema-part-tables-probe` | "Part tables of `Probe`?" — `parts` field is decisive. |
| **80** | `abstain-spyglassmixin-get-pk` | "Is there `.get_pk()` on SpyglassMixin?" — inherited methods listed; absent. Absence-inference. |
| **89** | `abstain-v1-naming-extrapolation` | "Is it `SpikeSortingV1.populate()`?" — exit code 4 (`not_found`) is decisive about the class name. |

The mixin-resolution capability is what makes evals 21, 51, 80 viable — without inherited-method enumeration, the agent would give wrong "no" answers to questions about real inherited methods. Eval 89 specifically exercises the exit-code-4 contract. The "decisive" cases (54, 56, 57, 74, 75, 78, 89) leave little room for interpretation; the "absence-inference" cases (21, 51, 80) require the agent to treat exhaustive listing of an enumerated set as evidence of absence.

### `code_graph.py find-method` — 4 evals it provides decisive evidence for (different direction from describe)

| Eval | Name | What find-method surfaces |
| --- | --- | --- |
| **21** | `adversarial-hallucination-resistance` | `find-method fetch_timeseries` returns exit 4 — decisive that no Spyglass class defines it. (Complementary to `describe Session`'s absence-inference; this is direct.) |
| **51** | `merge-method-misattribution` | `find-method get_restricted_merge_ids` returns SpikeSortingOutput as the *only* owner — decisive that PositionOutput doesn't have it (directly listed ownership, not inferred from absence). |
| **80** | `abstain-spyglassmixin-get-pk` | `find-method get_pk` returns exit 4 — decisive that no class defines this. The exit-4 hint references datajoint, so agent doesn't conclude "method doesn't exist anywhere." |
| **89** | `abstain-v1-naming-extrapolation` | `find-method populate` returns datajoint-base hint via exit-4-with-message — agent learns to consult datajoint docs rather than guess at Spyglass-side method shape. Overlaps with describe's exit-4 on the class name. |

`find-method` overlaps with `describe` on these four evals — different lookup direction, similar correctness outcome. The unique value is when the agent has the *method name* but doesn't know which class owns it (eval 51 in particular: agent saw `SpikeSortingOutput.get_restricted_merge_ids()` and is asking sideways "does PositionOutput have it?"). For "method ownership" hallucinations (mixin-vs-concrete confusion, v0/v1 method moves), this is a more direct entry point than describe's absence-inference.

### `code_graph.py path` — 5 evals likely closed across all three modes

| Eval | Name | Mode |
| --- | --- | --- |
| **76** | `schema-dep-probe-electrode` | `--to Electrode Probe` — surfaces the FK with declaring file:line. Decisive. |
| **81** | `abstain-ripple-direct-dependency` | `--to LFPV1 RippleTimesV1` — the canonical merge-hop-elision case. Decisive when the agent reaches for the tool. |
| **68** | `counterfactual-ripple-electrode-set` | `--down LFPV1` — enumerates downstream cascade. Decisive that a given table is or isn't reachable. |
| **72** | `dep-trace-decoding-output` | `--up DecodingOutput.ClusterlessDecodingV1` — full upstream dep-trace including selections + parameter tables. |
| **73** | `dep-trace-lfpbandv1` | `--up LFPBandV1` — same shape, different starting point. |

The three-mode design (`--to` / `--up` / `--down`) reflects three distinct eval shapes; the original "defer tree mode" plan would have left evals 68, 72, 73 unaddressed.

### Borderline / partial matches (~7 evals)

`describe` partially helps with 7, 28, 55, 62, 64, 79; `path` partially helps with 77 (filter coefficients table — `--up` would surface it). These count as bonus coverage, not justification, because each has a non-toolkit answer the agent can already produce.

### Out of scope (~74 evals)

Runtime debugging, parameter semantics, workflow, ingestion, env/config errors. The toolkit explicitly does NOT answer "why did populate fail" or "what does this parameter mean." Keeping these out of scope is the right discipline — `code_graph.py` is for code-graph traversal, full stop.

### What this means for the deferred items

`db_graph.py` and `disk_paths.py` have no current eval matches. This is consistent with the plan's "build when an eval demands it" trigger. After this branch ships, watch for:

- **DB-vs-code divergence shapes** (would justify `db_graph.py`) — currently 0 evals.
- **Path-shape questions** (would justify `disk_paths.py`) — currently 0 evals; eval 41 is config-related but not artifact-path.

If those shapes emerge in eval rounds N+1 or later, the deferred-trigger criteria fire. Until then, don't pre-build.

## Repo layout changes

```text
skills/spyglass/
├── scripts/
│   ├── _index.py                         # NEW — shared AST scan + FK + base parsing
│   ├── code_graph.py                     # NEW — describe + path + find-method subcommands over the code graph
│   └── README.md                         # modified — add code_graph.py row + 3-graph orientation
├── references/
│   └── feedback_loops.md                 # modified — three-graph orientation, code-graph entry, deferred slots for db / disk
└── tests/
    └── test_code_graph.py                # NEW — tool-contract tests for code_graph.py + _index.py (see § Tests)
```

One CLI script (`code_graph.py`) with three subcommands (`describe`, `path`, `find-method`). The rename and consolidation are doing real work: every invocation forces the agent to commit to *which graph* before *which question*. Future `db_graph.py` and `disk_paths.py` (deferred) will mirror the same subcommand shape so the agent's mental model maps 1:1 across graphs.

`_index.py` is a first-class artifact in this branch (three subcommand consumers plus the structured-field parser justify the shared module). Build order in [§ Rollout](#rollout) is `_index.py` first, then `code_graph.py` skeleton + the three subcommands one per commit, so each subcommand can pressure-test the shared shape independently.

No `cache/` directory. No `cache/.gitignore`. The 0.4s walk is rebuilt every invocation; `_index.py` caches within a single process via a module-level `@functools.lru_cache` so that downstream callers (e.g. `describe` resolving multiple bases, or `find-method` building the reverse index) don't re-scan.

## Shared module — `_index.py`

Single-purpose helper module. Not a CLI; imported by all three `code_graph.py` subcommands (`describe`, `path`, `find-method`). Sketch:

```python
# skills/spyglass/scripts/_index.py
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

@dataclass(frozen=True)
class FieldSpec:
    name: str          # e.g. "curation_id"
    type: str          # e.g. "int", "varchar(64)", "uuid"
    default: str | None    # textual default, if assigned in the definition
    auto_increment: bool   # for int PKs

@dataclass(frozen=True)
class FKEdge:
    parent: str        # e.g. "LFPOutput" — the textual referenced class
    qualname_target: str   # qualname when resolvable (e.g. "LFPOutput.LFPV1");
                           # falls back to `parent` otherwise
    kind: str          # "fk" | "proj" | "nested_part" | "merge_part"
    in_pk: bool        # is this FK above the `---` divider in definition?
    renames: dict[str, str]  # parsed from .proj(new='old', ...); empty for plain refs
    evidence: str      # the textual line from definition (e.g. "-> LFPOutput.proj(...)")
    evidence_line: int # absolute line in the source file where this edge appears

@dataclass(frozen=True)
class ClassRecord:
    name: str          # short name, e.g. "BodyPart"
    qualname: str      # fully qualified, e.g. "DLCProject.BodyPart" for parts;
                       # equals `name` for top-level. First-class field — see § Qualified class identity.
    master: str | None # for nested parts: master class name. None for top-level.
    file: str          # path relative to src_root
    line: int          # ClassDef.lineno
    bases: tuple[str, ...]      # textual base names: "SpyglassMixin", "dj.Computed"
    tier: str | None            # "Manual" | "Lookup" | "Computed" | "Imported" | "Part" | None
    definition: str | None      # raw literal definition string (preserved verbatim for callers
                                # that want the source); structured fields below are parsed once
                                # at scan time so consumers don't re-parse.
    pk_fields: tuple[FieldSpec, ...]      # parsed body-level fields above the `---` divider
    non_pk_fields: tuple[FieldSpec, ...]  # body-level fields below `---`
    fk_edges: tuple[FKEdge, ...]          # all `->` references with kind/renames/evidence
    methods: tuple[tuple[str, int], ...]  # body-level (def name, line) pairs
    parts: tuple[str, ...]      # nested ClassDef qualnames (e.g. "LFPOutput.LFPV1")

@lru_cache(maxsize=1)
def scan(src_root: Path) -> dict[str, list[ClassRecord]]:
    """AST-walk src_root/spyglass/, return {class_name: [records]}.
    Multi-file class names map to a list (no silent first-wins). lru_cache
    means a single process invocation pays the 0.4s walk once."""

def is_foreign_key(line: str) -> bool:
    """Mirror datajoint.declare.is_foreign_key (declare.py:144)."""

def parse_definition(definition: str, file: str, base_lineno: int) -> tuple[
    tuple[FieldSpec, ...],   # pk_fields
    tuple[FieldSpec, ...],   # non_pk_fields
    tuple[FKEdge, ...],      # fk_edges (with kind, renames, evidence)
]:
    """Parse a definition string into structured fields + FK edges.

    Splits on the `---` divider. Above-divider lines are PK; below are non-PK.
    Each `-> X` line becomes an FKEdge with kind "fk"; `-> X.proj(new='old')`
    becomes kind "proj" with renames={'new': 'old'} (parsed via ast.parse on
    the proj body, not regex — handles multi-kwarg, nested expressions). The
    `kind` is upgraded to "nested_part" / "merge_part" by the scanner after
    cross-referencing with the AST's nested-ClassDef structure.
    """

def resolve_base(name: str, index, mixin_registry) -> ClassRecord | None:
    """Resolve a base-class name to its ClassRecord. Used by `code_graph.py describe`
    to walk inheritance through SpyglassMixin / _Merge."""

def child_map(index) -> dict[str, list[str]]:
    """Inverse of the parent map. Used by `code_graph.py path --down`."""

def reverse_method_index(index, include_inherited: bool = False) -> dict[str, list[ClassRecord]]:
    """Build a {method_name: [classes that define it at body level]} index.
    Used by `code_graph.py find-method`. With include_inherited=True, also
    folds in MIXIN_REGISTRY-resolved bases so an agent asking 'where does
    fetch_nwb come from' gets 'SpyglassMixin' rather than every subclass.
    """
```

Contract guarantees:

- **Pure.** No imports from `spyglass`, `datajoint`, or any package not in stdlib. Runs against a checked-out source tree on a machine with neither installed.
- **Bounded.** Ignores `__pycache__/`, hidden dirs, and `*.pyc`. Skips files with `SyntaxError` rather than raising (matches `compare_versions.py`).
- **Cached per-process** via `lru_cache`. Don't pickle to disk. Multiple CLI invocations each pay 0.4s once.
- **Multi-file class returns a list,** not a single record. Consumers decide whether to disambiguate, error, or union.

Built first as a standalone module (commit 1 in [§ Rollout](#rollout)) so all three subcommands consume one stable contract from day 1. The structured-field parser and the FK-edge schema with `kind`/`renames`/`evidence` are fixed before any consumer exists, eliminating the inline-then-extracted drift risk.

### `parse_definition` coverage matrix

`parse_definition` must handle every shape that appears in real Spyglass `definition` strings. Enumerate the cases up-front; the developer builds the parser by walking down this list with a fixture per case.

**Field shapes (PK side, above `---`, and non-PK side, below `---`):**

- `name: int` — bare type.
- `name: int auto_increment` — auto-increment annotation.
- `name = -1: int` — default value (numeric).
- `name = '': varchar(1000)` — default value (string).
- `name: varchar(64)` — parameterized type.
- `name: enum('a', 'b')` — enum type.
- `name: blob` — opaque type.
- `name: uuid` — uuid (merge masters use this).
- `name: float unsigned` — type modifiers.
- `name: int  # this is a comment` — inline comments after the type.

**FK shapes:**

- `-> Other` — plain reference.
- `-> Other.Part` — part-table reference.
- `-> Other.proj(new='old')` — single-kwarg projection.
- `-> Other.proj(new1='old1', new2='old2')` — multi-kwarg projection.
- `-> Other.proj(\n    new='old'\n)` — multiline projection (must be flattened pre-parse).
- `-> [nullable] Other` — DataJoint nullable-FK option.
- `-> Other  # comment` — comment after FK.

**Edge cases:**

- Empty `definition` (some test classes have no body content).
- `definition` with no `---` divider (table has no non-PK fields, only PK).
- `definition` with multiple `---` dividers (malformed source — log and skip).

The developer builds the parser by writing a fixture for each shape in `test_code_graph.py`, then iterating until all pass. Real-Spyglass smoke-test (in [§ Validation](#validation) step 5) catches anything missed by the synthetic fixtures.

### Graceful degradation when `$SPYGLASS_SRC` is unset

Mirror `compare_versions.py`'s pattern: `_resolve_src_root` exits with code `2` (usage error) and the multi-form error message documented in [§ Pip install vs. git checkout](#pip-install-vs-git-checkout-all-subcommands). Don't try to auto-discover from `import spyglass` — that would defeat the source-only constraint and trigger DJ schema registration on import.

The pre-commit hook is graceful about missing `$SPYGLASS_SRC` (it skips the smoke step rather than failing the commit), matching the existing validator's behavior. `code_graph.py` itself errors loudly — running the script without `--src` or `$SPYGLASS_SRC` is always a usage bug, not a no-op.

## `code_graph.py path` subcommand — FK edge traversal

### `code_graph.py path` contract

`--to A B` mode (closes eval 81 — merge-hop elision):

```text
$ python code_graph.py path --to LFPV1 LFPBandV1
LFPV1 (src/spyglass/lfp/v1/lfp.py:42)
  └─> LFPOutput.LFPV1 [merge part]  (src/spyglass/lfp/lfp_merge.py:18)
      └─> LFPBandSelection           (src/spyglass/lfp/analysis/v1/lfp_band.py:26)
          └─> LFPBandV1              (src/spyglass/lfp/analysis/v1/lfp_band.py:71)
```

```text
$ python code_graph.py path --to RippleTimesV1 LFPV1
No FK path from RippleTimesV1 to LFPV1.
(Try the reverse: LFPV1 → RippleTimesV1.)
```

`--up CLASS` mode (closes evals 72, 73 — full upstream dep-trace):

```text
$ python code_graph.py path --up LFPBandV1
LFPBandV1 (src/spyglass/lfp/analysis/v1/lfp_band.py:71)
  ancestors (depth ≤ 12):
  ├── LFPBandSelection           src/spyglass/lfp/analysis/v1/lfp_band.py:26
  │   ├── LFPOutput [merge proj] src/spyglass/lfp/lfp_merge.py:14
  │   │   └── LFPOutput.LFPV1    src/spyglass/lfp/lfp_merge.py:18
  │   │       └── LFPV1          src/spyglass/lfp/v1/lfp.py:42
  │   │           └── LFPSelection ...
  │   └── FirFilterParameters    src/spyglass/common/common_filter.py:N
  └── (additional FK roots if any)
```

`--down CLASS` mode (closes eval 68 — counterfactual cascade enumeration):

```text
$ python code_graph.py path --down LFPV1
LFPV1 (src/spyglass/lfp/v1/lfp.py:42)
  descendants (depth ≤ 12):
  └── LFPOutput.LFPV1            src/spyglass/lfp/lfp_merge.py:18
      └── LFPBandSelection       src/spyglass/lfp/analysis/v1/lfp_band.py:26
          └── LFPBandV1          src/spyglass/lfp/analysis/v1/lfp_band.py:71
              └── RippleLFPSelection ...
                  └── RippleTimesV1 ...
```

Multi-file ambiguity (same exit-3 contract for all three modes):

```text
$ python code_graph.py path --to BodyPart Skeleton
Class 'BodyPart' is ambiguous (defined in 6 files):
  src/spyglass/position/v1/position_dlc_project.py:34   (top-level dj.Manual)
  src/spyglass/position/v1/position_dlc_project.py:88   (nested dj.Part of DLCProject)
  src/spyglass/position/v1/position_dlc_pose_estimation.py:41 (nested dj.Part of DLCPoseEstimation)
  ...
Re-run with --from-file <path> to disambiguate.
```

### `code_graph.py path` CLI

```text
code_graph.py path (--to FROM TO | --up CLASS | --down CLASS) [--src PATH]
         [--from-file PATH] [--to-file PATH] [--file PATH]
         [--max-depth N] [--json]
```

- One of `--to`, `--up`, `--down` is required (mutually exclusive group via argparse `add_mutually_exclusive_group(required=True)`).
- `--src` mirrors `compare_versions.py`: defaults to `$SPYGLASS_SRC`, errors if neither is set.
- `--from-file` / `--to-file` disambiguate ambiguous names in `--to` mode. `--file` disambiguates the single class in `--up` / `--down` mode. Accept paths relative to `src/`.
- `--max-depth` defaults to 12 (longest known real chain in Spyglass is ~8 hops); guard against pathological cycles. Applies to all three modes.
- `--json` emits a machine-readable JSON document. See [§ Output formats](#output-formats-all-subcommands) for the schema (different `kind` discriminator per mode).

**Exit codes** (departing from `compare_versions.py`'s exit-0-everywhere — `code_graph.py` outputs structured data, so downstream automation benefits from real status codes):

- `0` — happy path (path found and printed) **or** "no FK path between A and B" (a legitimate, well-formed answer to a well-formed query).
- `2` — usage error: missing required arg, malformed `--from-file` path, `--src` doesn't contain `spyglass/`, etc. argparse's default for usage errors.
- `3` — unresolved ambiguity: class name resolves to >1 file and no `--from-file` / `--to-file` hint was given. Output (human or JSON) lists the candidates so the caller can re-invoke with a hint.
- `4` — class not found in the index (typo, removed in this Spyglass version, etc.). Output names the missing class and suggests `compare_versions.py` for cross-version lookups.

Documenting these lets downstream tests assert specific failure modes rather than parsing stdout for substrings.

### Implementation outline

Single-file script, target ~250 lines (up from ~150 in the original plan — three modes, JSON output, exit codes). The bulk of the AST + FK + base parsing lives in `_index.py`; this script is dispatch + tree formatters.

```python
# code_graph.py
def main():
    args = parse_args()                         # subparsers: describe | path | find-method
    dispatch = {
        "path":         cmd_path,
        "describe":     cmd_describe,
        "find-method":  cmd_find_method,
    }
    return dispatch[args.cmd](args)

def cmd_path(args):
    if args.to:    return _path_to(args.to[0], args.to[1], ...)
    if args.up:    return _path_up(args.up, ...)
    if args.down:  return _path_down(args.down, ...)

def cmd_describe(args):                         # node view + structured fields + inheritance walk
    ...

def cmd_find_method(args):                      # reverse method index via _index.reverse_method_index
    ...

def _path_to(src, dst, ...):                    # BFS via _index.parent_map; existing eval 81 case
def _path_up(cls, max_depth, ...):              # BFS upward via _index.parent_map; eval 72/73
def _path_down(cls, max_depth, ...):            # BFS downward via _index.child_map; eval 68
def _format_path_to_human(...):                 # arrow renderer
def _format_tree_human(...):                    # ├── └── tree renderer for --up/--down
def _format_path_to_json(...):                  # path JSON shape
def _format_tree_json(...):                     # ancestors / descendants JSON shape
```

`_index.py` exposes `child_map` (inverse of `parent_map`) for `--down` mode and `reverse_method_index` for `find-method`. Both are derivable from the same scan; exposed as `lru_cache`d functions taking the index dict.

### Parsing rules for `->` declarations

Spyglass `definition` strings carry FKs as `-> Other` or `-> Other.proj(...)`. Before defining our own rules, note how DataJoint itself parses them — see [§ DataJoint source review](#datajoint-source-review) below. The short version: DJ uses `pyparsing` to grab `restOfLine` after `->`, then resolves the captured text via Python `eval()` against the table's *import namespace*. A source-only script cannot `eval()` (no namespace, no DB), so the parser is necessarily a static approximation. The rules below define the approximation and the blind-spots section pins what it can't reach.

The parser must handle:

1. **Plain reference.** `-> LFPSelection` → parent is `LFPSelection`.
2. **Projected merge reference.** `-> LFPOutput.proj(lfp_merge_id='merge_id')` → parent is `LFPOutput` (the merge master). Annotate the hop as `[merge proj]` when rendered. We strip the `.proj(...)` suffix textually rather than evaluating it; column-rename semantics don't affect the graph.
3. **Part-table reference.** `-> Master.Part` → parent is `Master.Part` (a part class). Resolve `Master.Part` to its declaring file by checking nested `ClassDef` nodes inside `Master`'s body during the scan.
4. **Comment-stripping.** `definition` strings often have `#` comments after the FK; strip everything after `#` per line before parsing. DataJoint's own `is_foreign_key` (declare.py:144) handles this by checking that `->` isn't preceded by `"`, `#`, or `'`; we mirror the rule.
5. **Multiline projection bodies.** `-> Foo.proj(\n    bar='baz'\n)` — flatten the multiline declaration to a single logical FK before regex-matching, otherwise the parser splits the parent name from its `.proj(...)` suffix.
6. **Aliased imports.** A class may be imported as `from .lfp import LFPOutput as Output` and referenced in `definition` as `-> Output`. We can't resolve aliases without import (see blind-spot #7 below); we'd report `Output` as the parent and fail to find it in the scan. In practice Spyglass uses the canonical names; document the case.

Use a regex against per-line stripped text rather than re-implementing DataJoint's grammar: `^\s*->\s*(\w+(?:\.\w+)?)`. Capture the name; ignore the `.proj(...)` suffix for graph purposes.

### Path-finding algorithm

The graph is the directed `child → parent` map (each FK in `definition` adds an edge). The inverse `parent → children` map is derived from the same scan and used for `--down`.

**`--to FROM TO`:** BFS from `TO_CLASS` walking parents until `FROM_CLASS` is hit or depth > `--max-depth`, then reverse the result for printing. (A real Spyglass chain reads left-to-right in user terms — `LFPV1 → LFPOutput.LFPV1 → LFPBandSelection → LFPBandV1` — but the parent map naturally walks the other direction.) If `FROM == TO`, print `(same class)` and exit 0. If multiple paths exist (downstream class with two FKs to the same upstream root), print shortest; document in blind-spots.

**`--up CLASS`:** BFS from `CLASS` walking parents, collect all visited nodes with their depth and parent edges. Render as a tree using box-drawing characters (`├── └── │`); JSON renders as a flat list of nodes plus an edge list for caller-side reconstruction. Cycles in the FK graph are theoretically impossible (DJ rejects them at declaration time), but the visited-set guard catches any pathological case from a malformed `definition` string.

**`--down CLASS`:** symmetric to `--up`, but walks the inverse `parent → children` map. Same tree / JSON output shape, different `kind` discriminator.

For all three modes, multi-file ambiguity in the input class name is resolved before the walk starts — the BFS only ever runs against a uniquely-identified `ClassRecord`.

### Multi-file class disambiguation

Reuse `compare_versions.py`'s pattern: when a class name resolves to >1 file, list every match with file:line and exit with a "specify with `--from-file` / `--to-file`" prompt. Do not silently pick the first. Multi-file unions on the FK side (a `BodyPart` in `DLCProject` vs `BodyPart` in `Skeleton`) will produce different FK shapes, and silently picking one would mislead the same way compare_versions's pre-fix BodyPart-union output did (see PR #15 commit `caae681`).

### `code_graph.py path` blind spots

Docstring section, mirroring `compare_versions.py`'s "What this catches / does NOT catch" shape. Initial blind-spots list to ship with:

1. **Mixin / base-class FKs.** `SpyglassMixin`, `_Merge`, `dj.Lookup`, etc. don't add FKs but DO add inherited methods. `code_graph.py path` only walks FKs, so mixin-only relationships (e.g., `SpyglassMixin.fetch_nwb` being available on every subclass) are invisible. Read the base class file when method-availability matters.
2. **Cross-pipeline merges via dynamic part registration.** Some merge masters lazily register parts (e.g., DecodingOutput parts added at import time). The static AST scan sees only what's in the source tree at scan time. Should be fine in practice but document.
3. **Runtime-overridden FKs.** Rare, but a table whose `key_source` is overridden in Python rather than declared in `definition` won't be reflected. Out of scope.
4. **Path ambiguity.** Multiple FK paths between two classes — the script picks shortest. Read the source for full topology when this matters; the pipeline references file documents canonical chains.
5. **Cross-class redesigns** (same blind spot as `compare_versions.py` #1). v0 `Curation` is not the same node as v1 `CurationV1`; the graph won't link them. Out of scope.
6. **Inheritance in `definition`.** Some Spyglass tables inherit a parent's `definition` via Python class inheritance rather than re-declaring FKs. The AST walk reads each `ClassDef.body`'s string-assigned `definition` only; inherited definitions are invisible. Document; if this matters in a real eval, add a follow-up that resolves inherited definitions.
7. **Expression-form refs we can't resolve.** DataJoint resolves the text after `->` via Python `eval()` against the table's import namespace (`datajoint/declare.py:177`). A static parser sees only the textual ref-table; aliased imports (`from .lfp import LFPOutput as Output` then `-> Output`), module-qualified names (`-> mod.Foo`), and any expression form richer than `Name`/`Name.Name`/`Name.proj(...)` are unresolvable from source alone. In practice Spyglass uses the canonical names directly, so this is a small surface; if a smoke-test against the live Spyglass tree finds an unresolvable ref, log it and skip that edge rather than crash.

## `code_graph.py describe` subcommand — node view + mixin resolution

### `code_graph.py describe` contract

```text
$ python code_graph.py describe CurationV1
CurationV1   src/spyglass/spikesorting/v1/curation.py:23
  bases:
    SpyglassMixin   src/spyglass/utils/dj_mixin.py:N    (resolved)
    dj.Computed                                          (datajoint — see API reference)
  tier: Computed
  definition:
    -> SpikeSortingSelection
    curation_id: int auto_increment
    ---
    parent_curation_id = -1: int
    analysis_file_name: varchar(64)
    object_id: varchar(40)
    merges_applied: blob
    description = '': varchar(1000)
  body-level methods:
    insert_curation       curation.py:74
    get_curation_key      curation.py:128
    get_merged_sortings   curation.py:172
  inherited from SpyglassMixin (src/spyglass/utils/dj_mixin.py):
    fetch_nwb             dj_mixin.py:142
    cautious_delete       dj_mixin.py:198
    __lshift__            dj_mixin.py:267   # the << operator (upstream restrict)
    __rshift__            dj_mixin.py:278   # the >> operator (downstream restrict)
    [...]
  inherited from dj.Computed: see datajoint API reference
```

```text
$ python code_graph.py describe LFPOutput
LFPOutput   src/spyglass/lfp/lfp_merge.py:14
  bases:
    _Merge          src/spyglass/utils/dj_merge_tables.py:N    (resolved)
    SpyglassMixin   src/spyglass/utils/dj_mixin.py:N           (resolved)
    dj.Manual                                                   (datajoint — see API reference)
  tier: Manual (merge master)
  definition:
    merge_id: uuid
    ---
    source: varchar(32)
  parts:
    LFPOutput.LFPV1     lfp_merge.py:22
    LFPOutput.ImportedLFP  lfp_merge.py:30
  body-level methods:
    (none)
  inherited from _Merge (src/spyglass/utils/dj_merge_tables.py):
    merge_get_part        dj_merge_tables.py:N
    merge_restrict        dj_merge_tables.py:N
    merge_delete          dj_merge_tables.py:N
    [...]
  inherited from SpyglassMixin: [...]
  inherited from dj.Manual: see datajoint API reference
```

```text
$ python code_graph.py describe BodyPart
Class 'BodyPart' is ambiguous (defined in 6 files):
  src/spyglass/position/v1/position_dlc_project.py:34   (top-level dj.Manual)
  src/spyglass/position/v1/position_dlc_project.py:88   (nested dj.Part of DLCProject)
  ...
Re-run with --file <path> to disambiguate.
```

### `code_graph.py describe` CLI

```text
code_graph.py describe <CLASS_NAME> [--src PATH] [--file PATH]
            [--no-inherited] [--include-private] [--json]
```

- `<CLASS_NAME>` is positional and required.
- `--src` mirrors `code_graph.py path` / `compare_versions.py`.
- `--file` disambiguates ambiguous names; same path-relative-to-`src/` semantics as `code_graph.py path`'s `--from-file`.
- `--no-inherited` suppresses the inherited-methods sections (sometimes the agent only wants body-level).
- `--include-private` includes `_*` methods in both body-level and inherited sections (default: skip, matching `compare_versions.py`).
- `--json` emits a machine-readable JSON document. See [§ Output formats](#output-formats-all-subcommands) for the schema.

**Exit codes** match `path` — `0` for found, `2` for usage error, `3` for unresolved ambiguity, `4` for class not in index.

### Mixin registry

A small hand-curated dict, paralleling `KNOWN_CLASSES` in the validator:

```python
# skills/spyglass/scripts/_index.py — module-level
MIXIN_REGISTRY = {
    "SpyglassMixin":      "spyglass/utils/dj_mixin.py",
    "_Merge":             "spyglass/utils/dj_merge_tables.py",
    # Aliases for the same mixins under common import-as forms;
    # populate as real Spyglass usage demands.
}

DATAJOINT_BASES = {
    # Annotated, not walked. `code_graph.py describe` prints "see datajoint API reference."
    "dj.Manual", "dj.Lookup", "dj.Computed", "dj.Imported", "dj.Part",
    "Manual", "Lookup", "Computed", "Imported", "Part",   # bare forms
}
```

`MIXIN_REGISTRY` is intentionally tiny — only Spyglass's own first-party mixins. The bar for adding an entry: Spyglass classes inherit from it AND it provides methods agents would ask about. The bar for *not* adding: it's a datajoint base class (annotated separately), or it's a private base used by exactly one class (just AST-walk that one class's bases inline).

### Inheritance walk

Pseudocode for the body of `code_graph.py describe`:

```python
record = resolve_class(name, file_hint=args.file)         # multi-file disambig here
print_header(record)
print_definition(record.definition)
print_parts(record.parts)
print_body_methods(record.methods)

if not args.no_inherited:
    visited = set()
    for base in record.bases:
        if base in DATAJOINT_BASES:
            print(f"inherited from {base}: see datajoint API reference")
            continue
        base_record = resolve_base(base, index, MIXIN_REGISTRY)
        if base_record is None:
            print(f"inherited from {base}: (unresolved — not in MIXIN_REGISTRY, "
                  f"not a known datajoint base; check src manually)")
            continue
        walk_inheritance(base_record, visited, depth=0, max_depth=4)
```

`walk_inheritance` AST-walks `base_record`'s class body for methods, then recurses on *its* bases (using the same `DATAJOINT_BASES` / `MIXIN_REGISTRY` rules). `visited` set guards against diamond inheritance. `max_depth=4` is a sanity cap; real Spyglass mixin chains are 1-2 deep.

### Method override handling

Body-level methods print first; inherited methods print after, grouped by base. If the same method name appears at body-level and on a base, the body-level wins (Python MRO). The output makes this implicit by ordering, not by computing MRO. Document this in "What this catches / does NOT catch."

### `code_graph.py describe` blind spots

Following `compare_versions.py`'s "What this catches / does NOT catch" pattern. Initial blind-spots:

1. **Datajoint methods.** Annotated as "see datajoint API reference," not enumerated. Agent must consult datajoint docs for `fetch`, `fetch1`, `insert`, `populate`, etc.
2. **Method overrides.** Body-level prints first; inherited prints after. The same name appearing in both means the body-level wins, but the script doesn't compute MRO — visually obvious, mechanically uncomputed. Don't claim "this method does X" based on the inherited version when a body-level override exists.
3. **Dynamically-added methods.** `setattr(Class, name, fn)` at import time, decorators that inject methods, metaclass tricks — invisible. Rare in Spyglass; document.
4. **Aliased imports of bases.** `from .utils import SpyglassMixin as Mixin` then `class X(Mixin, ...):` — registry lookup on `Mixin` fails. Add aliased forms to `MIXIN_REGISTRY` as discovered. Smoke-test against the live tree should catch most cases pre-merge.
5. **Inherited definitions.** Some Spyglass tables inherit `definition` strings via Python class inheritance rather than re-declaring. The AST walk reads each `ClassDef.body`'s string-assigned `definition` only; inherited `definition` strings are invisible. Document.
6. **Class-method vs. instance-method distinction.** Both are listed under "methods." Agent shouldn't assume call-shape from this listing alone.
7. **Property/descriptor methods.** `@property`-decorated functions are listed as methods. Agent should read the decorator if call-shape matters.
8. **Same-name classes across files.** Same `BodyPart`-style ambiguity as `code_graph.py path`. Disambiguate with `--file`.

## `code_graph.py find-method` subcommand — reverse method index

### `code_graph.py find-method` contract

```text
$ python code_graph.py find-method fetch_nwb
fetch_nwb defined on:
  SpyglassMixin   src/spyglass/utils/dj_mixin.py:142  (mixin)
    evidence: "    def fetch_nwb(self, *, save_dir=None, ...):"

inherited via:
  SpyglassMixin → every Spyglass user-table that subclasses it.
  Confirm on a specific class with: code_graph.py describe <ClassName>
```

```text
$ python code_graph.py find-method get_restricted_merge_ids
get_restricted_merge_ids defined on:
  SpikeSortingOutput   src/spyglass/spikesorting/spikesorting_merge.py:N  (body)
    evidence: "    def get_restricted_merge_ids(cls, restriction):"

inherited via: (none — body-level only, no mixin chain)
```

```text
$ python code_graph.py find-method get_pk
exit 4
No class in this Spyglass index defines a method named 'get_pk'.
Hint: the method may come from a datajoint base class. Check datajoint docs,
or run code_graph.py describe <SomeClass> to see the datajoint annotation.
```

### `code_graph.py find-method` CLI

```text
code_graph.py find-method <METHOD_NAME> [--src PATH]
            [--include-private] [--no-inherited] [--json]
```

- `<METHOD_NAME>` is positional and required.
- `--src` mirrors the other subcommands.
- `--include-private` includes `_*` methods (default: skip).
- `--no-inherited` suppresses the "inherited via" section (default: shown when the method comes from a registered mixin).
- `--json` emits machine-readable JSON. See [§ Output formats](#output-formats-all-subcommands) for the schema.

**Exit codes** match the other subcommands: `0` (found at least one definition), `2` (usage error), `4` (no class defines this method).

### `code_graph.py find-method` blind spots

1. **Datajoint methods.** `find-method fetch` returns exit 4 because `fetch` is defined on `dj.Table`, not on any class in the Spyglass source tree. This is the same "annotate, don't walk" boundary as `describe`. The exit-4 hint mentions datajoint explicitly so the agent doesn't conclude the method doesn't exist anywhere.
2. **Dynamically-injected methods.** Decorators that add methods, `setattr` at import time, metaclass tricks — invisible. Same blind spot as `describe`.
3. **Aliased mixin methods.** If `SpyglassMixin` is imported as `Mixin` and a class uses `Mixin.fetch_nwb` directly via classmethod, the method is still defined on `SpyglassMixin` so `find-method fetch_nwb` reports it correctly. But if a class redefines `fetch_nwb` at body level, `find-method` reports both — agent must read the override-precedence rule (body wins MRO).
4. **`__lshift__` / `__rshift__` (the `<<` and `>>` operators).** These are real method names and `find-method __lshift__` returns SpyglassMixin. But agents usually ask "does X support `<<`" not "where is `__lshift__` defined" — `describe X` is the better entry point for operator availability.

### Why a separate subcommand, not `describe --reverse`

The output shape is fundamentally different. `describe` returns one class. `find-method` returns N classes (often zero, often one, occasionally many for overridden methods). Folding both into `describe` with a `--reverse` flag would conflate two output schemas in one subcommand — argparse-tractable but mentally noisy. The three-subcommand surface (`describe`, `path`, `find-method`) is also a cleaner mapping to "node view," "edge traversal," "reverse method ownership" — three distinct code-graph question shapes, three distinct surfaces.

## File:line citations (all subcommands)

`code_graph.py describe`, `code_graph.py path`, and `code_graph.py find-method` annotate every printed class with `(file:line)` where `file` is the path relative to `--src` (so `src/spyglass/...` for a git checkout, `spyglass/...` for a pip install — the prefix is whatever directory `--src` points at). `line` is the `ClassDef.lineno`. Don't bake citations into source code or markdown — they're computed at runtime from the AST so they stay current with whatever Spyglass commit `--src` points at.

## Qualified class identity

Every `ClassRecord` carries a `qualname` field (e.g. `LFPOutput.LFPV1`, `DLCProject.BodyPart`, or just `CurationV1` for top-level classes) and a separate `master` field for parts. Both are first-class — built during the AST scan, not reconstructed from nesting context downstream. This matters because:

1. **`BodyPart`-style ambiguity** is endemic in Spyglass — `BodyPart` is defined six times in the position pipeline alone, as a top-level `dj.Manual` and as nested parts of five different masters. A flat name-keyed index is structurally wrong; consumers need both `name` (for short-form lookup) and `qualname` (for unambiguous identity).
2. **Merge masters' part tables** are the load-bearing case for `code_graph.py path`: every `LFPOutput.LFPV1`-style hop has a `qualname` that distinguishes it from any top-level `LFPV1` class. The part-table-as-explicit-hop output requirement in [§ goals](#goals-and-non-goals) only works if the index can produce the qualified name without inference.
3. **JSON output stability.** Downstream consumers (tests, future tools, IDE integrations) need a stable identifier per class. `name` collides; `(file, line)` is too verbose and shifts with edits. `qualname` plus `file` is unique and stable across edits-that-don't-rename.

The scan populates `qualname` as follows. For top-level `ClassDef`, `qualname = name`. For nested `ClassDef` whose enclosing scope is another `ClassDef` (Spyglass's part-table convention), `qualname = "<outer.name>.<inner.name>"` and `master = outer.name`. Deeper nesting (rare) extends the dotted form. The scan does *not* try to resolve `qualname` across files (e.g., importing a class then re-declaring it as a part inside another file is out of scope; we follow the local `ClassDef` parent chain only).

The index keys remain `name → list[ClassRecord]` for ergonomic lookup ("user types `BodyPart`, get the disambiguation list"). Consumers needing `qualname`-keyed access build their own dict from the records when they need it.

## Output formats (all subcommands)

`code_graph.py` ships two output modes: human-readable (default) and machine-readable (`--json`). Documenting both schemas explicitly so downstream automation, regression fixtures, and future tools can depend on them.

### Human-readable (default)

Layout shown in the contract examples for each subcommand. Indented arrows for `path`, indented sections per base for `describe`. Plain text, no escaping; safe for terminal display. Brittle for parsing — use `--json` for anything that consumes the output programmatically.

### Machine-readable (`--json`)

A single JSON object on stdout. The `kind` field is the discriminator. Schema:

**`code_graph.py path` happy path (`exit 0`):**

Every hop carries six fields: `name` (short), `qualname` (fully qualified), `file`, `line`, `kind` (enum: `fk` | `proj` | `nested_part` | `merge_part`), and `evidence` (the source-line text that justified this edge). The `evidence` field is what makes the chain self-citing — every claim in the output points at the source line that produced it.

```json
{
  "kind": "path",
  "from": {"name": "LFPV1",     "qualname": "LFPV1",     "file": "src/spyglass/lfp/v1/lfp.py", "line": 42},
  "to":   {"name": "LFPBandV1", "qualname": "LFPBandV1", "file": "src/spyglass/lfp/analysis/v1/lfp_band.py", "line": 71},
  "hops": [
    {
      "name": "LFPV1", "qualname": "LFPV1",
      "file": "src/spyglass/lfp/v1/lfp.py", "line": 42,
      "kind": "fk",
      "evidence": "class LFPV1(SpyglassMixin, dj.Computed):"
    },
    {
      "name": "LFPV1", "qualname": "LFPOutput.LFPV1",
      "file": "src/spyglass/lfp/lfp_merge.py", "line": 18,
      "kind": "merge_part",
      "evidence": "    class LFPV1(_Merge.Part):  # nested under LFPOutput"
    },
    {
      "name": "LFPBandSelection", "qualname": "LFPBandSelection",
      "file": "src/spyglass/lfp/analysis/v1/lfp_band.py", "line": 26,
      "kind": "proj",
      "evidence": "-> LFPOutput.proj(lfp_merge_id='merge_id')"
    },
    {
      "name": "LFPBandV1", "qualname": "LFPBandV1",
      "file": "src/spyglass/lfp/analysis/v1/lfp_band.py", "line": 71,
      "kind": "fk",
      "evidence": "-> LFPBandSelection"
    }
  ]
}
```

**`code_graph.py path` no-path (`exit 0`):**

```json
{"kind": "no_path", "from": "RippleTimesV1", "to": "LFPV1", "reason": "no FK chain found within max-depth 12"}
```

**`code_graph.py path --up` ancestors (`exit 0`):**

Each node carries `name`, `qualname`, `file`, `line`, `depth`. Each edge carries `child`, `parent`, `kind`, `evidence` — same edge schema as `--to` so callers can reuse one shape across modes.

```json
{
  "kind": "ancestors",
  "root": {"name": "LFPBandV1", "qualname": "LFPBandV1", "file": "src/spyglass/lfp/analysis/v1/lfp_band.py", "line": 71},
  "max_depth": 12,
  "nodes": [
    {"name": "LFPBandSelection",   "qualname": "LFPBandSelection",   "file": "src/spyglass/lfp/analysis/v1/lfp_band.py", "line": 26, "depth": 1},
    {"name": "LFPOutput",          "qualname": "LFPOutput",          "file": "src/spyglass/lfp/lfp_merge.py",            "line": 14, "depth": 2},
    {"name": "LFPV1",              "qualname": "LFPOutput.LFPV1",    "file": "src/spyglass/lfp/lfp_merge.py",            "line": 18, "depth": 3},
    {"name": "LFPV1",              "qualname": "LFPV1",              "file": "src/spyglass/lfp/v1/lfp.py",               "line": 42, "depth": 4},
    {"name": "FirFilterParameters", "qualname": "FirFilterParameters", "file": "src/spyglass/common/common_filter.py", "line": 0, "depth": 2}
  ],
  "edges": [
    {"child": "LFPBandV1",        "parent": "LFPBandSelection",     "kind": "fk",          "evidence": "-> LFPBandSelection"},
    {"child": "LFPBandSelection", "parent": "LFPOutput",            "kind": "proj",        "evidence": "-> LFPOutput.proj(lfp_merge_id='merge_id')"},
    {"child": "LFPBandSelection", "parent": "FirFilterParameters",  "kind": "fk",          "evidence": "-> FirFilterParameters"},
    {"child": "LFPOutput",        "parent": "LFPOutput.LFPV1",      "kind": "merge_part",  "evidence": "    class LFPV1(_Merge.Part):"},
    {"child": "LFPOutput.LFPV1",  "parent": "LFPV1",                "kind": "fk",          "evidence": "-> LFPV1"}
  ]
}
```

**`code_graph.py path --down` descendants (`exit 0`):** symmetric. `kind == "descendants"`, edges' direction reversed (`parent → child`), nodes contain everything reachable downstream. Edge schema (with `kind`/`evidence`) is identical to `--up`.

**`code_graph.py describe` happy path (`exit 0`):**

`bases` carry a `kind` enum (`inherits_resolved` | `inherits_annotated` | `inherits_unresolved`) plus `evidence` (the textual `class X(...)` line). FK edges in `pk_fields` and `fk_edges` carry the same `kind`/`evidence` schema as path hops. The structured `pk_fields`/`non_pk_fields`/`fk_edges` are what attack the field/key/rename hallucinations directly.

```json
{
  "kind": "describe",
  "class": {
    "name": "LFPBandSelection", "qualname": "LFPBandSelection", "master": null,
    "file": "src/spyglass/lfp/analysis/v1/lfp_band.py", "line": 26,
    "tier": "Manual",
    "definition": "-> LFPOutput.proj(lfp_merge_id='merge_id')\nfilter_name: varchar(80)\nfilter_sampling_rate: int\n---\n..."
  },
  "bases": [
    {"name": "SpyglassMixin", "kind": "inherits_resolved",
     "file": "src/spyglass/utils/dj_mixin.py", "line": 14,
     "evidence": "class LFPBandSelection(SpyglassMixin, dj.Manual):"},
    {"name": "dj.Manual", "kind": "inherits_annotated",
     "annotation": "datajoint API reference",
     "evidence": "class LFPBandSelection(SpyglassMixin, dj.Manual):"}
  ],
  "pk_fields": [
    {"name": "filter_name",          "type": "varchar(80)", "default": null, "auto_increment": false},
    {"name": "filter_sampling_rate", "type": "int",         "default": null, "auto_increment": false}
  ],
  "non_pk_fields": [],
  "fk_edges": [
    {
      "parent": "LFPOutput", "qualname_target": "LFPOutput",
      "kind": "proj", "in_pk": true,
      "renames": {"lfp_merge_id": "merge_id"},
      "evidence": "-> LFPOutput.proj(lfp_merge_id='merge_id')",
      "evidence_line": 27
    }
  ],
  "body_methods": [],
  "inherited_methods": [
    {"from_base": "SpyglassMixin",
     "from_file": "src/spyglass/utils/dj_mixin.py",
     "methods": [
       {"name": "fetch_nwb",       "line": 142},
       {"name": "cautious_delete", "line": 198}
     ]}
  ],
  "parts": []
}
```

For a merge master, `parts` is populated with `{name, qualname, file, line, kind: "merge_part"}` entries. For a class with PKs that are themselves FKs (e.g., `CurationV1` whose PK includes `-> SpikeSortingSelection`), `pk_fields` lists the explicit body-level PK fields and `fk_edges` lists the contributing FK with `in_pk: true` — so a caller can reconstruct the full PK shape including the inherited fields from the FK target.

**`code_graph.py find-method` happy path (`exit 0`):**

```json
{
  "kind": "find-method",
  "method": "fetch_nwb",
  "defined_at": [
    {
      "class": {"name": "SpyglassMixin", "qualname": "SpyglassMixin",
                "file": "src/spyglass/utils/dj_mixin.py", "line": 14},
      "line": 142,
      "ownership_kind": "mixin",
      "evidence": "    def fetch_nwb(self, *, save_dir=None, ...):"
    }
  ],
  "inherited_via": [
    {
      "base": "SpyglassMixin",
      "summary": "fetch_nwb is inherited by every class that subclasses SpyglassMixin (transitive). Use describe <ClassName> to confirm on a specific class."
    }
  ]
}
```

For a body-level-only method (e.g., `insert_curation`), `defined_at` has the single hit, `ownership_kind` is `"body"`, and `inherited_via` is empty. For a method with multiple definitions (overrides, or a name reused across pipelines), `defined_at` has every hit.

**`code_graph.py find-method` not found (`exit 4`):**

```json
{
  "kind": "not_found",
  "method": "get_pk",
  "hint": "no class in this Spyglass index defines a method by this name. The method may come from a datajoint base class — check datajoint docs. (Eval-80 closure: 'get_pk' is not a SpyglassMixin convenience.)"
}
```

**Ambiguity (`exit 3`):**

```json
{
  "kind": "ambiguous",
  "name": "BodyPart",
  "candidates": [
    {"qualname": "BodyPart",                "master": null,                "file": "src/spyglass/position/v1/position_dlc_project.py",         "line": 34, "tier": "Manual"},
    {"qualname": "DLCProject.BodyPart",     "master": "DLCProject",        "file": "src/spyglass/position/v1/position_dlc_project.py",         "line": 88, "tier": "Part"},
    {"qualname": "DLCPoseEstimation.BodyPart", "master": "DLCPoseEstimation", "file": "src/spyglass/position/v1/position_dlc_pose_estimation.py", "line": 41, "tier": "Part"}
  ],
  "hint": "re-run with --file <path> (for describe) or --from-file/--to-file <path> (for path)"
}
```

**Class not found (`exit 4`):**

```json
{"kind": "not_found", "name": "NonexistentTable",
 "hint": "class not in this Spyglass index — check spelling, or try compare_versions.py if asking about a specific version"}
```

**Usage error (`exit 2`):** argparse's standard stderr message; no JSON on stdout. (Usage errors happen before the subcommand dispatcher runs, so emitting JSON would require wrapping argparse.)

### Schema versioning

Every JSON output document carries a top-level `"schema_version": 1` field (omitted from the per-shape examples above to keep them readable; concretely, every example dict gains one extra key). When a future change requires a breaking schema bump (e.g., when `KNOWN_CLASSES` auto-derivation lands and the validator integration forces the FK-edge shape to evolve, per the [§ Out-of-scope](#out-of-scope-work-items) follow-up), bumping to `2` lets downstream consumers branch on version cleanly rather than guessing from missing fields.

### Schema stability commitment

The fields above are **part of the contract** at `schema_version: 1`. Adding new optional fields stays at v1; renaming or removing fields requires a version bump. To make this enforceable, the regression fixtures use `--json` exclusively and assert on dict keys / values (and on `schema_version == 1`) rather than text markers. That converts "we promise the schema won't drift" into "the test suite breaks if it does."

## DataJoint source review

`datajoint/declare.py` and `datajoint/dependencies.py` are the authoritative parsers/graph builders. Reviewed before writing `code_graph.py path` to avoid re-inventing semantics DJ already encodes:

- **`is_foreign_key(line)`** (`declare.py:144`) — canonical "is this an FK line?" check: `line.find("->") >= 0 and not any(c in line[:arrow_position] for c in "\"#'")`. Handles inline `#` comments and quoted `->` in attribute defaults. We mirror this rule rather than re-deriving it.
- **`build_foreign_key_parser()`** (`declare.py:110`) — pyparsing grammar that captures `[options]` and `restOfLine` as `ref_table`. The ref-table is then passed to `eval(result.ref_table, context)` (`declare.py:177`) where `context` is the table's declaration namespace. This is the eval-resolution gap our blind-spot #7 documents — DJ trusts Python to resolve aliases / expressions; we have to extract the leading textual name statically.
- **`Dependencies(nx.DiGraph)`** (`dependencies.py:70`) — DJ's own FK graph, but built from MySQL `information_schema` introspection, not from `definition` strings. Useless for inquiry-time (DB-bound) but a reference for "what does the right answer look like?"
- **`extract_master(part_table)`** (`dependencies.py:10`) — DJ's logic for resolving `master__part` full-table-name → master. We operate in *class-name* space (`Master.Part`) not full-table-name space, so the function isn't directly reusable, but the convention (every part has a master, and the master is one level up) is.
- **`diagram.py`** — visual ER diagram via NetworkX. Not relevant to text output. Notable for confirming NetworkX is already a transitive dep wherever Spyglass is installed; we still prefer stdlib BFS in `_find_path` because the script must run with no Spyglass / DJ install (the script's whole point is source-only).

**Net:** don't `import datajoint` from `code_graph.py path`. The script must run against a checked-out Spyglass source tree on a machine that may have neither DJ nor Spyglass installed. Borrow the *logic* (the FK-detection rule, the `Master.Part` convention) but not the imports.

## Pip install vs. git checkout (all subcommands)

All three `code_graph.py` subcommands work against either layout, with no special-casing needed. The contract (mirroring `compare_versions.py`) is "`$SPYGLASS_SRC` points at the directory containing the `spyglass/` package":

- Git checkout / editable install — `$SPYGLASS_SRC=<repo>/src`.
- PyPI wheel install (`pip install`, with or without an active conda env) — `$SPYGLASS_SRC=<env>/lib/pythonX.Y/site-packages`.
- conda-forge install (`conda install`) — same as PyPI wheel; `<conda-env>/lib/pythonX.Y/site-packages`.
- conda env + editable install (`pip install -e <repo>` inside an active conda env) — same as git checkout; `__file__` resolves through the editable link to the repo's `src/spyglass/`. This is the layout the skill repo's own dev env uses.

Both layouts ship `.py` source (PyPI wheels include source; only ultra-rare `.pyc`-only distributions would break the AST walk, and spyglass-neuro is MIT and ships `.py`). The discovery one-liner in SKILL.md returns the package dir, not the parent — the error message in `_resolve_src_root` should suggest both forms so a pip-install user doesn't trip:

```python
# In _resolve_src_root, when neither --src nor $SPYGLASS_SRC is set:
sys.exit(
    "ERROR: pass --src PATH or set $SPYGLASS_SRC to the directory "
    "containing the `spyglass/` package.\n"
    "  Git checkout: $SPYGLASS_SRC=/path/to/spyglass-repo/src\n"
    "  Pip install:  $SPYGLASS_SRC=$(python -c "
    "'import spyglass, os; print(os.path.dirname(os.path.dirname(spyglass.__file__)))')"
)
```

Note the **double `os.path.dirname`** — `spyglass.__file__` is `<...>/spyglass/__init__.py`, so one `dirname` gives the package dir and a second gives its parent (the dir containing `spyglass/`). The single-`dirname` form quoted in SKILL.md's "Source of truth" directive is for *citing paths inside the package*, which is a different goal. Worth fixing the SKILL.md docstring in a follow-up to call out the parent-dir form for `--src`-style consumers, but out of scope for this PR.

## Tool arbitration — when to pick `code_graph.py` vs `compare_versions.py`

Both tools answer "method exists?" questions, with overlap on v0/v1 cross-version asymmetries. Routing rule for the agent:

| Question shape | Primary tool | Why |
| --- | --- | --- |
| "Does class X have method Y *at all*?" (no version dimension) | `code_graph.py describe X` or `code_graph.py find-method Y` | Mixin resolution + structured fields; works on a single class. |
| "Does class X have method Y *in version vN*?" | `compare_versions.py <pipeline> v0 vN --class X` | Designed for pairwise version diffing. |
| "Where does method Y come from at all?" | `code_graph.py find-method Y` | Lists all body-level definitions across the tree; mixin arbitration is built in. |
| "What's the FK path / cascade chain?" | `code_graph.py path` | Only `code_graph.py` walks the FK graph. |
| "What does the source actually say at this line?" | `Read <file>` | Always cite the file; don't paraphrase from a tool when the prose is the question. |

When the agent uses `code_graph.py describe X` for a v1 class and the question is actually about v0 vs v1 drift, the answer can mislead — `describe` shows one side of the asymmetry. The mitigation: `describe`'s docstring blind-spot section names this (point readers at `compare_versions.py` when v0/v1 is involved). Don't try to enforce arbitration in code; document the rule and let the agent route via `feedback_loops.md`.

## Routing — `feedback_loops.md` extension

The "Verify behavior, trust identity" loop already covers cascade-chain claims (`LFPV1 → LFPOutput.LFPV1 → LFPBandSelection → LFPBandV1` is the canonical worked example) and v0/v1 method asymmetry. Extend the loop with a **three-graph orientation** so the agent commits to *which graph* before *which question shape*. This is the load-bearing routing change — it teaches the underlying graph structure rather than mapping symptom-shapes to tools, so the agent can extrapolate to novel question shapes.

Edit shape (~45 lines):

````markdown
### Three graphs, three primitive families

Spyglass has at least three overlapping graphs. Hallucinations come from
confusing one for another, or from not traversing the relevant one fast
enough to verify before answering. Pick the graph *before* the question
shape:

- **Code graph** — what the source declares. Classes, methods, bases,
  `definition` strings, `->` declarations. Authoritative for "what does
  the source say?" Source-only; works without a DB connection.

  ```bash
  python skills/spyglass/scripts/code_graph.py path --to A B   # FK path A → B
  python skills/spyglass/scripts/code_graph.py describe X      # node view, includes mixin-inherited methods
  ```

- **DB graph** — what DataJoint actually wired up at import time
  (`Table.parents()`, `Table.descendants()`, `dj.Diagram`). Authoritative
  for runtime behavior — the code graph is usually a faithful
  approximation, but dynamic part registration, runtime FK overrides,
  and aliased-import resolution can make them diverge. Requires a DB
  connection.

  *No primitive ships with this skill yet — when the agent has DB
  access, fall back to `Table.parents()` / `Table.descendants()`
  directly. A future `db_graph.py` will mirror the `describe` / `path`
  subcommand shape.*

- **Disk graph** — where artifacts live on disk (raw NWBs at
  `$SPYGLASS_BASE_DIR/raw/`, analysis NWBs at
  `$SPYGLASS_BASE_DIR/analysis/<nwb_file_name>/`, kachery sandboxes,
  DLC project dirs). Authoritative for "where is the file?" Path
  conventions live in `settings.py` and `AnalysisNwbfile`.

  *No primitive ships with this skill yet — read `settings.py` directly
  for path conventions. A future `disk_paths.py` will close the gap.*

For version-asymmetry questions ("is method Y on this class in v0 and
v1?"), use `compare_versions.py <pipeline> v0 v1 --class X`. For
behavior questions ("what does method Y do inside its body?"), read the
source — no script substitutes.

When the code-graph answer disagrees with observed runtime behavior,
the DB graph is authoritative. Flag any code-graph answer that depends
on the agent's assumption that the source matches the live import.
````

Word-budget check: `feedback_loops.md` is 146 lines now. Adding ~45 lines lifts it to ~191, still under the 200-line per-H2 informal ceiling and well under the 500-line file soft cap.

Do **not** add a Common Mistake #7 to SKILL.md. Common Mistakes is a footgun list; the navigation toolkit is a how-tool, not a footgun. Core Directive #2 already says "read source before answering" — these scripts are how, not what.

## Tests — new file `tests/test_code_graph.py`

These are **tool-contract tests**, not validator-regression tests — they pin the output shape of `code_graph.py` and the parser shape of `_index.py` against synthetic Spyglass-shaped trees. Reusing `test_validator_regressions.py` would conflate the validator's "drift detection on shipped reference content" job with `code_graph.py`'s "output contract" job, and would force every code_graph schema change to ripple through a file already loaded with validator concerns.

Land as a new file `skills/spyglass/tests/test_code_graph.py`. Borrow the structure conventions from `test_validator_regressions.py` (imperative `fixture_*` functions, `tempfile.TemporaryDirectory()`, subprocess invocation, `_compare_versions_script_path`-style helpers) but with its own `main()` collector and its own `_code_graph_script_path` / `_run_code_graph` helpers. The pre-commit hook and `validate_all.sh` should run both test files in sequence.

Ten fixtures total: four for `code_graph.py path` (`--to` direct, `--to` merge-hop, multi-file ambiguity, `--up`/`--down` tree walk), four for `code_graph.py describe` (mixin methods, datajoint annotation, multi-file ambiguity, **structured fields with FK rename**), two for `code_graph.py find-method` (body-level + mixin inherited-availability, no-class-defines exit-4).

**All fixtures invoke with `--json` and assert against the parsed dict** rather than text markers. This locks the JSON schema as part of the contract, so accidental field renames / removals in `code_graph.py` break the test suite. Also assert exit codes explicitly (`0` for happy and no-path, `3` for ambiguity, `4` for class-not-found).

### Fixture 1: `fixture_graph_finds_direct_fk_path`

Synthesize:

```text
spyglass/fakepipe/v1/foo.py:
    class A:
        definition = "id: int\n---\n"
    class B:
        definition = "-> A\nid: int\n---\n"
    class C:
        definition = "-> B\nid: int\n---\n"
```

Assert (on the parsed `--json` dict): `kind == "path"`, `[h["qualname"] for h in hops] == ["A", "B", "C"]`. Pins the path ordering as a contract rather than a happens-to-work artifact of the renderer.

### Fixture 2: `fixture_graph_names_merge_master_hop`

Synthesize a merge-master pattern:

```text
class Upstream:
    definition = "id: int\n---\n"
class MergeMaster:
    definition = "merge_id: uuid\n---\n"
    class Upstream:                          # nested part
        definition = "-> master\n-> Upstream\n"
class Downstream:
    definition = "-> MergeMaster.proj(merge_id='upstream_merge_id')\nid: int\n---\n"
```

Assert (on the parsed `--json` dict): `kind == "path"`, `len(hops) >= 3`, and one of the intermediate hops has `qualname == "MergeMaster.Upstream"` (i.e., the merge-master is an explicit hop, not elided). Pins the "merge-hop elision" eval 81 fix and the `qualname`-as-first-class-field invariant.

### Fixture 3: `fixture_graph_disambiguates_multi_file_class`

Synthesize the `BodyPart`-style ambiguity:

```text
spyglass/fakepipe/v1/file_a.py: class Ambig: ...
spyglass/fakepipe/v1/file_b.py: class Ambig: ...
```

Assert (on the parsed `--json` dict): exit code `3`, `kind == "ambiguous"`, `name == "Ambig"`, `len(candidates) == 2`, and each candidate has a `file` and `line`. Pins the multi-file-disambiguation behavior so a future refactor can't silently regress to "first match wins" or to a different exit code.

### Fixture 4: `fixture_graph_walks_up_and_down`

Synthesize a 3-deep linear chain plus a side branch, exercising both directions on the same tree:

```text
spyglass/fakepipe/v1/foo.py:
    class Root:                              # depth 0
        definition = "id: int\n---\n"
    class Mid:                               # depth 1: parent Root
        definition = "-> Root\nid: int\n---\n"
    class Leaf:                              # depth 2: parent Mid
        definition = "-> Mid\nid: int\n---\n"
    class Branch:                            # depth 1, side branch from Root
        definition = "-> Root\nid: int\n---\n"
```

Assert (on the parsed `--json` dict for `--up Leaf`): `kind == "ancestors"`, `root.qualname == "Leaf"`, `{n["qualname"] for n in nodes} == {"Mid", "Root"}`, edges contain both `Leaf→Mid` and `Mid→Root`, `Branch` is NOT in nodes (it's a sibling, not an ancestor of Leaf).

Assert (on the parsed `--json` dict for `--down Root`): `kind == "descendants"`, `{n["qualname"] for n in nodes} == {"Mid", "Branch", "Leaf"}`, edges contain `Root→Mid`, `Root→Branch`, `Mid→Leaf`. Pins both tree-walk modes simultaneously, the depth annotation, the edge-list shape, and the asymmetry between `--up` (only direct ancestor chain) vs `--down` (full descendant subtree).

### Fixture 5: `fixture_describe_lists_body_level_methods`

Synthesize a class with body-level methods and a SpyglassMixin-style mixin in a separate file:

```text
spyglass/utils/dj_mixin.py:
    class SpyglassMixin:
        def fetch_nwb(self): pass
        def cautious_delete(self): pass

spyglass/fakepipe/v1/foo.py:
    from spyglass.utils import SpyglassMixin
    class MyTable(SpyglassMixin):
        definition = "id: int\n---\n"
        def my_helper(self): pass
```

Assert (on the parsed `--json` dict): `kind == "describe"`, `class.qualname == "MyTable"`, `body_methods` contains an entry with `name == "my_helper"`, AND `inherited_methods` has a `from_base == "SpyglassMixin"` entry whose `methods` list includes both `fetch_nwb` and `cautious_delete`. Pins mixin-resolution and the schema's nested shape — the central reason `code_graph.py describe` exists.

### Fixture 6: `fixture_describe_annotates_datajoint_bases`

Synthesize a class inheriting from a datajoint tier without re-walking it:

```text
class MyComputed(SpyglassMixin, dj.Computed):
    definition = "..."
    def make(self, key): pass
```

Assert (on the parsed `--json` dict): `bases` contains an entry with `name == "dj.Computed"` and `resolved == false` and an `annotation` field referencing datajoint, AND `inherited_methods` does NOT contain any entry whose `from_base` starts with `dj.`. Pins the "annotate, don't walk" boundary so a future refactor can't accidentally start AST-walking into datajoint source.

### Fixture 7: `fixture_describe_parses_pk_and_fk_renames`

Synthesize a class with a projected FK rename (the canonical merge-master-downstream shape):

```text
class LFPOutput:
    definition = "merge_id: uuid\n---\nsource: varchar(32)\n"
    class LFPV1:                                       # nested part
        definition = "-> master\n-> LFPV1\n"
class LFPBandSelection:
    definition = "-> LFPOutput.proj(lfp_merge_id='merge_id')\nfilter_name: varchar(80)\nfilter_sampling_rate: int\n---\n"
```

Assert (on the parsed `--json` dict for `describe LFPBandSelection`):

- `pk_fields` contains entries for `filter_name` (`varchar(80)`) and `filter_sampling_rate` (`int`).
- `non_pk_fields` is empty (no fields below `---`).
- `fk_edges` has one entry with `parent == "LFPOutput"`, `kind == "proj"`, `in_pk == true`, `renames == {"lfp_merge_id": "merge_id"}`, and `evidence == "-> LFPOutput.proj(lfp_merge_id='merge_id')"`.

Pins the structured-field parsing AND the projected-FK-rename extraction — the two highest-value features for closing field/key/rename hallucinations (eval shapes around `merge_id` vs `pos_merge_id` / `lfp_merge_id`, `interval_list_name` vs `encoding_interval`, etc.).

### Fixture 8: `fixture_describe_disambiguates_multi_file_class`

Synthesize the `BodyPart`-style ambiguity, identical to `fixture_graph_disambiguates_multi_file_class` but invoking `code_graph.py describe`:

```text
spyglass/fakepipe/v1/file_a.py: class Ambig: ...
spyglass/fakepipe/v1/file_b.py: class Ambig: ...
```

Assert (on the parsed `--json` dict): exit code `3`, `kind == "ambiguous"`, same-shape candidates list as Fixture 3. Pins the multi-file-disambiguation behavior shared with `code_graph.py path` AND that the two subcommands return identical JSON shapes for the same failure mode.

### Fixture 9: `fixture_findmethod_lists_mixin_owner_and_inherited`

Synthesize a mixin and a class that inherits from it, then look up a method defined on the mixin:

```text
spyglass/utils/dj_mixin.py:
    class SpyglassMixin:
        def fetch_nwb(self): pass

spyglass/fakepipe/v1/foo.py:
    from spyglass.utils import SpyglassMixin
    class MyTable(SpyglassMixin):
        definition = "id: int\n---\n"
```

Assert (on the parsed `--json` dict for `find-method fetch_nwb`):

- `kind == "find-method"`, `method == "fetch_nwb"`.
- `defined_at` has exactly one entry, with `class.qualname == "SpyglassMixin"`, `ownership_kind == "mixin"`, `evidence` referencing the `def fetch_nwb` line.
- `inherited_via` has one entry with `base == "SpyglassMixin"` and a `summary` field mentioning subclass inheritance.

Pins find-method's mixin-owner identification AND the inherited-via summary that closes the "where does this come from" question.

### Fixture 10: `fixture_findmethod_returns_exit_4_for_unknown`

No synthesis needed beyond a minimal source tree (one class with no methods). Run `find-method nonexistent_method`.

Assert: exit code `4`, `kind == "not_found"`, `method == "nonexistent_method"`, `hint` is a non-empty string mentioning the datajoint-base possibility. Pins the exit-4 contract — load-bearing for eval-80-style "is there `.get_pk()`?" closures where the right answer is "no class defines this."

### Wiring

Add all ten fixtures to the new `test_code_graph.py` file. Imperative `fixture_*` functions (not pytest tests); the file's own `main()` collects and runs them. Follow the `_compare_versions_script_path` / `_run_compare_versions` helper pattern from `test_validator_regressions.py` — add `_code_graph_script_path` / `_run_code_graph` helpers in the new file (single pair since `code_graph.py` is one script with three subcommands). The CLI entry mirrors `test_validator_regressions.py`: `python skills/spyglass/tests/test_code_graph.py --spyglass-src $SPYGLASS_SRC`.

## ruff / pre-commit

`_index.py` and `code_graph.py` are gated by [ruff.toml](../../ruff.toml) and the [.pre-commit-config.yaml](../../.pre-commit-config.yaml) hook. Run `ruff check skills/spyglass/scripts/` before committing. The pre-commit hook also runs the full validator (graceful about missing `$SPYGLASS_SRC`); don't bypass with `--no-verify`.

## Validation

Before opening the PR:

1. `ruff check .` clean.
2. `python skills/spyglass/tests/test_validator_regressions.py --spyglass-src $SPYGLASS_SRC` — existing validator-regression fixtures still pass at the master baseline (no new ones added there).
3. `python skills/spyglass/tests/test_code_graph.py --spyglass-src $SPYGLASS_SRC` — all ten new tool-contract fixtures pass.
4. `./skills/spyglass/scripts/validate_all.sh --baseline-warnings 3` — main validator + both test files green; update `validate_all.sh` to run `test_code_graph.py` alongside `test_validator_regressions.py`.
5. Smoke-test `code_graph.py path` against the live Spyglass source:
    - `python skills/spyglass/scripts/code_graph.py path --to LFPV1 LFPBandV1` matches the documented chain in [feedback_loops.md](../../skills/spyglass/references/feedback_loops.md) line 140 (run with `--json` and verify hop `qualname`s match).
    - `python skills/spyglass/scripts/code_graph.py path --to LFPV1 RippleTimesV1` produces a chain with `RippleLFPSelection` as a middle hop.
    - `python skills/spyglass/scripts/code_graph.py path --to LFPV1 RippleTimesV1` exits in <2s (real-world budget; AST walk + BFS, no DB).
    - `python skills/spyglass/scripts/code_graph.py path --to LFPV1 BodyPart` exits 3 with `kind == "ambiguous"` (since `BodyPart` resolves to multiple files).
    - `python skills/spyglass/scripts/code_graph.py path --up LFPBandV1 --json` returns `kind == "ancestors"` and includes both `LFPBandSelection` and `FirFilterParameters` in `nodes` (eval 73 shape).
    - `python skills/spyglass/scripts/code_graph.py path --down LFPV1 --json` returns `kind == "descendants"` and includes `RippleTimesV1` in `nodes` (eval 68 shape — confirms cascade reaches ripple detection).
6. Smoke-test `code_graph.py describe` against the live Spyglass source:
    - `python skills/spyglass/scripts/code_graph.py describe CurationV1 --json` parses to `kind == "describe"` with `SpyglassMixin` resolved AND `fetch_nwb` / `cautious_delete` in `inherited_methods`.
    - `python skills/spyglass/scripts/code_graph.py describe LFPOutput --json` shows `_Merge` resolved AND `merge_get_part` / `merge_restrict` / `merge_delete` in `inherited_methods`. `parts` is non-empty.
    - `python skills/spyglass/scripts/code_graph.py describe LFPBandSelection --json` has `fk_edges[0].kind == "proj"` and `fk_edges[0].renames == {"lfp_merge_id": "merge_id"}` — confirms the projected-rename parser works on real Spyglass.
    - `python skills/spyglass/scripts/code_graph.py describe BodyPart` exits 3 with the disambiguation candidate list (BodyPart is defined 6+ times in the position pipeline; the script must surface that without picking a winner).
    - For each smoke-test, audit the output against the actual source — if the script claims a method that doesn't exist on the listed base, that's a registry / resolver bug to fix before merge.
7. Smoke-test `code_graph.py find-method` against the live Spyglass source:
    - `python skills/spyglass/scripts/code_graph.py find-method fetch_nwb --json` returns `defined_at` containing `SpyglassMixin` AND `inherited_via` mentioning subclass inheritance.
    - `python skills/spyglass/scripts/code_graph.py find-method get_restricted_merge_ids --json` returns `defined_at` containing only `SpikeSortingOutput` (eval 51 closure).
    - `python skills/spyglass/scripts/code_graph.py find-method nonexistent_method` exits 4 with `kind == "not_found"` and a hint mentioning datajoint (eval 80 closure shape).

## Rollout

Commit order on `feature/inquiry-time-navigation` (single PR; commits split for review):

1. **`_index.py` standalone.** AST scan + FK parsing + base resolution + `ClassRecord` / `FieldSpec` / `FKEdge` (with `qualname`, `master`, structured `pk_fields` / `non_pk_fields` / `fk_edges` with `kind`/`renames`/`evidence`) + `MIXIN_REGISTRY` + `DATAJOINT_BASES` + `parse_definition()` (kwargs-via-`ast.parse`) + `child_map()` + `reverse_method_index()` + `lru_cache(maxsize=1)`. No CLI consumer yet. Smoke output kept deliberately minimal: `if __name__ == "__main__":` prints two lines — class count and scan time. Anything richer (sample records, tier breakdown, etc.) inflates the review surface for a commit whose externally-visible behavior is intentionally narrow. Reviewers verify the AST walk works by running the smoke and reading the dataclass definitions; deeper validation lands with the consumers in commits 2-4.
2. **`code_graph.py` skeleton + `path` subcommand.** Argparse with subparsers (`describe`, `path`, `find-method`); only `path` is wired this commit. Three modes (`--to`, `--up`, `--down`) + multi-file disambiguation + JSON output (with `kind`/`evidence` per hop) + exit codes + blind-spots docstring. Imports from `_index.py` from the first line. Four regression fixtures for `path`.
3. **`describe` subcommand.** Base resolution + inheritance walk + structured PK / non-PK / FK-rename rendering + datajoint-base annotation + JSON output + blind-spots docstring. Wires into the existing argparse skeleton from step 2. Four regression fixtures (including the structured-PK / FK-rename fixture).
4. **`find-method` subcommand.** Reverse method index over `_index.py`'s scan + mixin inherited-availability summary + exit-4 not-found contract + JSON output + blind-spots docstring. Two regression fixtures.
5. **Routing copy.** Extend `feedback_loops.md`'s "Verify behavior, trust identity" loop with the **three-graph orientation** (code / DB / disk) and the named slots for the three subcommands of `code_graph.py`, deferred `db_graph.py`, deferred `disk_paths.py`, plus pointers to `compare_versions.py` for version-asymmetry questions.
6. **Final smoke + validator pass.** Re-run `validate_all.sh`; confirm baseline-warnings unchanged.

The index-first order means `_index.py`'s contract (especially the structured-field parser and the FK-edge schema with `kind`/`renames`/`evidence`) is fixed before any consumer exists, so all three subcommands consume one stable shape from day 1. Trade-off: step 1's commit has no externally visible behavior, which makes review slightly less satisfying — reviewers verify by running the two-line smoke (class count + scan time) and reading the dataclass definitions; deeper validation lands with the consumers in steps 2-4.

Stacking: branch sits on top of `feature/version-discovery-script` (`compare_versions.py`) and `feature/version-hallucination-policy` (Core Directive #2). Once #14 and #15 merge to master, rebase this branch on master before merging.

No DB migration, no schema change, no agent-config changes. The scripts are opt-in until the routing copy lands; the routing copy is in `feedback_loops.md`, which is loaded only when the agent triggers on feedback-loop-shaped questions.

One eval round after merge: re-run eval 81 (the merge-hop elision case), any cascade-chain neighbors, and seed any new "does class X have method Y?" eval shapes the mixin-resolution capability now makes answerable. If eval 81 stays green and the mixin-shape evals pass, the navigation toolkit's value is proven.

## Deferred — other graphs and tools

Two deferred items, each with concrete build-trigger criteria. The bar in all cases is "we have evidence this missing tool is making the agent wrong, not just that this missing tool is theoretically useful." (`find-method` was originally deferred too; the eval-coverage analysis showed it addresses 4 evals on a different lookup direction from `describe`, so it moved in-scope.)

### `db_graph.py` — DB-resolved graph traversal

The code graph is a faithful approximation of the DB graph for most questions, but they can diverge: dynamic part registration (parts added at import time), runtime FK overrides, aliased-import resolution that DJ does via `eval()` against the import namespace, AND **custom tables defined outside `$SPYGLASS_SRC`** (lab-member analysis repos, institute forks, downstream pip packages that subclass Spyglass classes or register parts on Spyglass merge masters). `db_graph.py` would wrap `Table.parents()` / `Table.descendants()` / `dj.Diagram` to give the agent a DB-resolved truth source when one is available, with the same `describe` / `path` subcommand shape as `code_graph.py` so the agent's mental model maps 1:1.

**Build it if any of these is true:**

1. An eval failure traces to a code-vs-DB divergence — the agent ran `code_graph.py` correctly, got the wrong answer because the live import added a part / overrode an FK / resolved an alias differently than the source declared.
2. **A real user question references a custom table that exists in their schema but not under `$SPYGLASS_SRC`.** This is the strongest empirical case for `db_graph.py` and is more likely to happen in practice than #1 — every lab has at least some custom analysis tables. `code_graph.py` will return `not_found` (exit 4) for these, which is correct behavior for a code-graph tool but wrong as a final answer when the table actually exists in the user's DB. The agent's fallback today is "ask the user to run `Table.descendants()` themselves"; `db_graph.py` would automate that fallback.
3. Maintainers want the validator to gate against DB-resolved structure (vs. just the source-declared structure that `_index.py` produces). Auto-derived `KNOWN_CLASSES` from a DB scan would be more authoritative than from an AST scan.

**Don't build it if:**

- The code-graph approximation is catching everything in practice. The bar is "real eval failure traceable to a divergence," not "theoretically possible divergence."
- The agent doesn't typically have DB access at inquiry time. A primitive that's unusable in 90% of contexts isn't worth the surface area.

**Sketch (when triggered):** ~150 lines, requires `import spyglass` and a working DB connection (departing from the source-only constraint that the rest of the toolkit honors). Same CLI shape as `code_graph.py` (`describe`, `path` subcommands). Uses DJ's existing graph machinery (`Table.descendants()`, `dj.Diagram`) under the hood. Output annotates each FK with whether it matched the source declaration, so divergences are visible.

### `disk_paths.py` — artifact-path resolution

The disk graph is the third graph, and the agent has nothing for it today. Hallucinations: agents guess paths from naming conventions when asked "where does the analysis NWB end up?" Path conventions live in `settings.py` (which reads `dj_local_conf.json` for `$SPYGLASS_BASE_DIR`) and `AnalysisNwbfile.create()`; references like `ingestion.md` document them in prose, which ages with the source.

**Build it if any of these is true:**

1. An eval failure traces to a wrong path claim — agent says "the file is at X" and the actual convention puts it at Y.
2. Users repeatedly ask path-shaped questions in agent transcripts — "where does my LFP analysis NWB end up?" "what's the kachery sandbox dir?" "where does DLC store project files?" — and the agent answers from prose rather than re-deriving.

**Don't build it if:**

- Existing references plus `Read settings.py` are catching path questions. `disk_paths.py` is the easiest of the three deferred items to skip — paths are slow-moving, and prose can keep pace.

**Sketch (when triggered):** ~120 lines, source-only (reads `dj_local_conf.json` via `scrub_dj_config.py`-style protection so passwords don't leak; reads `settings.py` and `AnalysisNwbfile.create()` AST for path conventions). Given a class + key fields, prints the path the populated row's artifact would live at, plus whether the file exists if `$SPYGLASS_BASE_DIR` is mounted. Cites the source file where the path convention is defined.

### Decision flow after this branch ships

```text
1. Merge feature/inquiry-time-navigation (code_graph.py with describe +
   path + find-method subcommands).
2. Re-run the eval suite. Watch four failure modes:
   a. cascade-chain shape (eval 81 + neighbors) — code_graph.py path
      should close these.
   b. mixin-availability + method-ownership shapes (evals 21, 51, 80,
      89) — code_graph.py describe + find-method should close these.
   c. NEW: code-vs-DB divergence shape — if observed, db_graph.py is
      the next priority.
   d. NEW: artifact-path shape — if observed, disk_paths.py is next.
3. If 2a and 2b stay green and no 2c / 2d shapes emerge — you're done.
   Don't speculate-build the deferred primitives.
4. When a deferred-trigger fires, build that one primitive as a
   separate PR. Reuse the script-shipping pattern (focused script,
   blind-spots docstring, regression fixtures, exit-0 discipline).
   Mirror code_graph.py's subcommand shape (describe / path / find-method
   if relevant) for db_graph.py so the agent's mental model carries over.
5. The auto-derive KNOWN_CLASSES from _index.py follow-up sits in the
   queue independently — _index.py is now proven against three
   consumers plus a curated registry plus the structured-field parser,
   so the validator integration is ready whenever the maintainer wants
   to close the manual-curation gap.
```

`compare_versions.py` cleared the bar (eval 40); the version Core Directive cleared it (multiple round-3 evals); `code_graph.py path` clears it via eval 81; `code_graph.py describe` clears it via the mixin-inheritance gap. The three deferred items above haven't cleared it yet.

## Pickup notes

### Starting the work

- Branch is `feature/inquiry-time-navigation`; the only commits are the parent plan ([inquiry-time-navigation-plan.md](inquiry-time-navigation-plan.md)) plus this impl plan. Stack implementation work on top per the [§ Rollout](#rollout) commit order.
- Pre-flight check: `echo $SPYGLASS_SRC` should print the directory containing the `spyglass/` package; `ls $SPYGLASS_SRC/spyglass/` should list the pipeline subdirs. If unset, see [§ Pip install vs. git checkout](#pip-install-vs-git-checkout-all-subcommands) for the discovery one-liner.
- Use `compare_versions.py` (in [feature/version-discovery-script](https://github.com/LorenFrankLab/spyglass-skill/pull/15)) as the structural template — `_resolve_src_root`, blind-spots docstring section, exit-0 discipline. Argparse shape diverges (subparsers for `describe` / `path` / `find-method`); use Python's `argparse.add_subparsers(dest="cmd", required=True)` and dispatch in `main()`.

### First targets to test the parser against

When building `_index.py`'s `parse_definition`, walk this progression. Each target adds one shape the parser must handle; if it works on `n`, it should still work on 1 through `n-1`.

1. **`Session`** (`src/spyglass/common/common_session.py`). Plain definition with PK + non-PK fields, no FK, no projection. Simplest case — proves the `---` split and field parsing works.
2. **`LFPV1`** (`src/spyglass/lfp/v1/lfp.py:42`). Adds a single `->` FK in the PK section. Proves FK extraction and the `kind == "fk"` annotation.
3. **`CurationV1`** (`src/spyglass/spikesorting/v1/curation.py:23`). Multiple non-PK fields with defaults and varied types (`varchar`, `blob`, `int = -1`). Proves field-shape coverage from [§ Parser coverage matrix](#parse_definition-coverage-matrix).
4. **`LFPBandSelection`** (`src/spyglass/lfp/analysis/v1/lfp_band.py:26`). The canonical projected-merge case — `-> LFPOutput.proj(lfp_merge_id='merge_id')`. Proves `kind == "proj"` and the `renames` dict extraction. **This is the structured-fields hallucination-prevention test.**
5. **`LFPOutput`** (`src/spyglass/lfp/lfp_merge.py:14`). Merge master with `_Merge` base + nested part `LFPOutput.LFPV1`. Proves `tier == "Manual (merge master)"`, `parts` list, and the qualname / master fields.
6. **`BodyPart`** (defined 6× across `src/spyglass/position/v1/`). Proves multi-file disambiguation surfaces correctly with exit code 3. Already pinned in Fixture 3.

After all six pass on real Spyglass source, run the full smoke from [§ Validation](#validation). Anything that fails is a real bug to fix before commit.

### Abort / escalation criteria

Pause and reconsider if any of these fire during implementation:

- **`scan(SPYGLASS_SRC)` returns 0 classes.** Either `$SPYGLASS_SRC` points at the wrong directory or the AST walk has a bug. Don't keep building consumers; fix the scan first.
- **`parse_definition` can't handle a real `definition` string.** Don't extend the parser ad-hoc; add the shape to [§ Parser coverage matrix](#parse_definition-coverage-matrix), write a fixture for it, then implement. The matrix is the contract.
- **`MIXIN_REGISTRY` needs >5 entries to cover real usage.** Stop and ask whether the registry approach is the right shape, or whether `code_graph.py describe` should follow inheritance more aggressively. The bar for adding entries was "small, hand-curated, regression-tested" — drift past that is a design signal, not a registry-curation task.
- **A subcommand starts wanting to `import spyglass`.** That's the whole point we're avoiding (DB schema registration, multi-second import). Step back: the right answer is in `_index.py`, not in importing.
- **Smoke tests pass but agent eval round shows worse hallucinations.** Routing problem, not toolkit problem — the agent isn't reaching for the script. Tighten `feedback_loops.md` instead of widening the script.

### Other callouts

- The three-graph framing in [§ Framing](#framing--three-graphs-hallucinations-from-confusing-them) is doing real work — every code-graph answer should be implicitly tagged "code-graph claim, not DB-resolved" in the agent's mental model. Resist the temptation to elide that distinction in the docstrings; it's the foundation that makes future `db_graph.py` legible.
- Spyglass's own `dj_graph.py` (`src/spyglass/utils/dj_graph.py:38` for `dj_topo_sort`, line 766 `RestrGraph`, line 1265 `TableChain`) is worth reading before writing `_find_path` — its merge-handling logic is the reference for what "right" looks like, even though we can't call it (DB-bound).
- The mixin registry starts tiny (`SpyglassMixin`, `_Merge`). Resist the temptation to pre-populate it. Add entries when smoke-testing against live Spyglass surfaces a class whose mixin chain isn't covered, not before. Same discipline as `KNOWN_CLASSES`.
- `_index.py`'s `lru_cache(maxsize=1)` on `scan` is the only caching in the system. Per-process, in-memory, automatic — no persistence, no invalidation footgun. If profiling later shows a real need for cross-process caching, it lands as a separate decision; don't pre-build it.
