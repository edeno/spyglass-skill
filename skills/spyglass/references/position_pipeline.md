# Position Tracking Pipeline

The position pipeline tracks animal location using multiple methods, all consolidated through the `PositionOutput` merge table. This file is the umbrella: it covers the merge layer, per-source method dispatch, and the manual-import path for pre-computed pose. The two populate-driven sources have their own files:

- **Trodes (LED)** — [position_trodes_v1_pipeline.md](position_trodes_v1_pipeline.md)
- **DeepLabCut** — [position_dlc_v1_pipeline.md](position_dlc_v1_pipeline.md)

## Contents

- [Overview](#overview)
- [PositionOutput Merge Table](#positionoutput-merge-table)
- [Per-Source Method Matrix](#per-source-method-matrix)
- [Imported Pose (manual NWB import)](#imported-pose-manual-nwb-import)
- [Common Patterns](#common-patterns)

## Overview

```python
from spyglass.position import PositionOutput
```

Three sources feed `PositionOutput`. Their operational shapes differ:

| Source | Shape | Auto-merges to PositionOutput? |
| --- | --- | --- |
| Trodes (`TrodesPosV1`) | params → selection → populate | Yes — `make()` calls `_merge_insert` (`position/v1/position_trodes_position.py:241`) |
| DLC (`DLCPosV1`) | 7-step pose-estimation chain | Yes — `make()` calls `_merge_insert` (`position/v1/position_dlc_selection.py:85`) |
| Imported (`ImportedPose`) | Manual NWB import; no params, no selection, no populate | **No** — `insert_from_nwbfile` does not call `_merge_insert`; manual `PositionOutput.insert(..., part_name="ImportedPose")` if you want it surfaced through the merge layer |

For the source-specific canonical examples, gotchas, and parameter tables, open the corresponding file above.

## PositionOutput Merge Table

**Primary Key**: `merge_id` (UUID)

### Part Tables (Sources)

| Part Table | Source Class | Description |
| ------------ | ------------- | ------------- |
| `PositionOutput.TrodesPosV1` | `TrodesPosV1` | LED-based tracking via SpikeGadgets/Trodes |
| `PositionOutput.DLCPosV1` | `DLCPosV1` | DeepLabCut pose estimation |
| `PositionOutput.CommonPos` | `IntervalPositionInfo` | Legacy common position |
| `PositionOutput.ImportedPose` | `ImportedPose` | Pre-computed pose from NWB |

## Per-Source Method Matrix

`PositionOutput.fetch1_dataframe()` (defined at `position/position_merge.py:81`) and `PositionOutput.fetch_video_path()` (`position_merge.py:110`) are dispatchers — they delegate to the source class. What you get back depends on which part the merge entry resolves to:

| Method | TrodesPosV1 | DLCPosV1 | ImportedPose |
| --- | --- | --- | --- |
| `fetch1_dataframe()` | DataFrame: position_x, position_y, orientation, velocity_x, velocity_y, speed | same as Trodes | **not implemented** — `ImportedPose` exposes `fetch_pose_dataframe(key)` (`position/v1/imported_pose.py:110`) instead. Calling `PositionOutput.fetch1_dataframe()` against an imported-pose merge entry routes to a method that doesn't exist on the part. |
| `fetch_video_path(key=dict())` | video path (`position/v1/position_trodes_position.py:278`) | video path (`position/v1/position_dlc_selection.py:315`) | **not implemented** — `ImportedPose` has no `fetch_video_path`. |
| `fetch_pose_dataframe(key)` | not present | per-bodypart DLC pose | per-bodypart imported pose (`imported_pose.py:110`) |

In short: for Trodes/DLC, use the merge-level `fetch1_dataframe` / `fetch_video_path`. For imported pose, work through `ImportedPose.fetch_pose_dataframe(key)` directly (or via `PositionOutput.ImportedPose` part rows, if you've inserted them).

## Imported Pose (manual NWB import)

For pre-computed pose data stored in NWB files. **This is a manual-import path, not a populate path** — there is no parameters table, no selection table, and no `make()` handler. The `insert_from_nwbfile` method (defined at `position/v1/imported_pose.py:47`, implementation at `:105`) inserts the IntervalList, the master row, and the per-bodypart part rows from the source NWB.

```python
from spyglass.position.v1.imported_pose import ImportedPose

# 1. Pull pose rows from the source NWB.
ImportedPose().insert_from_nwbfile(nwb_file)

# 2. Fetch back the per-bodypart pose dataframe directly from
#    ImportedPose. PositionOutput.fetch1_dataframe / fetch_video_path
#    do NOT route through here — see the method matrix above.
key = {"nwb_file_name": nwb_file, "interval_list_name": "<imported>"}
pose_df = ImportedPose().fetch_pose_dataframe(key)
```

**ImportedPose** (Manual; `position/v1/imported_pose.py:18`)

- Key: `nwb_file_name`, `interval_list_name`
- Part table: `ImportedPose.BodyPart` (key adds `part_name`)
- Methods:
  - `insert_from_nwbfile(nwb_file_name, ...)` — manual NWB import (inserts IntervalList + master + BodyPart rows)
  - `fetch_pose_dataframe(key=None)` — per-bodypart pose dataframe

**Surfacing through `PositionOutput`.** `insert_from_nwbfile` does NOT auto-insert into the merge layer (contrast with `TrodesPosV1.make` / `DLCPosV1.make` which call `PositionOutput._merge_insert(...)` explicitly: `position/v1/position_trodes_position.py:241`, `position_dlc_selection.py:85`). If a downstream consumer needs the imported pose to appear under `PositionOutput.ImportedPose`, you have to call `PositionOutput.insert([key], part_name="ImportedPose")` yourself. Most analyses can read directly from `ImportedPose`; route through the merge only when the consumer FKs to `PositionOutput`.

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
