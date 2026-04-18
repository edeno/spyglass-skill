# Other Pipelines: Linearization, Ripple, MUA, Behavior


## Contents

- [Linearization Pipeline](#linearization-pipeline)
- [Ripple Detection Pipeline](#ripple-detection-pipeline)
- [Multi-Unit Activity (MUA) Pipeline](#multi-unit-activity-mua-pipeline)
- [Behavior Pipeline](#behavior-pipeline)
- [Data Import](#data-import)
- [Data Sharing (Kachery)](#data-sharing-kachery)

## Linearization Pipeline

Converts 2D position to 1D linearized position using track graphs. Essential for decoding on linear/W-track environments.

```python
from spyglass.linearization.merge import LinearizedPositionOutput
```

### LinearizedPositionOutput Merge Table

**Primary Key**: `merge_id` (UUID)

**Part Tables**:
- `LinearizedPositionOutput.LinearizedPositionV0` — Legacy linearization
- `LinearizedPositionOutput.LinearizedPositionV1` — Current linearization

### Key Tables

```python
from spyglass.linearization.v1 import (
    LinearizationParameters,
    TrackGraph,
    LinearizationSelection,
    LinearizedPositionV1,
)
```

**TrackGraph** (Manual)
- Key: `track_graph_name`
- Defines track geometry as a networkx graph
- Used by: linearization pipeline and decoding pipeline

**LinearizationParameters** (Manual)
- Key: `linearization_param_name`
- Parameters for the HMM-based linearization algorithm

**LinearizationSelection** (Manual)
- Links: PositionOutput (merge_id), TrackGraph, LinearizationParameters, IntervalList

**LinearizedPositionV1** (Computed)
- Outputs linearized position projected onto track graph

### Example

```python
# Get linearized position
merge_key = LinearizedPositionOutput.merge_get_part(key).fetch1("KEY")
linear_pos = (LinearizedPositionOutput & merge_key).fetch1_dataframe()
```

### Dependency: track_linearization

Uses the `track_linearization` package:
- `track_linearization.make_track_graph()` — Creates networkx graph from coordinates
- `track_linearization.get_linearized_position()` — Main linearization function
- `track_linearization.plot_track_graph()` — Visualization

---

## Ripple Detection Pipeline

Detects sharp-wave ripple events from LFP data. No merge table — outputs directly from `RippleTimesV1`.

```python
from spyglass.ripple.v1 import RippleTimesV1, RippleParameters, RippleLFPSelection
```

### Pipeline Flow

```
LFPOutput (merge) → RippleLFPSelection → RippleTimesV1
    ↑                     ↑                    ↑
    ↑              RippleLFPSelection     RippleParameters
    ↑              .RippleLFPElectrode
PositionOutput (for speed filtering)
IntervalList (valid times)
```

### Key Tables

**RippleLFPSelection** (Manual)
- Key: includes nwb_file_name and LFP merge references
- Part table: `RippleLFPSelection.RippleLFPElectrode` — selects which electrodes to use

**RippleParameters** (Lookup)
- Key: `ripple_param_name`
- Configures detection algorithm and thresholds

**RippleTimesV1** (Computed)
- Detects ripples using Kay or Karlsson algorithms from `ripple_detection` package
- Uses position/speed to filter out movement artifacts
- Output: ripple start/end times

### Example

```python
# Find ripple results
RippleTimesV1 & {'nwb_file_name': nwb_file}

# Fetch ripple times
ripple_df = (RippleTimesV1 & key).fetch1_dataframe()
```

### Dependency: ripple_detection

- `ripple_detection.Kay_ripple_detector()` — Kay's algorithm
- `ripple_detection.Karlsson_ripple_detector()` — Karlsson's algorithm

---

## Multi-Unit Activity (MUA) Pipeline

Detects multi-unit high synchrony events (population bursts) from spike data. No merge table.

```python
from spyglass.mua.v1 import MuaEventsV1, MuaEventsParameters
```

### Pipeline Flow

```
SortedSpikesGroup (spikesorting) → MuaEventsV1
PositionOutput (for speed)              ↑
IntervalList (valid times)        MuaEventsParameters
```

### Key Tables

**MuaEventsParameters** (Manual)
- Key: `mua_param_name`
- Parameters for the `multiunit_HSE_detector` algorithm

**MuaEventsV1** (Computed)
- Uses `ripple_detection.multiunit_HSE_detector()` to detect high synchrony events
- Depends on SortedSpikesGroup for spike data and PositionOutput for speed filtering

### Example

```python
# Find MUA results
MuaEventsV1 & {'nwb_file_name': nwb_file}

# Fetch MUA event times
mua_df = (MuaEventsV1 & key).fetch1_dataframe()
```

---

## Behavior Pipeline

Behavioral analysis including pose grouping and motion sequencing (MoSeq).

```python
from spyglass.behavior.v1.core import PoseGroup
```

### PoseGroup

**PoseGroup** (Manual)
- Key: `pose_group_name`
- Part table: `PoseGroup.Pose` — links to PositionOutput entries
- Groups pose data from multiple bodyparts for behavioral analysis

### MoSeq (Motion Sequencing)

Optional pipeline for discovering behavioral syllables from keypoint data using the `keypoint_moseq` package.

```python
from spyglass.behavior.v1.moseq import MoseqModel, MoseqModelParams, MoseqModelSelection
```

**MoseqModelParams** (Lookup)
- Key: `moseq_model_params_name`
- Parameters for keypoint-moseq model training

**MoseqModelSelection** (Manual)
- Links PoseGroup to MoseqModelParams

**MoseqModel** (Computed)
- Trains a keypoint-moseq model on pose data
- Discovers behavioral syllables from keypoint trajectories

### Dependency: keypoint_moseq

Optional dependency (`pip install spyglass-neuro[moseq-cpu]` or `[moseq-gpu]`).
- `keypoint_moseq` (imported as `kpms`) — Motion sequencing from keypoint data

---

## Data Import

```python
from spyglass.data_import import insert_sessions
```

**Key functions** (not tables):
- `insert_sessions(nwb_file_names)` — Populates database with new NWB sessions

---

## Data Sharing (Kachery)

```python
from spyglass.sharing import AnalysisNwbfileKachery, KacheryZone
```

**KacheryZone** (Manual)
- Key: `kachery_zone_name`

**AnalysisNwbfileKachery** (Computed)
- Part table: `AnalysisNwbfileKachery.LinkedFile`
- Links analysis files to kachery-cloud for sharing
