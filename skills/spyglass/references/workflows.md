# Spyglass Analysis Workflows

## Contents

- [Exploring Available Data](#exploring-available-data)
- [Cross-Table Joins](#cross-table-joins)
- [Common Patterns](#common-patterns)
- [Troubleshooting](#troubleshooting)

For pipeline-specific workflows (position, LFP, spike sorting, decoding), see the corresponding pipeline reference files. For canonical end-to-end examples, run the `notebooks/*.ipynb` tutorials in Jupyter (the `notebooks/py_scripts/*.py` files are a jupytext mirror of the same content, kept for PR-review diffs).

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
from spyglass.common import ElectrodeGroup, BrainRegion
from spyglass.lfp import LFPOutput

groups = (ElectrodeGroup & (BrainRegion & {'region_name': 'CA1'})).fetch('KEY')

for g in groups:
    lfp = LFPOutput.merge_restrict(g)
    if len(lfp):
        print(f"Found LFP for: {g}")
```

### Navigate Upstream/Downstream

```python
# All position results for a session
PositionOutput() << f"nwb_file_name = '{nwb_file}'"

# Find sessions with specific parameters
Session() >> 'trodes_pos_params_name="default"'
```

---

## Common Patterns

### Batch Processing (One Merge, Many Sessions)

```python
from spyglass.common import Session
from spyglass.position import PositionOutput

sessions = (Session & {"subject_id": "J16"}).fetch("KEY")

results = []
for sk in sessions:
    key = {**sk, "interval_list_name": "task"}
    part = PositionOutput.merge_get_part(key)
    if len(part) == 1:          # skip ambiguous/missing sessions
        results.append((PositionOutput & part.fetch1("KEY")).fetch1_dataframe())
```

The `len(part) == 1` guard replaces a try/except around `fetch1("KEY")` — cheaper, more readable, and it's the cardinality check [feedback_loops.md](feedback_loops.md) recommends before any `fetch1()`.

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

Spyglass ships a NumPy-based interval-manipulation suite in `spyglass.common.common_interval` that users routinely reinvent because the tutorials don't mention it. Input/output shape is the standard `(N, 2)` start/stop array.

```python
from spyglass.common.common_interval import (
    interval_list_intersect,   # AND across two interval lists
    interval_list_union,       # OR across two interval lists
    interval_list_complement,  # intervals1 \ intervals2
    consolidate_intervals,     # merge overlapping/adjacent ranges
    intervals_by_length,       # filter by min/max duration
)

# Example: ripple intervals AND task intervals, ≥ 50 ms only.
# `RippleTimesV1` stores the ripple intervals as an NWB object — only
# `ripple_times_object_id` is on the heading (`ripple/v1/ripple.py:189`);
# the per-row dataframe comes via `fetch1_dataframe()` /
# `fetch_dataframe()` (`ripple.py:240, 245`), each row of which has
# `start_time` / `end_time` columns. Convert to (start, end) pairs
# before passing into `interval_list_intersect`.
ripple_df = (RippleTimesV1 & key).fetch1_dataframe()
ripples = ripple_df[["start_time", "end_time"]].to_numpy()
task = (IntervalList & {"nwb_file_name": f, "interval_list_name": "run1"}
        ).fetch1("valid_times")

long_ripples_in_task = intervals_by_length(
    interval_list_intersect(ripples, task), min_length=0.050
)
```

Reach for these before writing a for-loop over intervals. They're correct at the edge cases (zero-overlap, touching-boundaries) that naive implementations get wrong.

---

## Troubleshooting

### No Results Found

```python
# Check session exists
assert len(Session & {'nwb_file_name': nwb_file}) > 0, "Session not found"

# Check interval exists
assert len(IntervalList & key) > 0, "Interval not found"

# Preview merge table scoped to this session.
# Don't call merge_view() without a restriction — it prints the entire
# merge table across all sessions, which is noisy on shared databases.
PositionOutput.merge_view({'nwb_file_name': nwb_file})
```

### Multiple Results from merge_get_part

```python
parts = PositionOutput.merge_get_part(key, multi_source=True)
for part in parts:
    mk = part.fetch1("KEY")
    print(f"Source: {part.table_name}, merge_id: {mk}")
```

### Join Not Working

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
