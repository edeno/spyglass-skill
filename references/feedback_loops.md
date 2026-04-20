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

Before inserting a new row into a parameter or selection table, look for an existing row that already captures what you want. Duplicates fragment downstream queries: two rows with identical content but different names mean half the lab's analyses pin to one name and half to the other, and `(TrodesPosParams & {"trodes_pos_params_name": "default"}).fetch1()` returns whichever user's "default" was inserted first. The fix is a before-insert search, not a post-hoc cleanup.

Note on field names: every Spyglass parameter table uses a table-specific PK field, not a universal `params_name`. Examples: `trodes_pos_params_name` (`TrodesPosParams`), `ripple_param_name` (`RippleParameters`), `artifact_params_name` (`ArtifactDetectionParameters`), `unit_filter_params_name` (`UnitSelectionParams`), `dlc_si_params_name` (`DLCSmoothInterpParams`). Inspect `Table.heading.primary_key` to get the exact field for the table you're about to write — do not assume the pattern.

```python
# Before inserting, look at what already exists in the lab.
# Example uses RippleParameters / ripple_param_name; substitute your table's
# actual name-field (see note above).
existing = RippleParameters.fetch(as_dict=True)
for row in existing:
    # Compare content, not name — two rows can mean the same thing under different labels
    params = row["ripple_param_dict"]   # params blob field; inspect the table's heading
    if (params.get("speed_threshold") == 4.0
            and params.get("ripple_detection_params", {}).get("sampling_frequency") == 1000):
        print(f"Equivalent set already exists as '{row['ripple_param_name']}' — reuse this")
        break
else:
    # Genuinely new — insert with an informative, self-describing name
    RippleParameters.insert1({
        "ripple_param_name": "kay_speed4_fs1000",
        "ripple_param_dict": {...},
    })
```

This is not "never insert." Genuinely new parameter sets *should* exist — the loop is "check-then-decide," and the decision often legitimately lands on insert. What it prevents is unintentional duplication that quietly splits downstream work.

When the decision lands on insert, name quality matters:

- Poor (ambiguous, collides easily, doesn't survive a grep): `default`, `my_params`, `v2`, `test`, `tmp`.
- Informative (self-describing, searchable, collision-resistant): `kay_speed4_fs1000`, `dlc_smoothed_5px_conf_05`, `lfp_60hz_notch_1khz`.

The same check-then-decide loop applies to any free-form string primary key where a user picks the value: electrode-group names, interval-list names, filter names, sort-group names. Whenever you're about to create a new string that downstream work will join on, first ask: *is there already a row in this table that means the same thing?*

### Before the insert lands, run two self-tests

These are cheap to run and catch the two most common silent failures after a lab-wide search shows nothing equivalent exists.

**Understand-each-field test.** Before inserting a params blob you copied from a colleague's notebook or an older analysis, can you explain what every value in it does? `kappa`, `target_variance`, `num_ar_iters`, `filter_sampling_rate`, `welch_nperseg` — each affects the output in a way the consumer's `make()` assumes. If you don't know what a field does, read the source for the computed table (`populate()` → `make()` reads the field at some point) or ask. Inserting values you don't understand is how a silent-wrong-analysis gets shipped: `populate()` succeeds, results look plausible, the downstream figure is incorrect in a way no error message will surface.

**Name-describes-content test.** Can a reader who greps for your `params_name` (or `filter_name`, or `sort_group_name`) predict what the row contains without opening the blob? Good names survive this test; bad names fail it silently. `default_v2`, `my_params`, `theta` (without bandpass), `trodes_updated`, `fixed_version` — all fail. `kay_speed4_fs1000`, `theta_6_10_hz_welch_1024`, `lfp_60hz_notch_30khz` — all pass. Rename before inserting if the current name is self-misleading. The renaming step costs seconds; the cost of a lab member pinning their analysis to a name that turns out to mean something different is weeks of corrupted downstream work.

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
