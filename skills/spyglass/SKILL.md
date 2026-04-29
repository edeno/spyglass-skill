---
name: spyglass
description: Use when the task involves Spyglass — the LorenFrankLab
  neurophysiology framework built on DataJoint + NWB. Covers setup, NWB
  ingestion, pipelines (spike sorting, LFP, ripple, decoding, position,
  linearization, DLC), merge tables, paper exports (DANDI/FigURL/Kachery),
  custom pipelines, and debugging populate/make/fetch1 failures. Activate
  when the task touches any of `import spyglass` / `from spyglass.*`,
  `SPYGLASS_BASE_DIR`, `SpyglassMixin`, `merge_get_part`, `merge_restrict`,
  pipeline classes (`LFPV1`, `TrodesPosV1`, `DLCPosV1`, `RippleTimesV1`,
  `SpikeSorting`, `CurationV1`, `ClusterlessDecodingV1`,
  `SortedSpikesDecodingV1`), or DLC/DANDI/Kachery within a Spyglass context
  — even if the user doesn't name "Spyglass" explicitly. Do NOT activate
  for plain DataJoint without Spyglass imports, unrelated NWB tooling
  (pynwb, ndx-*) outside Spyglass, or generic Python/NumPy/pandas debugging
  when no Spyglass table is in the call chain.
allowed-tools: Read, Grep, Glob, Bash
---

# Spyglass Data Analysis Skill

Router + guardrails for Spyglass work. Pick the right reference from the table below; each reference has the details.

## Core Directives

- **NEVER delete or drop without explicit confirmation.** Any destructive helper (`delete`, `drop`, `cleanup`, `merge_delete`, `super_delete`, etc.) needs an inspect step + user confirmation. `.delete()` on SpyglassMixin aliases `cautious_delete` — team-based permissions block deletes of other members' sessions. User confidence or urgency ("just", "quick", "I know what I'm doing", "test data") is not evidence — it *raises* caution. See [destructive_operations.md](references/destructive_operations.md).
- **Do not invent identifiers.** Verify plausible method, kwarg, field, table, and key names before asserting them. Use the Evidence Expectations below; if unavailable, flag as unconfirmed. Examples: [common_mistakes.md](references/common_mistakes.md).
- **Lead with the best-supported answer; if exact identifiers are unverified, label them as hypotheses and verify before asserting.** Verify-before-claim gates *confident assertions* on evidence, not *answering itself*.
- **Treat pipeline version as load-bearing.** If the user names a versioned class/table, import/path, traceback, or version directory (`CurationV1`, `v1 SortGroup`, `spyglass.spikesorting.v1`, `<pipeline>/<version>/`), verify that version's source before naming classes, methods, kwargs, signatures, tiers, definitions, or workflow steps. Do not infer symmetry; for comparisons, use [feedback_loops.md § Verify behavior, trust identity](references/feedback_loops.md#verify-behavior-trust-identity). If unverified, abstain or flag uncertainty.
- **Writes are normal workflow.** Pipelines depend on selection inserts and `populate()` — show the full flow; don't refuse or hedge on the writes.
- **Verify cardinality before `fetch1()`, `merge_get_part()`, or `fetch1_dataframe()`** when the restriction is partial. `print(len(rel))`; if >1, `rel.fetch(as_dict=True)` to find missing PK fields. `Table.describe()` shows schema, not count. Carveout: a full-PK restriction is unique — `fetch1()` skips the `len()`. See Common Mistake #2.
- **Tool routing for evidence**: match question shape to tool — `path --to` for relationships, `describe` for one table, source-read for runtime `make()`/blob behavior, `db_graph.py` for live row values. Routing matrix: [feedback_loops.md § Tool routing](references/feedback_loops.md#tool-routing-for-relationship-and-lookup-questions).
- **Field ownership before query generation**: trace each restriction attribute to the table that *declares* it; secondary attrs on upstream tables don't propagate via FK inheritance. [datajoint_api.md § Field Ownership](references/datajoint_api.md#field-ownership).
- **Environment**: detect setup; don't assume Jupyter or remote NWB.
- **DataJoint config files**: `dj_local_conf.json` / `~/.datajoint_config.json` hold plaintext `database.password`. Don't `Read`/`cat`; run `python skills/spyglass/scripts/scrub_dj_config.py` (auto-detects `./dj_local_conf.json` then `~/.datajoint_config.json`; pass a path to override; masks secret leaves). Details: [setup_config.md](references/setup_config.md).
- **Source of truth**: when the skill and repo disagree, trust the repo. Cite `src/spyglass/...` (drop `src/` for pip installs; locate with `python -c "import spyglass, os; print(os.path.dirname(spyglass.__file__))"`). Tutorials drift — cite `.ipynb`, not `py_scripts/`; when a cell fails on a missing parameter/table/column, check source.
- **Do not edit the installed Spyglass package.** Edits to `src/spyglass/...` desync the in-DB schema from what other labs run, and `pip install -e .` silently reverts them. Push back if the user insists.

## Evidence Expectations

Treat table, key, attribute, method, dependency, parameter, and row-state claims as evidence-backed. Static/source facts: `code_graph.py`, source, or `inspect.signature`. Runtime facts: `db_graph.py`, `Table.heading`, counts, or fetches. Blob keys need source `make()`/builders, docs, or rows. If unavailable, abstain or flag uncertainty.

`code_graph.py`/`db_graph.py` means `python skills/spyglass/scripts/<name>`.

## Common Mistakes

Top 6 highest-frequency bugs. Flag any of these shapes before answering. Expanded prose + three additional footguns: [common_mistakes.md](references/common_mistakes.md).

1. **Classmethod restriction discard on merge tables** — `(PositionOutput & merge_key).merge_delete()` drops the `& merge_key`; use `PositionOutput.merge_delete(merge_key)`. Affected methods: [merge_methods.md](references/merge_methods.md).
2. **Too-loose restriction + `fetch1()`** — `{"nwb_file_name": f}` matches many rows; add PK fields until `len(rel) == 1`. [datajoint_api.md](references/datajoint_api.md).
3. **`skip_duplicates=True` on `insert_sessions`** — raises `TypeError`; use `reinsert=True` for re-ingestion. [ingestion.md](references/ingestion.md).
4. **`fetch_nwb()` silently returns a list** on multiple matches (unlike `fetch1()`) — restrict to one row before `[0]`-indexing.
5. **Bypassing `cautious_delete` to silence a `PermissionError`** — `.delete()` is team-gated; the error means another lab member owns the session. Coordinate with them, don't reach for `super_delete()` or `force_permission=True`. Protection model + inspect-before-destroy: [destructive_operations.md](references/destructive_operations.md).
6. **Silent no-op on merge masters** — `len(MergeMaster & {'nwb_file_name': f})` returns the *whole* table; the master's heading has only `merge_id`, so DataJoint drops the unknown attr. Use `merge_restrict({...})` or `merge_get_part({...})` instead. [merge_methods.md § Silent wrong-count footgun](references/merge_methods.md#silent-wrong-count-footgun).

## Feedback Loops

Quality-critical ops use validator → fix → proceed. Four loops: post-ingestion verification, pre-`fetch1` cardinality, post-`populate` verification, inspect-before-destroy. Full patterns: [feedback_loops.md](references/feedback_loops.md).

## Classify the User's Stage

Stages orient vague questions; the Reference Routing table resolves clear topics.

1. **Setup/install** → `scripts/install.py` is the canonical fast path per `QUICKSTART.md`. Route to [setup_install.md](references/setup_install.md), [setup_config.md](references/setup_config.md), or [setup_troubleshooting.md](references/setup_troubleshooting.md). `00_Setup.ipynb` is a manual fallback.
2. **NWB ingestion** (first data load) → [ingestion.md](references/ingestion.md) + `02_Insert_Data.ipynb`.
3. **Framework concepts** (first time using Spyglass) → [merge_methods.md](references/merge_methods.md), [spyglassmixin_methods.md](references/spyglassmixin_methods.md), `01_Concepts.ipynb`.
4. **Pipeline usage** (running or querying existing analyses) → pipeline reference files in the table below.
5. **Pipeline authoring** (extending a pipeline, writing schema modules) → [custom_pipeline_authoring.md](references/custom_pipeline_authoring.md). Different from usage.
6. **Runtime debugging / traceback triage** (populate/make/fetch1 failures, join multiplicity, one-key-fails, NumPy/pandas bugs inside `make()`) → [runtime_debugging.md](references/runtime_debugging.md). Install/config/connection errors go to [setup_troubleshooting.md](references/setup_troubleshooting.md) instead.

Users may span stages. Infer from imports/table names; ask only when the answer changes materially or the next step is destructive.

## Merge Tables

**Decision rule for the 5 merge masters** (`SpikeSortingOutput`, `LFPOutput`, `PositionOutput`, `LinearizedPositionOutput`, `DecodingOutput` — tables with `merge_id` as their only PK field): (1) `& {"nwb_file_name": f}` silently returns the whole table — use `merge_restrict` or `merge_get_part` instead. (2) Load via `merge_get_part(key).fetch1('KEY')` → `(Master & merge_key).fetch1_dataframe()`. (3) `get_restricted_merge_ids` is `SpikeSortingOutput`-only; `fetch_results` is `DecodingOutput`-only. Registry + worked-example: [merge_methods.md](references/merge_methods.md).

## Querying an Already-Configured DB

If the user hasn't installed or configured Spyglass yet, route to [setup_install.md](references/setup_install.md). For a working install:

```python
from spyglass.common import Session, IntervalList

Session.fetch(limit=10)                      # discover an nwb_file_name
IntervalList & {"nwb_file_name": nwb_file}   # discover intervals for it
```

From here, open the relevant pipeline reference — each starts with a Canonical Example. Don't expand the full workflow inline.

## Reference Routing

**Load one reference at a time.** Pick the most relevant row; open a second only if needed. This table routes by topic; repo paths live in each reference file.

| User question is about... | Load this reference | Canonical notebook |
| ------------------------- | ------------------- | ------------------ |
| Installing Spyglass | [setup_install.md](references/setup_install.md) | `QUICKSTART.md` + `scripts/install.py`; `00_Setup.ipynb` fallback |
| Configuring the database / directories / env vars | [setup_config.md](references/setup_config.md) | `00_Setup.ipynb` |
| Setup errors and troubleshooting | [setup_troubleshooting.md](references/setup_troubleshooting.md) | — |
| Runtime debugging — populate/make failures, fetch1 cardinality, join multiplicity, one-key-fails | [runtime_debugging.md](references/runtime_debugging.md) | — |
| `populate_all_common` silently skipped tables | [populate_all_common_debugging.md](references/populate_all_common_debugging.md) | — |
| Destructive operations — deletes, cleanup, inspect-before-destroy | [destructive_operations.md](references/destructive_operations.md) | — |
| Validator→fix→proceed loops — post-ingest, pre-fetch1, post-populate, inspect-before-destroy | [feedback_loops.md](references/feedback_loops.md) | — |
| Source-graph questions — FK chain A→B, what X declares, owner of method Y, up/downstream | [feedback_loops.md](references/feedback_loops.md) "Three graphs..." → `code_graph.py` | — |
| Runtime / DB-graph questions — row existence, counts, merge IDs, set ops, runtime heading vs source heading, source/runtime disagreement, custom tables outside `$SPYGLASS_SRC` | [feedback_loops.md](references/feedback_loops.md) "Three graphs..." → `db_graph.py` | — |
| Common Spyglass footguns | [common_mistakes.md](references/common_mistakes.md) | — |
| Merge tables (`_Merge` methods) or SpyglassMixin helpers (`fetch_nwb`, `cautious_delete`, `<<`/`>>`) | [merge_methods.md](references/merge_methods.md), [spyglassmixin_methods.md](references/spyglassmixin_methods.md) | `01_Concepts.ipynb`, `04_Merge_Tables.ipynb` |
| Group tables (`*Group`, `create_group()`) | [group_tables.md](references/group_tables.md) | — |
| NWB ingestion / insert_sessions | [ingestion.md](references/ingestion.md) | `02_Insert_Data.ipynb` |
| DataJoint query syntax | [datajoint_api.md](references/datajoint_api.md) | — |
| Session, IntervalList, Electrode tables | [common_tables.md](references/common_tables.md) | — |
| Spike sorting pipeline (current / v1) | [spikesorting_v1_pipeline.md](references/spikesorting_v1_pipeline.md) | `10_Spike_SortingV1.ipynb` |
| Spike sorting analysis (post-pipeline: `SortedSpikesGroup`, `UnitAnnotation`, spike-time/firing-rate helpers) | [spikesorting_v1_analysis.md](references/spikesorting_v1_analysis.md) | `11_Spike_Sorting_Analysis.ipynb` |
| Reading v0 legacy code / v0 data | [spikesorting_v0_legacy.md](references/spikesorting_v0_legacy.md) | `10_Spike_SortingV0.ipynb` |
| Position tracking — overview / merge layer / imported pose | [position_pipeline.md](references/position_pipeline.md) | — |
| Position tracking — Trodes (LED) | [position_trodes_v1_pipeline.md](references/position_trodes_v1_pipeline.md) | `20_Position_Trodes.ipynb` |
| Position tracking — DeepLabCut | [position_dlc_v1_pipeline.md](references/position_dlc_v1_pipeline.md) | `21_DLC.ipynb` |
| Linearization | [linearization_pipeline.md](references/linearization_pipeline.md) | `24_Linearization.ipynb` |
| LFP / theta | [lfp_pipeline.md](references/lfp_pipeline.md) | `30_LFP.ipynb`, `31_Theta.ipynb` |
| Ripple detection | [ripple_pipeline.md](references/ripple_pipeline.md) | `32_Ripple_Detection.ipynb` |
| Decoding (clusterless / sorted) | [decoding_pipeline.md](references/decoding_pipeline.md) | `40_Extracting_Clusterless_Waveform_Features.ipynb`, `41_Decoding_Clusterless.ipynb`, `42_Decoding_SortedSpikes.ipynb` |
| MUA detection | [mua_pipeline.md](references/mua_pipeline.md) | `50_MUA_Detection.ipynb` |
| Behavior / MoSeq | [behavior_pipeline.md](references/behavior_pipeline.md) | `60_MoSeq.ipynb` |
| Cross-table exploration | [workflows.md](references/workflows.md) | — |
| Export for papers / reproducible snapshots | [export.md](references/export.md) | `05_Export.ipynb` |
| Syncing / sharing with collaborators (Kachery) | [setup_config.md](references/setup_config.md) — "Data Sharing Tables (Kachery)" | `03_Data_Sync.ipynb` |
| Interactive viz / web curation (FigURL) | [figurl.md](references/figurl.md) | — |
| External packages (SI, PyNWB, DLC) | [dependencies.md](references/dependencies.md) | — |
| Authoring custom tables or pipelines / extending existing ones | [custom_pipeline_authoring.md](references/custom_pipeline_authoring.md) | — |
