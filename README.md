# spyglass-skill

[![Validate](https://github.com/edeno/spyglass-skill/actions/workflows/validate.yml/badge.svg)](https://github.com/edeno/spyglass-skill/actions/workflows/validate.yml)

A Claude Code plugin providing the `spyglass` skill — guidance for the
[LorenFrankLab Spyglass](https://github.com/LorenFrankLab/spyglass)
neurophysiology framework (DataJoint + NWB).

## What it does

Activates automatically when you're working on Spyglass code:
imports from `spyglass.*`, `SpyglassMixin` subclasses, V1 pipeline
classes (`LFPV1`, `SpikeSorting`, `RippleTimesV1`, etc.), or
DLC / DANDI / Kachery within a Spyglass context. The skill provides:

- **Core directives** that prevent the most common failure modes
  (accidental deletes, hallucinated method/kwarg names, unsafe
  `fetch1()` calls, cautious_delete bypasses).
- **A routing table** across 26 topic references — setup, ingestion,
  pipelines, debugging — so the agent pulls the relevant deep-dive
  on demand rather than pre-loading everything.
- **Validator-gated quality** (see `skills/spyglass/scripts/`): 20
  automated checks against a live Spyglass checkout, 46 regression
  fixtures, and an import-time harness. Runs on every edit; prose
  that drifts from the codebase fails CI before it reaches users.

## Usage

Once installed, the skill engages on questions like:

```text
"How do I populate LFPV1 for nwb_file X?"
"My populate() is failing with fetch1 cardinality errors in SpikeSorting."
"Write a make() that reads ripple bands from LFPBandV1."
"What's the right way to delete a subject's decoding results?"
"Set up Spyglass against my lab's MySQL server."
```

For vague questions it classifies your stage (setup / ingestion /
pipeline usage / pipeline authoring / debugging) and loads the
matching reference. For specific topics it routes directly via the
table in [`SKILL.md`](skills/spyglass/SKILL.md).

## Install

The skill uses the `SKILL.md` format, which Claude Code, OpenAI
Codex CLI, and Gemini CLI all read natively (as of early 2026). Only
the install location differs per tool.

### Claude Code

```text
/plugin install https://github.com/edeno/spyglass-skill
```

Or manually:

```bash
git clone https://github.com/edeno/spyglass-skill.git /tmp/spyglass-skill
cp -r /tmp/spyglass-skill/skills/spyglass ~/.claude/skills/spyglass
```

### OpenAI Codex CLI

```bash
git clone https://github.com/edeno/spyglass-skill.git /tmp/spyglass-skill
cp -r /tmp/spyglass-skill/skills/spyglass ~/.codex/skills/spyglass
```

Or scope the skill to a single project by copying into
`.agents/skills/spyglass/` at that project's root — Codex scans up
from the working directory.

### Gemini CLI

Consult the
[Gemini CLI skills docs](https://geminicli.com/docs/cli/skills/)
for the current install path; the `skills/spyglass/` directory is
format-compatible.

### After install

Restart the agent (or start a new session). The skill activates
automatically when the task involves Spyglass imports, `SpyglassMixin`,
V1 pipeline classes, or related topics — see the
[frontmatter description](skills/spyglass/SKILL.md) for the full
activation rules.

## What's in here

```text
.claude-plugin/plugin.json        # Claude Code plugin manifest
skills/spyglass/                  # the skill itself (SKILL.md + references)
  SKILL.md                        # entry point, loaded into context on match
  references/                     # progressive-disclosure topic files
  scripts/                        # validator + convenience runner
  tests/                          # regression fixtures + import harness
  evals/                          # behavioral eval cases
  README.md                       # maintainer notes
```

## Reviewing the skill

If you're reviewing this for correctness rather than using it, start at
[`skills/spyglass/SKILL.md`](skills/spyglass/SKILL.md) for the
user-facing guidance and [`skills/spyglass/references/`](skills/spyglass/references/)
for the detailed topic references. The validator in
[`skills/spyglass/scripts/validate_skill.py`](skills/spyglass/scripts/validate_skill.py)
gates skill quality against a live Spyglass checkout — see the skill's
own README for how to run it.

### Pointing the validator at a Spyglass checkout

The validator parses the Spyglass source tree via AST — no database or
Spyglass install needed, but it does need the source files on disk.
Path resolution, in order:

1. **`--spyglass-src PATH`** CLI flag — wins over everything.
2. **`$SPYGLASS_SRC` env var** — the recommended way for personal setups.
   Add to your shell rc:

   ```bash
   export SPYGLASS_SRC="$HOME/Documents/GitHub/spyglass/src"
   ```

3. **Sibling-clone fallback** — if a `spyglass/` checkout sits next to
   this repo (e.g. `~/Documents/GitHub/spyglass/` alongside
   `~/Documents/GitHub/spyglass-skill/`), the script finds it at
   `../spyglass/src` with zero config. Useful for both local dev and CI.
4. **`scripts/config.local.sh`** — gitignored, source before running if you
   need per-invocation overrides. Example:

   ```bash
   # scripts/config.local.sh
   export SPYGLASS_SRC="/some/other/path/to/spyglass/src"
   ```

   Then: `source skills/spyglass/scripts/config.local.sh && ./skills/spyglass/scripts/validate_all.sh`

Never commit a personal path. `.gitignore` already excludes
`.env.local` and `scripts/config.local.sh` for this reason.

Issues and PRs welcome at [github.com/edeno/spyglass-skill](https://github.com/edeno/spyglass-skill).

## Developing

Setup for contributors changing the skill itself (not just consumers of
the installed plugin):

```bash
git clone https://github.com/edeno/spyglass-skill.git
cd spyglass-skill

# Clone LorenFrankLab/spyglass as a sibling so the validator picks it up
# with zero config. (Alternative: set $SPYGLASS_SRC in your shell rc.)
git clone https://github.com/LorenFrankLab/spyglass.git ../spyglass

# Wire up the pre-commit hooks (one-time per clone)
uvx pre-commit install   # or: pip install pre-commit && pre-commit install

# Run the full local check
./skills/spyglass/scripts/validate_all.sh --baseline-warnings 3
ruff check .
```

### Tooling

- **ruff 0.14.6** — Python linter for the validator + tests + eval scripts.
  Config: [ruff.toml](ruff.toml). Runs on commit (via pre-commit) and in CI.
- **pre-commit** — runs `ruff check --fix` plus the skill validator (scoped
  to content files, skipped gracefully when no Spyglass checkout is available).
  Config: [.pre-commit-config.yaml](.pre-commit-config.yaml). Bypass with
  `git commit --no-verify` in emergencies; CI still gates.
- **GitHub Actions** — validates the skill against live LorenFrankLab/spyglass
  master on push, PR, and weekly on Mondays. Workflow:
  [.github/workflows/validate.yml](.github/workflows/validate.yml).
  Scheduled-run failures auto-open a drift issue (template at
  [.github/drift-issue-template.md](.github/drift-issue-template.md)).
- **Dependabot** — monthly PRs to update GitHub Actions pins. Config:
  [.github/dependabot.yml](.github/dependabot.yml). `ruff` itself is pinned
  in `.pre-commit-config.yaml` and bumped via `pre-commit autoupdate`
  (remember to bump the matching pin in the CI workflow at the same time).

See [CLAUDE.md](CLAUDE.md) for the full maintainer workflow — size budgets,
the regression-fixture-first pattern, commit style, and anti-patterns to
avoid when editing SKILL.md or references.

## License

MIT — see [LICENSE](LICENSE).
