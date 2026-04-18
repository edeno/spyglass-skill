# FigURL Interactive Visualization


## Contents

- [Overview](#overview)
- [Spike Sorting Curation via FigURL](#spike-sorting-curation-via-figurl)
- [Decoding Visualization](#decoding-visualization)
- [Prerequisites](#prerequisites)
- [Common Gotchas](#common-gotchas)

## Overview

FigURL provides web-based interactive visualizations for Spyglass data — spike sorting curation UIs and decoding playback views. Data is uploaded to kachery-cloud, which returns a shareable URL that opens in a browser.

Two main use cases:

- **Spike sorting curation**: upload a sorting, label/merge units in the browser, pull the results back into Spyglass
- **Decoding visualization**: generate a 1D or 2D interactive view of posterior probabilities over time

Sources: `src/spyglass/spikesorting/v1/figurl_curation.py`, `src/spyglass/decoding/decoding_merge.py` (`create_decoding_view`). Dependencies: `sortingview`, `kachery-cloud`, `figurl`.

Upstream project (FigURL itself, for questions beyond Spyglass integration): <https://github.com/flatironinstitute/figurl>

## Spike Sorting Curation via FigURL

```python
from spyglass.spikesorting.v1 import FigURLCurationSelection, FigURLCuration
```

### Workflow

The curation loop uploads a sorting to kachery, gives you a URL to curate in the browser, then pulls the resulting labels/merge groups back.

```python
# 1. Insert selection — references an existing CurationV1 entry
# insert_selection will auto-generate curation_uri if not provided
sel_key = FigURLCurationSelection.insert_selection({
    "sorting_id": sorting_id,
    "curation_id": curation_id,          # must exist in CurationV1
    "metrics_figurl": [],                 # optional metrics to display
})

# 2. Populate — uploads data, creates the interactive URL
FigURLCuration.populate(sel_key)

# 3. Fetch the URL and open it in a browser
url = (FigURLCuration & sel_key).fetch1("url")
print(url)

# ---- User curates in browser, saving labels/merges to the curation_uri ----

# 4. Pull curator's decisions back from kachery
curation_json = (FigURLCurationSelection & sel_key).fetch1("curation_uri")
labels = FigURLCuration.get_labels(curation_json)         # {unit_id: [labels]}
merge_groups = FigURLCuration.get_merge_groups(curation_json)  # merge structure

# 5. Create a new CurationV1 entry with the pulled results
CurationV1.insert_curation(
    sorting_id=sorting_id,
    parent_curation_id=curation_id,
    labels=labels,
    merge_groups=merge_groups,
    description="Manual curation via FigURL",
)
```

### Prerequisite: curation_label column

`generate_curation_uri()` requires the upstream `CurationV1` NWB to have a `curation_label` column. Add labels when inserting the parent curation — even empty ones are fine:

```python
CurationV1.insert_curation(sorting_id=sorting_id, labels={}, ...)
```

### Key Methods

- `FigURLCurationSelection.insert_selection(key)` — Class method, auto-generates `figurl_curation_id` UUID and `curation_uri` if missing
- `FigURLCurationSelection.generate_curation_uri(key)` — Static helper, uploads CurationV1 state to kachery and returns a URI string
- `FigURLCuration.get_labels(curation_json)` — Class method, returns `{unit_id: [label_list]}` from a kachery URI
- `FigURLCuration.get_merge_groups(curation_json)` — Class method, returns merge group structure from a kachery URI

## Decoding Visualization

`DecodingOutput` has a direct method that generates a FigURL view for decoded position:

```python
from spyglass.decoding import DecodingOutput

# Create 1D or 2D interactive decode view (dimension inferred from decoder)
view = DecodingOutput.create_decoding_view(
    key,
    head_direction_name="head_orientation",  # position DataFrame column
    interval_idx=None,                        # or an int to filter one interval
)
# view is a figurl view object; call .url() or print it for the browser URL
```

Under the hood, this routes to `non_local_detector.visualization.figurl_1D.create_1D_decode_view` or `figurl_2D.create_2D_decode_view` based on the decoder's environment dimensionality.

## Prerequisites

- `sortingview` and `kachery-cloud` installed (core Spyglass dependencies)
- A valid kachery zone configured — see [setup_and_config.md](setup_and_config.md) and the `KacheryZone` / `AnalysisNwbfileKachery` tables in [other_pipelines.md](other_pipelines.md)
- Internet access — FigURL uploads to kachery-cloud and returns a hosted URL
- For curation workflows: the `curation_label` column must exist on the parent `CurationV1` NWB

## Common Gotchas

- **URL retention**: kachery-cloud zones have retention policies. If the URL stops working, the underlying data has expired — repopulate to regenerate
- **Upload size**: large sortings or recordings can take minutes to upload. Consider windowing with `segment_duration_sec` (see `_generate_figurl` kwargs in `figurl_curation.py`)
- **Re-fetching labels**: `get_labels()` / `get_merge_groups()` hit kachery every call. If the curator updates the URL, re-run these to pull the latest state — no local cache
- **`insert_curation()` bug #1530**: Sortings without a `curation_label` column raise `ValueError`. Always insert parent curations with at least an empty labels dict
- **V0 vs V1**: The v0 pipeline has its own `curation_figurl.py` with a similar but not identical API. The v1 path above is the current recommendation
