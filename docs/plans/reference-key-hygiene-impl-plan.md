# Implementation plan — reference key hygiene and validator coverage

**Date:** 2026-04-28
**Status:** Draft.
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
