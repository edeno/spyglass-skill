# skills/spyglass/scripts/

Small CLI utilities shipped alongside the skill. Split by audience:

## User-facing (called from SKILL.md / references)

Both are `Bash`-invoked by Claude when the skill is active (skill frontmatter grants `Bash` for this purpose). Users run them directly too; exit codes are CI-friendly.

- **`scrub_dj_config.py`** — reads a DataJoint config JSON and prints it with sensitive leaves masked (`password`, `secret`, `token`, `credential`, `access_key`, `api_key`, `auth`). Enforces SKILL.md Core Directive #6 ("never `Read`/`cat` a DataJoint config raw"). Stdlib-only.
- **`verify_spyglass_env.py`** — one-shot environment-readiness check: seven named checks covering DataJoint config, base-dir resolution + writability, subdir layout, DB connection (with a hard timeout), and version-pin drift. `--check NAME` to run one check; `--json` for structured output; `--strict` to promote warns to non-zero. Depends on `datajoint` (required) and `packaging` (optional — enables version-pin checks).
- **`code_graph.py`** — source-only code-graph traversal; four subcommands (`describe`, `path`, `find-method`, `info`) anchored at the code graph (vs. DB-resolved tools that need a live `import spyglass`). `info --json` dumps the full machine-readable contract (subcommand purposes, exit codes, enums, payload envelopes) so an agent can introspect without parsing prose. `describe X` prints tier, bases, structured PK/non-PK/FK with projected-rename dicts, methods inherited from `SpyglassMixin` / `_Merge`, and parts. `path --to A B` walks FK edges + master-part containment (BFS bridges containment in both directions). `path --up X` is a containment-ancestor walk: it follows FK edges plus master→parts (parts-as-upstream-contributors so `--up Master` surfaces upstream pipelines through its parts). `path --down X` is an FK-impact cascade ("what breaks if I modify X?"): it follows FK consumers, plus a part→master bridge so a part's downstream consumers via the master are reachable. The descendant walk threads a `skip_parts` flag through the bridge so a master reached via the bridge does NOT fan out to its sibling parts (modifying one merge contributor doesn't propagate to independent sibling pipelines). `find-method Y` lists every class that defines method `Y` at body level. Stdlib-only; no `import spyglass` or `import datajoint`. JSON output via `--json` (`schema_version: 1`); each node carries a stable `record_id` (`<file>:<line>:<qualname>`) and every payload stamps top-level `graph: "code"`, `authority: "source-only"`, `source_root`. A top-level `warnings` block lists same-qualname collisions resolved by same-package preference; pass `--fail-on-heuristic` (exit code 5) to refuse to guess. Exit codes: 0 ok, 2 usage, 3 user-input ambiguous, 4 not found, 5 heuristic required. Routing in [../references/feedback_loops.md](../references/feedback_loops.md) "Three graphs, three primitive families." Run with plain `python3 …` or, for an isolated Python env, `uv run python skills/spyglass/scripts/code_graph.py --src $SPYGLASS_SRC <subcommand> …` (no third-party deps so `uv run` is just env isolation, not dependency resolution).
- **`_index.py`** — shared module imported by `code_graph.py`'s three subcommands. Single AST scan of `$SPYGLASS_SRC/spyglass/` (~0.3s for 260 unique class names / 310 records, since multi-file classes like `BodyPart` produce one record per declaration). `lru_cache`-d per process; returns a frozen, tuple-backed `ClassIndex` (Mapping interface plus `parent_map` / `child_map` / `reverse_methods` / `resolve_base` / `by_qualname` methods). Not a CLI; running it directly executes a two-line smoke (class count + scan time) for sanity-checking the AST walk.

## Maintainer-only

- **`validate_skill.py`** — the drift validator. Runs on every commit via pre-commit and in CI against a live LorenFrankLab/spyglass checkout. See [../README.md](../README.md) and the top-level [CLAUDE.md](../../../CLAUDE.md).
- **`validate_all.sh`** — thin wrapper around `validate_skill.py`, the validator-regression fixtures, the `code_graph.py` tool-contract fixtures, and the runnable-example import harness. Takes `--baseline-warnings N`. Steps 1-3 are gated; step 4 (import harness) is informational.

## Lifecycle — "prototype here → upstream → retire"

User-facing scripts in this directory are explicitly prototypes. Each one names an upstream migration target in its module docstring (usually a candidate function or module in `spyglass.settings` / `spyglass.utils.*`). The intended lifecycle:

1. **Prototype here.** Ship with tests under [../tests/](../tests/) and reference-file routing.
2. **Propose upstream** via a draft PR to `LorenFrankLab/spyglass` once the script's behavior stabilizes.
3. **Retire locally** when upstream merges. Update reference files to route at `python -m spyglass.xxx.yyy` (or wherever upstream put it), remove the prototype script and its tests, and — if the script had structurally prevented a footgun (e.g. `scrub_dj_config` retires Core Directive #6 from manual compliance to automation) — revisit whether the corresponding SKILL.md directive can be tightened or removed.

| Script | Upstream candidate |
| --- | --- |
| `scrub_dj_config.py` | `spyglass.settings.scrub_config()` + `python -m spyglass.settings` entry point |
| `verify_spyglass_env.py` | `spyglass.utils.diagnostics` (supersedes Spyglass's current `scripts/validate.py` + this wrapper) |
| `code_graph.py` (+ `_index.py`) | `spyglass.utils.code_graph` (or `spyglass.cli.code_graph`); upstream merge would also fold in `KNOWN_CLASSES` auto-derivation |

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
