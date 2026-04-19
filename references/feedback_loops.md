# Common Feedback Loops

Quality-critical Spyglass operations have a **validator → fix → proceed** shape: run a check, fix anything unexpected, only advance when the check passes. These are proactive versions of the rules in SKILL.md's Common Mistakes — they prevent bugs rather than diagnose them after the fact. Load this reference when the user is about to do one of the operations below and you want to teach the check alongside the action.

## Contents

- [Post-ingestion verification](#post-ingestion-verification)
- [Pre-insert check on parameter/selection tables](#pre-insert-check-on-parameterselection-tables)
- [Pre-`populate()` upstream check](#pre-populate-upstream-check)
- [Pre-`fetch1()` cardinality check](#pre-fetch1-cardinality-check)
- [Post-`populate()` verification](#post-populate-verification)
- [Inspect-before-destroy](#inspect-before-destroy)

## Post-ingestion verification

After `sgi.insert_sessions(fname)`, confirm the session landed cleanly before any pipeline populates. If any check fails, fix the NWB file and rerun with `reinsert=True`. Only start pipeline work when all three pass. Full ingestion flow: [ingestion.md](ingestion.md).

```python
f = "j1620210710_.nwb"                                  # copy-form; Spyglass appends the "_"
(Session & {"nwb_file_name": f}).fetch1("session_id")   # must return 1 row
print(len(IntervalList & {"nwb_file_name": f}))         # must be > 0
print(len(Electrode & {"nwb_file_name": f}))            # compare to NWB metadata
```

## Pre-insert check on parameter/selection tables

Before inserting a new row into a parameter or selection table, look for an existing row that already captures what you want. Duplicates fragment downstream queries: two rows with identical content but different names mean half the lab's analyses pin to one name and half to the other, and `(ParamsTable & {"params_name": "default"}).fetch1()` returns whichever user's "default" was inserted first. The fix is a before-insert search, not a post-hoc cleanup.

```python
# Before inserting, look at what already exists in the lab
existing = ParamsTable.fetch(as_dict=True)
for row in existing:
    # Compare content, not name — two rows can mean the same thing under different labels
    if (row["low_hz"] == 6.0 and row["high_hz"] == 10.0
            and row["welch_nperseg"] == 1024):
        print(f"Equivalent set already exists as '{row['params_name']}' — reuse this")
        break
else:
    # Genuinely new — insert with an informative, self-describing name
    ParamsTable.insert1({
        "params_name": "theta_6_10_hz_welch_1024",
        "low_hz": 6.0, "high_hz": 10.0, "welch_nperseg": 1024,
    })
```

This is not "never insert." Genuinely new parameter sets *should* exist — the loop is "check-then-decide," and the decision often legitimately lands on insert. What it prevents is unintentional duplication that quietly splits downstream work.

When the decision lands on insert, name quality matters:

- Poor (ambiguous, collides easily, doesn't survive a grep): `default`, `my_params`, `v2`, `test`, `tmp`.
- Informative (self-describing, searchable, collision-resistant): `theta_6_10_hz_welch_1024`, `dlc_smoothed_5px_conf_05`, `lfp_60hz_notch_1khz`.

The same check-then-decide loop applies to any free-form string primary key where a user picks the value: electrode-group names, interval-list names, filter names, sort-group names. Whenever you're about to create a new string that downstream work will join on, first ask: *is there already a row in this table that means the same thing?*

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

Canonical feedback-loop shape — inspect is the validator, user confirmation is the pass gate, the destructive call is the proceed step. Paired shapes for every destructive helper: [destructive_operations.md](destructive_operations.md).

```python
target = (SomeTable & restriction)
target.fetch(as_dict=True)   # inspect scope; cascade preview for .delete()
# Get explicit user confirmation here
target.delete()              # only after confirmation
```
