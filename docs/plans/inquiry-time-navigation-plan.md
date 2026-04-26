# Plan: inquiry-time navigation primitives for the Spyglass tree

**Branch:** `feature/inquiry-time-navigation`.
**Status (as of 2026-04-26):** **Code-graph layer shipped.** The first of the three deferred layers below — `code_graph.py` — is built, tested, provenance-stamped, and validated (37/37 fixtures, including 4 real-Spyglass smoke gates). See [code-graph-impl-plan.md](code-graph-impl-plan.md) for the (now historical) detail plan and what diverged from it during execution. The other two layers are tracked separately: **DB graph** in [db-graph-decision-record.md](db-graph-decision-record.md) (decision: build it in a separate PR after this one merges); **disk graph** remains deferred without a concrete next step (read `settings.py` directly until eval pressure justifies a CLI).
**Predecessors:** PR #15 `feature/version-discovery-script` (`compare_versions.py`) was assumed by the original plan but did NOT land before this PR — user-facing references to it were stripped from this branch's content. SKILL.md Core Directive #2 from PR #14 ("read source before answering") is in place and is what makes the source-only navigation primitive load-bearing rather than optional.

**Original plan below; left as-is for the Why-now / three-layers framing that motivated the code-graph build.**

---

## Goal

Give the agent a small family of fast, source-only primitives that let it
navigate Spyglass's overlapping graphs at inquiry time, instead of relying on
prose documentation that ages with the source. The primitives should answer
the questions agents actually ask without requiring `import spyglass` or a
live DB connection.

## Why now

The compare_versions investigation surfaced that the current skill model
("agent reads pre-written reference prose") is structurally lossy: prose ages,
LLMs hallucinate around it, and the validator can only catch identity errors,
not behavioral or relationship claims. The version-hallucination Core Directive
(in `feature/version-hallucination-policy`) tells the agent "Read source before
answering" — but reading source is itself an open-ended task. A small toolkit
of navigation primitives turns "Read source" into "ask the right script,"
which is faster, more deterministic, and leaves a citation trail.

Three eval failures from prior rounds illustrate the shapes that motivated
this:

- **Eval 40** — agent named v0 `set_group_by_electrode_group` on v1 `SortGroup`
  ("does this method exist on this class in this version?"). Partly addressed
  by `compare_versions.py`; would also be caught by `find_method.py`.
- **Eval 81** — agent wrote cascade chain `LFPV1 → LFPBandV1`, eliding the
  `LFPOutput.LFPV1` merge hop ("what's between A and B?"). Would be caught
  by `graph.py --to`.
- **Eval 61** — agent claimed `position_smoothing_duration` doesn't affect
  the `speed` column ("what does this method/field actually do?"). Would be
  caught by `describe.py` showing the `make()` body ordering.

## What "the tree" actually consists of

Spyglass is several overlapping graphs. The agent's question usually maps to
one of them:

1. **DataJoint dependency graph** — every table → its parents/children/
   ancestors/descendants. Lives in the live database connection
   (`Table.parents()`, `dj.Diagram`). Available only with a working DB +
   imported Python classes.
2. **Python class graph** — every `dj.Manual`/`dj.Computed`/`dj.Lookup`/
   `_Merge` class with its `definition` string, `__bases__`, methods. Lives in
   the source tree under `src/spyglass/`. AST-walkable in ~5s for the whole
   tree.
3. **Version-pipeline graph** — same logical concept across `v0/`, `v1/`,
   `v2/` directories. Already partially addressed by `compare_versions.py`.
4. **On-disk artifact graph** — `AnalysisNwbfile` rows link to files at
   `$SPYGLASS_BASE_DIR/analysis/<file>.nwb`; raw NWBs at `$SPYGLASS_BASE_DIR/raw/`;
   figURL caches, kachery sandboxes, DLC project directories all have their
   own subtree shape.
5. **Notebook graph** — `notebooks/00_Setup.ipynb` through `60_MoSeq.ipynb` as
   canonical workflow examples. Already routed in SKILL.md but not
   programmatically navigated.

The skill currently leans on (5) for routing, (2) for source verification, and
rarely on (1), (3), (4). The agent typically can't introspect (1) and (4) at
all because it doesn't have a live DB connection or filesystem permissions in
most settings.

## Speed regimes that determine what we can build

- **Sub-second (cheap, run on every question):** filesystem walk
  (`grep -rn "class X" src/spyglass/`), AST parse of one or two files, Read of
  a known path. *This is the regime the navigation primitives must target.*
- **Few-second (run when the question warrants):** full AST walk of
  `src/spyglass/` (~5s, ~600 .py files), building a class-name → file map.
  Worth caching to JSON keyed on source-tree mtime if reused across primitives.
- **Slow (avoid in the inquiry loop):** `import spyglass` and any subpackage —
  triggers DataJoint schema registration which round-trips the DB. Multi-second,
  sometimes minutes if the connection blocks. Live DB queries fall here too.

## What Spyglass already provides (and why we still need our own)

Spyglass has substantial in-tree graph machinery, primarily in
`src/spyglass/utils/dj_graph.py` (1692 lines) and `src/spyglass/utils/mixins/restrict_by.py`
(165 lines). Surfaces:

- `Table.restrict_by(restriction, direction='up'|'down')` — walks the DJ
  dependency graph to find rows in `Table` matching a restriction at a related
  table. Operator forms: `<<` (upstream) and `>>` (downstream).
- `Table.parents()`, `Table.children()`, `Table.ancestors()`, `Table.descendants()` —
  standard DataJoint introspection.
- `dj.Diagram(Table)` — visual ER diagram around a table.
- `Table.find_insert_fail(key)` — walks parents to figure out which upstream
  row is missing for a failed insert.

**Why we still need our own:** all of the above require `import spyglass`,
which triggers schema registration against the live DB. That's slow
(multi-second on cache miss) and fails entirely without a working DB
connection. The agent typically has neither at inquiry time. Our primitives
must work from the source tree alone — AST-parsing `definition` strings to
extract `->` declarations, then walking the parsed graph in pure Python with
no DB round-trip.

There's also a coverage gap: the in-tree machinery is for *running* queries
(restricted relations, cascade walks). The agent's questions are about
*structure* ("what depends on what," "where is X defined," "what version is
this method in"), which requires a different shape of output (file:line
citations, declaration sites) that the in-tree helpers don't produce.

## Proposed three layers

### Layer 1 — lookup index (~1-2 hours)

Build once from source, query per inquiry. Cache to JSON under
`skills/spyglass/cache/` (gitignored) keyed on the source tree's max mtime;
rebuild when stale.

The index has three views:

- `class_name → (file:line, base, tier, definition_string, methods, version)`
  — built by AST-walking `src/spyglass/`. `version` is `v0`/`v1`/`v2`/`None`
  inferred from the `<pipeline>/v<N>/` segment in the file path.
- `class_name → set(parent_class_names)` — built by parsing `->` from
  `definition` strings. The dependency graph in pure Python form.
- `method_name → list[(class, file, version)]` — reverse index for "where else
  does this method exist?"

The index is shared infrastructure; each navigation script depends on it.
Build cost: ~5 seconds first run, sub-second cached. Cache invalidation is
the only operational concern — keep it simple (mtime of the deepest .py
file under `$SPYGLASS_SRC/spyglass/`).

### Layer 2 — navigation scripts (~3-4 hours total)

Three primitives, each anchored at a different graph view, each ~50-100 lines.

#### `describe.py <ClassName>`

Anchored at the **node**. Prints:
- File:line of the class declaration
- Base class (`dj.Manual`, `dj.Lookup`, `dj.Computed`, `dj.Imported`,
  `dj.Part`, `_Merge`, `SpyglassMixin` ordering)
- Full `definition` string verbatim
- Parents extracted from `->` declarations in `definition`
- Body-level methods (with line numbers; same AST walk as `compare_versions`)
- Version (if under `<pipeline>/v<N>/`)
- For merge-master classes (subclassed from `_Merge`): part-table list

Catches the failure modes `compare_versions.py` misses: tier flips
(`Manual` → `Lookup`), `definition`-string changes (PK shape, FK shape,
column types), structural-vs-runtime attribution (does this behavior live in
`definition` or in `make()`?).

Example invocations:
```
describe.py SortGroup            # disambiguates v0 vs v1 if both exist
describe.py LFPBandV1            # shows the merge-via-LFPOutput FK explicitly
describe.py PositionGroup        # shows both master and PositionGroup.Position
```

#### `graph.py <ClassName> [--up | --down | --to OTHER] [--max-depth N]`

Anchored at the **edges**. Walks the FK graph extracted from `definition`
strings.

- `--up` — print ancestor chain (parents of parents of...)
- `--down` — print descendant tree (children of children of...)
- `--to OTHER` — find the FK path from one class to another, naming each
  intermediate hop including merge-master hops

The merge-hop case is the highest-leverage: an agent asking "does deleting
`LFPV1` cascade to `RippleTimesV1`?" should get a chain like
`LFPV1 → LFPOutput.LFPV1 → LFPBandSelection → LFPBandV1 → RippleLFPSelection → RippleTimesV1`,
with each arrow grounded in the `->` declaration that produces it. Eval 81
would have been a clean catch.

#### `find_method.py <method_name> [--version v0|v1|v2] [--pipeline <name>]`

Reverse index. Greppable yes/no with file:line for every (class, file, version)
hit. Catches the eval-40 shape ("is `set_group_by_electrode_group` available
on v1 SortGroup?") and the more general "where else does this method live?"
question. Optionally filtered by version or pipeline.

### Layer 3 — skill-level routing (~1 hour)

Updates teaching the agent which primitive to reach for:

- SKILL.md Common Mistakes: add a 7th entry pointing at the navigation
  toolkit ("Before claiming a method/class/cascade-chain on a versioned
  pipeline, run the right navigation primitive — `describe`, `graph`,
  `find_method`, or `compare_versions` — instead of inferring from prose").
- New "Navigation primitives" subsection in `feedback_loops.md`'s
  "Verify behavior, trust identity" loop, with a decision table matching
  question-shape to primitive.
- Worked examples in each pipeline reference where the navigation primitive
  is the canonical answer to a common question (e.g., "What's downstream of
  `RippleTimesV1`? — `python compare_versions.py path is wrong here, use graph.py --down RippleTimesV1`").

## What this approach DOESN'T solve

Worth being explicit so the next iteration doesn't overclaim:

- **Live DB state.** Whether a row exists, what its current `merge_id` is,
  what `populate()` has actually run — none of this is in the source tree.
  Agent still needs the user to run actual DB queries when state matters.
- **On-disk state.** File existence, file size, file integrity. Agent can
  predict the path; can't read the file unless mounted.
- **Behavioral semantics inside method bodies.** The script can show you the
  `make()` body; understanding what it does requires the agent to read it.
  We've moved "open the source" from "1 file at a time" to "one tool
  invocation" — but comprehension still has to happen. Eval 61 (smoothing
  affects speed) is caught by `describe.py` in the sense that the agent sees
  the `make()` body order; it's not caught in the sense of an automated
  "smoothing happens before velocity" assertion.
- **DataJoint's runtime expression evaluation.** `Table & restriction` returns
  rows; we can't evaluate that without the DB. The agent's job at
  inquiry-time is to produce the *correct expression*, not to run it.

## Recommended ordering

Don't build all three primitives speculatively. Build when an eval failure
shape demands it:

1. **`graph.py --to A B` first** — eval 81 (merge-hop elision) is recurring
   and the highest-leverage shape. Also the most non-trivial of the three to
   implement (path-finding through the FK graph), so the layer-1 index design
   gets pressure-tested early.
2. **`describe.py` second** — pairs naturally with `graph.py` (one shows
   nodes, the other edges) and reuses the same lookup index. Quick to build
   once the index exists.
3. **`find_method.py` last** — covers the eval-40 shape that `compare_versions`
   already partially handles. Marginal value if the other two and the
   version Core Directive are already in place.

Layer 3 (skill routing) lands as part of whichever of (1)-(3) ships first.

## Open questions to resolve before building

- **Cache location.** `skills/spyglass/cache/index.json` (gitignored)? Or
  rebuild per-invocation since 5 seconds is "fast enough" and avoids the
  staleness footgun? Lean toward rebuild-per-invocation initially; add cache
  if profiling shows it matters.
- **Cross-class redesigns** (the false-negative shape compare_versions can't
  catch) — does `graph.py --to A B` help? Probably yes when the user knows
  both names; not when they only know v0's name and want v1's. The "what's
  the v2 equivalent of v0 X?" question stays open. Worth flagging as a
  layer-2 limit in the docstring like compare_versions did.
- **Ambiguous class names** (e.g., `BodyPart` defined 6 times in spikesorting
  v1) — `describe.py BodyPart` should disambiguate by file path, similar to
  how `compare_versions.py` annotates multi-file unions. Same mechanism;
  reuse.
- **Whether to expose the lookup index as its own primitive** (`whois.py
  SortGroup` returning the JSON record). Maybe, for agent-readable structured
  output. Probably overkill until proven.
- **Validator integration.** Should the validator's `KNOWN_CLASSES` be
  derived from the lookup index instead of hand-curated? That would close the
  drift gap (eval-author adds a class, validator catches it without manual
  KNOWN_CLASSES update). Tempting but separable; defer to its own commit.

## Predecessor context

The two PRs that just landed feed directly into this plan:

- **PR #15** (`feature/version-discovery-script`, commits `259ccc7`,
  `0253a67`, `caae681`) — `compare_versions.py` is the prototype for the
  layer-2 pattern (small script, AST-walks source, prints structured output,
  documents its blind spots honestly, ships with regression fixtures). The
  navigation primitives follow the same pattern.
- **PR #14** (`feature/version-hallucination-policy`, commit `3c5be41`) —
  SKILL.md Core Directive #2 is the policy that makes the navigation
  primitives load-bearing. Without the directive telling the agent to
  read source before answering, the primitives are optional. With it, they
  become the discoverable shortcut.

Both PRs are independently mergeable; #14 depends on #15 in the sense that
its directive references content #15 ships. The navigation toolkit assumes
both have landed.

## Files we'll touch when building

- `skills/spyglass/scripts/_index.py` (new) — layer-1 lookup index
  builder/loader. Shared across the three primitives.
- `skills/spyglass/scripts/describe.py` (new)
- `skills/spyglass/scripts/graph.py` (new)
- `skills/spyglass/scripts/find_method.py` (new)
- `skills/spyglass/references/feedback_loops.md` — extend the
  "Verify behavior, trust identity" loop with a Navigation Primitives
  decision table.
- `skills/spyglass/SKILL.md` — Common Mistake #7 pointing at the toolkit
  (or fold into the existing Core Directive #2 if word-cap permits).
- `skills/spyglass/tests/test_validator_regressions.py` — fixtures per
  primitive following the `compare_versions` pattern (synth fake spyglass
  tree, run via subprocess, assert output contract).
- `skills/spyglass/cache/.gitignore` (new, if we adopt caching) — `*.json`.

## Pickup notes

- The branch is `feature/inquiry-time-navigation` and currently contains only
  this plan file. The first build commit should be `graph.py` per the
  ordering above.
- The compare_versions script's structure (`_resolve_src_root`, `_scan_version`,
  `_diff_versions`, regression-fixture pattern) is the template to follow.
  Copy the conventions: env-var defaults to `$SPYGLASS_SRC`, `--src` flag
  override, exit code 0 always (discovery tools, not gates), docstring with
  explicit "what this catches" + "what this doesn't catch" sections.
- The lookup index probably wants to live in its own importable helper
  (`_index.py`) so all three primitives share it. Keep the per-script CLI
  thin.
- Spyglass's own `dj_graph.py` is **not** a substitute even if it's importable
  — it requires DB round-trip. But its `dj_topo_sort` and merge-handling
  logic are good references for how the in-tree machinery thinks about the
  graph; worth reading before building `graph.py --to`.
