# Common Feedback Loops

Quality-critical Spyglass operations have a **validator → fix → proceed** shape: run a check, fix anything unexpected, only advance when the check passes. These are proactive versions of the rules in SKILL.md's Common Mistakes — they prevent bugs rather than diagnose them after the fact. Load this reference when the user is about to do one of the operations below and you want to teach the check alongside the action.

## Contents

- [Post-ingestion verification](#post-ingestion-verification)
- [Pre-insert check on parameter/selection tables](#pre-insert-check-on-parameterselection-tables)
- [Pre-`populate()` upstream check](#pre-populate-upstream-check)
- [Pre-`fetch1()` cardinality check](#pre-fetch1-cardinality-check)
- [Post-`populate()` verification](#post-populate-verification)
- [Inspect-before-destroy](#inspect-before-destroy)
- [Verify behavior, trust identity](#verify-behavior-trust-identity)

## Post-ingestion verification

After `sgi.insert_sessions(fname)`, confirm the session landed cleanly before any pipeline populates. If any check fails, fix the NWB file and rerun with `reinsert=True`. Only start pipeline work when all three pass. Full ingestion flow: [ingestion.md](ingestion.md).

```python
f = "j1620210710_.nwb"                                  # copy-form; Spyglass appends the "_"
(Session & {"nwb_file_name": f}).fetch1("session_id")   # must return 1 row
print(len(IntervalList & {"nwb_file_name": f}))         # must be > 0
print(len(Electrode & {"nwb_file_name": f}))            # compare to NWB metadata
```

## Pre-insert check on parameter/selection tables

Before inserting a new row into a parameter or selection table, look for an existing row that already captures what you want. Duplicates fragment downstream queries: two rows with identical content but different names mean half the lab's analyses pin to one name and half to the other, and `(TrodesPosParams & {"trodes_pos_params_name": "default"}).fetch1()` returns whichever user's "default" was inserted first. The fix is a before-insert search, not a post-hoc cleanup.

Note on field names: every Spyglass parameter table uses a table-specific PK field, not a universal `params_name`. Examples: `trodes_pos_params_name` (`TrodesPosParams`), `ripple_param_name` (`RippleParameters`), `artifact_params_name` (`ArtifactDetectionParameters`), `unit_filter_params_name` (`UnitSelectionParams`), `dlc_si_params_name` (`DLCSmoothInterpParams`). Inspect `Table.heading.primary_key` to get the exact field for the table you're about to write — do not assume the pattern.

The param-blob **shape** also varies per pipeline: `RippleParameters.ripple_param_dict` nests detection kwargs under `ripple_detection_params`; `MuaEventsParameters.mua_param_dict` is flat; `TrodesPosParams.params` uses `params` as the blob field name; DLC params tables use `params` too but with per-stage schemas. Read the consumer's `make()` — or at minimum the table's docstring and an existing row via `(T & {...}).fetch1()` — for the real shape before writing match logic. The template below is ripple-shaped; it is a *template*, not a recipe.

```python
# Before inserting, look at what already exists in the lab.
# Example uses RippleParameters / ripple_param_name; substitute your table's
# actual name-field (see note above). Note that param blobs are often
# nested — `ripple_param_dict` wraps detection kwargs under
# `ripple_detection_params`, and `sampling_frequency` is NOT stored in
# the blob at all (it comes from the upstream LFPBandV1 at populate time).
# Read the consumer's `make()` for the real shape before writing match logic.
existing = RippleParameters.fetch(as_dict=True)
for row in existing:
    # Compare content, not name — two rows can mean the same thing under different labels
    params = row["ripple_param_dict"]   # params blob field; inspect the table's heading
    detection = params.get("ripple_detection_params", {})
    if (params.get("ripple_detection_algorithm") == "Kay_ripple_detector"
            and detection.get("speed_threshold") == 4.0
            and detection.get("zscore_threshold") == 2.0):
        print(f"Equivalent set already exists as '{row['ripple_param_name']}' — reuse this")
        break
else:
    # Genuinely new — insert with an informative, self-describing name
    RippleParameters.insert1({
        "ripple_param_name": "kay_speed4_zscore2",
        "ripple_param_dict": {...},
    })
```

This is not "never insert." Genuinely new parameter sets *should* exist — the loop is "check-then-decide," and the decision often legitimately lands on insert. What it prevents is unintentional duplication that quietly splits downstream work.

When the decision lands on insert, name quality matters:

- Poor (ambiguous, collides easily, doesn't survive a grep): `default`, `my_params`, `v2`, `test`, `tmp`. Also watch for collision with Spyglass-shipped defaults — `RippleParameters` ships a row literally named `'default'` (see `ripple.py` `insert_default`), so naming yours `'default'` silently skips via `skip_duplicates=True` or overwrites the shipped row depending on call form.
- Informative (self-describing, searchable, collision-resistant). Encode the salient choices: `kay_speed4_zscore2` (ripple: detector + thresholds), `dlc_smoothed_5px_conf_05` (position: smoothing window + confidence), `lfp_60hz_notch_30khz` (filter: band + source sampling rate).

The same check-then-decide loop applies to any free-form string primary key where a user picks the value: electrode-group names, interval-list names, filter names, sort-group names. Whenever you're about to create a new string that downstream work will join on, first ask: *is there already a row in this table that means the same thing?*

### Before the insert lands, run two self-tests

These are cheap to run and catch the two most common silent failures after a lab-wide search shows nothing equivalent exists.

**Understand-each-field test.** Before inserting a params blob you copied from a colleague's notebook or an older analysis, can you explain what every value in it does? Pipeline-specific examples: `speed_threshold` / `zscore_threshold` / `minimum_duration` (ripple detection — eligibility, cutoff, and minimum-length filter), `kappa` / `num_ar_iters` / `target_variance` (MoSeq model training — syllable-length prior, warm-up iterations, PC-selection threshold), `filter_sampling_rate` / `target_sampling_rate` (LFP filtering — input rate and downsampled output rate; see the Nyquist note in `lfp_pipeline.md`). Each affects downstream output in a way the consumer's `make()` assumes. If you don't know what a field does, read `make()` on the computed table (it consumes the blob fields in-scope), the default-insert method on the params table (`insert_default` / `insert_default_params` when present) that documents the sane baseline, or the algorithm's upstream package (e.g., `ripple_detection` for Kay's detector). Inserting values you don't understand is how a silent-wrong-analysis gets shipped: `populate()` succeeds, results look plausible, the downstream figure is incorrect in a way no error message will surface.

**Name-describes-content test.** Can a reader who greps for your `params_name` (or `filter_name`, or `sort_group_name`) predict what the row contains without opening the blob? Good names survive this test; bad names fail it silently. `default_v2`, `my_params`, `theta` (without bandpass), `trodes_updated`, `fixed_version` — all fail. Self-describing names encode the salient knobs: `kay_speed4_zscore2` (detector + thresholds), `dlc_smoothed_5px_conf_05` (smoothing window + confidence cutoff), `lfp_60hz_notch_30khz` (band + source sampling rate). Rename before inserting if the current name is self-misleading. The renaming step costs seconds; the cost of a lab member pinning their analysis to a name that turns out to mean something different is weeks of corrupted downstream work.

## Pre-`populate()` upstream check

Before `MyTable.populate(key)` on a narrow `key`, confirm the upstream selection/dependency has a matching row. DataJoint's `populate()` silently does nothing when `key_source & key` is empty — no error, no warning — and downstream work then fails or produces empty outputs with no obvious cause. Symmetric to the post-populate check; cheap insurance.

```python
# About to run: MyPipelineV1.populate(key)
# First confirm upstream has something to populate from:
print(len(MyPipelineV1.key_source & key))       # must be > 0
print(len(UpstreamSelection & key))             # the selection table feeding this pipeline
# If either is 0: the upstream selection wasn't inserted for this key, or the
# restriction uses a field name the upstream doesn't have. Inspect with
# (UpstreamSelection & key).fetch(as_dict=True, limit=3) to see what's actually there.
```

Common causes when this fails:

- Selection-table insert used a different value for a key field (typical: interval name mismatch — see runtime_debugging.md Signature F).
- Selection row exists but references an interval/params/group that was never populated upstream.
- The key you built includes a field that isn't on `key_source`'s heading. **DataJoint silently DROPS the unknown field rather than failing** (this is the silent-no-op shape `runtime_debugging.md` Signature G describes for `populate()`, and the same shape `common_mistakes.md` #1 warns about for restrictions in general). The danger is the opposite of "empty match": the restriction becomes a **no-op**, and `populate()` runs against the unrestricted `key_source` — populating far more keys than you intended. To verify, print `key_source.heading.primary_key` and compare to your dict's keys; any field in your dict that isn't in the heading is silently being ignored.

## Pre-`fetch1()` cardinality check

Before any `fetch1()`, `merge_get_part()`, or `fetch1_dataframe()`. Proactive form of Common Mistake #2 — turn the rule into a step.

```python
rel = (SomeTable & key)
print(len(rel))          # must be exactly 1
# If != 1: add more primary-key fields, rerun the print
result = rel.fetch1()    # only call after len == 1 is confirmed
```

For merge tables specifically, the inspect phase uses `MergeTable.merge_restrict(key)` or `(MergeTable & key).fetch(as_dict=True)` — not `fetch_results`, which is a decoding-only data-loading method.

## Post-`populate()` verification

After a pipeline `populate()`, confirm rows landed and one output has the expected shape. If the count or shape is off, debug the failing key before moving on — see [runtime_debugging.md](runtime_debugging.md).

```python
MyPipelineV1.populate(key)
print(len(MyPipelineV1 & key))                   # keys you asked for get processed?
sample = (MyPipelineV1 & key).fetch(limit=1, as_dict=True)[0]
# Eyeball dtypes/shapes against downstream code's assumptions
```

## Inspect-before-destroy

Canonical feedback-loop shape — inspect is the validator, user confirmation is the pass gate, the destructive call is the proceed step. The authoritative phase-by-phase workflow (what to output, what counts as valid confirmation, when to verify) lives in [destructive_operations.md — Required workflow](destructive_operations.md#required-workflow). The minimal in-code pattern:

```python
target = (SomeTable & restriction)
target.fetch(as_dict=True)   # inspect scope; cascade preview for .delete()
# Get explicit user confirmation here
target.delete()              # only after confirmation
```

## Verify behavior, trust identity

Identity claims about Spyglass are well-handled by the existing toolchain — `Table.heading`, `Table.parents()`, `KNOWN_CLASSES`, `Table.describe()`, and an `AttributeError` at runtime if a method is named wrong. *Behavior* claims aren't. Field names follow conventions; pipeline order does not. v1 is mostly a refactor of v0, but the helpers are not symmetric. A merge master sits between the Computed table and its downstream consumers, but it's easy to elide it in a chain because the user-facing names suggest a direct link.

**Open the source before asserting any of the four claim shapes below.** Read the relevant `definition` string or `make()` body — don't reason from naming conventions or table tiers. For routine identity questions ("does this class exist," "what's its PK," "what tier is it"), the introspection primitives are sufficient and a source open isn't needed.

**Pipeline-internal call order.** When the answer hinges on whether X happens before or after Y inside a `make()` body — e.g., "does smoothing happen before velocity is computed?" — open the file and read the function. Naming alone is unreliable. Worked example: in `src/spyglass/common/common_position.py:407-481`, per-LED speeds are computed first but only used for outlier rejection; position is then smoothed via `position_smoothing_duration`; the *final* velocity and speed are computed from the smoothed centroid. Field-name-only reasoning ("speed is computed first because the field is called `speed_smoothing_std_dev`") gets the call order backwards.

**Cascade chains across merge tables.** When describing how a delete or a populate cascades, every Output-named master is a *hop* in the chain — write it explicitly. Worked example: `LFPV1` is not directly upstream of `LFPBandV1`. The actual chain is `LFPV1 → LFPOutput.LFPV1 → LFPBandSelection (lfp_merge_id) → LFPBandV1`. The merge hop is declared on `LFPBandSelection` at `src/spyglass/lfp/analysis/v1/lfp_band.py:26` (`-> LFPOutput.proj(lfp_merge_id='merge_id')`); `LFPBandV1` then FKs `LFPBandSelection`. Eliding the merge hop produces a chain that looks plausible but doesn't match `Table.descendants()`. Same shape for any pipeline whose name ends in `Output` (`SpikeSortingOutput`, `PositionOutput`, `LinearizedPositionOutput`, `DecodingOutput`).

**Structural vs. runtime attribution.** Spyglass behavior splits across two layers: *structural* (declared in `Table.definition` strings — FK shapes, projections, secondary attributes) and *runtime* (executed in `make()` or other methods). Footguns living in `definition` surface when the table populates, but they don't *originate* there. Worked example: the cohort-name projection footgun in `src/spyglass/position/v1/position_dlc_selection.py:33-34` (`-> DLCCentroid.proj(dlc_si_cohort_centroid='dlc_si_cohort_selection_name', ...)`) lives in `DLCPosSelection.definition`. Calling it a "`DLCPosV1.populate` footgun" gets the layer wrong even though that's when the user notices it.

**Cross-version asymmetry — eight shapes, one tool per shape.** Spyglass pipelines that ship side-by-side version directories (`spyglass/<pipeline>/<version>/`) are *partial* refactors at best and wholesale redesigns at worst. Symmetry across versions is the exception, not the rule, and the agent's most common hallucination shape is "this helper from version N exists on version N+1 too." Pipelines on master today with multiple version dirs: `spikesorting` (v0/v1), `decoding` (v0/v1), `linearization` (v0/v1), `position` (v1/v2). Single-version pipelines like `lfp`, `behavior`, `mua`, `ripple` aren't immune — their cross-version asymmetry shape is "the new pipeline lives under `<pipeline>/<version>/` while the legacy equivalent lives in `common/`" (e.g. `LFPSelection.set_lfp_electrodes` is the legacy `common/common_ephys.py` form; the v1 equivalent is `LFPElectrodeGroup.create_lfp_electrode_group`, on a different class). New pipelines added later inherit the same risk. Concrete trip-up that motivates this section: `set_group_by_electrode_group` exists on v0 `SortGroup` (`src/spyglass/spikesorting/v0/spikesorting_recording.py:94`) but **not** on v1 `SortGroup`, which exposes only `set_group_by_shank` (`src/spyglass/spikesorting/v1/recording.py:51`).

The `code_graph.py describe --file <path>` workflow covers presence/absence and structural-shape questions; signature questions still need a source read or `inspect.signature`. Substitute the actual version paths into the examples — the workflow is version-number-agnostic. For each asymmetry shape:

- **Same-named class, method present in one version absent in the other.** `code_graph.py describe <Class> --file spyglass/<pipeline>/<verA>/<file>.py --json` vs `… --file spyglass/<pipeline>/<verB>/<file>.py --json` — diff the `body_methods` and `inherited_methods` arrays on the `name` key. Method entries are intentionally minimal (`name` + `line` only) — sufficient for detecting absence, which is the common bug shape.
- **Method signature changed.** `describe` does not return method signatures. Read both source files at the cited `body_methods[].line` to compare params, or — when the user has Spyglass importable at runtime — `python -c "import inspect; from spyglass.<pipeline>.<ver>.<module> import <Class>; print(inspect.signature(<Class>.<method>))"`. Concrete case: v0 `Curation.insert_curation` takes `sorting_key: dict`; v1 `CurationV1.insert_curation` takes `sorting_id: str` plus an optional `apply_merge: bool = False` (`spikesorting/v1/curation.py:44, 50`). The presence-and-absence step above will report both versions have `insert_curation` and stop there; signature comparison is a separate read.
- **Class tier changed.** `describe`'s `class.tier` field surfaces it directly. Concrete case: v0 `WaveformParameters` is `dj.Manual`; v1 is `dj.Lookup`. Different `insert1` semantics — Lookup auto-populates from `contents`.
- **`definition` string / PK / FK changed.** `describe`'s `pk_fields`, `non_pk_fields`, and `fk_edges` are structured. Concrete case: v0 `SpikeSortingRecordingSelection` keys on `(SortGroup, SortInterval, …)`; v1 keys on `recording_id: uuid` only — v0-shaped key dicts won't work in v1.
- **Cross-class redesign within a pipeline.** Read both source files. `code_graph.py find-method <method-name>` lists every owner across versions — useful to confirm which class names exist; the conceptual link (e.g. v0 `Curation` → v1 `CurationV1`) is still a source-read. Wholesale redesigns (renamed classes, collapsed tiers, restructured FK shape) are the dominant pattern when a pipeline jumps two versions; expect this shape, don't assume continuity.
- **Cross-pipeline redesign.** Read `common/` and `<pipeline>/<pipeline>_merge.py`. Concrete case: v0 position info lives in `common/common_position.py` (`IntervalPositionInfo`); v1 lives under `position/v1/`. `code_graph.py path --to A B` finds FK chains across the pipeline boundary if both ends are named.
- **Behavioral change inside a method body.** Read both source files at the cited `file:line`. `describe` does not return method bodies — by design.
- **Module-level helper changed.** `grep -n "^def " src/spyglass/<pipeline>/<verA>/` vs `<verB>/`. `code_graph.py` walks `ClassDef` bodies only, so top-level helpers like `_get_artifact_times` are invisible to it.

When `describe`'s output reports the same shape on both versions, that's evidence of symmetry for *that shape* — it does not certify the API is stable across all eight. The "verify, don't assume" discipline applies regardless: when answer correctness matters, read the source for the version named in the question.

**Why a separate loop:** the validator and `KNOWN_CLASSES` catch identity errors at gate time. They cannot catch a behavior claim that names real classes and real methods but describes their interaction wrong. The `AttributeError` you'd normally rely on doesn't fire — the call works, just not the way the answer says it does. Source verification is the only check.

### Three graphs, three primitive families

**Decision tree — pick the graph before picking the tool:**

| Question shape | Graph | Where to look |
| --- | --- | --- |
| Source class / method / schema dependency (does method Y exist on class X? what FKs does X declare? what's the chain from A to B?) | **Code** | `code_graph.py` |
| Row existence, counts, merge IDs, intersect / antijoin / join across populated tables, runtime heading vs source heading | **DB / session** | `db_graph.py` (read-only: `find-instance`, `describe`, `path`) — emits `graph: "db"` / `authority: "runtime-db"` so payloads can't be confused with source claims |
| Custom table outside `$SPYGLASS_SRC` (lab repos, institute forks) | **DB / session** | `db_graph.py describe/find-instance/path --import <module> <module>:<Class>` — pick the subcommand by question shape: `describe` for "does it exist / what's its heading / what parents does runtime know?", `find-instance --class <module>:<Class>` for row evidence, `path --up`/`--down` for runtime adjacency. `--import` is required for any class outside `$SPYGLASS_SRC`; the explicit `module:Class` form bypasses `_index` lookup so the resolution works without a source tree of the user's repo |
| What does method Y *do* inside its body? | (no graph) | Read the source — no tool substitutes |
| Where is artifact / NWB object on disk? | **Disk** | `settings.py`, `AnalysisNwbfile.create(nwb_file_name)` in the user's session |

**Try order for a runtime/DB question:**

1. **For stock Spyglass classes**: `code_graph.py describe X` for source declarations (PK, FKs, body methods, mixin inheritance) — fast, no DB connection. **For custom classes outside `$SPYGLASS_SRC`** (lab repos, institute forks, external packages): skip step 1; the source index does not see them. Go straight to step 3 with `--import <module> <module>:<Class>`.
2. `db_graph.py find-instance --class X --key f=v` for row evidence; merge masters → `--merge-master M --part P`; intersections / antijoins / per-group counts → `--intersect`/`--except`/`--join`/`--group-by-table` with `--count-distinct`.
3. `db_graph.py describe X` when source and runtime disagree (schema drift) or for runtime-only relationships; check `describe.relationship_metadata_status.<rel>.status` before treating an empty list as "no parents/children/parts." (Pass `--import <module> <module>:<Class>` for custom classes.)
4. `db_graph.py path --to A B` / `--up X` / `--down X` for runtime adjacency walks; check `incomplete` before concluding "no path" — empty `hops` plus `incomplete: true` means the traversal failed, not that no path exists.
5. If `db_graph.py` returns exit `5` (DB error: connection, auth, schema, datajoint_import), fall back to user-session snippets and explain that the CLI cannot see notebook-only env vars or imports.

**Exit-code-`5` divergence between the two graphs:** `code_graph.py` exit `5` means **heuristic refusal** (a same-qualname collision was resolved via same-package preference and `--fail-on-heuristic` was passed). `db_graph.py` exit `5` means **DB / session error** (with `error.kind` discriminating `connection` / `auth` / `schema` / `datajoint_import`). Same code number, different cause. The full delta is also surfaced in `db_graph.py info --json.comparison` so an LLM consuming both tools' contracts gets the explicit translation.

`code_graph.py` is **source-only** — every JSON payload stamps `"graph": "code"` and `"authority": "source-only"` at the top level so an agent reading the output can't mistake it for runtime truth. When the source-graph answer disagrees with observed runtime behavior, the DB / session is authoritative.

Spyglass has at least three overlapping graphs. Hallucinations come from confusing one for another, or from not traversing the relevant one fast enough to verify before answering. Match the question shape to its graph before reaching for a tool:

- **Code graph** — what the source declares. Classes, methods, bases, `definition` strings, `->` declarations. Authoritative for "what does the source say?" Source-only; works without a DB connection.

  ```bash
  python skills/spyglass/scripts/code_graph.py path --to A B   # FK chain A → B (eval 81's merge-hop case)
  python skills/spyglass/scripts/code_graph.py path --up X     # full upstream dep-trace
  python skills/spyglass/scripts/code_graph.py path --down X   # what breaks if I modify X? (counterfactual cascade)
  python skills/spyglass/scripts/code_graph.py describe X      # node view: tier, bases, structured PK / FK / renames, methods (incl. mixin-inherited)
  python skills/spyglass/scripts/code_graph.py find-method Y   # which class owns method Y?
  ```

  Every output carries `file:line` plus an `evidence` source-line so the agent has a citation per claim, not a paraphrase. Add `--json` for machine-readable output (each node also carries a stable `record_id` of the form `<file>:<line>:<qualname>`, and a top-level `warnings` block lists any same-qualname collisions resolved by same-package preference). Exit codes: `0` = ok; `2` = usage error; `3` = user-supplied input ambiguous (re-run with `--from-file`/`--to-file`/`--file`); `4` = class/method not in the index; `5` = traversal needed a heuristic to disambiguate a same-qualname collision (only emitted when `--fail-on-heuristic` is passed, for validators that should refuse to guess).

- **DB graph** — runtime relationship metadata DataJoint exposes from the live server. `db_graph.py path` walks it through `dj.FreeTable(dj.conn(), full_name).parents()` / `.children()`; `db_graph.py describe` reads heading + per-table `parents()` / `children()` / `parts()`. (The same primitives a notebook session reaches via `Table.parents()` / `Table.descendants()` / `dj.Diagram`.) Authoritative for runtime behavior — the code graph is usually a faithful approximation, but dynamic part registration, runtime FK overrides, aliased-import resolution, and **custom tables defined outside `$SPYGLASS_SRC`** (lab-member analysis repos, institute forks, downstream pip packages) can make them diverge. Requires a DB connection AND (for stock Spyglass classes) that the relevant Spyglass module is importable in the subprocess.

  ```bash
  # Row evidence and merge-id resolution.
  python skills/spyglass/scripts/db_graph.py find-instance --class Session --key nwb_file_name=X
  python skills/spyglass/scripts/db_graph.py find-instance --merge-master PositionOutput --part TrodesPosV1 --key nwb_file_name=X --key interval_list_name=Y

  # Set ops + grouped counts. Routes restrictions narrowest-owner-first;
  # zero-shared-attribute ops are refused (no Cartesian-product accidents).
  python skills/spyglass/scripts/db_graph.py find-instance --class TrodesPosV1 --except DLCPosV1 --fields KEY
  python skills/spyglass/scripts/db_graph.py find-instance --class Electrode --key subject_id=aj80 --group-by-table Session --count-distinct electrode_group_name

  # Runtime introspection: heading + parent/child/part metadata. Inspect
  # `relationship_metadata_status` to distinguish "confirmed empty" from
  # "metadata unavailable / errored."
  python skills/spyglass/scripts/db_graph.py describe Session --count

  # Runtime graph traversal — sibling of code_graph.py path. Check
  # `incomplete` before concluding "no path"; check `truncated_at_depth`
  # before assuming a walk hit every reachable node.
  python skills/spyglass/scripts/db_graph.py path --down Session --max-depth 3

  # Custom table outside $SPYGLASS_SRC (lab-member analysis repo). --import
  # runs the user's module's normal import side effects; --class names the
  # specific class (--import alone does NOT register a short name).
  python skills/spyglass/scripts/db_graph.py find-instance --import labrepo.tables --class labrepo.tables:CustomCuration --key sorting_id=Z
  ```

  Every payload stamps `graph: "db"` / `authority: "runtime-db"` so an LLM cannot mistake a runtime row for a source claim. JSON envelopes are advertised in `info --json.payload_envelopes`; the planned and emitted shapes match (no envelope drift).

- **Disk graph** — where artifacts live on disk (raw NWBs at `$SPYGLASS_BASE_DIR/raw/`, analysis NWBs at `$SPYGLASS_BASE_DIR/analysis/<nwb_file_name>/`, kachery sandboxes, DLC project dirs). Authoritative for "where is the file?" Path conventions live in `settings.py` and `AnalysisNwbfile`.

  *Out of scope for this skill — read `settings.py` directly for path conventions, or call `AnalysisNwbfile.create(nwb_file_name)` in the user's session to get a concrete path. The path-construction logic is small enough that wrapping it in a CLI would just add a layer over the same string formatting.*

For version-asymmetry questions ("is method Y on this class in v0 and v1?"), `code_graph.py` is single-version-aware (it shows whichever class has the unique top-level qualname). For now, run `code_graph.py describe` against each version's class explicitly (e.g. `describe Curation --file <v0 path>` and `describe CurationV1 --file <v1 path>`) and diff the two payloads, or read the source files directly.

For behavior questions ("what does method Y do inside its body?"), read the source — no script substitutes for actually reading the function.

**When the code-graph answer disagrees with observed runtime behavior, the DB graph is authoritative.** Specifically: if `code_graph.py describe MyTable` reports `not_found` but the user knows `MyTable` exists in their schema, the right fallback is `db_graph.py describe --import labrepo.tables labrepo.tables:MyTable` — the runtime resolver bypasses `_index` for explicit `module:Class` forms, so a custom table outside `$SPYGLASS_SRC` (lab-member or external-package code) resolves cleanly. (Note: `describe` takes the class as a positional argument, unlike `find-instance` which takes `--class`. `path` is positional too for `--up CLASS` / `--down CLASS`, and takes two positionals for `--to FROM TO`.) Rare alternative: the class lives inside `$SPYGLASS_SRC` but under a module layout `_index.py` doesn't walk — flag and have the user verify. Don't conclude the table doesn't exist.
