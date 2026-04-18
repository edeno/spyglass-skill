# Spyglass Analysis Workflows


## Contents

- [Workflow 1: Exploring Available Data](#workflow-1-exploring-available-data)
- [Workflow 2: Position Data (The Merge Table Pattern)](#workflow-2-position-data-the-merge-table-pattern)
- [Workflow 3: LFP Analysis](#workflow-3-lfp-analysis)
- [Workflow 4: Spike Sorting Analysis](#workflow-4-spike-sorting-analysis)
- [Workflow 5: Decoding Analysis](#workflow-5-decoding-analysis)
- [Workflow 6: Cross-Table Joins](#workflow-6-cross-table-joins)
- [Common Patterns](#common-patterns)
- [Troubleshooting](#troubleshooting)

Step-by-step workflows for common analysis tasks. Each workflow follows the standard merge table pattern.

## Workflow 1: Exploring Available Data

### Step 1: List Sessions

```python
from spyglass.common import Session, IntervalList

# View all sessions
Session.fetch(limit=20)

# Sessions for specific subject
Session & {'subject_id': 'J16'}

# Find experimenters
Session.Experimenter & {'nwb_file_name': nwb_file}
```

### Step 2: Find Available Intervals

```python
# All intervals for session
IntervalList & {'nwb_file_name': nwb_file}

# Search for specific intervals
IntervalList & {'nwb_file_name': nwb_file} & 'interval_list_name LIKE "%r1%"'

# Get interval times
times = (IntervalList & {
    'nwb_file_name': nwb_file,
    'interval_list_name': '02_r1'
}).fetch1('valid_times')
```

### Step 3: Preview Analysis Results

```python
from spyglass.position import PositionOutput
from spyglass.lfp import LFPOutput
from spyglass.spikesorting.spikesorting_merge import SpikeSortingOutput

# What position data exists?
PositionOutput.merge_restrict({'nwb_file_name': nwb_file})

# What LFP data exists?
LFPOutput.merge_restrict({'nwb_file_name': nwb_file})

# What spike sorting exists?
SpikeSortingOutput.merge_restrict({'nwb_file_name': nwb_file})
```

---

## Workflow 2: Position Data (The Merge Table Pattern)

This is the most common pattern — used identically for all merge tables.

### Step 1: Build Restriction Key

```python
key = {
    'nwb_file_name': 'j1620210710_.nwb',
    'interval_list_name': 'pos 1 valid times',
    'trodes_pos_params_name': 'default',
}
```

### Step 2: Find Part Table and Get merge_id

```python
from spyglass.position import PositionOutput

part = PositionOutput.merge_get_part(key)
merge_key = part.fetch1("KEY")
# merge_key = {'merge_id': 'abc123-...'}
```

### Step 3: Fetch Data

```python
position_df = (PositionOutput & merge_key).fetch1_dataframe()
print(position_df.columns)  # position_x, position_y, orientation, velocity, speed
print(position_df.head())
```

### Step 4: Plot

```python
import matplotlib.pyplot as plt

plt.figure(figsize=(10, 8))
plt.plot(position_df['position_x'], position_df['position_y'],
         'b-', alpha=0.5, linewidth=0.5)
plt.xlabel('X Position (cm)')
plt.ylabel('Y Position (cm)')
plt.title(f"Position trajectory: {key['nwb_file_name']}")
plt.axis('equal')
plt.show()
```

---

## Workflow 3: LFP Analysis

### Step 1: Find Electrode Groups

```python
from spyglass.common import ElectrodeGroup
from spyglass.lfp import LFPElectrodeGroup

# Available electrode groups
ElectrodeGroup & {'nwb_file_name': nwb_file}

# LFP-specific groups
LFPElectrodeGroup & {'nwb_file_name': nwb_file}
```

### Step 2: Check Available Filters

```python
from spyglass.common import FirFilterParameters

FirFilterParameters.fetch('filter_name')
# Common: 'LFP 0-400 Hz', 'Theta 5-11 Hz', 'Ripple 150-250 Hz'
```

### Step 3: Fetch LFP Data

```python
from spyglass.lfp import LFPOutput

key = {
    'nwb_file_name': nwb_file,
    'lfp_electrode_group_name': 'lfp_tets_j16',
    'target_interval_list_name': '02_r1',
    'filter_name': 'LFP 0-400 Hz',
    'filter_sampling_rate': 30000,
}
merge_key = LFPOutput.merge_get_part(key).fetch1("KEY")
lfp_df = (LFPOutput & merge_key).fetch1_dataframe()

print(f"Shape: {lfp_df.shape}")
print(f"Sampling rate: {1/(lfp_df.index[1] - lfp_df.index[0]):.1f} Hz")
```

### Step 4: Plot LFP Traces

```python
import matplotlib.pyplot as plt

duration = 2.0  # seconds
channels = lfp_df.columns[:4]

fig, axes = plt.subplots(len(channels), 1, figsize=(12, 8), sharex=True)
for ax, channel in zip(axes, channels):
    mask = lfp_df.index < lfp_df.index[0] + duration
    ax.plot(lfp_df.index[mask], lfp_df[channel][mask])
    ax.set_ylabel(f'{channel}\n(uV)')
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
axes[-1].set_xlabel('Time (s)')
plt.tight_layout()
plt.show()
```

---

## Workflow 4: Spike Sorting Analysis

### Step 1: Find Spike Sorting Results

```python
from spyglass.spikesorting.spikesorting_merge import SpikeSortingOutput

SpikeSortingOutput.merge_restrict({'nwb_file_name': nwb_file})
```

### Step 2: Get Spike Times (Two Methods)

**Method A: Friendly keys → merge_ids**
```python
merge_ids = SpikeSortingOutput().get_restricted_merge_ids({
    'nwb_file_name': nwb_file,
    'interval_list_name': '02_r1',
    'sorter': 'mountainsort4',
})

for mid in merge_ids:
    spikes = SpikeSortingOutput().get_spike_times({"merge_id": mid})
    print(f"merge_id={mid}: {len(spikes)} units")
```

**Method B: Direct merge_id**
```python
spikes = SpikeSortingOutput().get_spike_times({"merge_id": known_id})
```

### Step 3: Use SortedSpikesGroup for Population Analysis

```python
from spyglass.spikesorting.analysis.v1.group import SortedSpikesGroup

spike_times, unit_ids = SortedSpikesGroup().fetch_spike_data(
    {
        'nwb_file_name': nwb_file,
        'unit_filter_params_name': 'all_units',
        'sorted_spikes_group_name': 'HPC_02_r1',
    },
    return_unit_ids=True,
)
```

### Step 4: Compute Firing Rates

```python
import numpy as np
from spyglass.common import IntervalList

interval_times = (IntervalList & {
    'nwb_file_name': nwb_file,
    'interval_list_name': '02_r1'
}).fetch1('valid_times')

for uid, spk in zip(unit_ids, spike_times):
    n = np.sum((spk >= interval_times[0, 0]) & (spk <= interval_times[-1, 1]))
    dur = np.sum(interval_times[:, 1] - interval_times[:, 0])
    print(f"Unit {uid}: {n / dur:.2f} Hz")
```

---

## Workflow 5: Decoding Analysis

### Step 1: Find Results

```python
from spyglass.decoding import DecodingOutput

DecodingOutput.merge_restrict({'nwb_file_name': nwb_file})
```

### Step 2: Fetch Results

```python
merge_key = DecodingOutput.merge_get_part(key).fetch1("KEY")
results = DecodingOutput.fetch_results(merge_key)
```

### Step 3: Analyze

```python
import numpy as np

# Get posterior and position
posterior = results.acausal_posterior.values
time = results.time.values

# Filter to specific interval
interval_data = results.where(results.interval_labels == 0, drop=True)

# Decoded position (MAP)
decoded = np.argmax(posterior, axis=1)

# Compare to actual
position_df, var_names = DecodingOutput.fetch_position_info(merge_key)
```

---

## Workflow 6: Cross-Table Joins

### Find Position Data by Experimenter

```python
from spyglass.common import Session
from spyglass.position import PositionOutput

sessions = (Session.Experimenter & {'lab_member_name': 'Name'}).fetch('nwb_file_name')

for s in sessions:
    results = PositionOutput.merge_restrict({'nwb_file_name': s})
    if len(results):
        print(f"{s}: {len(results)} position entries")
```

### Find LFP Data by Brain Region

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

### Safe Fetching with Error Handling

```python
def safe_fetch_merge_key(merge_table, key):
    """Safely get merge_key from a merge table. Returns None on failure."""
    try:
        part = merge_table.merge_get_part(key)
        return part.fetch1("KEY")
    except (ValueError, Exception) as e:
        print(f"No unique match for {key}: {e}")
        return None

# Usage (step 4 depends on the pipeline):
merge_key = safe_fetch_merge_key(PositionOutput, key)
if merge_key:
    data = (PositionOutput & merge_key).fetch1_dataframe()  # position/LFP
    # For decoding: DecodingOutput.fetch_results(merge_key)
    # For spikes: SpikeSortingOutput().get_spike_times(merge_key)
```

### Batch Processing Multiple Sessions

```python
sessions = (Session & {'subject_id': 'J16'}).fetch('KEY')

results = []
for sk in sessions:
    key = {**sk, 'interval_list_name': 'task'}
    data = safe_fetch(PositionOutput, key)
    if data is not None:
        results.append(data)
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
