---
name: spyglass
description: Use when writing, debugging, running, installing, or learning Spyglass — the LorenFrankLab neurophysiology analysis framework built on DataJoint + NWB. Activate on plain-language tasks like "install Spyglass", "set up Spyglass", "run the Spyglass tutorials", "ingest an NWB file into Spyglass", "run spike sorting / LFP / ripple detection / decoding / position tracking / linearization in Spyglass", "share Spyglass analysis files", "export a Spyglass paper bundle", "build a custom Spyglass pipeline". Also activate on code signals: `import spyglass` / `from spyglass.*`; merge tables (`PositionOutput`, `LFPOutput`, `SpikeSortingOutput`, `DecodingOutput`, `LinearizedPositionOutput`); `insert_sessions` or `SPYGLASS_BASE_DIR`; `merge_get_part` / `merge_restrict`. Do NOT activate for: plain DataJoint code without Spyglass imports; unrelated NWB tooling (pynwb, ndx-*) where Spyglass is not in the call chain; generic electrophysiology analysis unrelated to the Spyglass framework.
---

# Spyglass Data Analysis Skill

## Role & Core Directives

- **NEVER delete or drop without explicit confirmation**: This database contains irreplaceable neuroscience research data. Never generate destructive operations without first warning the user what will be affected and getting explicit confirmation. Explain what downstream data will be cascade-deleted before providing the code. Destructive operations include:
  - DataJoint: `delete()`, `drop()`, `cautious_delete()`, `super_delete()`, `delete_quick()`
  - Merge-table helpers: `merge_delete()`, `merge_delete_parent()`, `delete_downstream_parts()`
  - File cleanup: `cleanup()`, `delete_orphans()` — these remove analysis files from disk
- **Safe-before-destructive idiom**: always show the inspect step before the destroy step. See the paired shapes below — never present the destroy step without the matching inspect step above it.
- **Writes are normal workflow**: Spyglass pipelines require inserting selection rows and populating tables. When the user asks how to run a pipeline, show the full workflow including inserts and populates. Explain what each write does, but don't refuse to show it
- **Environment**: Do not assume Jupyter or remote NWB files — detect the user's setup from context. Spyglass supports local Docker, local data, and remote-lab workflows
- **Verify schema when unsure**: For tables you haven't worked with or when an example's field names look uncertain, inspect with `Table.describe()` or `Table.heading` before writing the query. For well-known tables already shown in the skill examples (`Session`, `IntervalList`, `PositionOutput`, etc.), don't add an inspection step to routine queries — it's friction
- **Source of truth**: When skill references conflict with the repo, trust the repo. Key locations:
  - `src/spyglass/common/` — shared tables; `src/spyglass/<pipeline>/` — pipeline code
  - `src/spyglass/utils/` — SpyglassMixin, _Merge; `notebooks/*.ipynb` — canonical user-facing workflows (per `notebooks/README.md`; `notebooks/py_scripts/*.py` is a jupytext mirror kept for PR review diffs — same content, route users to the `.ipynb` form)
- **Pip/conda users (no repo checkout)**: The `src/spyglass/` layout lives under the installed package — find it with `python -c "import spyglass, os; print(os.path.dirname(spyglass.__file__))"`. Notebooks, docs, and `scripts/` are NOT installed; fetch them from GitHub:
  - Notebooks: `https://github.com/LorenFrankLab/spyglass/tree/master/notebooks/` (run the `.ipynb` files in Jupyter; `py_scripts/` holds `.py` mirrors for PR review)
  - Docs: `https://lorenfranklab.github.io/spyglass/` (or `https://github.com/LorenFrankLab/spyglass/tree/master/docs/src/`)

## Safe-Before-Destructive Patterns

For every destructive helper listed above, the skill ships a paired inspect step. Produce the inspect step first, get user confirmation, THEN the destroy step. Never present the destroy step alone.

```python
# Delete rows: restrict, fetch to preview, confirm, THEN delete.
target = (Session & key)
print(len(target), "rows will be deleted; cascades to downstream tables")
target.fetch(as_dict=True)          # inspect what is there
# After user confirms:  target.delete()

# Merge-table delete helpers: merge_delete is a CLASSMETHOD with
# restriction=True as default. Calling it on a restricted relation like
# `(PositionOutput & merge_key).merge_delete()` silently drops the
# restriction — Python routes classmethod calls to the class, so that
# pattern deletes EVERY merge entry. Always pass the restriction as an
# arg: PositionOutput.merge_delete(restriction). Canonical example:
# notebooks/04_Merge_Tables.ipynb (see py_scripts/04_Merge_Tables.py:198 for
# the review-diff mirror of the same content).
merge_key = PositionOutput.merge_get_part(key).fetch1("KEY")
print((PositionOutput & merge_key).fetch(as_dict=True))   # inspect
# After confirm:  PositionOutput.merge_delete(merge_key)

# File cleanup: dry_run=True first, inspect the log output, THEN rerun.
# cleanup() returns None in both modes — it LOGS paths it would remove
# when dry_run=True, and deletes them when dry_run=False. Read the logs
# before the destroy call.
# cleanup() is pipeline-scoped: DecodingOutput().cleanup() removes only
# orphaned .nc/.pkl files from the decoding pipeline. AnalysisNwbfile
# has its own cleanup() for orphaned analysis NWB files across tables;
# same dry_run discipline applies.
DecodingOutput().cleanup(dry_run=True)   # LOGS what would be removed
# After confirming the logs look right:
# DecodingOutput().cleanup(dry_run=False)

# delete_downstream_parts: ALWAYS call on a restricted relation, never the
# whole table. reload_cache=True because the cache can be stale and
# silently return "nothing to delete" when entries actually exist.
(Nwbfile & {"nwb_file_name": nwb_copy_file_name}).delete_downstream_parts(
    reload_cache=True, dry_run=True,
)
```

## First Step: Classify the User's Stage

Before answering, decide which stage the user is in:

1. **Setup/install** → `scripts/install.py` (interactive installer) is the canonical fast path per the repo's `QUICKSTART.md`. Route to [setup_install.md](references/setup_install.md) for install methods and installer/validator scripts, [setup_config.md](references/setup_config.md) for database + directory + env-var configuration, or [setup_troubleshooting.md](references/setup_troubleshooting.md) for setup errors. `00_Setup.ipynb` is a fallback for walking through configuration manually
2. **NWB ingestion** (first data load) → [ingestion.md](references/ingestion.md) + `02_Insert_Data.ipynb`. Warn that `skip_duplicates=True` is for lookup tables / pipeline reruns only, not raw data — use `reinsert=True` for raw re-ingestion
3. **Framework concepts** (first time using Spyglass) → this SKILL.md + `01_Concepts.ipynb` for the core DataJoint+NWB mental model. `04_Merge_Tables.ipynb` is a later, specialized concept for pipeline versioning — don't lead with it for novice questions
4. **Pipeline usage** (running or querying existing analyses) → merge table workflow below + pipeline reference files
5. **Pipeline authoring** (extending a pipeline, building a new analysis off ingested/common tables, writing schema modules) → [custom_pipeline_authoring.md](references/custom_pipeline_authoring.md). Very different surface from usage — different imports, different class conventions, different non-negotiables.

Users may span stages. Prefer to infer the stage from the question and any imports/table names visible in context — don't halt the flow to ask. Ask only when (a) the answer would materially change depending on stage (e.g., pipeline usage vs. authoring), or (b) the next step is destructive and the user's intent is ambiguous.

## Merge Tables — The Key Concept

Merge tables consolidate outputs from multiple pipeline versions into a single `merge_id` interface. Not all part tables are merge tables — `Session.Experimenter` is a regular part table.

**Two ways to access merge table data:**

**Direct access** (DecodingOutput accepts friendly keys and resolves internally):
```python
results = DecodingOutput.fetch_results(key)  # no manual merge resolution needed
model = DecodingOutput.fetch_model(key)
# Still raises ValueError if key matches 0 or >1 entries
```

**Manual merge resolution** (when you need a merge-row restriction):
```python
part = MergeTable.merge_get_part(key)       # raises ValueError if 0 or >1 match
merge_key = part.fetch1("KEY")              # full part-table PK; use as a restriction
data = (MergeTable & merge_key).fetch1_dataframe()  # for position, LFP, linearization
```

Don't assume `merge_key` is `{'merge_id': 'abc...'}` alone. It's whatever the part table's primary key is (usually just `merge_id`, but treat it as an opaque restriction). Use it by passing to `&`, not by reading fields out of it.

**Gotcha**: `merge_get_part()` raises `ValueError` on zero or multiple matches. Use `multi_source=True` to allow multiple.

**Gotcha**: Don't restrict merge tables with friendly keys directly — use `merge_get_part()`, `merge_restrict()`, or `<<`.

**Gotcha — classmethod restriction discard** (common, high-impact): on merge tables, `merge_delete`, `merge_delete_parent`, `merge_restrict`, `merge_get_part`, `merge_get_parent`, `merge_view`, and `merge_html` are all `@classmethod`s that take the restriction as an **argument**, not from the instance. Python dispatches classmethod calls to the class, silently dropping any `& key` prefix. The same shape applies to the `Nwbfile.cleanup` staticmethod. So `(PositionOutput & merge_key).merge_delete()` runs with `restriction=True` → deletes every row in `PositionOutput`. Always pass the restriction as an arg: `PositionOutput.merge_delete(merge_key)`. The complete list of affected methods and their correct call forms is in [references/merge_and_mixin_methods.md](references/merge_and_mixin_methods.md).

**Gotcha — too-loose restriction** (common, not merge-specific): a restriction like `{"nwb_file_name": nwb_file}` alone usually matches MANY rows — every interval, every parameter set, every pipeline version for that session. That's what causes `fetch1()`, `merge_get_part()`, `fetch_results()`, and `fetch1_dataframe()` to raise "expected one row, got N" — the restriction was under-specified. Note: `fetch_nwb()` does NOT raise on multiple rows — it silently returns a list across all matches, which can produce wrong-but-plausible downstream results if you `[0]`-index without thinking. The same footgun applies to any Spyglass or DataJoint table, not just merge tables. Fix: include enough primary-key fields to pick exactly one row (typically `nwb_file_name` + `interval_list_name` + a params name). When unsure what exists, restrict loosely first, print the result, then build a fully-specified key:

```python
# Discover, don't guess — shows you every matching row and its full key
PositionOutput.merge_restrict({"nwb_file_name": nwb_file})
# Once you see the options, pick ONE and build a fully-specified key
key = {"nwb_file_name": nwb_file, "interval_list_name": "02_r1",
       "trodes_pos_params_name": "default"}
```

Pipeline output tables, import paths, and fetch methods are documented in each pipeline reference — use the routing table below. Common tables: `from spyglass.common import Session, IntervalList, Nwbfile, ElectrodeGroup, Electrode, Raw`. All tables inherit `fetch_nwb()`, `<<`/`>>`, and other SpyglassMixin methods — see [references/merge_and_mixin_methods.md](references/merge_and_mixin_methods.md).

## Querying an Already-Configured DB

This is **not** an onboarding quick start. If the user hasn't installed or configured Spyglass yet, route them to [setup_install.md](references/setup_install.md) first. The snippet below is for a working install where the goal is to discover what's already in the database:

```python
from spyglass.common import Session, IntervalList

Session.fetch(limit=10)                      # discover an nwb_file_name
IntervalList & {"nwb_file_name": nwb_file}   # discover intervals for it
```

From here, open the relevant pipeline reference — each starts with a Canonical Example: [position_pipeline.md](references/position_pipeline.md), [lfp_pipeline.md](references/lfp_pipeline.md), [spikesorting_pipeline.md](references/spikesorting_pipeline.md), [decoding_pipeline.md](references/decoding_pipeline.md), [linearization_pipeline.md](references/linearization_pipeline.md), [ripple_pipeline.md](references/ripple_pipeline.md), [mua_pipeline.md](references/mua_pipeline.md), [behavior_pipeline.md](references/behavior_pipeline.md). Do not expand the full workflow inline — load the one file you need.

## Reference Routing

For simple data queries, the examples above are usually sufficient. For deeper questions, load the right reference.

**Progressive disclosure — load one reference at a time.** Pick the single most relevant row from the table below and read that file first. Only open additional reference files if the first one doesn't cover the user's question, or if you actually need content from a second topic (e.g., a position question that also touches spike sorting). Don't pre-load several references "to be safe" — it wastes context.

| User question is about... | Load this reference | Canonical notebook | Repo path |
| ------------------------- | ------------------- | ------------------ | --------- |
| Installing Spyglass | [setup_install.md](references/setup_install.md) | `QUICKSTART.md` + `scripts/install.py`; `00_Setup.ipynb` as notebook fallback | `scripts/install.py`, `QUICKSTART.md` |
| Configuring the database / directories / env vars | [setup_config.md](references/setup_config.md) | `00_Setup.ipynb` | `src/spyglass/settings.py`, `dj_local_conf_example.json` |
| Setup errors and troubleshooting | [setup_troubleshooting.md](references/setup_troubleshooting.md) | — | `scripts/validate.py` |
| Framework concepts / merge tables | [merge_and_mixin_methods.md](references/merge_and_mixin_methods.md) | `01_Concepts.ipynb`, `04_Merge_Tables.ipynb` | `src/spyglass/utils/` |
| NWB ingestion / insert_sessions | [ingestion.md](references/ingestion.md) | `02_Insert_Data.ipynb` | `src/spyglass/data_import/insert_sessions.py`, `docs/src/Features/Ingestion.md` |
| DataJoint query syntax | [datajoint_api.md](references/datajoint_api.md) | — | — |
| Session, IntervalList, Electrode tables | [common_tables.md](references/common_tables.md) | — | `src/spyglass/common/` |
| Spike sorting pipeline (current / v1) | [spikesorting_pipeline.md](references/spikesorting_pipeline.md) | `10_Spike_SortingV1.ipynb`, `11_Spike_Sorting_Analysis.ipynb` | `src/spyglass/spikesorting/v1/` |
| Reading v0 legacy code / v0 data | [spikesorting_v0_legacy.md](references/spikesorting_v0_legacy.md) | `10_Spike_SortingV0.ipynb` | `src/spyglass/spikesorting/v0/` |
| Position tracking (Trodes / DLC) | [position_pipeline.md](references/position_pipeline.md) | `20_Position_Trodes.ipynb`, `21_DLC.ipynb` | `src/spyglass/position/` |
| Linearization | [linearization_pipeline.md](references/linearization_pipeline.md) | `24_Linearization.ipynb` | `src/spyglass/linearization/` |
| LFP / theta | [lfp_pipeline.md](references/lfp_pipeline.md) | `30_LFP.ipynb`, `31_Theta.ipynb` | `src/spyglass/lfp/` |
| Ripple detection | [ripple_pipeline.md](references/ripple_pipeline.md) | `32_Ripple_Detection.ipynb` | `src/spyglass/ripple/` |
| Decoding (clusterless / sorted) | [decoding_pipeline.md](references/decoding_pipeline.md) | `40_Extracting_Clusterless_Waveform_Features.ipynb`, `41_Decoding_Clusterless.ipynb`, `42_Decoding_SortedSpikes.ipynb` | `src/spyglass/decoding/` |
| MUA detection | [mua_pipeline.md](references/mua_pipeline.md) | `50_MUA_Detection.ipynb` | `src/spyglass/mua/` |
| Behavior / MoSeq | [behavior_pipeline.md](references/behavior_pipeline.md) | `60_MoSeq.ipynb` | `src/spyglass/behavior/` |
| Cross-table exploration / troubleshooting | [workflows.md](references/workflows.md) | — | — |
| Export for papers / reproducible snapshots | [export.md](references/export.md) | `05_Export.ipynb` | `src/spyglass/common/common_usage.py` |
| Syncing / sharing analysis files with collaborators (Kachery) | [setup_config.md](references/setup_config.md) — "Data Sharing Tables (Kachery)" section | `03_Data_Sync.ipynb` | `src/spyglass/sharing/sharing_kachery.py` |
| Interactive viz / web curation (FigURL) | [figurl.md](references/figurl.md) | — | `src/spyglass/spikesorting/v1/figurl_curation.py`, `src/spyglass/decoding/decoding_merge.py` |
| External packages (SI, PyNWB, DLC) | [dependencies.md](references/dependencies.md) | — | — |
| Authoring a new pipeline / extending an existing one | [custom_pipeline_authoring.md](references/custom_pipeline_authoring.md) | — | `docs/src/ForDevelopers/CustomPipelines.md`, `docs/src/ForDevelopers/TableTypes.md`, `docs/src/ForDevelopers/Schema.md`, `docs/src/ForDevelopers/Classes.md`, `docs/src/ForDevelopers/Reuse.md` |

When a reference file and the repo disagree, trust the repo. The `notebooks/*.ipynb` files are the canonical end-to-end examples that users run; `notebooks/py_scripts/*.py` is a jupytext mirror of those notebooks (kept for PR-review diffs, per `notebooks/README.md`) — cite the `.ipynb` form when pointing users at a tutorial.
