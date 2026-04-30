# Spyglass Analysis Workflows

## Contents

- [Exploring Available Data](#exploring-available-data)
- [Cross-Table Joins](#cross-table-joins)
- [Common Patterns](#common-patterns)
- [Troubleshooting](#troubleshooting)

Cross-table workflow planning and multi-pipeline analysis recipes — patterns for assembling queries that span session, position, sorting, and decoding tables. For pipeline-specific workflows (position, LFP, spike sorting, decoding), see the corresponding pipeline reference files; for relationship and runtime questions, route via [feedback_loops.md § Tool routing](feedback_loops.md#tool-routing-for-relationship-and-lookup-questions) instead of treating this file as a catch-all.

## Exploring Available Data

### List Sessions and Intervals

```python
from spyglass.common import Session, IntervalList

# View all sessions
Session.fetch(limit=20)

# Sessions for specific subject
Session & {'subject_id': 'J16'}

# Find experimenters
Session.Experimenter & {'nwb_file_name': nwb_file}

# All intervals for session
IntervalList & {'nwb_file_name': nwb_file}

# Search for specific intervals
IntervalList & {'nwb_file_name': nwb_file} & 'interval_list_name LIKE "%r1%"'
```

### Preview Analysis Results

```python
from spyglass.position import PositionOutput
from spyglass.lfp import LFPOutput
from spyglass.spikesorting.spikesorting_merge import SpikeSortingOutput
from spyglass.decoding import DecodingOutput

# What exists for this session?
PositionOutput.merge_restrict({'nwb_file_name': nwb_file})
LFPOutput.merge_restrict({'nwb_file_name': nwb_file})
SpikeSortingOutput.merge_restrict({'nwb_file_name': nwb_file})
DecodingOutput.merge_restrict({'nwb_file_name': nwb_file})
```

---

## Cross-Table Joins

### Find Data by Experimenter

```python
from spyglass.common import Session
from spyglass.position import PositionOutput

sessions = (Session.Experimenter & {'lab_member_name': 'Name'}).fetch('nwb_file_name')

for s in sessions:
    results = PositionOutput.merge_restrict({'nwb_file_name': s})
    if len(results):
        print(f"{s}: {len(results)} position entries")
```

### Find Data by Brain Region

```python
from spyglass.common import BrainRegion, Electrode
from spyglass.lfp import LFPElectrodeGroup, LFPOutput

# LFPOutput.LFPV1 is keyed by `lfp_electrode_group_name`, not raw
# `electrode_group_name`. Resolve through LFPElectrodeGroup.LFPElectrode
# before restricting the merge table.
lfp_electrodes = (
    LFPElectrodeGroup.LFPElectrode
    & (Electrode & (BrainRegion & {'region_name': 'CA1'}))
).fetch("KEY", as_dict=True)

seen = set()
for row in lfp_electrodes:
    lfp_key = {
        "nwb_file_name": row["nwb_file_name"],
        "lfp_electrode_group_name": row["lfp_electrode_group_name"],
    }
    ident = tuple(lfp_key.items())
    if ident in seen:
        continue
    seen.add(ident)
    lfp = LFPOutput.merge_restrict(lfp_key)
    if len(lfp):
        print(f"Found LFP for: {lfp_key}")
```

### Navigate Upstream/Downstream

```python
# Exploratory graph search. For copyable merge-table code, prefer
# PositionOutput.merge_restrict({"nwb_file_name": nwb_file}).
PositionOutput() << f"nwb_file_name = '{nwb_file}'"

# Find sessions with specific parameters
Session() >> 'trodes_pos_params_name="default"'
```

---

## Common Patterns

### Batch Processing (One Merge, Many Sessions)

```python
import datajoint as dj                        # for dj.DataJointError below
from spyglass.common import Session
from spyglass.position import PositionOutput

sessions = (Session & {"subject_id": "J16"}).fetch("KEY")

results = []
for sk in sessions:
    key = {**sk, "interval_list_name": "task"}
    # `merge_get_part(key)` raises (ValueError on the strict-source
    # path, `utils/dj_merge_tables.py:634`; DataJointError on other
    # internal failure modes) before returning when zero or multiple
    # parts match. A `len(part) == 1` guard never executes on the
    # failure branches, so wrap the call in try/except and use
    # `multi_source=True` to opt out of the strict-one check when
    # multiple matches are acceptable.
    try:
        part = PositionOutput.merge_get_part(key)
    except (dj.DataJointError, ValueError):
        # zero or multiple matches — skip this session in the batch
        continue
    # `merge_get_part` raises only on zero or multiple matching PART
    # TABLES — it does NOT prove the returned part relation has
    # exactly one ROW. Verify before fetch1, otherwise a multi-row
    # part will raise mid-batch.
    if len(part) != 1:
        continue
    results.append((PositionOutput & part.fetch1("KEY")).fetch1_dataframe())
```

For batch loops where ambiguous sessions are common, `merge_get_part(key, multi_source=True)` returns the part(s) without raising, and the caller iterates the parts explicitly.

### Incremental Exploration

```python
# Start broad
IntervalList & {'nwb_file_name': nwb_file}

# Add constraints
intervals = (IntervalList & {'nwb_file_name': nwb_file}
             & 'interval_list_name LIKE "%r1%"')

# Preview before fetching
intervals.fetch(limit=5)
```

### Interval Arithmetic

Spyglass ships a NumPy-based interval-manipulation suite in `spyglass.common.common_interval` that users routinely reinvent because the tutorials don't mention it. Use the `Interval` class (`common/common_interval.py:323`); the older module-level wrappers `interval_list_intersect`, `interval_list_union`, `interval_list_complement`, `intervals_by_length`, etc. log deprecation notices and forward to `Interval.intersect` / `Interval.by_length` / similar (`common_interval.py:1020, 1123`). Input shape is the standard `(N, 2)` start/stop array.

```python
from spyglass.common import IntervalList
from spyglass.common.common_interval import Interval
from spyglass.ripple.v1.ripple import RippleTimesV1

# Example: ripple intervals AND task intervals, >= 50 ms only.
# `RippleTimesV1` stores the ripple intervals as an NWB object — only
# `ripple_times_object_id` is on the heading (`ripple/v1/ripple.py:189`);
# the per-row dataframe comes via `fetch1_dataframe()` /
# `fetch_dataframe()` (`ripple.py:240, 245`), each row of which has
# `start_time` / `end_time` columns. Convert to (start, end) pairs
# before constructing the Interval.
ripple_key = {                  # build a fully-specified RippleTimesV1 key
    "nwb_file_name": nwb_file,  # use the same nwb_file_name throughout
    # ... + the rest of the RippleTimesV1 primary key:
    #     RippleLFPSelection fields (filter_name, target_interval_list_name,
    #     filter_sampling_rate, lfp_band_sampling_rate),
    #     ripple_param_name (from RippleParameters),
    #     pos_merge_id (projected from PositionOutput.merge_id).
}
ripple_df = (RippleTimesV1 & ripple_key).fetch1_dataframe()
ripples = ripple_df[["start_time", "end_time"]].to_numpy()

task = (IntervalList & {"nwb_file_name": nwb_file,
                        "interval_list_name": "run1"}).fetch1("valid_times")

long_ripples_in_task = Interval(ripples).intersect(task).by_length(min_length=0.050)
```

Reach for these before writing a for-loop over intervals. They're correct at the edge cases (zero-overlap, touching-boundaries) that naive implementations get wrong.

---

## Troubleshooting

### No Results Found

For an LLM-facing answer, prefer `db_graph.py find-instance` / `describe`
for row counts and runtime headings, because the JSON output is easier to
quote and distinguishes runtime DB facts from source facts. The Python
checks below are the notebook-session fallback.

```python
# Check session exists
session_count = len(Session & {'nwb_file_name': nwb_file})
if session_count == 0:
    raise ValueError("Session not found")

# Check interval exists
interval_count = len(IntervalList & key)
if interval_count == 0:
    raise ValueError("Interval not found")

# Preview merge table scoped to this session.
# Don't call merge_view() without a restriction — it prints the entire
# merge table across all sessions, which is noisy on shared databases.
PositionOutput.merge_view({'nwb_file_name': nwb_file})
```

### Multiple Results from merge_get_part

```python
parts = PositionOutput.merge_get_part(key, multi_source=True)
for part in parts:
    # Each `part` may itself contain multiple rows — `fetch1("KEY")`
    # only works when len(part) == 1. Iterate or use fetch(...) when
    # the part might match more than one row.
    for mk in part.fetch("KEY", as_dict=True):
        print(f"Source: {part.table_name}, merge_id: {mk}")
```

### Join Not Working

For source-declared relationships, run `code_graph.py path` or
`code_graph.py describe` first. For relationships in the connected
database, especially custom tables or schema drift, run `db_graph.py path`
or `db_graph.py describe`. The direct DataJoint checks below are the
notebook-session fallback.

```python
# Inspect keys
Table1.describe()
Table2.describe()

# Find common keys
common = set(Table1.heading.names) & set(Table2.heading.names)
print(f"Common keys: {common}")

# Check relationship path
Table1.parents()
Table2.children()
```
