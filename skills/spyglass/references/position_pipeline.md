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

Four sources feed `PositionOutput`. Their operational shapes differ:

| Source | Shape | Auto-merges to PositionOutput? |
| --- | --- | --- |
| Trodes (`TrodesPosV1`) | params → selection → populate | Yes — `make()` calls `_merge_insert` (`position/v1/position_trodes_position.py:241`) |
| DLC (`DLCPosV1`) | 7-step pose-estimation chain | Yes — `make()` calls `_merge_insert` (`position/v1/position_dlc_selection.py:85`) |
| Legacy common (`IntervalPositionInfo`, surfaced as `PositionOutput.CommonPos`) | params → selection → populate (older path; `common.common_position`) | Yes via the legacy populate path |
| Imported (`ImportedPose`) | NWB-import path; no params and no selection table | Indirect — `make()` (`position/v1/imported_pose.py:44`) just calls `insert_from_nwbfile` and does not call `_merge_insert`; common-ingest invokes it via `populate_all_common`'s ImportedPose special-case which overrides `key_source` to `Nwbfile()` for `ImportedPose` (`populate_all_common.py:141-145`). To surface a row under `PositionOutput.ImportedPose`, call `PositionOutput.insert([key], part_name="ImportedPose")` yourself. |

For the source-specific canonical examples, gotchas, and parameter tables, open the corresponding file above. Legacy `CommonPos` is not covered in detail here — most active analyses use Trodes or DLC, and `IntervalPositionInfo` predates the v1 split.

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

`PositionOutput.fetch1_dataframe()` (defined at `position/position_merge.py:81`), `PositionOutput.fetch_pose_dataframe()` (`position_merge.py:94`), and `PositionOutput.fetch_video_path()` (`position_merge.py:110`) are all dispatchers — they delegate to the source class. What you get back depends on which part the merge entry resolves to:

| Method | TrodesPosV1 | DLCPosV1 | CommonPos (`IntervalPositionInfo`) | ImportedPose |
| --- | --- | --- | --- | --- |
| `fetch1_dataframe()` | DataFrame: position_x, position_y, orientation, velocity_x, velocity_y, speed | same as Trodes | same shape (`common/common_position.py:491`) | **not implemented** — `ImportedPose` exposes `fetch_pose_dataframe(key)` (`position/v1/imported_pose.py:110`) instead. Calling `PositionOutput.fetch1_dataframe()` against an imported-pose merge entry routes to a method that doesn't exist on the part. |
| `fetch_video_path(key=dict())` | video path (`position/v1/position_trodes_position.py:278`) | video path (`position/v1/position_dlc_selection.py:315`) | video path (`common/common_position.py:546`) | **not implemented** — `ImportedPose` has no `fetch_video_path`. |
| `fetch_pose_dataframe(key)` | not present | per-bodypart DLC pose | not present | per-bodypart imported pose (`imported_pose.py:110`) |

In short: for Trodes/DLC/CommonPos, use the merge-level `fetch1_dataframe` / `fetch_video_path`. For imported pose, the merge-level `PositionOutput.fetch_pose_dataframe()` dispatcher routes to `ImportedPose.fetch_pose_dataframe(key)` for you (or to `DLCPosV1`'s pose helper for DLC merge entries); call `ImportedPose().fetch_pose_dataframe(key)` directly only when you don't need the merge layer.

## Imported Pose (manual NWB import)

For pre-computed pose data stored in NWB files. **No parameters table, no selection table, and no normal user-facing populate** — `ImportedPose.make()` (`position/v1/imported_pose.py:44`) is just a thin wrapper around `insert_from_nwbfile`, and it is invoked by common ingest (`populate_all_common` special-cases `ImportedPose` so its `key_source` is `Nwbfile()` — see the `if table_name in ["ImportedPose", ...]` branch at `populate_all_common.py:141-145`). Calling `ImportedPose().populate()` directly is not a user-facing pattern; use `insert_from_nwbfile` (defined at `position/v1/imported_pose.py:47`, implementation at `:105`) when manually importing outside the common-ingest driver.

```python
from spyglass.position.v1.imported_pose import ImportedPose

# 1. Pull pose rows from the source NWB.
ImportedPose().insert_from_nwbfile(nwb_file)

# 2. Discover the actual interval_list_name(s) the import created.
#    `insert_from_nwbfile` LOOPS over every `PoseEstimation` object
#    in the source NWB and creates one master row per object
#    (`imported_pose.py:54`), each keyed by a synthesized name of
#    the form `pose_<obj.name>_valid_intervals`
#    (`imported_pose.py:76`). One NWB → potentially several rows;
#    don't hand-build a name and don't assume "the first row" is
#    the one you want.
keys = (ImportedPose & {"nwb_file_name": nwb_file}).fetch(
    "KEY", as_dict=True
)
for k in keys:
    print(k["interval_list_name"])      # inspect candidates
# Then pick the one matching the PoseEstimation object you care
# about (the `<obj.name>` segment), e.g.:
my_key = next(
    k for k in keys
    if k["interval_list_name"] == "pose_<your_obj_name>_valid_intervals"
)
pose_df = ImportedPose().fetch_pose_dataframe(my_key)
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

# Only valid for merge entries whose source supports fetch1_dataframe
# (TrodesPosV1, DLCPosV1, CommonPos). For ImportedPose, use
# ImportedPose().fetch_pose_dataframe(key) instead — see the method
# matrix above.
position_df = (PositionOutput & merge_key).fetch1_dataframe()
plt.figure(figsize=(10, 8))
plt.plot(position_df['position_x'], position_df['position_y'],
         'b-', alpha=0.5, linewidth=0.5)
plt.xlabel('X Position (cm)')
plt.ylabel('Y Position (cm)')
plt.axis('equal')
plt.show()
```
