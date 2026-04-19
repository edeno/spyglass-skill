# Common Feedback Loops

Quality-critical Spyglass operations have a **validator → fix → proceed** shape: run a check, fix anything unexpected, only advance when the check passes. These are proactive versions of the rules in SKILL.md's Common Mistakes — they prevent bugs rather than diagnose them after the fact. Load this reference when the user is about to do one of the operations below and you want to teach the check alongside the action.

## Contents

- [Post-ingestion verification](#post-ingestion-verification)
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
- The key you built includes a field that doesn't exist on `key_source` — DataJoint silently ignores unknown fields in a restriction, producing an empty match.

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
