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

## Team-based protection: `.delete()` is `cautious_delete()`

**Spyglass enforces team-based permissions on deletes.** On any `SpyglassMixin` table, `.delete()` is aliased to `cautious_delete()` — calling `.delete()` automatically invokes the permission check. You do not need to (and should not) reach for `cautious_delete()` by name; just call `.delete()`.

**How the check works** (`src/spyglass/utils/mixins/cautious_delete.py:90-150`):

1. Reads the DataJoint user from `dj.config["database.user"]`.
2. If that user is flagged `admin=1` in `LabMember.LabMemberInfo`, the check is skipped.
3. Otherwise, walks to `Session.Experimenter` through the table's dependencies and collects the experimenter(s) of every session that would be affected.
4. For each experimenter, checks whether the current user shares a team via `LabTeam.get_team_members(experimenter)`. By convention every experimenter has a personal team auto-created at ingest, so the user must either be on that personal team or on a broader team that includes the experimenter.
5. If any session has no experimenter or the user shares no team with an experimenter, raises `PermissionError` naming the user, the experimenter, and the blocking sessions.

**What the PermissionError means.** It is not a bug in your query or restriction. It means another lab member owns the session(s) you're about to delete. Read the error message — it names who owns the data. The fix is social, not technical: coordinate with the data owner, not bypass the check.

```python
# You ran:
(Session & {"nwb_file_name": "j1620210710_.nwb"}).delete()
# It raised:
# PermissionError: User 'edeno' is not on a team with 'jsmith', an experimenter for session(s):
#   nwb_file_name: j1620210710_.nwb
# -> Talk to jsmith, not to super_delete().
```

**The two bypass mechanisms and when they are appropriate.**

- **`super_delete()`** (`cautious_delete.py:249-254`) — aliases directly to `datajoint.Table.delete`, skipping the permission check entirely. Logs the bypass to `common_usage.CautiousDelete` for audit. Appropriate only when you are the data owner OR have explicit written permission from the owner AND there is a specific reason the team check is misfiring.
- **`.delete(force_permission=True)`** — same effect, also logs. Same guidance.

Both exist for legitimate edge cases (admin cleanup after a lab member leaves, fixing a misconfigured experimenter). Neither is a fallback for "the PermissionError is annoying." Treat either call as if it had a social cost — because it does.

**Coverage gaps to know about.**

- Tables with no `Session` link bypass the check with a warning log (`cautious_delete.py:114-119`). Lookup tables like `ProbeType` or `FirFilterParameters` fall in this category — `.delete()` will work without a team check. Use extra caution with shared lookup rows; someone else's pipeline may depend on them.
- Sessions with no `Session.Experimenter` row raise `PermissionError` with a different message. Fix by ensuring every Session has an experimenter populated, not by bypassing.
- Merge-table `merge_delete()` / `merge_delete_parent()` are classmethods on `_Merge` (see below) — they go through DataJoint's delete path but the team check applies via the part-table `delete()` calls. Still: inspect before calling.

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

The same classmethod-dispatch shape applies to `merge_delete_parent`, `merge_restrict`, `merge_get_part`, `merge_get_parent`, `merge_view`, and `merge_html`. The complete list of affected methods with correct call forms is in [merge_and_mixin_methods.md](merge_and_mixin_methods.md). Canonical worked example: `notebooks/04_Merge_Tables.ipynb` (jupytext mirror at `py_scripts/04_Merge_Tables.py:198`).

### File cleanup

Two cleanup surfaces with **different signatures** — they do not share a safe-call pattern.

**`AnalysisNwbfile().cleanup(dry_run=False)`** (instance method, `common_nwbfile.py:754`) removes orphaned analysis NWB files across common and custom analysis tables. The same shape applies to pipeline-scoped helpers like `DecodingOutput().cleanup(dry_run=True)`, which removes orphaned `.nc`/`.pkl` files only from the decoding pipeline. Both return `None` in both modes and **log** paths they would remove when `dry_run=True`, then delete when `dry_run=False`. Read the logs before the destroy call.

```python
DecodingOutput().cleanup(dry_run=True)   # LOGS what would be removed
# After confirming the logs look right:
# DecodingOutput().cleanup(dry_run=False)
```

**`Nwbfile.cleanup(delete_files=False)`** (staticmethod, `common_nwbfile.py:140`) removes DataJoint filepath entries for raw NWB files not currently referenced. The default (`delete_files=False`) removes only the DB-level entries, leaving the files on disk — use this as the inspect-equivalent step. Setting `delete_files=True` also removes the files themselves. There is **no** `dry_run` argument, and passing `dry_run=True` raises `TypeError`. Do not conflate with `AnalysisNwbfile.cleanup` above.

```python
Nwbfile.cleanup()                    # entries only; files stay on disk
# After confirming entries-removed is what you intended:
# Nwbfile.cleanup(delete_files=True)
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
