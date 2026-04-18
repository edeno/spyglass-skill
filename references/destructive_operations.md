# Destructive Operations — Inspect Before Destroy

This reference owns the canonical paired shapes for every destructive helper in Spyglass and DataJoint. The hard rule (also in SKILL.md Core Directives): **never produce a destroy step without the matching inspect step above it**. Inspect first, get user confirmation, THEN the destroy call. The Spyglass database contains irreplaceable neuroscience research data — the cost of an unwanted cascade is very high; the cost of an extra confirmation round is negligible.

## Contents

- [Helpers this file covers](#helpers-this-file-covers)
- [Paired shapes](#paired-shapes)
  - [Row deletion](#row-deletion)
  - [Merge-table delete helpers](#merge-table-delete-helpers)
  - [File cleanup](#file-cleanup)
  - [delete_downstream_parts](#delete_downstream_parts)
- [Cross-references](#cross-references)

## Helpers this file covers

- **DataJoint**: `delete()`, `drop()`, `cautious_delete()`, `super_delete()`, `delete_quick()`
- **Merge-table helpers**: `merge_delete()`, `merge_delete_parent()`, `delete_downstream_parts()`
- **File cleanup**: `cleanup()`, `delete_orphans()` — these remove analysis files from disk

Any helper that removes rows or files goes through this file's patterns.

## Paired shapes

### Row deletion

```python
# Restrict, fetch to preview, confirm, THEN delete.
target = (Session & key)
print(len(target), "rows will be deleted; cascades to downstream tables")
target.fetch(as_dict=True)          # inspect what is there
# After user confirms:  target.delete()
```

### Merge-table delete helpers

`merge_delete` is a **classmethod** with `restriction=True` as the default. Calling it on a restricted relation — `(PositionOutput & merge_key).merge_delete()` — silently drops the restriction because Python routes classmethod calls to the class, not the restricted instance. That pattern deletes **every** merge entry. Always pass the restriction as an argument:

```python
# Inspect first
merge_key = PositionOutput.merge_get_part(key).fetch1("KEY")
print((PositionOutput & merge_key).fetch(as_dict=True))
# After confirmation:
# PositionOutput.merge_delete(merge_key)
```

The same classmethod-dispatch shape applies to `merge_delete_parent`, `merge_restrict`, `merge_get_part`, `merge_get_parent`, `merge_view`, `merge_html`, and to `Nwbfile.cleanup` (staticmethod). The complete list of affected methods with correct call forms is in [merge_and_mixin_methods.md](merge_and_mixin_methods.md). Canonical worked example: `notebooks/04_Merge_Tables.ipynb` (jupytext mirror at `py_scripts/04_Merge_Tables.py:198`).

### File cleanup

`cleanup()` is pipeline-scoped. `DecodingOutput().cleanup()` removes only orphaned `.nc`/`.pkl` files from the decoding pipeline; `AnalysisNwbfile.cleanup()` removes orphaned analysis NWB files across tables. Both follow the same dry-run-first discipline.

`cleanup()` returns `None` in both modes — it **logs** paths it would remove when `dry_run=True` and deletes them when `dry_run=False`. Read the logs before the destroy call.

```python
DecodingOutput().cleanup(dry_run=True)   # LOGS what would be removed
# After confirming the logs look right:
# DecodingOutput().cleanup(dry_run=False)
```

### delete_downstream_parts

Always call on a restricted relation, never the whole table. `reload_cache=True` because the cache can be stale and silently return "nothing to delete" when entries actually exist:

```python
(Nwbfile & {"nwb_file_name": nwb_copy_file_name}).delete_downstream_parts(
    reload_cache=True, dry_run=True,
)
# After inspecting the dry_run output:
# (Nwbfile & {...}).delete_downstream_parts(reload_cache=True, dry_run=False)
```

## Cross-references

- [merge_and_mixin_methods.md](merge_and_mixin_methods.md) — full classmethod-discard gotcha list and corrected call forms
- [runtime_debugging.md](runtime_debugging.md) — diagnosing whether a destructive call removed unexpected rows
- [datajoint_api.md](datajoint_api.md) — restriction semantics the inspect step depends on
