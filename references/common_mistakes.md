# Common Mistakes — Expanded

Expanded prose for the top-5 Spyglass footguns summarized in SKILL.md. Each section gives the full mechanism, fix, and cross-reference. Load this reference when the user's code shows one of these shapes, or when the SKILL.md one-liner needs a longer explanation.

## Contents

- [1. Classmethod restriction discard on merge tables](#1-classmethod-restriction-discard-on-merge-tables)
- [2. Too-loose restriction + `fetch1()`](#2-too-loose-restriction-fetch1)
- [3. Passing `skip_duplicates=True` to `insert_sessions`](#3-passing-skip_duplicatestrue-to-insert_sessions)
- [4. `fetch_nwb()` silently returns a list](#4-fetch_nwb-silently-returns-a-list)
- [5. Destructive call without the paired inspect step](#5-destructive-call-without-the-paired-inspect-step)

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
