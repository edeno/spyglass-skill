# Bundled scripts — LLM priority ranking

**Date:** 2026-04-22
**Status:** Draft — ordering for implementation sequencing.

Ranks the scripts from [bundled-scripts-issue.md](bundled-scripts-issue.md) by **how much they multiply LLM effectiveness**, not by general user utility. When LLM priority diverges from user priority (usually: admin/workflow tools score lower for LLMs), the LLM perspective wins here because the skill's target user is Claude invoking them.

## Scoring criteria

Five things make a script LLM-grade. Weights descending:

1. **Closes a hallucination vector.** If the script makes an LLM's guess-from-training-data shape *structurally impossible* (wrong Params name → wrong API call → wrong FK chain), that's the biggest single unlock. Rare across the list.
2. **Provides structured evidence.** JSON / Mermaid / CSV output the LLM can cite *as evidence* rather than summarize from prose. Preferred over human-readable status lines.
3. **Ground truth over code generation.** Reading current DB / env state is strictly more valuable than producing boilerplate — the LLM can write code, it can't see state.
4. **Bounded runtime.** A hard timeout means the LLM can invoke the script in an autonomous loop without worrying about hangs. Scripts without `--timeout` on network calls score lower.
5. **Replaces multi-step reconstruction.** Each script call that subsumes N context-burning rounds (`.parents()` + `.children()` + `.describe()` + follow-up queries → one Mermaid graph) is worth N in saved tokens and reduced failure-to-converge risk.

## Tier 1 — Ship first (highest LLM leverage)

These close the most context-burning failure modes. Each prevents a recurring LLM wrong-answer pattern.

| Script | Status | Why it's Tier 1 |
| --- | --- | --- |
| **`describe_params.py`** | unshipped | Closes the **#1 hallucination vector** in the skill: LLMs can't see `*Params` Lookup contents and invent names from training data. One invocation returns ground truth for every Params row feeding a pipeline, with usage counts. Highest single expected lift. |
| **`visualize_schema_neighborhood.py`** | unshipped | Mermaid output is LLM-native. Replaces 3+ round-trips (`.parents()`, `.children()`, `.describe()`) with one structured graph. Unblocks agent reasoning about any unfamiliar table. |
| **`map_si_to_spyglass.py`** | unshipped | Closes a specific, high-probability hallucination: SpikeInterface API drift (`WaveformExtractor` ↔ `SortingAnalyzer` across the 0.100 boundary). Prevents agents from pasting stale code from training data. Best implemented as a tiny script over a YAML catalog. |
| `verify_spyglass_env.py` | **shipped** | Seven checks + JSON output + bounded timeout = LLM-ideal. Env assumptions become cite-able evidence instead of "trust me." |
| `scrub_dj_config.py` | **shipped** | Safe ground-truth read of DB config. Closes the password-leak-into-context hallucination-adjacent hazard. |

**Next-3 recommendation for implementation:** `describe_params.py`, `visualize_schema_neighborhood.py`, `map_si_to_spyglass.py`. All three close hallucination vectors that no other script addresses; all three have modest implementation cost.

## Tier 2 — Ship second (high-value structured ground truth)

Not hallucination-blockers, but each gives the LLM ground truth it would otherwise have to reconstruct.

| Script | Why it's Tier 2 |
| --- | --- |
| **`session_summary.py`** | "What's in this session?" is the first question every interaction starts with. Walks the 5 merge masters in one call; replaces manual session-orientation rounds. |
| **`pipeline_provenance.py`** | "What produced this result?" is reproducibility bedrock. Structured dependency + params chain lets an LLM answer "is this result trustworthy" without improvising. |
| **`check_analysis_files.py`** | Thin wrapper over `AnalysisNwbfile.check_all_files()`. Ground truth about "is the data actually on disk?" — a question the LLM otherwise can't answer reliably without running fetch and catching FileNotFoundError. |
| **`trace_restriction.py`** | Thin wrapper over `RestrGraph` / `TableChain`. "What does this restriction affect across the DAG?" in structured form. |
| **`generate_selection_inserts.py`** | Retires the "reconstruct Selection-chain from tutorial cells" pattern that every new user runs into. Code-gen, not evidence, so slightly lower than pure-ground-truth scripts; but the per-pipeline chains are easy for LLMs to get off-by-one, so retiring that reconstruction is high value. |
| **`fetch_merge_row.py`** | Retires Common Mistake #1 (merge chain reconstruction). The script gets the `merge_get_part → fetch1('KEY') → (Master & ...)` sequence right so the LLM doesn't have to. |

## Tier 3 — High-value in specific scenarios

Each is a clean win when its triggering scenario shows up; none is the first thing an LLM should reach for.

| Script | Scenario |
| --- | --- |
| `reproduce_populate_failure.py` | Populate failed in a parallel run; LLM needs to reproduce one key's traceback. Transforms an unstructured triage into a structured one. |
| `check_schema_integrity.py` | Post-`git pull` drift detection. Catches "column in Python not yet in DB" before runtime KeyError. |
| `diff_nwb.py` | Reproducibility forensics — "why did this analysis regenerate differently?" Wraps `H5pyComparator`. Narrow but high-signal when needed. |
| `check_merge_integrity.py` | Merge-table pre-flight. Catches registry drift before `merge_get_part` fails with a confusing error. |
| `dandi_preflight.py` | Pre-DANDI-upload metadata check. Niche scope, but when it fires it saves hours. |
| `validate_lfp_params.py` | LFP silent-wrong-data (Nyquist / filter compat). Closes a specific hallucination vector for the LFP pipeline. Pipeline-specific; expect siblings for spike-sort / DLC / decoding. |
| `safe_delete_preview.py` | Pre-destructive dry-run. Structured evidence of "what would be deleted." |
| `trace_delete_blockers.py` | Post-delete-failure diagnosis. Complement to `find_insert_fail` (upstream, reference-only). |
| `diff_keys.py` | Batch-populate triage. "Why did these 5 fail but not these 47?" One column diff. |
| `scaffold_pipeline.py` | New pipeline authoring. Code-gen; LLMs can do this with the reference, but the script encodes the non-negotiables mechanically. |

## Tier 4 — Lower LLM-specific leverage

Useful to humans; LLMs rarely benefit proportionally.

| Script | Why lower priority for LLMs |
| --- | --- |
| `disk_usage_report.py` | Lab-admin tool. LLMs rarely triage storage decisions; humans do. Ship when a lab admin asks. |
| `fetch_figurl_labels.py` | Workflow automation (UI → DB). Closes human toil, doesn't give the LLM new reasoning power. |
| `cardinality_check.py` | Teaching-oriented; likely folds into a code block in [feedback_loops.md](../../skills/spyglass/references/feedback_loops.md) rather than shipping as a bundled script. |

## Reference-only helpers — already maxed-out leverage

Not bundled scripts; already routed from the right references. Listed for completeness since an LLM reading this doc should know they exist:

- `HelperMixin.find_insert_fail(key)` — IntegrityError diagnosis, cited from [runtime_debugging.md § H](../../skills/spyglass/references/runtime_debugging.md).
- `HelperMixin.check_threads()` — lock-contention diagnosis, cited from [runtime_debugging.md § I](../../skills/spyglass/references/runtime_debugging.md).
- `HelperMixin.get_table_storage_usage()` — per-table bytes, cited from [destructive_operations.md](../../skills/spyglass/references/destructive_operations.md).
- `AnalysisRegistry.get_all_classes()` — cross-team AnalysisNwbfile subclasses, cited from [custom_pipeline_authoring.md](../../skills/spyglass/references/custom_pipeline_authoring.md).
- `HelperMixin.delete_orphans(dry_run=True)` — rows-with-no-children, cited from `destructive_operations.md`, `common_mistakes.md`, `merge_methods.md`, `spyglassmixin_methods.md`.

## Cross-cutting requirements (from the design conventions section of the issue doc)

Every script above is expected to conform — not optional:

1. `--json` mode wrapping output in a reproducibility envelope (`spyglass_version`, `spyglass_commit`, `timestamp_utc`, `dj_user`, `dj_host`, …).
2. `--timeout` on any network-touching operation with a sane default (≤ 10 s).
3. Never-leak invariant for scripts reading secrets: stdout empty on any failure path; exception-class-only reporting.
4. `CheckResult`-style structured evidence; human and JSON modes render from the same data.
5. `Lifecycle:` paragraph in the module docstring naming the upstream migration target.

LLM-tier placement above is conditional on these being met. A Tier-1 script without structured evidence fails its Tier-1 claim.

## How to use this ranking

- **Next three PRs:** ship Tier 1 unshipped items (`describe_params.py`, `visualize_schema_neighborhood.py`, `map_si_to_spyglass.py`) before anything in Tier 2+.
- **Backlog grooming:** when a Tier 3 script's triggering scenario appears in a real user interaction, promote to next-up; otherwise hold.
- **New proposals:** score against the five criteria above before adding to the issue list. Tier 4-shaped scripts (admin / workflow) are still valid but should carry a clear "humans first, not LLMs" note so future contributors don't conflate utility with LLM leverage.
