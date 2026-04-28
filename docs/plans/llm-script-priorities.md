# Bundled scripts — LLM priority ranking

**Date:** 2026-04-22
**Status:** Revised 2026-04-27 after `code_graph.py` and `db_graph.py`.

Ranks the scripts from [bundled-scripts-issue.md](bundled-scripts-issue.md) by **how much they multiply LLM effectiveness**, not by general user utility. When LLM priority diverges from user priority (usually: admin/workflow tools score lower for LLMs), the LLM perspective wins here because the skill's target user is Claude invoking them.

## Current recommendation

Do **not** implement the old "next three scripts" list as written. The
source-only `code_graph.py` and runtime `db_graph.py` now cover the highest
value structural facts: table existence, source dependencies, runtime
headings, row counts, merge IDs, set operations, and source/runtime
disagreement. The next work should consolidate those tools, add evals that
force agents to use them, and only add a new script when the failure mode is
not already covered by either graph.

Immediate order:

1. Update references and evals so table/key/method/DAG claims are
   proof-carrying: `code_graph.py` for source facts, `db_graph.py` for runtime
   facts.
2. Keep `verify_spyglass_env.py` and `scrub_dj_config.py` stable and
   secret-safe; do not retrofit their JSON shape unless a real consumer needs
   a shared envelope.
3. Consider two likely next factual helpers after graph-tool evals:
   parameter inspection (`describe_params.py` / `trace_params.py`) and
   lightweight NWB inspection (`inspect_nwb_lite.py`). Parameters live in
   blobs and are interpreted in `make()` bodies, often by third-party
   packages. For blob params, the helper should inspect Spyglass's consuming
   source first, then inspect installed third-party signatures/source when
   values are passed through; web/docs are a fallback only when source and
   signatures do not explain semantics. NWB files are the file-backed evidence
   surface that the graph tools cannot see, including both raw NWBs before
   ingestion and AnalysisNWB files that store analysis results.
4. Consider `map_si_to_spyglass.py` when SpikeInterface API drift shows up in
   evals or user sessions; this is external-package compatibility, not a graph
   question.
5. Defer `visualize_schema_neighborhood.py`, `fetch_merge_row.py`,
   `cardinality_check.py`, and most row-debugging helpers until evals or real
   user sessions show that `db_graph.py`/`code_graph.py` are too awkward.

## Scoring criteria

Five things make a script LLM-grade. Weights descending:

1. **Closes a hallucination vector.** If the script makes an LLM's guess-from-training-data shape *structurally impossible* (wrong Params name → wrong API call → wrong FK chain), that's the biggest single unlock. Rare across the list.
2. **Provides structured evidence.** JSON / Mermaid / CSV output the LLM can cite *as evidence* rather than summarize from prose. Preferred over human-readable status lines.
3. **Ground truth over code generation.** Reading current DB / env state is strictly more valuable than producing boilerplate — the LLM can write code, it can't see state.
4. **Bounded runtime.** A hard timeout means the LLM can invoke the script in an autonomous loop without worrying about hangs. Scripts without `--timeout` on network calls score lower.
5. **Replaces multi-step reconstruction.** Each script call that subsumes N context-burning rounds (`.parents()` + `.children()` + `.describe()` + follow-up queries → one Mermaid graph) is worth N in saved tokens and reduced failure-to-converge risk.

## Tier 1 — Consolidate first (highest LLM leverage)

These are the shipped or near-term surfaces that should receive eval,
reference, and README attention before adding more scripts.

| Script | Status | Why it's Tier 1 |
| --- | --- | --- |
| `code_graph.py` | **shipped** | Source-only identity and dependency evidence: class existence, versioned source location, FK path, node kind, method ownership, and heuristic warnings. It is the main antidote to invented source claims. |
| `db_graph.py` | **shipped / PR-ready** | Runtime database evidence: actual table headings, row counts, merge IDs, set operations, custom-table imports, and source/runtime divergence. It is the main antidote to invented keys, attributes, and row-state claims. |
| `verify_spyglass_env.py` | **shipped** | Seven checks + JSON output + bounded timeout = LLM-ideal. Env assumptions become cite-able evidence instead of "trust me." |
| `scrub_dj_config.py` | **shipped** | Safe ground-truth read of DB config. Closes the password-leak-into-context hallucination-adjacent hazard. |
| **`describe_params.py` / `trace_params.py`** | likely next | Parameter rows are not just rows: values live in blobs, are consumed inside `make()`, and are often passed to third-party packages. This helper should produce an evidence packet tying params rows to consuming source locations, installed third-party signatures/source, and external call sites. It should not infer scientific meaning by itself; it should support a layered answer: verified DB/provenance effect, verified execution site, and verified-or-conditional model/scientific effect. |
| **`inspect_nwb_lite.py`** | candidate | Covers a different file-backed evidence surface: quickly summarize raw NWBs and AnalysisNWB files, including metadata, namespaces, processing modules, table shapes, dataset shapes, and object paths without loading array payloads into context. Useful before ingestion, when checking analysis outputs, and when comparing what the DB says to what is actually stored on disk. |
| **`map_si_to_spyglass.py`** | candidate | Still valuable because SpikeInterface API drift (`WaveformExtractor` ↔ `SortingAnalyzer`) is an external-package compatibility problem, not a source/runtime graph problem. Best implemented as a tiny script over a YAML catalog. |

**Next implementation recommendation:** do the consolidation/eval work first.
If a new script is justified after that, pick between parameter inspection,
NWB inspection, and SpikeInterface mapping based on the first failing eval/user
workflow.

## Tier 2 — Reconsider after graph-tool evals

These may still be useful, but they should not be built until evals show the
two graph tools are insufficient or too clumsy for the task.

| Script | Why it's Tier 2 |
| --- | --- |
| **`session_summary.py`** | "What's in this session?" may justify a convenience wrapper, but first test whether a small set of `db_graph.py` merge-master calls plus a reference template is enough. |
| **`pipeline_provenance.py`** | Reproducibility is central, but provenance spans source DAG, runtime rows, parameter blobs, files, and merge parts. It should likely be a higher-level composition over existing tools, not an early standalone script. |
| **`check_analysis_files.py`** | Thin wrapper over `AnalysisNwbfile.check_all_files()`. Ground truth about "is the data actually on disk?" — a question the LLM otherwise can't answer reliably without running fetch and catching FileNotFoundError. |
| **`trace_restriction.py`** | Thin wrapper over `RestrGraph` / `TableChain`. "What does this restriction affect across the DAG?" in structured form. |
| **`generate_selection_inserts.py`** | Retires the "reconstruct Selection-chain from tutorial cells" pattern that every new user runs into. Code-gen, not evidence, so slightly lower than pure-ground-truth scripts; but the per-pipeline chains are easy for LLMs to get off-by-one, so retiring that reconstruction is high value. |
| **`fetch_merge_row.py`** | Mostly superseded by merge-aware `db_graph.py find-instance`. Revisit only if evals show agents still misuse merge masters after the new routing prose. |

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
| `visualize_schema_neighborhood.py` | Mostly superseded by `code_graph.py path --up/--down` and `db_graph.py path`. Mermaid output is nice, but not enough to justify a duplicate graph surface without eval pressure. |
| `cardinality_check.py` | Teaching-oriented; `db_graph.py find-instance --count --fields KEY` covers the useful evidence. Keep the pattern in [feedback_loops.md](../../skills/spyglass/references/feedback_loops.md) rather than shipping a separate CLI. |

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

- **Next PRs:** consolidate `code_graph.py` / `db_graph.py` documentation,
  add evals that require proof-carrying answers, and keep existing scripts
  stable.
- **Next new script:** likely one of parameter inspection, lightweight NWB
  inspection, or SpikeInterface mapping. Let evals/user sessions choose among
  them.
- **Backlog grooming:** when a Tier 3 script's triggering scenario appears in a real user interaction, promote to next-up; otherwise hold.
- **New proposals:** score against the five criteria above before adding to the issue list. Tier 4-shaped scripts (admin / workflow) are still valid but should carry a clear "humans first, not LLMs" note so future contributors don't conflate utility with LLM leverage.
