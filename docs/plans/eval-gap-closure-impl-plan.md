# Implementation plan — close eval gaps in `skills/spyglass/evals/evals.json`

**Date:** 2026-04-23
**Status:** **Executed 2026-04-23.** All 25 target evals (IDs 54–78) landed across five phased commit batches: Phase A `bdc0c78` + `872f129` (table-understanding 54–57), Phase B `0b4cbb4` + `401218c` (parameter-understanding 58–62), Phase C `b7fd73f` + `97ee1ce` (disambiguation/counterfactual/resource-selection/workflow-position/dependency-tracing 63–73), Phase C' `5339e01` (schema-introspection 74–78), Phase D `e088d79` (anonymize evals 1–53). Follow-on hygiene work — `5b8b9b7`, `58871ba`, `696e4bc`, `ca2c041`, `6fe2beb` — resolved ~174 substring-hygiene + completeness warnings down to the current baseline of 3. Taxonomy vocabulary agreed and applied.
**Scope:** Add 25 new evals (IDs 54–78) covering nine under-served capability categories (eight gap categories + a new schema-introspection batch). Establish a single agreed-upon classification vocabulary (stages × tiers × difficulty) and apply it to existing evals 1–53. Retro-anonymize hostnames / usernames / lab names in existing prompts.

## Goals and non-goals

**Goals.**

- Close the eight gap categories surfaced in the prior audit. Priority: **table understanding** and **parameter understanding**; remaining six follow. A ninth small batch (`schema-introspection`) is added based on a candidate question set surfaced during planning.
- Produce one canonical taxonomy of `stage`, `tier`, and `difficulty` values that every eval — old and new — is tagged with, so benchmark slicing is consistent across all three axes.
- Re-tag existing evals where their current `stage` / `tier` no longer fits the canonical vocabulary; add the `difficulty` field to all 53 existing evals.
- Anonymize lab-identifying strings (`franklab.ucsf.edu`, `edeno`, lab-specific hostnames) in existing evals, replacing with `db.example.test`, `testuser`, `example-lab`.
- Keep `skills/spyglass/scripts/validate_all.sh --baseline-warnings 3` green at every commit.

**Non-goals.**

- Editing reference files **except** the two pre-req fixes called out in [Pre-req fixes](#pre-req-fixes-landed-before-phase-1) below. Other reference-side gaps the new evals expose are out of scope; track separately.
- Skill `description:` re-optimization. The new evals don't change triggering boundaries.
- New scoring infrastructure. Stay on the existing three-bucket assertion shape (`required_substrings`, `forbidden_substrings`, `behavioral_checks`).
- Re-anchoring evals away from the canonical session ID `j1620210710_.nwb`. It's an established fixture, not a lab identifier per se.

## Executor checklist

A Claude Code agent can execute this plan top-to-bottom. The order below maps 1:1 to the seven commits.

| Step | What | Where | Validation gate |
| --- | --- | --- | --- |
| 0 | Apply pre-req fixes (Electrode PK in [common_tables.md](../../skills/spyglass/references/common_tables.md), three classes in [validate_skill.py](../../skills/spyglass/scripts/validate_skill.py)) | See [Pre-req fixes](#pre-req-fixes-landed-before-phase-1). **Already applied to working tree as of plan-review pass; verify with `git diff` and commit.** | Validator + smoke check |
| 1 | Add `difficulty` field to all 53 existing evals; apply 4 re-tags from [Re-tags](#re-tags-4-evals); update [evals/README.md](../../skills/spyglass/evals/README.md) per [`evals/README.md` updates](#evalsreadmemd-updates-land-in-commit-1) | `evals.json` + `evals/README.md` | flatten + validator + smoke |
| 2 | Insert evals 54–57 (Phase A — table understanding) | `evals.json` | flatten + validator + smoke |
| 3 | Insert evals 58–62 (Phase B — parameter understanding) | `evals.json` | flatten + validator + smoke + **spot-run after this commit** |
| 4 | Insert evals 63–73 (Phase C — disambiguation, counterfactual, resource-selection, workflow-position, dependency-tracing) | `evals.json` | flatten + validator + smoke |
| 5 | Insert evals 74–78 (Phase C' — schema-introspection) | `evals.json` | flatten + validator + smoke |
| 6 | Anonymize evals 1–53 per Phase D below | `evals.json` | flatten + validator + smoke + post-anonymization substring re-check |

Each step is one commit. The "validation gate" column is the [Per-phase validation](#per-phase-validation) sequence plus the [Pre-commit smoke check](#pre-commit-smoke-check). Per-eval authoring uses [How to write a new eval](#how-to-write-a-new-eval-executor-reference).

If any step's validation fails, **do not skip hooks or bump baselines** — fix the underlying drift. See [Validator warning baseline](#validator-warning-baseline) for the warning policy.

## Pre-req fixes (landed before Phase 1)

Two source-of-truth bugs surfaced during plan review. Both must land in a pre-req commit *before* the vocabulary commit, so downstream evals don't reference broken state.

### Pre-req 1 — Fix `common_tables.md` Electrode PK

[skills/spyglass/references/common_tables.md:144](../../skills/spyglass/references/common_tables.md#L144) documents the `Electrode` PK as `nwb_file_name, electrode_id`. Source-of-truth ([spyglass/common/common_ephys.py:75](../../../spyglass/src/spyglass/common/common_ephys.py)) shows `Electrode` inherits from `ElectrodeGroup` (PK `nwb_file_name, electrode_group_name`) and adds its own `electrode_id`, so the actual PK is `nwb_file_name, electrode_group_name, electrode_id`. Fix the reference to list all three fields. Eval 74 depends on this.

### Pre-req 2 — Register three Selection classes in `validate_skill.py`

`KNOWN_CLASSES` in [scripts/validate_skill.py](../../skills/spyglass/scripts/validate_skill.py) is missing three real classes that new evals 71 and 72 cite:

| Class | Source path |
| --- | --- |
| `DLCPoseEstimationSelection` | `spyglass/position/v1/position_dlc_pose_estimation.py` |
| `DLCSmoothInterpSelection` | `spyglass/position/v1/position_dlc_position.py` |
| `ClusterlessDecodingSelection` | `spyglass/decoding/v1/clusterless.py` |

Without these, the validator's `check_evals_content` will fire false-positive hallucinated-class warnings on the new evals.

### Pre-req commit

Single commit, message: `references: fix Electrode PK; validator: register three Selection classes`. Validator + flatten-expectations check are no-ops here (no eval JSON change yet) — but run them anyway as a smoke test.

## Canonical classification vocabulary

Three orthogonal axes (extending the two-axis scheme already in [evals/README.md](../../skills/spyglass/evals/README.md)): **stage** = workflow phase (topic), **tier** = capability kind, **difficulty** = cognitive load. Every eval gets exactly one value on each axis. Three axes give 12 × 18 × 3 = 648 buckets in principle, but in practice clusters: a `pipeline-usage` / `atomic-read` eval is almost always `easy`; a `pipeline-usage` / `dependency-tracing` eval is almost always `hard`. The combinations matter for slicing benchmarks ("easy parameter-semantics" vs "hard parameter-semantics" can flag whether the skill collapses on harder reasoning).

### Stages (12)

| Stage | Definition |
| --- | --- |
| `setup` | Install, env vars, DataJoint config, permissions, environment drift. |
| `ingestion` | Loading NWB into Spyglass tables; first-touch validation. |
| `pipeline-usage` | Running or querying an existing pipeline end-to-end. |
| `pipeline-authoring` | Writing or extending a pipeline schema (custom tables, merge parts). |
| `framework-concepts` | DataJoint-layer abstractions (table tiers, blob vs external, merge mechanics) treated conceptually. |
| `runtime-debugging` | Triaging an error that already happened (traceback in hand). |
| `common-mistakes` | Patterns documented in [common_mistakes.md](../../skills/spyglass/references/common_mistakes.md). |
| `destructive-operations` | Delete / drop / cleanup; pushback expected when bypass is requested. |
| `non-activation` | Out-of-scope questions; skill should stay silent. |
| `hallucination-resistance` | Made-up API in the prompt; correct answer is "doesn't exist." |
| `table-understanding` *(new)* | Questions about what a table *is* (tier, role, what it stores, relationship to its merge). |
| `parameter-understanding` *(new)* | Questions about what a specific parameter *controls* and downstream consequences. |

### Tiers (18)

| Tier | Definition |
| --- | --- |
| `baseline` | Skill activation + correct routing on canonical happy-path questions. |
| `atomic-read` | Single-table fetch by PK or restricted scan. |
| `merge-key-discovery` | Resolve a `merge_id` from upstream selectors. |
| `joins` | Compose across 2+ tables. |
| `compound` | Multi-reference handoffs; answer draws on 3+ reference files. |
| `adversarial` | Pushback / non-activation / hallucination resistance. |
| `post-ingest-validation` | Verify what made it into tables after a "successful" ingest. |
| `merge-table-gotchas` | Merge-specific failure modes beyond key discovery. |
| `runtime-errors` | Real tracebacks from `populate()` / `make()` / `fetch1()`. |
| `environment-triage` | Install-level failures (env drift, conda/pip conflicts, editable-install staleness). |
| `config-troubleshooting` | Config-level failures (`dj.config`, Kachery creds, permissions). |
| `table-classification` *(new)* | Name a table's DataJoint tier (Manual / Lookup / Computed / Imported / Part) and its Spyglass role (selection / parameter / compute / output / merge); justify. |
| `parameter-semantics` *(new)* | Explain what a specific parameter controls; predict downstream effect of changing it. |
| `disambiguation` *(new)* | Choose between two similar tables or workflow branches with explicit reasoning. |
| `counterfactual` *(new)* | "If X were different, which downstream entries would change." |
| `resource-selection` *(new)* | Meta-test: which reference file should be opened first to answer the question. |
| `workflow-position` *(new)* | "I'm at point X in the pipeline; what populates next." |
| `dependency-tracing` *(new)* | Abstract enumeration of the full upstream chain for a given output table. |
| `schema-introspection` *(new)* | Direct fact about a table's schema (PK fields, direct dependency, part-table set). Grep-scorable, stable canonical answer. |

### Difficulty (3)

| Difficulty | Definition | Typical shape |
| --- | --- | --- |
| `easy` | One-step lookup or single-fact recall. The model either knows it or it doesn't; minimal reasoning between prompt and answer. | Atomic-read evals; `schema-introspection`; baseline activation; hallucination-resistance; non-activation. |
| `medium` | Two-step composition or one inference hop. Requires choosing the right tool/reference, then applying it. | Single-table debugging from a clean traceback; merge-key discovery; parameter-semantics where the param's effect is locally documented; disambiguation between two well-known options. |
| `hard` | Multi-step reasoning, multi-reference handoff, ambiguity tolerance, or counterfactual reasoning. Failure modes proliferate. | Compound multi-reference evals; dependency-tracing; counterfactual; recovery-from-incomplete-state; runtime errors with deep stacks; root-cause questions where multiple causes are plausible. |

Difficulty is *not* a quality bar — easy evals are still valuable as regression sentinels. It's a slicing dimension to ask "does the skill degrade on harder evals within the same tier?"

### Tagging rules

1. Exactly one `stage`, one `tier`, and one `difficulty` per eval. No "n/a" or blanks.
2. Reuse over invent — only introduce a new tier if the capability is genuinely new (the eight new tiers above already cover the gap categories; no further additions in this plan).
3. New topics (e.g., a new pipeline) → new stage if needed; new capabilities → new tier. Don't conflate.
4. When a prompt could fit two stages (e.g., a runtime error in ingestion), prefer the stage that matches the **user's experience** (where they got stuck), not the topic of the failed call.
5. Difficulty is judged on the answering side, not the question side. A short prompt can be hard ("trace upstream of `LFPBandV1`" — short to write, hard to answer); a long prompt with a clean traceback can be easy. When in doubt: `easy` if a competent first-year DataJoint user can answer in under a minute; `medium` if it takes them five minutes with the right reference open; `hard` if they'd need to reason about state they can't directly observe.

## Audit of existing evals (1–53) against the canonical vocabulary

Two passes: re-tag a small number of `stage` / `tier` mismatches, then assign `difficulty` to every existing eval (currently absent).

### Re-tags (4 evals)

Most existing `stage` / `tier` tags survive unchanged. Re-tag only the entries below; everything else stays. Re-tags trade one canonical value for another — they don't introduce hand-rolled values.

| ID | Current `stage` / `tier` | Proposed | Why |
| --- | --- | --- | --- |
| 7 | `framework-concepts` / `baseline` | `framework-concepts` / `table-classification` | Question is "what is a merge table" — that's table classification, not happy-path activation. |
| 30 | `common-mistakes` / `adversarial` | `common-mistakes` / `parameter-semantics` | Prompt is about understanding params before blind copy-paste — semantics question framed adversarially. Adversarial intent is captured in the behavioral check, not the tier. |
| 35 | `common-mistakes` / `merge-table-gotchas` | `runtime-debugging` / `merge-table-gotchas` | User has an error in hand; this is triage, not pattern-of-mistake. |
| 50 | `common-mistakes` / `merge-table-gotchas` | `runtime-debugging` / `merge-table-gotchas` | Same — silent wrong-count is observed via incorrect output. |

### Difficulty assignments for existing evals

| ID | Difficulty | ID | Difficulty | ID | Difficulty | ID | Difficulty |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | medium | 15 | medium | 29 | medium | 43 | hard |
| 2 | medium | 16 | medium | 30 | medium | 44 | medium |
| 3 | easy | 17 | medium | 31 | medium | 45 | medium |
| 4 | hard | 18 | medium | 32 | hard | 46 | hard |
| 5 | medium | 19 | easy | 33 | medium | 47 | medium |
| 6 | medium | 20 | easy | 34 | medium | 48 | medium |
| 7 | medium | 21 | easy | 35 | medium | 49 | hard |
| 8 | hard | 22 | easy | 36 | medium | 50 | medium |
| 9 | easy | 23 | medium | 37 | easy | 51 | easy |
| 10 | easy | 24 | medium | 38 | hard | 52 | easy |
| 11 | easy | 25 | medium | 39 | medium | 53 | medium |
| 12 | easy | 26 | hard | 40 | medium | | |
| 13 | medium | 27 | hard | 41 | medium | | |
| 14 | medium | 28 | medium | 42 | medium | | |

Heuristics behind the assignment:

- `easy`: atomic-read on a single table by PK (9–13), non-activation / hallucination-resistance where the right answer is "no" or "doesn't exist" (20–22), simple-traceback runtime errors with one cause (37, 51, 52).
- `medium`: most baselines, debugging from a clean traceback with a single likely cause, parameter understanding when documented, joins across two tables.
- `hard`: compound multi-reference (8, 26, 27), recovery from incomplete state (4, 43), runtime errors with multiple plausible root causes (32, 38, 46, 49).

The four re-tags above don't change the difficulty assignment. No JSON change for the other 49 evals beyond adding the `difficulty` field.

## How to write a new eval (executor reference)

### Canonical JSON object shape

Every new eval object goes into `evals[]` in [skills/spyglass/evals/evals.json](../../skills/spyglass/evals/evals.json) in this exact field order. Keep the order — `flatten_expectations.py` round-trips via `json.dumps(data, indent=2)` which preserves insertion order, and the existing 53 evals all follow this shape:

```json
{
  "id": 54,
  "eval_name": "classify-lfpselection",
  "stage": "table-understanding",
  "tier": "table-classification",
  "difficulty": "easy",
  "prompt": "Is `LFPSelection` a manual, lookup, computed, or imported table? ...",
  "expected_output": "<see drafting rule below>",
  "assertions": {
    "required_substrings": ["Manual", "selection table", "filter_name", "lfp_electrode_group_name"],
    "forbidden_substrings": ["is Computed", "is Lookup", "is Imported"],
    "behavioral_checks": [
      "Distinguishes DataJoint tier (Manual) from Spyglass role ...",
      "Names `LFPV1` as the Computed counterpart whose `populate()` consumes LFPSelection rows."
    ]
  },
  "files": [],
  "expectations": []
}
```

Field notes for the executor:

- `difficulty` is the new field, slotted between `tier` and `prompt`. Apply this same position when adding `difficulty` to existing evals 1–53.
- `files: []` is required (matches existing convention; no eval currently uses attachments).
- `expectations: []` is left empty on insert — `flatten_expectations.py` populates it automatically in step 1 of per-phase validation.
- Markdown backticks in the substring values (e.g., `` `Manual` ``) are formatting in this plan only — drop them when writing JSON. Substrings are bare strings.

### Drafting `expected_output`

`expected_output` is a 2–5 sentence prose description of the ideal answer (the LLM grader uses it as ground truth when scoring `behavioral_checks`). Pattern from existing evals: name the reference file the answer should route to, the specific APIs / flags / commands it should mention, and what it must not recommend.

Drafting rule for each new eval: combine the **routes to** pointer + the **behavioral_checks** into a single prose paragraph. Use the existing eval 1's `expected_output` as a length / voice template.

**Worked example for eval 54:**

> "Routes to lfp_pipeline.md (Step 2: Filter Raw Data block). Identifies LFPSelection as a Manual table at the DataJoint level and a 'selection table' in Spyglass terms — picks the input (electrode group + interval + filter) for the paired Computed table LFPV1, which is what actually runs the populate. Mentions that `filter_name` and `lfp_electrode_group_name` are PK fields on LFPSelection. Does not call LFPSelection a Computed, Lookup, or Imported table."

**Worked example for eval 58:**

> "Routes to lfp_pipeline.md → Nyquist note. Explains target_sampling_rate sets the downsampled output rate of LFPV1. Connects the rate to the Nyquist constraint: a downstream band filter (e.g., ripple band 150–250 Hz) requires the LFP stream's sampling rate to strictly exceed 2× the band's high cutoff, so a target_sampling_rate below ~500 Hz aliases ripple-band signal. Names 1000 Hz as the canonical Spyglass default. Does not say sample rate is arbitrary or doesn't matter."

For each of the 25 new evals, draft `expected_output` by combining (a) the **routes to** target, (b) the **behavioral_checks**, and (c) the **forbidden_substrings** as the "does not" clause.

## Phase A — table understanding (priority, evals 54–57)

Each subsection lists the prompt verbatim, the routing target, and the discriminating assertions. Behavioral checks are written as the LLM grader will see them. Draft `expected_output` per the rule above.

### Eval 54 — `classify-lfpselection`

- **stage / tier / difficulty:** `table-understanding` / `table-classification` / `easy`
- **prompt:** "Is `LFPSelection` a manual, lookup, computed, or imported table? And is it a 'selection' or 'parameter' table in spyglass terms? I'm trying to understand what I put into it vs. what gets computed."
- **routes to:** [lfp_pipeline.md](../../skills/spyglass/references/lfp_pipeline.md) → "Step 2: Filter Raw Data" block.
- **required_substrings:** `Manual table`, `selection table`, `filter_name`, `lfp_electrode_group_name`
- **forbidden_substrings:** `is Computed`, `is Lookup`, `is Imported`
- **behavioral_checks:**
  - Distinguishes DataJoint tier (Manual) from Spyglass role (selection table — picks input for the paired Computed table).
  - Names `LFPV1` as the Computed counterpart whose `populate()` consumes LFPSelection rows.

### Eval 55 — `classify-trodesposparams-vs-selection`

- **stage / tier / difficulty:** `table-understanding` / `table-classification` / `medium`
- **prompt:** "What's the difference between `TrodesPosParams` and `TrodesPosSelection`? Looking at both, they feel kind of similar and I can't tell which one I'm supposed to insert my parameter dict into."
- **routes to:** [position_pipeline.md](../../skills/spyglass/references/position_pipeline.md) → "Tables" block under Pipeline 1.
- **required_substrings:** `Manual`, `parameter table`, `selection table`, `insert1`, `trodes_pos_params_name`
- **forbidden_substrings:** `same table`, `interchangeable`
- **behavioral_checks:**
  - Identifies `TrodesPosParams` as the parameter table — Manual tier in DataJoint terms; named, reusable param dict; insert once per param set.
  - Identifies `TrodesPosSelection` as the selection table — also Manual; picks session + interval + params name for one populate run.
  - Discriminator note: `TrodesPosParams`/`TrodesPosSelection` removed from required (echoed in prompt); `trodes_pos_params_name` is the joining FK and a non-echoed discriminator. **Spyglass convention:** many `*Params` tables are `dj.Manual`, not `dj.Lookup` — verify each `*Params` class's tier individually before authoring related evals (do not assume parameter-table = Lookup tier).

### Eval 56 — `classify-positionoutput-merge`

- **stage / tier / difficulty:** `table-understanding` / `table-classification` / `medium`
- **prompt:** "What kind of table is `PositionOutput`? It doesn't have a `populate()` and I can't figure out how a row gets in there."
- **routes to:** [merge_methods.md](../../skills/spyglass/references/merge_methods.md) → mechanism intro; [position_pipeline.md](../../skills/spyglass/references/position_pipeline.md) → "PositionOutput Merge Table".
- **required_substrings:** `merge table`, `part table`, `PositionOutput.TrodesPosV1`, `PositionOutput.DLCPosV1`
- **forbidden_substrings:** (none — see discriminator note)
- **behavioral_checks:**
  - Explains that rows enter PositionOutput via insert into a part table (`PositionOutput.TrodesPosV1` or `PositionOutput.DLCPosV1`), not via `populate()`.
  - Names at least one valid downstream consumer pattern (`merge_get_part(key).fetch1('KEY')`).
  - Does not recommend `PositionOutput.populate()` or `populate(PositionOutput, ...)` as the entry point — explicitly contrasts with how rows actually arrive (insert into a part table).
  - Discriminator note: scoped forbidden substrings (`PositionOutput.populate`, `populate(PositionOutput`) were considered but moved to a behavioral check — a correct answer phrased as a denial ("you don't call `PositionOutput.populate()`") would still contain those substrings and false-fail. Behavioral grader handles the negation correctly.

### Eval 57 — `classify-lfpband-role`

- **stage / tier / difficulty:** `table-understanding` / `table-classification` / `easy`
- **prompt:** "Is `LFPBandV1` a compute table or an output table? I'm trying to decide if I should populate it or just read from it."
- **routes to:** [lfp_pipeline.md](../../skills/spyglass/references/lfp_pipeline.md).
- **required_substrings:** `Computed`, `LFPBandV1.populate`, `LFPBandSelection`
- **forbidden_substrings:** `LFPBandOutput`, `merge_get_part(LFPBand`
- **behavioral_checks:**
  - Identifies LFPBandV1 as Computed; user populates it after inserting `LFPBandSelection`.
  - Notes there is no merge wrapper — LFPBandV1 itself is the consumer-facing endpoint.
  - Discriminator note: bare `merge` removed from forbidden — the correct answer says "no merge wrapper" and would false-fail. Forbidden now pin the specific hallucination (made-up `LFPBandOutput` merge).

## Phase B — parameter understanding (priority, evals 58–62)

**General-knowledge dependency note.** Evals 58 and 62 are fully backed by skill content (Nyquist note in [lfp_pipeline.md:122](../../skills/spyglass/references/lfp_pipeline.md), `set_group_by_electrode` clusterless conflict in [spikesorting_pipeline.md](../../skills/spyglass/references/spikesorting_pipeline.md)). Evals 59, 60, and 61 partially rely on the model's general signal-processing / ML knowledge — the references mention the parameters but don't fully document direction-of-tradeoff. This is intentional: parameter-semantics evals test whether the skill primes the model to apply general knowledge in the Spyglass parameter context. They are *not* skill-content sentinels and should not be expected to swing on small reference edits.

### Eval 58 — `param-target-sampling-rate`

- **stage / tier / difficulty:** `parameter-understanding` / `parameter-semantics` / `hard`
- **prompt:** "`LFPSelection` has a `target_sampling_rate` field. What does this control, and what goes wrong if I set it too low for a ripple-band analysis I want to do later?"
- **routes to:** [lfp_pipeline.md](../../skills/spyglass/references/lfp_pipeline.md) → Nyquist note.
- **required_substrings:** `Nyquist`, `1000`, `downsample`
- **forbidden_substrings:** `sample rate doesn't matter`, `arbitrary`
- **behavioral_checks:**
  - Explains the field sets the downsampled output rate of LFPV1.
  - Connects the rate to the Nyquist constraint for downstream band filters (ripple band 150–250 Hz needs > 500 Hz sampling).
  - Mentions 1000 Hz as the canonical default and the consequence of going lower (aliasing in the downstream band).

### Eval 59 — `param-speed-threshold-ripple`

- **stage / tier / difficulty:** `parameter-understanding` / `parameter-semantics` / `medium`
- **prompt:** "In ripple params, what does `speed_threshold: 4.0` actually do? If I bump it to 10 cm/s, more ripples or fewer, and what quality tradeoff am I making?"
- **routes to:** [ripple_pipeline.md](../../skills/spyglass/references/ripple_pipeline.md).
- **required_substrings:** `speed_threshold`, `immobility`, `fewer`
- **forbidden_substrings:** `more ripples`
- **behavioral_checks:**
  - Explains the threshold filters out candidate events while the animal moves faster than the speed value (cm/s).
  - Predicts the direction: raising → fewer events, cleaner immobility-conditioned set; risks losing peri-movement SWRs.

### Eval 60 — `param-encoding-vs-decoding-interval`

- **stage / tier / difficulty:** `parameter-understanding` / `parameter-semantics` / `medium`
- **prompt:** "Clusterless decoding selection has both `encoding_interval` and `decoding_interval`. Can these be the same interval? When would I set them differently?"
- **routes to:** [decoding_pipeline.md](../../skills/spyglass/references/decoding_pipeline.md).
- **required_substrings:** `encoding_interval`, `decoding_interval`, `training`
- **behavioral_checks:**
  - Explains that encoding_interval trains the place-field / receptive-field model; decoding_interval is where the trained model is applied.
  - Gives a same-interval use (within-run reconstruction) and a different-interval use (train on run, decode replay during sleep / reward).

### Eval 61 — `param-trodes-smoothing`

- **stage / tier / difficulty:** `parameter-understanding` / `parameter-semantics` / `hard`
- **prompt:** "In `TrodesPosParams.insert_default()`'s params dict I see smoothing / filter fields. What happens to my resulting `speed` column if I turn smoothing off?"
- **routes to:** [position_pipeline.md](../../skills/spyglass/references/position_pipeline.md).
- **required_substrings:** `smoothing`, `speed`, `noise`
- **behavioral_checks:**
  - Explains smoothing low-passes raw position before the velocity / speed derivative.
  - Predicts: disabling smoothing gives a noisier speed trace, which causes spurious crossings of downstream thresholds (ripple `speed_threshold`, decoding interval gating, etc.).
  - Recommends inspecting `TrodesPosParams.describe()` / `.heading` for the exact field names rather than guessing.

### Eval 62 — `param-sort-group-contact-positions`

- **stage / tier / difficulty:** `parameter-understanding` / `parameter-semantics` / `hard`
- **prompt:** "`SortGroup().set_group_by_electrode()` — what grouping does this produce and why does the clusterless pipeline complain about non-unique contact positions when I use it?"
- **routes to:** [spikesorting_pipeline.md](../../skills/spyglass/references/spikesorting_pipeline.md), [decoding_pipeline.md](../../skills/spyglass/references/decoding_pipeline.md).
- **required_substrings:** `one electrode per group`, `contact_positions`, `set_group_by_shank`
- **forbidden_substrings:** `set_group_by_electrode is correct for clusterless`
- **behavioral_checks:**
  - Identifies that `set_group_by_electrode` puts one electrode in each sort group (fits tetrode-per-group sorts).
  - Explains the clusterless recording step requires each group to have distinct contact positions, which fails when each group has only one electrode whose position duplicates another's.
  - Recommends `set_group_by_shank` (or equivalent multi-contact grouping) for the clusterless workflow.

## Phase C — remaining gap categories (evals 63–73)

### Eval 63 — `disamb-trodes-vs-dlc`

- **stage / tier / difficulty:** `pipeline-usage` / `disambiguation` / `medium`
- **prompt:** "Rat has both headstage LEDs and a top-down camera with DLC models trained. Which pipeline do I use — Trodes or DLC — and what's the decision logic?"
- **required_substrings:** `TrodesPosV1`, `DLCPosV1`, `PositionOutput.TrodesPosV1`, `PositionOutput.DLCPosV1`
- **behavioral_checks:** Names latency / accuracy / setup-cost tradeoffs; mentions both can coexist (different merge entries) and the choice depends on the downstream analysis.
- Discriminator note: bare `LED`/`pose` removed (echo prompt and weak discriminators); replaced with the part-table strings, which require the model to commit to the DataJoint-level placement.

### Eval 64 — `disamb-lfpselection-vs-electrodegroup`

- **stage / tier / difficulty:** `pipeline-usage` / `disambiguation` / `medium`
- **prompt:** "What's the difference between `LFPElectrodeGroup` and `LFPSelection`? I see both in the flow and I don't know which to insert into first."
- **required_substrings:** `create_lfp_electrode_group`, `LFPElectrodeGroup.LFPElectrode`, `LFPSelection.insert1`
- **behavioral_checks:** Establishes ordering (electrode group must exist before LFPSelection.insert1 can succeed); explains the group is a reusable electrode bundle while selection picks group + interval + filter for one populate run.
- Discriminator note: `LFPElectrodeGroup`/`LFPSelection` (bare) removed from required (echoed in prompt); bare `first` and `before` both rejected as bare-words. Replaced with two API-shape strings (`create_lfp_electrode_group` is the group-creation method; `LFPSelection.insert1` is the next-step call) — these force the model to name the actual ordered API, not just describe sequence verbally.

### Eval 65 — `disamb-spikesortingv0-vs-v1`

- **stage / tier / difficulty:** `pipeline-usage` / `disambiguation` / `easy`
- **prompt:** "I see both `spyglass.spikesorting.v0` and `spyglass.spikesorting.v1` imports in old lab code. Which should I use for a fresh session today and why?"
- **required_substrings:** `legacy`, `SpikeSortingOutput`, `recommend v1`
- **forbidden_substrings:** `v0 for new sessions`, `use v0`
- **behavioral_checks:** Recommends v1 for new work; identifies v0 as legacy / read-only for old data; routes to [spikesorting_v0_legacy.md](../../skills/spyglass/references/spikesorting_v0_legacy.md) only for reading old sorts.
- Discriminator note: bare `v1` removed from required — matches "v1" in the prompt verbatim and is bare-word. The phrase `recommend v1` forces the model to commit to a recommendation.

### Eval 66 — `resource-first-ref-fetch1`

- **stage / tier / difficulty:** `runtime-debugging` / `resource-selection` / `easy`
- **prompt:** "I got `DataJointError: fetch1 should only be called on one tuple, but 47 were returned`. Before you answer the actual fix — which reference file inside the spyglass skill would you open first?"
- **required_substrings:** one of `datajoint_api.md`, `common_mistakes.md`
- **behavioral_checks:** Names the reference file by name; explains the choice (cardinality error → `common_mistakes.md` #2 or `datajoint_api.md` fetch section).

### Eval 67 — `resource-first-ref-merge-delete`

- **stage / tier / difficulty:** `destructive-operations` / `resource-selection` / `easy`
- **prompt:** "I want to delete one entry from `PositionOutput` via a merge_key. Which spyglass skill reference do you consult first?"
- **required_substrings:** one of `destructive_operations.md`, `merge_methods.md`
- **behavioral_checks:** Names the file; mentions inspect-before-destroy as the operative pattern.

### Eval 68 — `counterfactual-ripple-electrode-set`

- **stage / tier / difficulty:** `pipeline-usage` / `counterfactual` / `hard`
- **prompt:** "If I added 3 more CA1 tetrodes to my ripple detection electrode selection and re-populated, which downstream tables would change and which would be unaffected?"
- **required_substrings:** `RippleTimesV1`, `LFPBandV1`, `RippleParameters`
- **behavioral_checks:** Identifies `LFPBandV1` (or upstream LFP) as needing a new selection if the new electrodes weren't included; identifies `RippleTimesV1` as the table that re-populates; notes unrelated branches (decoding, position) are unaffected unless they depend on the same LFP entry.
- Discriminator note: `re-populate` echoed prompt's "re-populated" and was a weak discriminator; replaced with two table names that force the model to name specific upstream/downstream tables affected.

### Eval 69 — `counterfactual-two-users-empty`

- **stage / tier / difficulty:** `pipeline-usage` / `counterfactual` / `hard`
- **prompt:** "A labmate and I both ran the same selection + populate on `j1620210710_.nwb`. My `fetch_results` returns data, theirs returns empty. What differs between our pipeline states to explain this?"
- **required_substrings:** `params_name`, `cautious_delete`, `restriction`
- **forbidden_substrings:** `same selection key`, `identical pipeline state`
- **behavioral_checks:** Lists at least three plausible state differences (different params name, missing upstream populate, different selection key, team-permission gating, environment / package version drift); does not assume one cause; does not claim the pipeline state is identical when the symptoms prove otherwise.
- Discriminator note: original required (`selection`, `params`, `populate`) was three-for-three echo + bare-word violations — all three appear in the prompt verbatim and as bare common words. Replaced with: `params_name` (the FK that distinguishes two users' selections), `cautious_delete` (the team-permission gate that's the most common cause), and `restriction` (the DataJoint mechanism that explains different fetched rows for the same query). All three are non-echoed, are joined-word terms (no bare-word risk), and force the model to commit to specific Spyglass mechanisms rather than vague handwaving.

### Eval 70 — `workflow-next-after-spikesortingselection`

- **stage / tier / difficulty:** `pipeline-usage` / `workflow-position` / `medium`
- **prompt:** "I just inserted into `SpikeSortingSelection` without errors. What's the next table I populate, and after that, what's the next?"
- **required_substrings:** `SpikeSorting.populate(`, `CurationV1`, `MetricCuration`
- **behavioral_checks:** Gives an ordered next-N list (SpikeSorting.populate → curation entry → MetricCuration → CurationV1, or equivalent v1 path); routes to [spikesorting_pipeline.md](../../skills/spyglass/references/spikesorting_pipeline.md).
- Discriminator note: bare `SpikeSorting` (substring-matches the prompt's `SpikeSortingSelection`) and bare `populate` (echoes prompt) removed; replaced with the full method call (`SpikeSorting.populate(` — note: the v1 class name is `SpikeSorting`, not `SpikeSortingV1`; verified in [validate_skill.py KNOWN_CLASSES](../../skills/spyglass/scripts/validate_skill.py)) and the next-step table name `MetricCuration` (a non-echoed discriminator that forces ordered enumeration). The trailing paren in `SpikeSorting.populate(` prevents accidental match against `SpikeSortingSelection.populate(`.

### Eval 71 — `workflow-next-after-dlcmodeltraining`

- **stage / tier / difficulty:** `pipeline-usage` / `workflow-position` / `hard`
- **prompt:** "DLC model is trained and in the DLC model table. I want to get from here to a merge_id in `PositionOutput`. What's the ordered list of tables I still need to touch?"
- **required_substrings:** `DLCPosV1`, `PositionOutput.DLCPosV1`
- **behavioral_checks:** Lists the ordered tables (DLCPoseEstimationSelection → DLCPoseEstimation → DLCSmoothInterpSelection → DLCSmoothInterp → DLCPosV1 → insert into `PositionOutput.DLCPosV1`); routes to [position_pipeline.md](../../skills/spyglass/references/position_pipeline.md).

### Eval 72 — `dep-trace-decoding-output`

- **stage / tier / difficulty:** `pipeline-usage` / `dependency-tracing` / `hard`
- **prompt:** "Given a `DecodingOutput.ClusterlessDecodingV1` merge entry, enumerate every upstream table (including selections and parameter tables) that must have had an entry for this row to exist. Assume I want to regenerate from raw NWB."
- **required_substrings:** `Nwbfile`, `Session`, `IntervalList`, `Electrode`, `SortGroup`, `SpikeSortingRecording`, `UnitWaveformFeaturesGroup`, `PositionGroup`, `DecodingParameters`, `ClusterlessDecodingSelection`
- **behavioral_checks:** Produces an ordered or grouped list covering raw-data tables, recording / sorting branch, position branch, parameter table, selection table; does not invent table names.

### Eval 73 — `dep-trace-lfpbandv1`

- **stage / tier / difficulty:** `pipeline-usage` / `dependency-tracing` / `hard`
- **prompt:** "Starting from a populated `LFPBandV1` row, list all upstream tables whose entries it depends on. I want to know the minimum set I'd need to re-create this from scratch."
- **required_substrings:** `Nwbfile`, `Raw`, `IntervalList`, `LFPElectrodeGroup`, `LFPSelection`, `LFPV1`, `LFPOutput`, `FirFilterParameters`, `LFPBandSelection`
- **behavioral_checks:** Names every upstream table including the parameter and selection tables; does not skip the merge wrapper (`LFPOutput`) between LFPV1 and LFPBandSelection.

## Phase C' — schema-introspection (evals 74–78)

These were proposed during planning as a batch of 13 fact-shape questions. Five survived a triage pass (others were skipped for one of: dtype/nullability brittleness across Spyglass versions, enumeration completeness rot, or wrong expected answer for the current schema). All five are `easy` difficulty — they're single-fact lookups with stable canonical answers.

The shape differs from other evals: short prompt with a fixed-format answer requirement, scored by exact substring match. They behave more like an introspection regression sentinel than a reasoning test.

### Eval 74 — `schema-pk-electrode`

- **stage / tier / difficulty:** `framework-concepts` / `schema-introspection` / `easy`
- **prompt:** "What is the primary key of the `Electrode` table? Return only the field names as a comma-separated list, nothing else."
- **routes to:** [common_tables.md](../../skills/spyglass/references/common_tables.md).
- **required_substrings:** `nwb_file_name`, `electrode_group_name`, `electrode_id`
- **forbidden_substrings:** `region_id` (secondary, not PK)
- **behavioral_checks:** Lists exactly the three PK fields in any order; no extra fields.

### Eval 75 — `schema-pk-firfilterparameters`

- **stage / tier / difficulty:** `framework-concepts` / `schema-introspection` / `easy`
- **prompt:** "What is the primary key of the `FirFilterParameters` table? Return only the field names as a comma-separated list, nothing else."
- **routes to:** [lfp_pipeline.md](../../skills/spyglass/references/lfp_pipeline.md) (Nyquist note references the table).
- **required_substrings:** `filter_name`, `filter_sampling_rate`
- **behavioral_checks:** Lists exactly the two PK fields; explains the consequence (a filter named for one rate doesn't apply to a stream at another rate).

### Eval 76 — `schema-dep-intervallist`

- **stage / tier / difficulty:** `framework-concepts` / `schema-introspection` / `easy`
- **prompt:** "What table does `IntervalList` directly depend on? Return only the table name."
- **routes to:** [common_tables.md](../../skills/spyglass/references/common_tables.md).
- **required_substrings:** `Session`
- **behavioral_checks:** Names `Session` only (no extra speculation).

### Eval 77 — `schema-dep-lfp-filter`

- **stage / tier / difficulty:** `framework-concepts` / `schema-introspection` / `easy`
- **prompt:** "Which table holds the filter coefficients (FIR kernel data) used by the LFP pipeline? Return only the table name."
- **routes to:** [lfp_pipeline.md](../../skills/spyglass/references/lfp_pipeline.md).
- **required_substrings:** `FirFilterParameters`
- **behavioral_checks:** Names FirFilterParameters as the lookup table for filter coefficients (distinct from `LFPSelection`, which carries `filter_name` as FK but is the per-run selection, not the kernel store).
- Reframe note: original prompt asked "what does LFPV1 reference for filter information" — ambiguous between the direct FK (`LFPSelection`, two hops) and the lookup source (`FirFilterParameters`). Reworded to ask specifically about kernel data.

### Eval 78 — `schema-part-tables-probe`

- **stage / tier / difficulty:** `framework-concepts` / `schema-introspection` / `easy`
- **prompt:** "What are the part tables of `Probe`? Return only the part table names as a comma-separated list."
- **routes to:** [common_tables.md](../../skills/spyglass/references/common_tables.md).
- **required_substrings:** `Probe.Shank`, `Probe.Electrode`
- **behavioral_checks:** Lists both part tables in `Master.Part` notation.

### Triaged-out candidates (8)

Recorded here so the next contributor doesn't re-propose them without context:

| Candidate | Reason for exclusion |
| --- | --- |
| PK of `LFPBand` | `LFPBand` is v0; current is `LFPBandV1` and the proposed PK doesn't match. |
| dtype of `lfp_sampling_rate` in `LFP` | DataJoint dtype strings drift (`float` vs `decimal(10,3)`); brittle across Spyglass versions. |
| dtype of `region_id` in `BrainRegion` | Same brittleness. |
| Nullability of `probe_id` in `ElectrodeGroup` | Schema-version-dependent; nullability has changed historically. |
| Nullability of `region_id` in `Electrode` | Same. |
| All tables with `nwb_file_name` as PK | Enumeration is incomplete (missing `Raw`, `TaskEpoch`, others) and grows with Spyglass; impossible to keep right. |
| All tables with `filter_name` as PK | Same enumeration-rot. |
| Direct dep of `LFPSelection` (single answer) | Has multiple direct deps (`Session`, `LFPElectrodeGroup`, `IntervalList`, `FirFilterParameters`). Reframe to "name three" already covered by eval 73. |

If a future contributor wants to revive any of these, the right move is to (a) change the question shape to "show how to discover this via `Table.heading`" (testing the introspection skill, not memorization), or (b) pin the eval to a specific Spyglass version and accept it'll go stale.

## Phase D — retro-anonymization

### Scope

Sweep evals 1–53 in [skills/spyglass/evals/evals.json](../../skills/spyglass/evals/evals.json) for identifying strings. Apply to **all string fields per eval**: `prompt`, `expected_output`, and any string in `assertions.required_substrings` / `forbidden_substrings` / `behavioral_checks`. Do **not** touch `eval_name`, `stage`, `tier`, `difficulty`, or `id`. Skip new evals 54–78 entirely (already anonymized at authoring time).

### Find/replace table

| Find | Replace with |
| --- | --- |
| `franklab.ucsf.edu` | `db.example.test` |
| `Frank Lab` / `Frank lab` | `example lab` |
| `UCSF` (when paired with the lab reference) | drop or replace with `example institution` |
| `edeno` (as DB user) | `testuser` |
| `jsmith` (other user in permission examples) | `otheruser` |

Pair-aware substitution: `edeno` / `jsmith` appear together in eval 24's `PermissionError: User 'edeno' is not on a team with 'jsmith'` and in eval 43. Keep the substitutions consistent across both evals — `edeno → testuser` and `jsmith → otheruser` everywhere they appear, so paired references still scan ("`testuser` is not on a team with `otheruser`").

### Pre-sweep audit

Before mutating anything, run a discovery scan to enumerate the matches. This catches missed occurrences (e.g., `edeno` appearing in an `expected_output` not just the `prompt`):

```bash
python3 -c "
import json, re
with open('skills/spyglass/evals/evals.json') as f: d = json.load(f)
patterns = ['franklab\\.ucsf\\.edu', 'Frank [Ll]ab', 'UCSF', r\"'edeno'\", 'edeno@', r\"'jsmith'\"]
for e in d['evals']:
    if e['id'] > 53: continue
    blob = json.dumps(e)
    hits = [(p, len(re.findall(p, blob))) for p in patterns]
    hits = [(p, n) for p, n in hits if n > 0]
    if hits:
        print(f'eval {e[\"id\"]} ({e[\"eval_name\"]}): {hits}')
"
```

Use the discovery output as the work list. Do not blanket-replace `edeno` everywhere — match the patterns above (the bare word `edeno` could match unrelated identifiers like `edenovellis` if they ever appear).

### Keep (do not anonymize)

- `j1620210710_.nwb` and the underscore-trailing variant — established fixture, not an identifier in the privacy sense.
- `aj80` subject ID — animal IDs are not lab identifiers per the operative rule.
- All technical strings (table names, error messages, CLI flags).

### Post-sweep checks

1. Re-read each modified eval to check the prompt still scans naturally (no awkward "I just joined the example lab at example institution" — rephrase locally where needed).
2. For any eval where a `required_substring` was a quoted fragment of the prompt and the prompt got rewritten, re-verify the substring still appears verbatim in the new prompt. Use the substring-hygiene self-check.
3. Run `python3 skills/spyglass/evals/scripts/flatten_expectations.py` — if any anonymized substring landed in `assertions.*`, the regenerated `expectations[]` will reflect the new value. Confirm `--check` exits 0.

## Cross-cutting validation and rollout

### Preflight (run once before commit 0)

```bash
test -d "$SPYGLASS_SRC" || { echo "set SPYGLASS_SRC to a Spyglass source checkout"; exit 1; }
```

[validate_all.sh](../../skills/spyglass/scripts/validate_all.sh) reads `$SPYGLASS_SRC` to resolve method-existence and line-citation checks. Without it, the validator skips those checks and the `--baseline-warnings 3` gate is meaningless.

### Per-phase validation

After each phase (A, B, C, C', D — and after pre-req commit 0):

1. `python3 skills/spyglass/evals/scripts/flatten_expectations.py` — regenerate the `expectations` arrays.
2. `python3 skills/spyglass/evals/scripts/flatten_expectations.py --check` — confirm the regen is idempotent.
3. `./skills/spyglass/scripts/validate_all.sh --baseline-warnings 3` — main validator + regression suite.
4. `ruff check .` — Python lint (touches the `flatten_expectations.py` invocation only, but kept in CI).

### Substring hygiene self-check

For each new eval, before committing:

- No `required_substring` echoes a noun that already appears in the prompt verbatim. (E.g., eval 54: don't put `LFPSelection` in required; use `filter_name`.)
- No bare-word substring that flips meaning under negation (e.g., `restart` matches "no need to restart"). Pair with a disambiguating word or move to behavioral.
- `forbidden_substrings` pin the *specific* wrong answer the eval guards against, not generic banned vocabulary that good answers might mention (e.g., don't forbid bare `populate` on a merge-table eval — correct answers will say "you don't `populate()` it").
- After Phase D anonymization, re-scan touched evals: if a `required_substring` was quoted from the prompt and the prompt got rewritten, the substring may now be stale. Run a quick `grep -F "<substring>" <eval prompt>` for each touched eval to confirm the prompt-to-substring relationship is intentional.

### Spot-run after Phase B

After Phase B lands (evals 54–62 in the JSON), pick one eval per new tier introduced so far and run it both with the skill loaded and without (baseline). The discrimination gate: **at least one assertion must flip pass→fail when the skill is removed**. If every assertion passes baseline-without-skill too, the eval is measuring the model, not the skill, and the assertions need tightening.

Concrete picks for the Phase B spot-run:

| Tier introduced | Spot-run eval ID |
| --- | --- |
| `table-classification` | 56 (`classify-positionoutput-merge`) — strong skill-content backing in [merge_methods.md](../../skills/spyglass/references/merge_methods.md) |
| `parameter-semantics` | 58 (`param-target-sampling-rate`) — Nyquist note in [lfp_pipeline.md](../../skills/spyglass/references/lfp_pipeline.md) is the discriminating content |

Runner pattern (executed from a skill-creator workspace adjacent to the skill, per [skills/spyglass/CLAUDE.md](../../CLAUDE.md) dev-env guidance):

```bash
WS="$(dirname "$(realpath skills/spyglass)")/spyglass-workspace/iteration-1"
mkdir -p "$WS/eval-56/with_skill" "$WS/eval-56/baseline" \
         "$WS/eval-58/with_skill" "$WS/eval-58/baseline"
```

Then dispatch four `Agent` subagent calls in a single message (run in parallel — they're fully independent). Use the prompt template below for each. The four runs are: `{56, 58} × {with_skill, baseline}`.

**With-skill subagent prompt template:**

> ```text
> You have access to the spyglass skill at: /Users/edeno/Documents/GitHub/spyglass-skill/skills/spyglass/
> Read SKILL.md, then any references it directs you to.
>
> Answer this user message as if you were Claude Code in a real session:
>
> <PROMPT FROM EVAL ID 56 OR 58 — paste prompt verbatim from evals.json>
>
> Save your response to: <WS>/eval-<ID>/with_skill/response.md
> Also save the list of reference files you opened to: <WS>/eval-<ID>/with_skill/refs_opened.txt
> ```

**Baseline subagent prompt template** (same prompt, no skill access):

> ```text
> Answer this user message as if you were Claude Code in a real session, using only your training knowledge. Do NOT read any files under /Users/edeno/Documents/GitHub/spyglass-skill/skills/spyglass/.
>
> <PROMPT FROM EVAL ID 56 OR 58 — paste prompt verbatim>
>
> Save your response to: <WS>/eval-<ID>/baseline/response.md
> ```

After all four runs return, grade each `response.md` against the eval's `assertions.required_substrings`, `forbidden_substrings`, and `behavioral_checks` (manually, or by spawning a grader subagent given the full skill-creator [grader.md](https://github.com/anthropics/skills/blob/main/skill-creator/agents/grader.md) pattern). Discrimination gate: at least one assertion must be **pass in `with_skill` AND fail in `baseline`** for each spot-run eval.

```bash
python -m scripts.aggregate_benchmark "$WS" --skill-name spyglass  # if available
```

Workspaces are gitignored per [CLAUDE.md](../../CLAUDE.md) — never commit them.

If the discrimination gate fails for a spot-run eval, revise the assertions before continuing to Phase C. Don't paper over with a softer gate.

### Commit boundaries

Seven commits in strict order, per the repo's commit-message style (lowercase topic prefix):

0. `references: fix Electrode PK; validator: register three Selection classes` (pre-req — see [Pre-req fixes](#pre-req-fixes-landed-before-phase-1))
1. `evals: add canonical stage/tier/difficulty vocabulary, re-tag four existing evals, add difficulty to all 53`
2. `evals: add table-understanding evals 54-57`
3. `evals: add parameter-understanding evals 58-62`
4. `evals: add disambiguation/counterfactual/resource/workflow/dep-trace evals 63-73`
5. `evals: add schema-introspection evals 74-78`
6. `evals: anonymize lab identifiers in existing evals`

Each commit ends with `flatten_expectations.py` regen and validator pass; no commit skips hooks. Commit 0 has no JSON change but runs the validator as a smoke test against the registry edits.

**Rollback.** Each commit is atomic; revert via `git revert <sha>` and re-run the per-phase validation steps. The pre-req commit (0) is the exception — reverting it requires also reverting any later commit that cites the registered classes (i.e., commits 4–5 if Phase C / C' has landed).

### Infra updates required by this plan

#### `evals/README.md` updates (land in commit 1)

Three concrete changes:

1. **Per-eval keys table** — add a `difficulty` row between `tier` and `prompt`. Insert this row verbatim:

   ```markdown
   | `difficulty` | string | What kind of cognitive load the eval imposes on the answer side. One of `easy` / `medium` / `hard`. See [Difficulty](#difficulty). |
   ```

2. **Add a `## Difficulty` section** between Tiers and "Tier vs stage — why both?" with this content (copy-paste verbatim into the README):

   ```markdown
   ## Difficulty

   Captures *how hard the eval is to answer*, independent of stage and tier. Used for slicing benchmarks within a single tier ("does the skill degrade on harder parameter-semantics evals?").

   | Difficulty | N | What it tests |
   | --- | --- | --- |
   | `easy` | <count> | One-step lookup or single-fact recall. Atomic-read, schema-introspection, baseline activation, hallucination/non-activation. |
   | `medium` | <count> | Two-step composition or one inference hop. Single-table debugging, merge-key discovery, parameter-semantics with locally documented effects. |
   | `hard` | <count> | Multi-step reasoning, multi-reference handoff, ambiguity, or counterfactual reasoning. Compound, dependency-tracing, recovery-from-incomplete-state. |

   Difficulty is judged on the *answering* side, not the question side. A short prompt can be hard ("trace upstream of LFPBandV1") and a long traceback prompt can be easy.
   ```

   Fill `<count>` from the final state after all phases land: easy = (count of `easy` across all 78 evals), etc. The Phase A–C' difficulty assignments above plus the existing-evals table in [Difficulty assignments for existing evals](#difficulty-assignments-for-existing-evals) are the source.
3. **Bump per-tier and per-stage N counts** in the existing tables. After all phases land (verified by computing from the JSON, not by hand-arithmetic):
   - **Stages**: `setup` 6, `ingestion` 4, `pipeline-usage` 24 (+9 from new evals 63–65, 68–73), `pipeline-authoring` 1, `framework-concepts` 6 (+5 from new evals 74–78; eval 7 stays here under re-tag), `runtime-debugging` 16 (+2 from re-tags 35/50, +1 from eval 66), `common-mistakes` 5 (-2 from re-tags 35/50; eval 30 stays in common-mistakes), `destructive-operations` 4 (+1 from eval 67), `non-activation` 2, `hallucination-resistance` 1, `table-understanding` 4, `parameter-understanding` 5. Total = 78.
   - **Tiers**: `runtime-errors` 8, `baseline` 7 (-1 from eval 7 re-tag), `adversarial` 7 (-1 from eval 30 re-tag), `parameter-semantics` 6 (5 new + eval 30 re-tag), `atomic-read` 5, `joins` 5, `merge-table-gotchas` 5, `table-classification` 5 (4 new + eval 7 re-tag), `schema-introspection` 5 (new), `merge-key-discovery` 3, `environment-triage` 3, `post-ingest-validation` 3, `config-troubleshooting` 3, `disambiguation` 3 (new), `compound` 2, `counterfactual` 2 (new), `resource-selection` 2 (new), `workflow-position` 2 (new), `dependency-tracing` 2 (new). Total = 78.

Verify the README counts against the JSON before committing with the snippet from the [Pre-commit smoke check](#pre-commit-smoke-check) plus the rollup command in the bullet just below this list.

After editing the README, run a sanity check: `python3 -c "import json; d=json.load(open('skills/spyglass/evals/evals.json')); from collections import Counter; print('stages:', Counter(e['stage'] for e in d['evals'])); print('tiers:', Counter(e['tier'] for e in d['evals'])); print('difficulty:', Counter(e['difficulty'] for e in d['evals']))"` and confirm the README counts match the JSON output.

#### Other infra

- **`flatten_expectations.py`**: confirmed no change needed — script reads only `assertions.required_substrings`/`forbidden_substrings`/`behavioral_checks` (lines 25–35) and round-trips other fields via `json.dumps(data, ...)`. The new `difficulty` field survives untouched.
- **`scripts/validate_skill.py`**: confirmed no per-eval field allow-list. The `check_evals_content` function reads `expected_output`, `behavioral_checks`, `required_substrings` for hallucination checks but ignores other top-level fields. New `tier`, `stage`, and `difficulty` values pass silently. No validator change required.

### Validator warning baseline

Current baseline is **3 warnings** (all in pre-existing reference files: `datajoint_api.md` section length, `runtime_debugging.md` total length and one section length). Adding 25 new evals can introduce new warnings if:

- A new eval's `expected_output` mentions a class name not in `KNOWN_CLASSES` → false-positive hallucinated-class warning. Pre-req commit 0 already addresses the three known offenders; if a new warning fires, register the missing class rather than weakening the eval.
- A new eval's `required_substring` includes a method name with a wrong line number citation. The new evals don't cite line numbers, so this shouldn't fire.

If the validator emits more than 3 warnings after any phase, **prefer fixing** (tighten the eval, register the class, fix the typo) over **bumping the baseline**. Only bump `--baseline-warnings` with a one-line justification in the commit message and a follow-up issue to address the new warning.

### Out-of-scope / deferred

- Any reference-file edits the new evals expose as gaps. If, e.g., eval 62 (`set_group_by_electrode` clusterless conflict) reveals that the skill doesn't actually route well to that diagnosis, file a follow-up under `docs/plans/` rather than fixing inline.
- Skill description re-optimization. Run only if Phase B spot-runs show triggering regressions.
- Migrating the assertion schema (e.g., richer than three buckets). The existing shape is sufficient for all 25 new evals.
- Adding `difficulty` to the `assertion_schema` self-describing object at the top of `evals.json`. If the schema's intent is "how assertions are scored," difficulty isn't an assertion property — leave the schema object alone and document `difficulty` only in `evals/README.md`.

## Pre-commit smoke check

Run before every commit from **commit 1 onward** (commit 0 has no JSON change so the smoke check is not applicable; the validator alone covers it). One-liner that catches the common authoring mistakes — duplicate IDs, missing required fields, misordered fields, stale `expectations`:

```bash
python3 -c "
import json, sys
d = json.load(open('skills/spyglass/evals/evals.json'))
ids, names, errors = set(), set(), []
required = ['id','eval_name','stage','tier','difficulty','prompt','expected_output','assertions','files','expectations']
allowed_difficulty = {'easy','medium','hard'}
for e in d['evals']:
    if e['id'] in ids: errors.append(f\"duplicate id {e['id']}\")
    if e['eval_name'] in names: errors.append(f\"duplicate eval_name {e['eval_name']}\")
    ids.add(e['id']); names.add(e['eval_name'])
    missing = [k for k in required if k not in e]
    if missing: errors.append(f\"eval {e['id']}: missing fields {missing}\")
    if e.get('difficulty') not in allowed_difficulty:
        errors.append(f\"eval {e['id']}: bad difficulty {e.get('difficulty')!r}\")
    if list(e.keys())[:len(required)] != required:
        errors.append(f\"eval {e['id']}: field order wrong, got {list(e.keys())}\")
    a = e.get('assertions', {})
    for k in ['required_substrings','forbidden_substrings','behavioral_checks']:
        if k not in a: errors.append(f\"eval {e['id']}: missing assertions.{k}\")
if errors:
    print('\\n'.join(errors)); sys.exit(1)
print(f'ok: {len(d[\"evals\"])} evals, all fields present, ids unique')
"
```

This runs in <100 ms. If it fails, fix before committing — the validator's own checks won't catch missing-field or duplicate-ID errors at the JSON-shape level.

## Open questions deferred to execution

1. **Eval 30 re-tag.** Current: `common-mistakes` / `adversarial`; proposed: `common-mistakes` / `parameter-semantics`. The original `adversarial` framing is genuinely useful — the prompt is a labmate-pressure test. If the re-tag loses that signal, fall back to keeping `adversarial` and accept that `parameter-semantics` coverage there is implicit. Decide at the time of the Phase A commit.
2. **Difficulty borderline calls.** Several existing evals sit between easy and medium (e.g., #19 count-tetrodes-per-session — single aggregation, but composes across two tables). Initial assignments above are first-pass; expect to adjust 5–10 of them once we run the suite and see which the model actually finds easy vs medium. Treat the difficulty field as living metadata.
3. **Whether `schema-introspection` evals belong in `framework-concepts` stage or warrant a new `schema-knowledge` stage.** Current plan: keep in `framework-concepts` since the questions are conceptual rather than tied to a specific pipeline. If the batch grows past ~10 evals, split out.
