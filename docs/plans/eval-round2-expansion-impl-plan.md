# Implementation plan — round-2 eval expansion (`skills/spyglass/evals/evals.json`)

**Date:** 2026-04-24 (re-anchored 2026-04-25 after round-3 burned IDs 90–96)
**Status:** **Executed 2026-04-25/04-26.** All 8 batches landed on
`feature/eval-round2-expansion`: pre-reqs (`361c6ba`), Batch A
(`6b9baae` + 3 reviewer rounds), Batch B (`fd80f6d`), Batch C
(`51918fe`), Batch D (`6d66561`), Batch E (`a7141c1`), Batch F
(`e75a3a0`), Batch G (selective: `121` + `123` only — `120` and
`122` deferred per priority), Batch H (`bd022be`). Plus six
multi-batch reviewer-driven correction rounds covering source-
correctness, denial-sensitive forbidden_substrings, grader-hygiene
mismatches, and stale citations across both new and pre-existing
evals. Final eval count: **123** (was 95 → 123, +28; IDs `36`,
`120`, `122` are intentional gaps). Validator clean at
`--baseline-warnings 3`; ruff clean; expectations re-flattened on
every change. Branch is fast-forward mergeable to master.
**Scope:** Add **30 new evals (IDs 97–126)** — was IDs 90–119 in original draft; re-anchored after round-3 expansion (`20d50d0`) consumed 90–96. ID-by-ID remap below; semantic content unchanged. Add **30 new evals (IDs 97–126)** covering topology / dependency reasoning, session-metadata lookups, cross-pipeline compounds, group tables + custom analysis tables, new runtime-debugging failure modes, four new adversarial pushback shapes, and broader coverage in the five categories the maintainer flagged as thin (reference-correctness, parameter-understanding, counterfactual-parameter, hidden-prerequisite, recovery-planning). Land small reference-file and `validate_skill.py` pre-reqs before Phase 1 so new evals don't trip the validator on missing-class warnings. Reuse the existing three-axis taxonomy (stage × tier × difficulty) — no new vocabulary this round.

## Goals and non-goals

**Goals.**

- Add the 10 maintainer-proposed eval situations from the round-2 ask (topology, session recording info, compound, filesystem permissions, `SortedSpikesGroup`, GroupTables-as-concept, custom analysis tables, db locks / `check_threads`, three adversarial shapes — local edits of the Spyglass package, `update1` on params with downstream populated, "store big results as a blob column").
- Widen coverage in the five maintainer-flagged thin categories: reference-correctness / hallucination-resistance, parameter-understanding, counterfactual-parameter, hidden-prerequisite / dependency reasoning, recovery-planning / safest-next-step.
- Keep `./skills/spyglass/scripts/validate_all.sh --baseline-warnings 3` green at every commit. Don't raise the warning baseline; add `required_substrings_exempt` / `expected_output_tables_exempt` entries only where the post-audit rule in [evals/README.md](../../skills/spyglass/evals/README.md#legitimate-exempt-categories-three-buckets) applies, and call the category out in the commit message.
- Keep the `expectations` field in sync with `assertions` by running `python3 scripts/flatten_expectations.py` on every commit that touches eval JSON.

**Non-goals.**

- Reworking the existing taxonomy. The 20-tier / 12-stage / 3-difficulty vocabulary set by [eval-gap-closure-impl-plan.md](eval-gap-closure-impl-plan.md) stays fixed; this round only writes new rows into existing buckets.
- Rewriting already-anonymized prompts. Reuse `j1620210710_.nwb`, `testuser` / `otheruser`, `db.example.test`, `example-lab` per `notes` in `evals.json`.
- Growing the reference surface beyond the six targeted pre-req edits below. Any reference gap surfaced by a new eval that *isn't* in those six lands as a follow-up issue, not inline.
- Skill `description:` re-optimization. New evals don't change triggering boundaries; the skill-creator description loop runs separately when the maintainer chooses.
- New evals scoring infra (e.g. new assertion types). Stay on the three-bucket `required_substrings` / `forbidden_substrings` / `behavioral_checks` shape.

## Executor checklist

A Claude Code agent can execute this plan top-to-bottom. The order below maps 1:1 to the eight commits.

| Step | What | Where | Validation gate |
| --- | --- | --- | --- |
| 0 | Land reference-file + validator pre-reqs | See [Pre-req fixes](#pre-req-fixes) | Validator smoke (no eval JSON change yet) |
| 1 | Batch A — topology / dependency reasoning (6 evals, IDs 90–95) | `evals.json` | Flatten + validator + smoke |
| 2 | Batch B — session metadata lookups (4 evals, IDs 96–99) | `evals.json` | Flatten + validator + smoke |
| 3 | Batch C — cross-pipeline compound (2 evals, IDs 100–101) | `evals.json` | Flatten + validator + smoke + **spot-run** |
| 4 | Batch D — group tables & custom analysis (4 evals, IDs 102–105) | `evals.json` | Flatten + validator + smoke |
| 5 | Batch E — runtime-debugging additions (3 evals, IDs 106–108) | `evals.json` | Flatten + validator + smoke |
| 6 | Batch F — adversarial pushback (4 evals, IDs 109–112) | `evals.json` | Flatten + validator + smoke + **spot-run** |
| 7 | Batch G+H — hallucination-resistance (4) + counterfactual-parameter (3) (7 evals, IDs 113–119) | `evals.json` | Flatten + validator + smoke |

Each step is one commit. Validation gate = the [Per-phase validation](#per-phase-validation) sequence. If a gate fails, **do not** skip hooks or bump `--baseline-warnings`; fix the underlying drift (usually a missing class in `KNOWN_CLASSES`, a bare-word substring, or a stale line-number citation).

## Pre-req fixes

Five source-side gaps surfaced during plan drafting. Each blocks one or more evals downstream; all land in a single pre-req commit *before* Batch A. Message: `references+validator: pre-reqs for round-2 eval expansion`.

### Pre-req 1 — Register missing Common classes in `validate_skill.py`

`KNOWN_CLASSES` in [scripts/validate_skill.py](../../skills/spyglass/scripts/validate_skill.py) is missing seven real classes cited by Batch B and Batch C. Without these, `check_evals_content` will fire false-positive hallucinated-class warnings:

| Class | Source path |
| --- | --- |
| `DataAcquisitionDevice` | `spyglass/common/common_device.py` |
| `Probe` | `spyglass/common/common_device.py` |
| `ProbeType` | `spyglass/common/common_device.py` |
| `CameraDevice` | `spyglass/common/common_device.py` |
| `LabMember` | `spyglass/common/common_lab.py` |
| `LabTeam` | `spyglass/common/common_lab.py` |
| `Institution` | `spyglass/common/common_lab.py` |

Verify each file path against `$SPYGLASS_SRC` before adding (the module layout shifts occasionally when Spyglass is bumped).

### Pre-req 2 — Cross-link `descendants()` / `ancestors()` in `spyglassmixin_methods.md`

[spyglassmixin_methods.md:152](../../skills/spyglass/references/spyglassmixin_methods.md#L152) documents `parents()` / `children()` as a one-liner but silently assumes the reader knows DataJoint's `descendants()` / `ancestors()` for full transitive walks. Batch A eval 91 ("enumerate downstream consumers of `DecodingOutput`") needs a discriminating string that routes to the right method. Fix: under the existing `parents() / children()` heading, add a two-line note pointing to `descendants()` / `ancestors()` (defined on `dj.Table`, inherited by every `SpyglassMixin`) and cross-link to [datajoint_api.md:281](../../skills/spyglass/references/datajoint_api.md#L281). Keep the add under 5 lines; this is a cross-link, not a full section.

### Pre-req 3 — Add a short GroupTables-as-concept section

No reference currently explains GroupTables *as a concept* — they exist via `SortedSpikesGroup` (`decoding_pipeline.md`, `mua_pipeline.md`) and `PositionGroup` (`decoding_pipeline.md`) but never as a category. Batch D evals 103 and 104 both need to route somewhere. Add one H2 section to [custom_pipeline_authoring.md](../../skills/spyglass/references/custom_pipeline_authoring.md) titled **"Group tables (many-to-one aggregation)"**, ~40 lines, covering:

- The three concrete examples in the tree: `SortedSpikesGroup`, `PositionGroup`, `UnitSelectionParams` / `UnitSelection` (units-to-group aggregation inside `SortedSpikesGroup`).
- The shared shape: a Manual/Lookup table with a group-name PK + a part table keyed on upstream merge IDs or selection keys. Downstream consumers (`ClusterlessDecodingSelection`, `SortedSpikesDecodingSelection`, `MuaEventsSelection`) FK to the group, *not* to the individual upstream rows. This is what makes the group reusable across analyses.
- Two-line note: "not the same as merge tables — merge tables wrap interchangeable versions of one analysis; group tables aggregate many rows into one downstream-facing key."

This section is also the landing target for eval 102 ("how do I make it easier to get hippocampal spike data across all sort groups").

### Pre-req 4 — Add short "do not edit the core Spyglass package" note

No reference currently pushes back on "edit the installed Spyglass tables directly." Batch F eval 109 is an adversarial around this. Add one short subsection to [custom_pipeline_authoring.md](../../skills/spyglass/references/custom_pipeline_authoring.md) titled **"Extending without forking the core schema"** (~20 lines) covering:

- Why editing e.g. `DLCPosV1` in the installed source is wrong: the schema declaration is the source of truth for all labs sharing that DB; local edits desync the MySQL schema from `src/spyglass/position/v1/position_dlc_selection.py`, and next `pip install -e .` reverts silently.
- What to do instead: write a new `dj.Computed` table in your own schema module, FK to `DLCPosV1`, and implement the analysis there. Cross-link to [Custom Analysis Tables](../../skills/spyglass/references/custom_pipeline_authoring.md#analysisnwbfile-storage-pattern).
- Two-line note on the narrow legitimate case: a PR upstream to `LorenFrankLab/spyglass`. Not a local edit.

### Pre-req 5 — Add `update1` adversarial note in `destructive_operations.md`

[destructive_operations.md](../../skills/spyglass/references/destructive_operations.md) covers `.delete()` / `super_delete()` / `merge_delete()` but does not pushback on `update1()` against a parameter-table row that already has downstream populated children. Batch F eval 110 is an adversarial around exactly this shape. Add a short subsection titled **"`update1` on params with downstream rows"** (~15 lines) explaining:

- `update1()` silently mutates the row in place. Downstream rows (ripples computed with the *old* threshold) still reference this key by name but now carry stale provenance — same `ripple_params_name` points to a different parameter blob than when the downstream was populated.
- Correct shape: insert a **new** `RippleParameters` row with a different `ripple_params_name` (`tighter_thresh`, etc.), then insert a new `RippleLFPSelection` + populate `RippleTimesV1` for that name. Old rows stay intact and interpretable.
- If truly nothing downstream consumes the row yet, `update1()` is fine, but the check must be explicit: `len(<descendant>() & key)` on each child of `RippleParameters`.

### Pre-req 6 — "Long fetch → `check_threads`" grep-anchor in `runtime_debugging.md`

[runtime_debugging.md:495](../../skills/spyglass/references/runtime_debugging.md#L495) already discusses lock contention but the specific phrase "slow fetch" or "long fetch" doesn't appear. Batch E eval 107 needs a discriminating required substring that maps user-perceived slowness ("taking a really long time to fetch my parameters") to `check_threads`. Add one line to the existing lock-contention subsection: "If a `.fetch()` / `.fetch1()` call hangs with no CPU activity — not slow compute, just *idle* — go straight to `check_threads(detailed=True)`." This is a 1-line add, not a new section.

## Batch specs

Each eval's spec below gives enough to author it directly: target `tier` / `stage` / `difficulty`, the canonical route-to reference, the 1–3 discriminating `required_substrings`, the `forbidden_substrings` that pin the wrong answer, and 1–3 sentence-form `behavioral_checks`. Prompts are written as sketches in realistic user voice (final author should tighten). Apply the existing [substring hygiene](../../skills/spyglass/evals/README.md#substring-hygiene) rules.

**ID re-anchor map (2026-04-25).** Round-3 (`20d50d0`) added new evals at 90–96, so round-2's batches shift downstream:

| Batch | Original IDs | Anchored IDs |
| --- | --- | --- |
| A — topology / dependency / workflow-position / workflow-recovery | 90–95 | 97–102 |
| B — session metadata lookups | 96–99 | 103–106 |
| C — cross-pipeline compound | 100–101 | 107–108 |
| D — group tables & custom analysis | 102–105 | 109–112 |
| E — runtime debugging additions | 106–108 | 113–115 |
| F — adversarial pushback | 109–112 | 116–119 |
| G — hallucination / reference-correctness | 113–116 | 120–123 |
| H — counterfactual parameter | 117–119 | 124–126 |

The batch specs below still use the original IDs; treat each as the anchored ID per this map. (Re-numbering inline would churn cross-references; the map is canonical.)

### Batch A — topology / dependency reasoning (IDs 90–95 → 97–102)

Addresses the maintainer asks: *"What custom tables use data from DecodingOutput?"*, *"Where does tableName get its data from?"*, and the hidden-prerequisite category.

**90. `dependency-downstream-decoding-output`** — tier `dependency-tracing`, stage `framework-concepts`, difficulty `hard`.
- Prompt: "I want to find every custom analysis table in my DB that takes data from `DecodingOutput`. How do I enumerate them?"
- Route: `spyglassmixin_methods.md` (descendants) + `datajoint_api.md`.
- Required: `DecodingOutput`, `descendants(`, `children(`. Forbidden: `parents(` (as the primary method), `fetch_nwb`. Behavioral: "Recommends `DecodingOutput.descendants()` (transitive) over `children()` (one-hop) and explains the distinction"; "Notes that `DecodingOutput` is a merge master, so downstream consumers FK to the master, not to the part tables".

**91. `dependency-abstract-upstream`** — tier `dependency-tracing`, stage `framework-concepts`, difficulty `medium`.
- Prompt: "How do I figure out where a Spyglass table gets its data from? Is there a general way to do this for any table?"
- Route: `spyglassmixin_methods.md` + `datajoint_api.md`.
- Required: `parents(`, `ancestors(`, `.describe()`. Forbidden: `children(` (as the method that answers "where does it come from"). Behavioral: "Distinguishes `parents()` (one hop) from `ancestors()` (transitive)"; "Mentions `.describe()` as the schema-level companion".

**92. `hidden-prereq-ripple-populate`** — tier `dependency-tracing`, stage `pipeline-usage`, difficulty `medium`.
- Prompt: "I'm about to populate `RippleTimesV1` for the first time. What tables must already have entries for my key before `.populate()` will find work to do?"
- Route: `ripple_pipeline.md`.
- Required: `RippleLFPSelection`, `LFPBandV1`, `RippleParameters`, `IntervalList`, `PositionOutput`. Forbidden: `populate_all_common` (wrong abstraction — users don't ingest to populate Ripple). Behavioral: "Enumerates the *selection* tables (RippleLFPSelection) not just the *output* tables"; "Mentions that `PositionOutput` (via `pos_merge_id`) is a hidden FK people miss".

**93. `hidden-prereq-decoding-populate`** — tier `dependency-tracing`, stage `pipeline-usage`, difficulty `hard`.
- Prompt: "Before I can run `ClusterlessDecodingV1.populate()` on a new session, what rows must already exist? I keep hitting `DataJointError: Unknown attribute` and I can't tell what I'm missing."
- Route: `decoding_pipeline.md` + `runtime_debugging.md`.
- Required: `UnitWaveformFeaturesGroup` *or* `PositionGroup` *or* `DecodingParameters` (pick real table names and list at least four), `ClusterlessDecodingSelection`. Forbidden: `populate_all_common` (doesn't populate decoding). Behavioral: "Enumerates upstream groups (PositionGroup + waveform features group) alongside parameters"; "Mentions `Unknown attribute` errors almost always mean a missing FK target, not a schema bug".

**94. `workflow-position-post-sort-ingest`** — tier `workflow-position`, stage `pipeline-usage`, difficulty `medium`.
- Prompt: "I just ran `SpikeSortingV1.populate()` and it finished. What's next in the chain if I want clusterless decoding?"
- Route: `spikesorting_v1_pipeline.md` + `decoding_pipeline.md`.
- Required: `CurationV1`, `SpikeSortingOutput`, `UnitWaveformFeaturesGroup` *or* equivalent, `ClusterlessDecodingSelection`. Behavioral: "Identifies `CurationV1` (initial) as the mandatory next step, not optional"; "Calls out the merge insert into `SpikeSortingOutput` as a separate step".

**95. `recovery-populate-partial-electrodes`** — tier `workflow-recovery`, stage `runtime-debugging`, difficulty `hard`.
- Prompt: "I ran `populate_all_common('j1620210710_.nwb')`. `Session`, `IntervalList`, `Raw`, `Electrode` all populated. But `Probe` has zero rows for this session. The file has tetrode metadata — I checked in HDFView. What's the safe next step?"
- Route: `populate_all_common_debugging.md` + `ingestion.md`.
- Required: `InsertError`, `raise_err=True`, `DataAcquisitionDevice`. Forbidden: `reinsert=True` without a diagnostic step first, `super_delete`. Behavioral: "Inspects `common_usage.InsertError` first rather than re-running blindly"; "Mentions that missing Probe rows often mean an upstream `DataAcquisitionDevice` / `ProbeType` dependency skipped silently".

### Batch B — session metadata lookups (IDs 96–99)

Addresses: *"What ephys recording devices were used in j16…"*, *"Who's animal is wilbur?"*.

**96. `session-recording-devices`** — tier `joins`, stage `pipeline-usage`, difficulty `medium`.
- Prompt: "What ephys recording devices were used in `j1620210710_.nwb`?"
- Route: `common_tables.md`.
- Required: `Session.DataAcquisitionDevice`, `DataAcquisitionDevice`, `nwb_file_name`. Forbidden: `Session.fetch1('device')` (no such shape). Behavioral: "Joins through `Session.DataAcquisitionDevice` (part table) rather than expecting a column on `Session`"; "Mentions that one session can have multiple devices, so `.fetch()` not `.fetch1()`".

**97. `session-subject-owner`** — tier `joins`, stage `pipeline-usage`, difficulty `medium`.
- Prompt: "whose animal is wilbur? i need to figure out which lab member runs the sessions on this subject"
- Route: `common_tables.md`.
- Required: `Subject`, `LabMember`, `Session.Experimenter`, `subject_id`. Forbidden: `Subject.owner` (made-up attr). Behavioral: "Goes via `Session.Experimenter` → `LabMember` rather than assuming a direct `Subject → owner` FK"; "Narrows to one subject_id before joining".

**98. `probe-per-electrode-group`** — tier `atomic-read`, stage `pipeline-usage`, difficulty `easy`.
- Prompt: "For session `j1620210710_.nwb`, which probe model is each electrode group using?"
- Route: `common_tables.md`.
- Required: `ElectrodeGroup`, `Probe`, `probe_id`, `nwb_file_name`. Behavioral: "Restricts both tables by `nwb_file_name` before joining".

**99. `camera-devices-lookup`** — tier `atomic-read`, stage `pipeline-usage`, difficulty `easy`.
- Prompt: "What camera(s) recorded position for `j1620210710_.nwb`? I need the camera IDs for a DLC config."
- Route: `common_tables.md` + `position_pipeline.md`.
- Required: `CameraDevice`, `VideoFile`, `nwb_file_name`. Behavioral: "Routes through `VideoFile` (the per-session mapping), not only the `CameraDevice` lookup".

### Batch C — cross-pipeline compound (IDs 100–101)

Addresses: *"What animals have prefrontal recordings and ran on the wtrack?"* and *"custom table using spikes from all tetrode sort groups."*

**100. `compound-pfc-wtrack`** — tier `compound`, stage `pipeline-usage`, difficulty `hard`.
- Prompt: "I need a list of animals that have prefrontal cortex recordings *and* ran on a w-track. I'm new to the DB."
- Route: `common_tables.md` + `workflows.md`.
- Required: `BrainRegion`, `ElectrodeGroup` *or* `Electrode`, `IntervalList`, `Subject`, `interval_list_name`. Forbidden: `task_name` (no such column on `Session`). Behavioral: "Joins `Electrode` ⋈ `BrainRegion` on `region_name`-ish restriction for PFC, and `IntervalList` on a w-track-like `interval_list_name` substring"; "Aggregates up to `subject_id` with `.proj()` before the final intersection — doesn't return sessions"; "Flags the interval-naming convention as lab-dependent".

**101. `compound-sorted-spikes-across-sort-groups`** — tier `compound`, stage `pipeline-authoring`, difficulty `hard`.
- Prompt: "I want to make a custom table that uses the spikes from all the tetrode sort groups in my data. How do I wire it up so I don't have to list every `sort_group_id` by hand?"
- Route: `custom_pipeline_authoring.md` (new GroupTables section) + `spikesorting_v1_pipeline.md`.
- Required: `SortedSpikesGroup`, `SpikeSortingOutput`, `UnitSelectionParams`. Forbidden: `sort_group_id: blob` (stuffing a list into one column). Behavioral: "Routes to `SortedSpikesGroup` as the existing abstraction; doesn't build a new aggregation from scratch"; "Explains that the downstream custom table FKs to `SortedSpikesGroup`, not to each `SpikeSortingOutput` row individually".

### Batch D — group tables & custom analysis (IDs 102–105)

Addresses: *"how can I make it easier to get all the hippocampal spike data?"*, GroupTables-as-concept, custom analysis tables.

**102. `sorted-spikes-group-hippocampal`** — tier `disambiguation`, stage `pipeline-usage`, difficulty `medium`.
- Prompt: "I'm tired of manually joining across tetrode sort groups every time I want all my hippocampal spikes. How do I make this easier?"
- Route: new GroupTables section in `custom_pipeline_authoring.md` + `spikesorting_v1_pipeline.md`.
- Required: `SortedSpikesGroup`, `UnitSelectionParams`, `BrainRegion`. Forbidden: "just write a function that loops over sort_groups" (missing the DataJoint abstraction). Behavioral: "Recommends creating a `SortedSpikesGroup` restricted to hippocampal tetrodes, inserting a single group row, and FKing downstream analyses to the group name"; "Explains why the group-name key is reusable across analyses".

**103. `group-tables-concept`** — tier `table-classification`, stage `framework-concepts`, difficulty `medium`.
- Prompt: "What is a 'group table' in Spyglass? I see `SortedSpikesGroup`, `PositionGroup`, `UnitSelectionParams` — are those all the same kind of thing? When would I make one of my own?"
- Route: new GroupTables section in `custom_pipeline_authoring.md`.
- Required: `SortedSpikesGroup`, `PositionGroup`, `many-to-one`. Forbidden: `merge_id` (wrong concept — group tables ≠ merge tables). Behavioral: "Distinguishes group tables (many-to-one aggregation) from merge tables (interchangeable versions of one analysis)"; "Lists the shared shape: group-name PK + part table keyed on upstream rows".

**104. `custom-analysis-table-shape`** — tier `atomic-read`, stage `pipeline-authoring`, difficulty `medium`.
- Prompt: "I want to make a custom table that computes cross-correlation of all neuron pairs in a `SortedSpikesGroup`, with one row per group. What's the right shape? Should I store the correlation matrix as a blob column?"
- Route: `custom_pipeline_authoring.md` (AnalysisNwbfile storage pattern).
- Required: `AnalysisNwbfile`, `SpyglassMixin`, `_object_id` *or* `result_object_id`, `dj.Computed`. Forbidden: `correlations: longblob`, `correlations: blob`, "store the correlation matrix as a blob column". Behavioral: "Recommends writing the correlation matrix to an `AnalysisNwbfile` and storing only the `*_object_id` in the DJ row"; "Cites non-negotiable: tables reference exactly one AnalysisNwbfile table".

**105. `custom-table-multiple-nwbs-blob-pushback`** — tier `parameter-semantics`, stage `pipeline-authoring`, difficulty `hard`.
- Prompt: "For the cross-correlation table — if each correlation matrix is only ~5MB, can I just store it inline as a blob? I really don't want to deal with AnalysisNwbfile for this."
- Route: `custom_pipeline_authoring.md`.
- Required: `AnalysisNwbfile`, `Non-Negotiable`, `reproducibility`. Forbidden: `longblob` as the recommended answer, "yes, inline blob is fine at that size". Behavioral: "Pushes back: inline blobs break downstream portability (export, DANDI, Kachery sharing) even when small"; "Mentions that 5 MB × N sessions × N params scales past the practical blob ceiling faster than users expect".

### Batch E — runtime-debugging additions (IDs 106–108)

Addresses: filesystem permissions, DB lock / `check_threads`.

**106. `permission-error-analysis-nwbfile-write`** — tier `runtime-errors`, stage `runtime-debugging`, difficulty `medium`.
- Prompt (paste-style): "traceback from `LFPV1.populate()`: `PermissionError: [Errno 13] Permission denied: '/stelmo/nwb/analysis/j1620210710_/j1620210710_<hash>.nwb'`. other lab members can populate fine. what's going on?"
- Route: `setup_troubleshooting.md` + `setup_config.md`.
- Required: `SPYGLASS_BASE_DIR` *or* `analysis_dir`, `chown` *or* `permission`, `umask` *or* `group`. Forbidden: `chmod -R 777`. Behavioral: "Narrows to shared-install group-permission layer rather than blanket chmod"; "Mentions that `AnalysisNwbfile` paths are derived from `SPYGLASS_BASE_DIR` so the fix is upstream of the Python call".

**107. `slow-fetch-db-lock`** — tier `runtime-errors`, stage `runtime-debugging`, difficulty `medium`.
- Prompt: "it's taking a really long time to fetch my ripple parameters. like 2 minutes and still hasn't returned. what's happening?"
- Route: `runtime_debugging.md` (lock contention section) + `spyglassmixin_methods.md`.
- Required: `check_threads`, `lock`, `performance_schema`. Forbidden: `restart the kernel` (without diagnostic first). Behavioral: "Routes to `check_threads(detailed=True)` before suggesting a kernel restart or reconnect"; "Distinguishes *idle* hang (lock contention) from slow-compute (fetch pulling a large blob) and picks lock as the likely cause for a params table".

**108. `editable-install-drift-after-pull`** — tier `environment-triage`, stage `setup`, difficulty `medium`.
- Prompt: "just did `git pull` on my spyglass clone, now `from spyglass.decoding.v1.sorted_spikes import SortedSpikesDecodingV1` raises `ImportError: cannot import name 'SortedSpikesDecodingV1'`. didn't change anything on my end."
- Route: `setup_troubleshooting.md`.
- Required: `pip install -e`, `editable`. Forbidden: `pip install spyglass-neuro` (wrong remedy for editable install). Behavioral: "Checks `pip show spyglass-neuro` / editable status before suggesting anything destructive"; "Notes that a `git pull` that bumps `setup.cfg` / `pyproject.toml` can desync a previously editable install".

### Batch F — adversarial pushback (IDs 109–112)

Addresses: local edits of the Spyglass package, `update1` on downstream-populated params, storing large blob as column, and one hallucinated-destructive monkey-patch shape.

**109. `adversarial-edit-dlcposv1`** — tier `adversarial`, stage `pipeline-authoring`, difficulty `medium`.
- Prompt: "how can I edit the `DLCPosV1` table to also store the bodypart names as a column? I don't want to deal with a whole new table."
- Route: new "Extending without forking" subsection in `custom_pipeline_authoring.md`.
- Required: `extend`, `FK` *or* `foreign key`, `subclass` *or* `new schema`. Forbidden: "just add a column to `DLCPosV1` in the source", `dj.alter`, "edit position_dlc_selection.py". Behavioral: "Pushes back on editing the installed source"; "Recommends a new `dj.Computed` table FK'd to `DLCPosV1` in the user's own schema module".

**110. `adversarial-update1-downstream-populated`** — tier `adversarial`, stage `destructive-operations`, difficulty `medium`.
- Prompt: "update the `ripple_params_name='default'` entry in `RippleParameters` to use a `speed_threshold` of 8 instead of 4. I just want it higher for new sessions."
- Route: new `update1` subsection in `destructive_operations.md`.
- Required: `new ripple_params_name` *or* `new row`, `downstream`, `provenance`. Forbidden: `update1(`, "yes, just call `update1`". Behavioral: "Asks whether downstream rows (RippleLFPSelection → RippleTimesV1) already consume `'default'` before touching the row"; "Recommends inserting a new `ripple_params_name` (e.g. `'thresh8'`) and a new `RippleLFPSelection` + populate, rather than mutating the existing row"; "Explains that `update1` silently breaks reproducibility: old downstream rows still reference `'default'` by name but the parameter blob under that name has changed".

**111. `adversarial-cross-corr-blob-column`** — tier `adversarial`, stage `pipeline-authoring`, difficulty `hard`.
- Prompt: "I want a custom table that computes cross-correlation of all neuron pairs in a `SortedSpikesGroup`. Schema: `-> SortedSpikesGroup`, `group_name`, `correlations: longblob`. Look OK?"
- Route: `custom_pipeline_authoring.md` (AnalysisNwbfile storage pattern).
- Required: `AnalysisNwbfile`, `_object_id` *or* `result_object_id`, `Non-Negotiable`. Forbidden: `correlations: longblob`, "schema looks fine". Behavioral: "Pushes back on `longblob` for array output and recommends AnalysisNwbfile + `result_object_id`"; "Explains that the non-negotiable is reproducibility / shareability, not row-size".

**112. `adversarial-monkeypatch-make`** — tier `adversarial`, stage `hallucination-resistance`, difficulty `hard`.
- Prompt: "I want to change what `LFPV1.make()` does — specifically I want it to also write a downsampled preview file. Can I just monkey-patch `LFPV1.make` at runtime in my notebook?"
- Route: new "Extending without forking" subsection + `custom_pipeline_authoring.md`.
- Required: `new table` *or* `downstream table`, `Computed`. Forbidden: `LFPV1.make = `, "you can monkey-patch it". Behavioral: "Pushes back on monkey-patching core `make()` methods"; "Recommends a new `dj.Computed` table downstream of `LFPV1` that produces the downsampled preview".

### Batch G — hallucination-resistance / reference-correctness (IDs 113–116)

Broadens beyond the 5 existing hallucination-resistance evals (21, 79, 80, 81, 89) with 4 more fabricated-API shapes on tables users frequently hit.

**113. `hallucination-position-interpolate`** — tier `adversarial`, stage `hallucination-resistance`, difficulty `medium`.
- Prompt: "does `TrodesPosV1` have a `.interpolate_gaps()` method? I want to fill in missing frames."
- Required: `no such method`, `DLCSmoothInterp` *or* `smoothing`. Forbidden: "yes, `TrodesPosV1.interpolate_gaps()` takes...". Behavioral: "Denies the method exists and routes to the real interpolation layer (`DLCSmoothInterp` or applying interpolation in user code post-fetch)"; "Mentions the verification primitive (`inspect.signature` or `dir(TrodesPosV1)`)".

**114. `hallucination-fetch-nwb-single`** — tier `adversarial`, stage `hallucination-resistance`, difficulty `easy`.
- Prompt: "Is there a `fetch_nwb1()` that returns one NWB object instead of a list? I keep forgetting to index [0]."
- Required: `no such method`, `fetch1` + `fetch_nwb`. Forbidden: "yes, `fetch_nwb1()` returns a single object". Behavioral: "Denies the method exists"; "Explains that `fetch_nwb()` on a restriction returning one row still gives a list-of-one; users index `[0]` or restrict with `&` + `fetch1('KEY')` upstream first".

**115. `hallucination-ripple-recompute`** — tier `adversarial`, stage `hallucination-resistance`, difficulty `medium`.
- Prompt: "can I call `RippleTimesV1.recompute(key)` to just redo one row without going through populate?"
- Required: `no such method`, `.delete()` + `.populate(`. Forbidden: "yes, `recompute(key)` is shorthand for...". Behavioral: "Denies the method exists"; "Explains the canonical recompute shape: delete the row then re-populate (or use `populate(..., reserve_jobs=True)`)".

**116. `hallucination-spyglass-compact`** — tier `adversarial`, stage `hallucination-resistance`, difficulty `medium`.
- Prompt: "I read about a `spyglass.compact()` or maybe `dj.compact()` function that removes orphaned analysis files. What's the exact call?"
- Required: `no such function`, `delete_orphans`, `AnalysisNwbfile`. Forbidden: "yes, `spyglass.compact()` cleans up...". Behavioral: "Denies the top-level function exists"; "Routes to `AnalysisNwbfile().delete_orphans(dry_run=True)` as the real cleanup primitive, with the `dry_run` gate emphasized".

### Batch H — counterfactual-parameter (IDs 117–119)

Current `counterfactual` tier has 4 evals, one of which (eval 68) is a parameter-proximal change. Add 3 more in the pure-parameter direction the maintainer called out.

**117. `counterfactual-ripple-threshold`** — tier `counterfactual`, stage `parameter-understanding`, difficulty `hard`.
- Prompt: "If I change `ripple_params.zscore_threshold` from 2 to 3 and re-populate `RippleTimesV1`, which downstream rows will differ?"
- Route: `ripple_pipeline.md` + `destructive_operations.md` (`update1` note).
- Required: `RippleTimesV1`, `new ripple_params_name` *or* `new row`, `RippleLFPSelection`. Forbidden: "call `update1` on the existing row". Behavioral: "Recommends inserting a new `RippleParameters` row + new selection, not mutating the existing one"; "Enumerates downstream: anything FK'd to `RippleTimesV1` would re-populate under the new params name; old rows untouched".

**118. `counterfactual-sort-interval-change`** — tier `counterfactual`, stage `parameter-understanding`, difficulty `hard`.
- Prompt: "If I shorten the `sort_interval` on one `SpikeSortingRecordingSelection` row to half its original length, which downstream rows change? Can the old curation still be reused?"
- Route: `spikesorting_v1_pipeline.md`.
- Required: `SpikeSortingRecording`, `SpikeSorting`, `CurationV1`, `new recording_id` *or* `new row`. Forbidden: "yes, the old curation still applies". Behavioral: "Recognizes that changing `sort_interval` produces a different recording hash → new `recording_id` → old `CurationV1` rows pin the old recording and cannot transfer"; "Recommends inserting as a new selection rather than editing the existing row".

**119. `counterfactual-decoding-bin-size`** — tier `counterfactual`, stage `parameter-understanding`, difficulty `hard`.
- Prompt: "If I change `DecodingParameters.position_bin_size` from 2 cm to 5 cm, what downstream rows change? I only care about the decoding posterior, not upstream."
- Route: `decoding_pipeline.md`.
- Required: `DecodingParameters`, `ClusterlessDecodingV1` *or* `SortedSpikesDecodingV1`, `new decoding_param_name`. Forbidden: "spike sorting re-runs", "LFP re-runs". Behavioral: "Correctly identifies that only the decoding output changes; spike sorting and position upstream are unaffected"; "Recommends new `decoding_param_name` over `update1`".

## Per-phase validation

Run on every commit that touches `evals.json` (the pre-req commit only runs the validator, no flatten):

```bash
# Always run first — keeps expectations in sync with assertions
python3 skills/spyglass/evals/scripts/flatten_expectations.py

# JSON parse smoke
python3 -c 'import json; json.load(open("skills/spyglass/evals/evals.json"))'

# Main gate — exit status gates the commit
./skills/spyglass/scripts/validate_all.sh --baseline-warnings 3
```

If `validate_all.sh` warns above baseline, **diagnose before silencing**:

- Bare-word or literal-format warning → tighten the substring (`"group"` → `"group_name"`, `` "`Raw`" `` → `"Raw table"`), don't add to `required_substrings_exempt` unless the substring really is a discriminating domain term.
- Completeness warning → the `expected_output` names a class that no `required_substring` contains; add the class to `required_substrings` (preferred) or, if it's a prose distractor / contrast table / rare-term false positive per the three exempt categories in [evals/README.md](../../skills/spyglass/evals/README.md#legitimate-exempt-categories-three-buckets), add to `expected_output_tables_exempt` with a one-line rationale in the commit message.
- Missing-class warning → add to `KNOWN_CLASSES` in `validate_skill.py` if the class is real (verify against `$SPYGLASS_SRC`); otherwise fix the eval.

**Spot-run gates (steps 3 and 6).** After Batch C and Batch F, run the skill against one new eval from that batch end-to-end in a fresh Claude Code session (no conversation history) and confirm the response hits the `required_substrings` and avoids the `forbidden_substrings`. Spot-runs catch "the eval passes the validator but the skill can't actually answer it" drift — most common cause: the required substring only appears in the SKILL.md routing line, not in the reference the answer pulls from.

## Rollout

- Land all eight commits on a single topic branch, e.g. `evals/round2-expansion`. Open one PR for review; don't split by batch.
- Before merging, re-check `--baseline-warnings 3` on the tip commit. The existing baseline is 3 and stays 3 — any new warning accumulated across batches has to be resolved, not deferred.
- After merge, run the full skill-creator benchmark against the new evals as a separate (unscoped) follow-up. This plan does not include a benchmark run because the current three-bucket assertion shape is grep-scorable and the main goal is permanent-regression pinning, not a one-shot benchmark score.
- Follow-ups (out of scope, track as separate issues): (a) reference-side gaps surfaced by new evals beyond the six pre-reqs, (b) extending `KNOWN_CLASSES` with any additional real classes cited by reference edits during Pre-req 3 / 4 / 5, (c) skill `description:` re-run via skill-creator's `run_loop.py` if benchmark shows trigger-miss regressions on new adversarial evals.
