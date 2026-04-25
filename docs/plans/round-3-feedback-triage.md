# Round 3 — feedback triage

Companion to `round-3-feedback-organization.md`. For each feedback item: a
verdict (**Accept** / **Accept with modification** / **Reject** / **Defer
upstream**) plus the concrete action and the reasoning. Driven by:

- Resolved scope decisions §0 of the organization doc.
- Re-reading the relevant evals end-to-end (IDs 19, 30–35, 51–58, etc.).
- The skill's current triggering and routing posture (`SKILL.md` Core
  Directives + Reference Routing).

Verdict legend:

| Tag | Meaning |
|-----|---------|
| **Accept** | Action lands in this skill repo as-is. |
| **Modify** | Idea is right, but action is narrower / different from what was suggested. |
| **Reject** | Disagree on technical or scope grounds; reasoning recorded. |
| **Defer upstream** | Skill is not the right venue; tracked for a Spyglass repo issue/PR. Per §0.4, when the upstream lands, **remove** the eval. |

---

## 1. Cross-cutting themes — verdicts

### 1a. Bypass philosophy
**Verdict: Accept (already partially in skill).** Apply uniformly.

`destructive_operations.md` already names the bypasses. The drift is in the
*evals* — many forbidden-substring lists don't include `update1`,
`super_delete()` (some only list `super_delete(warn=False)`),
`force_permission=True`, or `delete_quick`.

Action:
- Sweep all destructive-flavored evals (24, 34, 36 [if kept], 43, 56 if
  edited, 85) and make their `forbidden_substrings` lists union to:
  `super_delete`, `super_delete(warn=False)`, `force_permission=True`,
  `delete_quick`, `update1`.
- Edit `destructive_operations.md`: bypasses appear once, in a "what to do
  if a user explicitly asks" section, framed as "redirect to admin," not in
  the main flow.

### 1b. "Show me how" vs. "do it for me"
**Verdict: Accept, scoped.** §0.1 confirmed the skill is for advice + code
generation in a help role — that explicitly *includes* code generation, so
we don't want a blanket "always teach, never do." Compromise:
- For pipeline executions and merge_id resolution, default to a code block
  the user runs themselves; annotate what each step is.
- Add a one-line norm to SKILL.md Core Directives: when the answer is more
  than a one-liner, show *and* explain the steps so the user can read the
  shape, not just paste it.

### 1c. Move away from env-var configuration
**Verdict: Reject for now.** `SPYGLASS_BASE_DIR` is the actual mechanism
Spyglass uses (`spyglass.settings`); eliminating it from skill output would
diverge from the source of truth. `setup_config.md` should keep documenting
it. Sam's intent ("don't recommend env vars as the canonical user-facing
config") is accomplished by the install script (`scripts/install.py`) —
we already point users there from `setup_install.md`.

If the user runs `install.py`, env vars are an implementation detail; if
the user is debugging config, env vars are part of the diagnostic. Both
are correct postures.

### 1d. Maintenance burden
**Verdict: Accept as ongoing concern.** No code action this round.
Track: Spyglass-version sweep cadence — open a separate issue.

### 1e. Param/term documentation in docstrings (IDs 30, 5X, 58, etc.)
**Verdict: Defer upstream where applicable, keep eval where it tests
*reasoning*, not memorization.**

- ID 30 (ripple params copy-paste): **Keep.** Tests pushback on a
  copy-paste-without-understanding pattern, not param trivia. Sam's
  suggestion to put definitions in docstrings is right *and* the eval is
  about behavior that no docstring fixes — the user explicitly says "I
  don't know what these do." That's the pushback the eval measures.
- ID 58 (`target_sampling_rate` Nyquist): **Keep.** Tests
  *consequence reasoning*, not name lookup. A docstring saying "downsampled
  rate" wouldn't replace the Nyquist-implication answer.
- True trivia evals (if any creep in): drop.

### 1f. Prompt realism
**Verdict: Accept selectively.** Specific eval-level decisions in §2.

### 1g. Generic placeholders (`edeno` → `<database_user>`)
**Verdict: Accept.** Find/replace pass over evals.json. Cheap, removes a
small but real mis-trigger risk.

---

## 2. Per-eval verdicts

### 2a. Filed issues (#9–11)

| Issue | Verdict | Action |
|-------|---------|--------|
| **#9** — gamma/theta from LFPBand, not LFPOutput | **Modify** | Rewrite eval to source from `LFPBandV1`. Project band names through the selection table. The eval as-written is technically wrong, not just suboptimal. |
| **#10** — upstream fetch error realism | **Accept (drop or rescope)** | Sam is right: the scenario implies a non-cascading delete, which is a bigger DB issue. **Drop** unless we can rescope to a realistic trigger (e.g. user's own broken populate not the missing-upstream framing). |
| **#11** — BrainRegion route | **Modify** | Keep as a *chained-table* eval; rewrite the prompt to explicitly require traversal. If the prompt doesn't require chaining, the simpler `CurationV1.get_sort_group_info()` is the right answer and the eval is testing memorization of the wrong path. |

### 2b. PR #13 — already-proposed edits

| ID | Verdict | Notes |
|----|---------|-------|
| 19 (LFP flow) | **Accept** | Electrode-discovery step + Theta-at-LFPSelection forbidden are both correct. |
| 27 (DecodingParameters) | **Accept** | Fallback display step is a real escape hatch users need. |
| 28 (joins) | **Accept** | `set(...fetch(...))` is the canonical idiom. |
| 33 (insert_sessions) | **Accept** | `fetch_nwb` substring belongs in the required list. |
| 34 (delete forbidden subs) | **Accept** | `delete_quick` belongs in `forbidden_substrings`. |
| 35 (merge empty list) | **Modify** | Keep eval but lighten — the spyglass-side fix in [LorenFrankLab/spyglass#1579](https://github.com/LorenFrankLab/spyglass/issues/1579) may obsolete the error-message detail. Track upstream; eval describes *current* behavior until then. |
| 36 (merge cascade NetworkX) | **Drop** | Per §0.4: behavior is fixed in latest Spyglass. Remove (don't comment out). |
| 37 (populate non-PK dict) | **Accept** | "in the v1 pipeline" disambiguation is correct. |
| 38 (DLC PositionIntervalMap) | **Drop** | Per §0.4: fixed in latest Spyglass. Remove. |
| 42 (schema drift) | **Accept** | CHANGELOG.md + admin direction is the correct user-facing instruction. |
| 87 (update1 forbidden) | **Accept** | Already aligned with §1a. |

### 2c. `temp-feedback.md` per-eval

Realism / scope:

| ID | Verdict | Notes |
|----|---------|-------|
| **19** (aggr) | **Modify** | Reframe to a usage prompt that has aggr as one valid answer, not the only one. Workshop signal is valid — it's not a frequent ask. |
| **31** (env drift) | **Defer upstream + reframe** | Sam is right on both: (a) Spyglass should `try/except` the import with a pinned-version error (open issue), (b) the prompt's clean "I know I caused env drift" framing is unrealistic. Rewrite the prompt to a generic `ImportError` traceback and require the agent to ask "did you upgrade anything recently?" before pinning. |
| **42** (schema drift) | **Accept (PR #13's edit)** | The CHANGELOG-direction edit already addresses Sam's point that user-side `.alter()` is overreach. |
| **5X** (table classification 54–58) | **Modify** | Don't drop these — they're not pure trivia, they distinguish manual-vs-selection roles users actually confuse. **But** add a usage-flavored sibling: "given table X, what's the next thing I can do with it?" That's the question Sam reports getting in workshops. Replacement, not deletion. |
| **76** (peripheral table) | **Modify** | Reframe to "why is `X` connected to `Y`?" — Sam's concrete suggestion. The peripheral-table concept stays, the prompt shape changes. |

Should be upstream code fix, not an eval (per §0.4 — when fixed, remove):

| ID | Verdict | Issue to file in Spyglass |
|----|---------|--------------------------|
| **31** | **Defer upstream** | `try/except` import + raise pinned-version. |
| **35** | **Defer upstream** | Already filed: [#1579](https://github.com/LorenFrankLab/spyglass/issues/1579). |
| **36** | **Defer upstream → already fixed** | Drop eval. |
| **37** | **Modify** | Sam's suggestion (warn on null restriction in `__and__`/populate) is a genuinely good DataJoint-level change but unlikely to land soon. Keep the eval as-is in the meantime; file as nice-to-have on the Spyglass side. |
| **38** | **Defer upstream → already fixed** | Drop eval. |
| **41** | **Defer upstream** | File the assertion / sensible default for `_set_dj_config_stores`. Then drop the eval. |

Use existing DataJoint / Spyglass functionality:

| ID | Verdict | Action |
|----|---------|--------|
| **28** | **Accept** | Add a one-liner xref to the common-mistakes section on `proj`. |
| **45** | **Accept** | Add `InsertError` to required substrings or behavioral checks; mention in the routing for ingestion errors. |
| **69** | **Accept** | Update expected output to fetch `UserEnvironment` and diff, not a generic "check your env" answer. Concrete, testable. |
| **74** | **Accept** | Require `Table.primary_key` in the answer. |
| **78** | **Accept** | Require `Table.parts` in the answer. |
| **87** | **Accept** | Require `Table.descendants` in the answer (and per PR #13 forbid `update1`). |

Conceptual gaps:

| ID / topic | Verdict | Action |
|------------|---------|--------|
| **52** (suffix indicators) | **Accept** | Add an explicit "not enforced; lookalikes exist" caveat to the expected output. The current text presents suffixes as more reliable than they are. |
| **62 / 64** (group tables) | **Accept** | Add a `group_tables.md` reference (small file) covering the concept; route from `common_tables.md` and `spyglassmixin_methods.md`. Sam's workshop notes are the source. |
| **No ID** (long-distance restrictions) | **Accept** | Add 1–2 evals covering long-distance restriction patterns (`Table & (Other & {...})`). Useful concept currently uncovered. |

Skill-transparency questions:

| ID | Verdict | Action |
|----|---------|--------|
| **33** (PR mentions) | **Accept** | Skill prose should describe current code state, not in-flight PRs. Sweep references for `PR #NNNN` mentions; convert to "this works in Spyglass ≥ X" if the merge is on main, or remove if speculative. The "check for patch updates" script idea is **deferred** — useful but separate work. |
| **82** (silent failure) | **Modify** | Sam is right that warnings *should* exist. Verify by re-running the relevant code path against current Spyglass. If a warning fires, rewrite the eval to test that the agent surfaces the warning rather than reaching for "silent" framing. If no warning fires, file an upstream issue and keep the eval. |

Bypasses (apply §1a):

| ID | Verdict |
|----|---------|
| **24, 43, 85** | **Accept** — covered by the §1a sweep; no separate action. |

---

## 3. Reference-file feedback verdicts

| File | Item | Verdict | Action |
|------|------|---------|--------|
| `references/X_pipeline.md` | Move to core repo | **Reject** (per §0.2) | Pipeline references stay here. |
| `custom_pipeline_authoring.md` | Permissions/roles section | **Accept** | Add a "Testing for user permissions and roles" subsection covering the SQL probe and the DataJoint dispatch. |
| `destructive_operations.md` | `.func()` vs `rel.func()` notation | **Accept** | Standardize on `(Table & key).func(...)` form for restriction-bearing examples; keep `Table.func(...)` for classmethod calls. Apply consistently. |
| `destructive_operations.md` | Bypass mentions | **Accept** | Move bypasses behind a "if explicitly asked" framing per §1a. |
| `destructive_operations.md` | `delete_downstream_merge` removed-function refs | **Accept** | Drop the references; assume current Spyglass. |
| `setup_troubleshooting.md` | `DLC_BASE_DIR` → `POSE_BASE_DIR` | **Defer per §0.6** | Update post-deprecation. |
| `ingestion.md` | Migrate subset upstream | **Reject (per §0.2)** | Stays here. |

---

## 4. Upstream Spyglass fixes — to file

Per §0.4, when these merge, **remove** the corresponding eval rather than
keep a back-compat copy.

| # | Fix | Origin | Eval to remove on merge |
|---|-----|--------|------------------------|
| 1 | `try/except` SpikeInterface import → raise pinned-version error | feedback ID 31 | 31 (or rewrite once landed) |
| 2 | Simplify merge API / clearer empty-list error | [LorenFrankLab/spyglass#1579](https://github.com/LorenFrankLab/spyglass/issues/1579) | 35 |
| 3 | (Already merged) `declare_all_merge_tables` in delete cascade | feedback ID 36 / PR #13 | 36 — drop now |
| 4 | (Already merged) `convert_epoch_interval_name_to_position_interval_name` empty-map fix | feedback ID 38 / PR #13 | 38 — drop now |
| 5 | Warn on null restriction in `__and__` / `populate` | feedback ID 37 | 37 (defer; keep eval until then) |
| 6 | Add assertion / sensible default to `_set_dj_config_stores` | feedback ID 41 | 41 (defer; keep until then) |

---

## 5. Net change set for an impl plan

Concrete, ready to plan against. Grouped by file/script per repo convention.

### `evals/evals.json`
- **Drop** evals 36, 38.
- **Rewrite** evals 9 (gamma/theta → LFPBand), 11 (chained-table framing or drop), 31 (generic ImportError prompt), 76 (why-X-connected-to-Y), 82 (verify warning behavior).
- **Modify** evals 19, 5X (54–58), 52 (caveat suffix indicators), 28 (proj xref), 45 (`InsertError`), 69 (`UserEnvironment` diff), 74 (`Table.primary_key`), 78 (`Table.parts`), 87 (`Table.descendants`).
- **Add** long-distance-restriction eval(s); add usage-shaped sibling for the table-classification block (5X).
- **Sweep §1a**: union forbidden-substring lists across destructive evals.
- **Sweep §1g**: replace literal `edeno` with `<database_user>`.
- **Sweep §2c-skill-transparency**: remove or restate `PR #NNNN` mentions in `expected_output` prose.

### `references/destructive_operations.md`
- Standardize `.func()` vs `(rel).func()` notation.
- Move bypass discussion behind an "if explicitly asked" frame.
- Drop `delete_downstream_merge` removed-function references.

### `references/custom_pipeline_authoring.md`
- Add "Testing for user permissions and roles" subsection.

### New file: `references/group_tables.md`
- Short reference covering the group-table concept; cross-link from
  `common_tables.md` and `spyglassmixin_methods.md`.

### `SKILL.md` (Core Directives)
- One line on §1b posture: code generation is fine, but accompany
  multi-step flows with a brief "what each step is doing" annotation.

### Issues to file upstream (Spyglass)
- Items 1, 2, 5, 6 in §4 above.

---

## 6. Out of scope this round (per §0)

Recorded for completeness, not actionable now:

- Read-only DB user for agents (§0.3).
- Lab-member-sourced prompts (§0.5).
- `DLC_BASE_DIR` → `POSE_BASE_DIR` rename (§0.6).
- Pipeline references migration upstream (§0.2 — stays here).
- Patch-update-checking script (§2c-33 — useful but separate).
