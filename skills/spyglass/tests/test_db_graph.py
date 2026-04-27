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
    rc, out, err = _run_db_graph(
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
    rc, out, err = _run_db_graph(
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
    rc, out, err = _run_db_graph(
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
    rc, out, err = _run_db_graph(["bogus"], python_env=args.python_env)
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
    """Shared assertion: Batch-B `not_implemented`/`stage:resolved` payload.

    Pulled out because four fixtures emit the same envelope with different
    `query` fields. Pinning the assertion in one place lets Batch C's
    real-query implementation update one site. db_graph.py emits every
    structured payload (success and error) to stdout — DataJoint and
    Spyglass write warnings + connection logs to stderr, so reading
    stdout is the only way to get clean JSON.
    """
    payload = _parse_json_or_fail(out, "find-instance resolved stdout")
    if payload is None:
        return False
    if payload.get("kind") != "not_implemented":
        print(f"  [FAIL] kind != 'not_implemented': {payload.get('kind')!r}")
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
    if query.get("stage") != "resolved":
        print(f"  [FAIL] query.stage != 'resolved': {query.get('stage')!r}")
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
    if rc != 2:  # Batch-B success endpoint exits 2 (kind=not_implemented)
        print(f"  [FAIL] expected rc=2, got {rc}; stderr: {err[:200]!r}")
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
    if rc != 2:
        print(f"  [FAIL] expected rc=2, got {rc}; stderr: {err[:200]!r}")
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
    if rc != 2:
        print(f"  [FAIL] expected rc=2, got {rc}; stderr: {err[:200]!r}")
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
    if rc != 2:
        print(f"  [FAIL] expected rc=2, got {rc}; stderr: {err[:200]!r}")
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
    if rc != 2:
        print(f"  [FAIL] expected rc=2, got {rc}; stderr: {err[:200]!r}")
        return False
    if not _expect_resolved_payload(
        out,
        expected_module="customlab_db_graph",
        expected_qualname="CustomTable",
        expected_resolution_source="module_path",
    ):
        return False
    print("  [ok] --import + module:Class resolves a custom UserTable")
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
    if rc != 2:
        print(
            f"  [FAIL] expected rc=2 (resolved via installed fallback), "
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
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--spyglass-src",
        type=Path,
        default=None,
        help=(
            "Path to spyglass src/ directory. Parity with sibling test files; "
            "Batch A fixtures do not consume this."
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
            "an environment that cannot exercise Batch-B resolution does "
            "not silently report '23/23 passed'."
        ),
    )
    args = parser.parse_args()

    # Capability detection: pre-compute once so per-fixture invocations
    # stay free. The Batch B resolution fixtures gate on these flags.
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
