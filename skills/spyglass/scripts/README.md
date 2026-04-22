# skills/spyglass/scripts/

Small CLI utilities shipped alongside the skill. Split by audience:

## User-facing (called from SKILL.md / references)

Both are `Bash`-invoked by Claude when the skill is active (skill frontmatter grants `Bash` for this purpose). Users run them directly too; exit codes are CI-friendly.

- **`scrub_dj_config.py`** — reads a DataJoint config JSON and prints it with sensitive leaves masked (`password`, `secret`, `token`, `credential`, `access_key`, `api_key`, `auth`). Enforces SKILL.md Core Directive #6 ("never `Read`/`cat` a DataJoint config raw"). Stdlib-only.
- **`verify_spyglass_env.py`** — one-shot environment-readiness check: seven named checks covering DataJoint config, base-dir resolution + writability, subdir layout, DB connection (with a hard timeout), and version-pin drift. `--check NAME` to run one check; `--json` for structured output; `--strict` to promote warns to non-zero. Depends on `datajoint` (required) and `packaging` (optional — enables version-pin checks).

## Maintainer-only

- **`validate_skill.py`** — the drift validator. Runs on every commit via pre-commit and in CI against a live LorenFrankLab/spyglass checkout. See [../README.md](../README.md) and the top-level [CLAUDE.md](../../../CLAUDE.md).
- **`validate_all.sh`** — thin wrapper around `validate_skill.py` plus the regression suite. Takes `--baseline-warnings N`.

## Lifecycle — "prototype here → upstream → retire"

User-facing scripts in this directory are explicitly prototypes. Each one names an upstream migration target in its module docstring (usually a candidate function or module in `spyglass.settings` / `spyglass.utils.*`). The intended lifecycle:

1. **Prototype here.** Ship with tests under [../tests/](../tests/) and reference-file routing.
2. **Propose upstream** via a draft PR to `LorenFrankLab/spyglass` once the script's behavior stabilizes.
3. **Retire locally** when upstream merges. Update reference files to route at `python -m spyglass.xxx.yyy` (or wherever upstream put it), remove the prototype script and its tests, and — if the script had structurally prevented a footgun (e.g. `scrub_dj_config` retires Core Directive #6 from manual compliance to automation) — revisit whether the corresponding SKILL.md directive can be tightened or removed.

| Script | Upstream candidate |
| --- | --- |
| `scrub_dj_config.py` | `spyglass.settings.scrub_config()` + `python -m spyglass.settings` entry point |
| `verify_spyglass_env.py` | `spyglass.utils.diagnostics` (supersedes Spyglass's current `scripts/validate.py` + this wrapper) |

Full design context for each prototype lives in [docs/plans/env-scripts-impl-plan.md](../../../docs/plans/env-scripts-impl-plan.md) (gitignored — it's a rolling design doc, not repo content).

## Adding a new user-facing script — checklist

1. Put it here. Top-line docstring must include a "Lifecycle" paragraph naming its upstream target.
2. Add tests under [../tests/](../tests/). Prefer stdlib + `pytest` monkeypatching over live fixtures.
3. Wire it into the skill:
   - If it addresses a Core Directive, update SKILL.md (watch the 1200-word hard cap).
   - Cite it from every reference where a user landing there would benefit — not just the primary one. Discoverability review has found gaps twice already; audit explicitly.
   - If behavior overlaps with an existing eval, update the eval's expected output.
4. Update this README: add it to the "User-facing" list and the lifecycle table.
5. Run `./validate_all.sh --baseline-warnings 3` and `ruff check .` before committing.
