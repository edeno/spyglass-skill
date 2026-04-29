# Dispatch prompt templates for the Spyglass-skill eval sweep

Canonical prompt strings used to launch each subagent during a graded eval run.
Use these verbatim (with the `{...}` placeholders filled in) when orchestrating
a sweep so prompts stay identical across batches and across orchestrators.

These were extracted after the round-C 130-eval sweep, where the without_skill
prompt did not explicitly forbid reading the skill bundle, and 5 / 133 baseline
subagents reached for it via `ls` / `grep` / direct `Read`. The contamination
biased *against* the skill (baselines got partial skill-content access on those
evals), but a clean comparison is worth the extra prompt sentence. The
empirical observation lives in
the round-c [`SUMMARY.md` in spyglass-skill-workspace](https://github.com/edeno/spyglass-skill-workspace/blob/main/runs/round-c-2026-04-28/summary/SUMMARY.md)
under "Transcript-level caveats and mechanisms."

## Placeholders

- `{prompt}` — the raw user-facing prompt from `evals.json` for the eval being run.
- `{eval_dir}` — absolute path of the per-eval workspace directory for this dispatch. Per-sweep artifacts live in the [spyglass-skill-workspace](https://github.com/edeno/spyglass-skill-workspace) repo (cloned as a sibling of spyglass-skill), so a typical path is `/.../spyglass-skill-workspace/runs/<run-id>/iteration-N/eval-NNN-name`.
- `{condition}` — `with_skill` or `without_skill`.
- `{skill_dir}` — absolute path to the skill bundle, i.e. `/.../skills/spyglass`. Resolves at orchestration time so the templates stay portable across machines.
- `{spyglass_src}` — absolute path of the **pinned local Spyglass source checkout** (the path that `$SPYGLASS_SRC` points at for this sweep), e.g. `/.../spyglass/src/spyglass`. Always pin to a local checkout for reproducibility — see the "Reproducibility" section below.

## with_skill template

> You are running an eval. Behave as you would on a real user query. Do NOT ask
> for clarification — answer directly.
>
> First, **load the Spyglass skill** by reading `{skill_dir}/SKILL.md` in full.
> Follow the directives there: when it points you to a reference file in
> `{skill_dir}/references/<topic>.md`, read that file before answering.
> You may also read source files at `{spyglass_src}/...` if cited or needed.
>
> **Do not read** any files under `{eval_dir}/..` other than this run's own
> `{condition}/outputs/` directory. The eval set, grading artifacts, and
> summary documents (e.g. `evals.json`, `grading.json`, `benchmark.json`,
> `grader_summary.md`, `summary/`) describe how your answer will be judged
> and are not user-facing input. Reading them leaks the rubric.
>
> **User question:** {prompt}
>
> After you answer, **write your full response to** `{eval_dir}/with_skill/outputs/response.md`. The response should be the full answer to the user — don't summarize, don't add meta-commentary about being an eval. Just answer.

## without_skill template

> You are running an eval. Behave as you would on a real user query. Do NOT ask
> for clarification — answer directly. Use whatever you know about Spyglass /
> DataJoint / pynwb from training, plus the **pinned local Spyglass source
> checkout** at `{spyglass_src}` if you need to verify a code claim. Do not
> WebFetch GitHub Spyglass — the local checkout is the canonical source for
> this run; using a moving upstream target makes results unreproducible.
>
> **Important — do not read or list any files under `{skill_dir}`.** That
> directory is the skill bundle you are being measured *against*. Reading,
> grepping, or listing it (including its `references/`, `scripts/`, and
> `SKILL.md`) contaminates the without_skill condition. The Spyglass *source*
> code you may consult lives at `{spyglass_src}`; the *skill* you must not
> consult lives at `{skill_dir}`. They are different directories.
>
> **Also do not read** any files under `{eval_dir}/..` other than this run's
> own `{condition}/outputs/` directory. The eval set, grading artifacts, and
> summary documents (`evals.json`, `grading.json`, `benchmark.json`,
> `grader_summary.md`, `summary/`) describe how your answer will be judged
> and are not user-facing input. Reading them leaks the rubric.
>
> **User question:** {prompt}
>
> After you answer, **write your full response to** `{eval_dir}/without_skill/outputs/response.md`. The response should be the full answer to the user — don't summarize, don't add meta-commentary about being an eval. Just answer.

## Reproducibility

For a graded sweep to be reproducible across reruns:

- `{spyglass_src}` must be a **local pinned checkout** (e.g., a specific git tag, branch + commit, or release-versioned install path). Record the commit hash in the sweep's `BATCHES.md` or `findings.md` so the comparison surface is fixed. WebFetching GitHub Spyglass during a baseline run lets the baseline benefit from upstream changes that landed *after* the sweep started, breaking the comparison.
- `{skill_dir}` must be the same skill checkout being graded. If you're A/B-testing two skill versions, run two separate sweeps with each checkout pinned, not one sweep with mid-run skill edits.
- The without_skill prompt's prohibition list is path-relative; if the workspace layout changes (e.g., the skill moves out of `skills/spyglass/`), update the templates here.

## Why the bundle prohibition lives in the template, not in `CLAUDE.md`

The instruction is a property of *one specific dispatch in one specific
eval-running workflow* — graded baseline subagents. It is not a repo-wide
invariant, because legitimate maintainer work (validator runs, reference
edits, prose-utilization audits, this very SUMMARY.md analysis) reads the
skill bundle constantly. Putting the prohibition in `CLAUDE.md` would
mis-scope it. Keeping it in the dispatch template scopes it exactly to the
one context where contamination matters. `CLAUDE.md` carries a one-line
breadcrumb pointing at this file so future orchestrators can find the
templates.
