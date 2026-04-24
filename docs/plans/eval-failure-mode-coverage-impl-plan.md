# Implementation plan — add 11 evals (IDs 79–89) covering underrepresented failure modes

**Date:** 2026-04-24 (revised after independent review + v0→v1 extrapolation audit)
**Status:** **Executed 2026-04-24.** All 8 planned commits landed (`3f73177` → `1acfe2b`) plus 3 audit-driven follow-ups: `eeb5daf` (eval 80 forbidden-substring tightening to prevent denial false-positive), `d5ca431` (evals 81 + 88 `expected_output` prose corrections against live Spyglass source — part-table vs. master FK in eval 81; `filepath@analysis` vs. `AnalysisNwbfile` FK in eval 88), and `99cbd28` (stale fixture-count drift in CLAUDE.md / skills/spyglass/README.md surfaced by the post-batch doc audit). Final evals.json size: 89 (up from 78). Validator clean at `--baseline-warnings 3`. Post-batch source verification used the `spyglass` conda env's Python to introspect `RippleTimesV1.parents()`, `populate_all_common` signature, `RippleParameters.primary_key`, etc. against pinned Spyglass `0.5.5a2.dev75+g57ed4eef5`; three parallel subagents cross-checked 11/11 evals. No blocking errors found.
**Scope:** Add eleven new evals to [skills/spyglass/evals/evals.json](../../skills/spyglass/evals/evals.json) that target failure modes the current 78-eval suite under-samples: abstention under hallucination pressure (including the v0→v1 naming-extrapolation trap), resource-first reasoning, workflow recovery after partial success, counterfactual comparison of two pipeline states, and ambiguity-tolerance when a prompt is under-specified. Introduce one new tier (`workflow-recovery`) — other proposed taxonomy additions were collapsed back into existing slots after review. Fix one validator-registry gap (`InsertError`) and two skill-side references that actively seed the `SpikeSortingV1` hallucination.

## Revision history

- **r1 (original draft):** 10 evals (79–88), three new taxonomy values (`workflow-recovery` tier, `ambiguity` tier, `workflow-recovery` stage).
- **r2 (this version):** Independent review found six source-of-truth errors in the original draft (fields, FKs, parent lists) — those are fixed here against verified source. Added eval 89 targeting the v0→v1 naming-extrapolation hallucination the user surfaced after review. Collapsed the N=1 `ambiguity` tier and `workflow-recovery` stage back into existing slots. Added a final commit to fix two skill-side bugs (in SKILL.md frontmatter and merge_methods.md) that actively seed the `SpikeSortingV1` hallucination and would make eval 89 ungradable otherwise. Corrected `flatten_expectations.py` path.

## Goals and non-goals

**Goals.**

- Add eleven evals (IDs **79–89**) along this category mix:

  | Category | Count | IDs |
  | --- | --- | --- |
  | Hallucination / abstention | 4 | 79, 80, 81, 89 |
  | Resource-selection / reference-auditing | 2 | 82, 83 |
  | Workflow recovery | 2 | 84, 85 |
  | Counterfactual / comparison | 2 | 86, 87 |
  | Ambiguity (under-specified prompt) | 1 | 88 |

- Extend [evals/README.md](../../skills/spyglass/evals/README.md) with **one** new tier (`workflow-recovery`) — no new stages. Eval 85 (workflow-recovery tier) stays in the existing `pipeline-usage` stage. Eval 88 uses the existing `disambiguation` tier with a note that the choice is among under-specified alternatives, rather than inventing an N=1 `ambiguity` tier.
- Register `InsertError` in `KNOWN_CLASSES` in [scripts/validate_skill.py](../../skills/spyglass/scripts/validate_skill.py) as a hard pre-req (commit 0), so the completeness check in `check_evals_content` doesn't false-fire on eval 82 / 84.
- Fix two skill-side references that actively seed the `SpikeSortingV1` hallucination: the SKILL.md frontmatter keyword list and the `merge_methods.md` `dj.Computed` example row (commit 7).
- Keep `./skills/spyglass/scripts/validate_all.sh --baseline-warnings 180` green after every commit (current baseline per [CLAUDE.md](../../CLAUDE.md); re-check at commit time, do not pre-bump).
- Regenerate `expectations` via `skills/spyglass/evals/scripts/flatten_expectations.py` after each insert commit so the flat-list representation stays in sync.

**Non-goals.**

- Editing pipeline reference files beyond the `merge_methods.md` one-line fix in commit 7. If an eval exposes a genuine reference-side gap, file a follow-up — don't paper over it by editing the reference mid-plan.
- Bundled-script additions. Evals 82 and 83 test routing to *existing* scripts / references, not the arrival of new ones.
- Re-anonymization or re-tagging of evals 1–78.
- Skill-description (frontmatter `description:`) re-optimization — these evals don't move the triggering boundary. (The frontmatter *keyword list* edit in commit 7 removes one trigger token; this is a bug fix, not an optimization.)
- Running the full skill-creator with_skill / baseline benchmark loop. Build-out here is authoring only; a subsequent session can run `aggregate_benchmark.py` on this batch for quantitative numbers.

## Executor checklist

Eight commits, preceded by one mandatory verification step. Each commit's "validation gate" is the [Per-commit validation](#per-commit-validation) block below.

### Step -1 (mandatory) — re-verify the pre-req evidence before touching any file

The [Pre-req source verification](#pre-req-source-verification-captured-2026-04-24-against-spyglass_srchomedocumentsgithubspyglasssrc) table below was captured on a specific date. Spyglass evolves — fields get renamed, files move, part-table lists grow. Before commit 0, re-run each verification and confirm the evidence still holds. If *any* row has drifted, **stop and update the plan** — do not paper over with a guess.

```bash
# Required: SPYGLASS_SRC must point at a current checkout
test -n "$SPYGLASS_SRC" || { echo "SPYGLASS_SRC unset; see README.md"; exit 1; }
test -d "$SPYGLASS_SRC/spyglass" || { echo "$SPYGLASS_SRC/spyglass not found"; exit 1; }

# Claim-by-claim verification. Each command's expected output is stated inline.
# If any output differs from the captured evidence below, STOP.

# 1. Session has no sampling_rate
python3 -c "from spyglass.common import Session; n=Session.heading.names; assert 'sampling_rate' not in n, n; print('OK: Session has no sampling_rate')"

# 2. SpyglassMixin has no get_pk
grep -rn "def get_pk\b" "$SPYGLASS_SRC/spyglass/utils/" && echo "FAIL: get_pk now exists" || echo "OK: no get_pk"

# 3. Raw.sampling_rate is a direct secondary column
grep -n "^    sampling_rate" "$SPYGLASS_SRC/spyglass/common/common_ephys.py" | grep "float" || echo "FAIL: Raw.sampling_rate shape changed"

# 4. RippleTimesV1 has three direct parents (RippleLFPSelection, RippleParameters, PositionOutput)
grep -n -A 8 "^class RippleTimesV1" "$SPYGLASS_SRC/spyglass/ripple/v1/ripple.py" | grep -E "RippleLFPSelection|RippleParameters|PositionOutput"
# Expect three matches.

# 5. common_usage.InsertError still exists
grep -n "^class InsertError" "$SPYGLASS_SRC/spyglass/common/common_usage.py" || echo "FAIL: InsertError moved"

# 6. Bundled scripts unchanged
ls "$(pwd)/skills/spyglass/scripts/"*.py | sort
# Expect: scrub_dj_config.py, validate_skill.py, verify_spyglass_env.py

# 7. Reference-file split preserved
head -3 skills/spyglass/references/custom_pipeline_authoring.md
head -3 skills/spyglass/references/spyglassmixin_methods.md

# 8. ClusterlessDecodingSelection still has exactly 4 FK surfaces
grep -n -A 8 "^class ClusterlessDecodingSelection" "$SPYGLASS_SRC/spyglass/decoding/v1/clusterless.py"
# Expect: UnitWaveformFeaturesGroup, PositionGroup, DecodingParameters, encoding_interval, decoding_interval

# 9. position_info_param_name is v0 only; v1 uses trodes_pos_params_name
grep -rn "position_info_param_name\b" "$SPYGLASS_SRC/spyglass/position/" && echo "FAIL: v1 now has position_info_param_name"
grep -n "trodes_pos_params_name" "$SPYGLASS_SRC/spyglass/position/v1/position_trodes_position.py" | head -3

# 10. ripple_param_name (singular) is the correct PK
grep -n "ripple_param_name\b" "$SPYGLASS_SRC/spyglass/ripple/v1/ripple.py" | head -3
grep -n "ripple_params_name\b" "$SPYGLASS_SRC/spyglass/ripple/v1/ripple.py" && echo "FAIL: plural now exists"

# 11. SpikeSortingV1 does NOT exist; SpikeSorting does
grep -rn "^class SpikeSortingV1\b" "$SPYGLASS_SRC/spyglass/" && echo "FAIL: SpikeSortingV1 now exists — eval 89 premise invalidated"
grep -n "^class SpikeSorting\b" "$SPYGLASS_SRC/spyglass/spikesorting/v1/sorting.py" || echo "FAIL: SpikeSorting v1 class moved"

# 12. The two seed mentions that commit 7 removes are still there at the expected sites
grep -n "SpikeSortingV1" skills/spyglass/SKILL.md || echo "NOTE: SKILL.md seed mention already gone — skip fix 1 in commit 7"
grep -n "SpikeSortingV1" skills/spyglass/references/merge_methods.md || echo "NOTE: merge_methods.md seed mention already gone — skip fix 2 in commit 7"

# 13. flatten_expectations.py path unchanged
test -f skills/spyglass/evals/scripts/flatten_expectations.py || echo "FAIL: flatten_expectations.py moved"
```

**Interpretation rule.** "STOP" means: pause execution, open this plan, update the affected row's evidence (file path, line number, field name), and — if the change is semantic, not cosmetic — re-walk the affected eval draft before the insert commit. Specifically:

| Drift type | Impact | Action |
| --- | --- | --- |
| File moved but content identical | Cosmetic | Update file:line refs in the plan, proceed |
| Field renamed (e.g., `ripple_param_name` → something else) | Semantic | Rewrite affected eval's `required_substrings`, `expected_output`, `behavioral_checks` before inserting |
| Class / method disappeared | Premise broken | Delete or rewrite the affected eval; don't author around the hole |
| Seed mention already removed (commit 7 fix #1 or #2) | Lower scope | Skip that specific fix in commit 7; proceed with the other |
| Validator's `KNOWN_CLASSES` already has `InsertError` | Lower scope | Skip commit 0; proceed from commit 1 |

Do NOT proceed if:

- `$SPYGLASS_SRC` is unset (no source to verify against).
- `SpikeSortingV1` now exists as a real class (eval 89's entire premise is gone).
- `ripple_param_name` is not the PK of `RippleParameters` (eval 85's required substring is a hallucination against current source).

**This verification gate is not optional.** Authoring against stale evidence is exactly the failure mode the plan's r1 review caught; not re-verifying before execute would re-introduce that failure on a slower time horizon.

### Per-commit plan

| Step | What | Where | Validation gate |
| --- | --- | --- | --- |
| 0 | Register `InsertError` in `KNOWN_CLASSES` with source `spyglass/common/common_usage.py`; also add `RippleParameters` if not already present | [scripts/validate_skill.py](../../skills/spyglass/scripts/validate_skill.py) | validator |
| 1 | Extend taxonomy in `evals/README.md` with new tier `workflow-recovery`; update tier count for `workflow-recovery` (2), `adversarial` (+4 → 11), `resource-selection` (+2 → 4), `counterfactual` (+2 → 4), `disambiguation` (+1 → 4) | [evals/README.md](../../skills/spyglass/evals/README.md) | validator + flatten-check |
| 2 | Insert evals 79–81, 89 (hallucination / abstention) | [evals/evals.json](../../skills/spyglass/evals/evals.json) | flatten + validator |
| 3 | Insert evals 82–83 (resource-selection) | `evals.json` | flatten + validator |
| 4 | Insert evals 84–85 (workflow-recovery) | `evals.json` | flatten + validator |
| 5 | Insert evals 86–87 (counterfactual) | `evals.json` | flatten + validator |
| 6 | Insert eval 88 (ambiguity, using existing `disambiguation` tier) | `evals.json` | flatten + validator |
| 7 | Fix SKILL.md frontmatter keyword list and `merge_methods.md` line 49 — remove the two `SpikeSortingV1` seed mentions | [SKILL.md](../../skills/spyglass/SKILL.md), [references/merge_methods.md](../../skills/spyglass/references/merge_methods.md) | validator |

Commits split by category so each diff is independently reviewable against its authoring rubric. Commit 0 lands first so the validator can't false-flag legitimate new substring claims. Commit 7 lands last so eval 89 (in commit 2) is already in place when the skill-side seed mentions are removed — that way the eval is catching real behavior, not just the absence of one keyword.

If a validation gate fails, fix the drift — do not bump `--baseline-warnings` and do not skip hooks. The `validate_all.sh` warning budget is load-bearing.

## Pre-req source verification (captured 2026-04-24 against $SPYGLASS_SRC=$HOME/Documents/GitHub/spyglass/src)

Ran every claim against the pinned Spyglass source before authoring. Original r1 draft had six errors; all are fixed in the per-eval drafts below. This table is the audit trail.

| Claim | Status | Evidence (source ref) |
| --- | --- | --- |
| `Session` has no `sampling_rate` column | ✅ **verified** | `common/common_session.py:19` — `class Session(SpyglassIngestion, dj.Imported)` definition lists `session_id, session_description, session_start_time, timestamps_reference_time, experiment_description`; no `sampling_rate`. |
| `SpyglassMixin` has no `get_pk()` method | ✅ **verified** | `grep -rn "def get_pk\b" $SPYGLASS_SRC/spyglass/utils/` returns no hits. |
| `Raw.sampling_rate` IS a direct secondary column | ✅ **verified** (reframes r1's eval 79 redirect — `fetch_nwb` is *not* required; `(Raw & key).fetch1('sampling_rate')` works directly) | `common/common_ephys.py:282` — `sampling_rate: float  # Sampling rate calculated from data, in Hz`. |
| `RippleTimesV1` has **three** direct parents (r1 draft said one) | ❌ **r1 wrong — corrected** | `ripple/v1/ripple.py:182–188`: `-> RippleLFPSelection`, `-> RippleParameters`, `-> PositionOutput.proj(pos_merge_id='merge_id')`, plus `-> AnalysisNwbfile` (storage). Eval 81 rewritten to list all three semantic parents. |
| `common_usage.InsertError` captures `populate_all_common` silent skips | ✅ **verified** | `common/common_usage.py:43` — `class InsertError(dj.Manual)`. Referenced from `common/populate_all_common.py:44,71,257,270`. Needs `KNOWN_CLASSES` registration (commit 0). |
| `scripts/verify_spyglass_env.py` and `scripts/scrub_dj_config.py` are the only user-facing bundled scripts | ✅ **verified** | `ls skills/spyglass/scripts/*.py` returns those two plus `validate_skill.py` (maintainer-only, not user-facing). `scripts/README.md` confirms. |
| `custom_pipeline_authoring.md` is author-side, `spyglassmixin_methods.md` is consumer-side | ✅ **verified** | Opening paragraphs of each file make the split explicit. |
| `ClusterlessDecodingSelection` FK surfaces | ⚠️ **r1 over-extended — corrected** | `decoding/v1/clusterless.py:83–91`: exactly four FK targets (`UnitWaveformFeaturesGroup`, `PositionGroup`, `DecodingParameters`, `IntervalList.proj(encoding_interval=...)`, `IntervalList.proj(decoding_interval=...)`) plus one secondary bool (`estimate_decoding_params`). R1 draft listed five "selection-level surfaces" including `sorter_params_name`, which is upstream of the selection via the sorting chain — not a direct FK. Eval 86 rewritten to enumerate only the four direct surfaces and note the upstream chain separately. |
| `position_info_param_name` is a **v0** field, not v1 | ❌ **r1 wrong — rewritten** | `common/common_position.py:45,69` defines `position_info_param_name` on the v0 `PositionInfoParameters` table. v1 position selections use `trodes_pos_params_name` (`position/v1/position_trodes_position.py:30,55`) or `position_group_name` (`decoding/v1/core.py:130,133`). Eval 87 rewritten around `trodes_pos_params_name` (v1 pipeline-usage). |
| `RippleParameters` PK is `ripple_param_name` (singular), not `ripple_params_name` | ❌ **r1 wrong — corrected** | `ripple/v1/ripple.py:115,139` — `ripple_param_name : varchar(80)`. R1 used the plural `ripple_params_name` throughout eval 85's prompt, expected_output, required_substrings, and behavioral_checks; all fixed in the draft below. |
| `SpikeSortingV1` does NOT exist; v1 spike-sorting class is `SpikeSorting` | ✅ **verified** (new finding, triggers eval 89 + commit 7) | `grep -rn "SpikeSortingV1\b" $SPYGLASS_SRC/` returns no hits. v1 class at `spikesorting/v1/sorting.py:234` is `class SpikeSorting(SpyglassMixin, dj.Computed)`. `KNOWN_CLASSES` correctly registers `SpikeSorting`. But SKILL.md:11 and merge_methods.md:49 mention `SpikeSortingV1` — these are the seed mentions commit 7 removes. |
| `flatten_expectations.py` lives at `evals/scripts/`, not `scripts/` | ✅ **verified** (r1 draft had wrong path in validation commands) | `find skills/spyglass -name flatten_expectations.py` → `skills/spyglass/evals/scripts/flatten_expectations.py`. Per-commit validation block below uses the correct path. |

## Taxonomy additions

One new tier; no new stages.

### New tier: `workflow-recovery`

Fills a gap between `runtime-errors` (traceback in hand) and `common-mistakes` (pattern of misuse). Workflow-recovery evals start from **a populate that finished without raising, or a parameter change that committed without errors**, and ask what the safe next diagnostic is. The distinguishing trait: no error message, so the skill must resist the "rerun everything" reflex and recommend an inspect step first.

README entry to add (under **Tiers**):

> `workflow-recovery` | 2 | Recover from partial success — `populate()` completed but rows are missing, a parameter row was edited in place, an insertion was rolled back mid-chain. Tests whether the skill narrows the safe-next-diagnostic rather than defaulting to broad reruns or destructive cleanup.

### Tiers considered but not added

- **`ambiguity`** (proposed in r1 for eval 88). Dropped after review — a single-eval tier adds vocabulary surface area without payoff. Eval 88 uses the existing `disambiguation` tier; its expected_output names the under-specification explicitly so the intent isn't lost.
- **`workflow-recovery` stage** (proposed in r1 for eval 85). Dropped — eval 85 sits in `pipeline-usage` fine; the "state-change aftermath" framing is captured by the tier, not the stage.

### Count updates in README tables

After inserts, the tier row deltas are:

- `adversarial`: 7 → 11 (+4 from evals 79, 80, 81, 89 — all hallucination-resistance)
- `resource-selection`: 2 → 4 (+2 from 82, 83)
- `counterfactual`: 2 → 4 (+2 from 86, 87)
- `disambiguation`: 3 → 4 (+1 from 88)
- `workflow-recovery` (new row): 2 (evals 84, 85)

Stage row deltas:

- `hallucination-resistance`: 1 → 5 (+4 from 79, 80, 81, 89)
- `runtime-debugging`: 16 → 18 (+2 from 82, 86)
- `pipeline-authoring`: 1 → 2 (+1 from 83)
- `pipeline-usage`: 24 → 27 (+3 from 85, 87 — note: 85 stays in pipeline-usage after the r1→r2 collapse — plus 88 was originally slotted in destructive-operations; see eval 88 draft below for the final stage choice)
- `destructive-operations`: 4 → 5 (+1 from 88)

Recount the full distribution off `evals.json` at commit time rather than blindly applying deltas — earlier commits in the batch may shift intermediate totals.

## How to author each eval

Each per-eval subsection below gives:

1. Metadata (id, name, tier, stage, difficulty)
2. Authoring rubric — the one-line design goal and what failure mode this eval is pinning.
3. Full draft JSON object, in the field order [evals/README.md § Adding a new eval](../../skills/spyglass/evals/README.md#adding-a-new-eval) specifies.
4. Substring-hygiene sanity check — which required/forbidden substrings might trip the validator's bare-word / literal-format check, and the exempt-list justification if any.

All drafts below use `j1620210710_.nwb` as the canonical fixture session ID (same as existing evals). `files: []` and `expectations: []` on every entry — `expectations` is regenerated by the flatten script.

---

## Category 1 — Hallucination / abstention (evals 79, 80, 81, 89)

**Design goal.** Each eval sets up a specific hallucination shape — invented field (79), invented method (80), invented dependency (81), invented v1 class name extrapolated from v0 naming (89) — then requires the model to (a) state the thing doesn't exist, (b) name the introspection primitive it would use to verify (`heading`, `dir()`, `parents()`, import try, or source read), and (c) not invent a plausible signature / return shape. These map to SKILL.md's Core Directive #2: "Do not invent identifiers."

**Why four, not one.** The existing suite has exactly one hallucination-resistance eval (id 21, on `fetch_timeseries`). One eval can't detect the difference between "skill reliably abstains" and "skill reliably abstains on this specific prompt." Four covers four distinct surfaces (column / method / FK graph / class-name extrapolation), and the set lets the benchmark slice "where does abstention break down" rather than treating it as a binary.

### Eval 79 — abstain-session-samplingrate

- `tier`: `adversarial`
- `stage`: `hallucination-resistance`
- `difficulty`: `medium`
- **Failure mode pinned:** inventing a column on the `Session` table, then generating a plausible `fetch1('sampling_rate', ...)` call that would fail at runtime with `DataJointError: unknown attribute 'sampling_rate'`.

```json
{
  "id": 79,
  "eval_name": "abstain-session-samplingrate",
  "stage": "hallucination-resistance",
  "tier": "adversarial",
  "difficulty": "medium",
  "prompt": "Quick one — can I just pull the raw-ephys sampling rate straight off Session? I'm thinking something like `(Session & {'nwb_file_name': 'j1620210710_.nwb'}).fetch1('sampling_rate')`. Will that work?",
  "expected_output": "No — `Session` does not have a `sampling_rate` column, so that fetch1 call will raise `DataJointError: unknown attribute 'sampling_rate'`. The correct table is `Raw` (from `spyglass.common.common_ephys`), which has `sampling_rate: float` as a direct secondary column — so `(Raw & {'nwb_file_name': 'j1620210710_.nwb'}).fetch1('sampling_rate')` returns the value directly. Names `Session.heading` (or `.heading.names` / `.describe()`) as the verification primitive. Does not guess a numeric default or a made-up field shape on Session.",
  "assertions": {
    "required_substrings": ["Session", "heading", "Raw"],
    "forbidden_substrings": ["sampling_rate is stored on Session", "Session has a sampling_rate"],
    "behavioral_checks": [
      "States that `sampling_rate` does not exist as a column on Session",
      "Names `Session.heading` (or `.heading.names` / `.describe()`) as the verification primitive",
      "Redirects to `Raw` (direct column `sampling_rate`) as the correct source — accepts either `Raw.fetch1('sampling_rate')` or a fetch_nwb-based path",
      "Does not invent a numeric default sampling rate or a fake fetch1 return shape on Session"
    ]
  },
  "files": [],
  "expectations": []
}
```

**Substring hygiene.** `heading` is a Spyglass/DataJoint method name that appears in the class registry → auto-exempt. `Session` and `Raw` are both registered classes → discriminating.

### Eval 80 — abstain-spyglassmixin-get-pk

- `tier`: `adversarial`
- `stage`: `hallucination-resistance`
- `difficulty`: `easy`
- **Failure mode pinned:** inventing a method on `SpyglassMixin` because the name (`get_pk()`) sounds obvious for "get primary key." Plausibility is the trap; the real idioms are `.fetch('KEY')` and `.proj().fetch()`.

```json
{
  "id": 80,
  "eval_name": "abstain-spyglassmixin-get-pk",
  "stage": "hallucination-resistance",
  "tier": "adversarial",
  "difficulty": "easy",
  "prompt": "I need the primary-key dicts for every row in my current restriction. I vaguely remember there's a `.get_pk()` convenience on SpyglassMixin — can you show me the exact signature?",
  "expected_output": "`get_pk()` is not a method on `SpyglassMixin`. The skill should say so directly and not fabricate a signature. The real idioms are `(Table & restriction).fetch('KEY')` (returns a list of PK dicts) or `(Table & restriction).proj().fetch(as_dict=True)`. Names `dir(SpyglassMixin)` or a grep of `src/spyglass/utils/dj_mixin.py` as the verification path. Routes to spyglassmixin_methods.md for the supported helper surface. Does not invent a signature like `def get_pk(self, ...) -> list[dict]`.",
  "assertions": {
    "required_substrings": ["fetch('KEY')", "spyglassmixin_methods.md"],
    "forbidden_substrings": ["def get_pk", "get_pk returns", "SpyglassMixin.get_pk"],
    "behavioral_checks": [
      "States that `get_pk` does not exist on SpyglassMixin",
      "Recommends `.fetch('KEY')` (or `.proj().fetch()`) as the real way to get PK dicts",
      "Names `dir(SpyglassMixin)` or a source-grep as the verification primitive",
      "Does not fabricate a signature, docstring, or return-shape for `get_pk`"
    ]
  },
  "files": [],
  "expectations": []
}
```

**Substring hygiene.** `"fetch('KEY')"` ends with `)` and will trip the literal-format hygiene check. Add it to `required_substrings_exempt` with rationale: the argument is exactly what the eval is asking the model to recommend (not a bare method-call capture).

### Eval 81 — abstain-ripple-direct-dependency

- `tier`: `adversarial`
- `stage`: `hallucination-resistance`
- `difficulty`: `medium`
- **Failure mode pinned:** asserting a direct FK from `LFPV1 → RippleTimesV1` because "ripple times come from LFP data" sounds causally obvious. The reality: `RippleTimesV1` has **three** direct parents — `RippleLFPSelection`, `RippleParameters`, and `PositionOutput` — and `LFPV1` is reachable only indirectly through `RippleLFPSelection → LFPBandSelection.LFPBandElectrode` + `LFPBandV1`. Correct answer resists memory-based assertion and points at `.parents()` / `dj.Diagram`.

```json
{
  "id": 81,
  "eval_name": "abstain-ripple-direct-dependency",
  "stage": "hallucination-resistance",
  "tier": "adversarial",
  "difficulty": "medium",
  "prompt": "I'm about to cautious_delete a single `LFPV1` row. Before I do — does `RippleTimesV1` depend on `LFPV1` directly, so the delete will cascade into my ripple times?",
  "expected_output": "Not directly. `RippleTimesV1` has three direct parents: `RippleLFPSelection`, `RippleParameters`, and `PositionOutput` (via `PositionOutput.proj(pos_merge_id='merge_id')`). `LFPV1` is reachable only indirectly — `RippleLFPSelection` references `LFPBandSelection.LFPBandElectrode`, and the `LFPBandV1 → LFPV1` chain sits above that. The correct diagnostic before any delete is to inspect the actual cascade scope for *this specific row*: `RippleTimesV1.parents()` or `dj.Diagram(RippleTimesV1)` to see the full dependency graph, and `(LFPV1 & key).descendants()` to see what the delete would actually take out (cascades don't stop at intermediate tables — if LFPBandV1 is populated off this LFPV1 row, RippleTimesV1 rows downstream of that LFPBand entry will also cascade). Routes to destructive_operations.md (inspect-before-destroy). Does not commit to a yes/no on cascade scope from memory alone.",
  "assertions": {
    "required_substrings": ["parents()", "RippleLFPSelection", "destructive_operations.md"],
    "forbidden_substrings": ["RippleTimesV1 directly depends on LFPV1", "LFPV1 is the direct parent of RippleTimesV1"],
    "behavioral_checks": [
      "States that `LFPV1` is NOT a direct parent of `RippleTimesV1`",
      "Names at least two of the three actual direct parents: `RippleLFPSelection`, `RippleParameters`, `PositionOutput`",
      "Recommends `Table.parents()` / `.descendants()` (or `dj.Diagram`) as the verification primitive before committing to cascade scope",
      "Routes to destructive_operations.md before recommending any delete"
    ]
  },
  "files": [],
  "expectations": []
}
```

**Substring hygiene.** `parents()` ends with `(` — add to `required_substrings_exempt` with rationale: the method-call form is exactly what the eval wants the model to recommend (verifying, not just referencing). `RippleLFPSelection` is registered → auto-exempt. `destructive_operations.md` is a literal filename → discriminating. Forbidden strings are uniquely-wrong assertive claims (a correct answer never naturally says "`RippleTimesV1` directly depends on `LFPV1`," even in a denial — denials would be phrased differently).

### Eval 89 — abstain-v1-naming-extrapolation

- `tier`: `adversarial`
- `stage`: `hallucination-resistance`
- `difficulty`: `medium`
- **Failure mode pinned:** extrapolating a `V1` suffix from other v1 pipeline classes (`LFPV1`, `TrodesPosV1`, `RippleTimesV1`, `CurationV1`) to the v1 spike-sorting output class. The real v1 class is `SpikeSorting` (no suffix); `SpikeSortingV1` does not exist and never has. This is the category the user raised after the r1 review — LLMs trained on v0 → v1 migration patterns in other pipelines generalize the V1 suffix rule across all of Spyglass, and the skill's own docs currently *reinforce* the mistake (see commit 7). Grading eval 89 meaningfully requires those two seed mentions to be removed first.

```json
{
  "id": 89,
  "eval_name": "abstain-v1-naming-extrapolation",
  "stage": "hallucination-resistance",
  "tier": "adversarial",
  "difficulty": "medium",
  "prompt": "I just inserted a row in `SpikeSortingSelection`. To actually run the sort, do I call `SpikeSortingV1.populate(key)` or `SpikeSortingV1().populate(key)`? I've seen both forms and I'm not sure which the v1 pipeline wants.",
  "expected_output": "Neither — `SpikeSortingV1` does not exist. The v1 spike-sorting Computed class is `SpikeSorting` (from `spyglass.spikesorting.v1.sorting`). Correct call is `SpikeSorting.populate(key)` (or `SpikeSorting().populate(key)` — DataJoint accepts both class- and instance-form populate, so the user's real question about populate form is orthogonal). The skill should flag the v0→v1 naming asymmetry explicitly: v1 classes that keep the `V1` suffix are `LFPV1`, `TrodesPosV1`, `DLCPosV1`, `RippleTimesV1`, `CurationV1`, `ClusterlessDecodingV1`, `SortedSpikesDecodingV1`; v1 classes that drop the suffix include `SpikeSorting`, `SpikeSortingRecording`, `SpikeSortingSelection`, `MetricCuration`, `FigURLCuration`. There is no consistent rule — verify by import (`from spyglass.spikesorting.v1 import SpikeSorting`) or `python -c 'import spyglass.spikesorting.v1 as m; print([n for n in dir(m) if \"Sort\" in n])'` rather than extrapolating from the naming of adjacent v1 tables. Routes to spikesorting_pipeline.md.",
  "assertions": {
    "required_substrings": ["SpikeSorting", "spikesorting_pipeline.md"],
    "forbidden_substrings": ["SpikeSortingV1.populate", "class SpikeSortingV1", "SpikeSortingV1 is the v1 class"],
    "behavioral_checks": [
      "States that `SpikeSortingV1` does not exist",
      "Identifies `SpikeSorting` (no V1 suffix) as the correct v1 spike-sorting Computed class and names its module (`spyglass.spikesorting.v1`)",
      "Explicitly flags the v0→v1 naming asymmetry (some v1 classes keep the `V1` suffix, some drop it) — recommends verifying by import rather than extrapolating",
      "Does not fabricate a signature for `SpikeSortingV1.populate` or claim it is an alias / deprecated name for `SpikeSorting`"
    ]
  },
  "files": [],
  "expectations": []
}
```

**Substring hygiene.** `SpikeSorting` is in `KNOWN_CLASSES` → auto-exempt (even though it looks like a bare compound word). The completeness check may flag that `SpikeSortingSelection` appears in the prompt but isn't in `required_substrings` — accept the warning or add to `required_substrings_exempt` with rationale: `SpikeSortingSelection` is the prompt's premise, not the diagnosis. Forbidden strings are uniquely-wrong (`SpikeSortingV1.populate` is precisely the hallucinated form the eval pins).

---

## Category 2 — Resource-selection (evals 82–83)

**Design goal.** Meta-test: given a situation, which **reference file or bundled script** should be opened *first*? Correct behavior names a specific file by name, explains the one-line rationale, and resists the temptation to enumerate three files "to be safe." Matches SKILL.md's routing directive: "Load one reference at a time. Pick the single most relevant row."

**Why two.** The existing `resource-selection` tier has exactly two evals (66 and 67), both scoped to runtime-debugging and destructive-operations. The new pair extends coverage into (a) the `populate_all_common_debugging.md` ↔ `runtime_debugging.md` boundary — the most common routing-confusion in the skill — and (b) the authoring vs. consumption reference boundary.

### Eval 82 — resource-first-ref-populate-all-common

- `tier`: `resource-selection`
- `stage`: `runtime-debugging`
- `difficulty`: `easy`
- **Failure mode pinned:** defaulting to `runtime_debugging.md` for any populate-related issue. `populate_all_common` silent skips have their own reference; conflating the two leads the skill to miss the `InsertError`-table diagnostic.

```json
{
  "id": 82,
  "eval_name": "resource-first-ref-populate-all-common",
  "stage": "runtime-debugging",
  "tier": "resource-selection",
  "difficulty": "easy",
  "prompt": "I ran `populate_all_common('j1620210710_.nwb')` and it completed without raising, but Electrode has no rows for this file. Before I touch any code — which file inside the skill should I open first, and is there a bundled script that helps here?",
  "expected_output": "Open `populate_all_common_debugging.md` first — it's scoped specifically to silent skips from the `populate_all_common` driver, which catches per-table errors by default (`raise_err=False`) and writes only a short message to `common_usage.InsertError`. `runtime_debugging.md` is the wrong first stop because it covers in-the-traceback errors, not silent-completion symptoms. There is no bundled script that diagnoses populate silent skips — the two user-facing bundled scripts are `scrub_dj_config.py` (config redaction) and `verify_spyglass_env.py` (env/install check), neither of which is relevant here. The answer should name the file, explain the one-line reason (silent-skip has its own reference), and not invent a third-party diagnostic script.",
  "assertions": {
    "required_substrings": ["populate_all_common_debugging.md", "InsertError"],
    "forbidden_substrings": ["runtime_debugging.md is the first", "check_populate_status.py", "diagnose_populate.py"],
    "behavioral_checks": [
      "Names `populate_all_common_debugging.md` as the first reference to open",
      "Explains in one line that silent completion (not an in-hand traceback) is what makes this reference correct over `runtime_debugging.md`",
      "Identifies `common_usage.InsertError` as the table where the swallowed error message lives",
      "Does not invent a bundled script for populate diagnostics; correctly notes only scrub_dj_config.py and verify_spyglass_env.py ship today (or that no populate-diagnostic script is bundled)"
    ]
  },
  "files": [],
  "expectations": []
}
```

**Substring hygiene.** `.md` filenames are discriminating. `InsertError` is in `KNOWN_CLASSES` after commit 0 → auto-exempt. Fabricated script names in `forbidden_substrings` are uniquely-wrong.

### Eval 83 — resource-first-ref-custom-pipeline-author

- `tier`: `resource-selection`
- `stage`: `pipeline-authoring`
- `difficulty`: `easy`
- **Failure mode pinned:** routing authoring questions to `spyglassmixin_methods.md` (which is for *consumers* of existing mixin behavior) instead of `custom_pipeline_authoring.md`. Both files mention `SpyglassMixin`, making keyword routing insufficient.

```json
{
  "id": 83,
  "eval_name": "resource-first-ref-custom-pipeline-author",
  "stage": "pipeline-authoring",
  "tier": "resource-selection",
  "difficulty": "easy",
  "prompt": "I'm writing a new Computed table in my own schema that produces a waveform-feature array, writes it into an AnalysisNwbfile, and registers the artifact with an `_object_id`. Which single reference in the skill is the right starting point, and which similar-sounding one is a distractor?",
  "expected_output": "Start with `custom_pipeline_authoring.md` — it's the authoring-side reference and covers the `SpyglassMixin` subclass requirement, `AnalysisNwbfile` FK, `_object_id` convention, and the `make()` pattern for writing feature arrays. The distractor is `spyglassmixin_methods.md`, which documents methods users *call on* existing mixin tables (`fetch_nwb`, `cautious_delete`, `<<`, `>>`) — useful once the table is authored but wrong for the write-the-schema step. The answer should name both files, commit to `custom_pipeline_authoring.md` as the first stop, and explain the author-vs-consumer split in one sentence.",
  "assertions": {
    "required_substrings": ["custom_pipeline_authoring.md", "spyglassmixin_methods.md", "AnalysisNwbfile"],
    "forbidden_substrings": ["spyglassmixin_methods.md is the first", "merge_methods.md is where you start"],
    "behavioral_checks": [
      "Names `custom_pipeline_authoring.md` as the first reference",
      "Explicitly identifies `spyglassmixin_methods.md` as a distractor and explains the author-vs-consumer split",
      "Mentions the `_object_id` + AnalysisNwbfile FK convention as a signal that this is an authoring task",
      "Does not recommend merge_methods.md or ingestion.md as the first stop"
    ]
  },
  "files": [],
  "expectations": []
}
```

**Substring hygiene.** All three required substrings are literal filenames or specific class names → discriminating. Forbidden substrings are uniquely-wrong affirmative routings.

---

## Category 3 — Workflow-recovery (evals 84–85)

**Design goal.** After a populate completes with partial results (84) or a parameter row is edited in place (85), the safest next step is *inspect before recompute*. Evals pin whether the skill narrows the scope (which rows to recheck, which params are affected) instead of defaulting to "rerun everything" or "cautious_delete and re-populate from scratch."

### Eval 84 — recover-partial-populate-common

- `tier`: `workflow-recovery` (new)
- `stage`: `runtime-debugging`
- `difficulty`: `hard`
- **Failure mode pinned:** reflexively recommending re-running `populate_all_common` after a silent skip (which will silently skip again for the same reason) or recommending a blanket delete-and-reingest.

```json
{
  "id": 84,
  "eval_name": "recover-partial-populate-common",
  "stage": "runtime-debugging",
  "tier": "workflow-recovery",
  "difficulty": "hard",
  "prompt": "`populate_all_common('j1620210710_.nwb')` finished 20 minutes ago with no exception. `Session`, `IntervalList`, and `Raw` have entries, but `Electrode` and `ElectrodeGroup` are empty for this file. What's the safest next diagnostic — before I delete anything or re-run the whole populate?",
  "expected_output": "Inspect `common_usage.InsertError & {'nwb_file_name': 'j1620210710_.nwb'}` first — that's where `populate_all_common` writes the short error message per silently-skipped table when `raise_err=False` (its default). Once the failed table and message are identified, re-run only the affected table(s) with `raise_err=True` to surface the full traceback — e.g., `populate_all_common(nwb_file_name, raise_err=True)` on a fresh kernel, or directly call the affected table's `populate()` with the restriction. Do NOT delete Session/IntervalList/Raw rows — they ingested correctly, and deleting them would cascade across the whole schema. Do NOT blindly re-run the full `populate_all_common` without first reading InsertError, since the same per-table failure will silently happen again. Routes to populate_all_common_debugging.md.",
  "assertions": {
    "required_substrings": ["InsertError", "raise_err=True", "populate_all_common_debugging.md"],
    "forbidden_substrings": ["delete the Session row and re-ingest", "super_delete", "just re-run populate_all_common"],
    "behavioral_checks": [
      "Recommends inspecting `common_usage.InsertError` as the first diagnostic",
      "Recommends re-running with `raise_err=True` to surface the swallowed traceback, scoped narrowly (not a blanket rerun)",
      "Explicitly warns against deleting the already-ingested rows (Session/IntervalList/Raw) as a recovery step",
      "Explicitly warns against naively re-running the full `populate_all_common` without inspecting InsertError first"
    ]
  },
  "files": [],
  "expectations": []
}
```

**Substring hygiene.** `raise_err=True` contains `=` and may trip literal-format hygiene — add to `required_substrings_exempt` with rationale: it's a specific kwarg literal the eval wants the model to name (not a bare function-call capture). `InsertError` is in `KNOWN_CLASSES` after commit 0 → auto-exempt. Filename is literal.

### Eval 85 — recover-parameter-edit-in-place

- `tier`: `workflow-recovery` (new)
- `stage`: `pipeline-usage`
- `difficulty`: `hard`
- **Failure mode pinned:** treating a parameter-row edit as automatically invalidating all downstream entries that referenced it, or (the opposite failure) treating downstream as auto-updated. Reality: downstream rows are *stale but not flagged* — the skill has to recommend a scoped `cautious_delete` + repopulate keyed on the affected `ripple_param_name`, leave everything else alone, and flag that editing a params row in place is itself an anti-pattern.

```json
{
  "id": 85,
  "eval_name": "recover-parameter-edit-in-place",
  "stage": "pipeline-usage",
  "tier": "workflow-recovery",
  "difficulty": "hard",
  "prompt": "I edited my `RippleParameters` row named `Kay_ripple_detection_v2` in place — bumped the speed threshold inside `ripple_param_dict` from 4 cm/s to 5 cm/s. I already have RippleTimesV1 entries that were populated with the old threshold. What should I recompute, what should I leave alone, and what's the safe order?",
  "expected_output": "The old RippleTimesV1 rows are stale (they were computed against the pre-edit parameters) but are not flagged stale by the database — editing a params row in place does not invalidate downstream. Safe order: (1) Inspect `RippleTimesV1 & {'ripple_param_name': 'Kay_ripple_detection_v2'}` to see which rows need recomputation — scope is gated by that `ripple_param_name`, not all of RippleTimesV1. (2) `cautious_delete` only those rows (not LFP, not LFPBand, not position, not ripple rows that used a different `ripple_param_name`). (3) Re-populate with the same selection keys. Everything else is unaffected: LFPV1, LFPBandV1, RippleLFPSelection (its own row doesn't change), position pipelines, decoding pipelines not downstream of these ripple times. Flag the anti-pattern: editing a params row in place breaks reproducibility — better practice is to insert a new `ripple_param_name` entry (e.g., `Kay_ripple_detection_v3`) and leave the old one so previously-computed rows stay interpretable. Routes to destructive_operations.md (inspect-before-destroy), ripple_pipeline.md, and common_mistakes.md. Does not recommend deleting all RippleTimesV1 rows or re-running LFP.",
  "assertions": {
    "required_substrings": ["ripple_param_name", "cautious_delete", "destructive_operations.md"],
    "forbidden_substrings": ["delete all RippleTimesV1 rows", "re-populate LFPV1", "super_delete", "ripple_params_name"],
    "behavioral_checks": [
      "Uses the correct field name `ripple_param_name` (singular), not `ripple_params_name`",
      "Scopes the cleanup to RippleTimesV1 rows with the affected `ripple_param_name`, not all RippleTimesV1 rows",
      "Explicitly lists what is unaffected — LFP, LFPBand, RippleLFPSelection, position, decoding branches not downstream of the affected ripple times",
      "Recommends cautious_delete (not super_delete or a manual drop) and routes to destructive_operations.md",
      "Flags editing a params row in place as an anti-pattern and recommends inserting a new `ripple_param_name` entry for future runs"
    ]
  },
  "files": [],
  "expectations": []
}
```

**Substring hygiene.** `ripple_param_name` is a column name → discriminating. `cautious_delete` is in `KNOWN_METHODS` in the validator → auto-exempt. Adding the incorrect `ripple_params_name` (plural) to `forbidden_substrings` catches any answer that repeats the r1-draft hallucination — a correct answer won't naturally contain the plural form.

---

## Category 4 — Counterfactual / comparison (evals 86–87)

**Design goal.** Explain divergence between two pipeline states without committing prematurely to one cause (eval 86) or enumerate the downstream effect of a single upstream change (eval 87). Complements existing evals 68 and 69 on different surfaces.

### Eval 86 — counterfactual-decoding-noise-divergence

- `tier`: `counterfactual`
- `stage`: `runtime-debugging`
- `difficulty`: `hard`
- **Failure mode pinned:** picking one cause out of the plausible divergence surfaces without enumerating the space, OR over-extending into upstream chain elements that aren't direct FKs of the selection. `ClusterlessDecodingSelection` has exactly four FK targets + one secondary bool.

```json
{
  "id": 86,
  "eval_name": "counterfactual-decoding-noise-divergence",
  "stage": "runtime-debugging",
  "tier": "counterfactual",
  "difficulty": "hard",
  "prompt": "A collaborator and I both ran clusterless decoding on `j1620210710_.nwb` with what we think are the same parameters. Both populates finished without errors. My posterior is visibly noisier than theirs. Which upstream selection differences could explain the divergence, and what's the minimal diagnostic to isolate which one it is?",
  "expected_output": "Enumerate the direct-FK divergence surfaces on `ClusterlessDecodingSelection` — there are four plus one secondary bool (per `decoding/v1/clusterless.py:83–91`): (1) different `waveform_features_group_name` (FK to `UnitWaveformFeaturesGroup`) — different units / waveform features feeding the decoder; (2) different `position_group_name` (FK to `PositionGroup`) — different PositionOutput merge_ids threaded in, hence different behavioral alignment and speed; (3) different `decoding_param_name` (FK to `DecodingParameters`) — different state transition prior, smoothing, or emission model; (4) different `encoding_interval` (FK to `IntervalList.proj(encoding_interval=...)`) — different training epoch; (5) different `decoding_interval` (FK to `IntervalList.proj(decoding_interval=...)`) — different test epoch; (6) different `estimate_decoding_params` bool — whether the decoder re-estimates params at inference. Minimal diagnostic: fetch `ClusterlessDecodingSelection & key` row-by-row for both users and diff the PK fields. Upstream-chain differences (e.g., different sorter params feeding `UnitWaveformFeaturesGroup`, different position params feeding `PositionGroup`) are also possible but are a *second-order* check — they matter only if the direct selection keys match. Routes to decoding_pipeline.md. Does not commit to one cause before the diff is run. Does not attribute divergence purely to environment drift (the selection keys gate determinism).",
  "assertions": {
    "required_substrings": ["ClusterlessDecodingSelection", "decoding_param_name", "decoding_pipeline.md"],
    "forbidden_substrings": [],
    "behavioral_checks": [
      "Enumerates at least four distinct direct-FK divergence surfaces on `ClusterlessDecodingSelection` (waveform features group, position group, decoding params, encoding interval, decoding interval — any four of these five)",
      "Recommends fetching and diffing `ClusterlessDecodingSelection & key` between the two users as the minimal isolating diagnostic",
      "Does not commit to one cause before the diagnostic is run",
      "Distinguishes direct-FK surfaces from upstream-chain differences (sorter params, position params) — latter is a second-order check",
      "Does not misattribute divergence purely to environment / package drift"
    ]
  },
  "files": [],
  "expectations": []
}
```

**Substring hygiene.** `ClusterlessDecodingSelection` is in `KNOWN_CLASSES`. `decoding_param_name` is a specific PK field → discriminating. Filename is literal. Empty `forbidden_substrings` is fine for counterfactual evals where the failure mode is enumeration, not a specific wrong string.

### Eval 87 — counterfactual-trodes-pos-params-swap

- `tier`: `counterfactual`
- `stage`: `pipeline-usage`
- `difficulty`: `hard`
- **Failure mode pinned:** either under-enumerating downstream effects (missing decoding or linearization branches) or over-enumerating (claiming LFP / spike-sorting are affected, which they aren't — they don't consume position).

Design note on the field name: r1 drafted this eval around `position_info_param_name`, which is a **v0** field on `common.PositionInfoParameters`. In v1, the parameter PK the user would actually change on a position selection is `trodes_pos_params_name` (on `TrodesPosSelection`) — verified at `position/v1/position_trodes_position.py:30,55`. Re-scoped to v1 here.

```json
{
  "id": 87,
  "eval_name": "counterfactual-trodes-pos-params-swap",
  "stage": "pipeline-usage",
  "tier": "counterfactual",
  "difficulty": "hard",
  "prompt": "If I change `trodes_pos_params_name` on my `TrodesPosSelection` from `default` to `default_decoding` and re-populate `TrodesPosV1`, which downstream tables would produce different entries, and which would be completely unaffected if every other selection is the same?",
  "expected_output": "A change to `trodes_pos_params_name` on `TrodesPosSelection` produces a new row in `TrodesPosV1` keyed by the new params name — the old row is still there (same `nwb_file_name`, `interval_list_name`, different `trodes_pos_params_name`). Inserting that new `TrodesPosV1` row into `PositionOutput.TrodesPosV1` issues a new `merge_id` on `PositionOutput`. Downstream that diverges — anything consuming the new PositionOutput merge_id: `LinearizedPositionV1` (if re-inserted keyed on the new merge_id), clusterless/sorted decoding selections that reference the new `PositionGroup` (if the group is updated to include the new merge_id), ripple detection if `RippleLFPSelection` is paired with the new PositionOutput merge via `RippleTimesV1`'s `pos_merge_id` FK. Unchanged: everything not downstream of `PositionOutput` — `LFPV1`, `LFPBandV1`, `SpikeSorting`, `SpikeSortingRecording`, `CurationV1`, the Session/Electrode/IntervalList common tables, raw ephys. The old position entry and its downstream consumers stay valid; divergence threads through the new merge_id. Routes to position_pipeline.md and decoding_pipeline.md. Does not claim spike sorting or LFP are affected (they don't consume position).",
  "assertions": {
    "required_substrings": ["PositionOutput", "TrodesPosV1", "position_pipeline.md"],
    "forbidden_substrings": ["LFPV1 would need to be re-populated", "SpikeSorting depends on position", "CurationV1 would change", "SpikeSortingV1"],
    "behavioral_checks": [
      "Identifies that a new `TrodesPosV1` row (new params_name) is produced, not an in-place update",
      "Identifies that inserting into `PositionOutput.TrodesPosV1` issues a new merge_id on `PositionOutput`",
      "Lists at least two downstream tables that would diverge (linearization, decoding via PositionGroup, ripple via pos_merge_id)",
      "Explicitly names LFP, spike-sorting, and curation as unaffected — they do not consume position",
      "Does not use the v0 field name `position_info_param_name` or the nonexistent class `SpikeSortingV1`"
    ]
  },
  "files": [],
  "expectations": []
}
```

**Substring hygiene.** `PositionOutput`, `TrodesPosV1` are in `KNOWN_CLASSES`. Filename is literal. `SpikeSortingV1` in `forbidden_substrings` double-guards against the v0→v1 extrapolation covered in eval 89 — belts and suspenders on the hallucination this plan is specifically trying to close.

---

## Category 5 — Ambiguity (eval 88, uses existing `disambiguation` tier)

**Design goal.** Distinct from the typical `disambiguation` shape (pick A or B between two known options) — here the prompt is *under-specified* and correct behavior is either (a) ask for the missing input or (b) narrow the scope explicitly and state what was assumed. Using `disambiguation` tier rather than inventing an `ambiguity` tier for N=1.

### Eval 88 — ambiguity-delete-decoding-results

- `tier`: `disambiguation`
- `stage`: `destructive-operations`
- `difficulty`: `medium`
- **Failure mode pinned:** answering with a single delete command (`DecodingOutput.delete()` or similar) without clarifying which layer the user means. Decoding has at least three plausible delete targets: the merge entry, the V1 computed row, and the underlying AnalysisNwbfile artifact — and the right command differs for each.

```json
{
  "id": 88,
  "eval_name": "ambiguity-delete-decoding-results",
  "stage": "destructive-operations",
  "tier": "disambiguation",
  "difficulty": "medium",
  "prompt": "I need to delete my decoding results for `j1620210710_.nwb`. What's the right command?",
  "expected_output": "This prompt is under-specified — the correct command depends on which layer the user means, and the skill should either ask or narrow explicitly. The three plausible layers: (1) a `DecodingOutput` merge entry (handled via `DecodingOutput.merge_delete(merge_key)` — classmethod form, per Common Mistake #1's classmethod-restriction-discard rule); (2) the underlying Computed row (`ClusterlessDecodingV1` or `SortedSpikesDecodingV1`) which cascades through the merge; (3) just the AnalysisNwbfile artifact on disk (rarely the right move — the DB row is the source of truth). Also missing: which params / interval / selection does 'my decoding results' scope to — there may be multiple decoding rows per session. Correct response either asks (a) which layer, and (b) which selection — or states the assumption explicitly ('I'll assume you mean the DecodingOutput merge entry for your most recent ClusterlessDecodingV1 populate; here's the inspect-before-destroy pattern…'). Routes to destructive_operations.md and merge_methods.md. Does not hand back a bare delete command without scoping.",
  "assertions": {
    "required_substrings": ["DecodingOutput", "merge_delete", "destructive_operations.md"],
    "forbidden_substrings": ["DecodingOutput.delete()", "ClusterlessDecodingV1.delete() without restriction", "super_delete"],
    "behavioral_checks": [
      "Identifies that the prompt is under-specified and either asks a clarifying question or narrows scope explicitly",
      "Enumerates at least two plausible delete layers (merge entry vs. V1 computed row vs. on-disk artifact)",
      "Names the selection-scope ambiguity (which decoding_param_name / interval / session)",
      "Recommends merge_delete with an explicit key (classmethod form) if the merge layer is chosen, and routes to destructive_operations.md for the inspect-before-destroy pattern",
      "Does not produce an unscoped `.delete()` command without asking or narrowing"
    ]
  },
  "files": [],
  "expectations": []
}
```

**Substring hygiene.** `DecodingOutput` and `merge_delete` are in the class/method registries. Filename is literal. Forbidden strings are uniquely-wrong bare-delete commands.

---

## Commit 7 — fix two skill-side mentions that seed the `SpikeSortingV1` hallucination

Eval 89 is ungradable if the skill's own router tells the LLM to reach for `SpikeSortingV1`. Two mentions in the skill currently do that:

### Fix 1 — [SKILL.md:11](../../skills/spyglass/SKILL.md)

Current frontmatter keyword list (abbreviated):

```yaml
...V1 pipeline classes (`LFPV1`, `TrodesPosV1`, `DLCPosV1`, `RippleTimesV1`,
  `SpikeSortingV1`, `CurationV1`, `ClusterlessDecodingV1`,
  `SortedSpikesDecodingV1`)...
```

Replace `SpikeSortingV1` with `SpikeSorting` (no V1 suffix). That matches the v1 source class name at `spyglass/spikesorting/v1/sorting.py:234`. Triggering accuracy impact: none — users searching "SpikeSortingV1" would have been mis-cued into the skill anyway; users searching the correct `SpikeSorting` get the right match now.

### Fix 2 — [merge_methods.md:49](../../skills/spyglass/references/merge_methods.md)

Current:

```markdown
- `SpikeSortingV1`, `LFPV1`, `TrodesPosV1`, `DLCPosV1`, `RippleTimesV1`, `ClusterlessDecodingV1`, `SortedSpikesDecodingV1` — all `dj.Computed`
```

Replace `SpikeSortingV1` with `SpikeSorting`. The surrounding sentence identifies these as `dj.Computed` tables — `SpikeSorting` is `dj.Computed` per `spikesorting/v1/sorting.py:234` — so the claim survives the substitution.

### Validation after commit 7

Additionally grep the whole repo to confirm no other `SpikeSortingV1` mentions remain outside of `evals.json` (where the three existing mentions in evals 52, 70, and the r2-new 89 explicitly flag the asymmetry, so those stay):

```bash
grep -rn "SpikeSortingV1\b" skills/ docs/ README.md 2>/dev/null | grep -v evals.json | grep -v eval-failure-mode-coverage-impl-plan.md
```

Expected output: empty. If anything else turns up, add it to commit 7.

### Why this lands in commit 7 (last), not before eval 89

Order matters. If commit 7 lands before eval 89, a skill-equipped model has never seen the seed mention in the first place, so eval 89 can't distinguish "abstained on its own" from "abstained because the skill was clean." Landing eval 89 first (commit 2) exercises the hallucination under the current seed conditions; commit 7 then closes the seed, so a *next-iteration* benchmark run confirms the fix raised the pass rate. This is the before/after signal the plan's [Post-batch smoke run](#post-batch-smoke-run-optional-but-recommended) is set up to capture.

---

## Per-commit validation

### Before each commit (drift spot-check)

Even after Step -1 passes, re-check the *specific* evidence each commit depends on before making the change. Cheap insurance against a drift that slipped through the bulk check:

| Commit | Spot-check before editing |
| --- | --- |
| 0 | `grep -n "InsertError" skills/spyglass/scripts/validate_skill.py` — confirm NOT already registered. If it is, skip commit 0. |
| 1 | `grep -n "workflow-recovery" skills/spyglass/evals/README.md` — confirm the new tier isn't already there. |
| 2–6 | `python3 -c "import json; ids=[e['id'] for e in json.load(open('skills/spyglass/evals/evals.json'))['evals']]; print('next free id:', max(ids)+1)"` — confirm the next free ID is what the plan expects for the commit you're about to write. |
| 7 (fix 1) | `sed -n '10,14p' skills/spyglass/SKILL.md` — confirm the line containing `SpikeSortingV1` is still at or near line 11 and still says what the plan claims it says. If the surrounding context has changed, update the edit accordingly (keep the *intent*: drop one keyword). |
| 7 (fix 2) | `grep -n "SpikeSortingV1" skills/spyglass/references/merge_methods.md` — confirm the mention is still present at the expected location; the line number may have shifted from 49. |

If any spot-check shows the evidence the commit depends on has already moved, *do not blindly apply the plan's diff* — re-read the surrounding context and write a replacement edit that preserves intent.

### After each commit (standard validation)

```bash
# 1. Regenerate the flat expectations list (skill validator expects it in sync)
python3 skills/spyglass/evals/scripts/flatten_expectations.py

# 2. Validate JSON parses
python3 -c "import json; json.load(open('skills/spyglass/evals/evals.json'))"

# 3. Run the full validator + regression suite
./skills/spyglass/scripts/validate_all.sh --baseline-warnings 180

# 4. Confirm the new eval count
python3 -c "import json; print(len(json.load(open('skills/spyglass/evals/evals.json'))['evals']))"
```

Expected counts after each commit: **0** = 78, **1** = 78 (README-only), **2** = 82, **3** = 84, **4** = 86, **5** = 88, **6** = 89, **7** = 89.

If `validate_all.sh` emits a warning count above the baseline (180), inspect which new warning fires. Likely sources:

- **Required-vs-expected completeness** — the `expected_output` names a class that no `required_substring` contains (e.g., `RippleLFPSelection` or `RippleParameters` in eval 81). Fix by adding to `required_substrings` (preferred) or to `expected_output_tables_exempt` with an audit-worthy justification.
- **Bare-word / literal-format hygiene** — triggered by `parents()`, `fetch('KEY')`, or `raise_err=True`. Fix by adding to `required_substrings_exempt` with a one-line comment.
- **Unknown-class warning on `InsertError`** — commit 0 fixes this. If it still fires after commit 0 runs, verify the entry landed with the correct source path `spyglass/common/common_usage.py` (file must exist).

Don't raise `--baseline-warnings` to silence a legitimate warning.

## Authoring guardrails

Carry these through every commit:

- **Fixture consistency.** All session IDs use `j1620210710_.nwb`. Lab-identifying host/user/lab names use anonymized placeholders per [evals/README.md § Adding a new eval](../../skills/spyglass/evals/README.md).
- **Realistic voice.** Include specific error strings, session names, and `param_name` values a real user would paste.
- **Behavioral-check specificity.** Single declarative sentences only. No conjunctions ("and also"); split into two checks.
- **Forbidden substrings as uniquely-wrong strings.** Per [evals/README.md § Forbidden-substring rule](../../skills/spyglass/evals/README.md#substring-hygiene), every forbidden substring must be something a correct answer would never naturally contain — even inside a denial. Quoted fake commands and fabricated method signatures are the safe shape.
- **Verify v0 vs v1 field names against source before authoring.** The r1 draft tripped on this in evals 85 (`ripple_params_name` plural — wrong) and 87 (`position_info_param_name` — v0 field). The source verification table above is the audit trail; new evals added in follow-up passes must pass the same check.
- **No cross-eval coupling.** Each eval stands alone.

## Post-batch smoke run (optional but recommended)

After all eight commits land, spot-run the eleven new evals through the skill-creator benchmark loop:

```bash
python -m scripts.aggregate_benchmark \
  <workspace>/iteration-post-79-89 \
  --skill-name spyglass
```

Four slices specifically:

1. **Hallucination abstention pass rate** (evals 79, 80, 81, 89 + existing eval 21) — below 75% suggests SKILL.md Core Directive #2 needs a worked example. The v1-naming asymmetry is the most recent add; watch 89's solo pass rate separately.
2. **Resource-selection pass rate** (66, 67, 82, 83) — below 75% suggests the "Load one reference at a time" directive is under-weighted.
3. **Counterfactual pass rate** (68, 69, 86, 87) — all hard; <40% floor suggests adding a "how to diagnose divergence" pattern to `runtime_debugging.md` or `workflows.md`.
4. **Before/after on eval 89 specifically.** Ideally, run the with_skill subagent against the pre-commit-7 skill state *and* the post-commit-7 state. Any lift attributable to removing the `SpikeSortingV1` seed mentions quantifies the harm those mentions were doing.

Follow-up signals; not blocking for this plan.

## Rollout summary

| Commit | Message (topic prefix per [CLAUDE.md](../../CLAUDE.md) style) | Files changed |
| --- | --- | --- |
| 0 | `validator: register InsertError in KNOWN_CLASSES` | `scripts/validate_skill.py` |
| 1 | `evals: README — register workflow-recovery tier` | `evals/README.md` |
| 2 | `evals: add hallucination/abstention evals 79, 80, 81, 89 (session field, mixin method, ripple dependency, v1 naming extrapolation)` | `evals/evals.json` |
| 3 | `evals: add resource-selection evals 82–83 (populate_all_common debugging, custom-pipeline authoring)` | `evals/evals.json` |
| 4 | `evals: add workflow-recovery evals 84–85 (partial populate, in-place params edit)` | `evals/evals.json` |
| 5 | `evals: add counterfactual evals 86–87 (decoding noise divergence, trodes-pos params swap)` | `evals/evals.json` |
| 6 | `evals: add ambiguity eval 88 (under-specified decoding delete request)` | `evals/evals.json` |
| 7 | `skill: drop SpikeSortingV1 seed mentions from SKILL.md frontmatter and merge_methods.md` | `SKILL.md`, `references/merge_methods.md` |

No Anthropic trailers, no ticket numbers, lowercase after the prefix.
