#!/usr/bin/env python3
"""Tool-contract tests for ``db_graph.py``.

Pins the JSON output schema (``schema_version: 1``) for ``db_graph.py``'s
subcommands. Mirrors ``test_code_graph.py`` in shape (subprocess-driven,
fixtures return ``bool``, ``main()`` runs them and exits 0/1) but adds
``--python-env`` because db_graph imports DataJoint and Spyglass on the
``find-instance`` path. ``info`` deliberately avoids those imports so it
can be tested on a Python without DataJoint.

Run::

    python skills/spyglass/tests/test_db_graph.py [--spyglass-src PATH] \
        [--python-env PATH]

Both flags are optional. ``--spyglass-src`` is parity with sibling test
files; Batch A fixtures do not need a real Spyglass tree because they
exercise ``info`` and the ``find-instance`` Batch-A stub. ``--python-env``
defaults to ``sys.executable``; pass a Python with DataJoint installed
when fixtures that exercise the real find-instance code path land in
Batch C.

Batch A scope
-------------

The fixtures here pin the **contract** (envelope, exit codes, info
payload, lazy-import discipline) so Batch C cannot silently drift it
when the real find-instance implementation lands. Each fixture has a
descriptive name keyed to a plan acceptance bullet.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
DB_GRAPH = SCRIPT_DIR / "db_graph.py"


def _python_can_import(python_env: str, module: str) -> bool:
    """Return True if ``module`` imports cleanly under ``python_env``.

    Cached per (python_env, module) tuple via the ``_capabilities`` dict
    on the calling args namespace; the runner pre-computes once at
    startup so per-fixture invocations are free.
    """
    proc = subprocess.run(
        [python_env, "-c", f"import {module}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode == 0


def _run_db_graph(
    args: list[str],
    *,
    python_env: str,
    extra_env: dict[str, str] | None = None,
) -> tuple[int, str, str]:
    """Run ``db_graph.py`` with ``args``, return ``(returncode, stdout, stderr)``.

    ``python_env`` is the interpreter to invoke. Tests that pin the lazy-
    import discipline pass the system python (which lacks DataJoint) to
    prove ``info`` does not import DataJoint; tests that exercise the
    real find-instance code path pass a Spyglass-equipped python.

    ``extra_env`` is merged into the subprocess's environment. Used by
    the lazy-import fixture to point ``PYTHONPATH`` at a sandbox that
    raises on ``import datajoint``.
    """
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    proc = subprocess.run(
        [python_env, str(DB_GRAPH), *args],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _parse_json_or_fail(stdout: str, label: str) -> dict | None:
    """Parse JSON or print a structured fail line and return None."""
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as e:
        print(f"  [FAIL] {label}: stdout is not valid JSON: {e}")
        print(f"         stdout: {stdout[:400]!r}")
        return None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def fixture_info_emits_valid_json(args: argparse.Namespace) -> bool:
    """``info --json`` returns a parseable JSON object on exit 0."""
    rc, out, err = _run_db_graph(["info", "--json"], python_env=args.python_env)
    if rc != 0:
        print(f"  [FAIL] info --json exited {rc}; stderr: {err!r}")
        return False
    payload = _parse_json_or_fail(out, "info --json")
    if payload is None:
        return False
    if payload.get("schema_version") != 1:
        print(f"  [FAIL] schema_version != 1: {payload.get('schema_version')!r}")
        return False
    if payload.get("kind") != "info":
        print(f"  [FAIL] kind != 'info': {payload.get('kind')!r}")
        return False
    if payload.get("graph") != "db":
        print(f"  [FAIL] graph != 'db': {payload.get('graph')!r}")
        return False
    if payload.get("authority") != "runtime-db":
        print(f"  [FAIL] authority != 'runtime-db': {payload.get('authority')!r}")
        return False
    if payload.get("source_root") is not None:
        print(
            "  [FAIL] info source_root must be null (info is static): "
            f"{payload.get('source_root')!r}"
        )
        return False
    print("  [ok] info --json: schema_version=1, db-graph identity, source_root=null")
    return True


def fixture_info_field_order_is_stable(args: argparse.Namespace) -> bool:
    """info payload top-level keys appear in the documented stable order.

    LLM consumers benefit from consistent field placement. The order
    pinned here matches ``PAYLOAD_ENVELOPES['info']`` in ``db_graph.py``.
    """
    expected = [
        "schema_version",
        "kind",
        "graph",
        "authority",
        "source_root",
        "subcommands",
        "exit_codes",
        "payload_envelopes",
        "result_shapes",
        "timings_keys",
        "security_profile",
        "null_policy",
        "comparison",
    ]
    rc, out, err = _run_db_graph(["info", "--json"], python_env=args.python_env)
    if rc != 0:
        print(f"  [FAIL] info --json exited {rc}; stderr: {err!r}")
        return False
    # `object_pairs_hook=list` preserves the on-the-wire key order so we
    # can verify it instead of trusting Python's dict insertion order
    # (which is preserved, but a test that asserts that explicitly is
    # the contract guarantee).
    pairs = json.loads(out, object_pairs_hook=list)
    if not isinstance(pairs, list):
        print("  [FAIL] info payload is not a JSON object")
        return False
    got = [k for k, _ in pairs]
    if got != expected:
        print("  [FAIL] field order mismatch")
        print(f"         expected: {expected}")
        print(f"         got     : {got}")
        return False
    print("  [ok] info --json: top-level keys appear in documented stable order")
    return True


def fixture_info_advertises_required_contract_fields(
    args: argparse.Namespace,
) -> bool:
    """info exposes every field promised by the Batch A acceptance bullet.

    Plan acceptance: ``info --json`` exposes ``subcommands``, ``exit_codes``,
    ``payload_envelopes``, ``result_shapes``, ``security_profile``,
    ``null_policy``, and ``comparison`` vs ``code_graph.py``.
    """
    rc, out, err = _run_db_graph(["info", "--json"], python_env=args.python_env)
    if rc != 0:
        print(f"  [FAIL] info --json exited {rc}; stderr: {err!r}")
        return False
    payload = _parse_json_or_fail(out, "info --json")
    if payload is None:
        return False
    required = {
        "subcommands": dict,
        "exit_codes": dict,
        "payload_envelopes": dict,
        "result_shapes": list,
        "timings_keys": list,
        "security_profile": dict,
        "null_policy": dict,
        "comparison": dict,
    }
    for name, expected_type in required.items():
        if name not in payload:
            print(f"  [FAIL] missing field {name!r}")
            return False
        if not isinstance(payload[name], expected_type):
            print(
                f"  [FAIL] {name!r} expected {expected_type.__name__}, "
                f"got {type(payload[name]).__name__}"
            )
            return False
    # Inside subcommands, both planned subcommand entries must be present.
    subcommands = payload["subcommands"]
    for sc in ("info", "find-instance"):
        if sc not in subcommands:
            print(f"  [FAIL] subcommands missing {sc!r}")
            return False
        for inner in ("purpose", "modes", "hints"):
            if inner not in subcommands[sc]:
                print(f"  [FAIL] subcommands[{sc!r}] missing {inner!r}")
                return False
    # Exit codes the plan promises must all be documented.
    exit_codes = payload["exit_codes"]
    for code in ("0", "2", "3", "4", "5", "6", "7"):
        if code not in exit_codes:
            print(f"  [FAIL] exit_codes missing {code!r}")
            return False
    # Comparison block must cite the sibling and at least the four
    # known-distinct fields.
    comparison = payload["comparison"]
    if comparison.get("sibling_tool") != "code_graph.py":
        print(
            f"  [FAIL] comparison.sibling_tool != 'code_graph.py': "
            f"{comparison.get('sibling_tool')!r}"
        )
        return False
    diffs = comparison.get("differences", {})
    for diff_key in ("graph", "authority", "exit_code_5", "src_root_resolution"):
        if diff_key not in diffs:
            print(f"  [FAIL] comparison.differences missing {diff_key!r}")
            return False
    print(
        "  [ok] info --json: subcommands, exit_codes, payload_envelopes, "
        "result_shapes, security_profile, null_policy, comparison all present"
    )
    return True


def fixture_info_payload_envelopes_pin_field_order(
    args: argparse.Namespace,
) -> bool:
    """payload_envelopes lists each shape's top-level fields in stable order.

    Batch C will lean on these envelopes to construct payloads; pinning
    them here ensures the implementer cannot silently reorder fields
    without the test catching it.
    """
    rc, out, err = _run_db_graph(["info", "--json"], python_env=args.python_env)
    if rc != 0:
        print(f"  [FAIL] info --json exited {rc}; stderr: {err!r}")
        return False
    payload = _parse_json_or_fail(out, "info --json")
    if payload is None:
        return False
    envelopes = payload["payload_envelopes"]
    # Spot-check: find-instance envelope pins the canonical row-shape order.
    fi = envelopes.get("find-instance", [])
    expected_fi_prefix = [
        "schema_version",
        "kind",
        "graph",
        "authority",
        "source_root",
        "db",
        "query",
        "count",
        "limit",
        "truncated",
        "incomplete",
        "timings_ms",
        "rows",
    ]
    if fi != expected_fi_prefix:
        print("  [FAIL] find-instance envelope drifted")
        print(f"         expected: {expected_fi_prefix}")
        print(f"         got     : {fi}")
        return False
    every = envelopes.get("every_payload", [])
    if every[:5] != ["schema_version", "kind", "graph", "authority", "source_root"]:
        print(f"  [FAIL] every_payload prefix drifted: {every!r}")
        return False
    print("  [ok] info --json: payload_envelopes pin find-instance + every_payload order")
    return True


def fixture_info_runs_without_datajoint(args: argparse.Namespace) -> bool:
    """``info --json`` works on a Python without DataJoint installed.

    Pins the lazy-import discipline. Verifying this would be circular
    if we used ``--python-env spyglass`` (DataJoint is installed there),
    so this fixture sandboxes the subprocess: it points ``PYTHONPATH`` at
    a temp directory containing a ``datajoint.py`` that raises
    ``ImportError`` on import. If ``info`` were eagerly importing
    DataJoint, the subprocess would fail; the fact that it succeeds is
    the proof.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        # A poison module that raises on import. PYTHONPATH puts it
        # ahead of site-packages so any `import datajoint` finds this
        # one first.
        (tmp / "datajoint.py").write_text(
            "raise ImportError(\n"
            "    'Lazy-import test poison: db_graph.py imported "
            "DataJoint when it should not have'\n"
            ")\n"
        )
        # Same for spyglass — class resolution can pull it in, but info
        # must not.
        spyglass_pkg = tmp / "spyglass"
        spyglass_pkg.mkdir()
        (spyglass_pkg / "__init__.py").write_text(
            "raise ImportError(\n"
            "    'Lazy-import test poison: db_graph.py imported "
            "Spyglass when it should not have'\n"
            ")\n"
        )
        rc, out, err = _run_db_graph(
            ["info", "--json"],
            python_env=args.python_env,
            extra_env={"PYTHONPATH": str(tmp)},
        )
    if rc != 0:
        print(
            f"  [FAIL] info --json exited {rc} with poisoned datajoint/spyglass; "
            "implies eager import"
        )
        print(f"         stderr: {err!r}")
        return False
    payload = _parse_json_or_fail(out, "info --json (poisoned env)")
    if payload is None:
        return False
    if payload.get("kind") != "info":
        print(f"  [FAIL] payload kind != 'info': {payload.get('kind')!r}")
        return False
    print(
        "  [ok] info --json: succeeded with poisoned datajoint+spyglass — "
        "lazy-import discipline holds"
    )
    return True


def _poisoned_datajoint_path() -> tempfile.TemporaryDirectory:
    """Return a temp dir whose top-level shadows ``datajoint`` with an ImportError.

    Used to force the DataJoint-import-failure path inside
    ``_is_datajoint_user_table`` deterministically, regardless of whether
    ``--python-env`` has DataJoint installed. Caller uses the returned
    object as a context manager so the dir is cleaned up. Spyglass is
    intentionally NOT poisoned: the lazy-import-discipline test poisons
    both, but the find-instance datajoint-missing test only needs
    DataJoint to fail.
    """
    tmp = tempfile.TemporaryDirectory()
    path = Path(tmp.name)
    (path / "datajoint.py").write_text(
        "raise ImportError(\n"
        "    'Test poison: db_graph.py reached datajoint import on a path "
        "that should not have'\n"
        ")\n"
    )
    return tmp


def fixture_find_instance_emits_db_error_when_datajoint_missing(
    args: argparse.Namespace,
) -> bool:
    """``find-instance`` returns ``kind: "db_error"`` / exit 5 when DataJoint is missing.

    Plan: exit 5 covers DB/session errors, with ``error.kind`` discriminating
    among ``connection`` / ``auth`` / ``schema`` / ``datajoint_import``.
    Uses ``--class json:JSONDecoder`` so the resolver imports a stdlib
    module (succeeds regardless of Spyglass / DataJoint state), then
    enters the UserTable predicate which trips on the poisoned
    ``datajoint`` import. This isolates the datajoint-missing failure
    mode without relying on the spyglass package state.
    """
    with _poisoned_datajoint_path() as tmp:
        rc, out, err = _run_db_graph(
            ["find-instance", "--class", "json:JSONDecoder"],
            python_env=args.python_env,
            extra_env={"PYTHONPATH": tmp},
        )
    if rc != 5:
        print(f"  [FAIL] expected rc=5 (db_error), got {rc}; stderr: {err[:200]!r}")
        return False
    payload = _parse_json_or_fail(out, "find-instance db_error stdout")
    if payload is None:
        return False
    if payload.get("kind") != "db_error":
        print(f"  [FAIL] kind != 'db_error': {payload.get('kind')!r}")
        return False
    error = payload.get("error", {})
    if error.get("kind") != "datajoint_import":
        print(
            f"  [FAIL] error.kind != 'datajoint_import': "
            f"{error.get('kind')!r}"
        )
        return False
    if "total" not in payload.get("timings_ms", {}):
        print(f"  [FAIL] timings_ms.total missing: {payload.get('timings_ms')!r}")
        return False
    print(
        "  [ok] find-instance: kind='db_error', error.kind='datajoint_import', "
        "exit 5, timings_ms.total present"
    )
    return True


def fixture_emitted_kind_always_appears_in_payload_envelopes(
    args: argparse.Namespace,
) -> bool:
    """Every emitted ``kind`` must be documented in ``info.payload_envelopes``.

    ``info --json`` is the contract source of truth. If the tool emits a
    ``kind`` that has no matching envelope, an LLM consuming the contract
    has no shape to validate the payload against. Tests both the
    deterministic ``db_error`` path (poisoned env) and, when DataJoint /
    Spyglass are available, the ``not_implemented`` Batch-B endpoint.
    """
    rc_info, out_info, err_info = _run_db_graph(
        ["info", "--json"], python_env=args.python_env
    )
    if rc_info != 0:
        print(f"  [FAIL] info --json exited {rc_info}; stderr: {err_info!r}")
        return False
    info = _parse_json_or_fail(out_info, "info --json")
    if info is None:
        return False
    envelopes = info.get("payload_envelopes", {})

    # Path 1: db_error (always available via poisoned datajoint).
    with _poisoned_datajoint_path() as tmp:
        _, out_db, _ = _run_db_graph(
            ["find-instance", "--class", "json:JSONDecoder"],
            python_env=args.python_env,
            extra_env={"PYTHONPATH": tmp},
        )
    db_payload = _parse_json_or_fail(out_db, "db_error path")
    if db_payload is None:
        return False
    if not _kind_matches_envelope(db_payload, envelopes, "db_error path"):
        return False

    # Path 2: not_implemented (Batch-B success) — only when DataJoint AND
    # Spyglass both import on python_env.
    if args.has_datajoint and args.has_spyglass:
        _, out_ni, _ = _run_db_graph(
            ["find-instance", "--class", "Session"],
            python_env=args.python_env,
        )
        ni_payload = _parse_json_or_fail(out_ni, "not_implemented path")
        if ni_payload is None:
            return False
        if not _kind_matches_envelope(ni_payload, envelopes, "not_implemented path"):
            return False
        print(
            "  [ok] db_error and not_implemented both match documented envelopes"
        )
    else:
        print(
            "  [ok] db_error matches documented envelope; "
            "not_implemented path skipped (no datajoint/spyglass on python_env)"
        )
    return True


def _kind_matches_envelope(payload: dict, envelopes: dict, label: str) -> bool:
    """Check ``payload``'s top-level keys match the documented envelope."""
    kind = payload.get("kind")
    if kind not in envelopes:
        print(
            f"  [FAIL] {label}: kind={kind!r} is not in payload_envelopes "
            f"({sorted(envelopes.keys())})"
        )
        return False
    documented = envelopes[kind]
    actual = list(payload.keys())
    if actual != documented:
        print(f"  [FAIL] {label}: field order mismatch")
        print(f"         envelope[{kind!r}]: {documented}")
        print(f"         actual           : {actual}")
        return False
    return True


def fixture_aggregate_modes_require_count_distinct(
    args: argparse.Namespace,
) -> bool:
    """``--group-by`` / ``--group-by-table`` require ``--count-distinct``.

    Plan, Grouped counts: the only MVP aggregates are paired modes. Free-
    form aggregates are out of scope. main() enforces the pairing so a
    malformed combination cannot reach the eventual implementation.
    """
    rc1, _, err1 = _run_db_graph(
        ["find-instance", "--class", "Foo", "--group-by", "f1,f2"],
        python_env=args.python_env,
    )
    if rc1 != 2 or "--count-distinct" not in err1:
        print(
            f"  [FAIL] --group-by alone: rc={rc1}, error did not mention "
            f"--count-distinct: {err1[-200:]!r}"
        )
        return False
    rc2, _, err2 = _run_db_graph(
        ["find-instance", "--class", "Foo", "--group-by-table", "Session"],
        python_env=args.python_env,
    )
    if rc2 != 2 or "--count-distinct" not in err2:
        print(
            f"  [FAIL] --group-by-table alone: rc={rc2}, error did not mention "
            f"--count-distinct: {err2[-200:]!r}"
        )
        return False
    print(
        "  [ok] --group-by / --group-by-table require --count-distinct (exit 2)"
    )
    return True


def fixture_count_distinct_requires_a_grouping(
    args: argparse.Namespace,
) -> bool:
    """``--count-distinct`` without a grouping flag is rejected.

    A bare ``--count-distinct FIELD`` could plausibly be misread as a
    "distinct count over the whole relation" mode, but that is out of
    MVP. Refuse it explicitly so an agent gets a clear error rather than
    a surprising silent reinterpretation.
    """
    rc, _, err = _run_db_graph(
        ["find-instance", "--class", "Foo", "--count-distinct", "field"],
        python_env=args.python_env,
    )
    if rc != 2:
        print(f"  [FAIL] expected rc=2, got {rc}")
        return False
    if "--group-by" not in err:
        print(
            f"  [FAIL] error did not mention --group-by[-table]: {err[-200:]!r}"
        )
        return False
    print("  [ok] --count-distinct requires --group-by[-table] (exit 2)")
    return True


def fixture_group_by_and_group_by_table_are_mutually_exclusive(
    args: argparse.Namespace,
) -> bool:
    """``--group-by`` and ``--group-by-table`` cannot both be supplied.

    The plan documents two grouping forms; combining them in one query
    is not defined. Refusing now prevents a future Batch E implementation
    from having to invent semantics under deadline pressure.
    """
    rc, _, err = _run_db_graph(
        [
            "find-instance",
            "--class",
            "Foo",
            "--group-by",
            "f1",
            "--group-by-table",
            "Session",
            "--count-distinct",
            "field",
        ],
        python_env=args.python_env,
    )
    if rc != 2:
        print(f"  [FAIL] expected rc=2, got {rc}")
        return False
    if "mutually exclusive" not in err:
        print(
            f"  [FAIL] error did not mention 'mutually exclusive': {err[-200:]!r}"
        )
        return False
    print(
        "  [ok] --group-by and --group-by-table are mutually exclusive (exit 2)"
    )
    return True


def fixture_merge_master_without_part_exits_2(
    args: argparse.Namespace,
) -> bool:
    """``--merge-master`` without ``--part`` (and vice versa) returns exit 2.

    Plan: both flags are required together. argparse cannot express the
    pairing directly, so ``main()`` enforces it; this test pins the rule.
    """
    rc1, _, err1 = _run_db_graph(
        ["find-instance", "--class", "Foo", "--merge-master", "Bar"],
        python_env=args.python_env,
    )
    if rc1 != 2:
        print(f"  [FAIL] --merge-master alone: expected rc=2, got {rc1}")
        return False
    if "--part" not in err1:
        print(f"  [FAIL] error message does not mention --part: {err1!r}")
        return False
    rc2, _, _ = _run_db_graph(
        ["find-instance", "--class", "Foo", "--part", "Bar"],
        python_env=args.python_env,
    )
    if rc2 != 2:
        print(f"  [FAIL] --part alone: expected rc=2, got {rc2}")
        return False
    print("  [ok] --merge-master / --part are required together (exit 2)")
    return True


def fixture_limit_hard_max_enforced(args: argparse.Namespace) -> bool:
    """``--limit`` above the hard cap of 1000 is rejected with exit 2."""
    rc, _, err = _run_db_graph(
        ["find-instance", "--class", "Foo", "--limit", "1001"],
        python_env=args.python_env,
    )
    if rc != 2:
        print(f"  [FAIL] --limit 1001: expected rc=2, got {rc}")
        return False
    if "1000" not in err:
        print(f"  [FAIL] error message does not mention the cap of 1000: {err!r}")
        return False
    print("  [ok] --limit hard max of 1000 is enforced")
    return True


def fixture_unknown_subcommand_exits_2(args: argparse.Namespace) -> bool:
    """A subcommand name not in {info, find-instance} returns exit 2."""
    rc, _, err = _run_db_graph(["bogus"], python_env=args.python_env)
    if rc != 2:
        print(f"  [FAIL] expected rc=2, got {rc}")
        return False
    if "bogus" not in err and "invalid choice" not in err:
        print(f"  [FAIL] unhelpful error message: {err!r}")
        return False
    print("  [ok] unknown subcommand returns exit 2")
    return True


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Batch B fixtures: class resolution
# ---------------------------------------------------------------------------


def _require_capability(
    args: argparse.Namespace,
    *,
    datajoint: bool,
    spyglass: bool,
    why: str,
) -> bool:
    """Capability gate. Returns True iff the fixture body should run.

    Convention used by every Batch-B fixture::

        if not _require_capability(args, datajoint=True, spyglass=True, why="..."):
            return True  # short-circuit; runner reads the markers below

    Returns False whenever required capabilities are missing — both in
    ``--require-capabilities`` mode (where the gate prints ``[FAIL]`` and
    sets ``args._last_fail_reason``) and in normal mode (where it prints
    ``[skip]`` and sets ``args._last_skip_reason``). The fixture
    short-circuits in both cases by ``return True``; the runner
    classifies the outcome by checking which marker was set, so a
    missing-capability skip is not counted as a real pass and a
    require-capabilities run produces a non-zero rc.
    """
    missing = []
    if datajoint and not args.has_datajoint:
        missing.append("datajoint")
    if spyglass and not args.has_spyglass:
        missing.append("spyglass")
    if not missing:
        return True
    if args.require_capabilities:
        print(
            f"  [FAIL] {why} — missing on python_env: "
            f"{', '.join(missing)} (--require-capabilities is set)"
        )
        args._last_fail_reason = ", ".join(missing)
        return False
    print(f"  [skip] {why} — missing on python_env: {', '.join(missing)}")
    args._last_skip_reason = ", ".join(missing)
    return False


def _expect_resolved_payload(
    out: str,
    *,
    expected_module: str,
    expected_qualname: str,
    expected_resolution_source: str,
) -> bool:
    """Shared assertion: payload's resolution provenance matches expectations.

    Used by every Batch-B fixture that wants to pin "this class went
    through this resolution path" without caring about the row data.
    Batch C subsumes the Batch B endpoint: instead of
    ``kind: "not_implemented"``, a successful resolution now produces
    ``kind: "find-instance"`` with real ``count``/``rows``. The provenance
    fields (``query.module``, ``query.qualname``, ``query.resolution_source``)
    remain the contract this helper pins. ``query.stage`` was a Batch-B
    affordance and is gone in Batch C.
    """
    payload = _parse_json_or_fail(out, "find-instance resolved stdout")
    if payload is None:
        return False
    if payload.get("kind") != "find-instance":
        print(f"  [FAIL] kind != 'find-instance': {payload.get('kind')!r}")
        return False
    query = payload.get("query", {})
    if query.get("module") != expected_module:
        print(
            f"  [FAIL] query.module != {expected_module!r}: "
            f"{query.get('module')!r}"
        )
        return False
    if query.get("qualname") != expected_qualname:
        print(
            f"  [FAIL] query.qualname != {expected_qualname!r}: "
            f"{query.get('qualname')!r}"
        )
        return False
    if query.get("resolution_source") != expected_resolution_source:
        print(
            f"  [FAIL] query.resolution_source != "
            f"{expected_resolution_source!r}: {query.get('resolution_source')!r}"
        )
        return False
    return True


def fixture_b_resolves_stock_short_name(args: argparse.Namespace) -> bool:
    """``--class Session`` resolves via the stock _index path."""
    if not _require_capability(
        args, datajoint=True, spyglass=True,
        why="resolves Session via stock _index lookup",
    ):
        return True  # skip = pass
    rc, out, err = _run_db_graph(
        ["find-instance", "--class", "Session"],
        python_env=args.python_env,
    )
    # Batch C makes the resolved-class endpoint go all the way through
    # to a real fetch — exit 0 with kind=find-instance. The provenance
    # check below pins the resolution path used to get there.
    if rc != 0:
        print(f"  [FAIL] expected rc=0, got {rc}; stderr: {err[:200]!r}")
        return False
    if not _expect_resolved_payload(
        out,
        expected_module="spyglass.common.common_session",
        expected_qualname="Session",
        expected_resolution_source="stock_index",
    ):
        return False
    print("  [ok] --class Session resolves via stock_index")
    return True


def fixture_b_resolves_dotted_qualname(args: argparse.Namespace) -> bool:
    """``--class LFPOutput.LFPV1`` resolves to the merge-part record.

    `code_graph._resolve_class` filters by exact qualname when the input
    is dotted; the part-table record (qualname=`LFPOutput.LFPV1`) wins
    over the v1 top-level record (qualname=`LFPV1`).
    """
    if not _require_capability(
        args, datajoint=True, spyglass=True,
        why="resolves Master.Part qualname",
    ):
        return True
    rc, out, err = _run_db_graph(
        ["find-instance", "--class", "LFPOutput.LFPV1"],
        python_env=args.python_env,
    )
    if rc != 0:
        print(f"  [FAIL] expected rc=0, got {rc}; stderr: {err[:200]!r}")
        return False
    if not _expect_resolved_payload(
        out,
        expected_module="spyglass.lfp.lfp_merge",
        expected_qualname="LFPOutput.LFPV1",
        expected_resolution_source="stock_index",
    ):
        return False
    print("  [ok] --class LFPOutput.LFPV1 resolves to merge-part via stock_index")
    return True


def fixture_b_resolves_module_class_form(args: argparse.Namespace) -> bool:
    """``module:Class`` (explicit colon form) resolves via module_path source."""
    if not _require_capability(
        args, datajoint=True, spyglass=True,
        why="resolves explicit module:Class form",
    ):
        return True
    rc, out, err = _run_db_graph(
        ["find-instance", "--class", "spyglass.common.common_session:Session"],
        python_env=args.python_env,
    )
    if rc != 0:
        print(f"  [FAIL] expected rc=0, got {rc}; stderr: {err[:200]!r}")
        return False
    if not _expect_resolved_payload(
        out,
        expected_module="spyglass.common.common_session",
        expected_qualname="Session",
        expected_resolution_source="module_path",
    ):
        return False
    print("  [ok] module:Class form resolves via module_path source")
    return True


def fixture_b_resolves_dotted_module_path(args: argparse.Namespace) -> bool:
    """Implicit dotted module path ``a.b.c.D`` falls through to module_path source.

    The _index lookup tries to match the full qualname (``a.b.c.D``) and
    fails (the index keys on Spyglass-internal qualnames like ``Session``,
    not on absolute module paths). The resolver then falls through to the
    module-path heuristic.
    """
    if not _require_capability(
        args, datajoint=True, spyglass=True,
        why="resolves dotted module path implicit form",
    ):
        return True
    rc, out, err = _run_db_graph(
        ["find-instance", "--class", "spyglass.common.common_session.Session"],
        python_env=args.python_env,
    )
    if rc != 0:
        print(f"  [FAIL] expected rc=0, got {rc}; stderr: {err[:200]!r}")
        return False
    if not _expect_resolved_payload(
        out,
        expected_module="spyglass.common.common_session",
        expected_qualname="Session",
        expected_resolution_source="module_path",
    ):
        return False
    print("  [ok] dotted module path falls through to module_path source")
    return True


def fixture_b_resolves_via_import_for_custom_class(
    args: argparse.Namespace,
) -> bool:
    """``--import customlab --class customlab:CustomTable`` resolves a non-stock UserTable.

    The custom-table escape hatch: ``--import`` runs the user-supplied
    module so its DataJoint declarations are loaded, and the colon form
    points the resolver at the in-memory class.
    """
    if not _require_capability(
        args, datajoint=True, spyglass=True,
        why="custom --import escape hatch for non-stock UserTable classes",
    ):
        return True
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        (tmp / "customlab_db_graph.py").write_text(
            textwrap.dedent(
                '''
                """Synthetic custom-table module for the db_graph --import test."""
                import datajoint as dj

                schema = dj.Schema(create_schema=False, create_tables=False)


                @schema
                class CustomTable(dj.Manual):
                    definition = """
                    custom_id : int
                    ---
                    """
                '''
            )
        )
        rc, out, err = _run_db_graph(
            [
                "find-instance",
                "--import",
                "customlab_db_graph",
                "--class",
                "customlab_db_graph:CustomTable",
            ],
            python_env=args.python_env,
            extra_env={"PYTHONPATH": str(tmp)},
        )
    # The synthetic CustomTable has no real DataJoint table backing it
    # (``create_tables=False``), so the fetch step legitimately fails
    # with a db_error. The resolution itself succeeded — that is what
    # this fixture pins. Accept either find-instance (table happened
    # to exist) or db_error (expected for a truly synthetic class), but
    # require the resolution provenance to be present in either payload.
    if rc not in (0, 5):
        print(f"  [FAIL] expected rc in (0, 5), got {rc}; stderr: {err[:200]!r}")
        return False
    payload = _parse_json_or_fail(out, "custom-import payload")
    if payload is None:
        return False
    query = payload.get("query", {})
    if query.get("module") != "customlab_db_graph":
        print(f"  [FAIL] query.module drifted: {query.get('module')!r}")
        return False
    if query.get("qualname") != "CustomTable":
        print(f"  [FAIL] query.qualname drifted: {query.get('qualname')!r}")
        return False
    if query.get("resolution_source") != "module_path":
        print(
            f"  [FAIL] query.resolution_source drifted: "
            f"{query.get('resolution_source')!r}"
        )
        return False
    print(
        f"  [ok] --import + module:Class resolves a custom class "
        f"(rc={rc}, kind={payload.get('kind')!r})"
    )
    return True


def fixture_b_ambiguous_short_name_exits_3(args: argparse.Namespace) -> bool:
    """Multiple top-level records with the same short name → exit 3, kind=ambiguous.

    Constructed via a synthetic ``--src`` tree because real Spyglass
    short names that pass the qualname-filter are mostly unique
    (``BodyPart`` resolves to the top-level record because the others
    are ``Master.BodyPart`` qualnames). The synthetic case puts two
    ``FooBar`` top-level records in different files.

    No capability gate: the resolver raises ``_AmbiguousClass`` from
    inside the _index lookup, which is pure stdlib (AST scan over the
    synthetic tree). The DataJoint UserTable predicate runs later, only
    when a class needs to be returned, so this fixture passes without
    DataJoint or Spyglass on ``python_env``.
    """
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        for sub in ("alpha", "beta"):
            mod_dir = tmp / "spyglass" / sub
            mod_dir.mkdir(parents=True, exist_ok=True)
            (mod_dir / "__init__.py").write_text("")
            (mod_dir / "tables.py").write_text(
                textwrap.dedent(
                    '''
                    class FooBar:
                        definition = """
                        id : int
                        ---
                        """
                    '''
                )
            )
        # Top-level spyglass/__init__.py so _index.scan accepts the tree.
        (tmp / "spyglass" / "__init__.py").write_text("")
        rc, out, err = _run_db_graph(
            ["find-instance", "--src", str(tmp), "--class", "FooBar"],
            python_env=args.python_env,
        )
    if rc != 3:
        print(f"  [FAIL] expected rc=3 (ambiguous), got {rc}; stderr: {err[:200]!r}")
        return False
    payload = _parse_json_or_fail(out, "ambiguous payload")
    if payload is None:
        return False
    if payload.get("kind") != "ambiguous":
        print(f"  [FAIL] kind != 'ambiguous': {payload.get('kind')!r}")
        return False
    candidates = payload.get("candidates", [])
    if len(candidates) < 2:
        print(f"  [FAIL] expected >= 2 candidates, got {candidates!r}")
        return False
    for cand in candidates:
        for field in ("qualname", "file", "line"):
            if field not in cand:
                print(f"  [FAIL] candidate missing {field!r}: {cand!r}")
                return False
    print(f"  [ok] FooBar exits 3 with {len(candidates)} candidates")
    return True


def fixture_b_not_found_exits_4(args: argparse.Namespace) -> bool:
    """Genuinely unknown short name → exit 4, kind=not_found, error.kind=not_found.

    Uses a synthetic ``--src`` (empty ``spyglass/`` package) so the
    fixture does not require Spyglass on ``python_env``; the resolver's
    not_found branch fires before the DataJoint predicate runs, so no
    DataJoint capability gate is needed either.
    """
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        (tmp / "spyglass").mkdir()
        (tmp / "spyglass" / "__init__.py").write_text("")
        rc, out, err = _run_db_graph(
            [
                "find-instance",
                "--src",
                str(tmp),
                "--class",
                "ZZZNotARealSpyglassClass",
            ],
            python_env=args.python_env,
        )
    if rc != 4:
        print(f"  [FAIL] expected rc=4 (not_found), got {rc}; stderr: {err[:200]!r}")
        return False
    payload = _parse_json_or_fail(out, "not_found payload")
    if payload is None:
        return False
    if payload.get("kind") != "not_found":
        print(f"  [FAIL] kind != 'not_found': {payload.get('kind')!r}")
        return False
    error = payload.get("error", {})
    if error.get("kind") != "not_found":
        print(f"  [FAIL] error.kind != 'not_found': {error.get('kind')!r}")
        return False
    if not error.get("hint"):
        print(f"  [FAIL] error.hint should describe how to recover: {error!r}")
        return False
    print("  [ok] unknown class name exits 4 with structured not_found")
    return True


def fixture_b_not_a_table_exits_4(args: argparse.Namespace) -> bool:
    """Importable class that is not a DataJoint UserTable → exit 4, error.kind=not_a_table.

    Uses ``json:JSONDecoder`` as the canonical example: stdlib, importable
    on any Python the find-instance path can reach (DataJoint must be
    importable for the predicate to run, hence the capability gate).
    """
    if not _require_capability(
        args, datajoint=True, spyglass=False,
        why="UserTable predicate requires DataJoint to be importable",
    ):
        return True
    rc, out, err = _run_db_graph(
        ["find-instance", "--class", "json:JSONDecoder"],
        python_env=args.python_env,
    )
    if rc != 4:
        print(
            f"  [FAIL] expected rc=4 (not a UserTable), got {rc}; "
            f"stderr: {err[:200]!r}"
        )
        return False
    payload = _parse_json_or_fail(out, "not_a_table payload")
    if payload is None:
        return False
    if payload.get("kind") != "not_found":
        print(f"  [FAIL] kind != 'not_found': {payload.get('kind')!r}")
        return False
    error = payload.get("error", {})
    if error.get("kind") != "not_a_table":
        print(
            f"  [FAIL] error.kind != 'not_a_table': {error.get('kind')!r}"
        )
        return False
    query = payload.get("query", {})
    if query.get("module") != "json" or query.get("qualname") != "JSONDecoder":
        print(f"  [FAIL] query.module/qualname drifted: {query!r}")
        return False
    print("  [ok] non-UserTable class exits 4 with error.kind='not_a_table'")
    return True


def fixture_b_src_overrides_installed_package(
    args: argparse.Namespace,
) -> bool:
    """``--src`` is authoritative over the installed-package fallback.

    Pass a ``--src`` that does not contain a ``spyglass/`` subdir, and
    ``--class Session`` (a real stock name): resolution must NOT succeed
    via the installed-package fallback. Proves --src has highest precedence.
    """
    if not _require_capability(
        args,
        datajoint=True,
        spyglass=True,
        why=(
            "--src precedence test relies on installed Spyglass being "
            "available as a fallback that we then prove unused"
        ),
    ):
        return True
    with tempfile.TemporaryDirectory() as tmp_str:
        rc, out, err = _run_db_graph(
            ["find-instance", "--src", tmp_str, "--class", "Session"],
            python_env=args.python_env,
        )
    if rc != 4:
        print(
            f"  [FAIL] --src bogus + --class Session: expected rc=4 "
            f"(--src is authoritative), got {rc}; stderr: {err[:200]!r}"
        )
        return False
    payload = _parse_json_or_fail(out, "src-precedence payload")
    if payload is None:
        return False
    if payload.get("kind") != "not_found":
        print(f"  [FAIL] kind != 'not_found': {payload.get('kind')!r}")
        return False
    print(
        "  [ok] --src bogus path overrides installed package: "
        "Session not found"
    )
    return True


def fixture_b_installed_package_overrides_env_var(
    args: argparse.Namespace,
) -> bool:
    """The installed-package fallback wins over ``$SPYGLASS_SRC``.

    With no ``--src`` flag, set ``SPYGLASS_SRC`` to a bogus path that
    contains no ``spyglass/`` subdir. ``--class Session`` must still
    resolve via the installed-package fallback (which is checked BEFORE
    ``$SPYGLASS_SRC`` per the precedence chain).
    """
    if not _require_capability(
        args, datajoint=True, spyglass=True,
        why="precedence test requires installed Spyglass",
    ):
        return True
    with tempfile.TemporaryDirectory() as tmp_str:
        rc, out, err = _run_db_graph(
            ["find-instance", "--class", "Session"],
            python_env=args.python_env,
            extra_env={"SPYGLASS_SRC": tmp_str},
        )
    if rc != 0:
        print(
            f"  [FAIL] expected rc=0 (resolved via installed fallback), "
            f"got {rc}; stderr: {err[:200]!r}"
        )
        return False
    if not _expect_resolved_payload(
        out,
        expected_module="spyglass.common.common_session",
        expected_qualname="Session",
        expected_resolution_source="stock_index",
    ):
        return False
    print(
        "  [ok] installed-package fallback wins over $SPYGLASS_SRC=<bogus>"
    )
    return True


# ---------------------------------------------------------------------------
# Batch C fixtures: basic find-instance
# ---------------------------------------------------------------------------


def _read_db_graph_source() -> str:
    """Read the db_graph.py source for static-analysis fixtures."""
    return DB_GRAPH.read_text()


def _setup_fakes_sandbox(
    tmp: Path,
    *,
    module_name: str,
    class_name: str,
    primary_key: tuple[str, ...],
    names: tuple[str, ...],
    attributes: dict[str, str],
    rows: list[dict],
    base: str = "Manual",
    raises_on_fetch: str | None = None,
) -> Path:
    """Build a self-contained PYTHONPATH directory and return its Path.

    The directory contains:

    * ``datajoint/`` — the fake-DataJoint shim from ``fakes.py``.
    * ``fakes.py`` — copied so the synthetic test module can import
      ``FakeRelation`` / ``FakeHeading`` directly.
    * ``<module_name>.py`` — the synthetic UserTable class.

    Subprocess invocations of ``db_graph.py`` then run with
    ``PYTHONPATH=<dir>`` and ``--import <module_name> --class
    <module_name>:<class_name>``. The fake DataJoint shadows the real
    one if installed, removing the live-DB dependency for fixtures
    that exercise restriction / fetch / heading paths.
    """
    import fakes as _fakes_module

    _fakes_module.prepare_sandbox(tmp)
    _fakes_module.write_fake_test_module(
        tmp,
        module_name=module_name,
        class_name=class_name,
        primary_key=primary_key,
        names=names,
        attributes=attributes,
        rows=rows,
        base=base,
        raises_on_fetch=raises_on_fetch,
    )
    return tmp


def fixture_c_fakes_restriction_and_fetch(args: argparse.Namespace) -> bool:
    """End-to-end find-instance via the fakes sandbox — no live DB needed.

    This is the canonical Batch-C coverage fixture for the no-VPN /
    no-spyglass-installed case. A synthetic ``FakeSession`` class is
    built with three rows; ``--key subject_id=aj80`` filters to two of
    them and ``--fields KEY`` returns just the primary keys. The fixture
    asserts the find-instance envelope, count, restriction echo,
    resolution provenance, and the actual returned rows match the
    sandboxed truth.
    """
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = _setup_fakes_sandbox(
            Path(tmp_str),
            module_name="fakelab",
            class_name="FakeSession",
            primary_key=("nwb_file_name",),
            names=("nwb_file_name", "subject_id", "session_description"),
            attributes={
                "nwb_file_name": "varchar(64)",
                "subject_id": "varchar(32)",
                "session_description": "varchar(2000)",
            },
            rows=[
                {
                    "nwb_file_name": "one.nwb",
                    "subject_id": "aj80",
                    "session_description": "first",
                },
                {
                    "nwb_file_name": "two.nwb",
                    "subject_id": "aj80",
                    "session_description": "second",
                },
                {
                    "nwb_file_name": "three.nwb",
                    "subject_id": "rat42",
                    "session_description": "third",
                },
            ],
        )
        rc, out, err = _run_db_graph(
            [
                "find-instance",
                "--import",
                "fakelab",
                "--class",
                "fakelab:FakeSession",
                "--key",
                "subject_id=aj80",
                "--fields",
                "KEY",
            ],
            python_env=args.python_env,
            extra_env={"PYTHONPATH": str(tmp)},
        )
    if rc != 0:
        print(f"  [FAIL] expected rc=0, got {rc}; stderr: {err[:300]!r}")
        return False
    payload = _parse_json_or_fail(out, "fakes restriction+fetch")
    if payload is None:
        return False
    if payload.get("kind") != "find-instance":
        print(f"  [FAIL] kind != 'find-instance': {payload.get('kind')!r}")
        return False
    if payload.get("count") != 2:
        print(
            f"  [FAIL] count != 2 (subject_id=aj80 expected two rows): "
            f"{payload.get('count')!r}"
        )
        return False
    rows = payload.get("rows", [])
    pks = sorted(r.get("nwb_file_name") for r in rows)
    if pks != ["one.nwb", "two.nwb"]:
        print(f"  [FAIL] rows do not match restriction: {pks!r}")
        return False
    restriction_echo = payload.get("query", {}).get("restriction")
    if restriction_echo != {"subject_id": "aj80"}:
        print(f"  [FAIL] query.restriction echo drifted: {restriction_echo!r}")
        return False
    print("  [ok] fakes sandbox: restriction+fetch returns 2 rows with correct PKs")
    return True


def fixture_c_fakes_count_only(args: argparse.Namespace) -> bool:
    """``--count`` against the fakes sandbox returns count without rows."""
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = _setup_fakes_sandbox(
            Path(tmp_str),
            module_name="fakelab_count",
            class_name="FakeElectrode",
            primary_key=("nwb_file_name", "electrode_id"),
            names=("nwb_file_name", "electrode_id"),
            attributes={
                "nwb_file_name": "varchar(64)",
                "electrode_id": "int",
            },
            rows=[
                {"nwb_file_name": "x.nwb", "electrode_id": i}
                for i in range(5)
            ],
        )
        rc, out, _ = _run_db_graph(
            [
                "find-instance",
                "--import",
                "fakelab_count",
                "--class",
                "fakelab_count:FakeElectrode",
                "--key",
                "nwb_file_name=x.nwb",
                "--count",
            ],
            python_env=args.python_env,
            extra_env={"PYTHONPATH": str(tmp)},
        )
    if rc != 0:
        print(f"  [FAIL] expected rc=0, got {rc}")
        return False
    payload = _parse_json_or_fail(out, "fakes count")
    if payload is None:
        return False
    if payload.get("count") != 5:
        print(f"  [FAIL] count != 5: {payload.get('count')!r}")
        return False
    if payload.get("rows") != []:
        print(f"  [FAIL] --count must yield empty rows: {payload.get('rows')!r}")
        return False
    if payload.get("query", {}).get("mode") != "count":
        print(f"  [FAIL] query.mode != 'count': {payload.get('query', {}).get('mode')!r}")
        return False
    print("  [ok] fakes sandbox: --count returns 5 with empty rows")
    return True


def fixture_c_fakes_truncation_marker(args: argparse.Namespace) -> bool:
    """``--limit 2`` against a 5-row relation triggers ``truncated: true``."""
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = _setup_fakes_sandbox(
            Path(tmp_str),
            module_name="fakelab_truncate",
            class_name="FakeIntervals",
            primary_key=("nwb_file_name", "interval_list_name"),
            names=("nwb_file_name", "interval_list_name"),
            attributes={
                "nwb_file_name": "varchar(64)",
                "interval_list_name": "varchar(200)",
            },
            rows=[
                {"nwb_file_name": "x.nwb", "interval_list_name": f"epoch_{i}"}
                for i in range(5)
            ],
        )
        rc, out, _ = _run_db_graph(
            [
                "find-instance",
                "--import",
                "fakelab_truncate",
                "--class",
                "fakelab_truncate:FakeIntervals",
                "--limit",
                "2",
                "--fields",
                "KEY",
            ],
            python_env=args.python_env,
            extra_env={"PYTHONPATH": str(tmp)},
        )
    if rc != 0:
        print(f"  [FAIL] expected rc=0, got {rc}")
        return False
    payload = _parse_json_or_fail(out, "fakes truncation")
    if payload is None:
        return False
    if not payload.get("truncated"):
        print(f"  [FAIL] truncated should be true: {payload.get('truncated')!r}")
        return False
    actual_rows = len(payload.get("rows", []))
    if actual_rows != 2:
        print(
            f"  [FAIL] rows should have 2 entries (the limit), got "
            f"{actual_rows}"
        )
        return False
    if payload.get("count") != 5:
        print(f"  [FAIL] count should be 5 (full relation): {payload.get('count')!r}")
        return False
    print("  [ok] fakes sandbox: --limit 2 with 5 rows → truncated=true, rows=2, count=5")
    return True


def fixture_c_fakes_unknown_field_validation(
    args: argparse.Namespace,
) -> bool:
    """Unknown restriction field validation runs through fakes too.

    Mirrors the live ``fixture_c_unknown_restriction_field_refused`` but
    uses the fakes sandbox so it runs on system Python without VPN.
    """
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = _setup_fakes_sandbox(
            Path(tmp_str),
            module_name="fakelab_validation",
            class_name="FakeTable",
            primary_key=("id",),
            names=("id", "name"),
            attributes={"id": "int", "name": "varchar(64)"},
            rows=[{"id": 1, "name": "a"}],
        )
        rc, out, err = _run_db_graph(
            [
                "find-instance",
                "--import",
                "fakelab_validation",
                "--class",
                "fakelab_validation:FakeTable",
                "--key",
                "definitely_not_a_field=x",
            ],
            python_env=args.python_env,
            extra_env={"PYTHONPATH": str(tmp)},
        )
    if rc != 2:
        print(f"  [FAIL] expected rc=2 (invalid_query), got {rc}; stderr: {err[:200]!r}")
        return False
    payload = _parse_json_or_fail(out, "fakes invalid_query")
    if payload is None:
        return False
    if payload.get("kind") != "invalid_query":
        print(f"  [FAIL] kind != 'invalid_query': {payload.get('kind')!r}")
        return False
    if payload.get("error", {}).get("kind") != "unknown_field":
        print(f"  [FAIL] error.kind != 'unknown_field': {payload.get('error', {})!r}")
        return False
    print("  [ok] fakes sandbox: unknown restriction field exits 2 with kind=invalid_query")
    return True


def fixture_c_fakes_blob_restriction_refused(
    args: argparse.Namespace,
) -> bool:
    """Blob-restriction refusal runs through fakes — no live DB needed."""
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = _setup_fakes_sandbox(
            Path(tmp_str),
            module_name="fakelab_blob",
            class_name="FakeIntervalList",
            primary_key=("nwb_file_name", "interval_list_name"),
            names=("nwb_file_name", "interval_list_name", "valid_times"),
            attributes={
                "nwb_file_name": "varchar(64)",
                "interval_list_name": "varchar(200)",
                "valid_times": "longblob",
            },
            rows=[],
        )
        rc, out, _ = _run_db_graph(
            [
                "find-instance",
                "--import",
                "fakelab_blob",
                "--class",
                "fakelab_blob:FakeIntervalList",
                "--key",
                "valid_times=anything",
            ],
            python_env=args.python_env,
            extra_env={"PYTHONPATH": str(tmp)},
        )
    if rc != 2:
        print(f"  [FAIL] expected rc=2, got {rc}")
        return False
    payload = _parse_json_or_fail(out, "fakes blob_restriction")
    if payload is None:
        return False
    if payload.get("error", {}).get("kind") != "blob_restriction_refused":
        print(f"  [FAIL] error.kind != 'blob_restriction_refused': {payload.get('error', {})!r}")
        return False
    print("  [ok] fakes sandbox: blob-attribute restriction exits 2 with clear error")
    return True


def fixture_c_fakes_safe_serialization_envelopes(
    args: argparse.Namespace,
) -> bool:
    """Per-field safe serialization envelopes round-trip via the fakes sandbox.

    Builds a synthetic class whose rows contain DataJoint-shaped values
    that ``json.dumps`` cannot serialize natively: ``bytes`` (blob),
    ``datetime`` (timestamp), ``uuid.UUID`` (DataJoint's ``uuid`` type),
    ``float('nan')`` (rare but emitted by some pandas pipelines). The
    fixture asserts each value is converted to its documented envelope
    and the whole payload survives ``json.loads(json.dumps(...,
    allow_nan=False))`` — strict-JSON compliance is the LLM-facing
    contract this fixture pins.

    Numpy ``ndarray`` is intentionally left out: it requires numpy
    available to the subprocess interpreter. The corresponding
    serialization branch is exercised by an inline smoke check at
    Batch-C commit time.
    """
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        # Fake datajoint + fakes copy.
        import fakes as _fakes_module

        _fakes_module.prepare_sandbox(tmp)
        # Synthetic module written directly so the rows can construct
        # bytes / datetime / UUID / NaN values via real Python
        # expressions (write_fake_test_module's repr-based path can't
        # round-trip every type).
        (tmp / "fakelab_serialize.py").write_text(
            "\n".join(
                [
                    '"""Synthetic class with rich-typed rows for serialization tests."""',
                    "import datetime",
                    "import uuid",
                    "from datajoint import Manual",
                    "from fakes import FakeHeading, FakeRelation",
                    "",
                    "",
                    "class FakeWeirdRow(Manual):",
                    "    _heading_obj = FakeHeading(",
                    "        primary_key=('id',),",
                    "        names=('id', 'blob_data', 'ts', 'uid', 'maybe_nan'),",
                    "        attributes={",
                    "            'id': 'int',",
                    "            'blob_data': 'varchar(64)',",
                    "            'ts': 'timestamp',",
                    "            'uid': 'uuid',",
                    "            'maybe_nan': 'float',",
                    "        },",
                    "    )",
                    "    _rows = [",
                    "        {",
                    "            'id': 1,",
                    "            'blob_data': b'\\x00\\xff\\x10\\x42',",
                    "            'ts': datetime.datetime(2026, 4, 27, 12, 30, 0),",
                    "            'uid': uuid.UUID('00000000-0000-0000-0000-000000000001'),",
                    "            'maybe_nan': float('nan'),",
                    "        },",
                    "    ]",
                    "",
                    "    def __new__(cls):",
                    "        return FakeRelation(",
                    "            heading=cls._heading_obj, rows=cls._rows",
                    "        )",
                    "",
                    "    @property",
                    "    def heading(self):",
                    "        return self._heading_obj",
                    "",
                ]
            )
        )
        rc, out, err = _run_db_graph(
            [
                "find-instance",
                "--import",
                "fakelab_serialize",
                "--class",
                "fakelab_serialize:FakeWeirdRow",
                "--fields",
                "id,blob_data,ts,uid,maybe_nan",
            ],
            python_env=args.python_env,
            extra_env={"PYTHONPATH": str(tmp)},
        )
    if rc != 0:
        print(f"  [FAIL] expected rc=0, got {rc}; stderr: {err[:300]!r}")
        return False
    payload = _parse_json_or_fail(out, "fakes serialization")
    if payload is None:
        return False
    rows = payload.get("rows", [])
    if not rows:
        print("  [FAIL] no rows returned from synthetic FakeWeirdRow")
        return False
    row = rows[0]
    # bytes → {_unserializable, type, length}
    blob = row.get("blob_data")
    if not (isinstance(blob, dict) and blob.get("type") == "bytes"
            and blob.get("length") == 4):
        print(f"  [FAIL] bytes serialization drift: {blob!r}")
        return False
    # datetime → ISO-8601 string
    ts = row.get("ts")
    if not (isinstance(ts, str) and "T" in ts and ts.startswith("2026-04-27")):
        print(f"  [FAIL] datetime serialization drift: {ts!r}")
        return False
    # uuid.UUID → string
    uid = row.get("uid")
    if uid != "00000000-0000-0000-0000-000000000001":
        print(f"  [FAIL] UUID serialization drift: {uid!r}")
        return False
    # NaN float → {_unserializable, type, value}
    nan_val = row.get("maybe_nan")
    if not (isinstance(nan_val, dict) and nan_val.get("type") == "float"
            and nan_val.get("value") == "nan"):
        print(f"  [FAIL] NaN float serialization drift: {nan_val!r}")
        return False
    # Strict-JSON round-trip: payload must reparse with allow_nan=False.
    try:
        json.loads(json.dumps(payload, allow_nan=False))
    except ValueError as exc:
        print(f"  [FAIL] payload is not strict-JSON: {exc}")
        return False
    print(
        "  [ok] fakes sandbox: bytes / datetime / UUID / NaN values "
        "serialize to documented envelopes; strict-JSON round-trip clean"
    )
    return True


def fixture_c_fakes_nan_restriction_refused(
    args: argparse.Namespace,
) -> bool:
    """``--key x=nan`` is refused at parse time (not echoed into restriction).

    DataJoint cannot generate a NaN comparison anyway, and ``json.dumps``
    emits ``NaN`` as a non-strict literal — both reasons to refuse at
    the parser. Pure parser test, no live DB needed.
    """
    rc, out, _ = _run_db_graph(
        [
            "find-instance",
            "--class",
            "json:JSONDecoder",
            "--key",
            "x=nan",
        ],
        python_env=args.python_env,
    )
    if rc != 2:
        print(f"  [FAIL] expected rc=2, got {rc}")
        return False
    payload = _parse_json_or_fail(out, "nan-restriction payload")
    if payload is None:
        return False
    error = payload.get("error", {})
    if error.get("kind") != "non_finite_restriction":
        print(
            f"  [FAIL] error.kind != 'non_finite_restriction': "
            f"{error!r}"
        )
        return False
    # Strict-JSON round-trip the payload itself — the rejection path
    # must not leak NaN into its own response.
    try:
        json.loads(json.dumps(payload, allow_nan=False))
    except ValueError as exc:
        print(f"  [FAIL] rejection payload is not strict-JSON: {exc}")
        return False
    print(
        "  [ok] --key field=nan refused at parse time with kind="
        "'non_finite_restriction'; rejection payload is strict-JSON"
    )
    return True


def _write_fake_merge_module(target: Path) -> None:
    """Write a synthetic Master + Part module to ``target``.

    The Part has ``master = MasterMerge`` set explicitly (DataJoint sets
    this automatically on Part subclasses, but the fake datajoint shim
    does not auto-wire it). Each part row carries a master_key field
    (here ``merge_id``) plus the part-only restriction field
    (``nwb_file_name``); each master row has just the merge_id.
    """
    (target / "fakemerge.py").write_text(
        "\n".join(
            [
                '"""Synthetic Master + Part for merge-aware fixtures."""',
                "from datajoint import Manual, Part",
                "from fakes import FakeHeading, FakeRelation",
                "",
                "",
                "class MasterMerge(Manual):",
                "    _heading_obj = FakeHeading(",
                "        primary_key=('merge_id',),",
                "        names=('merge_id', 'source'),",
                "        attributes={",
                "            'merge_id': 'uuid',",
                "            'source': 'varchar(32)',",
                "        },",
                "    )",
                "    _rows = [",
                "        {'merge_id': 'm-1', 'source': 'PartA'},",
                "        {'merge_id': 'm-2', 'source': 'PartA'},",
                "        {'merge_id': 'm-3', 'source': 'PartA'},",
                "    ]",
                "",
                "    def __new__(cls):",
                "        return FakeRelation(",
                "            heading=cls._heading_obj, rows=cls._rows",
                "        )",
                "",
                "    @property",
                "    def heading(self):",
                "        return self._heading_obj",
                "",
                "",
                "class PartA(Part):",
                "    master = MasterMerge",
                "    _heading_obj = FakeHeading(",
                "        primary_key=('merge_id',),",
                "        names=('merge_id', 'nwb_file_name', 'epoch'),",
                "        attributes={",
                "            'merge_id': 'uuid',",
                "            'nwb_file_name': 'varchar(64)',",
                "            'epoch': 'varchar(32)',",
                "        },",
                "    )",
                "    _rows = [",
                "        {'merge_id': 'm-1', 'nwb_file_name': 'a.nwb', 'epoch': '01'},",
                "        {'merge_id': 'm-2', 'nwb_file_name': 'a.nwb', 'epoch': '02'},",
                "        {'merge_id': 'm-3', 'nwb_file_name': 'b.nwb', 'epoch': '01'},",
                "    ]",
                "",
                "    def __new__(cls):",
                "        return FakeRelation(",
                "            heading=cls._heading_obj, rows=cls._rows",
                "        )",
                "",
                "    @property",
                "    def heading(self):",
                "        return self._heading_obj",
                "",
            ]
        )
    )


def fixture_d_fakes_merge_routes_part_only_field_to_part(
    args: argparse.Namespace,
) -> bool:
    """Eval-#14/15/16 shape: ``--merge-master M --part P --key part_only=X``.

    The user supplies a key (``nwb_file_name``) that exists only on the
    Part heading, not the Master. Without merge-aware routing, DataJoint
    would silently drop the key when applied to the Master and return
    the whole master table — the canonical wrong-count footgun.

    Merge mode applies the restriction to the Part, fetches the master
    keys (``merge_id``) from the restricted part, and queries the
    master by those resolved keys. The fixture asserts:

    * ``kind: "merge"``, exit 0.
    * ``merge.restriction_applied_to == "part"``.
    * ``merge.master_key_fields == ["merge_id"]``.
    * ``merge.merge_ids`` lists the part-resolved master keys.
    * ``rows`` are master rows for those merge_ids.
    """
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        import fakes as _fakes_module

        _fakes_module.prepare_sandbox(tmp)
        _write_fake_merge_module(tmp)
        rc, out, err = _run_db_graph(
            [
                "find-instance",
                "--import",
                "fakemerge",
                "--merge-master",
                "fakemerge:MasterMerge",
                "--part",
                "fakemerge:PartA",
                "--key",
                "nwb_file_name=a.nwb",
                "--fields",
                "KEY",
            ],
            python_env=args.python_env,
            extra_env={"PYTHONPATH": str(tmp)},
        )
    if rc != 0:
        print(f"  [FAIL] expected rc=0, got {rc}; stderr: {err[:300]!r}")
        return False
    payload = _parse_json_or_fail(out, "merge routing payload")
    if payload is None:
        return False
    if payload.get("kind") != "merge":
        print(f"  [FAIL] kind != 'merge': {payload.get('kind')!r}")
        return False
    merge = payload.get("merge", {})
    if merge.get("restriction_applied_to") != "part":
        print(
            f"  [FAIL] merge.restriction_applied_to != 'part': "
            f"{merge.get('restriction_applied_to')!r}"
        )
        return False
    if merge.get("master_key_fields") != ["merge_id"]:
        print(
            f"  [FAIL] merge.master_key_fields drift: "
            f"{merge.get('master_key_fields')!r}"
        )
        return False
    merge_ids = merge.get("merge_ids", [])
    resolved_ids = sorted(r.get("merge_id") for r in merge_ids)
    # The synthetic part has two rows with nwb_file_name=a.nwb (m-1, m-2).
    if resolved_ids != ["m-1", "m-2"]:
        print(f"  [FAIL] merge_ids drift: {resolved_ids!r}")
        return False
    rows = payload.get("rows", [])
    row_ids = sorted(r.get("merge_id") for r in rows)
    if row_ids != ["m-1", "m-2"]:
        print(f"  [FAIL] master rows drift: {row_ids!r}")
        return False
    if payload.get("count") != 2:
        print(f"  [FAIL] count != 2: {payload.get('count')!r}")
        return False
    print(
        "  [ok] merge mode: part-only key routed to part, master "
        "queried by resolved merge_ids"
    )
    return True


def fixture_d_fakes_merge_count_unbounded_by_limit(
    args: argparse.Namespace,
) -> bool:
    """Merge ``--count`` reports the TRUE count, not a page-limited count.

    150 part rows match the restriction. With default ``--limit 100``,
    the failure mode this fixture pins is paginating part keys to 100,
    then counting master rows reachable from that bounded key set —
    which would silently report ``count: 100`` (wrong-count footgun).
    The expected behavior is to compute count DB-side from the FULL
    restricted part, so ``count == 150`` regardless of ``--limit``.
    """
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        import fakes as _fakes_module

        _fakes_module.prepare_sandbox(tmp)

        master_rows = ", ".join(
            f"{{'merge_id': 'm-{i:03d}', 'source': 'PartA'}}"
            for i in range(150)
        )
        part_rows = ", ".join(
            f"{{'merge_id': 'm-{i:03d}', "
            "'subject_id': 'aj80', 'epoch': '01'}"
            for i in range(150)
        )
        (tmp / "fakemerge_big.py").write_text(
            "\n".join(
                [
                    "from datajoint import Manual, Part",
                    "from fakes import FakeHeading, FakeRelation",
                    "",
                    "class MasterMerge(Manual):",
                    "    _heading_obj = FakeHeading(",
                    "        primary_key=('merge_id',),",
                    "        names=('merge_id', 'source'),",
                    "        attributes={"
                    "'merge_id': 'uuid', 'source': 'varchar(32)'},",
                    "    )",
                    f"    _rows = [{master_rows}]",
                    "    def __new__(cls):",
                    "        return FakeRelation("
                    "heading=cls._heading_obj, rows=cls._rows)",
                    "    @property",
                    "    def heading(self):",
                    "        return self._heading_obj",
                    "",
                    "class PartA(Part):",
                    "    master = MasterMerge",
                    "    _heading_obj = FakeHeading(",
                    "        primary_key=('merge_id',),",
                    "        names=('merge_id', 'subject_id', 'epoch'),",
                    "        attributes={",
                    "            'merge_id': 'uuid',",
                    "            'subject_id': 'varchar(8)',",
                    "            'epoch': 'varchar(32)',",
                    "        },",
                    "    )",
                    f"    _rows = [{part_rows}]",
                    "    def __new__(cls):",
                    "        return FakeRelation("
                    "heading=cls._heading_obj, rows=cls._rows)",
                    "    @property",
                    "    def heading(self):",
                    "        return self._heading_obj",
                ]
            )
        )

        rc_count, out_count, err_count = _run_db_graph(
            [
                "find-instance",
                "--import",
                "fakemerge_big",
                "--merge-master",
                "fakemerge_big:MasterMerge",
                "--part",
                "fakemerge_big:PartA",
                "--key",
                "subject_id=aj80",
                "--count",
            ],
            python_env=args.python_env,
            extra_env={"PYTHONPATH": str(tmp)},
        )
        rc_rows, out_rows, err_rows = _run_db_graph(
            [
                "find-instance",
                "--import",
                "fakemerge_big",
                "--merge-master",
                "fakemerge_big:MasterMerge",
                "--part",
                "fakemerge_big:PartA",
                "--key",
                "subject_id=aj80",
                "--fields",
                "KEY",
            ],
            python_env=args.python_env,
            extra_env={"PYTHONPATH": str(tmp)},
        )

    if rc_count != 0 or rc_rows != 0:
        print(
            f"  [FAIL] expected rc=0, got count rc={rc_count} "
            f"({err_count[:200]!r}); rows rc={rc_rows} "
            f"({err_rows[:200]!r})"
        )
        return False
    payload_count = _parse_json_or_fail(out_count, "merge --count payload")
    payload_rows = _parse_json_or_fail(out_rows, "merge rows payload")
    if payload_count is None or payload_rows is None:
        return False
    if payload_count.get("count") != 150:
        print(
            f"  [FAIL] --count: expected 150, got "
            f"{payload_count.get('count')!r} (page-limited count footgun)"
        )
        return False
    if payload_rows.get("count") != 150:
        print(
            f"  [FAIL] rows mode: expected count=150 (true count), got "
            f"{payload_rows.get('count')!r}"
        )
        return False
    rows = payload_rows.get("rows", [])
    if len(rows) != 100:
        print(
            f"  [FAIL] rows mode: expected len(rows)==100 (page bound), "
            f"got {len(rows)}"
        )
        return False
    if not payload_rows.get("truncated"):
        print(
            f"  [FAIL] rows mode: expected truncated=True, got "
            f"{payload_rows.get('truncated')!r}"
        )
        return False
    print(
        "  [ok] merge --count: 150 (true count); rows mode: count=150, "
        "len(rows)=100, truncated=true"
    )
    return True


def fixture_d_fakes_merge_ids_dedup_when_part_rows_share_master(
    args: argparse.Namespace,
) -> bool:
    """``merge.merge_ids`` is a SET of master keys, deduped on master-key
    tuple. A part can have its own primary key in addition to the
    master FK, so multiple part rows often share the same master key.
    The payload must NOT echo the part-row count under ``merge_ids`` —
    otherwise an LLM treating ``len(merge_ids)`` as "distinct master
    rows" would over-count.

    Fixture has 3 part rows pointing at 2 distinct master keys
    (m-1×2, m-2×1). Expectation: ``count == 2``, ``len(rows) == 2``,
    ``len(merge_ids) == 2`` (deduped).
    """
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        import fakes as _fakes_module

        _fakes_module.prepare_sandbox(tmp)
        (tmp / "fakemerge_dup.py").write_text(
            "\n".join(
                [
                    "from datajoint import Manual, Part",
                    "from fakes import FakeHeading, FakeRelation",
                    "",
                    "class MasterMerge(Manual):",
                    "    _heading_obj = FakeHeading(",
                    "        primary_key=('merge_id',),",
                    "        names=('merge_id', 'source'),",
                    "        attributes={"
                    "'merge_id': 'uuid', 'source': 'varchar(32)'},",
                    "    )",
                    "    _rows = [",
                    "        {'merge_id': 'm-1', 'source': 'PartA'},",
                    "        {'merge_id': 'm-2', 'source': 'PartA'},",
                    "    ]",
                    "    def __new__(cls):",
                    "        return FakeRelation("
                    "heading=cls._heading_obj, rows=cls._rows)",
                    "    @property",
                    "    def heading(self):",
                    "        return self._heading_obj",
                    "",
                    "class PartA(Part):",
                    "    master = MasterMerge",
                    "    _heading_obj = FakeHeading(",
                    "        primary_key=('merge_id', 'epoch'),",
                    "        names=('merge_id', 'subject_id', 'epoch'),",
                    "        attributes={",
                    "            'merge_id': 'uuid',",
                    "            'subject_id': 'varchar(8)',",
                    "            'epoch': 'varchar(32)',",
                    "        },",
                    "    )",
                    "    _rows = [",
                    "        {'merge_id': 'm-1', 'subject_id': 'aj80', "
                    "'epoch': '01'},",
                    "        {'merge_id': 'm-1', 'subject_id': 'aj80', "
                    "'epoch': '02'},",
                    "        {'merge_id': 'm-2', 'subject_id': 'aj80', "
                    "'epoch': '01'},",
                    "    ]",
                    "    def __new__(cls):",
                    "        return FakeRelation("
                    "heading=cls._heading_obj, rows=cls._rows)",
                    "    @property",
                    "    def heading(self):",
                    "        return self._heading_obj",
                ]
            )
        )
        rc, out, err = _run_db_graph(
            [
                "find-instance",
                "--import",
                "fakemerge_dup",
                "--merge-master",
                "fakemerge_dup:MasterMerge",
                "--part",
                "fakemerge_dup:PartA",
                "--key",
                "subject_id=aj80",
                "--fields",
                "KEY",
            ],
            python_env=args.python_env,
            extra_env={"PYTHONPATH": str(tmp)},
        )
    if rc != 0:
        print(f"  [FAIL] expected rc=0, got {rc}; stderr: {err[:200]!r}")
        return False
    payload = _parse_json_or_fail(out, "merge dedup payload")
    if payload is None:
        return False
    if payload.get("count") != 2:
        print(
            f"  [FAIL] count != 2 (distinct master rows): "
            f"{payload.get('count')!r}"
        )
        return False
    rows = payload.get("rows", [])
    if len(rows) != 2:
        print(f"  [FAIL] len(rows) != 2: {len(rows)}")
        return False
    merge_ids = payload.get("merge", {}).get("merge_ids", [])
    if len(merge_ids) != 2:
        print(
            f"  [FAIL] merge_ids must be deduped to 2 (m-1, m-2), "
            f"got {len(merge_ids)}: {merge_ids!r}"
        )
        return False
    resolved_ids = sorted(r.get("merge_id") for r in merge_ids)
    if resolved_ids != ["m-1", "m-2"]:
        print(f"  [FAIL] merge_ids drift: {resolved_ids!r}")
        return False
    print(
        "  [ok] merge_ids deduped on master-key tuple "
        "(3 part rows → 2 distinct master keys)"
    )
    return True


def fixture_d_fakes_merge_rows_pagination_dedupes_master_keys(
    args: argparse.Namespace,
) -> bool:
    """Merge ``rows`` mode paginates DISTINCT master keys, not raw part
    rows. A duplicate-heavy part can otherwise hide distinct master
    IDs that would have fit under ``--limit``.

    Fixture: 150 part rows for ``m-1`` followed by a single part row
    for ``m-2``. With the old behavior, paginating raw part rows
    fills the page with m-1 (limit=100) and silently drops m-2 from
    the user-visible rows / merge_ids. Expectation:

    * ``count == 2`` (true distinct master count).
    * ``len(rows) == 2`` (both m-1 and m-2 returned).
    * ``len(merge_ids) == 2`` (both deduped master keys).
    * ``truncated`` is False because the distinct master set fits.
    """
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        import fakes as _fakes_module

        _fakes_module.prepare_sandbox(tmp)
        part_rows = ", ".join(
            [
                f"{{'merge_id': 'm-1', 'subject_id': 'aj80', "
                f"'epoch': '{i:02d}'}}"
                for i in range(150)
            ]
            + [
                "{'merge_id': 'm-2', 'subject_id': 'aj80', 'epoch': '01'}"
            ]
        )
        (tmp / "fakemerge_skew.py").write_text(
            "\n".join(
                [
                    "from datajoint import Manual, Part",
                    "from fakes import FakeHeading, FakeRelation",
                    "",
                    "class MasterMerge(Manual):",
                    "    _heading_obj = FakeHeading(",
                    "        primary_key=('merge_id',),",
                    "        names=('merge_id',),",
                    "        attributes={'merge_id': 'uuid'},",
                    "    )",
                    "    _rows = [",
                    "        {'merge_id': 'm-1'}, {'merge_id': 'm-2'},",
                    "    ]",
                    "    def __new__(cls):",
                    "        return FakeRelation("
                    "heading=cls._heading_obj, rows=cls._rows)",
                    "    @property",
                    "    def heading(self):",
                    "        return self._heading_obj",
                    "",
                    "class PartA(Part):",
                    "    master = MasterMerge",
                    "    _heading_obj = FakeHeading(",
                    "        primary_key=('merge_id', 'epoch'),",
                    "        names=('merge_id', 'subject_id', 'epoch'),",
                    "        attributes={",
                    "            'merge_id': 'uuid',",
                    "            'subject_id': 'varchar(8)',",
                    "            'epoch': 'varchar(32)',",
                    "        },",
                    "    )",
                    f"    _rows = [{part_rows}]",
                    "    def __new__(cls):",
                    "        return FakeRelation("
                    "heading=cls._heading_obj, rows=cls._rows)",
                    "    @property",
                    "    def heading(self):",
                    "        return self._heading_obj",
                ]
            )
        )
        rc, out, err = _run_db_graph(
            [
                "find-instance",
                "--import",
                "fakemerge_skew",
                "--merge-master",
                "fakemerge_skew:MasterMerge",
                "--part",
                "fakemerge_skew:PartA",
                "--key",
                "subject_id=aj80",
                "--fields",
                "KEY",
            ],
            python_env=args.python_env,
            extra_env={"PYTHONPATH": str(tmp)},
        )
    if rc != 0:
        print(f"  [FAIL] expected rc=0, got {rc}; stderr: {err[:200]!r}")
        return False
    payload = _parse_json_or_fail(out, "merge skew payload")
    if payload is None:
        return False
    if payload.get("count") != 2:
        print(f"  [FAIL] count != 2: {payload.get('count')!r}")
        return False
    rows = payload.get("rows", [])
    row_ids = sorted({r.get("merge_id") for r in rows})
    if row_ids != ["m-1", "m-2"]:
        print(
            f"  [FAIL] rows hide distinct master IDs: row_ids={row_ids!r}"
        )
        return False
    merge_ids = payload.get("merge", {}).get("merge_ids", [])
    mid_values = sorted({m.get("merge_id") for m in merge_ids})
    if mid_values != ["m-1", "m-2"]:
        print(
            f"  [FAIL] merge_ids hide distinct master IDs: {mid_values!r}"
        )
        return False
    if payload.get("truncated"):
        print(
            f"  [FAIL] distinct master set fits under --limit; "
            f"truncated should be False, got "
            f"{payload.get('truncated')!r}"
        )
        return False
    print(
        "  [ok] merge rows mode paginates distinct master keys "
        "(150×m-1 + 1×m-2 → both surfaced under default --limit)"
    )
    return True


def fixture_c_keyjson_non_finite_value_refused(
    args: argparse.Namespace,
) -> bool:
    """``--key-json`` rejects NaN, Infinity, ``-Infinity``, and overflow
    literals (``1e999``) at any depth.

    ``json.loads`` accepts these by default, but the tool's contract is
    strict-JSON end-to-end and DataJoint cannot restrict on non-finite
    floats. Pin all four shapes so a future relaxation cannot let
    non-finite values through silently.
    """
    cases = [
        ("x=NaN", "NaN"),
        ("x=Infinity", "Infinity"),
        ("x=-Infinity", "-Infinity"),
        ("x=1e999", "overflow literal 1e999"),
        ('x={"nested":NaN}', "nested NaN"),
    ]
    for value, label in cases:
        rc, out, _ = _run_db_graph(
            [
                "find-instance",
                "--class",
                "json:JSONDecoder",
                "--key-json",
                value,
            ],
            python_env=args.python_env,
        )
        if rc != 2:
            print(f"  [FAIL] {label}: expected rc=2, got {rc}")
            return False
        payload = _parse_json_or_fail(out, f"non-finite payload for {label}")
        if payload is None:
            return False
        if payload.get("error", {}).get("kind") != "non_finite_restriction":
            print(
                f"  [FAIL] {label}: error.kind != 'non_finite_restriction': "
                f"{payload.get('error', {})!r}"
            )
            return False
    print(
        "  [ok] --key-json refuses NaN / Infinity / -Infinity / 1e999 / "
        "nested NaN with kind=non_finite_restriction"
    )
    return True


def fixture_c_fakes_nested_non_finite_in_fetched_rows_envelopes(
    args: argparse.Namespace,
) -> bool:
    """Fetched values that are nested dicts/lists containing NaN or Inf
    must get the same ``_unserializable`` envelope as top-level
    non-finite scalars. Otherwise the payload emits non-strict
    ``NaN`` / ``Infinity`` literals and breaks LLM consumers piping
    through ``json.loads(..., parse_constant=...)`` or
    ``json.dumps(..., allow_nan=False)`` parsers.

    Fixture has one row with ``payload = {"nested": NaN}`` and
    ``arr = [1, Infinity]``. Expectations:

    * rc=0 (per-field substitution must not abort the payload).
    * The emitted JSON round-trips through
      ``json.dumps(..., allow_nan=False)`` (the strict-JSON contract).
    * ``rows[0]['payload']['nested']`` and ``rows[0]['arr'][1]`` are
      both the structured envelope (``_unserializable: true``,
      ``type: "float"``).
    """
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        import fakes as _fakes_module

        _fakes_module.prepare_sandbox(tmp)
        (tmp / "fakenest.py").write_text(
            "\n".join(
                [
                    "from datajoint import Manual",
                    "from fakes import FakeHeading, FakeRelation",
                    "",
                    "class T(Manual):",
                    "    _heading_obj = FakeHeading(",
                    "        primary_key=('id',),",
                    "        names=('id', 'payload', 'arr'),",
                    "        attributes={",
                    "            'id': 'int',",
                    "            'payload': 'longblob',",
                    "            'arr': 'longblob',",
                    "        },",
                    "    )",
                    "    _rows = [",
                    "        {'id': 1,",
                    "         'payload': {'nested': float('nan')},",
                    "         'arr': [1, float('inf')]},",
                    "    ]",
                    "    def __new__(cls):",
                    "        return FakeRelation("
                    "heading=cls._heading_obj, rows=cls._rows)",
                    "    @property",
                    "    def heading(self):",
                    "        return self._heading_obj",
                ]
            )
        )
        rc, out, err = _run_db_graph(
            [
                "find-instance",
                "--import",
                "fakenest",
                "--class",
                "fakenest:T",
                "--fields",
                "id,payload,arr",
            ],
            python_env=args.python_env,
            extra_env={"PYTHONPATH": str(tmp)},
        )
    if rc != 0:
        print(
            f"  [FAIL] expected rc=0, got {rc}; stderr: {err[:200]!r}"
        )
        return False
    payload = _parse_json_or_fail(out, "nested non-finite payload")
    if payload is None:
        return False
    # Strict-JSON round-trip: this fails if any NaN / Inf leaked through.
    try:
        json.dumps(payload, allow_nan=False)
    except ValueError as exc:
        print(f"  [FAIL] payload is not strict JSON: {exc}")
        return False
    rows = payload.get("rows", [])
    if not rows:
        print(f"  [FAIL] expected 1 row, got {len(rows)}")
        return False
    nested = rows[0].get("payload", {}).get("nested")
    arr = rows[0].get("arr", [])
    if not (
        isinstance(nested, dict)
        and nested.get("_unserializable")
        and nested.get("type") == "float"
    ):
        print(
            f"  [FAIL] nested NaN not enveloped: {nested!r}"
        )
        return False
    if len(arr) < 2:
        print(f"  [FAIL] arr too short: {arr!r}")
        return False
    second = arr[1]
    if not (
        isinstance(second, dict)
        and second.get("_unserializable")
        and second.get("type") == "float"
    ):
        print(
            f"  [FAIL] list-nested Inf not enveloped: {second!r}"
        )
        return False
    print(
        "  [ok] nested NaN/Inf inside dict and list payloads "
        "envelope-substituted; payload round-trips strict JSON"
    )
    return True


def fixture_c_fakes_blob_dict_with_non_string_keys_envelopes(
    args: argparse.Namespace,
) -> bool:
    """Fetched dict values whose keys are not JSON-safe scalars
    (``str / int / float / bool / None``) get the structured
    ``_unserializable`` envelope rather than crashing the payload at
    ``json.dumps`` time.

    DataJoint longblob values can deserialize arbitrary Python objects
    (tuples, frozensets, custom classes), so a single bad key would
    otherwise abort serialization for the whole row with
    ``TypeError: keys must be str, int, float, bool or None, not
    tuple``. Pin the envelope shape so a future refactor cannot
    quietly regress to recursing into non-JSON-safe keys.
    """
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        import fakes as _fakes_module

        _fakes_module.prepare_sandbox(tmp)
        (tmp / "fakebadkey.py").write_text(
            "\n".join(
                [
                    "from datajoint import Manual",
                    "from fakes import FakeHeading, FakeRelation",
                    "",
                    "class T(Manual):",
                    "    _heading_obj = FakeHeading(",
                    "        primary_key=('id',),",
                    "        names=('id', 'payload'),",
                    "        attributes={",
                    "            'id': 'int',",
                    "            'payload': 'longblob',",
                    "        },",
                    "    )",
                    "    _rows = [",
                    "        {'id': 1, 'payload': {('a', 'b'): 3}},",
                    "    ]",
                    "    def __new__(cls):",
                    "        return FakeRelation("
                    "heading=cls._heading_obj, rows=cls._rows)",
                    "    @property",
                    "    def heading(self):",
                    "        return self._heading_obj",
                ]
            )
        )
        rc, out, err = _run_db_graph(
            [
                "find-instance",
                "--import",
                "fakebadkey",
                "--class",
                "fakebadkey:T",
                "--fields",
                "id,payload",
            ],
            python_env=args.python_env,
            extra_env={"PYTHONPATH": str(tmp)},
        )
    if rc != 0:
        print(
            f"  [FAIL] expected rc=0, got {rc}; stderr: {err[:200]!r}"
        )
        return False
    payload = _parse_json_or_fail(out, "tuple-key dict payload")
    if payload is None:
        return False
    rows = payload.get("rows", [])
    if not rows:
        print("  [FAIL] expected 1 row, got 0")
        return False
    p = rows[0].get("payload")
    if not (
        isinstance(p, dict)
        and p.get("_unserializable")
        and p.get("type") == "dict"
    ):
        print(
            f"  [FAIL] tuple-key dict not enveloped: {p!r}"
        )
        return False
    if "tuple" not in p.get("key_types", []):
        print(
            f"  [FAIL] envelope key_types should include 'tuple': "
            f"{p!r}"
        )
        return False
    print(
        "  [ok] dict with non-JSON-safe keys envelope-substituted "
        "with type=dict + key_types=['tuple']"
    )
    return True


def fixture_d_fakes_merge_master_only_field_silent_no_op_refused(
    args: argparse.Namespace,
) -> bool:
    """Eval #50 footgun: master-class restricted by part-only field is refused.

    Without ``--merge-master``/``--part``, the user's
    ``--class MasterMerge --key nwb_file_name=X`` would silently drop the
    nwb_file_name restriction (because that field is not on the master
    heading) and return the whole master table — the canonical
    silent-wrong-count footgun. Field validation in Batch C closes
    this: kind=invalid_query, error.kind=unknown_field, exit 2.
    """
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        import fakes as _fakes_module

        _fakes_module.prepare_sandbox(tmp)
        _write_fake_merge_module(tmp)
        rc, out, err = _run_db_graph(
            [
                "find-instance",
                "--import",
                "fakemerge",
                "--class",
                "fakemerge:MasterMerge",
                "--key",
                "nwb_file_name=a.nwb",
            ],
            python_env=args.python_env,
            extra_env={"PYTHONPATH": str(tmp)},
        )
    if rc != 2:
        print(f"  [FAIL] expected rc=2, got {rc}; stderr: {err[:200]!r}")
        return False
    payload = _parse_json_or_fail(out, "silent_no_op refusal payload")
    if payload is None:
        return False
    if payload.get("kind") != "invalid_query":
        print(f"  [FAIL] kind != 'invalid_query': {payload.get('kind')!r}")
        return False
    if payload.get("error", {}).get("kind") != "unknown_field":
        print(
            f"  [FAIL] error.kind != 'unknown_field': "
            f"{payload.get('error', {})!r}"
        )
        return False
    print(
        "  [ok] eval #50 footgun: master-class restricted by part-only "
        "field exits 2 with kind=invalid_query"
    )
    return True


def fixture_d_fakes_merge_part_master_mismatch_exits_3(
    args: argparse.Namespace,
) -> bool:
    """``--merge-master`` disagreeing with ``part.master`` exits 3.

    The synthetic Part declares ``master = MasterMerge``. If the user
    supplies a different class as ``--merge-master``, the algorithm
    must refuse rather than silently use the user's pick — the user
    likely chose the wrong master.
    """
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        import fakes as _fakes_module

        _fakes_module.prepare_sandbox(tmp)
        _write_fake_merge_module(tmp)
        # Add a second master that PartA does NOT point at; supply it
        # to --merge-master to trigger the mismatch.
        (tmp / "fakemerge_other_master.py").write_text(
            "\n".join(
                [
                    "from datajoint import Manual",
                    "from fakes import FakeHeading, FakeRelation",
                    "",
                    "",
                    "class OtherMaster(Manual):",
                    "    _heading_obj = FakeHeading(",
                    "        primary_key=('merge_id',),",
                    "        names=('merge_id',),",
                    "        attributes={'merge_id': 'uuid'},",
                    "    )",
                    "    _rows = []",
                    "",
                    "    def __new__(cls):",
                    "        return FakeRelation(",
                    "            heading=cls._heading_obj, rows=cls._rows",
                    "        )",
                    "",
                    "    @property",
                    "    def heading(self):",
                    "        return self._heading_obj",
                    "",
                ]
            )
        )
        rc, out, _ = _run_db_graph(
            [
                "find-instance",
                "--import",
                "fakemerge",
                "--import",
                "fakemerge_other_master",
                "--merge-master",
                "fakemerge_other_master:OtherMaster",
                "--part",
                "fakemerge:PartA",
                "--key",
                "nwb_file_name=a.nwb",
            ],
            python_env=args.python_env,
            extra_env={"PYTHONPATH": str(tmp)},
        )
    if rc != 3:
        print(f"  [FAIL] expected rc=3 (ambiguous), got {rc}")
        return False
    payload = _parse_json_or_fail(out, "merge-mismatch payload")
    if payload is None:
        return False
    if payload.get("kind") != "ambiguous":
        print(f"  [FAIL] kind != 'ambiguous': {payload.get('kind')!r}")
        return False
    hint = payload.get("hint", "")
    if "disagrees" not in hint:
        print(f"  [FAIL] hint should mention disagreement: {hint!r}")
        return False
    print(
        "  [ok] merge-master mismatch with part.master exits 3 "
        "with structural hint"
    )
    return True


def fixture_d_set_op_flags_mutually_exclusive(
    args: argparse.Namespace,
) -> bool:
    """``--intersect`` / ``--except`` / ``--join`` cannot be combined.

    Pins the parser-level rule. Each flag is its own algebra; combining
    them would require a query language to express, which is out of MVP.
    """
    rc, _, err = _run_db_graph(
        [
            "find-instance",
            "--class",
            "json:JSONDecoder",
            "--intersect",
            "Foo",
            "--except",
            "Bar",
        ],
        python_env=args.python_env,
    )
    if rc != 2:
        print(f"  [FAIL] expected rc=2, got {rc}")
        return False
    if "mutually exclusive" not in err:
        print(
            f"  [FAIL] error should mention 'mutually exclusive': "
            f"{err[-200:]!r}"
        )
        return False
    print(
        "  [ok] --intersect + --except (and other set-op pairs) refused "
        "with exit 2 + 'mutually exclusive'"
    )
    return True


def fixture_d_set_op_with_grouping_refused(
    args: argparse.Namespace,
) -> bool:
    """Set ops cannot be combined with --group-by / --group-by-table."""
    rc, _, err = _run_db_graph(
        [
            "find-instance",
            "--class",
            "json:JSONDecoder",
            "--intersect",
            "Foo",
            "--group-by-table",
            "Bar",
            "--count-distinct",
            "x",
        ],
        python_env=args.python_env,
    )
    if rc != 2:
        print(f"  [FAIL] expected rc=2, got {rc}")
        return False
    if "cannot be combined" not in err:
        print(
            f"  [FAIL] error should mention 'cannot be combined': "
            f"{err[-200:]!r}"
        )
        return False
    print("  [ok] set-op + grouping combination refused with exit 2")
    return True


def _write_fake_setop_module(target: Path) -> None:
    """Write a synthetic Left/Right pair for set-op fixtures.

    Both classes share ``id`` and ``label`` fields so intersect / except
    / join are well-defined. Left has 3 rows; Right has 2 rows that
    overlap with Left on (id, label) only for ``id=2``.
    """
    (target / "fakesetop.py").write_text(
        "\n".join(
            [
                '"""Synthetic Left + Right tables for Batch E set-op fixtures."""',
                "from datajoint import Manual",
                "from fakes import FakeHeading, FakeRelation",
                "",
                "",
                "class Left(Manual):",
                "    _heading_obj = FakeHeading(",
                "        primary_key=('id',),",
                "        names=('id', 'label', 'left_only'),",
                "        attributes={",
                "            'id': 'int',",
                "            'label': 'varchar(32)',",
                "            'left_only': 'varchar(64)',",
                "        },",
                "    )",
                "    _rows = [",
                "        {'id': 1, 'label': 'a', 'left_only': 'l1'},",
                "        {'id': 2, 'label': 'b', 'left_only': 'l2'},",
                "        {'id': 3, 'label': 'c', 'left_only': 'l3'},",
                "    ]",
                "",
                "    def __new__(cls):",
                "        return FakeRelation(",
                "            heading=cls._heading_obj, rows=cls._rows",
                "        )",
                "",
                "    @property",
                "    def heading(self):",
                "        return self._heading_obj",
                "",
                "",
                "class Right(Manual):",
                "    _heading_obj = FakeHeading(",
                "        primary_key=('id',),",
                "        names=('id', 'label', 'right_only'),",
                "        attributes={",
                "            'id': 'int',",
                "            'label': 'varchar(32)',",
                "            'right_only': 'varchar(64)',",
                "        },",
                "    )",
                "    _rows = [",
                "        {'id': 2, 'label': 'b', 'right_only': 'r2'},",
                "        {'id': 4, 'label': 'd', 'right_only': 'r4'},",
                "    ]",
                "",
                "    def __new__(cls):",
                "        return FakeRelation(",
                "            heading=cls._heading_obj, rows=cls._rows",
                "        )",
                "",
                "    @property",
                "    def heading(self):",
                "        return self._heading_obj",
                "",
                "",
                "class Disjoint(Manual):",
                "    _heading_obj = FakeHeading(",
                "        primary_key=('foreign_key',),",
                "        names=('foreign_key',),",
                "        attributes={'foreign_key': 'varchar(32)'},",
                "    )",
                "    _rows = []",
                "",
                "    def __new__(cls):",
                "        return FakeRelation(",
                "            heading=cls._heading_obj, rows=cls._rows",
                "        )",
                "",
                "    @property",
                "    def heading(self):",
                "        return self._heading_obj",
                "",
            ]
        )
    )


def _setup_setop_sandbox(tmp: Path) -> None:
    """Build a sandbox with the fake datajoint and the setop module."""
    import fakes as _fakes_module

    _fakes_module.prepare_sandbox(tmp)
    _write_fake_setop_module(tmp)


def fixture_e_fakes_intersect_returns_shared_keys(
    args: argparse.Namespace,
) -> bool:
    """``--class Left --intersect Right`` returns rows present in both.

    Left has id ∈ {1, 2, 3}; Right has id ∈ {2, 4}. The intersection
    along shared attributes (id, label) is the single row with id=2.
    """
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        _setup_setop_sandbox(tmp)
        rc, out, err = _run_db_graph(
            [
                "find-instance",
                "--import",
                "fakesetop",
                "--class",
                "fakesetop:Left",
                "--intersect",
                "fakesetop:Right",
                "--fields",
                "KEY",
            ],
            python_env=args.python_env,
            extra_env={"PYTHONPATH": str(tmp)},
        )
    if rc != 0:
        print(f"  [FAIL] expected rc=0, got {rc}; stderr: {err[:200]!r}")
        return False
    payload = _parse_json_or_fail(out, "intersect payload")
    if payload is None:
        return False
    query = payload.get("query", {})
    if query.get("set_op") != "intersect":
        print(f"  [FAIL] query.set_op != 'intersect': {query.get('set_op')!r}")
        return False
    if query.get("set_op_form") != "L & R.proj()":
        print(
            f"  [FAIL] query.set_op_form drift: {query.get('set_op_form')!r}"
        )
        return False
    if query.get("class") != "fakesetop:Left":
        print(
            f"  [FAIL] query.class must echo the user's --class "
            f"(fakesetop:Left), got {query.get('class')!r}"
        )
        return False
    rows = payload.get("rows", [])
    ids = sorted(r.get("id") for r in rows)
    if ids != [2]:
        print(f"  [FAIL] intersection rows drift: {ids!r}")
        return False
    print("  [ok] --intersect: id=2 only (the shared row)")
    return True


def fixture_e_fakes_except_returns_left_minus_right(
    args: argparse.Namespace,
) -> bool:
    """``--class Left --except Right`` returns rows in Left but not Right."""
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        _setup_setop_sandbox(tmp)
        rc, out, _ = _run_db_graph(
            [
                "find-instance",
                "--import",
                "fakesetop",
                "--class",
                "fakesetop:Left",
                "--except",
                "fakesetop:Right",
                "--fields",
                "KEY",
            ],
            python_env=args.python_env,
            extra_env={"PYTHONPATH": str(tmp)},
        )
    if rc != 0:
        print(f"  [FAIL] expected rc=0, got {rc}")
        return False
    payload = _parse_json_or_fail(out, "except payload")
    if payload is None:
        return False
    query = payload.get("query", {})
    if query.get("set_op") != "except":
        print(f"  [FAIL] query.set_op != 'except': {query.get('set_op')!r}")
        return False
    if query.get("class") != "fakesetop:Left":
        print(
            f"  [FAIL] query.class must echo the user's --class "
            f"(fakesetop:Left), got {query.get('class')!r}"
        )
        return False
    rows = payload.get("rows", [])
    ids = sorted(r.get("id") for r in rows)
    # Left minus Right (along shared id, label): id 1 and id 3 remain
    # (both have labels not in Right's matching pairs).
    if ids != [1, 3]:
        print(f"  [FAIL] except rows drift: {ids!r}")
        return False
    print("  [ok] --except: id=[1, 3] (Left minus shared)")
    return True


def fixture_e_fakes_join_validates_output_fields(
    args: argparse.Namespace,
) -> bool:
    """``--class Left --join Right --fields ...`` returns the natural join."""
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        _setup_setop_sandbox(tmp)
        rc, out, _ = _run_db_graph(
            [
                "find-instance",
                "--import",
                "fakesetop",
                "--class",
                "fakesetop:Left",
                "--join",
                "fakesetop:Right",
                "--fields",
                "id,label,left_only,right_only",
            ],
            python_env=args.python_env,
            extra_env={"PYTHONPATH": str(tmp)},
        )
    if rc != 0:
        print(f"  [FAIL] expected rc=0, got {rc}")
        return False
    payload = _parse_json_or_fail(out, "join payload")
    if payload is None:
        return False
    query = payload.get("query", {})
    if query.get("set_op") != "join":
        print(f"  [FAIL] query.set_op != 'join': {query.get('set_op')!r}")
        return False
    if query.get("class") != "fakesetop:Left":
        print(
            f"  [FAIL] query.class must echo the user's --class "
            f"(fakesetop:Left), got {query.get('class')!r}"
        )
        return False
    rows = payload.get("rows", [])
    if len(rows) != 1:
        print(f"  [FAIL] join expected 1 row (id=2), got {len(rows)}")
        return False
    row = rows[0]
    if row.get("id") != 2 or row.get("label") != "b":
        print(f"  [FAIL] join row contents drift: {row!r}")
        return False
    if row.get("left_only") != "l2" or row.get("right_only") != "r2":
        print(f"  [FAIL] join did not merge fields from both sides: {row!r}")
        return False
    print("  [ok] --join: id=2 row carries fields from both Left and Right")
    return True


def fixture_e_fakes_intersect_secondary_only_overlap_refused(
    args: argparse.Namespace,
) -> bool:
    """Intersect with only-secondary-field overlap is refused at preflight.

    ``L & R.proj()`` projects R to its primary key, so the actual
    operator's shared-attribute set is ``L.heading.names ∩
    R.heading.primary_key``. A pair sharing only a non-PK field
    (``label``) would pass a naive ``heading.names`` overlap check
    yet fail at query time with an opaque DataJoint error. The
    preflight must use the right overlap — pinned here.
    """
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        import fakes as _fakes_module

        _fakes_module.prepare_sandbox(tmp)
        (tmp / "secondary_share.py").write_text(
            "\n".join(
                [
                    "from datajoint import Manual",
                    "from fakes import FakeHeading, FakeRelation",
                    "",
                    "class A(Manual):",
                    "    _heading_obj = FakeHeading(",
                    "        primary_key=('a_id',),",
                    "        names=('a_id', 'label'),",
                    "        attributes={'a_id': 'int', 'label': 'varchar(32)'},",
                    "    )",
                    "    _rows = [{'a_id': 1, 'label': 'x'}]",
                    "    def __new__(cls):",
                    "        return FakeRelation("
                    "heading=cls._heading_obj, rows=cls._rows)",
                    "    @property",
                    "    def heading(self):",
                    "        return self._heading_obj",
                    "",
                    "class B(Manual):",
                    "    _heading_obj = FakeHeading(",
                    "        primary_key=('b_id',),",
                    "        names=('b_id', 'label'),",
                    "        attributes={'b_id': 'int', 'label': 'varchar(32)'},",
                    "    )",
                    "    _rows = [{'b_id': 99, 'label': 'x'}]",
                    "    def __new__(cls):",
                    "        return FakeRelation("
                    "heading=cls._heading_obj, rows=cls._rows)",
                    "    @property",
                    "    def heading(self):",
                    "        return self._heading_obj",
                    "",
                ]
            )
        )
        rc, out, _ = _run_db_graph(
            [
                "find-instance",
                "--import",
                "secondary_share",
                "--class",
                "secondary_share:A",
                "--intersect",
                "secondary_share:B",
            ],
            python_env=args.python_env,
            extra_env={"PYTHONPATH": str(tmp)},
        )
    if rc != 2:
        print(f"  [FAIL] expected rc=2 (no_shared_attributes), got {rc}")
        return False
    payload = _parse_json_or_fail(out, "secondary-only payload")
    if payload is None:
        return False
    if payload.get("error", {}).get("kind") != "no_shared_attributes":
        print(
            f"  [FAIL] error.kind != 'no_shared_attributes': "
            f"{payload.get('error', {})!r}"
        )
        return False
    print(
        "  [ok] intersect with only-secondary-field overlap refused at "
        "preflight (overlap checked against R.proj()'s PK)"
    )
    return True


def fixture_e_fakes_setop_restriction_routes_to_partner(
    args: argparse.Namespace,
) -> bool:
    """A partner-only --key is applied to R, not the base.

    Restricts ``--join Right --key right_only=r2``: ``right_only`` is
    only on Right's heading. Without narrower-owner routing, the
    restriction would be applied to Left and refused as unknown_field.
    The fixture asserts both the routing
    (``query.restriction_applied_to`` maps the field to "partner")
    and that the join returns the correctly-restricted row.
    """
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        _setup_setop_sandbox(tmp)
        rc, out, err = _run_db_graph(
            [
                "find-instance",
                "--import",
                "fakesetop",
                "--class",
                "fakesetop:Left",
                "--join",
                "fakesetop:Right",
                "--key",
                "right_only=r2",
                "--fields",
                "id,label,left_only,right_only",
            ],
            python_env=args.python_env,
            extra_env={"PYTHONPATH": str(tmp)},
        )
    if rc != 0:
        print(f"  [FAIL] expected rc=0, got {rc}; stderr: {err[:200]!r}")
        return False
    payload = _parse_json_or_fail(out, "partner-routed payload")
    if payload is None:
        return False
    routing = payload.get("query", {}).get("restriction_applied_to", {})
    if routing.get("right_only") != "partner":
        print(
            f"  [FAIL] right_only not routed to partner: {routing!r}"
        )
        return False
    rows = payload.get("rows", [])
    if len(rows) != 1 or rows[0].get("id") != 2:
        print(f"  [FAIL] join+restriction did not narrow to id=2: {rows!r}")
        return False
    print(
        "  [ok] --key right_only=r2 routed to partner; join returned "
        "id=2 only"
    )
    return True


def fixture_e_fakes_setop_failure_carries_set_op_context(
    args: argparse.Namespace,
) -> bool:
    """Failure payloads from set-op invocations carry set-op fields.

    A non-existent partner class triggers a not_found in the resolver.
    The error payload must include ``query.set_op``,
    ``set_op_partner``, and ``set_op_form`` so an LLM can act on
    failed evidence without re-deriving the operation from CLI args.
    """
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        _setup_setop_sandbox(tmp)
        rc, out, _ = _run_db_graph(
            [
                "find-instance",
                "--import",
                "fakesetop",
                "--class",
                "fakesetop:Left",
                "--intersect",
                "fakesetop:NonexistentRight",
            ],
            python_env=args.python_env,
            extra_env={"PYTHONPATH": str(tmp)},
        )
    if rc != 4:
        print(f"  [FAIL] expected rc=4 (not_found), got {rc}")
        return False
    payload = _parse_json_or_fail(out, "set-op failure payload")
    if payload is None:
        return False
    query = payload.get("query", {})
    if query.get("set_op") != "intersect":
        print(f"  [FAIL] query.set_op missing: {query!r}")
        return False
    if query.get("set_op_partner") != "fakesetop:NonexistentRight":
        print(f"  [FAIL] query.set_op_partner missing: {query!r}")
        return False
    if query.get("set_op_form") != "L & R.proj()":
        print(
            f"  [FAIL] query.set_op_form drift: "
            f"{query.get('set_op_form')!r}"
        )
        return False
    print(
        "  [ok] set-op failure payload carries set_op + partner + "
        "canonical form"
    )
    return True


def fixture_e_fakes_zero_overlap_set_op_refused(
    args: argparse.Namespace,
) -> bool:
    """A set op with no shared attributes between operands exits 2.

    Plan: zero overlap returns kind=invalid_query / no_shared_attributes.
    Closes the silent-Cartesian-product footgun.
    """
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        _setup_setop_sandbox(tmp)
        rc, out, _ = _run_db_graph(
            [
                "find-instance",
                "--import",
                "fakesetop",
                "--class",
                "fakesetop:Left",
                "--intersect",
                "fakesetop:Disjoint",
            ],
            python_env=args.python_env,
            extra_env={"PYTHONPATH": str(tmp)},
        )
    if rc != 2:
        print(f"  [FAIL] expected rc=2, got {rc}")
        return False
    payload = _parse_json_or_fail(out, "zero-overlap payload")
    if payload is None:
        return False
    if payload.get("kind") != "invalid_query":
        print(f"  [FAIL] kind != 'invalid_query': {payload.get('kind')!r}")
        return False
    if payload.get("error", {}).get("kind") != "no_shared_attributes":
        print(
            f"  [FAIL] error.kind != 'no_shared_attributes': "
            f"{payload.get('error', {})!r}"
        )
        return False
    print(
        "  [ok] zero-overlap intersect refused with kind=invalid_query / "
        "error.kind=no_shared_attributes"
    )
    return True


def _write_fake_grouping_module(target: Path) -> None:
    """Write a synthetic Counted+Grouping pair for grouped-count fixtures.

    ``Electrode`` (counted) has rows tying nwb_file_name + electrode_id
    to electrode_group_name. ``Session`` (grouping) has just
    nwb_file_name. The eval-#19 shape `Session.aggr(Electrode * Session.proj(),
    n_tetrodes='count(distinct electrode_group_name)')` should produce
    one row per matching session with the count.
    """
    (target / "fakegroup.py").write_text(
        "\n".join(
            [
                '"""Synthetic Counted+Grouping for grouped-count fixtures."""',
                "from datajoint import Manual",
                "from fakes import FakeHeading, FakeRelation",
                "",
                "",
                "class Session(Manual):",
                "    _heading_obj = FakeHeading(",
                "        primary_key=('nwb_file_name',),",
                "        names=('nwb_file_name', 'subject_id'),",
                "        attributes={",
                "            'nwb_file_name': 'varchar(64)',",
                "            'subject_id': 'varchar(32)',",
                "        },",
                "    )",
                "    _rows = [",
                "        {'nwb_file_name': 'aj80_d1.nwb', 'subject_id': 'aj80'},",
                "        {'nwb_file_name': 'aj80_d2.nwb', 'subject_id': 'aj80'},",
                "        {'nwb_file_name': 'rat_x.nwb', 'subject_id': 'rat'},",
                "    ]",
                "",
                "    def __new__(cls):",
                "        return FakeRelation(",
                "            heading=cls._heading_obj, rows=cls._rows",
                "        )",
                "",
                "    @property",
                "    def heading(self):",
                "        return self._heading_obj",
                "",
                "",
                "class Electrode(Manual):",
                "    _heading_obj = FakeHeading(",
                "        primary_key=('nwb_file_name', 'electrode_id'),",
                "        names=(",
                "            'nwb_file_name', 'electrode_id',",
                "            'electrode_group_name', 'subject_id',",
                "        ),",
                "        attributes={",
                "            'nwb_file_name': 'varchar(64)',",
                "            'electrode_id': 'int',",
                "            'electrode_group_name': 'varchar(32)',",
                "            'subject_id': 'varchar(32)',",
                "        },",
                "    )",
                "    # aj80_d1: 2 tetrodes (TG1, TG2).",
                "    # aj80_d2: 3 tetrodes (TG1, TG2, TG3). rat_x: 1.",
                "    _rows = [",
                "        {'nwb_file_name': 'aj80_d1.nwb', 'electrode_id': 0, "
                "'electrode_group_name': 'TG1', 'subject_id': 'aj80'},",
                "        {'nwb_file_name': 'aj80_d1.nwb', 'electrode_id': 1, "
                "'electrode_group_name': 'TG1', 'subject_id': 'aj80'},",
                "        {'nwb_file_name': 'aj80_d1.nwb', 'electrode_id': 2, "
                "'electrode_group_name': 'TG2', 'subject_id': 'aj80'},",
                "        {'nwb_file_name': 'aj80_d2.nwb', 'electrode_id': 0, "
                "'electrode_group_name': 'TG1', 'subject_id': 'aj80'},",
                "        {'nwb_file_name': 'aj80_d2.nwb', 'electrode_id': 1, "
                "'electrode_group_name': 'TG2', 'subject_id': 'aj80'},",
                "        {'nwb_file_name': 'aj80_d2.nwb', 'electrode_id': 2, "
                "'electrode_group_name': 'TG3', 'subject_id': 'aj80'},",
                "        {'nwb_file_name': 'rat_x.nwb', 'electrode_id': 0, "
                "'electrode_group_name': 'TG1', 'subject_id': 'rat'},",
                "    ]",
                "",
                "    def __new__(cls):",
                "        return FakeRelation(",
                "            heading=cls._heading_obj, rows=cls._rows",
                "        )",
                "",
                "    @property",
                "    def heading(self):",
                "        return self._heading_obj",
                "",
            ]
        )
    )


def _setup_grouping_sandbox(tmp: Path) -> None:
    import fakes as _fakes_module

    _fakes_module.prepare_sandbox(tmp)
    _write_fake_grouping_module(tmp)


def fixture_e_fakes_group_by_table_eval19_shape(
    args: argparse.Namespace,
) -> bool:
    """Eval #19 shape: per-session distinct electrode-group counts.

    ``--class Electrode --key subject_id=aj80 --group-by-table Session
    --count-distinct electrode_group_name`` should produce one row per
    Session matching the restricted Electrode set:
    aj80_d1 → 2 (TG1, TG2), aj80_d2 → 3 (TG1, TG2, TG3).
    """
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        _setup_grouping_sandbox(tmp)
        rc, out, err = _run_db_graph(
            [
                "find-instance",
                "--import",
                "fakegroup",
                "--class",
                "fakegroup:Electrode",
                "--key",
                "subject_id=aj80",
                "--group-by-table",
                "fakegroup:Session",
                "--count-distinct",
                "electrode_group_name",
            ],
            python_env=args.python_env,
            extra_env={"PYTHONPATH": str(tmp)},
        )
    if rc != 0:
        print(f"  [FAIL] expected rc=0, got {rc}; stderr: {err[:200]!r}")
        return False
    payload = _parse_json_or_fail(out, "grouped_count payload")
    if payload is None:
        return False
    if payload.get("kind") != "grouped_count":
        print(f"  [FAIL] kind != 'grouped_count': {payload.get('kind')!r}")
        return False
    query = payload.get("query", {})
    if query.get("class") != "fakegroup:Electrode":
        print(
            f"  [FAIL] query.class must echo the user's --class "
            f"(fakegroup:Electrode), got {query.get('class')!r}"
        )
        return False
    groups = payload.get("groups", [])
    by_session = {
        g["nwb_file_name"]: g["count_distinct_electrode_group_name"]
        for g in groups
    }
    expected = {"aj80_d1.nwb": 2, "aj80_d2.nwb": 3}
    if by_session != expected:
        print(f"  [FAIL] grouped counts drift: {by_session!r} != {expected!r}")
        return False
    print(
        "  [ok] eval #19 shape: per-session distinct electrode-group "
        f"counts {by_session}"
    )
    return True


def fixture_e_fakes_group_by_explicit_fields(
    args: argparse.Namespace,
) -> bool:
    """``--group-by f1,f2`` form runs the explicit-field aggregation."""
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        _setup_grouping_sandbox(tmp)
        rc, out, _ = _run_db_graph(
            [
                "find-instance",
                "--import",
                "fakegroup",
                "--class",
                "fakegroup:Electrode",
                "--group-by",
                "subject_id",
                "--count-distinct",
                "nwb_file_name",
            ],
            python_env=args.python_env,
            extra_env={"PYTHONPATH": str(tmp)},
        )
    if rc != 0:
        print(f"  [FAIL] expected rc=0, got {rc}")
        return False
    payload = _parse_json_or_fail(out, "explicit grouped_count payload")
    if payload is None:
        return False
    groups = payload.get("groups", [])
    by_subject = {
        g["subject_id"]: g["count_distinct_nwb_file_name"] for g in groups
    }
    # aj80 has 2 distinct nwbs; rat has 1.
    if by_subject != {"aj80": 2, "rat": 1}:
        print(f"  [FAIL] grouped counts drift: {by_subject!r}")
        return False
    print(
        "  [ok] explicit --group-by subject_id: aj80=2, rat=1 distinct nwbs"
    )
    return True


def fixture_e_fakes_count_distinct_field_must_be_on_counted(
    args: argparse.Namespace,
) -> bool:
    """``--count-distinct`` field must exist on the counted relation, not the grouping table."""
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        _setup_grouping_sandbox(tmp)
        rc, out, _ = _run_db_graph(
            [
                "find-instance",
                "--import",
                "fakegroup",
                "--class",
                "fakegroup:Electrode",
                "--group-by-table",
                "fakegroup:Session",
                "--count-distinct",
                "definitely_not_a_field",
            ],
            python_env=args.python_env,
            extra_env={"PYTHONPATH": str(tmp)},
        )
    if rc != 2:
        print(f"  [FAIL] expected rc=2, got {rc}")
        return False
    payload = _parse_json_or_fail(out, "bad count-distinct payload")
    if payload is None:
        return False
    if payload.get("error", {}).get("kind") != "unknown_field":
        print(f"  [FAIL] error.kind != 'unknown_field': {payload.get('error', {})!r}")
        return False
    print(
        "  [ok] --count-distinct unknown field exits 2 with "
        "kind=invalid_query / error.kind=unknown_field"
    )
    return True


def fixture_d_merge_error_payload_carries_merge_context(
    args: argparse.Namespace,
) -> bool:
    """Merge-mode error payloads include merge_master and part fields.

    A failure during merge-mode resolution must surface BOTH the master
    and the part the user named, not just one as ``query.class``. An
    LLM consuming the payload can then re-issue with a corrected pair
    without re-reading the original CLI invocation.
    """
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        import fakes as _fakes_module

        _fakes_module.prepare_sandbox(tmp)
        # Don't write fakemerge.py — both classes will fail to resolve.
        rc, out, _ = _run_db_graph(
            [
                "find-instance",
                "--merge-master",
                "fakemerge:NonexistentMaster",
                "--part",
                "fakemerge:NonexistentPart",
            ],
            python_env=args.python_env,
            extra_env={"PYTHONPATH": str(tmp)},
        )
    if rc != 4:
        print(f"  [FAIL] expected rc=4 (not_found), got {rc}")
        return False
    payload = _parse_json_or_fail(out, "merge error payload")
    if payload is None:
        return False
    query = payload.get("query", {})
    if query.get("class") != "fakemerge:NonexistentMaster":
        print(
            f"  [FAIL] query.class did not fall back to merge_master: "
            f"{query.get('class')!r}"
        )
        return False
    if query.get("merge_master") != "fakemerge:NonexistentMaster":
        print(
            f"  [FAIL] query.merge_master missing: "
            f"{query.get('merge_master')!r}"
        )
        return False
    if query.get("part") != "fakemerge:NonexistentPart":
        print(f"  [FAIL] query.part missing: {query.get('part')!r}")
        return False
    print(
        "  [ok] merge-mode error payload carries class + merge_master + "
        "part"
    )
    return True


def fixture_d_fakes_merge_count_only(args: argparse.Namespace) -> bool:
    """Merge mode + ``--count`` returns count without rows."""
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        import fakes as _fakes_module

        _fakes_module.prepare_sandbox(tmp)
        _write_fake_merge_module(tmp)
        rc, out, _ = _run_db_graph(
            [
                "find-instance",
                "--import",
                "fakemerge",
                "--merge-master",
                "fakemerge:MasterMerge",
                "--part",
                "fakemerge:PartA",
                "--key",
                "nwb_file_name=a.nwb",
                "--count",
            ],
            python_env=args.python_env,
            extra_env={"PYTHONPATH": str(tmp)},
        )
    if rc != 0:
        print(f"  [FAIL] expected rc=0, got {rc}")
        return False
    payload = _parse_json_or_fail(out, "merge count payload")
    if payload is None:
        return False
    if payload.get("count") != 2:
        print(f"  [FAIL] count != 2: {payload.get('count')!r}")
        return False
    if payload.get("rows") != []:
        print(f"  [FAIL] --count must yield empty rows: {payload.get('rows')!r}")
        return False
    if payload.get("query", {}).get("mode") != "count":
        print(
            f"  [FAIL] query.mode != 'count': "
            f"{payload.get('query', {}).get('mode')!r}"
        )
        return False
    print("  [ok] merge mode + --count: count=2, rows=[]")
    return True


def fixture_c_fakes_db_error_classification(
    args: argparse.Namespace,
) -> bool:
    """``LostConnectionError`` from fetch is classified as ``connection``.

    Builds a synthetic table whose fetch raises ``LostConnectionError``;
    db_graph should emit kind=db_error with error.kind=connection. Pins
    the auth-vs-connection split (the M2 fix) on a deterministic path.
    """
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = _setup_fakes_sandbox(
            Path(tmp_str),
            module_name="fakelab_dberr",
            class_name="FakeBroken",
            primary_key=("id",),
            names=("id",),
            attributes={"id": "int"},
            rows=[],
            raises_on_fetch="LostConnectionError",
        )
        rc, out, _ = _run_db_graph(
            [
                "find-instance",
                "--import",
                "fakelab_dberr",
                "--class",
                "fakelab_dberr:FakeBroken",
            ],
            python_env=args.python_env,
            extra_env={"PYTHONPATH": str(tmp)},
        )
    if rc != 5:
        print(f"  [FAIL] expected rc=5 (db_error), got {rc}")
        return False
    payload = _parse_json_or_fail(out, "fakes db_error")
    if payload is None:
        return False
    if payload.get("kind") != "db_error":
        print(f"  [FAIL] kind != 'db_error': {payload.get('kind')!r}")
        return False
    if payload.get("error", {}).get("kind") != "connection":
        print(f"  [FAIL] error.kind != 'connection': {payload.get('error', {})!r}")
        return False
    query = payload.get("query", {})
    if query.get("module") != "fakelab_dberr":
        print(
            f"  [FAIL] resolved-class provenance lost on db_error path: "
            f"{query!r}"
        )
        return False
    print(
        "  [ok] fakes sandbox: LostConnectionError → kind=db_error / "
        "error.kind=connection"
    )
    return True


def fixture_c_no_restrgraph_or_tablechain_in_source(
    _args: argparse.Namespace,
) -> bool:
    """Plan acceptance: find-instance must not invoke RestrGraph / TableChain.

    Uses AST to walk Name and Attribute nodes — string literals
    (docstrings, comments, error-message text) explicitly mention
    ``RestrGraph`` / ``TableChain`` to document the discipline, and a
    naive substring grep would flag those. The AST walker only sees
    actual code references, which is the discipline we care about
    pinning. Plan-cited so a future Batch E author cannot quietly
    delegate to those classes when implementing set operations.
    """
    import ast as _ast

    forbidden = {"RestrGraph", "TableChain"}
    src = _read_db_graph_source()
    tree = _ast.parse(src)
    bad: list[tuple[str, int]] = []
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Name) and node.id in forbidden:
            bad.append((node.id, node.lineno))
        elif isinstance(node, _ast.Attribute) and node.attr in forbidden:
            bad.append((node.attr, node.lineno))
    if bad:
        print(
            f"  [FAIL] db_graph.py source code references "
            f"{[f'{n}@{ln}' for n, ln in bad]!r}; the plan forbids "
            "these in find-instance to keep the direct-relation fast path."
        )
        return False
    print(
        "  [ok] db_graph.py code (excluding docstrings) has no "
        "RestrGraph / TableChain references"
    )
    return True


# DataJoint write methods that have no plausible stdlib analogue at our
# call sites — flagging an attribute call to any of these means we
# accidentally introduced a write path. ``insert`` and ``delete`` are
# excluded from the AST check because both are stdlib container methods
# (``list.insert``, ``set.delete``) and ``sys.path.insert`` is part of
# our standard module bootstrap; flagging them by attribute name alone
# would be a false positive. The plan-required read-only invariant is
# adequately pinned by the unambiguous methods below.
_DJ_WRITE_METHODS = (
    "insert1",
    "delete_quick",
    "drop",
    "drop_quick",
    "populate",
    "alter",
)


def fixture_c_read_only_no_write_method_calls_in_source(
    _args: argparse.Namespace,
) -> bool:
    """Plan #23 / Definition-of-done: read-only invariant pinned in source.

    AST-walks the source and flags any ``Call`` whose target is one of
    the unambiguous DataJoint write methods. Comments and docstrings
    that NAME the methods (the ``security_profile`` block in
    ``info --json``) pass the check because Constant nodes are not Calls.
    Strong signal that no code path mutates the production database.

    See the ``_DJ_WRITE_METHODS`` definition for which methods this
    fixture pins and why ``insert`` / ``delete`` are excluded as
    ambiguous with stdlib container methods.
    """
    import ast as _ast

    src = _read_db_graph_source()
    tree = _ast.parse(src)
    bad: list[tuple[str, int]] = []
    for node in _ast.walk(tree):
        if not isinstance(node, _ast.Call):
            continue
        func = node.func
        if isinstance(func, _ast.Attribute) and func.attr in _DJ_WRITE_METHODS:
            bad.append((func.attr, node.lineno))
        elif isinstance(func, _ast.Name) and func.id in _DJ_WRITE_METHODS:
            bad.append((func.id, node.lineno))
    if bad:
        print(
            f"  [FAIL] db_graph.py contains call-shape references to "
            f"{[f'{n}@{ln}' for n, ln in bad]!r}; the plan declares "
            "find-instance is read-only by construction."
        )
        return False
    print(
        "  [ok] db_graph.py has no call-shape references to DataJoint "
        f"write methods ({', '.join(_DJ_WRITE_METHODS)})"
    )
    return True


def fixture_c_unknown_restriction_field_refused(
    args: argparse.Namespace,
) -> bool:
    """``--key unknown_field=x`` is refused with exit 2 (kind=invalid_query).

    Closes the silent-no-op footgun: DataJoint silently drops
    ``{unknown_field: x}`` from a restriction, returning the whole
    relation; an LLM would mis-cite the result as "filter applied, no
    rows match." Field validation against ``heading.names`` makes the
    error explicit.
    """
    if not _require_capability(
        args, datajoint=True, spyglass=True,
        why="unknown_field validation requires a real Spyglass heading",
    ):
        return True
    rc, out, err = _run_db_graph(
        [
            "find-instance",
            "--class",
            "Session",
            "--key",
            "definitely_not_a_real_field=x",
        ],
        python_env=args.python_env,
    )
    if rc != 2:
        print(f"  [FAIL] expected rc=2 (invalid_query), got {rc}; stderr: {err[:200]!r}")
        return False
    payload = _parse_json_or_fail(out, "unknown_field payload")
    if payload is None:
        return False
    if payload.get("kind") != "invalid_query":
        print(f"  [FAIL] kind != 'invalid_query': {payload.get('kind')!r}")
        return False
    error = payload.get("error", {})
    if error.get("kind") != "unknown_field":
        print(f"  [FAIL] error.kind != 'unknown_field': {error.get('kind')!r}")
        return False
    if "definitely_not_a_real_field" not in error.get("unknown_fields", []):
        print(
            f"  [FAIL] error.unknown_fields missing the bad field: "
            f"{error.get('unknown_fields')!r}"
        )
        return False
    if not error.get("valid_fields"):
        print(
            f"  [FAIL] error.valid_fields should list the heading "
            f"to help recovery: {error.get('valid_fields')!r}"
        )
        return False
    print("  [ok] unknown restriction field exits 2 with kind=invalid_query")
    return True


def fixture_c_blob_restriction_refused(args: argparse.Namespace) -> bool:
    """A ``--key`` against a blob attribute is refused.

    ``IntervalList.valid_times`` is a ``longblob`` attribute; restricting
    on it server-side is unsupported. Close the footgun before DataJoint
    emits an opaque SQL error.
    """
    if not _require_capability(
        args, datajoint=True, spyglass=True,
        why="blob-restriction refusal requires a real Spyglass heading",
    ):
        return True
    rc, out, err = _run_db_graph(
        [
            "find-instance",
            "--class",
            "IntervalList",
            "--key",
            "valid_times=anything",
        ],
        python_env=args.python_env,
    )
    if rc != 2:
        print(f"  [FAIL] expected rc=2, got {rc}; stderr: {err[:200]!r}")
        return False
    payload = _parse_json_or_fail(out, "blob_restriction payload")
    if payload is None:
        return False
    if payload.get("kind") != "invalid_query":
        print(f"  [FAIL] kind != 'invalid_query': {payload.get('kind')!r}")
        return False
    error = payload.get("error", {})
    if error.get("kind") != "blob_restriction_refused":
        print(
            f"  [FAIL] error.kind != 'blob_restriction_refused': "
            f"{error.get('kind')!r}"
        )
        return False
    print("  [ok] blob-attribute restriction exits 2 with clear error")
    return True


def fixture_c_null_key_value_refused(args: argparse.Namespace) -> bool:
    """``--key field=null`` is refused; DataJoint silently drops it otherwise.

    Pure parser test — does not need datajoint/spyglass on python_env
    because the parser fires before the resolver imports anything.
    """
    rc, out, _ = _run_db_graph(
        [
            "find-instance",
            "--class",
            "json:JSONDecoder",
            "--key",
            "x=null",
        ],
        python_env=args.python_env,
    )
    if rc != 2:
        print(f"  [FAIL] expected rc=2, got {rc}")
        return False
    payload = _parse_json_or_fail(out, "null_key payload")
    if payload is None:
        return False
    if payload.get("error", {}).get("kind") != "null_restriction_refused":
        print(
            f"  [FAIL] error.kind != 'null_restriction_refused': "
            f"{payload.get('error', {})!r}"
        )
        return False
    print("  [ok] --key field=null is refused with kind=null_restriction_refused")
    return True


def fixture_c_fields_key_mixed_with_explicit_fields_refused(
    args: argparse.Namespace,
) -> bool:
    """``--fields KEY,name`` is refused.

    Real DataJoint accepts the union (PK fields + extras) but the
    per-row payload dict cannot disambiguate a literal ``"KEY"`` from
    the PK fields it would expand to. The contract picks one form:
    ``--fields KEY`` for the primary key, or ``--fields f1,f2,...``
    for an explicit projection. Pinning the parser-side refusal so
    later passes cannot quietly relax it.

    Pure parser test — does not need datajoint/spyglass on python_env.
    """
    rc, out, _ = _run_db_graph(
        [
            "find-instance",
            "--class",
            "json:JSONDecoder",
            "--fields",
            "KEY,name",
        ],
        python_env=args.python_env,
    )
    if rc != 2:
        print(f"  [FAIL] expected rc=2, got {rc}")
        return False
    payload = _parse_json_or_fail(out, "fields KEY-mix payload")
    if payload is None:
        return False
    if payload.get("error", {}).get("kind") != "malformed_fields":
        print(
            f"  [FAIL] error.kind != 'malformed_fields': "
            f"{payload.get('error', {})!r}"
        )
        return False
    print("  [ok] --fields KEY,name refused with kind=malformed_fields")
    return True


def fixture_c_null_keyjson_value_refused(args: argparse.Namespace) -> bool:
    """``--key-json field=null`` is refused for the same reason ``--key
    field=null`` is — JSON ``null`` would otherwise sneak past the
    scalar-parser refusal and let DataJoint silently drop the
    restriction, returning the unrestricted relation.

    Pure parser test — does not need datajoint/spyglass on python_env.
    """
    rc, out, _ = _run_db_graph(
        [
            "find-instance",
            "--class",
            "json:JSONDecoder",
            "--key-json",
            "x=null",
        ],
        python_env=args.python_env,
    )
    if rc != 2:
        print(f"  [FAIL] expected rc=2, got {rc}")
        return False
    payload = _parse_json_or_fail(out, "null_keyjson payload")
    if payload is None:
        return False
    if payload.get("error", {}).get("kind") != "null_restriction_refused":
        print(
            f"  [FAIL] error.kind != 'null_restriction_refused': "
            f"{payload.get('error', {})!r}"
        )
        return False
    print(
        "  [ok] --key-json field=null is refused with "
        "kind=null_restriction_refused"
    )
    return True


def fixture_c_malformed_key_argument_refused(
    args: argparse.Namespace,
) -> bool:
    """``--key`` without an ``=`` is refused.

    Pure parser test. Empty FIELD or missing ``=`` falls into the
    malformed_key error class.
    """
    rc, out, _ = _run_db_graph(
        [
            "find-instance",
            "--class",
            "json:JSONDecoder",
            "--key",
            "no_equals_here",
        ],
        python_env=args.python_env,
    )
    if rc != 2:
        print(f"  [FAIL] expected rc=2, got {rc}")
        return False
    payload = _parse_json_or_fail(out, "malformed_key payload")
    if payload is None:
        return False
    if payload.get("error", {}).get("kind") != "malformed_key":
        print(
            f"  [FAIL] error.kind != 'malformed_key': "
            f"{payload.get('error', {})!r}"
        )
        return False
    print("  [ok] --key without = is refused with kind=malformed_key")
    return True


def fixture_c_unknown_fetch_field_refused(args: argparse.Namespace) -> bool:
    """``--fields nonexistent`` is refused.

    Mirrors the restriction-field validation. Catches the case where the
    user typed a field name that DataJoint would either error on or
    return None for, depending on the backend.
    """
    if not _require_capability(
        args, datajoint=True, spyglass=True,
        why="fetch-field validation requires a real Spyglass heading",
    ):
        return True
    rc, out, err = _run_db_graph(
        [
            "find-instance",
            "--class",
            "Session",
            "--fields",
            "definitely_not_a_field",
        ],
        python_env=args.python_env,
    )
    if rc != 2:
        print(f"  [FAIL] expected rc=2, got {rc}; stderr: {err[:200]!r}")
        return False
    payload = _parse_json_or_fail(out, "unknown_fetch_field payload")
    if payload is None:
        return False
    if payload.get("error", {}).get("kind") != "unknown_field":
        print(
            f"  [FAIL] error.kind != 'unknown_field': "
            f"{payload.get('error', {})!r}"
        )
        return False
    print("  [ok] unknown --fields entry is refused with kind=unknown_field")
    return True


def _expect_find_instance_payload(
    out: str, *, mode: str, expect_count_at_least: int = 0
) -> dict | None:
    """Common assertions for a successful find-instance call."""
    payload = _parse_json_or_fail(out, "find-instance success")
    if payload is None:
        return None
    if payload.get("kind") != "find-instance":
        print(f"  [FAIL] kind != 'find-instance': {payload.get('kind')!r}")
        return None
    if payload.get("query", {}).get("mode") != mode:
        print(
            f"  [FAIL] query.mode != {mode!r}: "
            f"{payload.get('query', {}).get('mode')!r}"
        )
        return None
    count = payload.get("count")
    if count is None or count < expect_count_at_least:
        print(
            f"  [FAIL] count {count!r} below expected lower bound "
            f"{expect_count_at_least}"
        )
        return None
    return payload


def fixture_c_eval9_session_row_lookup(args: argparse.Namespace) -> bool:
    """Eval #9 shape: ``--class Session --key nwb_file_name=X --fields KEY``.

    Returns ``query.resolved_class``, ``count``, bounded ``rows``. The
    nwb file used for this fixture is the lab's standard test session
    referenced throughout the eval set.
    """
    if not _require_capability(
        args, datajoint=True, spyglass=True,
        why="eval #9 row lookup against real Spyglass DB",
    ):
        return True
    rc, out, err = _run_db_graph(
        [
            "find-instance",
            "--class",
            "Session",
            "--key",
            "nwb_file_name=j1620210710_.nwb",
            "--fields",
            "KEY",
        ],
        python_env=args.python_env,
    )
    if rc != 0:
        print(f"  [FAIL] expected rc=0, got {rc}; stderr: {err[:200]!r}")
        return False
    payload = _expect_find_instance_payload(out, mode="rows")
    if payload is None:
        return False
    expected_resolved = "spyglass.common.common_session.Session"
    if payload["query"].get("resolved_class") != expected_resolved:
        print(
            f"  [FAIL] resolved_class drift: "
            f"{payload['query'].get('resolved_class')!r}"
        )
        return False
    rows = payload.get("rows", [])
    if not rows:
        print("  [FAIL] expected at least one row for the lab's test session")
        return False
    pk_fields = set(rows[0].keys())
    if "nwb_file_name" not in pk_fields:
        print(f"  [FAIL] PK field nwb_file_name missing from row keys: {pk_fields!r}")
        return False
    print("  [ok] eval #9: Session row lookup returns PK rows + count")
    return True


def fixture_c_eval10_selected_fields(args: argparse.Namespace) -> bool:
    """Eval #10 shape: selected fields fetch.

    ``--fields session_description,session_start_time`` returns those
    two fields per row, with safe-serialized values (datetime → ISO).
    """
    if not _require_capability(
        args, datajoint=True, spyglass=True,
        why="eval #10 selected fields against real Spyglass DB",
    ):
        return True
    rc, out, _ = _run_db_graph(
        [
            "find-instance",
            "--class",
            "Session",
            "--key",
            "nwb_file_name=j1620210710_.nwb",
            "--fields",
            "session_description,session_start_time",
        ],
        python_env=args.python_env,
    )
    if rc != 0:
        print(f"  [FAIL] expected rc=0, got {rc}")
        return False
    payload = _expect_find_instance_payload(out, mode="rows")
    if payload is None:
        return False
    rows = payload.get("rows", [])
    if not rows:
        print("  [FAIL] no rows returned")
        return False
    keys = set(rows[0].keys())
    if "session_description" not in keys or "session_start_time" not in keys:
        print(f"  [FAIL] expected fields not in row: {keys!r}")
        return False
    sst = rows[0]["session_start_time"]
    # ISO-8601 string proves the safe serializer fired.
    if not isinstance(sst, str) or "T" not in sst:
        print(f"  [FAIL] session_start_time not safe-serialized to ISO: {sst!r}")
        return False
    print("  [ok] eval #10: selected fields returned with ISO-serialized datetime")
    return True


def fixture_c_eval11_field_list(args: argparse.Namespace) -> bool:
    """Eval #11 shape: field listing across multiple rows.

    ``IntervalList & {nwb_file_name: X}`` typically returns ~50 rows;
    ``--fields interval_list_name`` should return that many strings.
    """
    if not _require_capability(
        args, datajoint=True, spyglass=True,
        why="eval #11 field list against real Spyglass DB",
    ):
        return True
    rc, out, _ = _run_db_graph(
        [
            "find-instance",
            "--class",
            "IntervalList",
            "--key",
            "nwb_file_name=j1620210710_.nwb",
            "--fields",
            "interval_list_name",
            "--limit",
            "100",
        ],
        python_env=args.python_env,
    )
    if rc != 0:
        print(f"  [FAIL] expected rc=0, got {rc}")
        return False
    payload = _expect_find_instance_payload(out, mode="rows", expect_count_at_least=1)
    if payload is None:
        return False
    rows = payload.get("rows", [])
    for row in rows:
        if "interval_list_name" not in row:
            print(f"  [FAIL] interval_list_name missing in row: {row!r}")
            return False
        if not isinstance(row["interval_list_name"], str):
            print(
                f"  [FAIL] interval_list_name not a string: "
                f"{type(row['interval_list_name']).__name__}"
            )
            return False
    print(
        f"  [ok] eval #11: IntervalList field list returned "
        f"{len(rows)} interval names"
    )
    return True


def fixture_c_eval12_count_only(args: argparse.Namespace) -> bool:
    """Eval #12 shape: ``--count`` returns count without rows.

    Eval ground truth: ``len(Electrode & {nwb_file_name: X})``. The
    ``--count`` flag short-circuits the fetch step, so the payload has
    ``count: N`` and ``rows: []``.
    """
    if not _require_capability(
        args, datajoint=True, spyglass=True,
        why="eval #12 count against real Spyglass DB",
    ):
        return True
    rc, out, _ = _run_db_graph(
        [
            "find-instance",
            "--class",
            "Electrode",
            "--key",
            "nwb_file_name=j1620210710_.nwb",
            "--count",
        ],
        python_env=args.python_env,
    )
    if rc != 0:
        print(f"  [FAIL] expected rc=0, got {rc}")
        return False
    payload = _expect_find_instance_payload(out, mode="count")
    if payload is None:
        return False
    rows = payload.get("rows", [])
    if rows:
        print(f"  [FAIL] --count should yield empty rows, got {len(rows)}")
        return False
    if payload["count"] < 1:
        print(f"  [FAIL] expected nonzero Electrode count, got {payload['count']}")
        return False
    print(f"  [ok] eval #12: --count yielded count={payload['count']}, rows=[]")
    return True


def fixture_c_eval13_key_only_resolves_merge_evidence(
    args: argparse.Namespace,
) -> bool:
    """Eval #13 shape: KEY-only fetch resolves the merge evidence.

    The eval prompt asks for the Trodes position dataframe via
    PositionOutput. Batch C does not implement merge-aware resolution
    (Batch D), but it MUST be able to fetch the part-table KEY which
    includes the merge_id. ``PositionOutput.TrodesPosV1 & {...}.fetch1('KEY')``
    is the canonical resolution step before the dataframe fetch.
    """
    if not _require_capability(
        args, datajoint=True, spyglass=True,
        why="eval #13 KEY-only fetch against real Spyglass DB",
    ):
        return True
    rc, out, err = _run_db_graph(
        [
            "find-instance",
            "--class",
            "PositionOutput.TrodesPosV1",
            "--key",
            "nwb_file_name=j1620210710_.nwb",
            "--key",
            "interval_list_name=02_r1",
            "--key",
            "trodes_pos_params_name=default",
            "--fields",
            "KEY",
        ],
        python_env=args.python_env,
    )
    if rc != 0:
        print(f"  [FAIL] expected rc=0, got {rc}; stderr: {err[:200]!r}")
        return False
    payload = _expect_find_instance_payload(out, mode="rows")
    if payload is None:
        return False
    rows = payload.get("rows", [])
    if not rows:
        print(
            "  [FAIL] expected at least one PositionOutput.TrodesPosV1 row "
            "for the lab's test session"
        )
        return False
    if "merge_id" not in rows[0]:
        print(
            f"  [FAIL] merge_id absent from KEY fetch — Batch D depends "
            f"on this evidence: {rows[0]!r}"
        )
        return False
    print("  [ok] eval #13: KEY fetch returns merge_id (Batch D evidence ready)")
    return True


def fixture_c_limit_truncation_marker(args: argparse.Namespace) -> bool:
    """``truncated: true`` fires when the relation has more rows than ``--limit``.

    Uses ``--limit 1`` against IntervalList for the lab's test session
    (which has many rows); the payload should report ``count > 1`` and
    ``truncated: true`` with exactly 1 row in the output.
    """
    if not _require_capability(
        args, datajoint=True, spyglass=True,
        why="truncation marker requires fetching from a real DataJoint table",
    ):
        return True
    rc, out, _ = _run_db_graph(
        [
            "find-instance",
            "--class",
            "IntervalList",
            "--key",
            "nwb_file_name=j1620210710_.nwb",
            "--fields",
            "KEY",
            "--limit",
            "1",
        ],
        python_env=args.python_env,
    )
    if rc != 0:
        print(f"  [FAIL] expected rc=0, got {rc}")
        return False
    payload = _parse_json_or_fail(out, "truncation payload")
    if payload is None:
        return False
    if not payload.get("truncated"):
        print(f"  [FAIL] truncated should be true: {payload.get('truncated')!r}")
        return False
    if len(payload.get("rows", [])) != 1:
        print(f"  [FAIL] rows should have 1 entry, got {len(payload.get('rows', []))}")
        return False
    if payload["count"] <= 1:
        print(
            f"  [FAIL] count should be > 1 for the truncation case: "
            f"{payload['count']}"
        )
        return False
    print(
        f"  [ok] --limit 1 + many rows: truncated=true, count="
        f"{payload['count']}, rows=1"
    )
    return True


def fixture_c_empty_result_exit_zero_by_default(
    args: argparse.Namespace,
) -> bool:
    """Empty result is exit 0 with ``count: 0`` (the canonical scientific answer).

    Plan: "I checked; there are zero rows" is a valid final answer; the
    user opts into a non-zero exit only via ``--fail-on-empty``.
    """
    if not _require_capability(
        args, datajoint=True, spyglass=True,
        why="empty-result-zero-exit requires a real Spyglass query",
    ):
        return True
    rc, out, _ = _run_db_graph(
        [
            "find-instance",
            "--class",
            "Session",
            "--key",
            "nwb_file_name=__definitely_not_a_real_session__.nwb",
            "--fields",
            "KEY",
        ],
        python_env=args.python_env,
    )
    if rc != 0:
        print(f"  [FAIL] expected rc=0, got {rc}")
        return False
    payload = _parse_json_or_fail(out, "empty-result payload")
    if payload is None:
        return False
    if payload.get("count") != 0:
        print(f"  [FAIL] count != 0: {payload.get('count')!r}")
        return False
    if payload.get("rows", "missing") != []:
        print(f"  [FAIL] rows != []: {payload.get('rows')!r}")
        return False
    print("  [ok] empty result → exit 0 with count=0 (default)")
    return True


def _expect_merge_payload(out: str) -> dict | None:
    """Common assertions for a successful merge-aware find-instance call."""
    payload = _parse_json_or_fail(out, "merge payload")
    if payload is None:
        return None
    if payload.get("kind") != "merge":
        print(f"  [FAIL] kind != 'merge': {payload.get('kind')!r}")
        return None
    merge = payload.get("merge", {})
    if merge.get("restriction_applied_to") != "part":
        print(
            f"  [FAIL] merge.restriction_applied_to != 'part': "
            f"{merge.get('restriction_applied_to')!r}"
        )
        return None
    if not merge.get("master_key_fields"):
        print(f"  [FAIL] merge.master_key_fields empty: {merge!r}")
        return None
    return payload


def fixture_d_eval14_trodes_position_merge_id(
    args: argparse.Namespace,
) -> bool:
    """Eval #14 shape: ``merge_id`` for Trodes position via PositionOutput.

    ``--merge-master PositionOutput --part TrodesPosV1 --key
    nwb_file_name=X --key interval_list_name=Y --key
    trodes_pos_params_name=Z`` resolves the part keys, fetches the
    master keys (``merge_id``), and returns master rows for those keys.
    """
    if not _require_capability(
        args, datajoint=True, spyglass=True,
        why="eval #14 merge-id lookup against real Spyglass DB",
    ):
        return True
    rc, out, err = _run_db_graph(
        [
            "find-instance",
            "--merge-master",
            "PositionOutput",
            "--part",
            "TrodesPosV1",
            "--key",
            "nwb_file_name=j1620210710_.nwb",
            "--key",
            "interval_list_name=02_r1",
            "--key",
            "trodes_pos_params_name=default",
            "--fields",
            "KEY",
        ],
        python_env=args.python_env,
    )
    if rc != 0:
        print(f"  [FAIL] expected rc=0, got {rc}; stderr: {err[:200]!r}")
        return False
    payload = _expect_merge_payload(out)
    if payload is None:
        return False
    merge = payload["merge"]
    if "merge_id" not in merge["master_key_fields"]:
        print(
            f"  [FAIL] master_key_fields missing 'merge_id': "
            f"{merge['master_key_fields']!r}"
        )
        return False
    if merge.get("master") != "PositionOutput":
        print(f"  [FAIL] merge.master != 'PositionOutput': {merge.get('master')!r}")
        return False
    if merge.get("part") != "TrodesPosV1":
        print(f"  [FAIL] merge.part != 'TrodesPosV1': {merge.get('part')!r}")
        return False
    if not merge.get("merge_ids"):
        print("  [FAIL] merge.merge_ids should list the resolved merge_id")
        return False
    print("  [ok] eval #14: PositionOutput merge_id resolved via TrodesPosV1")
    return True


def fixture_d_eval15_lfp_merge_id_via_lfpv1(
    args: argparse.Namespace,
) -> bool:
    """Eval #15 shape: LFP merge entry via LFPOutput / LFPV1 (when populated).

    Filter narrowness depends on the lab's data; this fixture uses the
    ``nwb_file_name`` restriction only and verifies the merge envelope
    is well-shaped. The eval ground truth notes that filter_name alone
    does not uniquely identify the filter (there are duplicates by
    sampling rate); the fixture asserts the merge mechanics, not a
    specific count.
    """
    if not _require_capability(
        args, datajoint=True, spyglass=True,
        why="eval #15 LFP merge against real Spyglass DB",
    ):
        return True
    rc, out, err = _run_db_graph(
        [
            "find-instance",
            "--merge-master",
            "LFPOutput",
            "--part",
            "LFPV1",
            "--key",
            "nwb_file_name=j1620210710_.nwb",
            "--fields",
            "KEY",
        ],
        python_env=args.python_env,
    )
    if rc != 0:
        print(f"  [FAIL] expected rc=0, got {rc}; stderr: {err[:200]!r}")
        return False
    payload = _expect_merge_payload(out)
    if payload is None:
        return False
    merge = payload["merge"]
    if "merge_id" not in merge["master_key_fields"]:
        print(
            f"  [FAIL] master_key_fields missing 'merge_id': "
            f"{merge['master_key_fields']!r}"
        )
        return False
    print(
        f"  [ok] eval #15: LFPOutput merge resolved via LFPV1 "
        f"(count={payload.get('count')})"
    )
    return True


def fixture_d_eval16_decoding_output_merge_id(
    args: argparse.Namespace,
) -> bool:
    """Eval #16 shape: DecodingOutput merge_id via ClusterlessDecodingV1.

    The eval ground truth involves a parameter-name discovery step that
    is out of scope here. This fixture exercises the merge mechanics
    against the part with a session-only restriction; the result may
    have ``count: 0`` if the lab's data hasn't populated this part for
    the given session, but the merge envelope must still be well-shaped.
    """
    if not _require_capability(
        args, datajoint=True, spyglass=True,
        why="eval #16 DecodingOutput merge against real Spyglass DB",
    ):
        return True
    rc, out, err = _run_db_graph(
        [
            "find-instance",
            "--merge-master",
            "DecodingOutput",
            "--part",
            "ClusterlessDecodingV1",
            "--key",
            "nwb_file_name=j1620210710_.nwb",
            "--fields",
            "KEY",
        ],
        python_env=args.python_env,
    )
    # Allow rc=0 (merge succeeded) or rc=4 (part not in current schema
    # snapshot — Spyglass schema evolution is fast and not every lab
    # has every part populated).
    if rc not in (0, 4):
        print(f"  [FAIL] expected rc in (0, 4), got {rc}; stderr: {err[:200]!r}")
        return False
    if rc == 0:
        payload = _expect_merge_payload(out)
        if payload is None:
            return False
        if "merge_id" not in payload["merge"]["master_key_fields"]:
            print("  [FAIL] master_key_fields missing 'merge_id'")
            return False
        print(
            f"  [ok] eval #16: DecodingOutput merge resolved "
            f"(count={payload.get('count')})"
        )
    else:
        print(
            "  [ok] eval #16: ClusterlessDecodingV1 not present in this "
            "Spyglass snapshot — not_found is the honest answer"
        )
    return True


def fixture_e_eval17_intersect_sessions_in_both(
    args: argparse.Namespace,
) -> bool:
    """Eval #17 shape: sessions with both RippleTimesV1 and ClusterlessDecodingV1.

    ``RippleTimesV1 * ClusterlessDecodingV1`` is the eval's natural-join
    formulation. ``--intersect`` runs ``L & R.proj()`` which, since
    both classes share ``nwb_file_name`` (among others), yields the
    same set of nwb_file_names. This fixture asserts the intersection
    succeeds and returns at least the shared key.
    """
    if not _require_capability(
        args, datajoint=True, spyglass=True,
        why="eval #17 intersect against real Spyglass DB",
    ):
        return True
    rc, out, err = _run_db_graph(
        [
            "find-instance",
            "--class",
            "RippleTimesV1",
            "--intersect",
            "ClusterlessDecodingV1",
            "--fields",
            "KEY",
        ],
        python_env=args.python_env,
    )
    # Allow both rc=0 (intersection has rows) and rc=0 with empty
    # rows (both classes populated but no shared row) — both are
    # honest answers. Refuse only on db_error / not_found.
    if rc != 0:
        print(f"  [FAIL] expected rc=0, got {rc}; stderr: {err[:200]!r}")
        return False
    payload = _parse_json_or_fail(out, "eval17 payload")
    if payload is None:
        return False
    if payload.get("kind") != "find-instance":
        print(f"  [FAIL] kind != 'find-instance': {payload.get('kind')!r}")
        return False
    if payload.get("query", {}).get("set_op") != "intersect":
        print("  [FAIL] set_op != 'intersect'")
        return False
    print(
        f"  [ok] eval #17: RippleTimesV1 ∩ ClusterlessDecodingV1 "
        f"(count={payload.get('count')})"
    )
    return True


def fixture_e_eval18_except_sessions_only_in_left(
    args: argparse.Namespace,
) -> bool:
    """Eval #18 shape: sessions in TrodesPosV1 but not DLCPosV1.

    The eval's bare ``TrodesPosV1 - DLCPosV1`` raises in DataJoint
    because the operands have non-shared PK attributes; we run with
    ``.proj()`` instead which DataJoint accepts.
    """
    if not _require_capability(
        args, datajoint=True, spyglass=True,
        why="eval #18 antijoin against real Spyglass DB",
    ):
        return True
    rc, out, err = _run_db_graph(
        [
            "find-instance",
            "--class",
            "TrodesPosV1",
            "--except",
            "DLCPosV1",
            "--fields",
            "KEY",
        ],
        python_env=args.python_env,
    )
    if rc != 0:
        # Allow rc=5 if DataJoint refuses the projection-form antijoin
        # (some DataJoint versions reject this even with .proj()).
        if rc == 5:
            print(
                f"  [ok] eval #18: DataJoint refused .proj() antijoin "
                f"(stderr: {err[:80]!r}). Future improvement: bounded "
                "Python fallback."
            )
            return True
        print(f"  [FAIL] expected rc in (0, 5), got {rc}; stderr: {err[:200]!r}")
        return False
    payload = _parse_json_or_fail(out, "eval18 payload")
    if payload is None:
        return False
    if payload.get("query", {}).get("set_op") != "except":
        print("  [FAIL] set_op != 'except'")
        return False
    print(
        f"  [ok] eval #18: TrodesPosV1 \\ DLCPosV1 "
        f"(count={payload.get('count')})"
    )
    return True


def fixture_e_eval19_per_session_distinct_tetrodes(
    args: argparse.Namespace,
) -> bool:
    """Eval #19 shape: per-session distinct electrode-group counts.

    ``--class Electrode --key subject_id=aj80 --group-by-table Session
    --count-distinct electrode_group_name`` should yield one row per
    Session matching the restriction, with the count of distinct
    electrode-group names.
    """
    if not _require_capability(
        args, datajoint=True, spyglass=True,
        why="eval #19 grouped count against real Spyglass DB",
    ):
        return True
    rc, out, err = _run_db_graph(
        [
            "find-instance",
            "--class",
            "Electrode",
            "--key",
            "subject_id=aj80",
            "--group-by-table",
            "Session",
            "--count-distinct",
            "electrode_group_name",
        ],
        python_env=args.python_env,
    )
    if rc != 0:
        print(f"  [FAIL] expected rc=0, got {rc}; stderr: {err[:200]!r}")
        return False
    payload = _parse_json_or_fail(out, "eval19 payload")
    if payload is None:
        return False
    if payload.get("kind") != "grouped_count":
        print(f"  [FAIL] kind != 'grouped_count': {payload.get('kind')!r}")
        return False
    groups = payload.get("groups", [])
    # Sanity: each group has nwb_file_name and a count of distinct groups.
    for g in groups:
        if "nwb_file_name" not in g:
            print(f"  [FAIL] group missing nwb_file_name: {g!r}")
            return False
        if "count_distinct_electrode_group_name" not in g:
            print(
                f"  [FAIL] group missing count_distinct_electrode_group_name: "
                f"{g!r}"
            )
            return False
    print(
        f"  [ok] eval #19: per-session distinct tetrode counts "
        f"({len(groups)} sessions for subject_id=aj80)"
    )
    return True


def fixture_e_eval28_29_join_to_brain_region(
    args: argparse.Namespace,
) -> bool:
    """Evals #28/#29 shape: join Electrode * BrainRegion via shared attrs.

    Both Electrode and BrainRegion live in spyglass.common; they share
    ``region_id`` (or similar). The join is the canonical pattern for
    "what brain region is this electrode in?". This fixture asserts
    the join produces a non-empty heading and returns rows that
    expose region-name-shaped fields.
    """
    if not _require_capability(
        args, datajoint=True, spyglass=True,
        why="eval #28/#29 join against real Spyglass DB",
    ):
        return True
    rc, out, err = _run_db_graph(
        [
            "find-instance",
            "--class",
            "Electrode",
            "--key",
            "nwb_file_name=j1620210710_.nwb",
            "--key",
            "electrode_id=7",
            "--join",
            "BrainRegion",
            "--fields",
            "nwb_file_name,electrode_id,region_name",
        ],
        python_env=args.python_env,
    )
    if rc != 0:
        print(f"  [FAIL] expected rc=0, got {rc}; stderr: {err[:200]!r}")
        return False
    payload = _parse_json_or_fail(out, "eval28/29 payload")
    if payload is None:
        return False
    if payload.get("query", {}).get("set_op") != "join":
        print("  [FAIL] set_op != 'join'")
        return False
    rows = payload.get("rows", [])
    if not rows:
        print(
            "  [FAIL] expected at least one Electrode-BrainRegion join row"
        )
        return False
    if "region_name" not in rows[0]:
        print(f"  [FAIL] join row missing region_name: {rows[0]!r}")
        return False
    print(
        f"  [ok] eval #28/#29: Electrode * BrainRegion returned "
        f"region_name={rows[0].get('region_name')!r}"
    )
    return True


def fixture_f_fakes_describe_returns_heading_and_adjacency(
    args: argparse.Namespace,
) -> bool:
    """``describe CLASS`` returns runtime heading + parent/child/part names.

    Builds a synthetic class with a known heading and adjacency lists,
    runs describe, and verifies every plan-required field appears in
    the payload at the right shape.
    """
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        import fakes as _fakes_module

        _fakes_module.prepare_sandbox(tmp)
        (tmp / "describetest.py").write_text(
            "\n".join(
                [
                    "from datajoint import Manual",
                    "from fakes import FakeHeading, FakeRelation",
                    "",
                    "class Demo(Manual):",
                    "    _heading_obj = FakeHeading(",
                    "        primary_key=('id',),",
                    "        names=('id', 'name', 'value'),",
                    "        attributes={",
                    "            'id': 'int',",
                    "            'name': 'varchar(64)',",
                    "            'value': 'float',",
                    "        },",
                    "    )",
                    "    _rows = [",
                    "        {'id': 1, 'name': 'a', 'value': 1.0},",
                    "        {'id': 2, 'name': 'b', 'value': 2.0},",
                    "    ]",
                    "",
                    "    def __new__(cls):",
                    "        return FakeRelation(",
                    "            heading=cls._heading_obj, rows=cls._rows,",
                    "            parents=('schema.upstream_a', 'schema.upstream_b'),",
                    "            children=('schema.downstream_x',),",
                    "            parts=(),",
                    "        )",
                    "",
                    "    @property",
                    "    def heading(self):",
                    "        return self._heading_obj",
                    "",
                ]
            )
        )
        rc, out, err = _run_db_graph(
            [
                "describe",
                "describetest:Demo",
                "--import",
                "describetest",
                "--count",
            ],
            python_env=args.python_env,
            extra_env={"PYTHONPATH": str(tmp)},
        )
    if rc != 0:
        print(f"  [FAIL] expected rc=0, got {rc}; stderr: {err[:200]!r}")
        return False
    payload = _parse_json_or_fail(out, "describe payload")
    if payload is None:
        return False
    if payload.get("kind") != "describe":
        print(f"  [FAIL] kind != 'describe': {payload.get('kind')!r}")
        return False
    desc = payload.get("describe", {})
    if desc.get("primary_key") != ["id"]:
        print(f"  [FAIL] primary_key drift: {desc.get('primary_key')!r}")
        return False
    if sorted(desc.get("secondary_attributes", [])) != ["name", "value"]:
        print(
            f"  [FAIL] secondary_attributes drift: "
            f"{desc.get('secondary_attributes')!r}"
        )
        return False
    attrs = desc.get("attributes", {})
    if attrs.get("id", {}).get("in_primary_key") is not True:
        print(f"  [FAIL] attributes.id.in_primary_key drift: {attrs.get('id')!r}")
        return False
    if attrs.get("name", {}).get("type") != "varchar(64)":
        print(f"  [FAIL] attributes.name.type drift: {attrs.get('name')!r}")
        return False
    if sorted(desc.get("parents", [])) != [
        "schema.upstream_a",
        "schema.upstream_b",
    ]:
        print(f"  [FAIL] parents drift: {desc.get('parents')!r}")
        return False
    if desc.get("children") != ["schema.downstream_x"]:
        print(f"  [FAIL] children drift: {desc.get('children')!r}")
        return False
    if desc.get("parts") != []:
        print(f"  [FAIL] parts drift: {desc.get('parts')!r}")
        return False
    if desc.get("count") != 2:
        print(f"  [FAIL] count != 2 (--count was passed): {desc.get('count')!r}")
        return False
    # Status block: parents/children present (status=ok). The fake
    # always exposes the methods, so all three should be ok.
    status = desc.get("relationship_metadata_status", {})
    for rel_name in ("parents", "children", "parts"):
        if status.get(rel_name, {}).get("status") != "ok":
            print(
                f"  [FAIL] relationship_metadata_status.{rel_name}.status "
                f"!= 'ok': {status.get(rel_name)!r}"
            )
            return False
    print(
        "  [ok] describe: heading + adjacency + count + "
        "relationship_metadata_status round-trip via fakes sandbox"
    )
    return True


def fixture_f_fakes_describe_errored_metadata_reported_as_error(
    args: argparse.Namespace,
) -> bool:
    """``parents()`` raising → ``status: "error"`` (not confirmed-empty).

    Builds a synthetic class whose returned relation has
    ``parents()`` overridden to raise (simulating an older
    DataJoint or a custom relation whose schema metadata
    round-trip fails). describe must report
    ``status: "error"`` plus the scrubbed message — distinct from a
    confirmed-empty list.
    """
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        import fakes as _fakes_module

        _fakes_module.prepare_sandbox(tmp)
        # Synthetic class whose returned relation has ``parents()``
        # raise — simulates an older DataJoint or a custom relation
        # whose schema metadata round-trip fails.  describe should
        # report ``status: "error"`` rather than ``parents: []`` with
        # no further signal.
        (tmp / "describemissing.py").write_text(
            "\n".join(
                [
                    "from datajoint import Manual",
                    "from fakes import FakeHeading, FakeRelation",
                    "",
                    "",
                    "def _raise_no_parents():",
                    "    raise AttributeError("
                    "'parents() lookup failed (synthetic)')",
                    "",
                    "",
                    "class Demo(Manual):",
                    "    _heading_obj = FakeHeading(",
                    "        primary_key=('id',),",
                    "        names=('id',),",
                    "        attributes={'id': 'int'},",
                    "    )",
                    "    def __new__(cls):",
                    "        rel = FakeRelation(",
                    "            heading=cls._heading_obj, rows=[],",
                    "            children=('schema.downstream_x',),",
                    "        )",
                    "        # Override the instance's parents() to raise.",
                    "        rel.parents = lambda *a, **k: "
                    "_raise_no_parents()",
                    "        return rel",
                    "    @property",
                    "    def heading(self):",
                    "        return self._heading_obj",
                ]
            )
        )
        rc, out, _ = _run_db_graph(
            [
                "describe",
                "describemissing:Demo",
                "--import",
                "describemissing",
            ],
            python_env=args.python_env,
            extra_env={"PYTHONPATH": str(tmp)},
        )
    if rc != 0:
        print(f"  [FAIL] expected rc=0, got {rc}")
        return False
    payload = _parse_json_or_fail(out, "describe-unavail payload")
    if payload is None:
        return False
    status = payload.get("describe", {}).get(
        "relationship_metadata_status", {}
    )
    parents_status = status.get("parents", {}).get("status")
    if parents_status != "error":
        print(
            f"  [FAIL] parents.status should be 'error' (raised "
            f"AttributeError), got {parents_status!r}"
        )
        return False
    if not status.get("parents", {}).get("error"):
        print("  [FAIL] parents.error should carry the message")
        return False
    children_status = status.get("children", {}).get("status")
    if children_status != "ok":
        print(
            f"  [FAIL] children.status should be 'ok' (the fake "
            f"exposes the method): got {children_status!r}"
        )
        return False
    print(
        "  [ok] describe distinguishes 'errored metadata lookup' from "
        "'confirmed empty' via relationship_metadata_status"
    )
    return True


def fixture_f_fakes_describe_omits_count_by_default(
    args: argparse.Namespace,
) -> bool:
    """Without ``--count``, ``describe.count`` is null (no count(*) round-trip)."""
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        import fakes as _fakes_module

        _fakes_module.prepare_sandbox(tmp)
        (tmp / "describenocnt.py").write_text(
            "\n".join(
                [
                    "from datajoint import Manual",
                    "from fakes import FakeHeading, FakeRelation",
                    "",
                    "class Tiny(Manual):",
                    "    _heading_obj = FakeHeading(",
                    "        primary_key=('id',),",
                    "        names=('id',),",
                    "        attributes={'id': 'int'},",
                    "    )",
                    "    _rows = []",
                    "    def __new__(cls):",
                    "        return FakeRelation("
                    "heading=cls._heading_obj, rows=cls._rows)",
                    "    @property",
                    "    def heading(self):",
                    "        return self._heading_obj",
                ]
            )
        )
        rc, out, _ = _run_db_graph(
            [
                "describe",
                "describenocnt:Tiny",
                "--import",
                "describenocnt",
            ],
            python_env=args.python_env,
            extra_env={"PYTHONPATH": str(tmp)},
        )
    if rc != 0:
        print(f"  [FAIL] expected rc=0, got {rc}")
        return False
    payload = _parse_json_or_fail(out, "describe-nocnt payload")
    if payload is None:
        return False
    desc = payload.get("describe", {})
    if desc.get("count") is not None:
        print(
            f"  [FAIL] count should be null without --count, got "
            f"{desc.get('count')!r}"
        )
        return False
    print("  [ok] describe without --count: describe.count is null")
    return True


def fixture_f_fakes_describe_unavailable_metadata_distinguished(
    args: argparse.Namespace,
) -> bool:
    """``parents`` not exposed on the relation → ``status: "unavailable"``.

    Distinct from the errored-metadata fixture: here the method
    simply isn't accessible (``getattr(rel, "parents", None) is
    None``) — the canonical "older DataJoint or non-DJ relation"
    case. ``children`` and ``parts`` remain functional on the same
    relation, so the fixture asserts only ``parents`` is reported
    as unavailable while the others stay ``ok``.
    """
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        import fakes as _fakes_module

        _fakes_module.prepare_sandbox(tmp)
        # Synthetic class returns a relation whose ``parents``
        # attribute is None — ``getattr(rel, "parents", None)`` then
        # falls into the unavailable path inside
        # ``_safe_runtime_metadata``.
        (tmp / "describeunavail.py").write_text(
            "\n".join(
                [
                    "from datajoint import Manual",
                    "from fakes import FakeHeading, FakeRelation",
                    "",
                    "class Demo(Manual):",
                    "    _heading_obj = FakeHeading(",
                    "        primary_key=('id',),",
                    "        names=('id',),",
                    "        attributes={'id': 'int'},",
                    "    )",
                    "    def __new__(cls):",
                    "        rel = FakeRelation(",
                    "            heading=cls._heading_obj, rows=[],",
                    "            children=('schema.downstream_x',),",
                    "        )",
                    "        # Older DataJoint / non-DJ relation: no "
                    "parents() method.",
                    "        rel.parents = None",
                    "        return rel",
                    "    @property",
                    "    def heading(self):",
                    "        return self._heading_obj",
                ]
            )
        )
        rc, out, _ = _run_db_graph(
            [
                "describe",
                "describeunavail:Demo",
                "--import",
                "describeunavail",
            ],
            python_env=args.python_env,
            extra_env={"PYTHONPATH": str(tmp)},
        )
    if rc != 0:
        print(f"  [FAIL] expected rc=0, got {rc}")
        return False
    payload = _parse_json_or_fail(out, "describe-unavail-real payload")
    if payload is None:
        return False
    status = payload.get("describe", {}).get(
        "relationship_metadata_status", {}
    )
    parents_status = status.get("parents", {}).get("status")
    if parents_status != "unavailable":
        print(
            f"  [FAIL] parents.status should be 'unavailable' (None "
            f"attribute), got {parents_status!r}"
        )
        return False
    if status.get("parents", {}).get("error") is not None:
        print(
            f"  [FAIL] parents.error should be null on unavailable: "
            f"{status.get('parents', {}).get('error')!r}"
        )
        return False
    children_status = status.get("children", {}).get("status")
    if children_status != "ok":
        print(
            f"  [FAIL] children.status should be 'ok': "
            f"{children_status!r}"
        )
        return False
    print(
        "  [ok] describe distinguishes 'unavailable' (method missing) "
        "from 'ok' on the same relation"
    )
    return True


def fixture_f_describe_advertised_in_info(
    args: argparse.Namespace,
) -> bool:
    """``info --json`` advertises describe with the documented contract.

    Pins the live machine-readable surface, not the source text:
    runs ``info --json`` and parses the payload, then asserts the
    describe subcommand block, payload envelope, and result-shape
    enum entry are all present. The earlier source-grep version
    missed a real drift (``describe`` not in result_shapes); this
    fixture would have caught it.
    """
    rc, out, err = _run_db_graph(["info", "--json"], python_env=args.python_env)
    if rc != 0:
        print(f"  [FAIL] info --json exited {rc}; stderr: {err!r}")
        return False
    payload = _parse_json_or_fail(out, "info --json")
    if payload is None:
        return False
    subcommands = payload.get("subcommands", {})
    if "describe" not in subcommands:
        print(
            f"  [FAIL] subcommands missing describe entry; got "
            f"{sorted(subcommands.keys())}"
        )
        return False
    describe_entry = subcommands["describe"]
    for inner in ("purpose", "modes", "hints"):
        if inner not in describe_entry:
            print(
                f"  [FAIL] subcommands.describe missing {inner!r}: "
                f"{sorted(describe_entry.keys())}"
            )
            return False
    envelopes = payload.get("payload_envelopes", {})
    if "describe" not in envelopes:
        print(
            f"  [FAIL] payload_envelopes missing describe; got "
            f"{sorted(envelopes.keys())}"
        )
        return False
    if "describe" not in envelopes["describe"]:
        print(
            f"  [FAIL] payload_envelopes.describe missing the "
            f"`describe` sub-block field: {envelopes['describe']!r}"
        )
        return False
    result_shapes = payload.get("result_shapes", [])
    if "describe" not in result_shapes:
        print(
            f"  [FAIL] result_shapes missing 'describe'; got "
            f"{result_shapes!r}"
        )
        return False
    print(
        "  [ok] info --json: subcommands.describe + payload_envelopes."
        "describe + result_shapes 'describe' entry all present"
    )
    return True


def fixture_f_eval_describe_session(args: argparse.Namespace) -> bool:
    """Live: ``describe Session --json --count`` returns the canonical heading."""
    if not _require_capability(
        args, datajoint=True, spyglass=True,
        why="live describe of Spyglass.Session",
    ):
        return True
    rc, out, err = _run_db_graph(
        ["describe", "Session", "--count"],
        python_env=args.python_env,
    )
    if rc != 0:
        print(f"  [FAIL] expected rc=0, got {rc}; stderr: {err[:200]!r}")
        return False
    payload = _parse_json_or_fail(out, "live describe Session")
    if payload is None:
        return False
    desc = payload.get("describe", {})
    if "nwb_file_name" not in desc.get("primary_key", []):
        print(
            f"  [FAIL] expected nwb_file_name in primary_key: "
            f"{desc.get('primary_key')!r}"
        )
        return False
    attrs = desc.get("attributes", {})
    if "session_description" not in attrs:
        print(
            f"  [FAIL] expected session_description in attributes "
            f"keys; got {sorted(attrs.keys())}"
        )
        return False
    print(
        f"  [ok] live describe: Session PK + session_description "
        f"present (count={desc.get('count')})"
    )
    return True


def _write_fake_path_module(target: Path) -> None:
    """Write a synthetic three-node chain A → B → C for path fixtures.

    Each class has ``full_table_name`` matching a registry entry in
    ``datajoint._TABLE_GRAPH``. The chain is acyclic so BFS results
    are deterministic.
    """
    (target / "fakepath.py").write_text(
        "\n".join(
            [
                '"""Synthetic A → B → C chain for Batch G path fixtures."""',
                "from datajoint import Manual, _TABLE_GRAPH",
                "from fakes import FakeHeading, FakeRelation",
                "",
                "",
                "_TABLE_GRAPH['fakepath.a'] = {",
                "    'parents': [],",
                "    'children': ['fakepath.b'],",
                "}",
                "_TABLE_GRAPH['fakepath.b'] = {",
                "    'parents': ['fakepath.a'],",
                "    'children': ['fakepath.c'],",
                "}",
                "_TABLE_GRAPH['fakepath.c'] = {",
                "    'parents': ['fakepath.b'],",
                "    'children': [],",
                "}",
                "",
                "",
                "class A(Manual):",
                "    full_table_name = 'fakepath.a'",
                "    _heading_obj = FakeHeading(",
                "        primary_key=('id',), names=('id',),",
                "        attributes={'id': 'int'},",
                "    )",
                "    def __new__(cls):",
                "        return FakeRelation(heading=cls._heading_obj, rows=[])",
                "    @property",
                "    def heading(self):",
                "        return self._heading_obj",
                "",
                "",
                "class B(Manual):",
                "    full_table_name = 'fakepath.b'",
                "    _heading_obj = FakeHeading(",
                "        primary_key=('id',), names=('id',),",
                "        attributes={'id': 'int'},",
                "    )",
                "    def __new__(cls):",
                "        return FakeRelation(heading=cls._heading_obj, rows=[])",
                "    @property",
                "    def heading(self):",
                "        return self._heading_obj",
                "",
                "",
                "class C(Manual):",
                "    full_table_name = 'fakepath.c'",
                "    _heading_obj = FakeHeading(",
                "        primary_key=('id',), names=('id',),",
                "        attributes={'id': 'int'},",
                "    )",
                "    def __new__(cls):",
                "        return FakeRelation(heading=cls._heading_obj, rows=[])",
                "    @property",
                "    def heading(self):",
                "        return self._heading_obj",
                "",
            ]
        )
    )


def _setup_path_sandbox(tmp: Path) -> None:
    import fakes as _fakes_module

    _fakes_module.prepare_sandbox(tmp)
    _write_fake_path_module(tmp)


def fixture_g_fakes_path_to_finds_chain(
    args: argparse.Namespace,
) -> bool:
    """``path --to A C`` returns the parent→child chain A → B → C."""
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        _setup_path_sandbox(tmp)
        rc, out, err = _run_db_graph(
            [
                "path",
                "--to",
                "fakepath:A",
                "fakepath:C",
                "--import",
                "fakepath",
            ],
            python_env=args.python_env,
            extra_env={"PYTHONPATH": str(tmp)},
        )
    if rc != 0:
        print(f"  [FAIL] expected rc=0, got {rc}; stderr: {err[:200]!r}")
        return False
    payload = _parse_json_or_fail(out, "path --to payload")
    if payload is None:
        return False
    if payload.get("kind") != "path":
        print(f"  [FAIL] kind != 'path': {payload.get('kind')!r}")
        return False
    if payload.get("query", {}).get("mode") != "to":
        print("  [FAIL] query.mode != 'to'")
        return False
    hops = payload.get("hops", [])
    chain = [h.get("full_table_name") for h in hops]
    if chain != ["fakepath.a", "fakepath.b", "fakepath.c"]:
        print(f"  [FAIL] hop chain drift: {chain!r}")
        return False
    if payload.get("truncated"):
        print(f"  [FAIL] truncated should be false: {payload.get('truncated')!r}")
        return False
    print(
        f"  [ok] path --to A C: chain {chain} (depth-3 BFS in fakes sandbox)"
    )
    return True


def fixture_g_fakes_path_to_no_path_returns_empty(
    args: argparse.Namespace,
) -> bool:
    """``path --to`` returns empty hops when no path exists.

    A → B → C is the only chain; ``path --to C A`` walks children
    starting at C (no children), so no path is found.
    """
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        _setup_path_sandbox(tmp)
        rc, out, _ = _run_db_graph(
            [
                "path",
                "--to",
                "fakepath:C",
                "fakepath:A",
                "--import",
                "fakepath",
            ],
            python_env=args.python_env,
            extra_env={"PYTHONPATH": str(tmp)},
        )
    if rc != 0:
        print(f"  [FAIL] expected rc=0, got {rc}")
        return False
    payload = _parse_json_or_fail(out, "path --to no-path payload")
    if payload is None:
        return False
    if payload.get("hops") != []:
        print(f"  [FAIL] hops should be empty: {payload.get('hops')!r}")
        return False
    print("  [ok] path --to: no-path case returns empty hops")
    return True


def fixture_g_fakes_path_up_walks_ancestors(
    args: argparse.Namespace,
) -> bool:
    """``path --up C`` returns ancestors via parents() walk."""
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        _setup_path_sandbox(tmp)
        rc, out, _ = _run_db_graph(
            [
                "path",
                "--up",
                "fakepath:C",
                "--import",
                "fakepath",
            ],
            python_env=args.python_env,
            extra_env={"PYTHONPATH": str(tmp)},
        )
    if rc != 0:
        print(f"  [FAIL] expected rc=0, got {rc}")
        return False
    payload = _parse_json_or_fail(out, "path --up payload")
    if payload is None:
        return False
    if payload.get("query", {}).get("mode") != "ancestors":
        print("  [FAIL] query.mode != 'ancestors'")
        return False
    nodes_by_name = {
        n["full_table_name"]: n for n in payload.get("nodes", [])
    }
    if sorted(nodes_by_name.keys()) != [
        "fakepath.a",
        "fakepath.b",
        "fakepath.c",
    ]:
        print(f"  [FAIL] node set drift: {sorted(nodes_by_name.keys())!r}")
        return False
    if nodes_by_name["fakepath.c"]["depth"] != 0:
        print(f"  [FAIL] root depth != 0: {nodes_by_name['fakepath.c']!r}")
        return False
    if nodes_by_name["fakepath.a"]["depth"] != 2:
        print(
            f"  [FAIL] grandparent depth != 2: "
            f"{nodes_by_name['fakepath.a']!r}"
        )
        return False
    edges = payload.get("edges", [])
    edge_pairs = sorted((e["parent"], e["child"]) for e in edges)
    if edge_pairs != [
        ("fakepath.a", "fakepath.b"),
        ("fakepath.b", "fakepath.c"),
    ]:
        print(f"  [FAIL] edge drift: {edge_pairs!r}")
        return False
    print(
        f"  [ok] path --up C: 3 nodes (A, B, C) at depths 2/1/0; "
        f"{len(edges)} parent→child edges"
    )
    return True


def fixture_g_fakes_path_down_walks_descendants(
    args: argparse.Namespace,
) -> bool:
    """``path --down A`` returns descendants via children() walk."""
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        _setup_path_sandbox(tmp)
        rc, out, _ = _run_db_graph(
            [
                "path",
                "--down",
                "fakepath:A",
                "--import",
                "fakepath",
            ],
            python_env=args.python_env,
            extra_env={"PYTHONPATH": str(tmp)},
        )
    if rc != 0:
        print(f"  [FAIL] expected rc=0, got {rc}")
        return False
    payload = _parse_json_or_fail(out, "path --down payload")
    if payload is None:
        return False
    if payload.get("query", {}).get("mode") != "descendants":
        print("  [FAIL] query.mode != 'descendants'")
        return False
    nodes = payload.get("nodes", [])
    if len(nodes) != 3:
        print(f"  [FAIL] expected 3 nodes, got {len(nodes)}")
        return False
    print(
        "  [ok] path --down A: 3 nodes reachable downstream "
        "(depth ≤ 2)"
    )
    return True


def fixture_g_fakes_path_max_depth_truncates(
    args: argparse.Namespace,
) -> bool:
    """``--max-depth 1`` on a 3-node chain marks the walk truncated."""
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        _setup_path_sandbox(tmp)
        rc, out, _ = _run_db_graph(
            [
                "path",
                "--down",
                "fakepath:A",
                "--max-depth",
                "1",
                "--import",
                "fakepath",
            ],
            python_env=args.python_env,
            extra_env={"PYTHONPATH": str(tmp)},
        )
    if rc != 0:
        print(f"  [FAIL] expected rc=0, got {rc}")
        return False
    payload = _parse_json_or_fail(out, "path --down truncated payload")
    if payload is None:
        return False
    if not payload.get("truncated"):
        print(f"  [FAIL] truncated should be true: {payload.get('truncated')!r}")
        return False
    if payload.get("truncated_at_depth") != 1:
        print(
            f"  [FAIL] truncated_at_depth != 1: "
            f"{payload.get('truncated_at_depth')!r}"
        )
        return False
    nodes = payload.get("nodes", [])
    # With max-depth=1: A (depth 0) is enqueued, expanded; B (depth 1) is
    # added but not expanded (its depth >= max_depth). C is unreachable.
    names = {n["full_table_name"] for n in nodes}
    if names != {"fakepath.a", "fakepath.b"}:
        print(f"  [FAIL] truncated walk should reach A + B only: {names!r}")
        return False
    print(
        "  [ok] --max-depth 1: walk truncated at depth 1; "
        "B reached but not expanded"
    )
    return True


def fixture_g_fakes_path_to_incomplete_when_traversal_errors(
    args: argparse.Namespace,
) -> bool:
    """``--to`` distinguishes "no path exists" from "traversal incomplete".

    Builds the A → B → C chain, then patches the fake datajoint
    FreeTable so ``children()`` raises for ``fakepath.a``. The BFS
    starts at A, fails to expand it, and reports ``hops: []`` —
    indistinguishable from "no path" without the new ``incomplete``
    discriminator. The fixture asserts ``incomplete: true`` plus an
    ``errors`` entry pointing at the failed node, so an LLM can tell
    the two cases apart.
    """
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        _setup_path_sandbox(tmp)
        # Append a poison module that monkeypatches FreeTable.children
        # to raise when called on fakepath.a. Importing this module
        # via --import installs the monkeypatch before db_graph's
        # path BFS calls FreeTable.
        (tmp / "poison_fakepath_a.py").write_text(
            "\n".join(
                [
                    "import datajoint as dj",
                    "",
                    "_orig_children = dj.FreeTable.children",
                    "",
                    "def _patched_children(self):",
                    "    if self.full_table_name == 'fakepath.a':",
                    "        raise RuntimeError("
                    "'synthetic neighbor lookup failure for fakepath.a')",
                    "    return _orig_children(self)",
                    "",
                    "dj.FreeTable.children = _patched_children",
                ]
            )
        )
        rc, out, err = _run_db_graph(
            [
                "path",
                "--to",
                "fakepath:A",
                "fakepath:C",
                "--import",
                "fakepath",
                "--import",
                "poison_fakepath_a",
            ],
            python_env=args.python_env,
            extra_env={"PYTHONPATH": str(tmp)},
        )
    if rc != 0:
        print(f"  [FAIL] expected rc=0, got {rc}; stderr: {err[:200]!r}")
        return False
    payload = _parse_json_or_fail(out, "path --to incomplete payload")
    if payload is None:
        return False
    if payload.get("hops") != []:
        print(
            f"  [FAIL] hops should be empty (BFS could not reach C): "
            f"{payload.get('hops')!r}"
        )
        return False
    if payload.get("incomplete") is not True:
        print(
            f"  [FAIL] incomplete should be True (BFS hit a failure): "
            f"{payload.get('incomplete')!r}"
        )
        return False
    errors = payload.get("errors", [])
    err_names = [e.get("full_table_name") for e in errors]
    if "fakepath.a" not in err_names:
        print(
            f"  [FAIL] errors should include fakepath.a; got "
            f"{err_names!r}"
        )
        return False
    print(
        "  [ok] path --to: traversal failure at fakepath.a → hops:[], "
        "incomplete:true, errors lists the failed node"
    )
    return True


def fixture_g_fakes_path_walk_incomplete_when_neighbor_errors(
    args: argparse.Namespace,
) -> bool:
    """``--down`` walks set incomplete=true when a node's children() raises."""
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        _setup_path_sandbox(tmp)
        (tmp / "poison_fakepath_b.py").write_text(
            "\n".join(
                [
                    "import datajoint as dj",
                    "",
                    "_orig_children = dj.FreeTable.children",
                    "",
                    "def _patched_children(self):",
                    "    if self.full_table_name == 'fakepath.b':",
                    "        raise RuntimeError("
                    "'synthetic neighbor lookup failure for fakepath.b')",
                    "    return _orig_children(self)",
                    "",
                    "dj.FreeTable.children = _patched_children",
                ]
            )
        )
        rc, out, _ = _run_db_graph(
            [
                "path",
                "--down",
                "fakepath:A",
                "--import",
                "fakepath",
                "--import",
                "poison_fakepath_b",
            ],
            python_env=args.python_env,
            extra_env={"PYTHONPATH": str(tmp)},
        )
    if rc != 0:
        print(f"  [FAIL] expected rc=0, got {rc}")
        return False
    payload = _parse_json_or_fail(out, "path walk-incomplete payload")
    if payload is None:
        return False
    if not payload.get("incomplete"):
        print(
            f"  [FAIL] incomplete should be True: "
            f"{payload.get('incomplete')!r}"
        )
        return False
    errors = payload.get("errors", [])
    err_names = [e.get("full_table_name") for e in errors]
    if "fakepath.b" not in err_names:
        print(
            f"  [FAIL] errors should include fakepath.b; got "
            f"{err_names!r}"
        )
        return False
    nodes_by_name = {n["full_table_name"]: n for n in payload.get("nodes", [])}
    if not nodes_by_name.get("fakepath.b", {}).get("error"):
        print("  [FAIL] node fakepath.b should have a non-null error")
        return False
    print(
        "  [ok] path --down: per-node error + top-level errors + "
        "incomplete=true on neighbor failure"
    )
    return True


def fixture_g_fakes_path_schema_error_carries_input_context(
    args: argparse.Namespace,
) -> bool:
    """A class that resolves but lacks ``full_table_name`` exits with a
    structured ``db_error`` (kind=schema). The failure payload must
    carry the user's path-mode inputs (``query.up`` / ``query.from`` /
    ``query.to``) so an LLM can act on it without re-parsing the
    command line — and it must NOT crash with an AttributeError when
    the path namespace has no ``--class``.
    """
    import fakes as _fakes_module

    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        _fakes_module.prepare_sandbox(tmp)
        (tmp / "nofull.py").write_text(
            "\n".join(
                [
                    "import datajoint",
                    "",
                    "class NoFull(datajoint.user_tables.UserTable):",
                    "    definition = 'id: int'",
                ]
            )
        )

        rc_up, out_up, err_up = _run_db_graph(
            [
                "path",
                "--import",
                "nofull",
                "--up",
                "nofull:NoFull",
            ],
            python_env=args.python_env,
            extra_env={"PYTHONPATH": str(tmp)},
        )
        rc_to, out_to, err_to = _run_db_graph(
            [
                "path",
                "--import",
                "nofull",
                "--to",
                "nofull:NoFull",
                "nofull:NoFull",
            ],
            python_env=args.python_env,
            extra_env={"PYTHONPATH": str(tmp)},
        )

    if rc_up != 5:
        print(
            f"  [FAIL] --up no-full_table_name: expected rc=5, got "
            f"{rc_up}; stderr: {err_up[:200]!r}"
        )
        return False
    if rc_to != 5:
        print(
            f"  [FAIL] --to no-full_table_name: expected rc=5, got "
            f"{rc_to}; stderr: {err_to[:200]!r}"
        )
        return False
    payload_up = _parse_json_or_fail(out_up, "path --up schema-error payload")
    payload_to = _parse_json_or_fail(out_to, "path --to schema-error payload")
    if payload_up is None or payload_to is None:
        return False
    if payload_up.get("kind") != "db_error":
        print(f"  [FAIL] --up kind != 'db_error': {payload_up.get('kind')!r}")
        return False
    if payload_to.get("kind") != "db_error":
        print(f"  [FAIL] --to kind != 'db_error': {payload_to.get('kind')!r}")
        return False
    if payload_up.get("error", {}).get("kind") != "schema":
        print(
            f"  [FAIL] --up error.kind != 'schema': "
            f"{payload_up.get('error', {})!r}"
        )
        return False
    query_up = payload_up.get("query", {})
    if query_up.get("up") != "nofull:NoFull":
        print(
            f"  [FAIL] --up payload missing query.up: {query_up!r}"
        )
        return False
    query_to = payload_to.get("query", {})
    if query_to.get("from") != "nofull:NoFull" or query_to.get("to") != "nofull:NoFull":
        print(
            f"  [FAIL] --to payload missing query.from / query.to: "
            f"{query_to!r}"
        )
        return False
    print(
        "  [ok] path schema-error payload carries query.up / query.from / "
        "query.to (no AttributeError when --class is absent)"
    )
    return True


def fixture_g_path_advertised_in_info(
    args: argparse.Namespace,
) -> bool:
    """``info --json`` advertises path with the documented contract."""
    rc, out, err = _run_db_graph(["info", "--json"], python_env=args.python_env)
    if rc != 0:
        print(f"  [FAIL] info exited {rc}; stderr: {err!r}")
        return False
    payload = _parse_json_or_fail(out, "info for path")
    if payload is None:
        return False
    if "path" not in payload.get("subcommands", {}):
        print(
            f"  [FAIL] subcommands missing path; got "
            f"{sorted(payload.get('subcommands', {}).keys())}"
        )
        return False
    if "path" not in payload.get("payload_envelopes", {}):
        print("  [FAIL] payload_envelopes missing path")
        return False
    if "path" not in payload.get("result_shapes", []):
        print(
            f"  [FAIL] result_shapes missing 'path'; got "
            f"{payload.get('result_shapes')!r}"
        )
        return False
    print(
        "  [ok] info --json: subcommands.path + payload_envelopes.path "
        "+ result_shapes 'path' all present"
    )
    return True


def fixture_g_eval_path_session_descendants(
    args: argparse.Namespace,
) -> bool:
    """Live: ``path --down Session --max-depth 2`` returns a non-empty walk.

    Spyglass.Session has many downstream tables (IntervalList, Electrode,
    Raw, ...). The fixture only verifies the walk produced any nodes
    and edges within depth 2, since the exact set varies with the
    Spyglass schema snapshot.
    """
    if not _require_capability(
        args, datajoint=True, spyglass=True,
        why="live path --down Session against real Spyglass DB",
    ):
        return True
    rc, out, err = _run_db_graph(
        ["path", "--down", "Session", "--max-depth", "2"],
        python_env=args.python_env,
    )
    if rc != 0:
        print(f"  [FAIL] expected rc=0, got {rc}; stderr: {err[:200]!r}")
        return False
    payload = _parse_json_or_fail(out, "live path --down Session")
    if payload is None:
        return False
    nodes = payload.get("nodes", [])
    edges = payload.get("edges", [])
    if len(nodes) < 2:
        print(
            f"  [FAIL] expected at least 2 nodes downstream of Session, "
            f"got {len(nodes)}"
        )
        return False
    if not edges:
        print("  [FAIL] expected at least one parent→child edge")
        return False
    print(
        f"  [ok] live path --down Session: {len(nodes)} nodes, "
        f"{len(edges)} edges (depth ≤ 2)"
    )
    return True


def fixture_d_eval50_silent_wrong_count_footgun_refused(
    args: argparse.Namespace,
) -> bool:
    """Eval #50: ``DecodingOutput & {nwb_file_name: X}`` is refused.

    Without merge-aware mode, restricting the merge master by a part-
    only field is the canonical silent-wrong-count footgun. Field
    validation against the master heading must refuse it because
    ``nwb_file_name`` is not in ``DecodingOutput.heading.names``.
    """
    if not _require_capability(
        args, datajoint=True, spyglass=True,
        why="eval #50 silent-no-op refusal against real DecodingOutput heading",
    ):
        return True
    rc, out, err = _run_db_graph(
        [
            "find-instance",
            "--class",
            "DecodingOutput",
            "--key",
            "nwb_file_name=j1620210710_.nwb",
        ],
        python_env=args.python_env,
    )
    if rc != 2:
        print(f"  [FAIL] expected rc=2 (invalid_query), got {rc}; stderr: {err[:200]!r}")
        return False
    payload = _parse_json_or_fail(out, "eval #50 refusal payload")
    if payload is None:
        return False
    if payload.get("kind") != "invalid_query":
        print(f"  [FAIL] kind != 'invalid_query': {payload.get('kind')!r}")
        return False
    if payload.get("error", {}).get("kind") != "unknown_field":
        print(f"  [FAIL] error.kind != 'unknown_field': {payload.get('error', {})!r}")
        return False
    if "nwb_file_name" not in payload.get("error", {}).get("unknown_fields", []):
        print(
            f"  [FAIL] unknown_fields should list nwb_file_name: "
            f"{payload.get('error', {}).get('unknown_fields')!r}"
        )
        return False
    print(
        "  [ok] eval #50: silent-wrong-count footgun closed — DecodingOutput "
        "& {nwb_file_name: X} exits 2 with kind=invalid_query"
    )
    return True


def fixture_c_empty_result_fail_on_empty_exit_seven(
    args: argparse.Namespace,
) -> bool:
    """``--fail-on-empty`` opts into exit 7 on an otherwise-successful empty query."""
    if not _require_capability(
        args, datajoint=True, spyglass=True,
        why="--fail-on-empty round-trip needs a real Spyglass query",
    ):
        return True
    rc, out, _ = _run_db_graph(
        [
            "find-instance",
            "--class",
            "Session",
            "--key",
            "nwb_file_name=__definitely_not_a_real_session__.nwb",
            "--fields",
            "KEY",
            "--fail-on-empty",
        ],
        python_env=args.python_env,
    )
    if rc != 7:
        print(f"  [FAIL] expected rc=7, got {rc}")
        return False
    payload = _parse_json_or_fail(out, "fail-on-empty payload")
    if payload is None:
        return False
    if payload.get("count") != 0:
        print(f"  [FAIL] count != 0: {payload.get('count')!r}")
        return False
    print("  [ok] --fail-on-empty + count=0 → exit 7")
    return True


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


FIXTURES = [
    # Batch A — info contract + cross-flag validation
    fixture_info_emits_valid_json,
    fixture_info_field_order_is_stable,
    fixture_info_advertises_required_contract_fields,
    fixture_info_payload_envelopes_pin_field_order,
    fixture_info_runs_without_datajoint,
    fixture_find_instance_emits_db_error_when_datajoint_missing,
    fixture_emitted_kind_always_appears_in_payload_envelopes,
    fixture_merge_master_without_part_exits_2,
    fixture_aggregate_modes_require_count_distinct,
    fixture_count_distinct_requires_a_grouping,
    fixture_group_by_and_group_by_table_are_mutually_exclusive,
    fixture_limit_hard_max_enforced,
    fixture_unknown_subcommand_exits_2,
    # Batch B — class resolution
    fixture_b_resolves_stock_short_name,
    fixture_b_resolves_dotted_qualname,
    fixture_b_resolves_module_class_form,
    fixture_b_resolves_dotted_module_path,
    fixture_b_resolves_via_import_for_custom_class,
    fixture_b_ambiguous_short_name_exits_3,
    fixture_b_not_found_exits_4,
    fixture_b_not_a_table_exits_4,
    fixture_b_src_overrides_installed_package,
    fixture_b_installed_package_overrides_env_var,
    # Batch C — basic find-instance (fakes sandbox: no live DB needed)
    fixture_c_fakes_restriction_and_fetch,
    fixture_c_fakes_count_only,
    fixture_c_fakes_truncation_marker,
    fixture_c_fakes_unknown_field_validation,
    fixture_c_fakes_blob_restriction_refused,
    fixture_c_fakes_safe_serialization_envelopes,
    fixture_c_fakes_nan_restriction_refused,
    fixture_c_fakes_db_error_classification,
    # Batch D — merge-aware lookup (fakes sandbox)
    fixture_d_fakes_merge_routes_part_only_field_to_part,
    fixture_d_fakes_merge_count_unbounded_by_limit,
    fixture_d_fakes_merge_ids_dedup_when_part_rows_share_master,
    fixture_d_fakes_merge_rows_pagination_dedupes_master_keys,
    fixture_d_fakes_merge_master_only_field_silent_no_op_refused,
    fixture_d_fakes_merge_part_master_mismatch_exits_3,
    fixture_d_fakes_merge_count_only,
    fixture_d_set_op_flags_mutually_exclusive,
    fixture_d_set_op_with_grouping_refused,
    fixture_d_merge_error_payload_carries_merge_context,
    # Batch E — set ops + grouped counts (fakes sandbox)
    fixture_e_fakes_intersect_returns_shared_keys,
    fixture_e_fakes_except_returns_left_minus_right,
    fixture_e_fakes_join_validates_output_fields,
    fixture_e_fakes_intersect_secondary_only_overlap_refused,
    fixture_e_fakes_setop_restriction_routes_to_partner,
    fixture_e_fakes_setop_failure_carries_set_op_context,
    fixture_e_fakes_zero_overlap_set_op_refused,
    fixture_e_fakes_group_by_table_eval19_shape,
    fixture_e_fakes_group_by_explicit_fields,
    fixture_e_fakes_count_distinct_field_must_be_on_counted,
    # Batch E — live Spyglass evals
    fixture_e_eval17_intersect_sessions_in_both,
    fixture_e_eval18_except_sessions_only_in_left,
    fixture_e_eval19_per_session_distinct_tetrodes,
    fixture_e_eval28_29_join_to_brain_region,
    # Batch F — describe (runtime introspection)
    fixture_f_fakes_describe_returns_heading_and_adjacency,
    fixture_f_fakes_describe_omits_count_by_default,
    fixture_f_fakes_describe_errored_metadata_reported_as_error,
    fixture_f_fakes_describe_unavailable_metadata_distinguished,
    fixture_f_describe_advertised_in_info,
    fixture_f_eval_describe_session,
    # Batch G — path (runtime graph traversal)
    fixture_g_fakes_path_to_finds_chain,
    fixture_g_fakes_path_to_no_path_returns_empty,
    fixture_g_fakes_path_up_walks_ancestors,
    fixture_g_fakes_path_down_walks_descendants,
    fixture_g_fakes_path_max_depth_truncates,
    fixture_g_fakes_path_to_incomplete_when_traversal_errors,
    fixture_g_fakes_path_walk_incomplete_when_neighbor_errors,
    fixture_g_fakes_path_schema_error_carries_input_context,
    fixture_g_path_advertised_in_info,
    fixture_g_eval_path_session_descendants,
    # Batch D — live Spyglass evals
    fixture_d_eval14_trodes_position_merge_id,
    fixture_d_eval15_lfp_merge_id_via_lfpv1,
    fixture_d_eval16_decoding_output_merge_id,
    fixture_d_eval50_silent_wrong_count_footgun_refused,
    # Batch C — static-source / parser fixtures
    fixture_c_no_restrgraph_or_tablechain_in_source,
    fixture_c_read_only_no_write_method_calls_in_source,
    fixture_c_unknown_restriction_field_refused,
    fixture_c_blob_restriction_refused,
    fixture_c_null_key_value_refused,
    fixture_c_null_keyjson_value_refused,
    fixture_c_keyjson_non_finite_value_refused,
    fixture_c_fakes_nested_non_finite_in_fetched_rows_envelopes,
    fixture_c_fakes_blob_dict_with_non_string_keys_envelopes,
    fixture_c_fields_key_mixed_with_explicit_fields_refused,
    fixture_c_malformed_key_argument_refused,
    fixture_c_unknown_fetch_field_refused,
    fixture_c_eval9_session_row_lookup,
    fixture_c_eval10_selected_fields,
    fixture_c_eval11_field_list,
    fixture_c_eval12_count_only,
    fixture_c_eval13_key_only_resolves_merge_evidence,
    fixture_c_limit_truncation_marker,
    fixture_c_empty_result_exit_zero_by_default,
    fixture_c_empty_result_fail_on_empty_exit_seven,
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--spyglass-src",
        type=Path,
        default=None,
        help=(
            "Path to spyglass src/ directory. Parity with sibling test files; "
            "fixtures that exercise the source-only path do not consume this."
        ),
    )
    parser.add_argument(
        "--python-env",
        default=sys.executable,
        help=(
            "Python interpreter for subprocess invocations. Defaults to "
            "sys.executable. db_graph.py imports DataJoint and Spyglass "
            "lazily on the find-instance path; fixtures that exercise the "
            "real resolution path skip cleanly when --python-env lacks "
            "those packages."
        ),
    )
    parser.add_argument(
        "--require-capabilities",
        action="store_true",
        help=(
            "Treat missing python_env capabilities (datajoint, spyglass) "
            "as failure instead of skip. Pass this in CI / pre-commit so "
            "an environment that cannot exercise the resolution path does "
            "not silently report '23/23 passed'."
        ),
    )
    args = parser.parse_args()

    # Capability detection: pre-compute once so per-fixture invocations
    # stay free. Resolution fixtures gate on these flags.
    args.has_datajoint = _python_can_import(args.python_env, "datajoint")
    args.has_spyglass = _python_can_import(args.python_env, "spyglass")

    print(
        f"Running {len(FIXTURES)} db_graph fixtures with "
        f"python_env={args.python_env} "
        f"(datajoint={args.has_datajoint}, spyglass={args.has_spyglass}, "
        f"require_capabilities={args.require_capabilities})..."
    )
    passed = 0
    skipped = 0
    failed = 0
    for fixture in FIXTURES:
        print(f"\n{fixture.__name__}:")
        # Reset per-fixture markers before invocation; _require_capability
        # sets exactly one of them when capabilities are missing.
        args._last_skip_reason = ""
        args._last_fail_reason = ""
        try:
            ok = fixture(args)
        except Exception as exc:
            print(f"  [FAIL] uncaught exception: {type(exc).__name__}: {exc}")
            ok = False
        # `getattr` keeps the type checker honest — without it, ty narrows
        # away the elif branches because it cannot follow attribute mutation
        # through the _require_capability call inside the fixture.
        skip_reason = getattr(args, "_last_skip_reason", "")
        fail_reason = getattr(args, "_last_fail_reason", "")
        if not ok or fail_reason:
            failed += 1
        elif skip_reason:
            skipped += 1
        else:
            passed += 1
    print(f"\n{'=' * 60}")
    total = len(FIXTURES)
    summary = f"{passed} passed, {skipped} skipped, {failed} failed (of {total})"
    print(summary)
    if skipped and not args.require_capabilities:
        print(
            "  (skipped fixtures gated on python_env capabilities; pass "
            "--require-capabilities to make them fail-loud)"
        )
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
