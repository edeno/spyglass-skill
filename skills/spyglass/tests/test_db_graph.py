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
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
DB_GRAPH = SCRIPT_DIR / "db_graph.py"


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


def fixture_find_instance_stub_emits_structured_error(
    args: argparse.Namespace,
) -> bool:
    """Batch A scaffold: find-instance returns a structured error, exit 2.

    Pins the contract for the stub so Batch C does not silently drift
    the envelope when it replaces this with a real implementation. The
    top-level ``kind`` is ``"not_implemented"`` (not the generic ``"error"``)
    so an LLM can distinguish a build-incomplete stub from a runtime DB
    failure (which uses ``kind: "db_error"`` in later batches).
    """
    rc, out, err = _run_db_graph(
        ["find-instance", "--class", "Session", "--key", "nwb_file_name=foo.nwb"],
        python_env=args.python_env,
    )
    if rc != 2:
        print(f"  [FAIL] expected rc=2 (usage), got {rc}; stderr: {err[:200]!r}")
        return False
    if out.strip():
        # The stub must keep stdout clean — error envelope goes to stderr so
        # callers piping `... | jq` on a normal-success path do not see a
        # mixed-content stream.
        print(f"  [FAIL] stub leaked content to stdout: {out[:200]!r}")
        return False
    payload = _parse_json_or_fail(err, "find-instance stub stderr")
    if payload is None:
        # The stub writes to stderr; if that's also not JSON we have a problem.
        return False
    if payload.get("schema_version") != 1:
        print(f"  [FAIL] schema_version != 1: {payload.get('schema_version')!r}")
        return False
    if payload.get("kind") != "not_implemented":
        print(
            f"  [FAIL] top-level kind != 'not_implemented': "
            f"{payload.get('kind')!r}"
        )
        return False
    if payload.get("graph") != "db":
        print(f"  [FAIL] graph != 'db': {payload.get('graph')!r}")
        return False
    if payload.get("authority") != "runtime-db":
        print(f"  [FAIL] authority != 'runtime-db': {payload.get('authority')!r}")
        return False
    error = payload.get("error", {})
    if error.get("kind") != "not_implemented":
        print(f"  [FAIL] error.kind != 'not_implemented': {error.get('kind')!r}")
        return False
    timings = payload.get("timings_ms", {})
    if "total" not in timings:
        print(f"  [FAIL] timings_ms.total missing on stub payload: {timings!r}")
        return False
    print(
        "  [ok] find-instance stub: kind='not_implemented', exit 2, "
        "timings_ms.total present"
    )
    return True


def fixture_stub_kind_appears_in_payload_envelopes(
    args: argparse.Namespace,
) -> bool:
    """Every JSON shape the tool emits must be documented in info.payload_envelopes.

    `info --json` is the contract source of truth. If the stub emits a
    ``kind`` that does not appear in ``payload_envelopes``, an LLM
    consuming the contract has no shape to validate the actual payload
    against. This fixture binds the rule for the Batch A stub; it stays
    relevant for every shape the tool emits in later batches.
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

    rc_stub, _, err_stub = _run_db_graph(
        ["find-instance", "--class", "Session", "--key", "nwb_file_name=foo.nwb"],
        python_env=args.python_env,
    )
    if rc_stub != 2:
        print(f"  [FAIL] stub exit code drifted: {rc_stub}")
        return False
    stub = _parse_json_or_fail(err_stub, "find-instance stub stderr")
    if stub is None:
        return False
    stub_kind = stub.get("kind")
    if stub_kind not in envelopes:
        print(
            f"  [FAIL] stub emitted kind={stub_kind!r}, but "
            f"payload_envelopes does not document it. Documented kinds: "
            f"{sorted(envelopes.keys())}"
        )
        return False
    # The stub's actual top-level field order should match the documented
    # envelope. Otherwise the contract drifts silently.
    documented = envelopes[stub_kind]
    actual = list(stub.keys())
    if actual != documented:
        print("  [FAIL] stub field order does not match documented envelope")
        print(f"         envelope[{stub_kind!r}]: {documented}")
        print(f"         stub keys           : {actual}")
        return False
    print(
        f"  [ok] stub kind={stub_kind!r} appears in payload_envelopes "
        "and matches its field order"
    )
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


FIXTURES = [
    fixture_info_emits_valid_json,
    fixture_info_field_order_is_stable,
    fixture_info_advertises_required_contract_fields,
    fixture_info_payload_envelopes_pin_field_order,
    fixture_info_runs_without_datajoint,
    fixture_find_instance_stub_emits_structured_error,
    fixture_stub_kind_appears_in_payload_envelopes,
    fixture_merge_master_without_part_exits_2,
    fixture_aggregate_modes_require_count_distinct,
    fixture_count_distinct_requires_a_grouping,
    fixture_group_by_and_group_by_table_are_mutually_exclusive,
    fixture_limit_hard_max_enforced,
    fixture_unknown_subcommand_exits_2,
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
            "lazily on the find-instance path, so most Batch A fixtures "
            "pass with the system python."
        ),
    )
    args = parser.parse_args()
    print(f"Running {len(FIXTURES)} db_graph fixtures with python_env={args.python_env}...")
    passed = 0
    for fixture in FIXTURES:
        print(f"\n{fixture.__name__}:")
        try:
            ok = fixture(args)
        except Exception as exc:
            print(f"  [FAIL] uncaught exception: {type(exc).__name__}: {exc}")
            ok = False
        if ok:
            passed += 1
    print(f"\n{'=' * 60}")
    print(f"{passed}/{len(FIXTURES)} fixtures passed")
    return 0 if passed == len(FIXTURES) else 1


if __name__ == "__main__":
    sys.exit(main())
