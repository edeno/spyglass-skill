<!-- pipeline-version: v1 -->
# FigURL Interactive Visualization

FigURL interactive viewers for spike-sorting curation, decoding visualization, and MUA event visualization; distinct from reproducible paper export ([export.md](export.md)).

## Contents

- [Overview](#overview)
- [Spike Sorting Curation via FigURL](#spike-sorting-curation-via-figurl)
- [Decoding Visualization](#decoding-visualization)
- [Prerequisites](#prerequisites)
- [Common Gotchas](#common-gotchas)

## Overview

FigURL provides web-based interactive visualizations for Spyglass data. Data is uploaded to kachery-cloud, which returns a shareable URL that opens in a browser. For paper-snapshot exports rather than ephemeral viewers, see [export.md](export.md).

This reference focuses on the two most common FigURL paths in Spyglass; a third (MUA event visualization) is also exposed via `MuaEventsV1.create_figurl` (`mua/v1/mua.py:154`):

- **Spike sorting curation** (covered below): upload a sorting, label/merge units in the browser, pull the results back into Spyglass
- **Decoding visualization**: generate a 1D or 2D interactive view of posterior probabilities over time
- *MUA event visualization (not covered in detail here)*: see [mua_pipeline.md](mua_pipeline.md).

Sources: `src/spyglass/spikesorting/v1/figurl_curation.py`, `src/spyglass/decoding/decoding_merge.py` (`create_decoding_view`). FigURL is the upstream **web service / project**, not a Spyglass Python dependency. Spyglass integrates with it via `sortingview` and `kachery-cloud` (the actual installed packages — see `pyproject.toml:51, 68`).

Upstream project (FigURL itself, for questions beyond Spyglass integration): <https://github.com/flatironinstitute/figurl>

## Spike Sorting Curation via FigURL

```python
from spyglass.spikesorting.v1 import (
    CurationV1,
    FigURLCurationSelection,
    FigURLCuration,
)
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

# 4. Pull curator's decisions back from kachery. The fetched value is
#    the kachery URI (e.g. `sha1://...`); the helpers call
#    `kachery_cloud.load_json(curation_uri)` internally
#    (`spikesorting/v1/figurl_curation.py:215`) to deref it. Don't pre-load
#    the JSON yourself — pass the URI string in.
curation_uri = (FigURLCurationSelection & sel_key).fetch1("curation_uri")
labels = FigURLCuration.get_labels(curation_uri)         # {unit_id: [labels]}
merge_groups = FigURLCuration.get_merge_groups(curation_uri)  # merge structure

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
CurationV1.insert_curation(sorting_id=sorting_id, labels={})  # other args omitted
```

### Key Methods

- `FigURLCurationSelection.insert_selection(key)` — Class method, auto-generates `figurl_curation_id` UUID and `curation_uri` if missing
- `FigURLCurationSelection.generate_curation_uri(key)` — `@staticmethod`; uploads CurationV1 state to kachery and returns a URI string. Call on the class (`FigURLCurationSelection.generate_curation_uri(key)`), not on an instance.
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
# view is a figurl view object; call .url(label=...) to get the browser URL string
```

Under the hood, this routes to `non_local_detector.visualization.figurl_1D.create_1D_decode_view` or `figurl_2D.create_2D_decode_view` based on the decoder's environment dimensionality.

## Prerequisites

- `sortingview` and `kachery-cloud` installed (core Spyglass dependencies)
- A valid kachery zone configured — see [setup_config.md](setup_config.md) for the env vars and the `KacheryZone` / `AnalysisNwbfileKachery` tables
- Internet access — FigURL uploads to kachery-cloud and returns a hosted URL
- For curation workflows: the `curation_label` column must exist on the parent `CurationV1` NWB

## Common Gotchas

- **URL retention**: kachery-cloud zones have retention policies. If the URL stops working, the underlying data has expired — repopulate to regenerate
- **Upload size**: large sortings or recordings can take minutes to upload. `_generate_figurl` accepts a `segment_duration_sec` windowing kwarg, but the normal `FigURLCuration.populate(sel_key)` path does *not* expose it through `FigURLCurationSelection` — to use it, call `_generate_figurl` directly rather than relying on the table workflow
- **Re-fetching labels**: `get_labels()` / `get_merge_groups()` hit kachery every call. If the curator updates the URL, re-run these to pull the latest state — no local cache
- **`generate_curation_uri()` requires the parent `CurationV1` NWB to have a `curation_label` column** — `insert_curation(labels=None)` itself just doesn't create one. The error fires later when you generate the figurl URI: `figurl_curation.py:87-93` raises `ValueError: Sorting object must have a 'curation_label' column ...`. Pass `labels={}` (or any non-`None` dict) to `insert_curation` — the `insert_curation` body adds the `curation_label` column whenever `labels is not None`, and any unit IDs missing from the dict get an empty `[]` automatically (see the `if labels is not None:` block in `spikesorting/v1/curation.py`). You don't have to enumerate every unit_id yourself.
- **V0 vs V1**: v0 has its own `curation_figurl.py` with a similar but not identical API. V1 is the only path to use for new work — do not fall back to v0 if the v1 path fails. Existing v0 curation rows remain readable via `SpikeSortingOutput` (the merge table is source-agnostic); the FigURL generation path is what differs. Legacy v0 references are in [spikesorting_v0_legacy.md](spikesorting_v0_legacy.md).
