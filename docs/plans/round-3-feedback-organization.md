# Round 3 — Sam Bray feedback organization

Source material:
- GitHub issues [#9](https://github.com/edeno/spyglass-skill/issues/9), [#10](https://github.com/edeno/spyglass-skill/issues/10), [#11](https://github.com/edeno/spyglass-skill/issues/11)
- PR [#13 (evals review)](https://github.com/edeno/spyglass-skill/pull/13)
- `~/Downloads/temp-feedback.md` (per-eval + reference-file notes)

Resolved decisions are noted inline below. Open per-eval items become the
backlog for a follow-up impl plan.

---

## 0. Resolved scope decisions

These were settled after Sam's review and bound the rest of this work:

1. **Skill purpose:** advise users on code and generate code, in a support/help
   role or otherwise. Not transparent infrastructure — users *do* interrogate
   it.
2. **Pipeline references:** stay in this repo. The skill may layer
   agent-specific framing on top of them; we are not migrating them upstream.
3. **Read-only DB user for agents:** not yet. Revisit as agent usage rolls out.
4. **Out-of-date evals (36, 38, etc.):** if Spyglass already fixes the
   underlying issue, **remove** the eval rather than maintain it for older
   versions. Replace with new questions where useful.
5. **Lab-member-sourced prompts:** will solicit later, not this session.
6. **`DLC_BASE_DIR` → `POSE_BASE_DIR`:** update after the deprecation lands,
   not now.

---

## 1. Cross-cutting strategic themes

### 1a. Bypass philosophy (IDs 24, 34, 36, 43, 85; `destructive_operations.md`)
Skill should not surface `super_delete`, `super_delete(warn=False)`,
`force_permission=True`, `delete_quick`, `update1` (for in-place edits), or
`delete_downstream_merge`. Default: don't mention; redirect to admin or to
the proper learning path. Only respond with "let's try X first" if the user
themselves names the bypass.

PR #13 already added `delete_quick` (ID 34) and `update1` (ID 87) to
`forbidden_substrings`. Apply uniformly.

### 1b. "Show me how" vs. "do it for me"
Many evals lean toward executing on the user's behalf (merge_id resolution,
dataframe fetches). Sam wants the skill to lean toward teaching, both for UX
and to train potential contributors. Make the posture explicit in SKILL.md.

Compatible with §0.1: a help/code-generation skill can still favor explanation
over silent execution.

### 1c. Move away from env-var configuration (`SPYGLASS_BASE_DIR`)
Stop steering users toward env-var configuration as the canonical path.

### 1d. Maintenance burden
Open question raised twice (`setup_troubleshooting.md`,
`references/X_pipeline.md`): how does the skill stay in sync with the
codebase? §0.2 settles location (stays here); we still need a maintenance
cadence — likely a periodic Spyglass-version sweep rather than per-change
updates.

### 1e. Param/term documentation belongs in docstrings (IDs 30, 5X)
When an eval exists *only* to explain a parameter or table-class concept,
the fix is a docstring upstream, not eval enumeration.

### 1f. Prompt realism
Several prompts assume artificially high user understanding:
- Naming the database port, key uniqueness logic, class-hierarchy observations.
- Knowing the causality of "environmental drift" / "schema drift" (IDs 31, 42).
- Single-word table-classification quizzes (IDs 5X, 76).
- Aggr usage (ID 19) — Sam has never been asked this in workshops.

Generalize toward "what can X table do?" / "why is X connected to Y?" over
taxonomy quizzes.

### 1g. Generic placeholders
Replace literal `edeno` with `<database_user>` (or similar) so the agent
treats it as a placeholder.

---

## 2. Per-eval feedback

### 2a. Filed issues (need decisions)
- **#9 — eval at L287 (gamma/theta ratio):** source from `LFPBandV1`, not
  `LFPOutput`. Requires projecting band names into selection-table entries.
- **#10 — eval at L975 (upstream fetch error):** Sam doesn't see when this
  arises in practice; missing upstream entry implies a non-cascading delete,
  i.e. a bigger DB issue than the eval suggests. Consider removing or rescoping.
- **#11 — eval at L1030 (BrainRegion route):** too complex;
  `CurationV1.get_sort_group_info()` does the same thing. Keep only if the
  eval is *intentionally* testing chained-table reasoning — make that
  explicit.

### 2b. PR #13 — already-proposed edits

| ID | Change |
|----|--------|
| 19 | Add electrode-discovery step; forbid applying Theta filter at the `LFPSelection` step |
| 27 | Add fallback `DecodingOutput.ClusterlessDecodingV1 & {...}` display when no match |
| 28 | Switch to `set((...).fetch('nwb_file_name'))` over `as_dict=True` |
| 33 | Add `fetch_nwb` to `required_substrings` |
| 34 | Add `delete_quick` to `forbidden_substrings` |
| 35 | Marked confusing → upstream issue [LorenFrankLab/spyglass#1579](https://github.com/LorenFrankLab/spyglass/issues/1579) |
| 36 | **Commented out** — merge tables now imported automatically for cascade. Per §0.4: **remove** rather than comment. |
| 37 | Clarify "in the v1 pipeline" |
| 38 | **Commented out** — fixed in latest Spyglass. Per §0.4: **remove**. |
| 42 | Replace `.alter()` direction with "consult CHANGELOG.md, admin runs alter" |
| 87 | Add `update1` to `forbidden_substrings` |

### 2c. `temp-feedback.md` per-eval notes (not in PR #13)

**Bypass / philosophy** (apply §1a uniformly)
- **IDs 24, 43, 85** — `super_delete`, in-place edits via `update1`.

**Realism / scope concerns** (apply §1f)
- **ID 19:** is `aggr` realistic? Workshop attendees don't seem to care.
- **ID 31:** "environmental drift" framing too clean — likely back-and-forth
  in practice.
- **ID 42:** schema-drift causality is jargon for the agent.
- **ID 5X:** replace table-classification quizzes with usage questions, or
  rely on suffix pattern-matching.
- **ID 76:** single-word answers about peripheral tables aren't realistic;
  "why is X connected to Y?" is.

**Should be an upstream code fix, not an eval** (per §0.4 — if Spyglass fixes
it, remove the eval)
- **ID 31:** Spyglass should `try/except` the missing import and raise
  helpfully.
- **ID 35:** "If the fix is fewer lines than the explanation, just make the
  fix." Long-term: simplify the merge API.
- **ID 36:** add `declare_all_merge_tables` to `delete` (already obviated
  per PR #13).
- **ID 37:** warn on null restriction in `__and__` / `populate`.
- **ID 41:** add the assertion (or sensible default) to
  `_set_dj_config_stores`.

**Use existing DataJoint / Spyglass functionality**
- **ID 28:** reference the common-mistakes section on `proj`.
- **ID 45:** mention the `InsertError` table.
- **ID 69:** fetch from `UserEnvironment` and diff.
- **ID 74:** demonstrate `Table.primary_key`.
- **ID 78:** demonstrate `Table.parts`.
- **ID 87:** demonstrate `Table.descendants`.

**Conceptual gaps**
- **ID 52:** suffix indicators are presented as reliable; if they aren't
  enforced, say so.
- **IDs 62 / 64:** group-table concept needs better docs (Sam's workshop
  repo has notes).
- **No ID:** no evals cover long-distance restrictions — add if useful.

**Skill-transparency questions**
- **ID 33:** skills should describe current codebase state, not PRs.
  Suggestion: a script that checks for patch updates on main and offers
  them.
- **ID 82:** "silent failure" — warnings should exist, so this may be jargon
  for the agent rather than reality. Verify before keeping the eval as-is.

---

## 3. Reference file feedback

Per §0.2 these stay in this repo; the edits below are what Sam flagged.

### `references/X_pipeline.md` (all pipeline references)
Stay here. Add agent-specific framing on top of them where useful.

### `custom_pipeline_authoring.md`
- Add operational notes on **testing for user permissions / roles**.
- Currently unclear whether the skill provides MySQL/DataJoint commands
  for role-checking, or assumes Claude knows them.

### `destructive_operations.md`
- Notation inconsistency: some examples use `.func(args)`, others use
  `rel.func(args)`. May affect agent performance — pick one.
- Drop safety-bypass mentions (`super_delete`, `force_permission=True`) per
  §1a; reframe as "if a user wishes to X, suggest contacting an admin."
- `delete_downstream_merge` references removed functions — drop those
  mentions; assume users are on the latest patch.

### `setup_troubleshooting.md`
- `DLC_BASE_DIR` → `POSE_BASE_DIR`: **defer per §0.6** until deprecation
  lands.
- Maintenance cadence question (see §1d).

### `ingestion.md`
- Subset belongs as upstream docs or as a troubleshooting section in the
  ingestion notebook. Since pipeline references stay here (§0.2), this is
  optional duplication, not a migration.

---

## 4. Upstream Spyglass fixes proposed

Per §0.4, when Spyglass merges a fix the corresponding eval should be
**removed**, not kept for back-compat. Replace with new questions where
useful.

1. **ID 31:** `try/except` on import errors → raise with pinned-version
   suggestion.
2. **ID 35:** simplify merge API — tracked in
   [LorenFrankLab/spyglass#1579](https://github.com/LorenFrankLab/spyglass/issues/1579).
3. **ID 36:** add `declare_all_merge_tables` to `delete` (already in latest
   Spyglass).
4. **ID 37:** warn on null restriction in `__and__` / `populate`.
5. **ID 41:** add assertion / sensible default to `_set_dj_config_stores`.
6. **ID 38:** `convert_epoch_interval_name_to_position_interval_name` empty
   map — already fixed in latest Spyglass.

---

## 5. Backlog for follow-up impl plan

Concrete eval / reference edits, ready to script-centric per the repo's
plan convention:

- **Eval removals (per §0.4):** 36, 38, plus any others confirmed obsoleted
  by current Spyglass.
- **Eval edits per §1a:** scrub bypass mentions across 24, 43, 85.
- **Eval edits per §1f:** rescope or remove 19 (aggr), 31, 42 (drift framing),
  5X / 76 (taxonomy quizzes).
- **Eval enhancements per §1e and "use existing functionality":** 28
  (`proj` xref), 45 (`InsertError`), 69 (`UserEnvironment` diff), 74
  (`Table.primary_key`), 78 (`Table.parts`), 87 (`Table.descendants`).
- **New evals:** long-distance restrictions; "what can X table do?" /
  "why is X connected to Y?" usage questions; group-table concept
  (62 / 64 follow-up).
- **Issue triage:** decisions on #9 (rewire to `LFPBandV1`), #10 (likely
  remove), #11 (remove or mark as chained-table test).
- **Reference edits:** `destructive_operations.md` notation + bypass
  scrub; `custom_pipeline_authoring.md` permissions/roles section;
  `references/X_pipeline.md` agent-specific framing pass.
- **SKILL.md:** make the "show how, don't do for" posture explicit
  (§1b); deprecate env-var-first configuration guidance (§1c); add
  `<database_user>` placeholder convention (§1g).

Out of scope for this round per §0:
- Migrating pipeline references upstream.
- Read-only DB user for agents.
- Soliciting lab-member prompts.
- `DLC_BASE_DIR` rename.
