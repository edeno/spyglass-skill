# Spyglass — Agent Rules

Portable guidance for any AI coding agent that loads a single top-level
rules file (OpenAI Codex CLI, Cursor, Aider, etc.). This is the flat
equivalent of the Claude Code skill published at
[github.com/edeno/spyglass-skill](https://github.com/edeno/spyglass-skill).

**How to use this file.** Copy `AGENTS.md` (or `GEMINI.md` — same
content) into the root of a project where you're analyzing Spyglass
data. Most modern coding agents auto-detect these filenames and load
the content into context on session start. Deep-dive references live
in the linked GitHub files; your agent can fetch them on demand, or
you can clone
[edeno/spyglass-skill](https://github.com/edeno/spyglass-skill)
alongside your project for offline access.

**Scope.** This file covers Spyglass — the LorenFrankLab neurophysiology
framework built on DataJoint + NWB: setup, NWB ingestion, pipelines
(spike sorting, LFP, ripple, decoding, position, linearization, DLC),
merge tables, paper exports (DANDI / FigURL / Kachery), custom
pipelines, and debugging `populate` / `make` / `fetch1` failures.

Engage this guidance when the user's task involves `import spyglass` /
`from spyglass.*`, `SPYGLASS_BASE_DIR`, `SpyglassMixin`,
`merge_get_part`, `merge_restrict`, V1 pipeline classes (`LFPV1`,
`TrodesPosV1`, `DLCPosV1`, `RippleTimesV1`, `SpikeSortingV1`,
`CurationV1`, `ClusterlessDecodingV1`, `SortedSpikesDecodingV1`), or
DLC / DANDI / Kachery within a Spyglass context — even if the user
doesn't name "Spyglass" explicitly.

**Don't engage** for plain DataJoint without Spyglass imports,
unrelated NWB tooling (pynwb, ndx-*) outside Spyglass, or generic
Python / NumPy / pandas debugging when no Spyglass table is in the
call chain.

---

## Core Directives

- **NEVER delete or drop without explicit confirmation.** The database
  holds irreplaceable neuroscience data. Any destructive helper
  (`delete`, `drop`, `cleanup`, `merge_delete`, etc.) must be paired
  with an inspect step and user confirmation first. `.delete()` on
  `SpyglassMixin` tables aliases to `cautious_delete` — it enforces
  team-based permissions so you can't accidentally delete another lab
  member's sessions. Paired shapes + protection model:
  [destructive_operations.md](https://github.com/edeno/spyglass-skill/blob/master/skills/spyglass/references/destructive_operations.md).

- **Do not invent identifiers.** Plausible method, kwarg, field, and
  table names are the most common hallucination shape here — they fail
  with `AttributeError`, `TypeError`, or `DataJointError: unknown
  attribute`. Verify before asserting: grep the source,
  `inspect.signature`, or `Table.heading`. If unverifiable, flag as
  unconfirmed. Real examples: Common Mistake #8 in
  [common_mistakes.md](https://github.com/edeno/spyglass-skill/blob/master/skills/spyglass/references/common_mistakes.md).

- **Writes are normal workflow.** Pipelines depend on selection
  inserts and `populate()` — show the full flow; don't refuse or hedge
  on the writes.

- **Verify cardinality before `fetch1()`, `merge_get_part()`, or
  `fetch1_dataframe()`** on any table, including well-known ones. Use
  `print(len(rel))`; if >1, inspect with `rel.fetch(as_dict=True)` or
  `merge_restrict` to see which PK fields still need narrowing.
  `Table.describe()` / `Table.heading` show schema, not row count.
  See Common Mistake #2.

- **Environment**: detect the user's setup (local Docker, local data,
  remote lab) — don't assume Jupyter or remote NWB.

- **Reading DataJoint config files**: `dj_local_conf.json` /
  `~/.datajoint_config.json` may hold `database.password` in plaintext.
  Never `cat` raw — use the scrubbed-read pattern in
  [setup_config.md](https://github.com/edeno/spyglass-skill/blob/master/skills/spyglass/references/setup_config.md).

- **Source of truth**: when this file and the repo disagree, trust the
  repo. Cited paths use the GitHub layout (`src/spyglass/...`); in pip
  installs, drop `src/` — locate via
  `python -c "import spyglass, os; print(os.path.dirname(spyglass.__file__))"`.
  Tutorials at `notebooks/*.ipynb` (cite the `.ipynb`, not the
  `py_scripts/` jupytext mirror). Tutorials drift; when a cell fails
  on a missing parameter, table, or column, treat it as stale and
  check the source tree.

## Common Mistakes

Top 5 highest-frequency bugs. Flag any of these shapes before
answering. Three more footguns plus expanded prose + fixes:
[common_mistakes.md](https://github.com/edeno/spyglass-skill/blob/master/skills/spyglass/references/common_mistakes.md)
(8 entries total).

1. **Classmethod restriction discard on merge tables** —
   `(PositionOutput & merge_key).merge_delete()` drops the
   `& merge_key`; use `PositionOutput.merge_delete(merge_key)`.
   Affected methods:
   [merge_and_mixin_methods.md](https://github.com/edeno/spyglass-skill/blob/master/skills/spyglass/references/merge_and_mixin_methods.md).
2. **Too-loose restriction + `fetch1()`** —
   `{"nwb_file_name": f}` matches many rows; add PK fields until
   `len(rel) == 1`.
3. **`skip_duplicates=True` on `insert_sessions`** — raises
   `TypeError`; use `reinsert=True` for re-ingestion.
4. **`fetch_nwb()` silently returns a list** on multiple matches
   (unlike `fetch1()`) — restrict to one row before `[0]`-indexing.
5. **Bypassing `cautious_delete` to silence a `PermissionError`** —
   `.delete()` is team-gated; the error means another lab member owns
   the session. Coordinate with them, don't reach for `super_delete()`
   or `force_permission=True`. Protection model + inspect-before-
   destroy:
   [destructive_operations.md](https://github.com/edeno/spyglass-skill/blob/master/skills/spyglass/references/destructive_operations.md).

## Feedback Loops

Quality-critical operations use a validator → fix → proceed shape.
Four loops cover the highest-friction points: post-ingestion
verification, pre-`fetch1` cardinality check, post-`populate`
verification, and inspect-before-destroy. Full patterns with code:
[feedback_loops.md](https://github.com/edeno/spyglass-skill/blob/master/skills/spyglass/references/feedback_loops.md).

## Classify the User's Stage

Stages orient you to *what the user is doing*; the Reference Routing
table below resolves *what they're asking about*. Use stages for vague
questions; use the routing table when the topic is clear.

1. **Setup / install** → `scripts/install.py` is the canonical fast
   path per `QUICKSTART.md`. Route to
   [setup_install.md](https://github.com/edeno/spyglass-skill/blob/master/skills/spyglass/references/setup_install.md),
   [setup_config.md](https://github.com/edeno/spyglass-skill/blob/master/skills/spyglass/references/setup_config.md),
   or
   [setup_troubleshooting.md](https://github.com/edeno/spyglass-skill/blob/master/skills/spyglass/references/setup_troubleshooting.md).
   `00_Setup.ipynb` is a manual fallback.
2. **NWB ingestion** (first data load) →
   [ingestion.md](https://github.com/edeno/spyglass-skill/blob/master/skills/spyglass/references/ingestion.md)
   + `02_Insert_Data.ipynb`.
3. **Framework concepts** (first time using Spyglass) →
   [merge_and_mixin_methods.md](https://github.com/edeno/spyglass-skill/blob/master/skills/spyglass/references/merge_and_mixin_methods.md)
   + `01_Concepts.ipynb`. `04_Merge_Tables.ipynb` is a later,
   specialized concept — don't lead with it for novice questions.
4. **Pipeline usage** (running or querying existing analyses) →
   pipeline reference files in the table below.
5. **Pipeline authoring** (extending a pipeline, writing schema
   modules) →
   [custom_pipeline_authoring.md](https://github.com/edeno/spyglass-skill/blob/master/skills/spyglass/references/custom_pipeline_authoring.md).
   Different from usage.
6. **Runtime debugging / traceback triage** (populate / make / fetch1
   failures, join multiplicity, one-key-fails, NumPy / pandas bugs
   inside `make()`) →
   [runtime_debugging.md](https://github.com/edeno/spyglass-skill/blob/master/skills/spyglass/references/runtime_debugging.md).
   Install / config / connection errors go to
   [setup_troubleshooting.md](https://github.com/edeno/spyglass-skill/blob/master/skills/spyglass/references/setup_troubleshooting.md)
   instead.

Users may span stages. Infer from the question and any imports / table
names in context — don't halt to ask unless (a) the answer would
change materially (pipeline usage vs. authoring), or (b) the next step
is destructive and intent is ambiguous.

## Merge Tables

Two phases: **inspect** with `MergeTable & key` or `merge_restrict`
(SQL only), then **load** with `merge_get_part` → `fetch1_dataframe`
(disk read; cardinality-check first). Full pattern, including the
`fetch_results` decoding-only footgun:
[merge_and_mixin_methods.md](https://github.com/edeno/spyglass-skill/blob/master/skills/spyglass/references/merge_and_mixin_methods.md).

## Querying an Already-Configured DB

If the user hasn't installed or configured Spyglass yet, route to
[setup_install.md](https://github.com/edeno/spyglass-skill/blob/master/skills/spyglass/references/setup_install.md).
For a working install:

```python
from spyglass.common import Session, IntervalList

Session.fetch(limit=10)                      # discover an nwb_file_name
IntervalList & {"nwb_file_name": nwb_file}   # discover intervals for it
```

From here, open the relevant pipeline reference — each starts with a
Canonical Example. Don't expand the full workflow inline.

## Reference Routing

**For deep-dives, open ONE reference at a time.** Pick the single most
relevant row. Only open a second reference if the first doesn't cover
the question. Don't pre-load several "to be safe" — it wastes context.

Repo paths (source, docs) are listed in each reference file — this
table routes by topic, not by path.

Base URL for all references:
`https://github.com/edeno/spyglass-skill/blob/master/skills/spyglass/references/`

| User question is about... | Reference file | Canonical notebook |
| ------------------------- | -------------- | ------------------ |
| Installing Spyglass | `setup_install.md` | `QUICKSTART.md` + `scripts/install.py`; `00_Setup.ipynb` fallback |
| Configuring the database / directories / env vars | `setup_config.md` | `00_Setup.ipynb` |
| Setup errors and troubleshooting | `setup_troubleshooting.md` | — |
| Runtime debugging — populate / make failures, fetch1 cardinality, ambiguous-truth, join multiplicity, one-key-fails | `runtime_debugging.md` | — |
| `populate_all_common` silently skipped tables | `populate_all_common_debugging.md` | — |
| Destructive operations — deletes, cleanup, inspect-before-destroy patterns | `destructive_operations.md` | — |
| Validator → fix → proceed loops — post-ingest, pre-fetch1, post-populate, inspect-before-destroy | `feedback_loops.md` | — |
| Expanded prose on the most common Spyglass footguns (8 entries) | `common_mistakes.md` | — |
| Framework concepts / merge tables | `merge_and_mixin_methods.md` | `01_Concepts.ipynb`, `04_Merge_Tables.ipynb` |
| NWB ingestion / insert_sessions | `ingestion.md` | `02_Insert_Data.ipynb` |
| DataJoint query syntax | `datajoint_api.md` | — |
| Session, IntervalList, Electrode tables | `common_tables.md` | — |
| Spike sorting pipeline (current / v1) | `spikesorting_pipeline.md` | `10_Spike_SortingV1.ipynb`, `11_Spike_Sorting_Analysis.ipynb` |
| Reading v0 legacy code / v0 data | `spikesorting_v0_legacy.md` | `10_Spike_SortingV0.ipynb` |
| Position tracking (Trodes / DLC) | `position_pipeline.md` | `20_Position_Trodes.ipynb`, `21_DLC.ipynb` |
| Linearization | `linearization_pipeline.md` | `24_Linearization.ipynb` |
| LFP / theta | `lfp_pipeline.md` | `30_LFP.ipynb`, `31_Theta.ipynb` |
| Ripple detection | `ripple_pipeline.md` | `32_Ripple_Detection.ipynb` |
| Decoding (clusterless / sorted) | `decoding_pipeline.md` | `40_Extracting_Clusterless_Waveform_Features.ipynb`, `41_Decoding_Clusterless.ipynb`, `42_Decoding_SortedSpikes.ipynb` |
| MUA detection | `mua_pipeline.md` | `50_MUA_Detection.ipynb` |
| Behavior / MoSeq | `behavior_pipeline.md` | `60_MoSeq.ipynb` |
| Cross-table exploration / troubleshooting | `workflows.md` | — |
| Export for papers / reproducible snapshots | `export.md` | `05_Export.ipynb` |
| Syncing / sharing with collaborators (Kachery) | `setup_config.md` — "Data Sharing Tables (Kachery)" | `03_Data_Sync.ipynb` |
| Interactive viz / web curation (FigURL) | `figurl.md` | — |
| External packages (SI, PyNWB, DLC) | `dependencies.md` | — |
| Authoring a new pipeline / extending an existing one | `custom_pipeline_authoring.md` | — |
