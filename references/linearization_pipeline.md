# Linearization Pipeline

Converts 2D position to 1D linearized position using track graphs. Essential for decoding on linear/W-track environments.

## Contents

- [Overview](#overview)
- [LinearizedPositionOutput Merge Table](#linearizedpositionoutput-merge-table)
- [Key Tables](#key-tables)
- [Example](#example)
- [Dependency: track_linearization](#dependency-track_linearization)

## Overview

```python
from spyglass.linearization.merge import LinearizedPositionOutput
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

## Example

```python
# Get linearized position
merge_key = LinearizedPositionOutput.merge_get_part(key).fetch1("KEY")
linear_pos = (LinearizedPositionOutput & merge_key).fetch1_dataframe()
```

## Dependency: track_linearization

Uses the `track_linearization` package:
- `track_linearization.make_track_graph()` — Creates networkx graph from coordinates
- `track_linearization.get_linearized_position()` — Main linearization function
- `track_linearization.plot_track_graph()` — Visualization
