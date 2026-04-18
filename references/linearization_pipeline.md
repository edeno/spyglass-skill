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

Linearization takes a 2D position (from the `PositionOutput` merge table) and projects it onto a track graph. Minimal end-to-end flow:

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
pos_merge_key = {"merge_id": position_merge_id}

# 2. Selection — ties together PositionOutput, TrackGraph, params, interval
selection_key = {
    **pos_merge_key,
    "track_graph_name": "6-arm-radial",
    "linearization_param_name": "default",
    "interval_list_name": interval_name,
}
LinearizationSelection.insert1(selection_key, skip_duplicates=True)

# 3. Populate
LinearizedPositionV1.populate(selection_key)

# 4. Fetch via the merge table
merge_key = LinearizedPositionOutput.merge_get_part(selection_key).fetch1("KEY")
linear_pos = (LinearizedPositionOutput & merge_key).fetch1_dataframe()
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
- Used by: linearization pipeline and decoding pipeline

**LinearizationParameters** (Manual)
- Key: `linearization_param_name`
- Parameters for the HMM-based linearization algorithm

**LinearizationSelection** (Lookup)
- Links: PositionOutput (merge_id), TrackGraph, LinearizationParameters, IntervalList

**LinearizedPositionV1** (Computed)
- Outputs linearized position projected onto track graph

## Fetch Example

```python
# Get linearized position for an already-populated merge entry
merge_key = LinearizedPositionOutput.merge_get_part(key).fetch1("KEY")
linear_pos = (LinearizedPositionOutput & merge_key).fetch1_dataframe()
```

## Dependency: track_linearization

Uses the `track_linearization` package:
- `track_linearization.make_track_graph()` — Creates networkx graph from coordinates
- `track_linearization.get_linearized_position()` — Main linearization function
- `track_linearization.plot_track_graph()` — Visualization
