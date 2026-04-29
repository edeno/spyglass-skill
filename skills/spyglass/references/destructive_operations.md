<!-- pipeline-version: v1 -->

# Destructive Operations — Inspect Before Destroy

This reference owns the canonical paired shapes for every destructive helper in Spyglass and DataJoint. The hard rule (also in SKILL.md Core Directives): **never produce a destroy step without the matching inspect step above it**. Inspect first, get user confirmation, THEN the destroy call. The Spyglass database contains irreplaceable neuroscience research data — the cost of an unwanted cascade is very high; the cost of an extra confirmation round is negligible.

## Contents

- [Required workflow](#required-workflow)
- [Helpers this file covers](#helpers-this-file-covers)
- [When a user explicitly asks to bypass](#when-a-user-explicitly-asks-to-bypass)
- [Paired shapes](#paired-shapes)
  - [Row deletion](#row-deletion)
  - [Merge-table delete helpers](#merge-table-delete-helpers)
  - [File cleanup](#file-cleanup)
  - [Session-wide cleanup](#session-wide-cleanup)
- [Counterfactual / recovery / parameter-swap cascade template](#counterfactual--recovery--parameter-swap-cascade-template)
- [`update1` on params with downstream rows](#update1-on-params-with-downstream-rows)
- [Cross-references](#cross-references)

## Required workflow

Every call to `delete()`, `drop()`, `cleanup()`, `merge_delete()`, `merge_delete_parent()`, `super_delete()`, or `delete_quick()` proceeds through these phases. Do not skip any, and do not collapse Phase 2 and Phase 3 into a single message — give the user time to actually read the inspect output before expecting confirmation.

### Phase 1 — Inspect

Build the restricted relation; do not call the destructive helper yet.

- `print(len(rel_to_delete))` — row count.
- If the count is `0`, stop. The restriction didn't match what the user thinks it did; almost always a bug in the PK fields.
- If the count is *unexpectedly large*, stop and ask whether the restriction is right before proceeding.
- For merge tables, preview the affected part rows. **`(MergeTable & key).parts()` is NOT restriction-aware** — `parts()` returns every declared part regardless of the restriction (DataJoint structural metadata; see `utils/dj_merge_tables.py:95`). Use `MergeTable().merge_restrict(key)` (returns the union of restricted parts as a DataJoint relation) or `MergeTable().merge_get_part(key)` (returns the specific part class for a single matched row), and count rows on each.

### Phase 2 — Report

Output to the user in one message, before asking for confirmation:

- Target table and the restriction used
- Row count
- Sample rows (`.fetch(as_dict=True, limit=5)` or similar)
- What will cascade: child tables that will also lose rows
- For file-cleanup helpers, list filenames that will be deleted
- For large deletes, also report total disk that will be reclaimed: `rel.get_table_storage_usage(human_readable=True)` (sums sizes of referenced analysis files — useful for "is this worth doing" decisions before the user confirms).

### Phase 3 — Wait for explicit confirmation

Do not proceed on silence, hedging, or implicit approval. Clear go-signals: "yes, delete", "go ahead", "ok delete it". Weak signals that need to be paired with evidence the user saw Phase 2's output: "sure", "ok", "looks fine". Anything ambiguous means ask again, naming the specific destructive call you're about to make.

### Phase 4 — Execute

Make the call. If the user explicitly asked for a bypass call (`super_delete`, `force_permission=True`, `merge_delete_parent`), the bypass subsection below has the additional preconditions.

### Phase 5 — Verify (partial deletes)

When the user intended to delete a subset, confirm the remainder matches expectations:

- `print(len(Table & unaffected_restriction))` — count after
- Spot-check that what should still be there still is

## Helpers this file covers

- **DataJoint**: `delete()`, `drop()`, `cautious_delete()`, `super_delete()`, `delete_quick()`
- **Merge-table helpers**: `merge_delete()`, `merge_delete_parent()`
- **File cleanup**: `cleanup()`, `delete_orphans()` — these remove analysis files from disk

Any helper that removes rows or files goes through this file's patterns.

## Team-based protection: `.delete()` is `cautious_delete()`

**Spyglass enforces team-based permissions on deletes.** On any `SpyglassMixin` table, `.delete()` is aliased to `cautious_delete()` — calling `.delete()` automatically invokes the permission check. You do not need to (and should not) reach for `cautious_delete()` by name; just call `.delete()`.

**How the check works** (`_check_delete_permission` at `src/spyglass/utils/mixins/cautious_delete.py:90-150`):

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

**Default response to a `PermissionError`: coordinate, don't bypass.** The error names the experimenter who owns the blocking session(s) — talk to them. If the experimenter is no longer reachable (left the lab, on extended leave), contact a lab admin. The bypass mechanisms exist but are not the first response — they live in [When a user explicitly asks to bypass](#when-a-user-explicitly-asks-to-bypass) below.

If the error message is `Could not find name for datajoint user <name> in LabMember.LabMemberInfo`, the user just needs to be added to `LabMember` (see `setup_troubleshooting.md` "AccessError / PermissionError"). That is a setup gap, not a permission denial — fix the gap, no bypass needed.

**Coverage gaps where the team check does NOT fire (know these — they let data through):**

- **Tables with no Session dependency path** (`cautious_delete.py:110-119`). `.delete()` logs a warning and proceeds without the team check. Lookup tables like `ProbeType`, `FirFilterParameters`, `Lab`, `Institution` fall in this category, and so do any tables whose dependency graph doesn't reach `Session`. Use extra caution with shared lookup rows — someone else's pipeline may depend on them.
- **Tables where the session summary can't be resolved** (`cautious_delete.py:121-126`). A second escape path: if the dependency path to `Session` exists nominally but `_get_exp_summary()` returns empty, the check logs "Could not find a connection from {table} to Session" and returns without raising. This is rarer than the no-Session case but equally silent.
- **Sessions with no `Session.Experimenter` row** raise `PermissionError` with a different message. Fix by populating `Session.Experimenter`, not by bypassing.
- **`merge_delete()`** (the merge-master classmethod) dispatches to `(cls() & uuids).delete(**kwargs)` at `dj_merge_tables.py:444-465`, which routes through the merge master's `delete()` → each part table's `.delete()` → `cautious_delete`. Team check DOES apply.
- **`merge_delete_parent()` BYPASSES the team check** (`dj_merge_tables.py:499, 505`). Both the master delete and the part-parent deletes call `super().delete(...)` directly — jumping to `datajoint.Table.delete` without routing through `cautious_delete`. A user who can't `.delete()` a Session due to team-permissions CAN still `merge_delete_parent()` the same Session's pipeline outputs. Treat `merge_delete_parent()` as the merge-table equivalent of `super_delete()`: use only when you're the data owner or have explicit permission, and always preview with `dry_run=True` first.

### When a user explicitly asks to bypass

Only enter this subsection when the user has explicitly named one of `super_delete`, `force_permission=True`, or `merge_delete_parent` and asked to use it. A `PermissionError` from `cautious_delete` is not by itself a request to bypass — the default response is in the section above (coordinate, don't bypass).

Appropriate scenarios are narrow: admin cleanup after a lab member leaves, fixing a misconfigured experimenter row, or the data owner deleting their own data when the team check is misfiring for a known reason. In every case, run the bypass with `dry_run=True` first when the helper supports it, and report the preview before the actual call.

- **`(Table & key).super_delete(warn=True)`** (`cautious_delete.py:249-254`) — aliases directly to `datajoint.Table.delete`, skipping the permission check entirely. Logs the bypass to `common_usage.CautiousDelete` by default; `warn=False` suppresses both the warning and the log, so the audit trail depends on the default. **`super_delete` does NOT run Spyglass's file cleanup** — analysis / raw NWB files stay on disk because `Nwbfile.cleanup(delete_files=True)` is never called. After a `super_delete`, run the cleanup helpers explicitly (see [File cleanup](#file-cleanup) below).
- **`(Table & key).delete(force_permission=True)`** — skips the team check (`cautious_delete.py:226`) but **stays on the cautious_delete path** for the rest, so the per-`ext_type` external-file cleanup loop at `cautious_delete.py:238-241` still runs. Disk cleanup is NOT skipped here, in contrast with `super_delete`.
- **`MergeMaster.merge_delete_parent(key, dry_run=True)`** — bypasses the team check structurally (see Coverage gaps above). The classmethod form is required; the restricted form `(MergeMaster & key).merge_delete_parent()` silently drops the restriction and would delete every parent.

After a bypass call, treat the next message as a verification step: fetch the post-state, confirm only the intended rows are gone, and run `Nwbfile.cleanup(delete_files=True)` and any pipeline-scoped `cleanup()` helpers to reclaim the disk space `cautious_delete` would have handled.

## Paired shapes

### Row deletion

```python
# Restrict, fetch to preview, confirm, THEN delete.
target = (Session & key)
print(len(target), "rows will be deleted; cascades to downstream tables")
target.fetch(as_dict=True)          # inspect what is there
# After user confirms:  target.delete()
```

#### When `.delete()` raises `IntegrityError (1217)` or `'NoneType' object has no attribute 'groupdict'`

MySQL 8 reports only the top blocking FK row during a cascade. The
blocking row is often in **another user's schema** that your DataJoint
account has no `DELETE` grant on, so the cascade halts and leaves you
with either the raw 1217 error or — if DataJoint's regex-based error
parser fails on the MySQL 8 message text — a downstream `NoneType has
no groupdict` in `datajoint/table.py`.

**Disambiguate.** Run:

```python
dj.conn().query('SHOW GRANTS FOR CURRENT_USER()').fetchall()
```

Look for `DELETE` on the schema named in the FK error. If missing, the
cascade is blocked by a permissions gap, not a bug in your query.

**Fix.** Either (a) ask a DB admin to grant `DELETE` on the blocking
schema, (b) ask the owner of the blocking downstream entry to delete
their row first, or (c) use the per-row workaround when only some rows
are blocked:

```python
for row in (Table & restriction).fetch('KEY', as_dict=True):
    try:
        (Table & row).delete()
    except dj.errors.IntegrityError:
        continue   # keep going; admin will clean up the blocked rows
```

Do not reach for `super_delete()` — it bypasses Spyglass's file cleanup
and the team-permission audit trail.

### Merge-table delete helpers

`merge_delete` is a **classmethod** with `restriction=True` as the default. Calling it on a restricted relation — `(PositionOutput & merge_key).merge_delete()` — silently drops the restriction because Python routes classmethod calls to the class, not the restricted instance. That pattern deletes **every** merge entry. Always pass the restriction as an argument:

```python
# Inspect first
merge_key = PositionOutput.merge_get_part(key).fetch1("KEY")
print((PositionOutput & merge_key).fetch(as_dict=True))
# After confirmation:
# PositionOutput.merge_delete(merge_key)
```

The same classmethod-dispatch shape applies to `merge_delete_parent`, `merge_restrict`, `merge_get_part`, `merge_get_parent`, `merge_view`, and `merge_html`. The complete list of affected methods with correct call forms is in [merge_methods.md](merge_methods.md). Canonical worked example: `notebooks/04_Merge_Tables.ipynb` (jupytext mirror at `py_scripts/04_Merge_Tables.py:198`).

### File cleanup

Two cleanup surfaces with **different signatures** — they do not share a safe-call pattern.

**`AnalysisNwbfile().cleanup(dry_run=False)`** (instance method, `common_nwbfile.py:754`) removes orphaned analysis NWB files across common and custom analysis tables. The same shape applies to pipeline-scoped helpers like `DecodingOutput().cleanup(dry_run=True)`, which removes orphaned `.nc`/`.pkl` files only from the decoding pipeline. Both return `None` in both modes and **log** paths they would remove when `dry_run=True`, then delete when `dry_run=False`. Read the logs before the destroy call.

```python
DecodingOutput().cleanup(dry_run=True)   # LOGS what would be removed
# After confirming the logs look right:
# DecodingOutput().cleanup(dry_run=False)
```

**`Nwbfile.cleanup(delete_files=False)`** (staticmethod, `common_nwbfile.py:140-146`) is **destructive in both modes**. It calls `schema.external["raw"].delete(delete_external_files=delete_files)` unconditionally, which removes external-table entries (the DB-level filepath rows) regardless of `delete_files`. `delete_files=False` only stops the on-disk file removal — it does NOT stop the DB mutation. There is **no** `dry_run` argument; passing `dry_run=True` raises `TypeError`. **Do not present this as a preview step.** If you want to see what would be removed, query the external table directly first (`schema.external["raw"].unused()` returns the entries the cleanup would touch). Do not conflate with `AnalysisNwbfile.cleanup` above, which DOES have a `dry_run` argument.

```python
Nwbfile.cleanup()                    # entries only; files stay on disk
# After confirming entries-removed is what you intended:
# Nwbfile.cleanup(delete_files=True)
```

### Session-wide cleanup

Current Spyglass has no single "delete everything downstream of this session" helper. Compose two steps:

- `(Nwbfile & {"nwb_file_name": f}).delete()` — DataJoint's cascade removes rows from tables with a foreign-key path to `Nwbfile`, routed through `cautious_delete` for the team check. Preview with `.fetch(as_dict=True)` on the restricted relation first.
- For each merge table whose part entries reference the session, call `SomeMergeOutput.merge_delete_parent({"nwb_file_name": f}, dry_run=True)` explicitly. Run `dry_run=True` first, inspect, then `dry_run=False`. `merge_delete_parent` bypasses the team check (see [When a user explicitly asks to bypass](#when-a-user-explicitly-asks-to-bypass)), so treat every call as if the data owner were watching.

## Counterfactual / recovery / parameter-swap cascade template

When the user asks "what changes if I re-run with new params?", "what cascades if I delete X?", or "how do I recover from an in-place edit?", the answer must enumerate four slots — incomplete answers (especially missing the unaffected-branches slot) leave the user without enough information to know what they can re-use vs. what they have to recompute.

**Slot 1 — The new row / new merge_id.** Whether a clean re-run produces a *new* row alongside the old one, or mutates the old row. For Spyglass's pattern, parameter tables (`*Params`) and selection tables (`*Selection`) are typically PK'd on a name; changing values means inserting a *new* parameter row under a *new* name and populating fresh downstream rows from the new selection — the old name still resolves to the old downstream rows. New merge_ids are minted on every fresh populate of a Computed feeding a `*Output` merge.

**Slot 2 — Downstream branches that must be re-selected and re-populated.** Specific table names, walked from the changed table downward. For each branch, name (a) the selection table the user must insert into for the new run, (b) the Computed table whose `populate(key)` must be called, and (c) the merge layer (if any) that gets a new entry. Don't say "downstream pipelines" — name them.

**Slot 3 — Unaffected sibling and upstream branches.** Explicitly enumerated. Symmetric pipelines often re-use the same upstream (LFP, position, sorting, etc.); the unaffected list tells the user what they can keep without recomputing. *Failure mode:* answers that walk only the downstream cascade and leave the user guessing whether LFP / position / sorting are affected. They usually aren't, but say so.

**Slot 4 — Verification step.** Concrete command for confirming the cascade scope. From source: `Table.descendants()` / `Table.ancestors()` (DataJoint's runtime introspection on the `dj.Diagram`-derived graph). From a live DB: `db_graph.py path --down <Class>` / `db_graph.py path --up <Class>`. From source-only (no live DB): `code_graph.py path --down <Class>`. Name the actual command, not "walk the graph."

### Worked-example pattern

For a parameter swap on a `*Params` table:

```text
1. New row:        insert under a new param_name; old rows survive at the old name.
2. Re-populate:    *Selection insert with new param_name → *Computed.populate(key)
                   → new entry in *Output (if merge); each leaf below the merge
                   that the user wants under the new params needs its own
                   selection insert + populate.
3. Unaffected:     <list specific upstream tables that don't depend on the
                   changed param — typically LFP, position, sorting branches
                   parallel to the affected one>.
4. Verify scope:   `Table.descendants(as_objects=True)` from <ChangedTable>;
                   confirm the union of slot-2 entries matches.
```

The four-slot template applies equally to deletion-cascade questions (slot 1 reads "rows removed from <Table>"), in-place-edit recovery (slot 1 reads "the row stays at the same key with the new values; existing downstream rows now have stale provenance"), and counterfactual "what if I had run with X" questions.

## `update1` on params with downstream rows

`update1()` silently mutates a row in place. On a parameter table (`RippleParameters`, `DecodingParameters`, `MetricParameters`, …) this is almost always wrong if anything downstream has already been populated against that key.

Concrete shape:

```python
# WRONG — mutates the parameter row in place. Existing RippleTimesV1 rows
# computed with the old threshold still reference this key by name, but
# `ripple_param_name="default"` now points to a *different* parameter blob
# than when those downstream rows were populated. Provenance is silently
# corrupted. (Shape note: `speed_threshold` lives nested under
# `ripple_detection_params`, NOT at the top level of `ripple_param_dict` —
# see `ripple_pipeline.md` and `feedback_loops.md` for the full blob shape.)
RippleParameters().update1({
    "ripple_param_name": "default",
    "ripple_param_dict": {
        "speed_name": "head_speed",
        "ripple_detection_algorithm": "Kay_ripple_detector",
        "ripple_detection_params": {"speed_threshold": 0.1},  # changed value
    },
})
```

Correct shape: insert a **new** parameter row with a different name, then populate downstream against the new name. Old rows stay intact and interpretable.

```python
RippleParameters().insert1({
    "ripple_param_name": "tighter_thresh",
    "ripple_param_dict": {
        "speed_name": "head_speed",
        "ripple_detection_algorithm": "Kay_ripple_detector",
        "ripple_detection_params": {"speed_threshold": 0.1},
    },
})
# RippleLFPSelection rows already exist for the LFP band + group; no
# new selection row needed. Build a fully-scoped populate key —
# RippleTimesV1's PK includes RippleLFPSelection, RippleParameters,
# AND PositionOutput.proj(pos_merge_id='merge_id') (`ripple/v1/ripple.py:182`).
# Restricting populate to `{"ripple_param_name": ...}` alone leaves
# the upstream selection / position open and re-runs against every
# eligible (RippleLFPSelection, pos_merge_id) combo under the new
# params name — usually NOT what you want for a re-run scoped to one
# downstream analysis.
populate_key = {
    **rip_sel_key,                  # the RippleLFPSelection PK fields
    "ripple_param_name": "tighter_thresh",
    "pos_merge_id": pos_merge_id,   # specific PositionOutput merge_id
}
RippleTimesV1.populate(populate_key)
```

When `update1()` *is* fine: only when nothing downstream consumes the row yet. Verify explicitly before mutating — don't assume:

```python
# For each child of the param table, check no rows reference this key.
# `descendants()` returns table NAMES by default (datajoint table.py:220);
# pass `as_objects=True` to get FreeTable objects you can restrict.
for child in RippleParameters().descendants(as_objects=True):
    if "ripple_param_name" not in child.heading.names:
        continue  # skip descendants that don't carry this PK field
    n = len(child & {"ripple_param_name": "default"})
    assert n == 0, f"{child.table_name} has {n} rows under this params name"

# Or, for the database-graph topology view, run:
#   python skills/spyglass/scripts/db_graph.py path --down RippleParameters
# (db_graph.py reads from the connected DataJoint database, NOT
# from source — see scripts/README.md for the source-vs-runtime split.)
```

If any descendant has rows, do not `update1()` — insert a new params row instead.

## Cross-references

- [merge_methods.md](merge_methods.md) — full classmethod-discard gotcha list and corrected call forms
- [runtime_debugging.md](runtime_debugging.md) — diagnosing whether a destructive call removed unexpected rows
- [datajoint_api.md](datajoint_api.md) — restriction semantics the inspect step depends on
