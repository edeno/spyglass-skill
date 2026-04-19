# Common Mistakes — Expanded

Expanded prose for the top-5 Spyglass footguns summarized in SKILL.md. Each section gives the full mechanism, fix, and cross-reference. Load this reference when the user's code shows one of these shapes, or when the SKILL.md one-liner needs a longer explanation.

## Contents

- [1. Classmethod restriction discard on merge tables](#1-classmethod-restriction-discard-on-merge-tables)
- [2. Too-loose restriction + `fetch1()`](#2-too-loose-restriction-fetch1)
- [3. Passing `skip_duplicates=True` to `insert_sessions`](#3-passing-skip_duplicatestrue-to-insert_sessions)
- [4. `fetch_nwb()` silently returns a list](#4-fetch_nwb-silently-returns-a-list)
- [5. Destructive call without the paired inspect step](#5-destructive-call-without-the-paired-inspect-step)
- [6. Interval / epoch mismatch between pipeline selections](#6-interval-epoch-mismatch-between-pipeline-selections)
- [7. Fragmenting lab-wide search with inconsistent names](#7-fragmenting-lab-wide-search-with-inconsistent-names)

## 1. Classmethod restriction discard on merge tables

`(PositionOutput & merge_key).merge_delete()` silently drops the `& merge_key` — Python routes classmethod calls to the class, not the restricted instance. With `merge_delete`'s default `restriction=True`, the call operates on the entire merge table and asks the user to confirm deletion of every row.

**Fix.** Always pass the restriction as an argument: `PositionOutput.merge_delete(merge_key)`.

The same classmethod-dispatch rule applies to `merge_delete_parent`, `merge_restrict`, `merge_get_part`, `merge_get_parent`, `merge_view`, and `merge_html`. Full affected-method list with correct call forms: [merge_and_mixin_methods.md](merge_and_mixin_methods.md).

## 2. Too-loose restriction + `fetch1()`

`{"nwb_file_name": f}` alone usually matches many rows — every interval, every param set, every pipeline version for that session. `fetch1()`, `merge_get_part()`, and `fetch1_dataframe()` all raise "expected one row, got N" under an under-specified restriction. The decoding-only `DecodingOutput.fetch_results()` shares this behavior since it wraps `fetch1()` internally — but it is decoding-specific, not a universal helper.

**Fix.** Add enough primary-key fields to pick exactly one row. Discovery pattern: restrict loosely first, inspect with `.fetch(as_dict=True)` or `MergeTable.merge_restrict(key)`, then build a fully-specified key. Full footgun and fix: [datajoint_api.md](datajoint_api.md).

## 3. Passing `skip_duplicates=True` to `insert_sessions`

`skip_duplicates` is a DataJoint `.insert1()` / `.insert()` flag — valid for manual lookup-table inserts like `ProbeType.insert1(...)` or `Lab.insert1(...)`. `insert_sessions` does not accept it. Passing it raises `TypeError: unexpected keyword argument 'skip_duplicates'`.

**Fix.** For re-ingesting raw NWB data, use `reinsert=True` on `insert_sessions` instead. Full ingestion flow: [ingestion.md](ingestion.md).

## 4. `fetch_nwb()` silently returns a list

Unlike `fetch1()`, `fetch_nwb()` does NOT raise when the restriction matches multiple rows — it silently returns a list. `(Table & key).fetch_nwb()[0]` on an under-specified restriction picks an arbitrary row and returns a plausibly-shaped result with no warning. This is the quiet cousin of Common Mistake #2.

**Fix.** Restrict to exactly one row before calling `fetch_nwb()`. The same cardinality check that guards `fetch1()` protects `fetch_nwb()[0]`. See [datajoint_api.md](datajoint_api.md).

## 5. Destructive call without the paired inspect step

Every destructive helper in Spyglass — `delete`, `drop`, `cautious_delete`, `super_delete`, `delete_quick`, `merge_delete`, `merge_delete_parent`, `delete_downstream_parts`, `cleanup`, `delete_orphans` — has a preview shape that must run first. `dry_run=True` for cleanups, `fetch(as_dict=True)` before `.delete()`, etc. The pattern is inspect → get user confirmation → destroy.

**Fix.** Never produce a destroy step without the matching inspect step above it. Full paired shapes for every helper: [destructive_operations.md](destructive_operations.md).

## 6. Interval / epoch mismatch between pipeline selections

Spyglass pipelines take different interval-name fields, and two upstream tables populated individually for a session may not actually refer to the same temporal support. Symptoms: a downstream populate silently does nothing; a join between two upstream tables returns empty even though each has rows for the session; decoding or ripple outputs are suspiciously short.

No universal `target_interval_list_name` exists. The field varies by pipeline:
- `IntervalList.interval_list_name` — the primary key of the source table
- `LFPSelection` / `LFPBandSelection` — `target_interval_list_name`
- `SpikeSortingRecordingSelection` (v0) — `sort_interval_name`
- Artifact removal outputs — `artifact_removed_interval_list_name`
- Decoding V1 — `encoding_interval` AND `decoding_interval` (two separate intervals, both projected from `IntervalList.interval_list_name`)

A restriction that works on one selection table can silently match zero rows on another because the field name, the interval-name value, or both differ. DataJoint does not warn when a restriction field is missing from the table — the field is silently ignored.

**Fix.** Inspect the downstream table's primary key (`Table.heading.primary_key`) to see the actual interval-field name. Confirm the value exists for the session with `(IntervalList & {"nwb_file_name": f}).fetch("interval_list_name")`. If the selection was inserted against a different interval than the one you're now restricting, re-insert with the correct value. Full triage including diagnostic queries and the two-interval decoding case: [runtime_debugging.md](runtime_debugging.md) Signature F.

## 7. Fragmenting lab-wide search with inconsistent names

DataJoint restrictions are exact string matches. When lab members insert the same anatomical structure as `CA1`, `hippocampus`, `HPC`, `CA1_1`, `Hippocampus`, and `Hipp`, a query like `(Electrode & {"region_name": "CA1"})` returns only the `CA1` rows — the other five spellings are invisible. Lab-wide analyses silently return partial data, and nobody notices until someone audits row counts by hand.

The same splits happen with any free-form string PK field: subject names (`j16` vs `J16` vs `j1620210710`), electrode group names (`tet1` vs `tetrode_1` vs `1`), interval list names (`sleep` vs `Sleep` vs `sleep_1`), parameter-set names (`default` vs `default_v2` vs `lab_default`), experimenter names, filter names, sort-group labels. Each variant fragments a field that downstream joins and restrictions depend on.

**Fix.** Before inserting a new string into any free-form PK field, query existing values for that table and align to the convention already in use:

```python
# What region names does the lab already use?
BrainRegion.fetch("region_name")
# Electrode groups already inserted for this session
(ElectrodeGroup & {"nwb_file_name": f}).fetch("electrode_group_name")
# Existing parameter-set names on a selection table
ParamsTable.fetch("params_name")
```

Treat existing values in `BrainRegion`, `LabMember`, `LabTeam`, and the lab's established parameter tables as the de facto naming convention — they are what downstream analyses pin to. Diverge only with a specific reason, and when you do, pick an informatively-distinct name (not a typo-variant that collides under casing or whitespace normalization).

This skill can route you to the tables to inspect, but it cannot tell you "the right spelling" — that is lab convention. Surface the existing options to the user and let them choose alignment vs. a justified new name. Related proactive pattern (before inserting a duplicate-content parameter set): [feedback_loops.md](feedback_loops.md) "Pre-insert check on parameter/selection tables".
