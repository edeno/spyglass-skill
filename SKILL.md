---
name: spyglass
description: Use when the task involves Spyglass — the LorenFrankLab neurophysiology analysis framework built on DataJoint + NWB. Covers installing/configuring Spyglass, ingesting an NWB file via insert_sessions, running V1 pipelines (spike sorting, LFP, ripple, decoding, position, linearization), working with merge tables (PositionOutput, LFPOutput, SpikeSortingOutput, DecodingOutput, LinearizedPositionOutput), exporting a paper bundle, authoring custom Spyglass pipelines, or debugging a populate()/make()/fetch1 failure in a Spyglass table. Triggers on `import spyglass` / `from spyglass.*`, on `SPYGLASS_BASE_DIR`, `SpyglassMixin`, `merge_get_part`, `merge_restrict`, and on V1 pipeline classes (`LFPV1`, `TrodesPosV1`, `DLCPosV1`, `RippleTimesV1`, `SpikeSortingV1`, `CurationV1`, `ClusterlessDecodingV1`, `SortedSpikesDecodingV1`). Activate whenever the task clearly involves a Spyglass table or pipeline — even if the user doesn't name "Spyglass" explicitly.
---

# Spyglass Data Analysis Skill

Router + guardrails for Spyglass work. Pick the right reference from the table below; each reference has the details.

## Core Directives

- **NEVER delete or drop without explicit confirmation.** The database contains irreplaceable neuroscience research data. Destructive helpers (`delete`, `drop`, `cautious_delete`, `super_delete`, `delete_quick`, `merge_delete`, `merge_delete_parent`, `delete_downstream_parts`, `cleanup`, `delete_orphans`) must be paired with an inspect step first and user confirmation second. Canonical paired shapes: [destructive_operations.md](references/destructive_operations.md).
- **Do NOT activate** for plain DataJoint code without Spyglass imports, unrelated NWB tooling (pynwb, ndx-*) outside Spyglass, or generic Python/NumPy/pandas debugging when no Spyglass table is in the call chain.
- **Writes are normal workflow.** Spyglass pipelines are designed around inserting selection rows and calling `populate()` — these writes are the pipeline's intended shape, not signs of user confusion. Show the full flow including the inserts; explain what each write does, but don't refuse or hedge on them.
- **Verify cardinality before `fetch1()`, `merge_get_part()`, or `fetch1_dataframe()`**, including on well-known tables. Recognizing `PositionOutput`, `IntervalList`, or any `*Output` merge table is not the same as knowing its cardinality under a given restriction — that depends on the data (how many intervals, param sets, and pipeline versions exist for this session). Print `len(relation)` or call `Table.describe()` / `Table.heading` to confirm the restriction uniquely identifies one row before the fetch. This is where Common Mistake #2 comes from.
- **Environment**: detect the user's setup (local Docker, local data, remote lab) — don't assume Jupyter or remote NWB.
- **Source of truth**: when the skill and the repo disagree, trust the repo. Source lives at `src/spyglass/` (under the installed package for pip/conda — find with `python -c "import spyglass, os; print(os.path.dirname(spyglass.__file__))"`). User-facing tutorials are `notebooks/*.ipynb` per `notebooks/README.md`; `notebooks/py_scripts/*.py` is a jupytext mirror for PR-review diffs — cite the `.ipynb` form.

## Common Mistakes

Top-frequency bugs. If the user's code shows any of these shapes, flag it before answering the rest of the question.

1. **Classmethod restriction discard on merge tables.** `(PositionOutput & merge_key).merge_delete()` silently drops the `& merge_key` — Python routes classmethod calls to the class. Always pass the restriction as an arg: `PositionOutput.merge_delete(merge_key)`. Full affected-method list: [merge_and_mixin_methods.md](references/merge_and_mixin_methods.md).
2. **Too-loose restriction + `fetch1()`.** `{"nwb_file_name": f}` alone usually matches many rows (every interval, every param set, every pipeline version). `fetch1()`, `merge_get_part()`, `fetch_results()`, and `fetch1_dataframe()` all raise "expected one row, got N". Add enough primary-key fields to pick exactly one row. Discovery pattern: [datajoint_api.md](references/datajoint_api.md).
3. **Passing `skip_duplicates=True` to `insert_sessions`.** `skip_duplicates` is a DataJoint `.insert1()` / `.insert()` flag (valid for manual lookup-table inserts like `ProbeType`, `Lab`). `insert_sessions` does not accept it — passing it raises `TypeError: unexpected keyword argument 'skip_duplicates'`. For re-ingesting raw NWB data, use `reinsert=True` on `insert_sessions` instead. Details: [ingestion.md](references/ingestion.md).
4. **`fetch_nwb()` silently returns a list** when the restriction matches multiple rows — unlike `fetch1()`, it does not raise. `(Table & key).fetch_nwb()[0]` on an under-specified restriction picks an arbitrary row. Fix: restrict to exactly one row before calling.
5. **Destructive call without the paired inspect step.** Every destructive helper has a preview shape (`dry_run=True`, `fetch(as_dict=True)` first, etc.). Inspect step, user confirmation, THEN destroy. See [destructive_operations.md](references/destructive_operations.md).

## Common Feedback Loops

Quality-critical Spyglass operations have a **validator → fix → proceed** shape: run a check, fix anything unexpected, only advance when the check passes. These are proactive versions of the rules in Common Mistakes — they prevent bugs rather than diagnose them.

**Post-ingestion verification.** After `sgi.insert_sessions(fname)`, confirm the session landed cleanly before any pipeline populates. If any check fails, fix the NWB file and rerun with `reinsert=True`. Full ingestion flow: [ingestion.md](references/ingestion.md).

```python
f = "j1620210710_.nwb"                                  # copy-form; Spyglass appends the "_"
(Session & {"nwb_file_name": f}).fetch1("session_id")   # must return 1 row
print(len(IntervalList & {"nwb_file_name": f}))         # must be > 0
print(len(Electrode & {"nwb_file_name": f}))            # compare to NWB metadata
```

**Pre-`fetch1()` cardinality check.** Before any `fetch1()`, `merge_get_part()`, or `fetch1_dataframe()`. Proactive form of Common Mistake #2.

```python
rel = (SomeTable & key)
print(len(rel))          # must be exactly 1
# If != 1: add more primary-key fields, rerun the print
result = rel.fetch1()    # only call after len == 1 is confirmed
```

**Post-`populate()` verification.** After a pipeline `populate()`, confirm rows landed and one output has the expected shape. If the count or shape is off, debug the failing key before moving on — see [runtime_debugging.md](references/runtime_debugging.md).

```python
MyPipelineV1.populate(key)
print(len(MyPipelineV1 & key))                   # keys you asked for get processed?
sample = (MyPipelineV1 & key).fetch(limit=1, as_dict=True)[0]
# Eyeball dtypes/shapes against downstream code's assumptions
```

**Inspect-before-destroy.** Canonical feedback-loop shape — inspect is the validator, user confirmation is the pass gate, the destructive call is the proceed step. Paired shapes for every destructive helper: [destructive_operations.md](references/destructive_operations.md).

```python
target = (SomeTable & restriction)
target.fetch(as_dict=True)   # inspect scope; cascade preview for .delete()
# Get explicit user confirmation here
target.delete()              # only after confirmation
```

## Classify the User's Stage

1. **Setup/install** → `scripts/install.py` is the canonical fast path per `QUICKSTART.md`. Route to [setup_install.md](references/setup_install.md), [setup_config.md](references/setup_config.md), or [setup_troubleshooting.md](references/setup_troubleshooting.md). `00_Setup.ipynb` is a manual fallback.
2. **NWB ingestion** (first data load) → [ingestion.md](references/ingestion.md) + `02_Insert_Data.ipynb`.
3. **Framework concepts** (first time using Spyglass) → [merge_and_mixin_methods.md](references/merge_and_mixin_methods.md) + `01_Concepts.ipynb`. `04_Merge_Tables.ipynb` is a later, specialized concept — don't lead with it for novice questions.
4. **Pipeline usage** (running or querying existing analyses) → pipeline reference files in the table below.
5. **Pipeline authoring** (extending a pipeline, writing schema modules) → [custom_pipeline_authoring.md](references/custom_pipeline_authoring.md). Very different surface from usage.
6. **Runtime debugging / traceback triage** (populate/make/fetch1 failures, join multiplicity, one-key-fails, NumPy/pandas bugs inside `make()`) → [runtime_debugging.md](references/runtime_debugging.md). Install/config/connection errors go to [setup_troubleshooting.md](references/setup_troubleshooting.md) instead.

Users may span stages. Infer from the question and any imports/table names in context — don't halt to ask unless (a) the answer would change materially (pipeline usage vs. authoring), or (b) the next step is destructive and intent is ambiguous.

## Merge Tables in One Paragraph

Merge tables consolidate outputs from multiple pipeline versions behind a single `merge_id`. Two access paths: **direct** (e.g., `DecodingOutput.fetch_results(key)` handles resolution internally) and **manual** (`part = MergeTable.merge_get_part(key); merge_key = part.fetch1("KEY"); (MergeTable & merge_key).fetch1_dataframe()`). Treat `merge_key` as an opaque restriction — pass it to `&`, don't read fields out of it. For the full surface (classmethod rules, `<<`/`>>` semantics, canonical example), load [merge_and_mixin_methods.md](references/merge_and_mixin_methods.md).

## Querying an Already-Configured DB

If the user hasn't installed or configured Spyglass yet, route to [setup_install.md](references/setup_install.md). For a working install:

```python
from spyglass.common import Session, IntervalList

Session.fetch(limit=10)                      # discover an nwb_file_name
IntervalList & {"nwb_file_name": nwb_file}   # discover intervals for it
```

From here, open the relevant pipeline reference — each starts with a Canonical Example. Don't expand the full workflow inline.

## Reference Routing

**Progressive disclosure — load one reference at a time.** Pick the single most relevant row. Only open a second reference if the first doesn't cover the question. Don't pre-load several "to be safe" — it wastes context.

Repo paths (source, docs) are listed in each reference file — this table routes by topic, not by path.

| User question is about... | Load this reference | Canonical notebook |
| ------------------------- | ------------------- | ------------------ |
| Installing Spyglass | [setup_install.md](references/setup_install.md) | `QUICKSTART.md` + `scripts/install.py`; `00_Setup.ipynb` fallback |
| Configuring the database / directories / env vars | [setup_config.md](references/setup_config.md) | `00_Setup.ipynb` |
| Setup errors and troubleshooting | [setup_troubleshooting.md](references/setup_troubleshooting.md) | — |
| Runtime debugging — populate/make failures, fetch1 cardinality, ambiguous-truth, join multiplicity, one-key-fails | [runtime_debugging.md](references/runtime_debugging.md) | — |
| Destructive operations — deletes, cleanup, inspect-before-destroy patterns | [destructive_operations.md](references/destructive_operations.md) | — |
| Framework concepts / merge tables | [merge_and_mixin_methods.md](references/merge_and_mixin_methods.md) | `01_Concepts.ipynb`, `04_Merge_Tables.ipynb` |
| NWB ingestion / insert_sessions | [ingestion.md](references/ingestion.md) | `02_Insert_Data.ipynb` |
| DataJoint query syntax | [datajoint_api.md](references/datajoint_api.md) | — |
| Session, IntervalList, Electrode tables | [common_tables.md](references/common_tables.md) | — |
| Spike sorting pipeline (current / v1) | [spikesorting_pipeline.md](references/spikesorting_pipeline.md) | `10_Spike_SortingV1.ipynb`, `11_Spike_Sorting_Analysis.ipynb` |
| Reading v0 legacy code / v0 data | [spikesorting_v0_legacy.md](references/spikesorting_v0_legacy.md) | `10_Spike_SortingV0.ipynb` |
| Position tracking (Trodes / DLC) | [position_pipeline.md](references/position_pipeline.md) | `20_Position_Trodes.ipynb`, `21_DLC.ipynb` |
| Linearization | [linearization_pipeline.md](references/linearization_pipeline.md) | `24_Linearization.ipynb` |
| LFP / theta | [lfp_pipeline.md](references/lfp_pipeline.md) | `30_LFP.ipynb`, `31_Theta.ipynb` |
| Ripple detection | [ripple_pipeline.md](references/ripple_pipeline.md) | `32_Ripple_Detection.ipynb` |
| Decoding (clusterless / sorted) | [decoding_pipeline.md](references/decoding_pipeline.md) | `40_Extracting_Clusterless_Waveform_Features.ipynb`, `41_Decoding_Clusterless.ipynb`, `42_Decoding_SortedSpikes.ipynb` |
| MUA detection | [mua_pipeline.md](references/mua_pipeline.md) | `50_MUA_Detection.ipynb` |
| Behavior / MoSeq | [behavior_pipeline.md](references/behavior_pipeline.md) | `60_MoSeq.ipynb` |
| Cross-table exploration / troubleshooting | [workflows.md](references/workflows.md) | — |
| Export for papers / reproducible snapshots | [export.md](references/export.md) | `05_Export.ipynb` |
| Syncing / sharing with collaborators (Kachery) | [setup_config.md](references/setup_config.md) — "Data Sharing Tables (Kachery)" | `03_Data_Sync.ipynb` |
| Interactive viz / web curation (FigURL) | [figurl.md](references/figurl.md) | — |
| External packages (SI, PyNWB, DLC) | [dependencies.md](references/dependencies.md) | — |
| Authoring a new pipeline / extending an existing one | [custom_pipeline_authoring.md](references/custom_pipeline_authoring.md) | — |

When a reference and the repo disagree, trust the repo.
