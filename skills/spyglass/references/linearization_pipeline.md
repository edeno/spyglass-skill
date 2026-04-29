<!-- pipeline-version: v1 -->
# Linearization Pipeline

Converts 2D position to 1D linearized position using track graphs. Essential for decoding on linear/W-track environments.

## Contents

- [Overview](#overview)
- [Canonical Example](#canonical-example)
- [LinearizedPositionOutput Merge Table](#linearizedpositionoutput-merge-table)
- [Key Tables](#key-tables)
- [Fetch Example](#fetch-example)
- [Dependency: track_linearization](#dependency-track_linearization)

## Overview

```python
from spyglass.linearization.merge import LinearizedPositionOutput
```

## Canonical Example

Linearization takes a 2D position (from a `PositionOutput` entry whose source exposes a `position` NWB object with `get_spatial_series()` — typically `TrodesPosV1` or `DLCPosV1`) and projects it onto a track graph. `LinearizedPositionV1.make()` calls `PositionOutput().fetch_nwb({"merge_id": pos_merge_id})[0]` and reads the `"position"` key (`linearization/v1/main.py:136-143`); other PositionOutput sources don't share that shape. `ImportedPose` reads a `"pose"` key via `fetch_pose_dataframe` (`position/v1/imported_pose.py:129`); legacy `IntervalPositionInfo` exposes per-component `head_position_object_id` (`common/common_position.py:105`); neither resolves through this pipeline as-is.

Minimal end-to-end flow:

```python
from spyglass.linearization.merge import LinearizedPositionOutput
from spyglass.linearization.v1 import (
    TrackGraph,
    LinearizationParameters,
    LinearizationSelection,
    LinearizedPositionV1,
)

# 1. Prereqs: a TrackGraph row defining the track geometry, a
#    LinearizationParameters row, and a PositionOutput entry for the
#    session/interval you want linearized. Discover the PositionOutput
#    merge_id the same way as the position pipeline.
#    Note the FK rename: LinearizationSelection is defined as
#    `-> PositionOutput.proj(pos_merge_id='merge_id')`, so the selection
#    key uses `pos_merge_id`, not `merge_id` — projected FK rename pattern,
#    see merge_methods.md.

# 2. Selection — ties PositionOutput + TrackGraph + params. No interval
#    field: the interval is implicit in the PositionOutput entry selected.
selection_key = {
    "pos_merge_id": position_merge_id,
    "track_graph_name": "6-arm-radial",
    "linearization_param_name": "default",
}
LinearizationSelection.insert1(selection_key, skip_duplicates=True)

# 3. Populate
LinearizedPositionV1.populate(selection_key)

# 4. Fetch via the merge table. `merge_restrict(selection_key)`
#    restricts the merge view to entries whose part-table parent
#    matches the selection key — clearer than `merge_get_part` here
#    because the selection key already names the part. Notebook
#    `24_Linearization.py:281` uses this form.
merge_key = LinearizedPositionOutput.merge_restrict(selection_key).fetch1("KEY")
linear_pos = (LinearizedPositionOutput & merge_key).fetch1_dataframe()
# Output columns (from track_linearization.get_linearized_position):
#   linear_position, track_segment_id, projected_x_position, projected_y_position
```

## LinearizedPositionOutput Merge Table

**Primary Key**: `merge_id` (UUID)

**Part Tables**:

- `LinearizedPositionOutput.LinearizedPositionV0` — Legacy linearization
- `LinearizedPositionOutput.LinearizedPositionV1` — Current linearization

## Key Tables

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
- Used directly by linearization (`LinearizationSelection` FKs `TrackGraph`). Decoding **does not** FK this Spyglass `TrackGraph` table — it stores / restores `non_local_detector.Environment` parameters and converts the embedded `track_graph` dict via `track_linearization.make_track_graph()` at runtime. Same track-graph *concept*, different table surface.

**LinearizationParameters** (Lookup)

- Key: `linearization_param_name`
- Parameters for nearest-edge or optional HMM-based linearization. The schema's `use_hmm` field defaults to `0` (`linearization/v1/main.py:30`); `track_linearization.get_linearized_position()` uses nearest-edge projection when `use_HMM=False` and switches to HMM only when explicitly enabled. The "default" row is the nearest-edge path.
- `dj.Lookup` (not `Manual`) at `linearization/v1/main.py:22`. **No `contents`** are declared, so the table is empty by default — `dj.Lookup` only auto-populates when `contents = [...]` is set on the class. Insert a row before using it; the canonical workflow uses `linearization_param_name="default"` and notebook `24_Linearization.py` inserts that row explicitly with `LinearizationParameters().insert1({"linearization_param_name": "default"}, skip_duplicates=True)`. The bare `code_graph.py describe LinearizationParameters` exits with an ambiguity error because v0 also defines a class of the same qualname; pass a file hint to pick the v1 one: `python skills/spyglass/scripts/code_graph.py describe --file spyglass/linearization/v1/main.py LinearizationParameters` (no `contents` in the class body). Then confirm at runtime with `(LinearizationParameters & {"linearization_param_name": "default"}).fetch()`.

**LinearizationSelection** (Lookup)

- Links: `PositionOutput.proj(pos_merge_id='merge_id')`, `TrackGraph`, `LinearizationParameters` (`linearization/v1/main.py:101-105`). It does NOT FK `IntervalList` directly — the temporal scope flows in via the `PositionOutput` merge entry, not as a separate selection-table FK.

**LinearizedPositionV1** (Computed)

- Outputs linearized position projected onto the track graph. The dataframe carries:
  - `linear_position` — 1D position along the track
  - `track_segment_id` — which graph segment the sample is on
  - `projected_x_position`, `projected_y_position` — 2D coordinates of the nearest-edge projection
- Source: `linearization/v1/main.py:184-186` calls `LinearizedPositionOutput._merge_insert(...)` after writing the dataframe; the column set is what `track_linearization.get_linearized_position()` returns.

## Fetch Example

```python
# Get linearized position for an already-populated entry. Build
# `selection_key` the same way the canonical example above did
# (pos_merge_id + track_graph_name + linearization_param_name); use
# `merge_restrict` to scope the merge view to that selection's part.
selection_key = {
    "pos_merge_id": position_merge_id,
    "track_graph_name": "6-arm-radial",
    "linearization_param_name": "default",
}
merge_key = LinearizedPositionOutput.merge_restrict(selection_key).fetch1("KEY")
linear_pos = (LinearizedPositionOutput & merge_key).fetch1_dataframe()
# Columns: linear_position, track_segment_id, projected_x_position,
#          projected_y_position.
```

## Dependency: track_linearization

Uses the `track_linearization` package:

- `track_linearization.make_track_graph()` — Creates networkx graph from coordinates
- `track_linearization.get_linearized_position()` — Main linearization function
- `track_linearization.plot_track_graph()` — Visualization
