<!-- pipeline-version: v1 -->
# Common Mistakes — Expanded

Expanded prose for the 9 most common Spyglass footguns — top 5 are summarized in SKILL.md; entries 6–9 are additional shapes that surface less often but reliably trip up new users. Each section gives the full mechanism, fix, and cross-reference. Load this reference when the user's code shows one of these shapes, or when the SKILL.md one-liner needs a longer explanation.

## Contents

- [1. Classmethod restriction discard on merge tables](#1-classmethod-restriction-discard-on-merge-tables)
- [2. Too-loose restriction + `fetch1()`](#2-too-loose-restriction--fetch1)
- [3. Passing `skip_duplicates=True` to `insert_sessions`](#3-passing-skip_duplicatestrue-to-insert_sessions)
- [4. `fetch_nwb()` silently returns a list](#4-fetch_nwb-silently-returns-a-list)
- [5. Destructive call without the paired inspect step](#5-destructive-call-without-the-paired-inspect-step)
- [6. Interval / epoch mismatch between pipeline selections](#6-interval--epoch-mismatch-between-pipeline-selections)
- [7. Fragmenting lab-wide search with inconsistent names](#7-fragmenting-lab-wide-search-with-inconsistent-names)
- [8. Plausible-sounding identifier that doesn't exist](#8-plausible-sounding-identifier-that-doesnt-exist)
- [9. `*` refuses to join on a "dependent attribute"](#9--refuses-to-join-on-a-dependent-attribute)

## 1. Classmethod restriction discard on merge tables

`(PositionOutput & merge_key).merge_delete()` silently drops the `& merge_key` — Python routes classmethod calls to the class, not the restricted instance. With `merge_delete`'s default `restriction=True`, the call operates on the entire merge table and asks the user to confirm deletion of every row.

**Fix.** Always pass the restriction as an argument: `PositionOutput.merge_delete(merge_key)`.

The same classmethod-dispatch rule applies to `merge_delete_parent`, `merge_restrict`, `merge_get_part`, `merge_get_parent`, `merge_view`, and `merge_html`. Full affected-method list with correct call forms: [merge_methods.md](merge_methods.md).

**Related footgun (same family).** `(LFPOutput & {'nwb_file_name': f}).fetch()`
doesn't error — it silently returns the whole table (not zero rows,
not one). The master's PK is `merge_id`, and `nwb_file_name` lives on
the part tables, so DataJoint treats the restriction as a no-op. The
worked example with `len(...)` demonstration, plus the canonical
"count across sessions" pattern, lives at
[`merge_methods.md` § Silent wrong-count footgun](merge_methods.md#silent-wrong-count-footgun).

## 2. Too-loose restriction + `fetch1()`

`{"nwb_file_name": f}` alone usually matches many rows — every interval, every param set, every pipeline version for that session. `fetch1()`, `merge_get_part()`, and `fetch1_dataframe()` all raise `DataJointError: expected one row, got N` under an under-specified restriction. `DecodingOutput.fetch_results()` raises a *different* error class for the same diagnostic shape — `ValueError: Ambiguous entry...` — because it routes through `merge_restrict_class` (`utils/dj_merge_tables.py:770`), not `fetch1()`. Same fix, different exception type to pattern-match on.

**Fix.** Add enough primary-key fields to pick exactly one row. Discovery pattern: restrict loosely first, inspect with `.fetch(as_dict=True)` or `MergeTable.merge_restrict(key)`, then build a fully-specified key. Full footgun and fix: [datajoint_api.md](datajoint_api.md).

## 3. Passing `skip_duplicates=True` to `insert_sessions`

`skip_duplicates` is a DataJoint `.insert1()` / `.insert()` flag — valid for manual lookup-table inserts like `ProbeType.insert1(...)` or `Lab.insert1(...)`. `insert_sessions` does not accept it. Passing it raises `TypeError: unexpected keyword argument 'skip_duplicates'`.

**Fix.** For re-ingesting raw NWB data, use `reinsert=True` on `insert_sessions` instead. Full ingestion flow: [ingestion.md](ingestion.md).

## 4. `fetch_nwb()` silently returns a list

Unlike `fetch1()`, `fetch_nwb()` does NOT raise when the restriction matches multiple rows — it silently returns a list. `(Table & key).fetch_nwb()[0]` on an under-specified restriction picks an arbitrary row and returns a plausibly-shaped result with no warning. This is the quiet cousin of Common Mistake #2.

**Fix.** Restrict to exactly one row before calling `fetch_nwb()`. The same cardinality check that guards `fetch1()` protects `fetch_nwb()[0]`. See [datajoint_api.md](datajoint_api.md).

## 5. Destructive call without the paired inspect step

Every destructive helper in Spyglass — `delete`, `drop`, `cautious_delete`, `super_delete`, `delete_quick`, `merge_delete`, `merge_delete_parent`, `cleanup`, `delete_orphans` — needs a paired inspect step before it runs. The exact preview move depends on the helper: `cleanup` and `merge_delete_parent` accept `dry_run=True`; plain `delete` / `drop` / `super_delete` / `delete_quick` / `merge_delete` do **not** — for those, run an explicit `len(rel)` + `rel.fetch(as_dict=True)` (or the `.delete().preview()` flow on `cautious_delete`) so the user sees what would be destroyed. Per-helper paired shapes: [destructive_operations.md](destructive_operations.md). The pattern is inspect → get user confirmation → destroy. Never invent `dry_run=True` on a helper that does not document it.

**Fix.** Never produce a destroy step without the matching inspect step above it. Full paired shapes for every helper: [destructive_operations.md](destructive_operations.md).

## 6. Interval / epoch mismatch between pipeline selections

Spyglass pipelines take different interval-name fields, and two upstream tables populated individually for a session may not actually refer to the same temporal support. Symptoms: a downstream populate silently does nothing; a join between two upstream tables returns empty even though each has rows for the session; decoding or ripple outputs are suspiciously short.

No universal `target_interval_list_name` exists. The field varies by pipeline:
- `IntervalList.interval_list_name` — the primary key of the source table
- `LFPSelection` / `LFPBandSelection` — `target_interval_list_name`
- `spyglass.spikesorting.v0.SpikeSortingRecordingSelection` — `sort_interval_name` (FKs `SortInterval` whose PK is `sort_interval_name` at `spikesorting_recording.py:241`). The downstream v0 `SpikeSortingRecording` (computed) is what introduces `sort_interval_list_name` via `-> IntervalList.proj(sort_interval_list_name='interval_list_name')` at `spikesorting_recording.py:342`. Use `sort_interval_name` to restrict the selection; use `sort_interval_list_name` to restrict the recording or its consumers. **`spyglass.spikesorting.v1.SpikeSortingRecordingSelection` exposes a different field set** — verify with `code_graph.py describe spyglass.spikesorting.v1.SpikeSortingRecordingSelection` before using either name in a v1 context.
- Artifact removal outputs — `artifact_removed_interval_list_name`
- Decoding V1 — `encoding_interval` AND `decoding_interval` (two separate intervals, both projected from `IntervalList.interval_list_name`)

A restriction that works on one selection table can silently match zero rows on another because the field name, the interval-name value, or both differ. DataJoint does not warn when a restriction field is missing from the table — the field is silently ignored.

**Fix.** Inspect the downstream table's primary key (`db_graph.py describe`
for runtime truth, `code_graph.py describe` for source truth, or
`Table.heading.primary_key` inside the user's session) to see the actual
interval-field name. Confirm the value exists for the session with
`db_graph.py find-instance` or `(IntervalList & {"nwb_file_name": f}).fetch("interval_list_name")`.
If the selection was inserted against a different interval than the one you're now restricting, re-insert with the correct value. Full triage including diagnostic queries and the two-interval decoding case: [runtime_debugging.md](runtime_debugging.md) Signature F.

## 7. Fragmenting lab-wide search with inconsistent names

DataJoint restrictions are exact string matches. When lab members insert the same anatomical structure as `CA1`, `hippocampus`, `HPC`, `CA1_1`, `Hippocampus`, and `Hipp`, a query like `(Electrode & {"region_name": "CA1"})` returns only the `CA1` rows — the other five spellings are invisible. Lab-wide analyses silently return partial data, and nobody notices until someone audits row counts by hand.

The same splits happen with any free-form string PK field: subject names (`j16` vs `J16` vs `j1620210710`), electrode group names (`tet1` vs `tetrode_1` vs `1`), interval list names (`sleep` vs `Sleep` vs `sleep_1`), parameter-set names (`default` vs `default_v2` vs `lab_default`), experimenter names, filter names, sort-group labels. Each variant fragments a field that downstream joins and restrictions depend on.

**Fix.** Before inserting a new string into any free-form PK field, query existing values for that table and align to the convention already in use:

```python
# What region names does the lab already use?
BrainRegion.fetch("region_name")
# Electrode groups already inserted for this session
(ElectrodeGroup & {"nwb_file_name": f}).fetch("electrode_group_name")
# Existing parameter-set names on a parameter table. There is no
# universal `params_name` field — each parameter table has its own
# field (e.g. `trodes_pos_params_name`, `decoding_param_name`,
# `dlc_si_params_name`). Discover via the table's PK, then fetch:
pk = ParamsTable.heading.primary_key
ParamsTable.fetch(*pk)
```

Treat existing values in `BrainRegion`, `LabMember`, `LabTeam`, and the lab's established parameter tables as the de facto naming convention — they are what downstream analyses pin to. Diverge only with a specific reason, and when you do, pick an informatively-distinct name (not a typo-variant that collides under casing or whitespace normalization).

This skill can route you to the tables to inspect, but it cannot tell you "the right spelling" — that is lab convention. Surface the existing options to the user and let them choose alignment vs. a justified new name. Related proactive pattern (before inserting a duplicate-content parameter set): [feedback_loops.md](feedback_loops.md) "Pre-insert check on parameter/selection tables".

## 8. Plausible-sounding identifier that doesn't exist

A method, kwarg, column, or table name that sounds right given surrounding conventions — but isn't actually in the Spyglass source. The mistake looks like correct code and passes a reader's eyeball test; at runtime it raises `AttributeError`, `TypeError: unexpected keyword argument`, or `DataJointError: unknown attribute`. Real examples that shipped past multiple review passes in this codebase:

- `moseq_model_params_name` — plausible because other params tables use the `<pipeline>_params_name` pattern (`trodes_pos_params_name`, `ripple_param_name`). But `MoseqModelParams` breaks the pattern — the real PK is `model_params_name` (`src/spyglass/behavior/v1/moseq.py:37`).
- `reference_electrodes` as a kwarg on `set_lfp_band_electrodes` — plausible because shorter names are common. Real kwarg is `reference_electrode_list` (`src/spyglass/lfp/analysis/v1/lfp_band.py:48`).
- `welch_nperseg` as a params field — plausible because welch-method parameters commonly use `nperseg`. Nowhere in the Spyglass codebase; fabricated whole.
- `delete_downstream_parts` as a SpyglassMixin method — plausible because it survived in a deprecated wrapper's docstring. Not present on the current `SpyglassMixin` (search `src/spyglass/utils/dj_mixin.py` and `src/spyglass/utils/mixins/`); calling it raises `AttributeError`.
- `sampling_frequency` as a top-level key of `ripple_param_dict` — plausible because sampling_frequency is everywhere else. Real schema is nested under `ripple_detection_params`, and `sampling_frequency` isn't even stored in the blob — it flows in from `LFPBandV1` at populate time via `RippleTimesV1.make` (`src/spyglass/ripple/v1/ripple.py:204-223`).

The failure mode is uniform: LLMs and humans alike pattern-match from similar contexts and guess a name that sounds consistent. The verification step takes seconds; the cost of shipping the wrong name can be weeks of downstream confusion.

**Fix.** Before writing code or guidance that depends on a specific identifier, verify it via the bundled scripts first; fall back to grep / `inspect` when the script can't speak to the question:

```bash
# Does this class / method / FK actually exist? (Source identity, fast, no DB.)
python skills/spyglass/scripts/code_graph.py describe Cls --json
python skills/spyglass/scripts/code_graph.py find-method the_method_name --json

# Does this table / heading actually exist on the live server? (Runtime truth.)
python skills/spyglass/scripts/db_graph.py describe Cls --json
python skills/spyglass/scripts/db_graph.py find-instance --class Cls --key f=v --fields KEY

# Fallback: method body, signature, blob-key shape — things the scripts don't surface.
grep -rn "def the_method_name" src/spyglass/
python -c "import inspect; from spyglass.X import Cls; print(inspect.signature(Cls.method))"
```

If the symbol doesn't surface in at least one of those checks, assume it doesn't exist and rename. The skill validator enforces this for KNOWN_CLASSES, but field names in blob params, kwargs on lesser-known methods, and part-table attribute-access patterns all slip past it — those are exactly where the pattern-matching guesses hit hardest. Related active check: the validator's `check_evals_content` scans `evals/evals.json` `expected_output`, `behavioral_checks`, and `required_substrings` for method references that don't resolve; `forbidden_substrings` is intentionally skipped because those entries are wrong-by-design adversarial patterns the eval must reject. The corresponding check for reference prose runs via `check_methods`.

**Before generating insert / fetch / populate code.** Code generation is where invented identifiers become executable damage. Run this five-step check; if any step is unavailable, mark the response a *template* and name the missing facts so the user can fill them in:

1. **Verify the table / class exists.** `python skills/spyglass/scripts/code_graph.py describe <Class> --json` (source) or `python skills/spyglass/scripts/db_graph.py describe <Class> --json` (runtime).
2. **Verify primary-key fields + attribute names + types.** Same `describe` calls — the heading is in `pk_fields` / `non_pk_fields` (code-graph) or `describe.primary_key` / `describe.attributes` (db-graph). Do not write a `--key` / `insert1` dict against names you have not just read.
3. **Verify at least one upstream key or row count.** `python skills/spyglass/scripts/db_graph.py find-instance --class <Upstream> --key f=v --count` (or `--fields KEY` for a sample). Confirms the upstream row you'll FK into actually exists for the user's session.
4. **Verify parameter-table names + heading fields via `describe`; verify blob/dict parameter keys separately.** Spyglass parameter sets (`*Parameters`, `*Params`, `<Pipeline>Selection`) are real DataJoint tables — `describe` confirms the table exists and lists its top-level heading attributes. **It does not see inside a blob / dict parameter payload**, which is exactly where `welch_nperseg`-style hallucinations land. To verify keys nested inside a blob params dict, read the source (the pipeline's `make()` or its parameter-builder helper), the existing rows (fetch the table's *actual* blob attribute — e.g. `ripple_param_dict`, `mua_param_dict`, `model_params`, or `params`; there is no universal `param_dict` field), or the docs — those are outside what the bundled scripts surface.
5. **If a verification step cannot run** (no DB connection, custom-class outside `$SPYGLASS_SRC` and `--import` not provided, exit-5 from `db_graph.py`): mark the generated code as a *template*, list each unverified identifier explicitly, and tell the user which facts to fill in before running. Do not present an unverified template as ready-to-run code.

## 9. `*` refuses to join on a "dependent attribute"

DataJoint raises `DataJointError: Cannot join query expressions on dependent attribute '<name>'` when a shared attribute is secondary on **both** sides of a `*`. Two like-named secondary columns reached their tables via different FK paths, so DataJoint can't assume they mean the same thing — it refuses rather than silently producing a semantically-unsafe join. The rule fires at query-build time (no row-level test yet), visible in [datajoint/condition.py `assert_join_compatibility`](https://github.com/datajoint/datajoint-python/blob/master/datajoint/condition.py).

Canonical Spyglass trigger: `SpikeSortingSelection * SpikeSortingRecordingSelection`. Both tables carry `nwb_file_name` and `interval_list_name` as secondary attributes — `SpikeSortingSelection` via `-> IntervalList` (`src/spyglass/spikesorting/v1/sorting.py:199-207`), `SpikeSortingRecordingSelection` via `-> Raw` and `-> SortGroup` (`src/spyglass/spikesorting/v1/recording.py:147-157`). The bare `*` raises immediately. The same shape recurs whenever two selection/recording tables each inherit `nwb_file_name` or `interval_list_name` through different FK paths — a very common pattern across Spyglass pipelines.

**Fix 1 — project the left side down** to drop the colliding secondaries before the `*`:

```python
((SpikeSortingSelection & {'sorting_id': sid}).proj('recording_id')
 * SpikeSortingRecordingSelection
 * SortGroup.SortGroupElectrode * Electrode * BrainRegion
).fetch('region_name')
```

`.proj('recording_id')` keeps the left-side PK (`sorting_id`) plus the one secondary you need to bridge (`recording_id`), discarding `nwb_file_name` and `interval_list_name`. The remaining shared attribute is `recording_id` — secondary on the left, primary on the right. One-sided-secondary joins are legal; the refusal only fires when it's secondary on **both** sides.

**Fix 2 — split into two restrictions** so the two tables never appear in the same `*`:

```python
recording_id = (SpikeSortingSelection & {'sorting_id': sid}).fetch1('recording_id')
(SpikeSortingRecordingSelection
 * SortGroup.SortGroupElectrode * Electrode * BrainRegion
 & {'recording_id': recording_id}
).fetch('region_name')
```

Both fixes are correct. Fix 1 stays composable in one expression; Fix 2 is more legible when you want to pause and inspect `recording_id` mid-debug.

**Diagnostic habit.** Before recommending a multi-table `*` chain, inspect each side's secondary attributes: use `db_graph.py describe` for runtime headings, `code_graph.py describe` for source headings, or `Table.heading.secondary_attributes` inside the user's session. Look for collisions — if any attribute appears in both, you need `.proj()` or a split. The Spyglass attributes most likely to collide are `nwb_file_name` (propagated via `-> Raw`, `-> Session`, `-> IntervalList`, `-> AnalysisNwbfile`, `-> Electrode`) and `interval_list_name` (via `-> IntervalList` on any selection table). When you're unsure, build the join one step at a time and inspect `.heading` after each `*`.
