# Implementation plan — reference key hygiene and validator coverage

**Date:** 2026-04-28
**Status:** Batches A, B, C, D complete (PRs #22, #23, #24, #25). Batch E deferred (only opens if drift recurs).
**Scope:** Reduce wrong or missing key claims in `skills/spyglass/references/` by tightening reference-writing policy, adding targeted validator checks for key-bearing examples, and adding evals that punish confident key invention.

This plan responds to a repeated review finding: many dangerous Spyglass mistakes are not missing imports or broken links. They are plausible, copyable key claims that look reasonable to an LLM but fail against source or the user's runtime database.

## Decision

Treat exact table keys as fragile facts. References should teach workflows and the need to verify keys; scripts and source should provide the exact identifiers.

Do **not** try to make every reference into a complete, static schema catalog. Static catalogs drift, custom pipelines are invisible to source-only tooling, and runtime databases can diverge from checked-out source. Use static key examples only when they are essential to the workflow and verified against source or `db_graph.py`.

## Goals

- Remove or rewrite reference examples that hardcode keys unnecessarily.
- Preserve concise, useful examples by showing key-discovery patterns before final restrictions or inserts.
- Extend the validator to catch the high-risk key mistakes that are mechanically detectable.
- Add evals that reward verification and abstention when key facts are not available.
- Keep `SKILL.md` lean; use references for workflow detail and scripts for factual lookup.

## Non-goals

- Building a full schema-fact validator for every table entry.
- Verifying secondary attributes or field types exhaustively.
- Importing Spyglass or connecting to a live database during normal validation.
- Turning `db_graph.py` into a general DataJoint query language.
- Rewriting all references in one broad pass.

## Authority model

Use this hierarchy when reviewing or authoring key-bearing prose:

| Claim type | Preferred authority | Notes |
| --- | --- | --- |
| Source table/class exists | `code_graph.py describe`, source read | Source-only; may miss custom pipelines. |
| Static dependency path exists | `code_graph.py path`, source read | Version and record identity matter. |
| Table heading / PK in current DB | `db_graph.py describe`, `Table.heading` | Runtime authority; can differ from source. |
| Row exists / restriction cardinality | `db_graph.py count` / fetch, normal DataJoint count | Never infer from source docs alone. |
| Merge master row lookup | `db_graph.py` merge-aware commands or merge helper methods | Master headings often only expose `merge_id`. |
| Blob/dict parameter key | Source `make()` / builder code, docs, actual parameter rows | Table heading only proves the blob field exists. |
| Custom pipeline table | `db_graph.py` with explicit import/module context, or direct source read | `code_graph.py` may not see it. |

## Reference policy

When editing a reference, apply these rules:

1. If an example restricts, inserts, fetches, or populates by key, verify the field names against source or runtime DB before keeping them.
2. Prefer discovery-first examples when the exact key is not the point:

   ```python
   Table.heading.primary_key
   rel.fetch("KEY", limit=5)
   len(rel)
   ```

3. If a final restriction is shown, include only fields that are actually in the relation being restricted.
4. Do not use upstream keys against merge masters unless the method is merge-aware (`merge_restrict`, `merge_get_part`, or a validated helper).
5. Do not present blob parameter contents as heading fields. Name the top-level blob field separately from keys inside the blob.
6. If the correct key depends on a pipeline version, say so and verify that version's source.
7. If the key depends on the user's live database, route to `db_graph.py` rather than hardcoding the answer.

## Batch A — audit and classify existing key-bearing examples

Create a lightweight audit report before changing references.

### Inputs

- `skills/spyglass/references/*.md`
- Python code blocks containing dict literals.
- Prose lines containing likely key terms:
  - `Primary Key`
  - `Key:`
  - `restriction`
  - `insert`
  - `fetch1`
  - `populate`
  - `merge_id`
  - `_param_name`
  - `_params_name`

### Classification

For each finding, classify as:

| Class | Meaning | Action |
| --- | --- | --- |
| Verified static key | Key is intentionally documented and matches source | Keep; optionally add citation if high-risk. |
| Runtime key | Must come from user's connected DB | Replace with discovery/routing language. |
| Blob parameter key | Nested parameter field, not table heading | Route to source `make()` / actual row inspection. |
| Merge-key hazard | Uses upstream fields against merge master | Rewrite to merge-aware pattern. |
| Unnecessary hardcode | Key is not essential to teaching workflow | Replace with discovery-first example. |
| Wrong / stale key | Does not match source relation | Fix or remove. |

### Output

Add an audit note to this plan or a short temporary checklist in the PR description. Do not create a permanent reference catalog unless drift continues recurring.

### Batch A audit note — 2026-04-28

Initial audit started on branch `reference-key-hygiene`.

Checks run:

- `rg` scan over `skills/spyglass/references/*.md` for dict restrictions, `Primary Key`, `Key:`, `insert`, `populate`, `fetch1`, merge helpers, and likely key fields.
- Targeted merge-hazard scan for `*Output & {...}`, `merge_get_part`, `merge_restrict`, `merge_delete`, `merge_delete_parent`, and `merge_id`.
- `python skills/spyglass/scripts/validate_skill.py --spyglass-src /Users/edeno/Documents/GitHub/spyglass/src`.

Observed baseline:

- Existing validator passes: `2011 passed, 3 warnings, 0 failed`.
- Warnings are existing size/progressive-disclosure warnings (`datajoint_api.md`, `runtime_debugging.md`), not key correctness failures.
- No obvious stale split-route issue remains in references from the recent position/spike-sorting split.
- The highest-risk merge-master footguns are already documented in `merge_methods.md`, `common_mistakes.md`, `feedback_loops.md`, and `destructive_operations.md`: bare `Master & {"nwb_file_name": ...}` is flagged as unsafe unless the field is actually on the master, and merge-aware helpers are recommended.
- This PR corrects the `RippleParameters` blob example in `destructive_operations.md` so `speed_threshold` lives under `ripple_param_dict["ripple_detection_params"]`; this matches source (`ripple/v1/ripple.py` default blob construction and `make()` consumption).

Working classification for Batch B:

| Finding class | Current status | Next action |
| --- | --- | --- |
| Merge-key hazards | Mostly covered in cross-cutting refs | Spot-check examples that still use `*Output & {...}` and keep only master-key or explicit footgun examples. |
| Blob parameter keys | Active cleanup surface | Prioritize parameter examples in `destructive_operations.md`, `ripple_pipeline.md`, `lfp_pipeline.md`, `decoding_pipeline.md`, and `position_trodes_v1_pipeline.md`. |
| Unnecessary hardcoded keys | Needs file-by-file review | Replace with discovery-first examples where the exact key is not the concept being taught. |
| Wrong / stale keys | None confirmed yet in this audit pass | Continue source-backed checks before editing. |
| Validator coverage | Existing validator catches many dict-field cases, but not all prose/blob cases | Implement only narrow C1-C3 checks after Batch B surfaces concrete examples. |

Do not broaden this into a full schema catalog. The next useful unit is a small PR that finishes the active `destructive_operations.md` parameter-blob correction, then audits one high-risk reference at a time.

### Progress log

> **Note (2026-04-28 maintenance commit):** eval IDs were renumbered to a dense 1..N sequence after the historical gaps (36, 120, 122) were filled. Specific IDs cited in this log (e.g. 127–133, 65, 131) reflect the values at the time of each PR; current IDs differ. Look up by `eval_name` in `evals.json` for the canonical mapping.

- **2026-04-28 — PR #22 (merged, commit `66d1a34`):** Batch A audit + early Batch B. Fixed two concrete wrong/copyable findings: `RippleParameters` blob shape in `destructive_operations.md` and tutorial-specific `trodes_pos_params_name` hardcode in `mua_pipeline.md`. Round-2/3 follow-ups added scoped `RippleTimesV1.populate` key, multi-row ImportedPose discovery, BurstPair populate scope, v0 legacy `fetch_nwb()[0]` cardinality, and `behavior_pipeline.md` first-row pattern.
- **2026-04-28 — PR #23 (merged, commit `1ed578c`) — Batch B narrow first pass:** focused pass over runnable code blocks in priority files (merge_methods, spyglassmixin_methods, datajoint_api, runtime_debugging, workflows, dependencies, feedback_loops, custom_pipeline_authoring). Added cardinality guards before `fetch_nwb`, replaced `assert` with explicit `if/raise ValueError` patterns, sharpened merge-master silent-no-op wording, fixed `LFPElectrodeGroup` join key in workflows, renamed shadowing `ElectrodeGroup` part class. Companion thread: promote `code_graph.py` / `db_graph.py` CLIs as the LLM-facing fact-check authority, with in-session DataJoint API as fallback (SKILL.md, common_mistakes.md, common_tables.md, datajoint_api.md, spyglassmixin_methods.md, workflows.md). SKILL.md L40 clarifies that bare CLI names mean `python skills/spyglass/scripts/<name>`. Stricter `_one()` helper in `spikesorting_v1_pipeline.md` raises on multi-row selection results instead of silently picking the first.
- **2026-04-28 — PR #24 (merged, commit `fce3f0d`) — Batch C narrow first slice:** validator-side enforcement for two of the failure modes the previous PRs fixed by hand. (a) `_singular_plural_near_miss` helper appends `(did you mean 'X'?)` to existing field-missing warnings on `_param_name` / `_params_name` and `_param_id` / `_params_id` near-misses. (b) `pk_fields_for(class_name, version)` added to `ClassIndex`; `check_insert_key_shape` extended with a partial-PK populate guard that warns when `Class.populate({...})` keys form a strict subset of the table's PK. Four regression fixtures added. Also fixed an upstream parser bug where `_index.parse_definition` only recognized exactly `---` as the divider — real Spyglass source uses both `---` and `----` (e.g. `RippleParameters` at `ripple/v1/ripple.py:140`); now any run of 3+ dashes is recognized.
- **2026-04-28 — Batch 1 eval run (iteration-1, no PR):** ran the Batch D evals (and 7 adjacent merge-gotcha evals) against current SKILL.md. with_skill swept 14/14 full-pass after a forbidden-substring relaxation on evals 125 and 129 (commit `178f678`); baseline 11/14. Largest delta on the under-specified-prompt case (eval-130 `key-hygiene-discovery-before-fetch`): with_skill 6/6 vs baseline 0/6 — confirms the discovery-first guidance moves behavior. Workspace under `skills/spyglass-workspace/iteration-1/` (gitignored); run summary in `BATCHES.md`.
- **2026-04-28 — Batch D evals (this PR, #25):** seven behavioral evals (ids 127–133) testing whether the agent verifies keys, routes to the right authority, and abstains when runtime facts are unavailable. Coverage: singular/plural typo (127), blob key vs heading (128), merge-master silent no-op (129), partial-PK populate scope (130), v0/v1 cross-version copy (131), custom runtime-only table (132), discovery-before-fetch (133). Verification-route assertions distinguish three contexts: agent path (bundled `code_graph.py` / `db_graph.py`), user path (`Table.heading.primary_key`), source-read fallback. Bundled scripts framed as agent tools, NOT universal user commands; required substrings stay portable. Per skill-creator review: narrow-string forbiddens (`"Yes, that's enough"` etc.) replaced with strengthened behavioral checks; eval 131 tier collapsed to existing `disambiguation` (matches eval 65's `disamb-spikesortingv0-vs-v1`) rather than introducing a topic-split tier.

### Remaining work

- **Batch C remaining slices** — singular/plural and partial-PK populate landed in PR #24. Still open: C2 blob-shape guard (warn when prose implies nested parameter keys are heading fields); broader C1 extensions (e.g., merge-master upstream-field warning beyond what `check_restriction_fields` already covers). Open as follow-up only if recurring failures justify the validator complexity.
- **Eval coverage gap** — skill-creator review of PR #25 flagged that eval 127 only pins the `trodes_pos_param_name` typo; the broader singular/plural family (e.g. `MoseqModelParams.model_params_name` from `common_mistakes.md:107`) is unpinned. Worth a single follow-up eval if drift recurs in this family.
- **Batch E maintainer checklist** — open only if drift continues recurring after the validator + evals catch most regressions in flight.

## Batch B — reference cleanup

Work reference-by-reference. Do not bulk rewrite prose.

Priority order:

1. `merge_methods.md` and `spyglassmixin_methods.md` — merge-key and `fetch_nwb()` mistakes produce silent wrong answers.
2. Pipeline references that show runnable insert/populate snippets:
   - `spikesorting_v1_pipeline.md`
   - `position_pipeline.md`
   - `position_trodes_v1_pipeline.md`
   - `position_dlc_v1_pipeline.md`
   - `lfp_pipeline.md`
   - `ripple_pipeline.md`
   - `decoding_pipeline.md`
   - `linearization_pipeline.md`
3. Cross-cutting references:
   - `datajoint_api.md`
   - `runtime_debugging.md`
   - `workflows.md`
   - `common_mistakes.md`

For each file:

- Replace unnecessary concrete key lists with discovery-first examples.
- Keep one canonical example per workflow where concrete keys are needed.
- Add a short warning only where the trap is local to that workflow.
- Avoid repeating the global Evidence Expectations section.

## Batch C — validator hardening

Extend `skills/spyglass/scripts/validate_skill.py` with targeted checks. Keep the implementation AST/markdown-only and no-DB.

### C1. Dict restriction / insert field checks

Build on the existing dict-restriction field checker.

Enhancements:

- Detect more relation shapes around dict literals:
  - `(Table & {...})`
  - `Table.insert1({...})`
  - `Table.insert([...])`
  - `Table.populate({...})`
  - `(MergeMaster & {...})`
- Fail when a dict field is neither in the table heading nor explicitly marked as runtime-only or illustrative.
- For merge masters with only `merge_id`, warn on upstream fields used with `& {...}` and suggest merge-aware methods.

### C2. Parameter blob guard

Warn when prose implies nested parameter keys are table columns.

Examples to catch:

- "`foo_param` is a key of `SomeParameters`" when source only has `params` / `parameter_dict` blob.
- Dict examples that mix top-level PK fields and nested blob keys in the same restriction.

Failure level: warning unless the example is executable code that would definitely fail.

### C3. Singular/plural near-miss checker

Warn on likely key near-misses when the source table contains the opposite spelling:

- `_param_name` vs `_params_name`
- `_param_id` vs `_params_id`
- `position_info_param_name` in v1-only references

This should be a narrow allowlisted check, not fuzzy matching across every word in every file.

### C4. Regression fixtures

Add one bad fixture and one safe fixture per rule to `skills/spyglass/tests/test_validator_regressions.py`.

Required fixtures:

- Unknown dict field against a known table.
- Merge master restricted by upstream key with `&`.
- Merge master routed through `merge_restrict`.
- Blob nested key described as a heading field.
- Blob nested key described as requiring source / row inspection.
- Singular/plural parameter-name trap.

## Batch D — eval coverage

Add a small eval batch focused on key invention and verification behavior.

High-value scenarios:

1. Plausible but nonexistent key on a real table.
2. Key exists on a part/upstream table but not on the merge master.
3. v0/v1 key difference where the tempting answer copies the other version.
4. Parameter key lives inside a blob and must be traced to `make()` or actual row contents.
5. Custom pipeline table not visible to `code_graph.py`; answer should route to runtime/source inspection.
6. Source table exists but runtime heading or row state is unknown; answer should avoid claiming current rows.
7. User asks for insert/fetch code before providing enough key context; answer should verify first or show discovery code.

Eval scoring should require:

- correct final guidance,
- no invented key names,
- appropriate verification route,
- abstention or hypothesis language when evidence is unavailable.

## Batch E — optional reference authoring checklist

If key mistakes continue recurring after B-D, add a short checklist to the contributor-facing docs or PR template:

```text
If this change adds a Spyglass restriction, insert, fetch, populate, or merge example:
- Did you verify each field against source or db_graph?
- Is the example source/static or runtime-specific?
- Are merge masters handled with merge-aware helpers?
- Are blob parameter keys separated from table heading fields?
- Does an eval or validator fixture cover the failure mode?
```

Do not add this to `SKILL.md`; it is maintainer guidance, not runtime skill behavior.

## Validation commands

Use the current Spyglass source checkout:

```bash
python skills/spyglass/scripts/validate_skill.py \
  --spyglass-src /Users/edeno/Documents/GitHub/spyglass/src

python skills/spyglass/tests/test_validator_regressions.py \
  --spyglass-src /Users/edeno/Documents/GitHub/spyglass/src
```

If the source checkout is unavailable, do not claim key correctness. Mark the review as static-only and defer source-backed validation.

## Stop rules

Stop and reassess if:

- The validator implementation starts needing a second DataJoint-definition parser.
- The reference cleanup turns into a full schema catalog.
- A rule produces many false positives on safe examples.
- The evals become tests of wording rather than unsupported key invention.
- Runtime DB facts are being asserted from source-only evidence.

## Expected outcome

After this plan, references should still be useful to humans and LLMs, but exact keys should be evidence-backed rather than memorized. The skill should teach agents to ask the repo or database for table/key facts, and the validator/evals should catch the most likely regressions before they ship.
