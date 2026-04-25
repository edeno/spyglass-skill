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
- The key you built includes a field that doesn't exist on `key_source` — for standard computed tables, DataJoint typically ignores unknown fields in a dictionary restriction, producing an empty match with no error. Tables with custom `key_source` properties may behave differently; if the restriction seems valid but `len(key_source & key) == 0`, print the `key_source.heading.primary_key` to confirm which fields it actually accepts.

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

**v0 / v1 method symmetry.** v1 is a partial refactor of v0; helper methods that exist on the v0 version of a table do *not* always have a v1 counterpart, even when the table name is the same. Concrete example: `set_group_by_electrode_group` exists on v0 `SortGroup` (`src/spyglass/spikesorting/v0/spikesorting_recording.py:94`) but **not** on v1 `SortGroup`, which exposes only `set_group_by_shank` (`src/spyglass/spikesorting/v1/recording.py:51`).

The skill ships `skills/spyglass/scripts/compare_versions.py` for exactly this shape — same-named class, public method present in one version and absent in the other. Run it before asserting that a v0 helper exists in v1 (or vice versa):

```bash
python skills/spyglass/scripts/compare_versions.py spikesorting v0 v1
python skills/spyglass/scripts/compare_versions.py spikesorting v0 v1 --class SortGroup   # focused
python skills/spyglass/scripts/compare_versions.py decoding                                # auto-discover
```

The script AST-parses each version directory under the pinned Spyglass source and prints which classes and methods exist in one version but not the other. It generalizes to any pipeline (`spikesorting`, `lfp`, `position`, `decoding`, `linearization`, `behavior`, …) and to any future v2/v3 the moment the directory exists; nothing in this reference is hand-curated about which methods differ.

**The script is a fast first-pass — it does not cover the full v0/v1 question.** It catches same-class same-name presence/absence asymmetries cleanly. It does *not* catch the seven other shapes of v0/v1 difference (full enumeration in the script's docstring under "What this script does NOT catch"). When the script reports symmetry, that means *one specific shape* of asymmetry is absent — not that the API is stable. Reach for these companion primitives depending on what you're checking:

- **Method signature changed?** `python -c "import inspect; from spyglass.spikesorting.v1.curation import CurationV1; print(inspect.signature(CurationV1.insert_curation))"` — same name in v0 and v1 may take different positional args, switch instance↔classmethod, or add required kwargs. Concrete case: v0 `Curation.insert_curation` takes `sorting_key: dict`; v1 `CurationV1.insert_curation` takes `sorting_id: str` and adds required `apply_merge`.
- **Class tier changed?** `Class.__bases__` — v0 `WaveformParameters` is `dj.Manual`; v1 is `dj.Lookup`. Different `insert1` semantics (Lookup auto-populates from `contents`).
- **`definition` string / PK / FK changed?** `Table.heading` or `Table.describe()` — v0 `SpikeSortingRecordingSelection` keys on `(SortGroup, SortInterval, ...)`; v1 keys on `recording_id: uuid` only. v0-shaped key dicts won't work in v1.
- **Cross-class redesign?** Read both source files. v0 `Curation` (`spikesorting/v0/spikesorting_curation.py`) → v1 `CurationV1` (`spikesorting/v1/curation.py`) is the same conceptual surface across renamed classes; the script reports them as "only in v0" / "only in v1" without drawing the link.
- **Cross-pipeline redesign?** Read `common/` and `<pipeline>/<pipeline>_merge.py`. v0 position info lives in `common/common_position.py` (`IntervalPositionInfo`); v1 lives under `position/v1/`. The script only diffs within one pipeline.
- **Module-level helper changed?** `grep -n "^def " src/spyglass/<pipeline>/v0/` vs `grep -n "^def " src/spyglass/<pipeline>/v1/` — the script walks `ClassDef` bodies only, so top-level helpers like `_get_artifact_times` are invisible.

The behavior-claim discipline ("verify, don't assume") still applies. The script reduces work for one common shape; it doesn't replace reading the source when answer correctness matters.

**Why a separate loop:** the validator and `KNOWN_CLASSES` catch identity errors at gate time. They cannot catch a behavior claim that names real classes and real methods but describes their interaction wrong. The `AttributeError` you'd normally rely on doesn't fire — the call works, just not the way the answer says it does. Source verification is the only check.
