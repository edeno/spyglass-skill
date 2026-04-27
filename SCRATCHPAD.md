# SCRATCHPAD — db_graph.py implementation

Working notes for the `db-graph` branch. Not committed-as-policy; this file is
a single-developer scratch log so context survives session resets. Delete or
fold into the PR description when the work lands.

## Plan + branch

- Plan: [docs/plans/db-graph-impl-plan.md](docs/plans/db-graph-impl-plan.md), committed at `5228d20`.
- Branch: `db-graph`, off `master`.
- Predecessor decision record: [docs/plans/db-graph-decision-record.md](docs/plans/db-graph-decision-record.md).

## Pre-implementation decisions (locked in 2026-04-26)

### D1. `_index.resolve_src_root` backport — out of MVP

Keep the installed-package fallback **local to `db_graph.py`**. Backporting
to `_index.resolve_src_root` would change `code_graph.py` behavior + its
advertised `info --json` contract, which is a separate decision and a
separate PR.

Document the divergence in two places:

- `db_graph.py info --json.comparison`: include a delta entry like
  `"src_root_resolution": "db_graph.py adds installed-package fallback; code_graph.py does not"`.
- `skills/spyglass/scripts/README.md`: lifecycle row note.

Follow-up PR (after MVP): consider folding the fallback into
`_index.resolve_src_root` and updating `code_graph.py info` accordingly.

### D2. Pre-commit hook scope — extend now

Current regex in `.pre-commit-config.yaml` (line 34):

```
^skills/spyglass/(SKILL\.md|references/.*\.md|scripts/(validate_skill|_index|code_graph)\.py|tests/(test_validator_regressions|test_code_graph)\.py|evals/evals\.json)$
```

Add to the alternation:

- `scripts/db_graph.py`
- `tests/test_db_graph.py`
- `tests/fakes.py`

This only matters if `validate_all.sh` actually runs the new DB-graph
fixtures. Add a gated step:

```
[4/5] db_graph.py tool-contract fixtures
```

slotted **before** the existing `[4/4] runnable import harness` (which
demotes to `[5/5]` and stays informational). The new step is gated like
`[3/4] code_graph.py tool-contract fixtures` — its return code feeds the
overall exit.

### D3. `--python-env` for tests/test_db_graph.py

`validate_all.sh` already supports `--python-env` ([validate_all.sh:7](skills/spyglass/scripts/validate_all.sh#L7)).
`test_code_graph.py` hardcodes `python3` ([test_code_graph.py:33](skills/spyglass/tests/test_code_graph.py#L33)),
which is fine because that script is stdlib-only.

`test_db_graph.py` cannot copy that pattern — db_graph.py imports DataJoint,
which is not in the system `python3`. Implementation:

- `argparse` flag `--python-env PATH`, default `sys.executable`.
- Subprocess CLI invocations use that interpreter:
  `subprocess.run([args.python_env, str(DB_GRAPH), ...])`.

**Critical companion rule for `db_graph.py` itself:** delay DataJoint and
Spyglass imports until after argparse + class resolution. Specifically:

- `info --json` must run on a DataJoint-less interpreter (plan, "Efficiency
  strategy", bullet 2). It already says this — pin it in code by importing
  DataJoint inside `cmd_find_instance`, not at module top.
- Unit fixtures that monkeypatch DataJoint can run on the system python
  by ensuring `db_graph.py` only triggers the import on the `find-instance`
  path. `info`, ambiguous, not-found, unsafe paths must not import DataJoint.

If `test_db_graph.py` ever does `import db_graph` directly (rather than
spawning subprocesses), the same delayed-import rule keeps system-python
fixtures green. Default to subprocess invocation (mirrors `test_code_graph.py`)
so the import question is moot.

## Environment fingerprint

| Thing | Value |
| --- | --- |
| Working interpreter | `/Users/edeno/miniconda3/envs/spyglass/bin/python` (3.12.12) |
| `datajoint.__version__` | `0.14.6` |
| `datajoint.user_tables.UserTable` | `/Users/edeno/miniconda3/envs/spyglass/lib/python3.12/site-packages/datajoint/user_tables.py` |
| `spyglass.__version__` | `0.5.5a2.dev75+g57ed4eef5` |
| `spyglass.__file__` | `/Users/edeno/Documents/GitHub/spyglass/src/spyglass/__init__.py` (editable install) |
| Installed-fallback `src_root` | `/Users/edeno/Documents/GitHub/spyglass/src` (contains `spyglass/` ✓) |
| `$SPYGLASS_SRC` | unset → installed-fallback path is exercised |
| PyPI distribution name | `spyglass-neuro` (per `spyglass/pyproject.toml`) |

## Existing code I'll mirror or call into

| Symbol | Location | Notes |
| --- | --- | --- |
| `SCHEMA_VERSION = _index.SCHEMA_VERSION` | code_graph.py:117 | Reuse value `1`. |
| `EXIT_OK / EXIT_USAGE / EXIT_AMBIGUOUS / EXIT_NOT_FOUND` | code_graph.py:118-128 | Same semantics 0/2/3/4. |
| `EXIT_HEURISTIC = 5` (code_graph) | code_graph.py:128 | **Diverges** in db_graph: `5` = DB error. Document in `info --json.comparison`. |
| `GRAPH_KIND="code"`, `AUTHORITY="source-only"` | code_graph.py:133-134 | db_graph: `GRAPH_KIND="db"`, `AUTHORITY="runtime-db"`. |
| `_provenance_fields(source_root)` | code_graph.py:237 | Pattern; db version also stamps `db: {...}`. |
| `_stamp_payload(payload, source_root, log)` | code_graph.py:246 | Pattern; db version threads `timings_ms` + `db` envelope. |
| `cmd_info` | code_graph.py:1834 | Direct template for `db_graph.py info --json`. |
| `_resolve_class(name, idx, file_hint)` | code_graph.py:396 | Returns `(record, error_kind, candidates)`. Reuse as-is. |
| `_index.scan(src_root) -> ClassIndex` | _index.py:867 | `lru_cache`'d. NOT `ClassIndex.from_root`. |
| `_index.resolve_src_root(arg_src)` | _index.py:484 | Wrap with installed-package fallback (do not catch its `SystemExit`). |
| `ClassRecord` | _index.py:243 | Dataclass; `.qualname`, `.file`, `.line`, `.bases`. Module path derives from `.file`. |

## New constants for db_graph.py

```python
SCHEMA_VERSION = _index.SCHEMA_VERSION  # = 1, shared with code_graph.py
GRAPH_KIND = "db"
AUTHORITY = "runtime-db"

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_AMBIGUOUS = 3
EXIT_NOT_FOUND = 4
EXIT_DB = 5         # connection / auth / schema / dj-import failure
EXIT_UNSAFE = 6     # refused write/raw-SQL request
EXIT_EMPTY = 7      # --fail-on-empty + count == 0 (opt-in)

LIMIT_DEFAULT = 100
LIMIT_HARD_MAX = 1000
FALLBACK_KEY_BOUND = LIMIT_DEFAULT + 1  # `--limit + 1` per plan
```

## Test infrastructure conventions

- **Subprocess-driven, no pytest discovery.** Each test file is a CLI:
  `python skills/spyglass/tests/test_X.py --spyglass-src PATH [--python-env PATH]`.
- Fixtures = functions returning `bool`. `main()` runs all and exits 0/1.
- No `conftest.py`. Pytest is available in the spyglass env but tests don't
  depend on it.
- Synthetic Spyglass trees live under `tempfile.TemporaryDirectory()`;
  `_write_fakepipe` helper writes files relative to `tmp/spyglass/...`.

For `test_db_graph.py`:

- Add `--python-env PATH` (default `sys.executable`).
- `_run_db_graph(args, python_env)` mirrors `_run_code_graph`.
- `tests/fakes.py` provides `FakeRelation` + `FakeHeading` etc. — used by
  fixtures that need DataJoint behavior without a live DB.
- For the `RestrGraph` / `TableChain` no-instantiation fixture (#18),
  the cleanest approach is to import `db_graph` in-process *with*
  `monkeypatch.setattr` on the `spyglass.utils.dj_graph` symbols. That
  requires DataJoint to be importable on the test python — i.e., run that
  fixture under `--python-env` only, gate it with a "spyglass-importable"
  check, skip cleanly otherwise. **Alternative:** pass via subprocess but
  inject a `sys.path` shim that pre-imports the patches. Decide during
  implementation; in-process probably wins for clarity.

## Validation pipeline updates

`validate_all.sh` step list after change:

```
[1/5] Main validator
[2/5] Validator-regression fixtures
[3/5] code_graph.py tool-contract fixtures
[4/5] db_graph.py tool-contract fixtures   <-- new, gated
[5/5] Runnable import harness               (informational, was 4/4)
```

The `[4/5]` step needs `--python-env` because db_graph imports DataJoint.
Pass `${PY}` (which already comes from `--python-env` or defaults to
`python3`) through.

`.pre-commit-config.yaml` regex update:

```
^skills/spyglass/(
    SKILL\.md
  | references/.*\.md
  | scripts/(validate_skill|_index|code_graph|db_graph)\.py
  | tests/(test_validator_regressions|test_code_graph|test_db_graph|fakes)\.py
  | evals/evals\.json
)$
```

(Single-line in the actual YAML; broken across lines here for readability.)

## Eval coverage map

| Eval # | Shape | Plan batch |
| --- | --- | --- |
| 9 | Session row | C |
| 10 | Selected fields | C |
| 11 | Field list | C |
| 12 | Count via `len(restricted)` | C |
| 13 | Merge-key resolve before df fetch (df out of scope) | C (key-resolve only) |
| 14 | merge_id for Trodes part | D |
| 15 | merge_id for LFP part with FK constraint | D |
| 16 | merge_id for DecodingOutput via params | D |
| 17 | Sessions in both A & B (intersect) | E |
| 18 | TrodesPosV1 - DLCPosV1 (antijoin; bare `-` raises) | E |
| 19 | per-session distinct electrode-group count | E (`--group-by-table Session`) |
| 28 | brain regions for sorting (join via shared attrs) | E |
| 29 | brain region for one electrode (join Electrode * BrainRegion) | E |
| 50 | DecodingOutput silent no-op (the canonical footgun) | D refusal/route |

## Lazy-import discipline

`db_graph.py` MUST keep DataJoint and Spyglass imports lazy:

```python
# top of db_graph.py
import argparse, json, sys, time
from pathlib import Path
import _index  # stdlib-equivalent; no datajoint, no spyglass
# NO: import datajoint
# NO: import spyglass

def cmd_info(args):
    # No DataJoint / Spyglass import here. Static payload only.
    ...

def cmd_find_instance(args):
    # Import inside the function so info, ambiguous, not-found stay light.
    import datajoint as dj
    from datajoint.user_tables import UserTable
    ...
```

Why: `info --json` must work when DataJoint isn't installed (plan,
"Efficiency strategy" bullet 2). Also: subprocess startup cost on the
hot path is a known risk (plan, "Risks" — `timings_ms.connect` records
this).

## Open questions to resolve during coding (not before)

- Exact module path for `RestrGraph` / `TableChain` in current Spyglass
  (`spyglass.utils.dj_graph`?). Verify at fixture-#18 implementation time.
- Whether `FieldSpec` from `_index.py` ([_index.py:192](skills/spyglass/scripts/_index.py#L192)) overlaps with what we serialize from `heading.attributes` —
  it shouldn't, because `_index` is source-only and `db_graph` reads runtime
  heading. Keep them separate even if shapes look similar.
- Whether to expose `--no-color` / human output. Default to `--json`-or-bust
  for MVP; revisit if hand-debugging is awkward.

## Lint / style

- ruff target-version is `py39`. Avoid 3.10+ syntax (no `match`, no `X | Y`
  outside type hints with `from __future__ import annotations`).
- ruff currently passes on `master`. New code must keep that green.
- `pre-commit run --all-files` is the local check.
