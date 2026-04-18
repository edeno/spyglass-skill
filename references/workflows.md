# Spyglass Analysis Workflows

## Contents

- [Exploring Available Data](#exploring-available-data)
- [Cross-Table Joins](#cross-table-joins)
- [Common Patterns](#common-patterns)
- [Troubleshooting](#troubleshooting)

For pipeline-specific workflows (position, LFP, spike sorting, decoding), see the corresponding pipeline reference files. For canonical end-to-end examples, inspect `notebooks/py_scripts/` in the repo.

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

### Safe Merge Key Fetching

```python
def safe_fetch_merge_key(merge_table, key):
    """Safely get merge_key from a merge table. Returns None on failure."""
    try:
        part = merge_table.merge_get_part(key)
        return part.fetch1("KEY")
    except ValueError as e:
        print(f"No unique match for {key}: {e}")
        return None

# Usage (step 4 depends on the pipeline):
merge_key = safe_fetch_merge_key(PositionOutput, key)
if merge_key:
    data = (PositionOutput & merge_key).fetch1_dataframe()  # position/LFP
    # For decoding: DecodingOutput.fetch_results(merge_key)
    # For spikes: SpikeSortingOutput().get_spike_times(merge_key)
```

### Batch Processing

```python
sessions = (Session & {'subject_id': 'J16'}).fetch('KEY')

results = []
for sk in sessions:
    merge_key = safe_fetch_merge_key(PositionOutput, {**sk, 'interval_list_name': 'task'})
    if merge_key:
        results.append((PositionOutput & merge_key).fetch1_dataframe())
```

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

---

## Troubleshooting

### No Results Found

```python
# Check session exists
assert len(Session & {'nwb_file_name': nwb_file}) > 0, "Session not found"

# Check interval exists
assert len(IntervalList & key) > 0, "Interval not found"

# Preview merge table
PositionOutput.merge_view()
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
