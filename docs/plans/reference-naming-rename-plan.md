# Reference naming and rename plan

This plan defines a consistent naming policy for Spyglass skill reference files
and a staged rename path. It is intentionally separate from the Round-D content
edits: renames are mechanical, high-churn, and should be reviewed independently
from prose or eval changes.

## Goals

- Make pipeline reference filenames reflect the pipeline and version they own.
- Keep cross-cutting references unversioned.
- Preserve the current progressive-disclosure model: `SKILL.md` routes to one
  reference at a time, and filenames should reinforce that routing.
- Avoid mixed naming schemes where some v1 pipeline references encode `_v1_`
  and others do not.

## Current audit

The current reference set uses two naming styles:

- Versioned/source-specific pipeline references:
  - `position_dlc_v1_pipeline.md`
  - `position_trodes_v1_pipeline.md`
  - `spikesorting_v1_pipeline.md`
  - `spikesorting_v1_analysis.md`
  - `spikesorting_v0_legacy.md`
- Unversioned pipeline-like references:
  - `behavior_pipeline.md`
  - `decoding_pipeline.md`
  - `lfp_pipeline.md`
  - `linearization_pipeline.md`
  - `mua_pipeline.md`
  - `ripple_pipeline.md`

This is the main inconsistency. The unversioned pipeline-like files document
current Spyglass v1 pipeline classes, while similarly scoped position and spike
sorting files include the version in the filename.

## Naming policy

1. **Concrete versioned pipeline implementations use**
   `<domain>_vN_pipeline.md`.

   Examples:
   - `lfp_v1_pipeline.md`
   - `ripple_v1_pipeline.md`
   - `decoding_v1_pipeline.md`

2. **Source-specific pipeline variants include the source before the version.**

   Existing names already follow this rule:
   - `position_dlc_v1_pipeline.md`
   - `position_trodes_v1_pipeline.md`

3. **Post-pipeline analysis surfaces include both version and role.**

   Existing name:
   - `spikesorting_v1_analysis.md`

4. **Legacy references encode the legacy version and role.**

   Existing name:
   - `spikesorting_v0_legacy.md`

5. **Cross-cutting references stay unversioned.**

   Do not add `_v1_` to setup, DataJoint, common-table, merge-method,
   debugging, destructive-operation, workflow, dependency, export, FigURL,
   or custom-pipeline-authoring references unless the file is narrowed to a
   single versioned implementation.

6. **Umbrella references stay unversioned.**

   `position_pipeline.md` should remain the umbrella for the position merge
   layer and source dispatch, while Trodes and DLC keep their source-specific
   v1 filenames.

## Proposed rename map

Rename these in a dedicated rename-only commit:

| Current file | Proposed file | Reason |
| --- | --- | --- |
| `behavior_pipeline.md` | `behavior_moseq_v1_pipeline.md` | The file is specifically the MoSeq behavior pipeline, not all behavior. |
| `decoding_pipeline.md` | `decoding_v1_pipeline.md` | Documents current v1 decoding tables and `DecodingOutput`. |
| `lfp_pipeline.md` | `lfp_v1_pipeline.md` | Documents `LFPV1`, `LFPOutput`, `LFPBandV1`, and `LFPBandSelection`. |
| `linearization_pipeline.md` | `linearization_v1_pipeline.md` | Documents current v1 linearization pipeline. |
| `mua_pipeline.md` | `mua_v1_pipeline.md` | Documents `MuaEventsV1` pipeline surface. |
| `ripple_pipeline.md` | `ripple_v1_pipeline.md` | Documents `RippleTimesV1` pipeline surface. |

Optional non-pipeline renames if the rename PR becomes a broader reference
naming cleanup:

| Current file | Proposed file | Reason |
| --- | --- | --- |
| `feedback_loops.md` | `verification_loops.md` | The file now owns validator/fix/proceed loops, tool routing, field-ownership cross-links, and static-vs-runtime guidance. "Feedback loops" undersells that routing role. |
| `workflows.md` | `cross_table_workflows.md` | Narrows the file away from catch-all workflow status and toward its real surface: assembling queries and recipes across multiple tables/pipelines. |
| `dependencies.md` | `external_dependencies.md` | Clarifies that the file is the external-package boundary, not internal table dependencies. |
| `ingestion.md` | `nwb_ingestion.md` | Makes the NWB-specific ingest surface explicit and matches the file title. |

Do not include these optional renames if the goal is only to make concrete
pipeline filenames version-consistent. If included, keep them in the same
rename-only PR but preferably in a separate commit from the pipeline renames.

Do not rename these:

| File | Reason |
| --- | --- |
| `position_pipeline.md` | Umbrella / merge-layer reference; source-specific v1 files already exist. |
| `position_dlc_v1_pipeline.md` | Already follows policy. |
| `position_trodes_v1_pipeline.md` | Already follows policy. |
| `spikesorting_v1_pipeline.md` | Already follows policy. |
| `spikesorting_v1_analysis.md` | Already follows policy. |
| `spikesorting_v0_legacy.md` | Already follows policy. |
| `figurl.md` | Integration / visualization reference, not a single pipeline implementation. |
| `export.md` | Paper/export workflow, not a versioned pipeline. |
| `dependencies.md` | External-package boundary, cross-cutting. Rename only if doing the optional broader cleanup above. |
| `workflows.md` | Cross-table workflow recipes, cross-cutting. Rename only if doing the optional broader cleanup above. |
| `runtime_debugging.md` | Runtime triage across pipelines, cross-cutting. |
| `destructive_operations.md` | Safety policy across pipelines, cross-cutting. |
| `feedback_loops.md` | Verification/tool-routing loops, cross-cutting. Rename only if doing the optional broader cleanup above. |
| `common_mistakes.md` | Cross-cutting anti-pattern reference. |
| `common_tables.md` | Common ingest and metadata tables, not a pipeline. |
| `datajoint_api.md` | Query/API reference, not a pipeline. |
| `merge_methods.md` | Merge-method API reference, not a pipeline. |
| `group_tables.md` | Group-table pattern reference across pipelines. |
| `spyglassmixin_methods.md` | Mixin-method API reference, not a pipeline. |
| `custom_pipeline_authoring.md` | Authoring guide, not a concrete pipeline. |
| `setup_install.md`, `setup_config.md`, `setup_troubleshooting.md` | Setup surfaces, not pipelines. |
| `ingestion.md`, `populate_all_common_debugging.md` | Ingestion/common-populate surfaces, not versioned analysis pipelines. Rename `ingestion.md` only if doing the optional broader cleanup above. |

## Mechanical update checklist

In the rename-only commit:

1. Rename files with `git mv`.
2. Update `skills/spyglass/SKILL.md` reference-routing links and labels.
3. Update all internal markdown links in `skills/spyglass/references/*.md`.
4. Update eval references in `skills/spyglass/evals/evals.json`.
5. Update bundled docs/plans that mention old filenames only if they are
   current planning artifacts. Historical benchmark summaries can remain as
   historical records unless they are part of active validation.
6. Run:

   ```bash
   rg "behavior_pipeline|decoding_pipeline|lfp_pipeline|linearization_pipeline|mua_pipeline|ripple_pipeline|feedback_loops|workflows|dependencies|ingestion" skills docs
   ./skills/spyglass/scripts/validate_all.sh --baseline-warnings 3
   ```

7. If the validator reports broken links or stale eval references, fix only
   those references. Do not edit content prose in the rename commit.

## Review criteria

The rename PR is ready when:

- No references to the old filenames remain in active skill files, evals, or
  current plans.
- `SKILL.md` still routes each user intent to exactly one primary reference.
- The validator passes with no new failures and no new warnings beyond the
  accepted baseline.
- The diff is mechanically reviewable: file moves plus link updates only.

## Risks and mitigations

- **Risk: large noisy diff hides content changes.**
  - Mitigation: rename-only commit; no prose edits.

- **Risk: eval artifacts or old summaries refer to previous filenames.**
  - Mitigation: update active eval definitions; leave historical benchmark
    summaries alone unless they are regenerated.

- **Risk: agents lose continuity with prior discussions that mention old names.**
  - Mitigation: keep one compatibility note in the PR description, not in the
    skill references.

- **Risk: `behavior_moseq_v1_pipeline.md` is too specific if future behavior
  pipelines are added.**
  - Mitigation: that specificity is intentional. Add a future
    `behavior_pipeline.md` umbrella only when Spyglass has multiple behavior
    pipeline references that need dispatch.

## Recommendation

Do this after the current Round-D content PR merges, as a standalone
reference-organization PR. It improves long-term consistency, but it should not
be mixed with behavior-changing skill guidance.
