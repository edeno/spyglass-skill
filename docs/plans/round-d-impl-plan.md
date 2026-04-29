# Round-D implementation plan

Round of skill edits and verification driven by the round-C 130-eval sweep
analysis ([summary](../../skills/spyglass-workspace/runs/round-c-2026-04-28/summary/SUMMARY.md)).
This plan is granular: per-edit insertion anchors, validator gates between
commits, and explicit success/regression criteria for the narrow rerun.

The starting state is post-commit `d1a7dc1` (round-C bundle landed). Each
phase below is a separate commit unless noted; each commit must leave the
validator green before the next begins.

## Phase 2 — SKILL.md and reference edits (8 commits)

Edits are inserted **thematically into existing bullet sections**, not
appended. Core Directives in `SKILL.md` are bullets, not numbered, so
insertion order is determined by topical proximity to existing bullets.

### Phase 2.1 — Verify-before-claim Core Directive clarification

**File**: `skills/spyglass/SKILL.md`

**Anchor**: existing `Do not invent identifiers` bullet at SKILL.md:27,
which already references the Evidence Expectations section that follows
at SKILL.md:36. The verify-before-claim clarification belongs adjacent
to that bullet because they share the same "evidence-gating" concern.

**Edit**: Add a sibling bullet immediately after the
`Do not invent identifiers` bullet:

> - **State the most-likely answer first; then verify high-stakes claims.**
>   The verify-before-claim discipline gates *confident assertions* on
>   evidence; it does NOT gate *answering at all*. Lead with the most
>   likely answer (named directly, not buried under caveats), and use the
>   Evidence Expectations to verify the high-stakes parts. Anti-pattern:
>   opening with "let me verify whether X is even a real field" and
>   spending the response on source-skepticism without ever naming the
>   substantive answer; the user is left with a caveat list instead of
>   an answer.

**Why this anchor**: keeps verify-before-claim semantically next to the
existing identifier-invention guard, where readers already expect
evidence-related rules.

**Validator**: must pass after edit. Validator runs static checks on
class names (we're adding none), line-number citations (none), and link
targets (none). Should be green on first try.

**Success check**: SKILL.md word count rises by ~80 words; `validate_all.sh
--baseline-warnings 3` exits 0; the existing test suite still passes.

**Estimated effort**: 10 min.

### Phase 2.2 — Tool-routing Core Directive (the 4-mode routing matrix)

**File**: `skills/spyglass/SKILL.md`

**Anchor**: existing `## Evidence Expectations` section at SKILL.md:36.
Tool routing is a property of *how* to gather evidence, so it belongs
inside or immediately adjacent to Evidence Expectations rather than as
a top-level Core Directive. Two options:

- (a) New subsection inside Evidence Expectations (`### Tool routing for relationship and lookup questions`)
- (b) Top-level Core Directive bullet pointing at the new subsection

Recommendation: do both. (a) is the substantive content, (b) is a
single-line cross-link from Core Directives so agents reading the
directives find the routing matrix without having to discover it.

**Edit**: Add a Core Directive bullet adjacent to the existing
`Verify cardinality before fetch1()` bullet (line 30), since both are
"how to verify" rules:

> - **Tool routing for relationship and lookup questions.** See the
>   subsection in Evidence Expectations below for the routing matrix.
>   Briefly: `code_graph.py path --to A B` for table-to-table
>   relationships, `code_graph.py describe X` for one table's surface,
>   source-read for runtime `make()` behavior, `db_graph.py` for live row
>   values. Field-level provenance is *not* what `path --to` answers —
>   see the field-ownership rule.

Then add the substantive subsection inside Evidence Expectations
(content already drafted in
[runs/round-c-2026-04-28/summary/SUMMARY.md](../../skills/spyglass-workspace/runs/round-c-2026-04-28/summary/SUMMARY.md)
recommendation #6, the four-bullet routing matrix).

**Validator**: same as 2.1.

**Success check**: SKILL.md gains ~150 words. The Evidence Expectations
section now has a routing-matrix subsection. The bundled-script
references inside the subsection (`code_graph.py path --to`,
`code_graph.py describe`, `db_graph.py find-instance`,
`db_graph.py path --down/--up`) match real CLI subcommands — verify by
running `python skills/spyglass/scripts/code_graph.py --help` and
`python skills/spyglass/scripts/db_graph.py --help` and confirming the
subcommands referenced exist.

**Estimated effort**: 25 min.

### Phase 2.3 — Field-ownership-before-query Core Directive

**File**: `skills/spyglass/SKILL.md`

**Anchor**: existing `Verify cardinality before fetch1()` bullet at
SKILL.md:30. Field ownership is a *cardinality-adjacent* concern — both
gate query-correctness on something the agent might assume but can't
see directly without verification. Insert the new bullet immediately
after the cardinality bullet so the two query-correctness rules are
neighbors.

**Edit**: New Core Directive bullet:

> - **Field ownership before query generation.** When writing a join or
>   restriction, every attribute used as a join key or in a restriction
>   dict must be traced to the table that *declares* it. DataJoint FK
>   inheritance only safely propagates **primary-key** fields; secondary
>   attributes on an upstream table do **not** automatically become
>   restriction-safe on downstream tables. The most common trap is
>   reused names — `nwb_file_name`, `interval_list_name`, `merge_id`,
>   `electrode_id` — appearing on multiple tables with different
>   declaration sites. If you can't cite where a field is declared,
>   treat the query as a hypothesis and verify via
>   `code_graph.py describe <Table>`, source-read, or `Table.heading`
>   before claiming the query works. Two failure shapes this guards
>   against: (a) **wrong owner for a real field** — the query runs but
>   routes through a table that doesn't actually declare the
>   restriction attribute, so the result depends on accidental
>   PK-inheritance rather than the schema you intend; (b) **invented
>   ownership of a real field** — claiming a field lives on a
>   downstream table when it's actually a secondary attribute of an
>   upstream table and doesn't propagate via FK inheritance.

**Validator**: same as 2.1.

**Success check**: SKILL.md gains ~120 words. The four trap-pattern
identifiers (`nwb_file_name`, `interval_list_name`, `merge_id`,
`electrode_id`) appear verbatim — the rule is concrete enough to be
self-triggering.

**Estimated effort**: 25 min.

### Phase 2.4 — `scrub_dj_config.py` literal-command form

**File**: `skills/spyglass/SKILL.md`

**Anchor**: existing `DataJoint config files` bullet at SKILL.md:32.
This is a one-line edit, not a new bullet — just expand the existing
bullet to include the literal command form. The eval-022 ws agent
talked *about* the script in prose without ever running it; adding the
literal copy-pasteable form bridges the discoverability gap.

**Edit**: Replace
> `python skills/spyglass/scripts/scrub_dj_config.py` (masks secret leaves)
with
> `python skills/spyglass/scripts/scrub_dj_config.py ~/.datajoint_config.json`
> (masks secret leaves; pass the config file path as the argument)

**Validator**: same as 2.1.

**Success check**: the bullet now includes a copy-pasteable command.

**Estimated effort**: 5 min.

### Phase 2.5 — Cascade template (counterfactual / recovery / parameter-swap)

**Files**:
- Primary: `skills/spyglass/references/destructive_operations.md` — new section.
- Cross-link edits: `decoding_pipeline.md`, `ripple_pipeline.md`,
  `position_pipeline.md`, `lfp_pipeline.md`,
  `spikesorting_v1_pipeline.md` — one-line link each.

**Decision** (from earlier discussion): the template lives in
`destructive_operations.md` as a major section, NOT in its own
`cascade_template.md`. Argument: the template is a destructive-ops
shape, just more general; splitting it into a separate file adds
lookup overhead without adding semantic clarity.

**Edit (destructive_operations.md)**: add a new section
`## Counterfactual / recovery / parameter-swap cascade template` with
the four required slots:

1. The new row / new merge_id (and that the old row is *not* mutated).
2. Downstream branches that must be re-selected and re-populated.
3. Unaffected sibling and upstream branches — explicitly enumerated.
4. `Table.descendants()` / `Table.ancestors()` (or
   `db_graph.py path --down <Class>` / `db_graph.py path --up <Class>`
   against a live DB) as the verification step.

**Edit (each pipeline reference)**: one-line cross-link near each
reference's parameter-swap or recovery example, of the form:
`> For "what cascades if I re-run with new params" / "how do I recover
from an in-place edit" questions, see the [cascade template](destructive_operations.md#counterfactual--recovery--parameter-swap-cascade-template).`

**Validator**: must pass. The cross-links are new and the validator
checks link landing content overlaps with the linking context — the
template content needs to mention "counterfactual" / "recovery" /
"parameter-swap" near the section heading so the link-overlap heuristic
is satisfied.

**Success check**: `destructive_operations.md` line count rises by
~50–80 lines (one major section). Five pipeline references each gain
one line. Validator stays green. Existing regression fixtures still
pass.

**Estimated effort**: 60 min.

### Phase 2.6 — `Raw`-as-runtime-fetch callout in `lfp_pipeline.md`

**File**: `skills/spyglass/references/lfp_pipeline.md`

**Anchor**: wherever the FK chain is documented in `lfp_pipeline.md`
(`grep -n "FK\|upstream\|dependencies" lfp_pipeline.md` to find the
exact line — likely in the pipeline overview section).

**Edit**: One-line callout where the FK chain is documented:
> Note: `Raw` is read at runtime inside `LFPV1.make()`, not declared as
> a static FK. Static-graph tools (`code_graph.py path --up LFPBandV1`)
> won't surface this dependency; the `make()` source is the
> ground-truth.

**Validator**: must pass. No new class names; line-number citations
are not added (we're not citing a specific line of `lfp.py:make`,
just naming the runtime-fetch fact). Should be green on first try.

**Success check**: `lfp_pipeline.md` gains 3 lines (callout + blank
lines around it).

**Estimated effort**: 10 min.

### Phase 2.7 — Clusterless plumbing-vs-input callout in `decoding_pipeline.md`

**File**: `skills/spyglass/references/decoding_pipeline.md`

**Anchor**: wherever clusterless decoding flow is documented (likely a
section like "Clusterless Decoding Flow" or similar).

**Edit**: New subsection
`### Clusterless: what's needed from curation` (the framing we agreed
on after the user's eval-100 correction):

> Clusterless decoding's relationship to curation has two distinct layers:
>
> 1. **Plumbing requirement**:
>    `UnitWaveformFeaturesSelection` FKs
>    `SpikeSortingOutput.proj(spikesorting_merge_id="merge_id")`, and
>    the v1 waveform-features `make()` reads from
>    `SpikeSortingOutput.CurationV1` to recover `sorting_id`. So a
>    `CurationV1`-backed merge row must exist before
>    `UnitWaveformFeatures.populate()` will run.
>
> 2. **Scientific input**: the per-spike waveform features
>    (amplitudes, spike locations) are what flow into the decoder, NOT
>    the curated accept/reject labels. So an initial curation that
>    registers the sort in the merge table is enough; ongoing
>    accept/reject curation does not change the clusterless result.
>
> Avoid the binary "curation is required" / "curation is bypassed"
> framings — both are wrong. The right framing is: an initial curation
> that creates the `SpikeSortingOutput.CurationV1` merge row is
> required as plumbing/provenance; the *content* of accept/reject
> labels does not flow into clusterless decoding.

**Validator**: must pass. The class names referenced
(`UnitWaveformFeaturesSelection`, `SpikeSortingOutput.CurationV1`,
`UnitWaveformFeatures.make`) need to exist in current Spyglass —
verify with
`python skills/spyglass/scripts/code_graph.py describe UnitWaveformFeaturesSelection`
before committing. If `KNOWN_CLASSES` in `validate_skill.py` doesn't
include these, the validator's method-existence check may warn.

**Success check**: `decoding_pipeline.md` gains ~25 lines. The
clusterless plumbing fact is verifiable against current source via
`code_graph.py path --to UnitWaveformFeaturesSelection SpikeSortingOutput`.

**Estimated effort**: 25 min.

### Phase 2.8 — `key_source` concept callout in `runtime_debugging.md`

**File**: `skills/spyglass/references/runtime_debugging.md`

**Anchor**: section on populate-related debugging (likely "Populate
returns nothing" or similar — `grep -n "populate\|silent\|no rows"
runtime_debugging.md` finds the right sub-section).

**Edit**: New ~5-line callout:

> **Symptom: populate runs but produces zero rows.**
> If `Table.populate()` exits cleanly without raising and yet
> `len(Table & key)` is still 0, check the `key_source` of the
> Computed table — DataJoint subtracts already-populated keys from the
> `key_source` and only iterates over the difference. If the
> `key_source` is empty (because no upstream selection rows match, or
> a custom override returns empty), `populate()` has nothing to do
> and silently no-ops. Verify with
> `print(len(Table.key_source - Table))`. See DataJoint's
> [Computed table docs](https://docs.datajoint.org/) for the full
> `key_source` mechanism.

**Validator**: must pass. No new Spyglass class names.

**Success check**: `runtime_debugging.md` gains ~7 lines. The eval-099
ws agent (or its successor in Phase 4) should now have access to the
`key_source` concept when explaining a silent populate.

**Estimated effort**: 15 min.

### Phase 2 totals

- **8 commits**, ~3 hours of focused work.
- **Validator gate** between each commit; rollback if validator regresses.
- **No SKILL.md word-budget violation**: the four Core Directive edits
  add ~350 words to SKILL.md, well below the 500-word soft cap (current
  `SKILL.md` is ~1450 words; ceiling is ~3000).

## Phase 3 — Eval-set rubric corrections (1 commit, partial Phase 2 dependency)

**Refinement from review**: Phase 3 corrections do *not* all depend on
Phase 2. Specifically:

- **Eval-060** rubric correction is independent of Phase 2 — it's a
  pure rubric fix (`.describe()` → `fetch1("params")` + source-read).
  Could land before, after, or alongside Phase 2.
- **Eval-099** rubric correction depends on Phase 2.8 (the
  `key_source` callout) — without the skill content, the corrected
  rubric tests for a concept the skill doesn't yet teach.
- **Eval-041** rubric correction depends on Phase 2.1 (the
  verify-before-claim clarification) — the new behavioral check tests
  for the substantive fix the skill clarification enables.

**Recommended order**: still land Phase 3 *after* Phase 2 so all three
rubric corrections sit in one commit and the eval-set is consistent
with the skill state. The independent eval-060 correction could be
cherry-picked earlier if there's a reason (e.g., a separate issue
opens against eval-060), but otherwise commit-with-2-and-3-together
keeps the round-D state coherent.

**File**: `skills/spyglass/evals/evals.json`

### Phase 3.1 — Eval-041 behavioral check reframe

Replace the current behavioral check that fires symmetrically against
both conditions (both lost the same check by recommending
`git checkout`) with a positive check:

- **New behavioral check**: "Names `CHANGELOG.md` / `Table.alter()` /
  `pip install -e .` as the canonical fix path for schema drift after
  a git pull."
- **Forbidden substring**: `git checkout <sha>` rollback —
  explicitly forbidden so the eval can't pass by recommending the
  bypass.

### Phase 3.2 — Eval-060 rubric correction

Replace the `.describe()` / `.heading` literal-substring requirement
with a behavioral check that prefers `fetch1("params")` + source-read:

- **New behavioral check**: "Recommends inspecting the params blob via
  `(TrodesPosParams & key).fetch1('params')` rather than `.describe()`
  / `.heading` — for blob-bearing param tables, the heading only
  confirms a blob column exists, not what keys it carries."
- **Remove**: `.describe()` literal-substring requirement.

### Phase 3.3 — Eval-099 rubric correction

Remove the literal `key_source` substring requirement; replace with a
concept-level behavioral check:

- **New behavioral check**: "Names a way to debug a `populate()` that
  silently produces zero rows (e.g., the `key_source` mechanism, or
  `len(Table.key_source - Table)`)."
- **Remove**: literal `key_source` required-substring.

**Validator**: must pass. `evals.json` doesn't go through the
SKILL.md validator, but the rubric should still parse via
`evals/eval_metadata.json` consumers (test it by re-grading round-C's
eval-041, eval-060, eval-099 transcripts against the new rubric and
confirming the grading still produces sensible output).

**Estimated effort**: 35 min.

## Phase 4 — Round-D narrow eval rerun (1 commit per artifact)

**Refinement from review**: Phase 4 success criteria gain a regression
clause: the narrow rerun must NOT reduce previously-passing with_skill
behaviors on evals where tool routing could add overhead (specifically
028, 029, 107). The desired behavior is *better evidence*, not *worse
answer directness*.

### Phase 4.0 — Round-D run setup

Before any dispatch, create the run directory and metadata:

1. **Pin `$SPYGLASS_SRC`**: record the current upstream Spyglass
   commit hash. Add it to a new
   `skills/spyglass-workspace/runs/round-d-<date>/run.json`.
2. **Create the run directory**: copy the round-C
   `iteration-N/` skeleton structure (just `eval_metadata.json` +
   empty `outputs/` dirs) for the narrow subset.
3. **Use the dispatch templates**: `dispatch_prompts.md` placeholders
   are now portable and pin to a local Spyglass checkout — fill them
   with the round-D values.

### Phase 4.1 — Narrow eval subset (16 unique evals = 32 dispatches)

Targeted subset organized by which Phase 2 edit each eval verifies:

| Edit verified | Eval IDs |
| --- | --- |
| Verify-before-claim (2.1) | 118, 041 |
| Tool routing (2.2) | 028, 029, 089, 107, 108 |
| Field ownership (2.3) | 089, 105 (eval-089 verifies both 2.2 and 2.3) |
| Cascade template (2.5) | 085, 087, 088, 113 |
| `Raw`-as-runtime-fetch (2.6) | 072 |
| Clusterless plumbing-vs-input (2.7) | 100 |
| `key_source` concept (2.8) | 099 |

Net: **16 unique eval IDs × 2 conditions = 32 dispatches**, runnable
in one batch. Use the new dispatch templates so the no-bundle-peek
and no-grading-peek prohibitions are enforced.

### Phase 4.2 — Success and regression criteria

**Success criteria** (the narrow rerun must hit ALL of these for
Round-D to ship):

1. **Eval-118 ws** ≥ baseline pass rate (current: ws 5/7, bs 7/7 → ws should match or beat bs).
2. **Eval-041 ws** ≥ baseline pass rate (current: ws 1/7, bs 3/7 → ws should match or beat bs).
3. **Eval-028, 107, 108 ws transcripts** show
   `code_graph.py path --to` invocations on at least 1 of the 3 evals.
   This is a *tool-utilization* check (parse transcripts post-hoc),
   not a rubric pass/fail.
4. **Eval-089 ws response** restricts via `SpikeSortingRecordingSelection`
   (the correct table per source verification), not via
   `SpikeSortingRecording`. Specific behavioral check.
5. **Eval-105 ws response** acknowledges that `camera_name` on
   `VideoFile` is a secondary attribute matched by name, not a
   declared FK. Specific behavioral check.
6. **Eval-085, 087, 088, 113 ws responses** each enumerate at least
   2 unaffected sibling branches AND name `descendants()` /
   `ancestors()` (or `db_graph.py path` equivalent). Specific
   behavioral check.
7. **Eval-099 ws response** names a way to debug a silent populate
   (key_source concept, even if the literal token isn't there) —
   verifies Phase 2.8 made the concept available without needing the
   rubric literal.
8. **Eval-072 ws response** acknowledges `Raw` is a runtime fetch
   (not in the static FK graph) — verifies Phase 2.6.
9. **Eval-100 ws response** uses the plumbing-vs-input framing
   (avoids "curation is required" or "curation is bypassed" binary)
   — verifies Phase 2.7.

**Regression criterion** (NEW — must NOT be triggered):

10. **No regression on previously-passing with_skill behaviors.**
    Specifically:

    - **Eval-028, 029, 107**: ws response directness should not degrade.
      Round-C ws scored 5/5 on eval-028 behavioral, 4/5 on eval-029, 5/5
      on eval-107. After Phase 2, these must still pass. Risk shape:
      tool-routing rule could prompt agents to *spend more time
      describing tools they used* and less on the substantive answer.
      The desired behavior is *running the right tool more often*, not
      *talking about it more*.
    - **No new ws-worse-than-bs cases.** Round-C had 3 (eval-118,
      eval-041, eval-106). After Phase 2 the count should drop to ≤1
      (eval-106 may persist since its miss was rubric-friction, not a
      design issue we're addressing). If a *new* eval enters the
      ws-worse list, that's a regression and Phase 2 needs revising.
    - **No degradation on saturated ties.** Eval clusters that scored
      ws 100% / bs 100% in round-C (`runtime-errors`,
      `schema-introspection`) should not slip in round-D.

If any of criteria 1–9 fails, the corresponding Phase 2 edit needs
revision before merging. If criterion 10 fires, the *added skill
content* is interfering with the model's existing answer-directness
and needs scoping back.

### Phase 4.3 — Aggregation and recording

After all 32 dispatches complete and grade:

1. Run `make_plots.py` against the round-D run dir (relative-path
   resolution already supports this).
2. Add a "Round-D narrow rerun" section to a new
   `runs/round-d-<date>/findings.md` documenting the success/regression
   criterion outcomes.
3. Update `run.json` with completed-at timestamp and any
   contamination caveats observed.

**Estimated effort**: 90 min wall-clock (60 min waiting on subagents
+ 30 min orchestration / aggregation / write-up).

## Phase 5 — Optional: full 130-eval Round-D sweep

**Decision rule**: only run if Phase 4 confirms all 9 success criteria
hit AND the regression criterion (#10) is NOT triggered. The narrow
rerun is enough to validate the edits did what they were designed to
do; the full sweep is for headline numbers and for catching regressions
in clusters Phase 4 didn't touch.

If we run it: same 7-batch stratified shape as round-C, lands in
`runs/round-d-<date>/`. ~$200 / ~8M tokens. Compare headline pass rates
against round-C to confirm round-D moved the needle as expected.

## Phase 6 — Frontmatter trigger audit (parallelizable, optional)

Run `skill-creator`'s description-improver against the live eval set
plus a small adversarial set of *non-Spyglass* prompts (pynwb raw
access, generic DataJoint, etc.) to confirm activation accuracy didn't
drift after the Phase 2 SKILL.md edits. ~30 min.

Can run in parallel with Phase 4 — the description doesn't change in
Phase 2 (only the body), but verifying activation hasn't drifted is
worth doing once SKILL.md changes ship.

## What goes in each commit (summary table)

| Commit | Phase | Files | Effort |
| --- | --- | --- | --- |
| 1 | 2.1 verify-before-claim | SKILL.md | 10 min |
| 2 | 2.2 tool routing | SKILL.md | 25 min |
| 3 | 2.3 field ownership | SKILL.md | 25 min |
| 4 | 2.4 scrub_dj literal | SKILL.md | 5 min |
| 5 | 2.5 cascade template | destructive_operations.md + 5 pipeline refs | 60 min |
| 6 | 2.6 Raw runtime fetch | lfp_pipeline.md | 10 min |
| 7 | 2.7 clusterless plumbing | decoding_pipeline.md | 25 min |
| 8 | 2.8 key_source | runtime_debugging.md | 15 min |
| 9 | 3 rubric corrections | evals.json | 35 min |
| 10 | 4.0 round-D setup | runs/round-d-<date>/run.json + iteration-1/ skeleton | 10 min |
| 11 | 4.3 round-D narrow rerun results | runs/round-d-<date>/{iteration-1, summary, findings.md} | dispatch + 30 min aggregation |

11 commits total, ~5–6 hours of focused work spread across however
many sessions you want. Commits 1–9 are pure file edits with validator
gates. Commits 10–11 are workspace artifacts (analogous to round-C).

Phase 5 (full sweep) and Phase 6 (frontmatter audit) are conditional
follow-ons.

## Decision points worth flagging now

1. **Should commit 5 (cascade template) split into 2 commits?** One
   for the new section in `destructive_operations.md`, one for the 5
   cross-link edits across pipeline references. Argument for splitting:
   each commit is smaller and more reviewable. Argument against: the
   cross-links are meaningless without the link target, so the natural
   atomic change is "add target + add links to it." Recommendation:
   single commit unless one of the 5 pipeline references needs
   non-trivial re-structuring (then split that reference's edit out).

2. **Round-D run-id format**: `round-d-2026-04-XX` matches the
   round-C convention. If the actual round-D rerun spans multiple
   days, name it for the start date. Discrepancy with run.json's
   `started_at` / `completed_at` fields is fine — the directory name
   is the primary key, the timestamps capture the duration.

3. **Whether to include `eval-106` in the narrow rerun.** Round-C had
   it as a ws-worse case but the user (correctly) characterized it as
   rubric-friction not a design issue. Including eval-106 in Phase 4
   would test whether the rubric still mis-fires after Phase 3.2
   addresses the eval-060 rubric (different eval, but same rubric-fix
   class). Recommendation: include it — adds 1 dispatch to the 16-eval
   subset, costs $1, gives a regression check on whether eval-106
   stays a ws-worse case.

These decisions can be deferred until the corresponding phase begins;
flagging them here so they aren't surprises.
