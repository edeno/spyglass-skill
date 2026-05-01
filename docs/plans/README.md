# Plan Documents

This directory holds planning artifacts for the Spyglass skill. Keep historical
plans in place: some scripts, tests, and references intentionally cite these
files as design rationale.

## How to Use This Directory

- **Execute** means the plan is concrete enough to run without another planning
  pass.
- **Decide first** means the idea may be worth doing, but needs a human choice
  or a fresh scope check before implementation.
- **Think / strategy** means the document is for design direction, prioritizing,
  or future-roadmap discussion.
- **Historical** means the work already shipped; use it for rationale, not as a
  current task list.
- **Superseded** means do not execute as written.

When adding a new plan, put a short `Status` line near the top and link to the
current source of truth if the plan is later executed or superseded.

## Execute Now

These are the only plans that should be treated as current execution work.

| Plan | Action | Use for |
| --- | --- | --- |
| [round-e-impl-plan.md](round-e-impl-plan.md) | Execute after PR #26 merges | Re-grading round-d, targeted behavioral reruns, and gated full sweep decisions. |

## Decide Before Executing

These are plausible future work, but should not be picked up blindly. Re-check
scope, branch state, and whether the need still exists before implementation.

| Plan | Action | Use for |
| --- | --- | --- |
| [reference-naming-rename-plan.md](reference-naming-rename-plan.md) | Decide when to schedule | Standalone reference-file rename work after content PRs settle. |
| [outside-collaborator-sharing-plan.md](outside-collaborator-sharing-plan.md) | Decide whether still priority | Adding outside-collaborator sharing/onboarding coverage. |
| [problem-solving-templates-impl-plan.md](problem-solving-templates-impl-plan.md) | Re-scope before executing more | Reusable reasoning-template strategy; PR #26 already implemented several pieces. |

## Think / Strategy / Backlog

These docs are for prioritization and design discussion. They are not direct
implementation queues.

| Plan | Action | Use for |
| --- | --- | --- |
| [skill-expansion-roadmap.md](skill-expansion-roadmap.md) | Think / roadmap | Long-range direction for onboarding, data health, and meta-analysis surfaces. |
| [bundled-scripts-issue.md](bundled-scripts-issue.md) | Think / backlog | Candidate bundled scripts and upstream candidates after `code_graph.py` / `db_graph.py`. |
| [llm-script-priorities.md](llm-script-priorities.md) | Think / prioritize | Deciding whether a proposed script helps agents beyond existing graph tools. |

## Historical / Shipped

Do not execute these as current plans. Use them to understand why shipped
features look the way they do.

| Plan | Action | Use for |
| --- | --- | --- |
| [round-d-impl-plan.md](round-d-impl-plan.md) | Historical | Round-D edit sequence and narrow-rerun rationale. |
| [code-graph-impl-plan.md](code-graph-impl-plan.md) | Historical | `code_graph.py` design rationale; current behavior lives in code/tests and `info --json`. |
| [inquiry-time-navigation-plan.md](inquiry-time-navigation-plan.md) | Historical | Original navigation-primitive framing; code graph and DB graph shipped, disk graph deferred. |
| [reference-key-hygiene-impl-plan.md](reference-key-hygiene-impl-plan.md) | Historical with deferred tail | Reference key-hygiene batches and validator strategy. |
| [eval-gap-closure-impl-plan.md](eval-gap-closure-impl-plan.md) | Historical | Eval IDs 54-78 expansion and taxonomy cleanup. |
| [eval-failure-mode-coverage-impl-plan.md](eval-failure-mode-coverage-impl-plan.md) | Historical | Evals covering hallucination, resource selection, workflow recovery, counterfactuals, and ambiguity. |
| [eval-round2-expansion-impl-plan.md](eval-round2-expansion-impl-plan.md) | Historical | Round-2 eval expansion and source-correction history. |
| [round-3-feedback-organization.md](round-3-feedback-organization.md) | Historical | Raw organized feedback from issues/PR review. |
| [round-3-feedback-triage.md](round-3-feedback-triage.md) | Historical | Accept / modify / reject decisions for round-3 feedback. |
| [round-3-feedback-impl-plan.md](round-3-feedback-impl-plan.md) | Historical | Concrete application plan for round-3 feedback. |

## Superseded / Not Executing

Do not execute these as written. They are retained to document rejected or
paused design paths.

| Plan | Action | Use for |
| --- | --- | --- |
| [tier1-scripts-impl-plan.md](tier1-scripts-impl-plan.md) | Do not execute | Background on scripts displaced by `code_graph.py` and `db_graph.py`. |
| [schema-fact-validator-impl-plan.md](schema-fact-validator-impl-plan.md) | Do not execute | Historical schema-fact validator design and audit outcome. |
