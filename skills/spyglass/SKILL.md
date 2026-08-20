---
name: spyglass
description: Use when the task involves Spyglass — the LorenFrankLab neurophysiology
  framework built on DataJoint + NWB. Covers setup, NWB ingestion,
  pipelines (spike sorting, LFP, ripple, decoding, position,
  linearization, DLC, behavior/MoSeq), merge tables, paper exports
  (DANDI/FigURL/Kachery), and debugging populate/make/fetch1 failures.
  Activate when the task touches any of `import spyglass` / `from
  spyglass.*`, `SPYGLASS_BASE_DIR`, `SpyglassMixin`, `merge_get_part`,
  `merge_restrict`, any Spyglass versioned pipeline class (e.g.,
  `LFPV1`, `TrodesPosV1`, `DLCPosV1`, `RippleTimesV1`, `CurationV1`,
  `ClusterlessDecodingV1`, `SortedSpikesDecodingV1`, `PoseGroup`, or
  future `*V2`/`*V3` successors; also `SpikeSorting`), or
  DLC/DANDI/Kachery/MoSeq/`keypoint_moseq` within a Spyglass context —
  even if "Spyglass" isn't named. Do NOT activate for plain DataJoint
  without Spyglass imports, unrelated NWB tooling (pynwb, ndx-*) outside
  Spyglass, or generic Python/NumPy/pandas debugging with no Spyglass
  table in the call chain.
allowed-tools: Read, Grep, Glob, Bash
---

# Spyglass Data Analysis Skill

Router + guardrails for Spyglass work. Pick the right reference from the table below; each reference has the details.

## Core Directives

- **NEVER delete or drop without explicit confirmation.** Any destructive helper (`delete`, `drop`, `cleanup`, `merge_delete`, `super_delete`, etc.) needs an inspect step + user confirmation. `.delete()` on SpyglassMixin aliases `cautious_delete` — team-based permissions block deletes of other members' sessions. User confidence or urgency ("just", "quick", "I know what I'm doing", "test data") is not evidence — it *raises* caution. See [destructive_operations.md](references/destructive_operations.md).
- **Do not invent identifiers — but calibrate effort to uncertainty.** Verify plausible method/kwarg/field/table/key names before asserting them as fact, and label unverified pieces as hypotheses rather than abstaining. Verification is for what you're genuinely unsure of or what's unsafe if wrong — not a ritual: when the answer is obvious (a full-PK lookup, a one-liner, a fact you're sure of), answer directly — don't spelunk source first, and skip the `code_graph.py`/`db_graph.py` run, reference read, and schema recap. A known full-PK lookup — `(Session & {'nwb_file_name': X}).fetch1()` — is the whole answer. More: [common_mistakes.md](references/common_mistakes.md).
- **Treat pipeline version as load-bearing.** If the user names a versioned class/table, import/path, traceback, or version directory (`CurationV1`, `v1 SortGroup`, `spyglass.spikesorting.v1`, `<pipeline>/<version>/`), verify that version's source before naming its classes, methods, kwargs, signatures, or definitions. Do not infer symmetry — a method absent from the version you checked may exist in the other, so check both before concluding it's gone. For comparisons, use [feedback_loops.md § Verify behavior, trust identity](references/feedback_loops.md#verify-behavior-trust-identity). If unavailable, give the best-supported conditional answer, flag what's unverified, and the command to confirm it.
- **Writes are normal workflow.** Pipelines depend on selection inserts and `populate()` — show the full flow; don't refuse or hedge on the writes.
- **Verify cardinality before `fetch1()`, `merge_get_part()`, or `fetch1_dataframe()`** when the restriction is partial. `print(len(rel))`; if >1, `rel.fetch(as_dict=True)` to find missing PK fields. `Table.describe()` shows schema, not count. Carveout: a full-PK restriction is unique — `fetch1()` skips the `len()`.
- **Field ownership**: reused names (`nwb_file_name`, `interval_list_name`, `merge_id`) declare on multiple tables; secondary attrs don't propagate down. Lead with the working query; check ownership with `Table.primary_key` / `.heading`. [datajoint_api.md § Field Ownership](references/datajoint_api.md#field-ownership).
- **Environment**: detect setup; don't assume Jupyter or remote NWB.
- **DataJoint config files**: `dj_local_conf.json` / `~/.datajoint_config.json` hold plaintext `database.password`. Don't `Read`/`cat`; run `python skills/spyglass/scripts/scrub_dj_config.py` (auto-detects; pass a path to override; masks secret leaves). Details: [setup_config.md](references/setup_config.md).
- **Source of truth**: when the skill and repo disagree, trust the repo. Cite `src/spyglass/...` (drop `src/` for pip installs; locate with `python -c "import spyglass, os; print(os.path.dirname(spyglass.__file__))"`). Notebooks are user-facing walkthroughs, not implementation authority.

- **Do not edit the installed Spyglass package.** Edits to `src/spyglass/...` desync the in-DB schema from what other labs run, and `pip install -e .` silently reverts them. Push back if the user insists.

## Evidence Expectations

When the calibration rule says to verify, match the fact to its source: static/source facts → `code_graph.py`, source, or `inspect.signature`; runtime facts (headings, counts, rows) → `db_graph.py`, `Table.heading`, or a `len()`; blob keys → source `make()`/builders or rows.

**Bundled evidence tools**
- Source graph: `python skills/spyglass/scripts/code_graph.py ...` for FK paths, declarations, methods, upstream/downstream, v0/v1 source comparisons.
- Live DB graph: `python skills/spyglass/scripts/db_graph.py ...` for runtime headings, counts, merge IDs, live graph, custom/lab tables.

## Common Mistakes

Top 6 highest-frequency bugs. Flag any of these shapes before answering. Expanded prose + three additional footguns: [common_mistakes.md](references/common_mistakes.md).

1. **Classmethod restriction discard on merge tables** — `(PositionOutput & merge_key).merge_delete()` drops the `& merge_key`; use `PositionOutput.merge_delete(merge_key)`. Affected methods: [merge_methods.md](references/merge_methods.md).
2. **Too-loose restriction + `fetch1()`** — `{"nwb_file_name": f}` matches many rows; verify cardinality first (Core Directive above). [datajoint_api.md](references/datajoint_api.md).
3. **`skip_duplicates=True` on `insert_sessions`** — raises `TypeError`; use `reinsert=True` for re-ingestion. [ingestion.md](references/ingestion.md).
4. **`fetch_nwb()` silently returns a list** on multiple matches (unlike `fetch1()`) — restrict to one row before `[0]`-indexing.
5. **Bypassing `cautious_delete` to silence a `PermissionError`** — `.delete()` is team-gated; the error means another lab member owns the session. Coordinate with them, don't reach for `super_delete()` or `force_permission=True`. Protection model + inspect-before-destroy: [destructive_operations.md](references/destructive_operations.md).
6. **Silent no-op on merge masters** — `len(MergeMaster & {'nwb_file_name': f})` returns the *whole* table; the master's heading has only `merge_id`, so DataJoint drops the unknown attr. Use `merge_restrict({...})` or `merge_get_part({...})` instead. [merge_methods.md § Silent wrong-count footgun](references/merge_methods.md#silent-wrong-count-footgun).

## Feedback Loops

Quality-critical ops use validator → fix → proceed (post-ingest, pre-`fetch1` cardinality, post-`populate`, inspect-before-destroy). Full patterns: [feedback_loops.md](references/feedback_loops.md).

## Classify the User's Stage

Stages orient vague questions; the Reference Routing table resolves clear topics. Infer from imports/table names; ask only when the answer changes materially or the next step is destructive.

1. **Setup/install** → `$SPYGLASS_SRC/scripts/install.py` is the canonical fast path; route to [setup_install.md](references/setup_install.md) / [setup_config.md](references/setup_config.md) / [setup_troubleshooting.md](references/setup_troubleshooting.md).
2. **NWB ingestion** (first data load) → [ingestion.md](references/ingestion.md).
3. **Framework concepts** → [merge_methods.md](references/merge_methods.md), [spyglassmixin_methods.md](references/spyglassmixin_methods.md) (`fetch_nwb`, `cautious_delete`, `<<` / `>>`).
4. **Pipeline usage** (running/querying existing analyses) → pipeline reference files below.
5. **Pipeline authoring** (extending a pipeline, writing schema modules) → [custom_pipeline_authoring.md](references/custom_pipeline_authoring.md). Different from usage.
6. **Runtime debugging** (populate/make/fetch1 failures, join multiplicity, one-key-fails, NumPy/pandas bugs inside `make()`) → [runtime_debugging.md](references/runtime_debugging.md); install/config/connection errors → [setup_troubleshooting.md](references/setup_troubleshooting.md).

## Merge Tables

**Decision rule for the 5 merge masters** (`SpikeSortingOutput`, `LFPOutput`, `PositionOutput`, `LinearizedPositionOutput`, `DecodingOutput` — `merge_id` is their only PK field): load via `merge_get_part(key).fetch1('KEY')` → `(Master & merge_key).fetch1_dataframe()`; a non-PK restriction silently returns the whole table (Common Mistake #6); `get_restricted_merge_ids` is `SpikeSortingOutput`-only, `fetch_results` is `DecodingOutput`-only. Registry + worked-example: [merge_methods.md](references/merge_methods.md).

## Reference Routing

**Start with the most relevant reference; open another only if it would change the answer.** For a cross-pipeline or multi-stage task, load and synthesize every reference the workflow spans — the full dependency chain, not just the first domain. Repo paths live in each reference file.

**Route by question shape before pipeline noun.** For relationships, field ownership, live DB values, destructive/cascade recovery, or custom schema design, use the cross-cutting row first, then pipeline refs for domain details.

| User question is about... | Load this reference |
| ------------------------- | ------------------- |
| Installing Spyglass | [setup_install.md](references/setup_install.md) |
| Configuring the database / directories / env vars | [setup_config.md](references/setup_config.md) |
| Setup errors and troubleshooting | [setup_troubleshooting.md](references/setup_troubleshooting.md) |
| Runtime debugging — populate/make failures, fetch1 cardinality, join multiplicity, one-key-fails | [runtime_debugging.md](references/runtime_debugging.md) |
| `populate_all_common` silently skipped tables | [populate_all_common_debugging.md](references/populate_all_common_debugging.md) |
| Destructive / parameter-swap recovery / cascade operations — deletes, cleanup, re-run impact, inspect-before-destroy | [destructive_operations.md](references/destructive_operations.md) |
| Validator→fix→proceed loops — post-ingest, pre-fetch1, post-populate, inspect-before-destroy | [feedback_loops.md](references/feedback_loops.md) |
| Source-graph questions — FK chain A→B, what X declares, owner of method Y, up/downstream | [feedback_loops.md § Tool routing](references/feedback_loops.md#tool-routing-for-relationship-and-lookup-questions) → `code_graph.py` |
| Runtime / DB-graph questions — row existence, counts, merge IDs, set ops, runtime heading vs source heading, source/runtime disagreement, custom tables outside `$SPYGLASS_SRC` | [feedback_loops.md § Tool routing](references/feedback_loops.md#tool-routing-for-relationship-and-lookup-questions) → `db_graph.py` |
| Cross-version comparison or versioned class/table behavior (v0 vs v1, versioned imports/paths, method/signature differences) | [feedback_loops.md § Verify behavior, trust identity](references/feedback_loops.md#verify-behavior-trust-identity) + `code_graph.py describe` / `find-method` / source-read |
| Common Spyglass footguns | [common_mistakes.md](references/common_mistakes.md) |
| Merge tables / `_Merge` methods (`merge_get_part`, `merge_restrict`, `merge_delete`) | [merge_methods.md](references/merge_methods.md) |
| SpyglassMixin helpers (`fetch_nwb`, `cautious_delete`, `<<` / `>>`) | [spyglassmixin_methods.md](references/spyglassmixin_methods.md) |
| Group tables (`*Group`, `create_group()`) | [group_tables.md](references/group_tables.md) |
| NWB ingestion / `insert_sessions` | [ingestion.md](references/ingestion.md) |
| DataJoint query syntax — restrictions, joins, projections, headings, field ownership | [datajoint_api.md](references/datajoint_api.md) |
| Common tables — sessions/files, intervals, electrodes/devices, brain regions, lab/team metadata | [common_tables.md](references/common_tables.md) |
| Spike sorting pipeline (current / v1) | [spikesorting_v1_pipeline.md](references/spikesorting_v1_pipeline.md) |
| Spike sorting analysis (post-pipeline: `SortedSpikesGroup`, `UnitAnnotation`, spike-time/firing-rate helpers) | [spikesorting_v1_analysis.md](references/spikesorting_v1_analysis.md) |
| Spike sorting v0 legacy code / v0 data | [spikesorting_v0_legacy.md](references/spikesorting_v0_legacy.md) |
| Position tracking — overview / merge layer / imported pose | [position_pipeline.md](references/position_pipeline.md) |
| Position tracking — Trodes (LED) | [position_trodes_v1_pipeline.md](references/position_trodes_v1_pipeline.md) |
| Position tracking — DeepLabCut | [position_dlc_v1_pipeline.md](references/position_dlc_v1_pipeline.md) |
| Linearization | [linearization_pipeline.md](references/linearization_pipeline.md) |
| LFP / LFPBand — wideband or bandpass-filtered LFP at any band | [lfp_pipeline.md](references/lfp_pipeline.md) |
| Ripple detection | [ripple_pipeline.md](references/ripple_pipeline.md) |
| Decoding (clusterless / sorted) | [decoding_pipeline.md](references/decoding_pipeline.md) |
| MUA detection | [mua_pipeline.md](references/mua_pipeline.md) |
| MoSeq | [behavior_pipeline.md](references/behavior_pipeline.md) |
| Cross-table workflow recipes after graph/query routing is known | [workflows.md](references/workflows.md) |
| Export for papers / reproducible snapshots | [export.md](references/export.md) |
| Syncing / sharing with collaborators (Kachery) | [setup_config.md § Data Sharing Tables (Kachery)](references/setup_config.md#data-sharing-tables-kachery) |
| Interactive viz / web curation (FigURL) | [figurl.md](references/figurl.md) |
| External packages (SpikeInterface, PyNWB, DLC/DeepLabCut, non_local_detector, MoSeq) | [dependencies.md](references/dependencies.md) |
| Custom authoring decisions — new tables/pipelines, upstream FK choice, side tables, storage pattern | [custom_pipeline_authoring.md](references/custom_pipeline_authoring.md) |
