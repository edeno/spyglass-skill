# Behavior Pipeline

Behavioral analysis including pose grouping and motion sequencing (MoSeq).

## Contents

- [Overview](#overview)
- [PoseGroup](#posegroup)
- [MoSeq (Motion Sequencing)](#moseq-motion-sequencing)
- [Dependency: keypoint_moseq](#dependency-keypoint_moseq)

## Overview

```python
from spyglass.behavior.v1.core import PoseGroup
```

## PoseGroup

**PoseGroup** (Manual)

- Key: `pose_group_name`
- Part table: `PoseGroup.Pose` — links to PositionOutput entries
- Groups pose data from multiple bodyparts for behavioral analysis

## MoSeq (Motion Sequencing)

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

## Dependency: keypoint_moseq

Optional dependency (`pip install spyglass-neuro[moseq-cpu]` or `[moseq-gpu]`).

- `keypoint_moseq` (imported as `kpms`) — Motion sequencing from keypoint data
