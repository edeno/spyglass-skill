# Behavior Pipeline

Behavioral analysis: group keypoint pose data, train a motion-sequencing (MoSeq) model, then apply it to convert pose trajectories into behavioral syllables.

## Contents

- [Overview](#overview)
- [Pipeline Flow](#pipeline-flow)
- [Key Tables](#key-tables)
- [Example](#example)
- [Dependency: keypoint_moseq](#dependency-keypoint_moseq)

## Overview

```python
from spyglass.behavior.v1.core import PoseGroup
from spyglass.behavior.v1.moseq import (
    MoseqModel, MoseqModelParams, MoseqModelSelection,
    MoseqSyllable, MoseqSyllableSelection,
)
```

MoSeq is an **optional dependency** — install with `pip install spyglass-neuro[moseq-cpu]` or `[moseq-gpu]`. Without it, imports from `spyglass.behavior.v1.moseq` fail with `ModuleNotFoundError: keypoint_moseq`. `PoseGroup` itself lives in `spyglass.behavior.v1.core` and does not require `keypoint_moseq`.

The pipeline has two phases that are always run in order: **train** a model on a pose group, then **apply** the trained model to pose data (which may be inside or outside the training set).

## Pipeline Flow

```text
PositionOutput (merge, DLC or Trodes pose) ──┐
                                             │
                                             ▼
                    PoseGroup  ◄──── PoseGroup.Pose — one row per video/merge_id
                         │
                         │              MoseqModelParams (kappa, skeleton, num_epochs, ...)
                         ▼                            │
                    MoseqModelSelection ◄─────────────┘
                         │
                         ▼
                    MoseqModel (trained model — Computed)
                         │
                         ▼
                    MoseqSyllableSelection ◄── PositionOutput (pose to label)
                         │
                         ▼
                    MoseqSyllable (per-frame syllables + centroid + heading)
```

## Key Tables

**PoseGroup** (Manual) — `core.py`

- Key: `pose_group_name`
- Part table: `PoseGroup.Pose` — one row per `PositionOutput` merge entry joined in (via `pose_merge_id`).
- Helpers: `create_group(group_name, merge_ids, bodyparts)` inserts master + part rows in one call; `fetch_pose_datasets(key, format_for_moseq=True)` returns the arrays MoSeq wants; `fetch_video_paths(key)` returns the videos for grid-movie generation.

**MoseqModelParams** (Lookup) — `moseq.py`

- Key: `model_params_name` (note: not `moseq_model_params_name`).
- Payload: `model_params` blob. Relevant keys: `skeleton`, `kappa` (syllable-length prior, usually needs dataset-specific tuning), `num_ar_iters`, `num_epochs`, `anterior_bodyparts`, `posterior_bodyparts`, `target_variance` (PC selection). To extend training from an existing model, use `MoseqModelParams().make_training_extension_params(model_key, num_epochs=...)` — it clones the params and sets `initial_model` so `MoseqModel.populate` resumes rather than starts over.

**MoseqModelSelection** (Manual) — pairs one `PoseGroup` with one `MoseqModelParams`.

**MoseqModel** (Computed) — trains the model. Inherits the combined key of Selection. Post-populate helpers on the restricted table: `fetch_model(key)` returns the trained model dict; `analyze_pca()`, `generate_trajectory_plots()`, `generate_grid_movies(output_dir=...)` produce diagnostic plots/videos.

**MoseqSyllableSelection** (Manual) — pairs one trained `MoseqModel` with a single `PositionOutput` merge entry (`pose_merge_id`) to label; sets `num_iters` (default 500). Validates on insert that every bodypart the model was trained on exists in the target pose dataframe — missing bodyparts raise `ValueError`.

**MoseqSyllable** (Computed) — applies the trained model. Output accessible via `fetch1_dataframe()`: per-frame `syllable`, `centroid x/y[/z]`, `heading`, and optional latent-state columns.

## Example

Canonical flow mirrors `60_MoSeq.ipynb`. Two phases, explicit; `skip_duplicates=True` on manual inserts is standard for this pipeline because re-running the tutorial is common.

```python
from spyglass.position.position_merge import PositionOutput
from spyglass.behavior.v1.core import PoseGroup
from spyglass.behavior.v1.moseq import (
    MoseqModel, MoseqModelParams, MoseqModelSelection,
    MoseqSyllable, MoseqSyllableSelection,
)

# --- Phase 1: train ----------------------------------------------------------

# 1. Discover the DLC pose entry you want to train on
pose_key = {
    "nwb_file_name": "SC100020230912_.nwb",
    "epoch": 9,
    "video_file_num": 14,
    "project_name": "sideHomeOfficial",
    "dlc_model_name": "sideHomeOfficial_tutorial_00",
    "dlc_model_params_name": "default",
    "task_mode": "trigger",
}
merge_key = (PositionOutput.DLCPosV1 & pose_key).fetch1("KEY")
merge_ids = [merge_key["merge_id"]]   # extend this list to train across epochs

# 2. Group the pose data with an explicit bodypart list
PoseGroup().create_group(
    group_name="tutorial_group",
    merge_ids=merge_ids,
    bodyparts=["forelimbL", "forelimbR", "nose",
               "spine1", "spine3", "spine5", "tailBase"],
)

# 3. Register training params
MoseqModelParams().insert1({
    "model_params_name": "tutorial_kappa4_mini",
    "model_params": {
        "skeleton": [["nose", "spine1"], ["spine1", "forelimbL"],
                     ["spine1", "forelimbR"], ["spine1", "spine3"],
                     ["spine3", "spine5"], ["spine5", "tailBase"]],
        "kappa": 1e4,
        "num_ar_iters": 50,
        "num_epochs": 50,
        "anterior_bodyparts": ["nose"],
        "posterior_bodyparts": ["tailBase"],
        "target_variance": 0.9,
    },
}, skip_duplicates=True)

# 4. Pair group + params, then train
model_key = {"pose_group_name": "tutorial_group",
             "model_params_name": "tutorial_kappa4_mini"}
MoseqModelSelection().insert1(model_key, skip_duplicates=True)
MoseqModel().populate(model_key)

# --- Phase 2: apply ----------------------------------------------------------

# 5. Pair trained model with a pose merge_id to label (can differ from training)
label_key = {**model_key, "pose_merge_id": merge_ids[0], "num_iters": 3}
MoseqSyllableSelection().insert1(label_key, skip_duplicates=True)
MoseqSyllable().populate(label_key)

# 6. Pull the per-frame syllables
syllable_df = (MoseqSyllable & label_key).fetch1_dataframe()
# columns: syllable, centroid x, centroid y[, centroid z], heading[, latent_state_*]
```

## Dependency: keypoint_moseq

Optional dependency (`pip install spyglass-neuro[moseq-cpu]` or `[moseq-gpu]`).

- `keypoint_moseq` (imported as `kpms`) — motion sequencing from keypoint data. Used internally by `MoseqModel.make()` (project setup, format conversion, PCA, AR-HMM fitting) and `MoseqSyllable.make()` (applying a fit model to new data). You do not normally call `kpms` directly from skill code; `PoseGroup.fetch_pose_datasets(format_for_moseq=True)` produces the arrays the pipeline needs.
