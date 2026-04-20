# Position Tracking Pipeline

## Contents

- [Overview](#overview)
- [Canonical Example (Trodes)](#canonical-example-trodes)
- [PositionOutput Merge Table](#positionoutput-merge-table)
- [Pipeline 1: Trodes LED Tracking](#pipeline-1-trodes-led-tracking)
- [Pipeline 2: DeepLabCut (DLC)](#pipeline-2-deeplabcut-dlc)
- [Pipeline 3: Imported Pose](#pipeline-3-imported-pose)
- [Common Patterns](#common-patterns)

## Overview

The position pipeline tracks animal location using multiple methods, all consolidated through the `PositionOutput` merge table.

```python
from spyglass.position import PositionOutput
```

## Canonical Example (Trodes)

Minimal end-to-end flow for LED-based tracking. DLC and imported-pose sources follow the same 3-step shape (params → selection → populate → fetch via merge). Everything below this expands on the pieces.

```python
from spyglass.position import PositionOutput
from spyglass.position.v1 import TrodesPosParams, TrodesPosSelection, TrodesPosV1

# 1. Params — insert once; reuse for many sessions
TrodesPosParams().insert_default()

# 2. Selection — pick the input (session + interval + params)
key = {"nwb_file_name": nwb_file,
       "interval_list_name": "pos 1 valid times",
       "trodes_pos_params_name": "default"}
TrodesPosSelection.insert1(key, skip_duplicates=True)

# 3. Populate — runs computation, writes to PositionOutput merge
TrodesPosV1.populate(key)

# Fetch via the merge table
merge_key = PositionOutput.merge_get_part(key).fetch1("KEY")
position_df = (PositionOutput & merge_key).fetch1_dataframe()
# Columns: position_x, position_y, orientation, velocity_x, velocity_y, speed
```

## PositionOutput Merge Table

**Primary Key**: `merge_id` (UUID)

### Part Tables (Sources)

| Part Table | Source Class | Description |
| ------------ | ------------- | ------------- |
| `PositionOutput.TrodesPosV1` | `TrodesPosV1` | LED-based tracking via SpikeGadgets/Trodes |
| `PositionOutput.DLCPosV1` | `DLCPosV1` | DeepLabCut pose estimation |
| `PositionOutput.CommonPos` | `IntervalPositionInfo` | Legacy common position |
| `PositionOutput.ImportedPose` | `ImportedPose` | Pre-computed pose from NWB |

### Key Methods on PositionOutput

- `fetch1_dataframe()` — Returns DataFrame with position_x, position_y, orientation, velocity columns. Index is timestamps.
- `fetch_pose_dataframe()` — Returns multi-bodypart pose data (DLC/imported sources only). No bodypart filter argument — returns all bodyparts.
- `fetch_video_path(key=dict())` — Returns video file path associated with this position entry.

## Pipeline 1: Trodes LED Tracking

Simple pipeline: raw LED positions → smoothed/interpolated position.

```text
RawPosition (common) → TrodesPosSelection → TrodesPosV1 → PositionOutput.TrodesPosV1
                                ↑
                        TrodesPosParams
```

### Tables

```python
from spyglass.position.v1 import TrodesPosParams, TrodesPosSelection, TrodesPosV1
```

**TrodesPosParams** (Manual, parameter table)

- Key: `trodes_pos_params_name`
- Methods: `insert_default()`, `get_default()`
- Use `TrodesPosParams.describe()` or `TrodesPosParams.heading` for exact parameter names

**TrodesPosSelection** (Manual)

- Key: `nwb_file_name`, `interval_list_name`, `trodes_pos_params_name`

**TrodesPosV1** (Computed)

- Key: inherits from TrodesPosSelection
- Methods: `fetch1_dataframe(add_frame_ind=True)`, `fetch_video_path()`

### Running the Pipeline (Selection + Populate)

Every Spyglass pipeline follows the same 3-step pattern: insert a params row, insert a selection row, then populate. Fetching via `PositionOutput` comes after.

```python
# 1. Params (skip if default already inserted)
TrodesPosParams.insert1({"trodes_pos_params_name": "my_params", "params": {...}},
                         skip_duplicates=True)

# 2. Selection — picks the input to run on
key = {"nwb_file_name": nwb_file, "interval_list_name": interval_name,
       "trodes_pos_params_name": "my_params"}
TrodesPosSelection.insert1(key, skip_duplicates=True)

# 3. Populate — runs computation, writes to PositionOutput merge
TrodesPosV1.populate(key)
```

Warning: `skip_duplicates=True` silently ignores conflicting rows. Use it for idempotent pipeline reruns. Do not use it when inserting raw data — it masks real errors.

### Example: Fetch Trodes Position

```python
key = {
    'nwb_file_name': nwb_file,
    'interval_list_name': 'pos 1 valid times',
    'trodes_pos_params_name': 'default',
}
merge_key = PositionOutput.merge_get_part(key).fetch1("KEY")
position_df = (PositionOutput & merge_key).fetch1_dataframe()
# Columns: position_x, position_y, orientation, velocity_x, velocity_y, speed
```

## Pipeline 2: DeepLabCut (DLC)

Complex multi-stage pipeline for video-based pose estimation.

```text
DLCProject → DLCModelSource → DLCModelSelection → DLCModel
                                                       ↓
DLCPoseEstimationSelection → DLCPoseEstimation → DLCPoseEstimation.BodyPart
                                                       ↓
DLCSmoothInterpParams → DLCSmoothInterpSelection → DLCSmoothInterp (per bodypart)
                                                       ↓
DLCSmoothInterpCohortSelection → DLCSmoothInterpCohort (combines bodyparts)
        ↓                                    ↓
DLCCentroidParams → DLCCentroidSelection → DLCCentroid
DLCOrientationParams → DLCOrientationSelection → DLCOrientation
        ↓                                    ↓
                    DLCPosSelection → DLCPosV1 → PositionOutput.DLCPosV1
```

### Key DLC Tables

```python
from spyglass.position.v1 import (
    BodyPart, DLCProject,
    DLCModel, DLCModelParams, DLCModelSource,
    DLCPoseEstimation, DLCPoseEstimationSelection,
    DLCSmoothInterp, DLCSmoothInterpParams,
    DLCSmoothInterpCohort, DLCSmoothInterpCohortSelection,
    DLCCentroid, DLCCentroidParams,
    DLCOrientation, DLCOrientationParams,
    DLCPosSelection, DLCPosV1,
)
```

**Gotcha — pose estimation hangs silently if the target video file already exists.** `DLCPoseEstimationSelection.insert_estimation_task(...)` never completes (no error, no progress) when an `.mp4` with the same name already sits in the DLC target video directory. The path is whatever the install sets for `dlc_video_dir` (see `spyglass.settings`; Frank Lab hosts use `/nimbus/deeplabcut/video/`, but this is a lab-specific default, not a Spyglass default). Manually delete the stale `.mp4` before re-running. If the call appears to hang, this is the first thing to check.

### DLC Parameter Tables

| Table | Key |
| ------- | ----- |
| `DLCModelParams` | `dlc_model_params_name` |
| `DLCSmoothInterpParams` | `dlc_si_params_name` |
| `DLCCentroidParams` | `dlc_centroid_params_name` |
| `DLCOrientationParams` | `dlc_orientation_params_name` |

Use `TableName.describe()` to see exact parameter fields for each.

### DLC Data Access

```python
# Get pose data for all bodyparts
pose_df = (PositionOutput & merge_key).fetch_pose_dataframe()

# Get raw pose estimation for a bodypart (before smoothing)
(DLCPoseEstimation.BodyPart & key).fetch1_dataframe()
# Columns: video_frame_ind, x, y, likelihood

# Get smoothed pose for a bodypart
(DLCSmoothInterp & key).fetch1_dataframe()
# Columns: video_frame_ind, x, y
```

## Pipeline 3: Imported Pose

For pre-computed pose data stored in NWB files.

```python
from spyglass.position.v1.imported_pose import ImportedPose
```

**ImportedPose** (Manual)

- Key: `nwb_file_name`, `interval_list_name`
- Part table: `ImportedPose.BodyPart` (key adds `part_name`)
- Methods:
  - `insert_from_nwbfile(nwb_file_name)` — Import from NWB
  - `fetch_pose_dataframe(key=None)` — Get pose DataFrame

## Common Patterns

### Find all position data for a session

```python
# See all available sources
PositionOutput.merge_get_part(
    {'nwb_file_name': nwb_file},
    multi_source=True
)

# Or use merge_restrict for a quick view
PositionOutput.merge_restrict({'nwb_file_name': nwb_file})
```

### Plot position trajectory

```python
import matplotlib.pyplot as plt

position_df = (PositionOutput & merge_key).fetch1_dataframe()
plt.figure(figsize=(10, 8))
plt.plot(position_df['position_x'], position_df['position_y'],
         'b-', alpha=0.5, linewidth=0.5)
plt.xlabel('X Position (cm)')
plt.ylabel('Y Position (cm)')
plt.axis('equal')
plt.show()
```

### Check available parameters

```python
# Trodes defaults
TrodesPosParams & {'trodes_pos_params_name': 'default'}

# DLC smoothing defaults
DLCSmoothInterpParams.fetch('dlc_si_params_name')
```
