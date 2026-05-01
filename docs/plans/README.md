# Plan Documents

This directory holds planning artifacts for the Spyglass skill. Keep historical
plans in place: some scripts, tests, and references intentionally cite these
files as design rationale.

## How to Use This Directory

- Start with **Active / next work** for implementation decisions.
- Use **Living strategy and backlog** for roadmap-level choices.
- Use **Historical / shipped** for design rationale and provenance, not current
  behavior.
- Use **Superseded / not executing** only for background on rejected or paused
  designs.

When adding a new plan, put a short `Status` line near the top and link to the
current source of truth if the plan is later executed or superseded.

## Active / Next Work

| Plan | Status | Use for |
| --- | --- | --- |
| [round-e-impl-plan.md](round-e-impl-plan.md) | Active / next measurement plan | Re-grading round-d, targeted behavioral reruns, and gated full sweep decisions. |
| [reference-naming-rename-plan.md](reference-naming-rename-plan.md) | Proposed standalone cleanup | Future reference-file rename work after content PRs settle. |
| [outside-collaborator-sharing-plan.md](outside-collaborator-sharing-plan.md) | Draft ready to execute | Adding outside-collaborator sharing/onboarding coverage. |

## Living Strategy and Backlog

| Plan | Status | Use for |
| --- | --- | --- |
| [skill-expansion-roadmap.md](skill-expansion-roadmap.md) | Roadmap | Long-range direction for onboarding, data health, and meta-analysis surfaces. |
| [bundled-scripts-issue.md](bundled-scripts-issue.md) | Living script backlog | Candidate bundled scripts and upstream candidates after `code_graph.py` / `db_graph.py`. |
| [llm-script-priorities.md](llm-script-priorities.md) | LLM-priority ranking | Deciding whether a proposed script helps agents beyond existing graph tools. |
| [problem-solving-templates-impl-plan.md](problem-solving-templates-impl-plan.md) | Partially executed design reference | Reusable reasoning-template strategy; keep templates in owning references, not a catch-all file. |

## Historical / Shipped

| Plan | Status | Use for |
| --- | --- | --- |
| [round-d-impl-plan.md](round-d-impl-plan.md) | Historical / executed by PR #26 | Round-D edit sequence and narrow-rerun rationale. |
| [code-graph-impl-plan.md](code-graph-impl-plan.md) | Historical / shipped | `code_graph.py` design rationale; current behavior lives in code/tests and `info --json`. |
| [inquiry-time-navigation-plan.md](inquiry-time-navigation-plan.md) | Historical / partially shipped | Original navigation-primitive framing; code graph and DB graph shipped, disk graph deferred. |
| [reference-key-hygiene-impl-plan.md](reference-key-hygiene-impl-plan.md) | Mostly complete / deferred tail | Reference key-hygiene batches and validator strategy. |
| [eval-gap-closure-impl-plan.md](eval-gap-closure-impl-plan.md) | Historical / executed | Eval IDs 54-78 expansion and taxonomy cleanup. |
| [eval-failure-mode-coverage-impl-plan.md](eval-failure-mode-coverage-impl-plan.md) | Historical / executed | Evals covering hallucination, resource selection, workflow recovery, counterfactuals, and ambiguity. |
| [eval-round2-expansion-impl-plan.md](eval-round2-expansion-impl-plan.md) | Historical / executed | Round-2 eval expansion and source-correction history. |
| [round-3-feedback-organization.md](round-3-feedback-organization.md) | Historical source material | Raw organized feedback from issues/PR review. |
| [round-3-feedback-triage.md](round-3-feedback-triage.md) | Historical triage | Accept / modify / reject decisions for round-3 feedback. |
| [round-3-feedback-impl-plan.md](round-3-feedback-impl-plan.md) | Historical implementation plan | Concrete application plan for round-3 feedback. |

## Superseded / Not Executing

| Plan | Status | Use for |
| --- | --- | --- |
| [tier1-scripts-impl-plan.md](tier1-scripts-impl-plan.md) | Superseded / paused | Background on scripts displaced by `code_graph.py` and `db_graph.py`. |
| [schema-fact-validator-impl-plan.md](schema-fact-validator-impl-plan.md) | Not executing | Historical schema-fact validator design and audit outcome. |
