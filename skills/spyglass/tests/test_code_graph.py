#!/usr/bin/env python3
"""Tool-contract tests for ``code_graph.py`` and ``_index.py``.

Pins the JSON output schema (``schema_version: 1``) for ``code_graph.py``'s
three subcommands against synthetic Spyglass-shaped trees. Reusing
``test_validator_regressions.py`` would conflate the validator's
"drift-detection on shipped reference content" job with ``code_graph.py``'s
"output contract" job; keeping them separate matches the docs/plans/
code-graph-impl-plan.md decision.

Run::

    python skills/spyglass/tests/test_code_graph.py --spyglass-src PATH

Same CLI shape as ``test_validator_regressions.py`` — exits 0 if every
fixture passes, 1 otherwise. ``--spyglass-src`` is required by argparse
parity with the sibling test file but not consumed by every fixture
(synthetic trees stand in for real Spyglass for most assertions).
"""

import argparse
import json
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
CODE_GRAPH = SCRIPT_DIR / "code_graph.py"


def _run_code_graph(args: list[str]) -> tuple[int, str, str]:
    """Run ``code_graph.py`` with ``args``, return ``(returncode, stdout, stderr)``."""
    proc = subprocess.run(
        ["python3", str(CODE_GRAPH), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _write_fakepipe(tmp: Path, files: dict[str, str]) -> Path:
    """Write a synthetic spyglass tree under ``tmp``.

    Each entry in ``files`` maps a relative path under ``spyglass/`` to its
    file contents (after ``textwrap.dedent``). Returns the directory to pass
    as ``--src``.
    """
    for rel, body in files.items():
        path = tmp / "spyglass" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(body))
    return tmp


def _parse_json_or_fail(stdout: str, label: str) -> dict | None:
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as e:
        print(f"  [FAIL] {label}: stdout is not valid JSON: {e}")
        print(f"         stdout: {stdout[:400]!r}")
        return None


def fixture_path_finds_direct_fk_path(src_root: Path) -> bool:
    """`code_graph.py path --to A C` returns kind=path, hops=[A, B, C]."""
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        _write_fakepipe(tmp, {
            "fakepipe/v1/foo.py": '''
                class A:
                    definition = """
                    id: int
                    ---
                    """
                class B:
                    definition = """
                    -> A
                    id: int
                    ---
                    """
                class C:
                    definition = """
                    -> B
                    id: int
                    ---
                    """
            ''',
        })
        rc, out, err = _run_code_graph(
            ["--src", str(tmp), "path", "--to", "A", "C", "--json"]
        )
        if rc != 0:
            print(f"  [FAIL] exited {rc}; stderr: {err!r}")
            return False
        payload = _parse_json_or_fail(out, "path --to A C")
        if payload is None:
            return False
        if payload.get("schema_version") != 1:
            print(f"  [FAIL] schema_version != 1: {payload.get('schema_version')!r}")
            return False
        if payload.get("kind") != "path":
            print(f"  [FAIL] kind != 'path': {payload.get('kind')!r}")
            return False
        hops = payload.get("hops", [])
        qualnames = [h["qualname"] for h in hops]
        if qualnames != ["A", "B", "C"]:
            print(f"  [FAIL] hop qualnames != [A, B, C]: {qualnames!r}")
            return False
        for h in hops:
            for k in ("name", "qualname", "file", "line", "kind", "evidence"):
                if k not in h:
                    print(f"  [FAIL] hop missing field {k!r}: {h!r}")
                    return False
    print("  [ok] path --to: direct FK chain rendered as 3 hops with full schema")
    return True


def fixture_path_names_merge_master_hop(src_root: Path) -> bool:
    """Merge-master containment surfaces explicitly (eval 81 closure shape)."""
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        _write_fakepipe(tmp, {
            "utils/dj_merge_tables.py": '''
                class _Merge:
                    pass
            ''',
            "fakepipe/merge.py": '''
                from spyglass.utils.dj_merge_tables import _Merge
                class Upstream:
                    definition = """
                    id: int
                    ---
                    """
                class MergeMaster(_Merge):
                    definition = """
                    merge_id: uuid
                    ---
                    """
                    class Upstream:
                        definition = """
                        -> master
                        -> Upstream
                        ---
                        """
                class Downstream:
                    definition = """
                    -> MergeMaster.proj(merge_id='upstream_merge_id')
                    id: int
                    ---
                    """
            ''',
        })
        rc, out, err = _run_code_graph(
            ["--src", str(tmp), "path", "--to", "Upstream", "Downstream", "--json"]
        )
        if rc != 0:
            print(f"  [FAIL] exited {rc}; stderr: {err!r}")
            return False
        payload = _parse_json_or_fail(out, "merge-master path")
        if payload is None:
            return False
        if payload.get("kind") != "path":
            print(f"  [FAIL] kind != 'path': {payload.get('kind')!r}")
            return False
        qualnames = [h["qualname"] for h in payload.get("hops", [])]
        # The chain must include MergeMaster.Upstream as an explicit hop;
        # Upstream → Downstream directly would be elision (eval 81).
        if "MergeMaster.Upstream" not in qualnames:
            print(f"  [FAIL] merge-part hop elided: {qualnames!r}")
            return False
        # Find an edge with kind in the merge-part / proj family.
        kinds = {h["kind"] for h in payload.get("hops", [])}
        if not kinds & {"merge_part", "nested_part", "proj"}:
            print(f"  [FAIL] no merge_part / nested_part / proj kind in chain: {kinds!r}")
            return False
    print("  [ok] path --to: merge-master hop named explicitly with structural kind")
    return True


def fixture_path_disambiguates_multi_file_class(src_root: Path) -> bool:
    """Multi-file ambiguity returns exit 3 with candidates list."""
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        _write_fakepipe(tmp, {
            "fakepipe/v1/file_a.py": '''
                class Ambig:
                    definition = """
                    id: int
                    ---
                    """
            ''',
            "fakepipe/v1/file_b.py": '''
                class Ambig:
                    definition = """
                    other_id: int
                    ---
                    """
            ''',
            "fakepipe/v1/other.py": '''
                class Other:
                    definition = """
                    id: int
                    ---
                    """
            ''',
        })
        rc, out, _ = _run_code_graph(
            ["--src", str(tmp), "path", "--to", "Ambig", "Other", "--json"]
        )
        if rc != 3:
            print(f"  [FAIL] expected exit 3 for ambiguity, got {rc}")
            print(f"         stdout: {out[:200]!r}")
            return False
        payload = _parse_json_or_fail(out, "ambiguous")
        if payload is None:
            return False
        if payload.get("kind") != "ambiguous":
            print(f"  [FAIL] kind != 'ambiguous': {payload.get('kind')!r}")
            return False
        if payload.get("name") != "Ambig":
            print(f"  [FAIL] name != 'Ambig': {payload.get('name')!r}")
            return False
        candidates = payload.get("candidates", [])
        if len(candidates) != 2:
            print(f"  [FAIL] expected 2 candidates, got {len(candidates)}")
            return False
        for c in candidates:
            for k in ("file", "line", "qualname"):
                if k not in c:
                    print(f"  [FAIL] candidate missing {k!r}: {c!r}")
                    return False
    print("  [ok] path --to: multi-file ambiguity surfaces with exit 3 and candidates")
    return True


def fixture_path_walks_up_and_down(src_root: Path) -> bool:
    """`path --up` / `path --down` walk the FK graph in both directions."""
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        _write_fakepipe(tmp, {
            "fakepipe/v1/foo.py": '''
                class Root:
                    definition = """
                    id: int
                    ---
                    """
                class Mid:
                    definition = """
                    -> Root
                    id: int
                    ---
                    """
                class Leaf:
                    definition = """
                    -> Mid
                    id: int
                    ---
                    """
                class Branch:
                    definition = """
                    -> Root
                    branch_id: int
                    ---
                    """
            ''',
        })
        # --up Leaf — ancestors should be {Mid, Root}, NOT Branch.
        rc, out, err = _run_code_graph(
            ["--src", str(tmp), "path", "--up", "Leaf", "--json"]
        )
        if rc != 0:
            print(f"  [FAIL] --up Leaf exit {rc}; stderr: {err!r}")
            return False
        payload = _parse_json_or_fail(out, "ancestors")
        if payload is None:
            return False
        if payload.get("kind") != "ancestors":
            print(f"  [FAIL] --up kind != 'ancestors': {payload.get('kind')!r}")
            return False
        node_qns = {n["qualname"] for n in payload.get("nodes", [])}
        if node_qns != {"Mid", "Root"}:
            print(f"  [FAIL] --up Leaf nodes != {{Mid, Root}}: {node_qns!r}")
            return False
        edge_pairs = {(e["child"], e["parent"]) for e in payload.get("edges", [])}
        if ("Leaf", "Mid") not in edge_pairs or ("Mid", "Root") not in edge_pairs:
            print(f"  [FAIL] --up Leaf missing expected edges: {edge_pairs!r}")
            return False
        # --down Root — descendants should be {Mid, Branch, Leaf}.
        rc, out, err = _run_code_graph(
            ["--src", str(tmp), "path", "--down", "Root", "--json"]
        )
        if rc != 0:
            print(f"  [FAIL] --down Root exit {rc}; stderr: {err!r}")
            return False
        payload = _parse_json_or_fail(out, "descendants")
        if payload is None:
            return False
        if payload.get("kind") != "descendants":
            print(f"  [FAIL] --down kind != 'descendants': {payload.get('kind')!r}")
            return False
        node_qns = {n["qualname"] for n in payload.get("nodes", [])}
        if node_qns != {"Mid", "Branch", "Leaf"}:
            print(f"  [FAIL] --down Root nodes != {{Mid, Branch, Leaf}}: {node_qns!r}")
            return False
        # Assert edge polarity for descendants too (the bug found during
        # TDD was edge-direction-inversion in ancestors; --down must be
        # symmetric).
        edge_pairs = {(e["parent"], e["child"]) for e in payload.get("edges", [])}
        for required in (("Root", "Mid"), ("Root", "Branch"), ("Mid", "Leaf")):
            if required not in edge_pairs:
                print(f"  [FAIL] --down Root missing edge {required}: {edge_pairs!r}")
                return False
    print("  [ok] path --up / --down: tree walk + edge polarity correct in both directions")
    return True


def fixture_path_no_path_returns_kind_no_path(src_root: Path) -> bool:
    """`path --to A B` with two disconnected classes returns kind=no_path (exit 0)."""
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        _write_fakepipe(tmp, {
            "fakepipe/v1/foo.py": '''
                class Lonely:
                    definition = """
                    id: int
                    ---
                    """
                class Stranger:
                    definition = """
                    other_id: int
                    ---
                    """
            ''',
        })
        rc, out, err = _run_code_graph(
            ["--src", str(tmp), "path", "--to", "Lonely", "Stranger", "--json"]
        )
        if rc != 0:
            print(f"  [FAIL] expected exit 0 for no-path, got {rc}; stderr: {err!r}")
            return False
        payload = _parse_json_or_fail(out, "no_path")
        if payload is None:
            return False
        if payload.get("kind") != "no_path":
            print(f"  [FAIL] kind != 'no_path': {payload.get('kind')!r}")
            return False
        # Pin from/to as node objects (matches happy-path schema, not bare strings).
        for side in ("from", "to"):
            obj = payload.get(side)
            if not isinstance(obj, dict):
                print(f"  [FAIL] {side} is not an object: {obj!r}")
                return False
            for k in ("name", "qualname", "file", "line"):
                if k not in obj:
                    print(f"  [FAIL] {side} missing field {k!r}: {obj!r}")
                    return False
        if "reason" not in payload or not payload["reason"]:
            print(f"  [FAIL] reason missing or empty: {payload!r}")
            return False
    print("  [ok] path --to: disconnected classes return kind=no_path with node-object from/to")
    return True


def fixture_path_not_found_returns_exit_4(src_root: Path) -> bool:
    """`path --to <missing> ...` exits 4 with kind=not_found JSON."""
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        _write_fakepipe(tmp, {
            "fakepipe/v1/foo.py": '''
                class Existing:
                    definition = """
                    id: int
                    ---
                    """
            ''',
        })
        rc, out, _ = _run_code_graph(
            ["--src", str(tmp), "path", "--to", "Nonexistent", "Existing", "--json"]
        )
        if rc != 4:
            print(f"  [FAIL] expected exit 4 for not_found, got {rc}; stdout: {out[:200]!r}")
            return False
        payload = _parse_json_or_fail(out, "not_found")
        if payload is None:
            return False
        if payload.get("kind") != "not_found":
            print(f"  [FAIL] kind != 'not_found': {payload.get('kind')!r}")
            return False
        if payload.get("name") != "Nonexistent":
            print(f"  [FAIL] name != 'Nonexistent': {payload.get('name')!r}")
            return False
        if "hint" not in payload or not payload["hint"]:
            print(f"  [FAIL] hint missing or empty: {payload!r}")
            return False
        # Pin a substantive hint (not just "not found") so a refactor can't
        # silently drop the routing copy that tells the agent what to try next.
        if "version" not in payload["hint"].lower():
            print(f"  [FAIL] hint missing version-fallback guidance: {payload['hint']!r}")
            return False
    print("  [ok] path: missing class returns exit 4 with not_found JSON + version-fallback hint")
    return True


def fixture_path_accepts_dotted_qualname(src_root: Path) -> bool:
    """`path --to Outer.Inner Downstream` resolves the qualified name directly.

    Outer.Inner is the source (from), Downstream the destination (to). The
    fixture pins both sides — without the `to`-side assertion, a path that
    silently routes to the wrong destination would pass vacuously.
    """
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        _write_fakepipe(tmp, {
            "fakepipe/v1/foo.py": '''
                class Outer:
                    definition = """
                    id: int
                    ---
                    """
                    class Inner:
                        definition = """
                        -> master
                        nested_id: int
                        ---
                        """
                class Downstream:
                    definition = """
                    -> Outer.Inner
                    ---
                    """
            ''',
        })
        rc, out, err = _run_code_graph(
            ["--src", str(tmp), "path", "--to", "Outer.Inner", "Downstream", "--json"]
        )
        if rc != 0:
            print(f"  [FAIL] qualname input exit {rc}; stderr: {err!r}; stdout: {out[:200]!r}")
            return False
        payload = _parse_json_or_fail(out, "qualname-input path")
        if payload is None:
            return False
        if payload.get("kind") != "path":
            print(f"  [FAIL] kind != 'path': {payload.get('kind')!r}")
            return False
        # The from-side qualname must match what the user typed.
        if payload.get("from", {}).get("qualname") != "Outer.Inner":
            print(f"  [FAIL] from.qualname != 'Outer.Inner': {payload.get('from')!r}")
            return False
        # Pin the to-side too — without this, a path silently routing to
        # the wrong destination could pass vacuously (rc=0, kind=path).
        if payload.get("to", {}).get("qualname") != "Downstream":
            print(f"  [FAIL] to.qualname != 'Downstream': {payload.get('to')!r}")
            return False
        # Walk must produce at least 2 hops (Outer.Inner → ... → Downstream).
        hops = payload.get("hops", [])
        hop_qns = [h["qualname"] for h in hops]
        if len(hops) < 2 or hop_qns[0] != "Outer.Inner" or hop_qns[-1] != "Downstream":
            print(f"  [FAIL] hop chain doesn't terminate at Downstream: {hop_qns!r}")
            return False
    print("  [ok] path --to: dotted qualname input resolves directly without ambiguity")
    return True


def fixture_dotted_qualname_respects_file_hint(src_root: Path) -> bool:
    """Dotted-qualname input (``Master.Part``) with multiple matching
    records (e.g. ``LFPBandSelection.LFPBandElectrode`` exists in both
    ``common/common_ephys.py`` and ``lfp/analysis/v1/lfp_band.py``) must
    honor ``--file`` / ``--from-file`` / ``--to-file`` to pick the right
    record. Pre-fix, the dotted branch in ``_resolve_class`` returned
    ``ambiguous`` immediately without consulting the file hint, so the
    CLI told the user to pass ``--file`` while ignoring it when they did.

    Repro on real Spyglass:
        path --up LFPBandSelection.LFPBandElectrode \
             --file spyglass/lfp/analysis/v1/lfp_band.py
    Pre-fix: exit 3, candidates list both v0 (common_ephys.py:624) and
    v1 (lfp_band.py:34) records.
    Post-fix: exit 0, root resolves to the v1 record.
    """
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = _write_fakepipe(Path(tmp_str), {
            "utils/dj_mixin.py": "class SpyglassMixin: pass\n",
            # Two files BOTH define a `Master` with the SAME nested part
            # `Master.Inner`. The dotted qualname `Master.Inner` matches
            # both — file hint must disambiguate.
            "common/legacy.py": '''
                from spyglass.utils.dj_mixin import SpyglassMixin
                class Master(SpyglassMixin):
                    definition = """
                    legacy_id: int
                    ---
                    """
                    class Inner(SpyglassMixin):
                        definition = """
                        -> master
                        legacy_extra: varchar(32)
                        """
            ''',
            "fakepipe/v1/main.py": '''
                from spyglass.utils.dj_mixin import SpyglassMixin
                class Master(SpyglassMixin):
                    definition = """
                    v1_id: int
                    ---
                    """
                    class Inner(SpyglassMixin):
                        definition = """
                        -> master
                        v1_extra: varchar(32)
                        """
                class Downstream(SpyglassMixin):
                    definition = """
                    -> Master.Inner
                    ---
                    """
            ''',
        })

        # Without --file: dotted Master.Inner resolves ambiguously (exit 3).
        rc, out, _err = _run_code_graph([
            "--src", str(tmp), "path", "--up", "Master.Inner", "--json",
        ])
        if rc != 3:
            print(f"  [FAIL] expected exit 3 without --file, got {rc}: {out[:300]!r}")
            return False
        payload = _parse_json_or_fail(out, "dotted ambiguous (no --file)")
        if payload is None or payload.get("kind") != "ambiguous":
            print(f"  [FAIL] expected kind=ambiguous: {payload!r}")
            return False
        candidates = payload.get("candidates", [])
        if len(candidates) != 2:
            print(f"  [FAIL] expected 2 candidates, got {len(candidates)}: {candidates!r}")
            return False

        # With --file pointing at v1: must resolve cleanly to the v1 record.
        rc, out, _err = _run_code_graph([
            "--src", str(tmp), "path", "--up", "Master.Inner",
            "--file", "spyglass/fakepipe/v1/main.py", "--json",
        ])
        if rc != 0:
            print(
                f"  [FAIL] dotted qualname + --file should resolve, got exit {rc}: "
                f"{out[:300]!r}"
            )
            return False
        payload = _parse_json_or_fail(out, "dotted with --file")
        if payload is None or payload.get("kind") != "ancestors":
            print(f"  [FAIL] expected kind=ancestors after --file, got {payload!r}")
            return False
        root_file = payload.get("root", {}).get("file", "")
        if "fakepipe/v1/main.py" not in root_file:
            print(
                f"  [FAIL] root resolved to wrong record: {root_file!r} "
                "(expected fakepipe/v1/main.py)"
            )
            return False

        # Same case for `describe`: dotted + --file must pick v1.
        rc, out, _err = _run_code_graph([
            "--src", str(tmp), "describe", "Master.Inner",
            "--file", "spyglass/fakepipe/v1/main.py", "--json",
        ])
        if rc != 0:
            print(
                f"  [FAIL] describe Master.Inner --file should resolve, got "
                f"exit {rc}: {out[:300]!r}"
            )
            return False
        payload = _parse_json_or_fail(out, "describe dotted with --file")
        if payload is None or payload.get("kind") != "describe":
            print(f"  [FAIL] expected kind=describe, got {payload!r}")
            return False

        # And the --from-file variant of `path --to`: dotted source + hint.
        rc, out, _err = _run_code_graph([
            "--src", str(tmp), "path", "--to", "Master.Inner", "Downstream",
            "--from-file", "spyglass/fakepipe/v1/main.py", "--json",
        ])
        if rc != 0:
            print(
                f"  [FAIL] path --to dotted + --from-file should resolve, got "
                f"exit {rc}: {out[:300]!r}"
            )
            return False
    print(
        "  [ok] dotted qualname: --file / --from-file / --to-file disambiguate "
        "duplicate part records"
    )
    return True


def fixture_describe_lists_body_level_methods(src_root: Path) -> bool:
    """`describe MyTable` lists body methods + methods inherited from SpyglassMixin.

    Pins the mixin-resolution capability — the central reason describe exists.
    """
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        _write_fakepipe(tmp, {
            "utils/dj_mixin.py": '''
                class SpyglassMixin:
                    def fetch_nwb(self): pass
                    def cautious_delete(self): pass
            ''',
            "fakepipe/v1/foo.py": '''
                from spyglass.utils.dj_mixin import SpyglassMixin
                class MyTable(SpyglassMixin):
                    definition = """
                    id: int
                    ---
                    """
                    def my_helper(self): pass
                    def make(self, key): pass
            ''',
        })
        rc, out, err = _run_code_graph(
            ["--src", str(tmp), "describe", "MyTable", "--json"]
        )
        if rc != 0:
            print(f"  [FAIL] exited {rc}; stderr: {err!r}")
            return False
        payload = _parse_json_or_fail(out, "describe MyTable")
        if payload is None:
            return False
        if payload.get("schema_version") != 1:
            print(f"  [FAIL] schema_version != 1: {payload.get('schema_version')!r}")
            return False
        if payload.get("kind") != "describe":
            print(f"  [FAIL] kind != 'describe': {payload.get('kind')!r}")
            return False
        cls = payload.get("class", {})
        if cls.get("qualname") != "MyTable":
            print(f"  [FAIL] class.qualname != 'MyTable': {cls!r}")
            return False
        body_names = {m["name"] for m in payload.get("body_methods", [])}
        if "my_helper" not in body_names or "make" not in body_names:
            print(f"  [FAIL] body_methods missing my_helper/make: {body_names!r}")
            return False
        # Inherited from SpyglassMixin: fetch_nwb + cautious_delete.
        spx = next(
            (e for e in payload.get("inherited_methods", []) if e["from_base"] == "SpyglassMixin"),
            None,
        )
        if spx is None:
            inh = payload.get("inherited_methods")
            print(f"  [FAIL] no SpyglassMixin entry in inherited_methods: {inh!r}")
            return False
        spx_methods = {m["name"] for m in spx.get("methods", [])}
        if "fetch_nwb" not in spx_methods or "cautious_delete" not in spx_methods:
            print(f"  [FAIL] SpyglassMixin inherited methods missing entries: {spx_methods!r}")
            return False
    print("  [ok] describe: body methods + SpyglassMixin-inherited methods both surface")
    return True


def fixture_describe_annotates_datajoint_bases(src_root: Path) -> bool:
    """`describe MyComputed(SpyglassMixin, dj.Computed)` annotates dj.Computed
    rather than walking into datajoint source.
    """
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        _write_fakepipe(tmp, {
            "utils/dj_mixin.py": '''
                class SpyglassMixin:
                    def fetch_nwb(self): pass
            ''',
            "fakepipe/v1/foo.py": '''
                import datajoint as dj
                from spyglass.utils.dj_mixin import SpyglassMixin
                class MyComputed(SpyglassMixin, dj.Computed):
                    definition = """
                    id: int
                    ---
                    """
                    def make(self, key): pass
            ''',
        })
        rc, out, err = _run_code_graph(
            ["--src", str(tmp), "describe", "MyComputed", "--json"]
        )
        if rc != 0:
            print(f"  [FAIL] exited {rc}; stderr: {err!r}")
            return False
        payload = _parse_json_or_fail(out, "describe MyComputed")
        if payload is None:
            return False
        # Look for dj.Computed in bases with annotation kind.
        bases = payload.get("bases", [])
        dj_entry = next((b for b in bases if b["name"] == "dj.Computed"), None)
        if dj_entry is None:
            print(f"  [FAIL] dj.Computed not in bases: {bases!r}")
            return False
        if dj_entry.get("kind") != "inherits_annotated":
            print(f"  [FAIL] dj.Computed kind != 'inherits_annotated': {dj_entry!r}")
            return False
        # inherited_methods must NOT include any entry whose from_base starts
        # with "dj." — that would mean we walked into datajoint source.
        for entry in payload.get("inherited_methods", []):
            if entry["from_base"].startswith("dj."):
                print(f"  [FAIL] datajoint base walked into: {entry!r}")
                return False
    print("  [ok] describe: dj.Computed annotated, not enumerated")
    return True


def fixture_describe_parses_pk_and_fk_renames(src_root: Path) -> bool:
    """`describe LFPBandSelection`-style class surfaces structured PK +
    FK with projected-rename dict (the canonical hallucination-prevention
    case for field/key/rename shapes).
    """
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        _write_fakepipe(tmp, {
            "utils/dj_merge_tables.py": '''
                class _Merge:
                    pass
            ''',
            "fakepipe/v1/lfp_merge.py": '''
                from spyglass.utils.dj_merge_tables import _Merge
                class LFPOutput(_Merge):
                    definition = """
                    merge_id: uuid
                    ---
                    source: varchar(32)
                    """
                    class LFPV1:
                        definition = """
                        -> master
                        -> LFPV1
                        ---
                        """
            ''',
            "fakepipe/v1/lfp_band.py": '''
                class LFPV1:
                    definition = """
                    id: int
                    ---
                    """
                class LFPBandSelection:
                    definition = """
                    -> LFPOutput.proj(lfp_merge_id='merge_id')
                    filter_name: varchar(80)
                    filter_sampling_rate: int
                    ---
                    """
            ''',
        })
        rc, out, err = _run_code_graph(
            ["--src", str(tmp), "describe", "LFPBandSelection", "--json"]
        )
        if rc != 0:
            print(f"  [FAIL] exited {rc}; stderr: {err!r}")
            return False
        payload = _parse_json_or_fail(out, "describe LFPBandSelection")
        if payload is None:
            return False
        # Structured PK: filter_name varchar(80) + filter_sampling_rate int.
        pk_names = {f["name"] for f in payload.get("pk_fields", [])}
        if pk_names != {"filter_name", "filter_sampling_rate"}:
            print(f"  [FAIL] pk_fields != {{filter_name, filter_sampling_rate}}: {pk_names!r}")
            return False
        # No non-PK fields.
        if payload.get("non_pk_fields"):
            print(f"  [FAIL] non_pk_fields not empty: {payload.get('non_pk_fields')!r}")
            return False
        # FK to LFPOutput with kind=proj and renames={lfp_merge_id: merge_id}.
        fks = payload.get("fk_edges", [])
        proj_edge = next((e for e in fks if e["parent"] == "LFPOutput"), None)
        if proj_edge is None:
            print(f"  [FAIL] no FK to LFPOutput: {fks!r}")
            return False
        if proj_edge.get("kind") != "proj":
            print(f"  [FAIL] LFPOutput edge kind != 'proj': {proj_edge!r}")
            return False
        if proj_edge.get("renames") != {"lfp_merge_id": "merge_id"}:
            print(f"  [FAIL] renames != {{lfp_merge_id: merge_id}}: {proj_edge.get('renames')!r}")
            return False
        if not proj_edge.get("in_pk"):
            print(f"  [FAIL] proj edge in_pk should be True: {proj_edge!r}")
            return False
    print("  [ok] describe: structured PK + projected-FK renames extracted correctly")
    return True


def fixture_describe_walks_transitive_sub_mixin(src_root: Path) -> bool:
    """Inheritance walk recurses into a sub-mixin's body methods.

    Real Spyglass: SpyglassMixin itself subclasses CautiousDeleteMixin /
    ExportMixin / FetchMixin / etc., and ``fetch_nwb`` lives on those
    sub-mixins. Without recursion, body methods on the sub-mixin would
    never surface in inherited_methods. Pins the recursive `_walk_base`.
    """
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        _write_fakepipe(tmp, {
            "utils/dj_mixin.py": '''
                class MySubMixin:
                    def deep_method(self): pass
                class SpyglassMixin(MySubMixin):
                    def shallow_method(self): pass
            ''',
            "fakepipe/v1/foo.py": '''
                from spyglass.utils.dj_mixin import SpyglassMixin
                class MyTable(SpyglassMixin):
                    definition = """
                    id: int
                    ---
                    """
            ''',
        })
        rc, out, err = _run_code_graph(
            ["--src", str(tmp), "describe", "MyTable", "--json"]
        )
        if rc != 0:
            print(f"  [FAIL] exited {rc}; stderr: {err!r}")
            return False
        payload = _parse_json_or_fail(out, "transitive walk")
        if payload is None:
            return False
        all_methods = {
            m["name"]
            for entry in payload.get("inherited_methods", [])
            for m in entry["methods"]
        }
        if "shallow_method" not in all_methods:
            print(f"  [FAIL] shallow_method missing: {all_methods!r}")
            return False
        if "deep_method" not in all_methods:
            print(f"  [FAIL] deep_method (transitive) missing: {all_methods!r}")
            return False
        # The deep_method's owner should be MySubMixin, not SpyglassMixin —
        # pins the recursion source-attribution.
        sub_entry = next(
            (e for e in payload["inherited_methods"] if e["from_base"] == "MySubMixin"),
            None,
        )
        if sub_entry is None:
            print("  [FAIL] no MySubMixin entry in inherited_methods")
            return False
        if "deep_method" not in {m["name"] for m in sub_entry["methods"]}:
            print("  [FAIL] MySubMixin entry doesn't list deep_method")
            return False
    print("  [ok] describe: inheritance walk recurses into sub-mixin body methods")
    return True


def fixture_describe_alias_merge_resolves_inherited_methods(src_root: Path) -> bool:
    """`_Merge` (alias for `Merge`) resolves via MIXIN_ALIASES.

    Real Spyglass exposes ``_Merge = Merge`` at the bottom of
    ``dj_merge_tables.py``; user code consistently writes
    ``class LFPOutput(_Merge):``. Without alias support, ``_Merge`` is
    unresolved and ``merge_*`` methods don't surface.

    The synthetic tree puts the canonical ``Merge`` class in
    ``utils/dj_merge_tables.py`` (matching MIXIN_REGISTRY's path) and
    references it from user code as ``_Merge``. Asserts the alias is
    followed and inherited methods come through.
    """
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        _write_fakepipe(tmp, {
            "utils/dj_merge_tables.py": '''
                class Merge:
                    def merge_get_part(self, key): pass
                    def merge_restrict(self, key): pass
            ''',
            "fakepipe/v1/lfp_merge.py": '''
                from spyglass.utils.dj_merge_tables import _Merge
                class FakeLFPOutput(_Merge):
                    definition = """
                    merge_id: uuid
                    ---
                    """
            ''',
        })
        rc, out, err = _run_code_graph(
            ["--src", str(tmp), "describe", "FakeLFPOutput", "--json"]
        )
        if rc != 0:
            print(f"  [FAIL] exited {rc}; stderr: {err!r}")
            return False
        payload = _parse_json_or_fail(out, "alias merge")
        if payload is None:
            return False
        # The base name (as written in the source) is `_Merge`.
        merge_entry = next(
            (e for e in payload.get("inherited_methods", []) if e["from_base"] == "_Merge"),
            None,
        )
        if merge_entry is None:
            print(f"  [FAIL] _Merge alias not resolved: {payload.get('inherited_methods')!r}")
            return False
        method_names = {m["name"] for m in merge_entry["methods"]}
        if "merge_get_part" not in method_names or "merge_restrict" not in method_names:
            print(f"  [FAIL] merge_* methods missing under _Merge: {method_names!r}")
            return False
    print("  [ok] describe: _Merge alias resolves to Merge; merge_* methods surface")
    return True


def fixture_describe_disambiguates_multi_file_class(src_root: Path) -> bool:
    """`describe Ambig` returns exit 3 with candidates when defined in 2 files."""
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        _write_fakepipe(tmp, {
            "fakepipe/v1/file_a.py": '''
                class Ambig:
                    definition = """
                    id: int
                    ---
                    """
            ''',
            "fakepipe/v1/file_b.py": '''
                class Ambig:
                    definition = """
                    other_id: int
                    ---
                    """
            ''',
        })
        rc, out, _ = _run_code_graph(["--src", str(tmp), "describe", "Ambig", "--json"])
        if rc != 3:
            print(f"  [FAIL] expected exit 3, got {rc}; stdout: {out[:200]!r}")
            return False
        payload = _parse_json_or_fail(out, "describe ambiguous")
        if payload is None:
            return False
        if payload.get("kind") != "ambiguous":
            print(f"  [FAIL] kind != 'ambiguous': {payload.get('kind')!r}")
            return False
        if payload.get("name") != "Ambig":
            print(f"  [FAIL] name != 'Ambig': {payload.get('name')!r}")
            return False
        if len(payload.get("candidates", [])) != 2:
            print(f"  [FAIL] expected 2 candidates: {payload.get('candidates')!r}")
            return False
    print("  [ok] describe: multi-file ambiguity surfaces with same exit-3 contract as path")
    return True


def fixture_findmethod_lists_mixin_owner_and_inherited(src_root: Path) -> bool:
    """`find-method fetch_nwb` returns SpyglassMixin as the body-level owner
    AND surfaces inherited-via-summary text mentioning subclass inheritance.

    Pins the canonical eval-51 closure shape (agent asks 'where does method
    Y come from?'). The body-level scan finds SpyglassMixin's own definition;
    the inherited_via summary tells the agent that subclasses transitively
    have it without enumerating every subclass.
    """
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        _write_fakepipe(tmp, {
            "utils/dj_mixin.py": '''
                class SpyglassMixin:
                    def fetch_nwb(self): pass
            ''',
            "fakepipe/v1/foo.py": '''
                from spyglass.utils.dj_mixin import SpyglassMixin
                class MyTable(SpyglassMixin):
                    definition = """
                    id: int
                    ---
                    """
            ''',
        })
        rc, out, err = _run_code_graph(
            ["--src", str(tmp), "find-method", "fetch_nwb", "--json"]
        )
        if rc != 0:
            print(f"  [FAIL] exited {rc}; stderr: {err!r}")
            return False
        payload = _parse_json_or_fail(out, "find-method fetch_nwb")
        if payload is None:
            return False
        if payload.get("schema_version") != 1:
            print(f"  [FAIL] schema_version != 1: {payload.get('schema_version')!r}")
            return False
        if payload.get("kind") != "find-method":
            print(f"  [FAIL] kind != 'find-method': {payload.get('kind')!r}")
            return False
        if payload.get("method") != "fetch_nwb":
            print(f"  [FAIL] method != 'fetch_nwb': {payload.get('method')!r}")
            return False
        defined_at = payload.get("defined_at", [])
        if len(defined_at) != 1:
            print(f"  [FAIL] expected 1 defined_at entry, got {len(defined_at)}: {defined_at!r}")
            return False
        owner = defined_at[0]
        if owner["class"]["qualname"] != "SpyglassMixin":
            print(f"  [FAIL] owner.class.qualname != 'SpyglassMixin': {owner!r}")
            return False
        if owner.get("ownership_kind") != "mixin":
            print(f"  [FAIL] ownership_kind != 'mixin': {owner!r}")
            return False
        if "evidence" not in owner or not owner["evidence"]:
            print(f"  [FAIL] evidence missing or empty: {owner!r}")
            return False
        # inherited_via must include a SpyglassMixin entry with a summary.
        inh = payload.get("inherited_via", [])
        spx = next((e for e in inh if e["base"] == "SpyglassMixin"), None)
        if spx is None:
            print(f"  [FAIL] no SpyglassMixin entry in inherited_via: {inh!r}")
            return False
        if not spx.get("summary"):
            print(f"  [FAIL] SpyglassMixin entry missing summary: {spx!r}")
            return False
    print("  [ok] find-method: mixin owner identified, inherited-via summary present")
    return True


def fixture_findmethod_orders_multiple_owners(src_root: Path) -> bool:
    """When a method is defined on multiple classes, ordering is deterministic
    (sorted by file:line) and `ownership_kind` is correct per owner.

    Synthesizes three classes that all define `do_thing`: one in a mixin
    (registered), one in a sub-mixin (inherited via mixin's ancestors),
    one as a body-level override on a regular table. Asserts:

    * defined_at has 3 entries (no dedup, since the method is real on each).
    * Order is sorted lexicographically by (file, line) — pinning so a
      future scan-order regression can't silently flip the list.
    * ownership_kind correctly distinguishes mixin / mixin-walked / body.
    """
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        _write_fakepipe(tmp, {
            # Path components chosen so file-order sort is deterministic.
            "utils/dj_mixin.py": '''
                class SpyglassMixin:
                    def do_thing(self): pass
            ''',
            "fakepipe/v1/a_first.py": '''
                class FirstTable:
                    definition = """
                    id: int
                    ---
                    """
                    def do_thing(self): pass
            ''',
            "fakepipe/v1/b_second.py": '''
                from spyglass.utils.dj_mixin import SpyglassMixin
                class SecondTable(SpyglassMixin):
                    definition = """
                    id: int
                    ---
                    """
                    def do_thing(self): pass
            ''',
        })
        rc, out, err = _run_code_graph(
            ["--src", str(tmp), "find-method", "do_thing", "--json"]
        )
        if rc != 0:
            print(f"  [FAIL] exited {rc}; stderr: {err!r}")
            return False
        payload = _parse_json_or_fail(out, "find-method multi-owner")
        if payload is None:
            return False
        defined_at = payload.get("defined_at", [])
        if len(defined_at) != 3:
            print(f"  [FAIL] expected 3 owners, got {len(defined_at)}: {defined_at!r}")
            return False
        # Ordering: sorted by (file, line).
        files = [(d["class"]["file"], d["class"]["line"]) for d in defined_at]
        if files != sorted(files):
            print(f"  [FAIL] defined_at not sorted by (file, line): {files!r}")
            return False
        # Four-bucket taxonomy:
        #   * SpyglassMixin itself → "mixin" (registered).
        #   * SecondTable inherits from SpyglassMixin → "inherits_mixin"
        #     (the body-level def lives on a concrete table whose base
        #     chain includes a registered mixin).
        #   * FirstTable has no mixin base → "body".
        kinds = {d["class"]["qualname"]: d["ownership_kind"] for d in defined_at}
        if kinds.get("FirstTable") != "body":
            print(f"  [FAIL] FirstTable ownership_kind != 'body': {kinds!r}")
            return False
        if kinds.get("SpyglassMixin") != "mixin":
            print(f"  [FAIL] SpyglassMixin ownership_kind != 'mixin': {kinds!r}")
            return False
        if kinds.get("SecondTable") != "inherits_mixin":
            print(
                f"  [FAIL] SecondTable ownership_kind != 'inherits_mixin': "
                f"{kinds!r}"
            )
            return False
    print("  [ok] find-method: multi-owner ordering deterministic, ownership_kind per owner")
    return True


def fixture_findmethod_returns_exit_4_for_unknown(src_root: Path) -> bool:
    """`find-method <unknown>` exits 4 with kind=not_found + datajoint hint."""
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        _write_fakepipe(tmp, {
            "fakepipe/v1/foo.py": '''
                class OnlyClass:
                    definition = """
                    id: int
                    ---
                    """
            ''',
        })
        rc, out, _ = _run_code_graph(
            ["--src", str(tmp), "find-method", "nonexistent_method", "--json"]
        )
        if rc != 4:
            print(f"  [FAIL] expected exit 4, got {rc}; stdout: {out[:200]!r}")
            return False
        payload = _parse_json_or_fail(out, "find-method not_found")
        if payload is None:
            return False
        if payload.get("kind") != "not_found":
            print(f"  [FAIL] kind != 'not_found': {payload.get('kind')!r}")
            return False
        if payload.get("method") != "nonexistent_method":
            print(f"  [FAIL] method != 'nonexistent_method': {payload.get('method')!r}")
            return False
        # Hint must mention datajoint so the agent doesn't conclude the
        # method doesn't exist anywhere in the wider Python ecosystem.
        hint = payload.get("hint", "")
        if "datajoint" not in hint.lower():
            print(f"  [FAIL] hint doesn't mention datajoint: {hint!r}")
            return False
    print("  [ok] find-method: missing method returns exit 4 with datajoint-fallback hint")
    return True


def fixture_path_walk_polarity_for_merge_masters(src_root: Path) -> bool:
    """Polarity contract for ``--up`` / ``--down`` on merge masters and
    their parts. ``--up`` answers a containment-ancestor question;
    ``--down`` answers an FK-impact-cascade question ("what breaks if
    I modify X?"). The master-part bridge is asymmetric to match.

    * ``--up MergeMaster`` MUST surface parts as ancestors. Parts
      represent the upstream pipelines feeding into the merge — the
      canonical "what feeds in?" question. (The merge master itself
      has no FKs of its own, so without this the answer would be empty.)
    * ``--down MergeMaster`` MUST surface parts as descendants. They
      ARE the downstream containment.
    * ``--down Part`` MUST surface its own master as a descendant.
      Modifying a part's data changes the master's contents, so the
      master is downstream in FK-impact terms (even though the master
      "contains" the part structurally). Without this bridge,
      ``--down LFPV1`` would dead-end at ``LFPOutput.LFPV1`` and never
      reach ``LFPBandV1`` / ``RippleTimesV1``.
    * ``--up Part`` MAY surface its master via the part's ``-> master``
      FK (the FK graph naturally puts master as a parent), but the
      walk must not loop back master → part → master indefinitely.

    Pre-fix repros: an initial bidirectional bridge made `Master.Upstream`
    show as `Master`'s ancestor (containment-polarity inversion). A
    subsequent over-correction made `--up MergeMaster` return empty. A
    third over-correction (the bug this fixture pins) blocked the
    part→master bridge in `walk_child_map` entirely, so ``--down LFPV1``
    never reached downstream consumers like ``RippleTimesV1`` —
    contradicting the documented "what breaks if I modify X?" semantic.
    """
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = _write_fakepipe(Path(tmp_str), {
            "fakepipe/main.py": '''
                from spyglass.utils.dj_merge_tables import _Merge
                from spyglass.utils.dj_mixin import SpyglassMixin

                class Master(_Merge, SpyglassMixin):
                    definition = """
                    merge_id: uuid
                    ---
                    source: varchar(32)
                    """

                    class Upstream(SpyglassMixin):
                        definition = """
                        -> master
                        -> Upstream
                        """
            ''',
            "fakepipe/upstream.py": '''
                from spyglass.utils.dj_mixin import SpyglassMixin

                class Upstream(SpyglassMixin):
                    definition = """
                    upstream_id: int
                    ---
                    """
            ''',
            "utils/dj_merge_tables.py": "class Merge: pass\n_Merge = Merge\n",
            "utils/dj_mixin.py": "class SpyglassMixin: pass\n",
        })
        # --up MergeMaster: parts MUST appear as ancestors (upstream
        # contributors). Pre-fix this was the original bug surface;
        # post-fix-1 (over-correction) returned empty; current design
        # surfaces them.
        rc, out, err = _run_code_graph([
            "--src", str(tmp), "path", "--up", "Master", "--json",
        ])
        if rc != 0:
            print(f"  [FAIL] --up Master rc={rc}: {err!r}")
            return False
        payload = _parse_json_or_fail(out, "path --up Master")
        if payload is None:
            return False
        ancestor_qualnames = {n["qualname"] for n in payload.get("nodes", [])}
        if "Master.Upstream" not in ancestor_qualnames:
            print(
                "  [FAIL] Master.Upstream missing from --up Master ancestors "
                f"(merge master should expose parts as upstream contributors); "
                f"got: {ancestor_qualnames!r}"
            )
            return False
        # The walk must terminate cleanly without infinite cycle. Each
        # qualname appears at most once in nodes (BFS visited guard).
        node_qualnames = [n["qualname"] for n in payload.get("nodes", [])]
        if len(node_qualnames) != len(set(node_qualnames)):
            print(
                "  [FAIL] cycle in --up Master nodes (duplicate qualnames): "
                f"{node_qualnames!r}"
            )
            return False

        # --down Master.Upstream: master MUST appear as descendant.
        # In FK-impact terms ("what breaks if I modify Master.Upstream?"),
        # the master IS downstream — its rows include this part's data,
        # so anything FK'd to the master is impacted by changes to the
        # part. Pre-fix: this bridge was missing, so --down Part chains
        # dead-ended at the part instead of cascading through the master.
        rc, out, err = _run_code_graph([
            "--src", str(tmp), "path", "--down", "Master.Upstream", "--json",
        ])
        if rc != 0:
            print(f"  [FAIL] --down Master.Upstream rc={rc}: {err!r}")
            return False
        payload = _parse_json_or_fail(out, "path --down Master.Upstream")
        if payload is None:
            return False
        descendant_qualnames = {n["qualname"] for n in payload.get("nodes", [])}
        if "Master" not in descendant_qualnames:
            print(
                "  [FAIL] Master missing from --down Master.Upstream descendants "
                "(part→master FK-impact bridge regressed); "
                f"got: {descendant_qualnames!r}"
            )
            return False
        # Walk must terminate cleanly — no cycle from part → master → part.
        node_qualnames = [n["qualname"] for n in payload.get("nodes", [])]
        if len(node_qualnames) != len(set(node_qualnames)):
            print(
                "  [FAIL] cycle in --down Master.Upstream nodes (duplicate qualnames): "
                f"{node_qualnames!r}"
            )
            return False
    print("  [ok] path --up/--down: merge-master polarity correct, no cycles")
    return True


def fixture_path_down_part_does_not_fan_out_to_sibling_parts(src_root: Path) -> bool:
    """``--down Part`` cascades through master to downstream consumers but
    must NOT fan out to the master's *sibling* parts. Modifying one part's
    rows changes that part's data and (transitively) the master's contents,
    but it does NOT change the rows that came from sibling parts —
    those came from independent upstream pipelines.

    Pre-fix repro on real Spyglass:
    ``code_graph.py path --down LFPV1`` reported ``LFPOutput.ImportedLFP``
    and ``LFPOutput.CommonLFP`` as descendants of ``LFPV1`` because
    ``child_map[LFPOutput]`` included all parts indiscriminately. The fix
    threads a ``skip_parts`` flag through BFS so a master reached via the
    part-bridge doesn't fan out to its siblings.
    """
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = _write_fakepipe(Path(tmp_str), {
            "utils/dj_mixin.py": "class SpyglassMixin: pass\n",
            "utils/dj_merge_tables.py": "class Merge: pass\n_Merge = Merge\n",
            "fakepipe/source_a.py": '''
                from spyglass.utils.dj_mixin import SpyglassMixin
                class SourceA(SpyglassMixin):
                    definition = """
                    a_id: int
                    ---
                    """
            ''',
            "fakepipe/source_b.py": '''
                from spyglass.utils.dj_mixin import SpyglassMixin
                class SourceB(SpyglassMixin):
                    definition = """
                    b_id: int
                    ---
                    """
            ''',
            # Merge with TWO parts — one for each independent source pipeline.
            "fakepipe/merge.py": '''
                from spyglass.utils.dj_merge_tables import _Merge
                from spyglass.utils.dj_mixin import SpyglassMixin
                class MergeMaster(_Merge, SpyglassMixin):
                    definition = """
                    merge_id: uuid
                    ---
                    source: varchar(32)
                    """
                    class PartA(SpyglassMixin):
                        definition = """
                        -> master
                        -> SourceA
                        """
                    class PartB(SpyglassMixin):
                        definition = """
                        -> master
                        -> SourceB
                        """
            ''',
            "fakepipe/downstream.py": '''
                from spyglass.utils.dj_mixin import SpyglassMixin
                class Downstream(SpyglassMixin):
                    definition = """
                    -> MergeMaster
                    ---
                    """
            ''',
        })
        rc, out, err = _run_code_graph([
            "--src", str(tmp), "path", "--down", "SourceA",
            "--max-depth", "6", "--json",
        ])
        if rc != 0:
            print(f"  [FAIL] --down SourceA rc={rc}: {err!r}")
            return False
        payload = _parse_json_or_fail(out, "path --down SourceA (sibling-part exclusion)")
        if payload is None:
            return False
        descendants = {n["qualname"] for n in payload.get("nodes", [])}
        # Must reach: PartA (own part), MergeMaster (via part-bridge),
        # Downstream (via master's normal FK consumer).
        required = {"MergeMaster.PartA", "MergeMaster", "Downstream"}
        missing = required - descendants
        if missing:
            print(
                f"  [FAIL] --down SourceA missing required hops: {sorted(missing)} "
                f"— got {sorted(descendants)!r}"
            )
            return False
        # Must NOT reach: PartB (sibling part of MergeMaster). Modifying
        # SourceA shouldn't impact rows that came from SourceB.
        if "MergeMaster.PartB" in descendants:
            print(
                "  [FAIL] --down SourceA fanned out to sibling part "
                "MergeMaster.PartB (skip_parts marker regressed); "
                f"got: {sorted(descendants)!r}"
            )
            return False
    print(
        "  [ok] path --down: part-bridge to master does NOT fan out to sibling parts"
    )
    return True


def fixture_path_walk_picks_same_package_record_for_same_qualname(src_root: Path) -> bool:
    """When two records share a qualname (v0/v1 both named ``LFPBandSelection``),
    walks must pick the same-package record per the FK owner — both for
    rendering (file:line) and for traversal (which record's edges to
    follow next).

    Pre-fix repro on real Spyglass:
    ``code_graph.py path --up LFPBandV1`` rendered ``LFPBandSelection``
    as ``spyglass/common/common_ephys.py:614`` (the v0 record returned
    first by ``by_qualname``) while showing the v1-only edge evidence
    ``-> LFPOutput.proj(lfp_merge_id='merge_id')``. After the fix, the
    rendered file:line and the traversed edge come from the same v1
    record because BFS is record-keyed and FK target resolution
    prefers the same-package record.
    """
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = _write_fakepipe(Path(tmp_str), {
            "utils/dj_mixin.py": "class SpyglassMixin: pass\n",
            # v0 SharedName lives in common/, sorts BEFORE v1 in many
            # filesystem orderings — repros first-match-wins in by_qualname.
            "common/legacy.py": '''
                from spyglass.utils.dj_mixin import SpyglassMixin
                class V0Upstream(SpyglassMixin):
                    definition = """
                    legacy_id: int
                    ---
                    """
                class SharedName(SpyglassMixin):
                    definition = """
                    -> V0Upstream
                    legacy_extra: varchar(32)
                    ---
                    """
            ''',
            # v1 SharedName lives in v1/ pipeline. References a v1-only
            # parent (V1Upstream) that v0 SharedName does NOT reach.
            "fakepipe/v1/upstream.py": '''
                from spyglass.utils.dj_mixin import SpyglassMixin
                class V1Upstream(SpyglassMixin):
                    definition = """
                    upstream_id: int
                    ---
                    """
            ''',
            "fakepipe/v1/shared.py": '''
                from spyglass.utils.dj_mixin import SpyglassMixin
                class SharedName(SpyglassMixin):
                    definition = """
                    -> V1Upstream
                    v1_extra: varchar(32)
                    ---
                    """
            ''',
            # Downstream class lives in same v1 package; its FK to
            # SharedName must resolve to the v1 SharedName via same-package
            # preference.
            "fakepipe/v1/downstream.py": '''
                from spyglass.utils.dj_mixin import SpyglassMixin
                class V1Downstream(SpyglassMixin):
                    definition = """
                    -> SharedName
                    ---
                    """
            ''',
        })
        rc, out, err = _run_code_graph([
            "--src", str(tmp), "path", "--up", "V1Downstream", "--max-depth", "4",
            "--json",
        ])
        if rc != 0:
            print(f"  [FAIL] --up V1Downstream rc={rc}: {err!r}")
            return False
        payload = _parse_json_or_fail(out, "path --up V1Downstream")
        if payload is None:
            return False
        nodes = payload.get("nodes", [])
        # Find SharedName among ancestors. Must render as the v1 file.
        shared = next((n for n in nodes if n["qualname"] == "SharedName"), None)
        if shared is None:
            print(f"  [FAIL] SharedName not in --up V1Downstream nodes: {nodes!r}")
            return False
        if "v1/shared.py" not in shared["file"]:
            print(
                "  [FAIL] SharedName rendered with wrong record file: "
                f"got {shared['file']!r}, expected fakepipe/v1/shared.py "
                "(same-package preference should pick v1 since V1Downstream "
                "is also in v1/)"
            )
            return False
        if "common/legacy.py" in shared["file"]:
            print(f"  [FAIL] SharedName rendered as v0 record: {shared['file']!r}")
            return False
        # Walking up from v1 SharedName must reach V1Upstream (v1's parent),
        # NOT V0Upstream (v0's parent — that would mean we walked v0's
        # edges from the v1 SharedName node).
        ancestor_qualnames = {n["qualname"] for n in nodes}
        if "V1Upstream" not in ancestor_qualnames:
            print(
                f"  [FAIL] V1Upstream missing from ancestors: {sorted(ancestor_qualnames)!r}"
            )
            return False
        if "V0Upstream" in ancestor_qualnames:
            print(
                "  [FAIL] V0Upstream surfaced as ancestor — record-aware BFS "
                f"leaked v0 edges through same-qualname collision: "
                f"{sorted(ancestor_qualnames)!r}"
            )
            return False
    print(
        "  [ok] walks: same-qualname records resolved by same-package preference; "
        "no v0 leakage in v1 walk"
    )
    return True


def fixture_path_down_excludes_v0_consumers_through_master(src_root: Path) -> bool:
    """When ``--down`` cascades through a master to consumers of a
    same-qualname intermediate, only the version-matched consumers
    appear — the other version's consumers are filtered by same-package
    preference in ``_resolve_consumers``.

    Pre-fix repro on real Spyglass:
    ``code_graph.py path --down LFPV1`` included v0 ``LFPBand`` (and
    v0 ``LFPBandSelection.LFPBandElectrode``) as descendants because
    ``child_map["LFPBandSelection"]`` merged v0 and v1 children. After
    the fix, walking down from v1 ``LFPBandSelection`` only reaches
    consumers whose FK to ``LFPBandSelection`` resolves to v1 (not v0)
    via same-package preference.
    """
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = _write_fakepipe(Path(tmp_str), {
            "utils/dj_mixin.py": "class SpyglassMixin: pass\n",
            "utils/dj_merge_tables.py": "class Merge: pass\n_Merge = Merge\n",
            "fakepipe/source.py": '''
                from spyglass.utils.dj_mixin import SpyglassMixin
                class Source(SpyglassMixin):
                    definition = """
                    src_id: int
                    ---
                    """
            ''',
            "fakepipe/merge.py": '''
                from spyglass.utils.dj_merge_tables import _Merge
                from spyglass.utils.dj_mixin import SpyglassMixin
                class MergeMaster(_Merge, SpyglassMixin):
                    definition = """
                    merge_id: uuid
                    ---
                    source: varchar(32)
                    """
                    class SourcePart(SpyglassMixin):
                        definition = """
                        -> master
                        -> Source
                        """
            ''',
            # v1 SharedName in v1/ pipeline — FKs to MergeMaster.
            "fakepipe/v1/shared.py": '''
                from spyglass.utils.dj_mixin import SpyglassMixin
                class SharedName(SpyglassMixin):
                    definition = """
                    -> MergeMaster
                    ---
                    """
            ''',
            "fakepipe/v1/v1_consumer.py": '''
                from spyglass.utils.dj_mixin import SpyglassMixin
                class V1Consumer(SpyglassMixin):
                    definition = """
                    -> SharedName
                    ---
                    """
            ''',
            # v0 SharedName in common/ — has its own consumer in common/.
            # The v0 SharedName has no FK to MergeMaster (legacy).
            "common/legacy.py": '''
                from spyglass.utils.dj_mixin import SpyglassMixin
                class SharedName(SpyglassMixin):
                    definition = """
                    legacy_id: int
                    ---
                    """
                class V0Consumer(SpyglassMixin):
                    definition = """
                    -> SharedName
                    ---
                    """
            ''',
        })
        rc, out, err = _run_code_graph([
            "--src", str(tmp), "path", "--down", "Source",
            "--max-depth", "6", "--json",
        ])
        if rc != 0:
            print(f"  [FAIL] --down Source rc={rc}: {err!r}")
            return False
        payload = _parse_json_or_fail(out, "path --down Source (v0 leakage exclusion)")
        if payload is None:
            return False
        descendants = {n["qualname"] for n in payload.get("nodes", [])}
        # Must reach: SourcePart (own part), MergeMaster, SharedName (v1),
        # V1Consumer (v1's consumer of SharedName).
        required = {"MergeMaster.SourcePart", "MergeMaster", "SharedName", "V1Consumer"}
        missing = required - descendants
        if missing:
            print(
                f"  [FAIL] --down Source missing v1 hops: {sorted(missing)} "
                f"— got {sorted(descendants)!r}"
            )
            return False
        # Must NOT reach V0Consumer — its FK to SharedName resolves to
        # the v0 SharedName via same-package preference (both in common/),
        # so it's NOT a consumer of the v1 SharedName we walked into.
        if "V0Consumer" in descendants:
            print(
                "  [FAIL] V0Consumer surfaced as descendant — same-qualname "
                "leakage through master regressed; "
                f"got: {sorted(descendants)!r}"
            )
            return False
    print(
        "  [ok] path --down: same-qualname leakage filtered by same-package "
        "preference at master-bridge crossing"
    )
    return True


def fixture_path_to_still_bridges_master_part(src_root: Path) -> bool:
    """`path --to` BFS must STILL bridge master-part containment in both
    directions — the bidirectional bridge is correct for `--to`, just
    not for the directional walks. This fixture pins the symmetric
    contract by walking from a part-table down through its master to
    a downstream selection.
    """
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = _write_fakepipe(Path(tmp_str), {
            "fakepipe/main.py": '''
                from spyglass.utils.dj_merge_tables import _Merge
                from spyglass.utils.dj_mixin import SpyglassMixin

                class Upstream(SpyglassMixin):
                    definition = """
                    upstream_id: int
                    ---
                    """

                class MergeMaster(_Merge, SpyglassMixin):
                    definition = """
                    merge_id: uuid
                    ---
                    source: varchar(32)
                    """

                    class UpstreamPart(SpyglassMixin):
                        definition = """
                        -> master
                        -> Upstream
                        """

                class Downstream(SpyglassMixin):
                    definition = """
                    -> MergeMaster
                    extra: varchar(32)
                    """
            ''',
            "utils/dj_merge_tables.py": "class Merge: pass\n_Merge = Merge\n",
            "utils/dj_mixin.py": "class SpyglassMixin: pass\n",
        })
        rc, out, err = _run_code_graph([
            "--src", str(tmp), "path", "--to", "Upstream", "Downstream", "--json",
        ])
        if rc != 0:
            print(f"  [FAIL] --to rc={rc}: {err!r}")
            return False
        payload = _parse_json_or_fail(out, "path --to bridges master-part")
        if payload is None or payload.get("kind") == "no_path":
            print(f"  [FAIL] expected a path through master-part bridge: {payload!r}")
            return False
        hops = payload.get("hops") or []
        kinds = {h.get("kind") for h in hops}
        # Must include a merge_part hop bridging UpstreamPart ↔ MergeMaster.
        if "merge_part" not in kinds:
            print(
                f"  [FAIL] expected merge_part hop in path, got kinds={kinds!r}"
            )
            return False
    print("  [ok] path --to: BFS still bridges master-part containment bidirectionally")
    return True


def fixture_path_down_cascades_through_merge_master_to_deep_consumer(src_root: Path) -> bool:
    """``--down`` impact-cascade must transit at least one merge-master
    bridge to reach a deep downstream consumer.

    Pre-fix repro on real Spyglass:
    ``code_graph.py path --down LFPV1`` returned only
    ``[LFPOutput.LFPV1, LFPArtifactDetectionSelection, ...]`` and never
    reached ``LFPBandV1`` / ``RippleTimesV1`` even though both are
    obviously impacted by changes to ``LFPV1`` (the chain runs
    ``LFPV1 → LFPOutput.LFPV1 → LFPOutput → LFPBandSelection → LFPBandV1
    → RippleLFPSelection → RippleTimesV1``). The dead-end was at
    ``LFPOutput.LFPV1 → LFPOutput`` — the part→master containment
    bridge wasn't in ``walk_child_map``.

    Synthetic mirror:
        Source → MergeMaster.SourcePart → MergeMaster
            → MidSelection (FK to MergeMaster) → MidV1 (FK to MidSelection)
            → DeepConsumer (FK to MidV1).
    All five intermediate hops must land in ``--down Source``'s
    descendants.
    """
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = _write_fakepipe(Path(tmp_str), {
            "utils/dj_mixin.py": "class SpyglassMixin: pass\n",
            "utils/dj_merge_tables.py": "class Merge: pass\n_Merge = Merge\n",
            "fakepipe/source.py": '''
                from spyglass.utils.dj_mixin import SpyglassMixin
                class Source(SpyglassMixin):
                    definition = """
                    source_id: int
                    ---
                    """
            ''',
            "fakepipe/merge.py": '''
                from spyglass.utils.dj_merge_tables import _Merge
                from spyglass.utils.dj_mixin import SpyglassMixin
                class MergeMaster(_Merge, SpyglassMixin):
                    definition = """
                    merge_id: uuid
                    ---
                    source: varchar(32)
                    """
                    class SourcePart(SpyglassMixin):
                        definition = """
                        -> master
                        -> Source
                        """
            ''',
            "fakepipe/mid.py": '''
                from spyglass.utils.dj_mixin import SpyglassMixin
                class MidSelection(SpyglassMixin):
                    definition = """
                    -> MergeMaster
                    mid_id: int
                    ---
                    """
                class MidV1(SpyglassMixin):
                    definition = """
                    -> MidSelection
                    ---
                    """
            ''',
            "fakepipe/deep.py": '''
                from spyglass.utils.dj_mixin import SpyglassMixin
                class DeepConsumer(SpyglassMixin):
                    definition = """
                    -> MidV1
                    ---
                    """
            ''',
        })
        rc, out, err = _run_code_graph([
            "--src", str(tmp), "path", "--down", "Source",
            "--max-depth", "8", "--json",
        ])
        if rc != 0:
            print(f"  [FAIL] --down Source rc={rc}: {err!r}")
            return False
        payload = _parse_json_or_fail(out, "path --down Source (deep cascade)")
        if payload is None:
            return False
        descendants = {n["qualname"] for n in payload.get("nodes", [])}
        required = {
            "MergeMaster.SourcePart",
            "MergeMaster",
            "MidSelection",
            "MidV1",
            "DeepConsumer",
        }
        missing = required - descendants
        if missing:
            print(
                "  [FAIL] --down Source missing impact-cascade hops: "
                f"{sorted(missing)} — got {sorted(descendants)!r}"
            )
            return False
    print(
        "  [ok] path --down: cascades through merge master to reach deep "
        "downstream consumers"
    )
    return True


def fixture_path_edge_meta_walks_all_records_for_qualname(src_root: Path) -> bool:
    """Multi-version classes share a qualname (v0 and v1 ``LFPBandSelection``
    both have qualname == 'LFPBandSelection'). The FK-edge that BFS
    found may live on only ONE of those records — typically the v1
    version, which references a v1-only parent (e.g. ``LFPOutput``).
    ``_edge_meta`` must walk all records with the matching qualname,
    not just the first, or it falsely raises "graph/index desync."

    Pre-fix repro on real Spyglass:
    ``code_graph.py path --to LFPV1 RippleTimesV1`` raised RuntimeError
    on the LFPOutput → LFPBandSelection hop because the v0 record was
    found first and has no FK to LFPOutput.
    """
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = _write_fakepipe(Path(tmp_str), {
            "utils/dj_mixin.py": "class SpyglassMixin: pass\n",
            "utils/dj_merge_tables.py": "class Merge: pass\n_Merge = Merge\n",
            "fakepipe/v1/upstream.py": '''
                from spyglass.utils.dj_mixin import SpyglassMixin
                class Upstream(SpyglassMixin):
                    definition = """
                    upstream_id: int
                    ---
                    """
            ''',
            "fakepipe/v1/merge.py": '''
                from spyglass.utils.dj_merge_tables import _Merge
                from spyglass.utils.dj_mixin import SpyglassMixin
                class MergeMaster(_Merge, SpyglassMixin):
                    definition = """
                    merge_id: uuid
                    ---
                    source: varchar(32)
                    """
                    class UpstreamPart(SpyglassMixin):
                        definition = """
                        -> master
                        -> Upstream
                        """
            ''',
            # v1 SharedName references MergeMaster via projection.
            "fakepipe/v1/shared.py": '''
                from spyglass.utils.dj_mixin import SpyglassMixin
                class SharedName(SpyglassMixin):
                    definition = """
                    -> MergeMaster.proj(my_merge_id='merge_id')
                    extra_v1: varchar(32)
                    ---
                    """
            ''',
            # v0 SharedName has the SAME qualname but references nothing.
            # The first record (alphabetically by file) will be v0; the
            # FK edge of interest lives on v1's record.
            "fakepipe/v0/shared.py": '''
                from spyglass.utils.dj_mixin import SpyglassMixin
                class SharedName(SpyglassMixin):
                    definition = """
                    legacy_id: int
                    ---
                    """
            ''',
        })
        rc, out, err = _run_code_graph([
            "--src", str(tmp), "path", "--to", "Upstream", "SharedName",
            "--from-file", "spyglass/fakepipe/v1/upstream.py",
            "--to-file", "spyglass/fakepipe/v1/shared.py",
            "--json",
        ])
        if rc != 0:
            print(f"  [FAIL] expected exit 0, got {rc}: stderr={err[:400]!r}")
            return False
        payload = _parse_json_or_fail(out, "path with multi-record qualname")
        if payload is None or payload.get("kind") == "no_path":
            print(f"  [FAIL] expected real path, got: {payload!r}")
            return False
    print("  [ok] _edge_meta: walks all records for a qualname (multi-version FK)")
    return True


def fixture_path_hop_citation_matches_record_that_owns_edge(src_root: Path) -> bool:
    """When v0 and v1 share a qualname, the rendered ``file:line`` for an
    intermediate hop must come from the record that ACTUALLY owns the
    traversed FK edge, not from whichever record ``by_qualname`` returns
    first.

    Pre-fix repro on real Spyglass:
    ``code_graph.py path --to LFPV1 LFPBandV1`` rendered the
    ``LFPBandSelection`` hop with ``file: spyglass/common/common_ephys.py``
    (the v0 record, returned first by ``by_qualname``) while the
    ``evidence`` string came from v1
    (``-> LFPOutput.proj(lfp_merge_id='merge_id')`` lives on
    ``spyglass/lfp/analysis/v1/lfp_band.py``). Citation and evidence
    pointed to different files, defeating the "file:line plus evidence"
    promise of the tool.
    """
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = _write_fakepipe(Path(tmp_str), {
            "utils/dj_mixin.py": "class SpyglassMixin: pass\n",
            "fakepipe/v1/upstream.py": '''
                from spyglass.utils.dj_mixin import SpyglassMixin
                class Upstream(SpyglassMixin):
                    definition = """
                    upstream_id: int
                    ---
                    """
            ''',
            # v0 SharedName: NO FK to Upstream. Lives in a file that
            # sorts BEFORE v1 (so by_qualname's first-match would pick
            # this one).
            "fakepipe/v0/shared.py": '''
                from spyglass.utils.dj_mixin import SpyglassMixin
                class SharedName(SpyglassMixin):
                    definition = """
                    legacy_id: int
                    ---
                    """
            ''',
            # v1 SharedName: HAS the FK to Upstream. Same qualname.
            "fakepipe/v1/shared.py": '''
                from spyglass.utils.dj_mixin import SpyglassMixin
                class SharedName(SpyglassMixin):
                    definition = """
                    -> Upstream
                    extra_v1: varchar(32)
                    ---
                    """
            ''',
            "fakepipe/v1/downstream.py": '''
                from spyglass.utils.dj_mixin import SpyglassMixin
                class Downstream(SpyglassMixin):
                    definition = """
                    -> SharedName
                    ---
                    """
            ''',
        })
        rc, out, err = _run_code_graph([
            "--src", str(tmp), "path", "--to", "Upstream", "Downstream",
            "--from-file", "spyglass/fakepipe/v1/upstream.py",
            "--to-file", "spyglass/fakepipe/v1/downstream.py",
            "--json",
        ])
        if rc != 0:
            print(f"  [FAIL] expected exit 0, got {rc}: stderr={err[:400]!r}")
            return False
        payload = _parse_json_or_fail(out, "path with multi-record qualname citation")
        if payload is None:
            return False
        # Find the SharedName intermediate hop.
        hops = payload.get("hops") or []
        shared_hop = next((h for h in hops if h.get("name") == "SharedName"), None)
        if shared_hop is None:
            print(f"  [FAIL] no SharedName hop in payload: {payload!r}")
            return False
        # The FK ``-> Upstream`` lives only on v1. The hop's file must
        # be the v1 record's file, not v0's.
        if "v1/shared.py" not in shared_hop["file"]:
            print(
                "  [FAIL] SharedName hop file:line points to wrong record — "
                f"got {shared_hop['file']!r}, expected v1/shared.py "
                "(the record that carries the traversed FK)"
            )
            return False
        if "v0/shared.py" in shared_hop["file"]:
            print(f"  [FAIL] SharedName hop pinned v0 record: {shared_hop['file']!r}")
            return False
        # Evidence must come from the v1 FK declaration.
        if "Upstream" not in shared_hop["evidence"]:
            print(f"  [FAIL] evidence missing FK reference: {shared_hop['evidence']!r}")
            return False
    print("  [ok] hop citation: file:line matches the record that owns the traversed edge")
    return True


def fixture_describe_no_inherited_suppresses(src_root: Path) -> bool:
    """`describe --no-inherited` produces an empty `inherited_methods` list."""
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = _write_fakepipe(Path(tmp_str), {
            "utils/dj_mixin.py": '''
                class SpyglassMixin:
                    def fetch_nwb(self): ...
                    def fetch_pynapple(self): ...
            ''',
            "fakepipe/main.py": '''
                from spyglass.utils.dj_mixin import SpyglassMixin
                class Suppressible(SpyglassMixin):
                    definition = """
                    suppress_id: int
                    ---
                    """
                    def own_method(self): ...
            ''',
        })
        # With --no-inherited.
        rc, out, _err = _run_code_graph([
            "--src", str(tmp), "describe", "Suppressible",
            "--no-inherited", "--json",
        ])
        if rc != 0:
            print(f"  [FAIL] describe --no-inherited rc={rc}")
            return False
        payload = _parse_json_or_fail(out, "describe --no-inherited")
        if payload is None:
            return False
        if payload.get("inherited_methods"):
            print(
                f"  [FAIL] inherited_methods should be empty: "
                f"{payload['inherited_methods']!r}"
            )
            return False
        # Without --no-inherited.
        rc, out, _err = _run_code_graph([
            "--src", str(tmp), "describe", "Suppressible", "--json",
        ])
        payload = _parse_json_or_fail(out, "describe (default)")
        if payload is None:
            return False
        if not payload.get("inherited_methods"):
            print("  [FAIL] inherited_methods unexpectedly empty by default")
            return False
    print("  [ok] describe: --no-inherited suppresses inherited block")
    return True


def fixture_path_max_depth_limits_walk(src_root: Path) -> bool:
    """`--max-depth N` truncates BFS at depth N (`kind=no_path` for chains
    that exist but are longer)."""
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = _write_fakepipe(Path(tmp_str), {
            "fakepipe/main.py": '''
                from spyglass.utils.dj_mixin import SpyglassMixin
                class Top(SpyglassMixin):
                    definition = """
                    top_id: int
                    ---
                    """
                class Mid1(SpyglassMixin):
                    definition = """
                    -> Top
                    mid1_id: int
                    ---
                    """
                class Mid2(SpyglassMixin):
                    definition = """
                    -> Mid1
                    mid2_id: int
                    ---
                    """
                class Bottom(SpyglassMixin):
                    definition = """
                    -> Mid2
                    bottom_id: int
                    ---
                    """
            ''',
            "utils/dj_mixin.py": "class SpyglassMixin: pass\n",
        })
        rc, out, _err = _run_code_graph([
            "--src", str(tmp), "path", "--to", "Top", "Bottom",
            "--max-depth", "1", "--json",
        ])
        if rc != 0:
            print(f"  [FAIL] --max-depth 1 rc={rc}")
            return False
        payload = _parse_json_or_fail(out, "path --max-depth 1")
        if payload is None:
            return False
        if payload.get("kind") != "no_path":
            print(f"  [FAIL] expected no_path at depth 1: {payload!r}")
            return False
        # Same chain at sufficient depth resolves.
        rc, out, _err = _run_code_graph([
            "--src", str(tmp), "path", "--to", "Top", "Bottom",
            "--max-depth", "5", "--json",
        ])
        payload = _parse_json_or_fail(out, "path --max-depth 5")
        if payload is None or payload.get("kind") == "no_path":
            print(f"  [FAIL] depth 5 should reach Bottom: {payload!r}")
            return False
    print("  [ok] path --max-depth: truncates correctly, sufficient depth resolves")
    return True


def fixture_path_disambig_flags_resolve_ambiguous(src_root: Path) -> bool:
    """`path --to A B --from-file/--to-file PATH` and `--up X --file PATH`
    select among multi-file candidates rather than exit-3-ing.

    Pins the recovery contract for the ambiguous case — the whole point
    of these flags.
    """
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = _write_fakepipe(Path(tmp_str), {
            "fakepipe/v0/main.py": '''
                from spyglass.utils.dj_mixin import SpyglassMixin
                class Ambig(SpyglassMixin):
                    definition = """
                    ambig_id: int
                    ---
                    """
                class DownV0(SpyglassMixin):
                    definition = """
                    -> Ambig
                    extra: varchar(32)
                    """
            ''',
            "fakepipe/v1/main.py": '''
                from spyglass.utils.dj_mixin import SpyglassMixin
                class Ambig(SpyglassMixin):
                    definition = """
                    ambig_id: int
                    ---
                    """
                class DownV1(SpyglassMixin):
                    definition = """
                    -> Ambig
                    extra: varchar(32)
                    """
            ''',
            "utils/dj_mixin.py": "class SpyglassMixin: pass\n",
        })
        # Without --from-file, exit 3 (ambiguous).
        rc, out, _err = _run_code_graph([
            "--src", str(tmp), "path", "--to", "Ambig", "DownV0", "--json",
        ])
        if rc != 3:
            print(f"  [FAIL] expected exit 3 without --from-file, got {rc}: {out[:200]!r}")
            return False
        # With --from-file, resolves and finds path.
        rc, out, _err = _run_code_graph([
            "--src", str(tmp), "path", "--to", "Ambig", "DownV0",
            "--from-file", "spyglass/fakepipe/v0/main.py", "--json",
        ])
        if rc != 0:
            print(f"  [FAIL] --from-file should resolve: rc={rc}, out={out[:200]!r}")
            return False
        payload = _parse_json_or_fail(out, "path --to with --from-file")
        if payload is None or payload.get("kind") == "no_path":
            print(f"  [FAIL] expected real path: {payload!r}")
            return False
        # `describe --file` for the same shape.
        rc, out, _err = _run_code_graph([
            "--src", str(tmp), "describe", "Ambig",
            "--file", "spyglass/fakepipe/v1/main.py", "--json",
        ])
        if rc != 0:
            print(f"  [FAIL] describe --file should resolve: rc={rc}")
            return False
        payload = _parse_json_or_fail(out, "describe --file")
        if payload is None:
            return False
        chosen_file = (payload.get("class") or {}).get("file", "")
        if "/v1/" not in chosen_file:
            print(f"  [FAIL] --file should pick v1: {chosen_file!r}")
            return False
        # `--up Ambig --file PATH` for the directional walk.
        rc, out, _err = _run_code_graph([
            "--src", str(tmp), "path", "--up", "Ambig",
            "--file", "spyglass/fakepipe/v0/main.py", "--json",
        ])
        if rc != 0:
            print(f"  [FAIL] --up Ambig --file should resolve: rc={rc}")
            return False
    print("  [ok] disambiguation flags resolve multi-file ambiguous classes")
    return True


def fixture_describe_mixin_registry_path_miss_returns_unresolved(src_root: Path) -> bool:
    """When ``MIXIN_REGISTRY`` pins a mixin to a specific file but no
    record exists at that path, ``resolve_base`` must return None — NOT
    silently fall back to a same-named class elsewhere — and ``describe``
    must demote the base entry from ``inherits_resolved`` to
    ``inherits_unresolved``.

    Pins the registry-path-authoritative contract: if you pin
    ``"SpyglassMixin": "spyglass/utils/dj_mixin.py"`` but the class
    actually lives in ``some/other/file.py``, the validator/CLI MUST
    fail loud rather than silently picking the wrong file.
    """
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = _write_fakepipe(Path(tmp_str), {
            # SpyglassMixin lives at the WRONG path (not utils/dj_mixin.py).
            "wrong/place.py": "class SpyglassMixin:\n    def shadow_method(self): ...\n",
            "fakepipe/main.py": '''
                from spyglass.wrong.place import SpyglassMixin
                class UsesShadow(SpyglassMixin):
                    definition = """
                    use_id: int
                    ---
                    """
            ''',
        })
        # Verify resolve_base directly: returns None for a registry-pinned
        # mixin whose record isn't at the pinned path.
        sys.path.insert(0, str(SCRIPT_DIR))
        try:
            import _index
            _index.scan.cache_clear()
            idx = _index.scan(tmp)
            resolved = _index.resolve_base("SpyglassMixin", idx)
            if resolved is not None:
                print(
                    "  [FAIL] resolve_base should return None for registry-path "
                    f"miss; got: {resolved!r}"
                )
                return False
        finally:
            _index.scan.cache_clear()
        # And describe demotes the base.
        rc, out, _err = _run_code_graph([
            "--src", str(tmp), "describe", "UsesShadow", "--json",
        ])
        if rc != 0:
            print(f"  [FAIL] describe rc={rc}")
            return False
        payload = _parse_json_or_fail(out, "describe with shadow mixin")
        if payload is None:
            return False
        bases = payload.get("bases") or []
        sgm = next((b for b in bases if b.get("name") == "SpyglassMixin"), None)
        if sgm is None or sgm.get("kind") != "inherits_unresolved":
            print(
                "  [FAIL] expected SpyglassMixin demoted to "
                f"inherits_unresolved; got: {sgm!r}"
            )
            return False
    print("  [ok] MIXIN_REGISTRY path-miss: resolve_base→None, describe→inherits_unresolved")
    return True


def fixture_parse_definition_handles_edge_cases(src_root: Path) -> bool:
    """Pin a few `parse_definition` edge cases (auto_increment,
    `[nullable]`/`[unique]` strip, multi-line `.proj()`, inline `#`
    comment with quotes). Real-Spyglass fixtures exercise these
    transitively; explicit pins prevent silent regressions.
    """
    sys.path.insert(0, str(SCRIPT_DIR))
    try:
        import _index
        # auto_increment flag.
        defn = "id: int auto_increment\n---\nname: varchar(32)\n"
        pk, non_pk, _fks = _index.parse_definition(defn, base_lineno=1)
        if not pk or pk[0].name != "id":
            print(f"  [FAIL] auto_increment not parsed: pk={pk!r}")
            return False
        if not pk[0].auto_increment:
            print("  [FAIL] auto_increment flag dropped")
            return False
        if not non_pk or non_pk[0].name != "name":
            print(f"  [FAIL] non_pk lost: {non_pk!r}")
            return False
        # [nullable] / [unique] option-block stripping on FK.
        defn = "-> [nullable] OtherTable\n---\n"
        _pk, _non_pk, fks = _index.parse_definition(defn, base_lineno=1)
        if not fks or fks[0].parent != "OtherTable":
            print(f"  [FAIL] [nullable] option-block not stripped: {fks!r}")
            return False
        # Multi-line .proj()
        defn = (
            "-> Master.proj(\n"
            "    new_a='old_a',\n"
            "    new_b='old_b',\n"
            ")\n---\n"
        )
        _pk, _non_pk, fks = _index.parse_definition(defn, base_lineno=1)
        if not fks or dict(fks[0].renames) != {"new_a": "old_a", "new_b": "old_b"}:
            print(f"  [FAIL] multi-line .proj() not flattened: {fks!r}")
            return False
        # Inline `#` comment with embedded quote.
        defn = "id: int  # \"a quoted\" comment\n---\n"
        pk, _non_pk, _fks = _index.parse_definition(defn, base_lineno=1)
        if not pk or pk[0].name != "id":
            print(f"  [FAIL] inline comment with quotes broke parse: {pk!r}")
            return False
    finally:
        pass
    print("  [ok] parse_definition: auto_increment, [nullable], multi-line proj, quoted comments")
    return True


def fixture_payload_schema_stability(src_root: Path) -> bool:
    """Pin the top-level field set of every JSON payload kind so a refactor
    can't silently drop / rename a contract field.

    Per ``kind`` the agent's branching contract is:

    * Every payload: ``schema_version``, ``kind``, ``graph``,
      ``authority``, ``source_root``.
    * ``path``: ``from``, ``to``, ``hops``, ``max_depth``,
      ``truncated``, ``truncated_at_depth``.
    * ``no_path``: ``from``, ``to``, ``reason``, ``max_depth``,
      ``truncated``, ``truncated_at_depth``.
    * ``ancestors`` / ``descendants``: ``root``, ``max_depth``,
      ``truncated``, ``truncated_at_depth``, ``nodes``, ``edges``.
    * ``describe``: per the describe output contract.
    * ``find-method``: ``method``, ``defined_at``, ``inherited_via``.
    * ``not_found``: ``name`` (or ``method``) and ``hint``.
    * ``ambiguous``: ``name``, ``candidates``, ``hint``.

    Per node entry: ``name``, ``qualname``, ``file``, ``line``,
    ``record_id``, ``node_kind`` (when ``idx`` was passed in).
    Per hop: same fields plus ``kind`` and ``evidence``.
    """
    universal = {"schema_version", "kind", "graph", "authority", "source_root"}
    expected_per_kind = {
        "path": {"from", "to", "hops", "max_depth", "truncated", "truncated_at_depth"},
        "no_path": {
            "from", "to", "reason", "max_depth", "truncated", "truncated_at_depth",
        },
        "ancestors": {
            "root", "max_depth", "truncated", "truncated_at_depth",
            "nodes", "edges",
        },
        "descendants": {
            "root", "max_depth", "truncated", "truncated_at_depth",
            "nodes", "edges",
        },
        "describe": {
            "class", "bases", "pk_fields", "non_pk_fields", "fk_edges",
            "body_methods", "inherited_methods", "parts", "warnings",
        },
        "find-method": {"method", "defined_at", "inherited_via"},
        "not_found": {"hint"},  # `name` xor `method` depending on subcommand.
        "ambiguous": {"name", "candidates", "hint"},
        "info": {
            "subcommands", "exit_codes", "node_kind_values", "fk_edge_kinds",
            "ownership_kinds", "warning_kinds", "payload_envelopes",
        },
    }
    node_required = {"name", "qualname", "file", "line", "record_id"}

    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = _write_fakepipe(Path(tmp_str), {
            "utils/dj_mixin.py": '''
                class SpyglassMixin:
                    def fetch_nwb(self): pass
            ''',
            "fakepipe/v1/main.py": '''
                from spyglass.utils.dj_mixin import SpyglassMixin
                class Root(SpyglassMixin):
                    definition = """
                    root_id: int
                    ---
                    """
                class Mid(SpyglassMixin):
                    definition = """
                    -> Root
                    mid_id: int
                    ---
                    """
                class Leaf(SpyglassMixin):
                    definition = """
                    -> Mid
                    ---
                    """
            ''',
        })

        def _check(cli_args: list[str], expected_kind: str, expect_node_kind: bool) -> bool:
            rc, out, _err = _run_code_graph(["--src", str(tmp), *cli_args, "--json"])
            payload = _parse_json_or_fail(out, f"{cli_args} schema")
            if payload is None:
                print(f"  [FAIL] {cli_args}: no JSON; rc={rc}")
                return False
            if payload.get("kind") != expected_kind:
                print(
                    f"  [FAIL] {cli_args}: expected kind={expected_kind!r}, "
                    f"got {payload.get('kind')!r}"
                )
                return False
            missing = (universal | expected_per_kind[expected_kind]) - payload.keys()
            if missing:
                print(
                    f"  [FAIL] {cli_args} ({expected_kind}): missing top-level "
                    f"fields {sorted(missing)}; got {sorted(payload.keys())}"
                )
                return False
            # Provenance values must be the documented constants.
            if payload["graph"] != "code":
                print(f"  [FAIL] {cli_args}: graph != 'code': {payload['graph']!r}")
                return False
            if payload["authority"] != "source-only":
                print(
                    f"  [FAIL] {cli_args}: authority != 'source-only': "
                    f"{payload['authority']!r}"
                )
                return False
            # Node-shape spot-check: pick one node from each shape.
            sample_nodes: list[dict] = []
            if expected_kind == "path":
                sample_nodes = [payload["from"], payload["to"], *payload["hops"]]
            elif expected_kind == "no_path":
                sample_nodes = [payload["from"], payload["to"]]
            elif expected_kind in ("ancestors", "descendants"):
                sample_nodes = [payload["root"], *payload["nodes"]]
            for n in sample_nodes:
                missing_node = node_required - n.keys()
                if missing_node:
                    print(
                        f"  [FAIL] {cli_args}: node {n.get('qualname')!r} missing "
                        f"required fields {sorted(missing_node)}"
                    )
                    return False
                if expect_node_kind and "node_kind" not in n:
                    print(
                        f"  [FAIL] {cli_args}: node {n.get('qualname')!r} missing "
                        f"node_kind"
                    )
                    return False
            return True

        # Exercise every documented payload kind.
        cases = [
            (["path", "--to", "Root", "Leaf"], "path", True),
            (["path", "--up", "Leaf"], "ancestors", True),
            (["path", "--down", "Root"], "descendants", True),
            (["describe", "Root"], "describe", False),
            (["find-method", "fetch_nwb"], "find-method", False),
            (["path", "--up", "Nonexistent"], "not_found", False),
            (["info"], "info", False),
        ]
        for cli_args, expected_kind, expect_node_kind in cases:
            if not _check(cli_args, expected_kind, expect_node_kind):
                return False

        # Cross-check `info`'s declared envelopes against actual top-level
        # fields of every other payload kind. If `info` says path has fields
        # X but the path payload only has Y, the agent's contract drift
        # silently. This catches the exact bug shape (info envelopes lying
        # about other payloads' shape, not just about info's own shape).
        rc, out, _err = _run_code_graph(["--src", str(tmp), "info", "--json"])
        info_payload = _parse_json_or_fail(out, "info envelope cross-check")
        if info_payload is None:
            return False
        envelopes = info_payload["payload_envelopes"]
        for kind, declared in envelopes.items():
            if kind in ("every_payload", "info"):
                continue
            if kind not in expected_per_kind:
                # info is documenting a payload kind the test doesn't cover.
                continue
            declared_set = set(declared)
            expected_set = expected_per_kind[kind]
            # `not_found` envelope uses `name_or_method` as a docstring
            # placeholder for the xor field; skip the strict equality there.
            if kind == "not_found":
                continue
            mismatch = declared_set ^ expected_set
            if mismatch:
                print(
                    f"  [FAIL] info payload_envelopes[{kind!r}] "
                    f"disagrees with actual: declared={sorted(declared_set)}, "
                    f"actual={sorted(expected_set)}, mismatch={sorted(mismatch)}"
                )
                return False

        # ambiguous: synthesize by requesting an ambiguous-by-shadow class.
        # We add a second `Root` in another file to force ambiguity without
        # --file.
        Path(tmp / "spyglass" / "fakepipe" / "v0" / "main.py").parent.mkdir(
            parents=True, exist_ok=True,
        )
        (tmp / "spyglass" / "fakepipe" / "v0" / "main.py").write_text(textwrap.dedent('''
            from spyglass.utils.dj_mixin import SpyglassMixin
            class Root(SpyglassMixin):
                definition = """
                v0_id: int
                ---
                """
        '''))
        if not _check(["path", "--up", "Root"], "ambiguous", False):
            return False

    print(
        "  [ok] schema stability: every payload kind carries "
        "{schema_version, kind, graph, authority, source_root} + per-kind contract fields"
    )
    return True


def fixture_path_truncation_marker(src_root: Path) -> bool:
    """``--max-depth`` cutting off BFS must surface
    ``truncated: true`` + ``truncated_at_depth`` on the payload, so the
    agent can rerun with a larger depth instead of treating the result
    as complete.
    """
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = _write_fakepipe(Path(tmp_str), {
            "utils/dj_mixin.py": "class SpyglassMixin: pass\n",
            "fakepipe/main.py": '''
                from spyglass.utils.dj_mixin import SpyglassMixin
                class A(SpyglassMixin):
                    definition = """
                    a_id: int
                    ---
                    """
                class B(SpyglassMixin):
                    definition = """
                    -> A
                    ---
                    """
                class C(SpyglassMixin):
                    definition = """
                    -> B
                    ---
                    """
                class D(SpyglassMixin):
                    definition = """
                    -> C
                    ---
                    """
            ''',
        })
        # max-depth 1 from A: should reach B but not C/D → truncated.
        rc, out, _err = _run_code_graph([
            "--src", str(tmp), "path", "--down", "A", "--max-depth", "1", "--json",
        ])
        if rc != 0:
            print(f"  [FAIL] --down A --max-depth 1 rc={rc}")
            return False
        payload = _parse_json_or_fail(out, "shallow walk")
        if payload is None:
            return False
        if payload.get("truncated") is not True:
            print(f"  [FAIL] expected truncated=True at max-depth 1: {payload!r}")
            return False
        if payload.get("truncated_at_depth") != 1:
            print(f"  [FAIL] expected truncated_at_depth=1: {payload!r}")
            return False
        # max-depth 5 from A: enough to reach D → not truncated.
        rc, out, _err = _run_code_graph([
            "--src", str(tmp), "path", "--down", "A", "--max-depth", "5", "--json",
        ])
        payload = _parse_json_or_fail(out, "deep walk")
        if payload is None:
            return False
        if payload.get("truncated") is not False:
            print(f"  [FAIL] expected truncated=False at max-depth 5: {payload!r}")
            return False
        if payload.get("truncated_at_depth") is not None:
            print(
                f"  [FAIL] expected truncated_at_depth=null when not truncated: "
                f"{payload!r}"
            )
            return False
    print(
        "  [ok] truncation: --max-depth cutoff surfaces truncated=true + "
        "truncated_at_depth"
    )
    return True


def fixture_path_merge_master_hop_kind_is_specific(src_root: Path) -> bool:
    """Tighten `fixture_path_names_merge_master_hop`: assert the master-part
    hop specifically has `kind == "merge_part"`, not just that some hop
    in the chain has a permissive kind. Pre-tightening, a regression
    that swapped `merge_part`/`nested_part` labels would have passed.
    """
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = _write_fakepipe(Path(tmp_str), {
            "fakepipe/main.py": '''
                from spyglass.utils.dj_merge_tables import _Merge
                from spyglass.utils.dj_mixin import SpyglassMixin

                class Upstream(SpyglassMixin):
                    definition = """
                    upstream_id: int
                    ---
                    """

                class MergeMaster(_Merge, SpyglassMixin):
                    definition = """
                    merge_id: uuid
                    ---
                    source: varchar(32)
                    """

                    class UpstreamPart(SpyglassMixin):
                        definition = """
                        -> master
                        -> Upstream
                        """

                class Downstream(SpyglassMixin):
                    definition = """
                    -> MergeMaster
                    extra: varchar(32)
                    """
            ''',
            "utils/dj_merge_tables.py": "class Merge: pass\n_Merge = Merge\n",
            "utils/dj_mixin.py": "class SpyglassMixin: pass\n",
        })
        rc, out, _err = _run_code_graph([
            "--src", str(tmp), "path", "--to", "Upstream", "Downstream", "--json",
        ])
        if rc != 0:
            print(f"  [FAIL] rc={rc}")
            return False
        payload = _parse_json_or_fail(out, "merge-part kind specificity")
        if payload is None:
            return False
        hops = payload.get("hops") or []
        # The specific hop where master-part bridge applies is the one
        # whose `to` is MergeMaster (or `from` is MergeMaster.UpstreamPart).
        master_part_hops = [
            h for h in hops
            if h.get("kind") == "merge_part"
        ]
        if not master_part_hops:
            kinds = [h.get("kind") for h in hops]
            print(
                "  [FAIL] no `merge_part` hop in chain; got kinds: "
                f"{kinds!r}"
            )
            return False
    print("  [ok] path: merge-master containment hop labeled merge_part specifically")
    return True


# ---------------------------------------------------------------------------
# Real-Spyglass smoke fixtures (gated on the real source tree).
#
# Every fixture above runs against a synthetic Spyglass-shaped tree —
# deterministic, hermetic, no bumps when Spyglass moves. These smoke
# fixtures verify the same correctness on REAL Spyglass and pin the
# specific failure shapes the second-pass review caught:
#   * `--up LFPBandV1` selects the v1 LFPBandSelection record.
#   * `--down LFPV1` reaches RippleTimesV1.
#   * `--down LFPV1` does NOT leak v0 LFPBand or sibling merge parts.
#   * Position pipelines (TrodesPosV1 / DLCPosV1) chain to LinearizedPositionV1.
#
# Skipped (printed but not failed) when ``--spyglass-src`` doesn't point
# at a real Spyglass checkout, so contributors without one can still run
# the synthetic suite. The gate looks for ``spyglass/lfp/v1/lfp.py`` —
# any real Spyglass at any recent version has that file.
# ---------------------------------------------------------------------------


def _real_spyglass_available(src_root: Path) -> bool:
    """True iff ``src_root`` looks like a real Spyglass source tree."""
    return (src_root / "spyglass" / "lfp" / "v1" / "lfp.py").is_file()


def fixture_real_spyglass_up_lfpbandv1_picks_v1_lfpbandselection(src_root: Path) -> bool:
    """Real Spyglass: ``--up LFPBandV1`` must surface ``LFPBandSelection``
    cited at ``spyglass/lfp/analysis/v1/lfp_band.py`` (the v1 record),
    not at ``spyglass/common/common_ephys.py`` (the v0 record). The
    same-package preference picks v1 because LFPBandV1 lives in v1.
    """
    if not _real_spyglass_available(src_root):
        print(f"  [skip] real Spyglass not at {src_root!r} — synthetic suite covers this case")
        return True
    rc, out, err = _run_code_graph([
        "--src", str(src_root), "path", "--up", "LFPBandV1",
        "--max-depth", "2", "--json",
    ])
    if rc != 0:
        print(f"  [FAIL] --up LFPBandV1 rc={rc}: {err[:300]!r}")
        return False
    payload = _parse_json_or_fail(out, "real --up LFPBandV1")
    if payload is None:
        return False
    nodes = payload.get("nodes", [])
    shared = next((n for n in nodes if n["qualname"] == "LFPBandSelection"), None)
    if shared is None:
        print("  [FAIL] LFPBandSelection missing from --up LFPBandV1 ancestors")
        return False
    if shared["file"] != "spyglass/lfp/analysis/v1/lfp_band.py":
        print(
            f"  [FAIL] LFPBandSelection cited as {shared['file']!r}, "
            "expected spyglass/lfp/analysis/v1/lfp_band.py (v1 record)"
        )
        return False
    if "common/common_ephys.py" in shared["file"]:
        print(f"  [FAIL] LFPBandSelection regressed to v0 record: {shared['file']!r}")
        return False
    print("  [ok] real Spyglass: --up LFPBandV1 cites v1 LFPBandSelection")
    return True


def fixture_real_spyglass_down_lfpv1_reaches_rippletimesv1(src_root: Path) -> bool:
    """Real Spyglass: ``--down LFPV1`` must transit
    ``LFPV1 → LFPOutput.LFPV1 → LFPOutput → LFPBandSelection (v1) →
    LFPBandV1 → RippleLFPSelection → RippleTimesV1`` to demonstrate the
    impact-cascade promise (the original "dead-ends at LFPOutput.LFPV1"
    bug is what this PR fixes).
    """
    if not _real_spyglass_available(src_root):
        print(f"  [skip] real Spyglass not at {src_root!r} — synthetic suite covers this case")
        return True
    rc, out, err = _run_code_graph([
        "--src", str(src_root), "path", "--down", "LFPV1",
        "--max-depth", "10", "--json",
    ])
    if rc != 0:
        print(f"  [FAIL] --down LFPV1 rc={rc}: {err[:300]!r}")
        return False
    payload = _parse_json_or_fail(out, "real --down LFPV1")
    if payload is None:
        return False
    descendants = {n["qualname"] for n in payload.get("nodes", [])}
    required = {
        "LFPOutput.LFPV1", "LFPOutput", "LFPBandSelection",
        "LFPBandV1", "RippleLFPSelection", "RippleTimesV1",
    }
    missing = required - descendants
    if missing:
        print(
            f"  [FAIL] --down LFPV1 missing impact-cascade hops: {sorted(missing)} "
            f"(impact cascade through merge master regressed)"
        )
        return False
    print("  [ok] real Spyglass: --down LFPV1 reaches RippleTimesV1 via LFPOutput")
    return True


def fixture_real_spyglass_down_lfpv1_excludes_sibling_and_v0_leaks(src_root: Path) -> bool:
    """Real Spyglass: ``--down LFPV1`` must NOT include sibling parts
    of LFPOutput (``ImportedLFP``, ``CommonLFP``) or v0-only consumers
    of LFPBandSelection (``LFPBand``). These are the exact leaks the
    second-pass review flagged before the record-aware refactor.
    """
    if not _real_spyglass_available(src_root):
        print(f"  [skip] real Spyglass not at {src_root!r} — synthetic suite covers this case")
        return True
    rc, out, err = _run_code_graph([
        "--src", str(src_root), "path", "--down", "LFPV1",
        "--max-depth", "10", "--json",
    ])
    if rc != 0:
        print(f"  [FAIL] --down LFPV1 rc={rc}: {err[:300]!r}")
        return False
    payload = _parse_json_or_fail(out, "real --down LFPV1 (leak exclusion)")
    if payload is None:
        return False
    nodes_by_qn = {n["qualname"]: n for n in payload.get("nodes", [])}
    forbidden_sibling_parts = ["LFPOutput.ImportedLFP", "LFPOutput.CommonLFP"]
    leaks = [q for q in forbidden_sibling_parts if q in nodes_by_qn]
    if leaks:
        print(
            f"  [FAIL] --down LFPV1 fanned out to sibling parts: {leaks!r} "
            "(skip_parts regressed at master crossing)"
        )
        return False
    # v0 LFPBand is in spyglass/common/common_ephys.py. The v1 ancestor
    # chain shouldn't reach it. (LFPBand is v0-only — not LFPBandV1.)
    if "LFPBand" in nodes_by_qn:
        v0_leak = nodes_by_qn["LFPBand"]
        if "common/common_ephys.py" in v0_leak.get("file", ""):
            print(
                f"  [FAIL] v0 LFPBand surfaced as descendant: {v0_leak!r} "
                "(same-qualname leakage at master crossing regressed)"
            )
            return False
    # v0 LFPBandSelection.LFPBandElectrode in common_ephys.py would
    # similarly indicate a v0 leak. The v1 nested part (in lfp_band.py)
    # is fine.
    elec = nodes_by_qn.get("LFPBandSelection.LFPBandElectrode")
    if elec is not None and "common/common_ephys.py" in elec.get("file", ""):
        print(
            f"  [FAIL] v0 LFPBandSelection.LFPBandElectrode surfaced: {elec!r} "
            "(same-qualname leakage at master crossing regressed)"
        )
        return False
    print(
        "  [ok] real Spyglass: --down LFPV1 excludes sibling parts and v0 leaks"
    )
    return True


def fixture_real_spyglass_position_chains_reach_linearized(src_root: Path) -> bool:
    """Real Spyglass: position pipelines reach LinearizedPositionV1 via
    the PositionOutput merge.

    Pins both the Trodes and DLC chains to confirm the merge-master
    bridge works for any upstream pipeline, not just LFP.
    """
    if not _real_spyglass_available(src_root):
        print(f"  [skip] real Spyglass not at {src_root!r} — synthetic suite covers this case")
        return True
    for upstream in ("TrodesPosV1", "DLCPosV1"):
        rc, out, err = _run_code_graph([
            "--src", str(src_root), "path", "--to", upstream, "LinearizedPositionV1",
            "--json",
        ])
        if rc != 0:
            print(f"  [FAIL] --to {upstream} LinearizedPositionV1 rc={rc}: {err[:300]!r}")
            return False
        payload = _parse_json_or_fail(out, f"real --to {upstream} LinearizedPositionV1")
        if payload is None:
            return False
        if payload.get("kind") == "no_path":
            print(f"  [FAIL] no path from {upstream} to LinearizedPositionV1: {payload!r}")
            return False
        hops = payload.get("hops") or []
        # Chain must transit PositionOutput master via merge_part bridge.
        kinds = [h.get("kind") for h in hops]
        if "merge_part" not in kinds:
            print(
                f"  [FAIL] {upstream} → LinearizedPositionV1 chain missing merge_part hop "
                f"(should bridge PositionOutput); kinds={kinds!r}"
            )
            return False
    print(
        "  [ok] real Spyglass: TrodesPosV1 + DLCPosV1 chain to LinearizedPositionV1 "
        "via PositionOutput"
    )
    return True


FIXTURES = [
    fixture_path_finds_direct_fk_path,
    fixture_path_names_merge_master_hop,
    fixture_path_disambiguates_multi_file_class,
    fixture_path_walks_up_and_down,
    fixture_path_walk_polarity_for_merge_masters,
    fixture_path_down_cascades_through_merge_master_to_deep_consumer,
    fixture_path_down_part_does_not_fan_out_to_sibling_parts,
    fixture_path_walk_picks_same_package_record_for_same_qualname,
    fixture_path_down_excludes_v0_consumers_through_master,
    fixture_path_to_still_bridges_master_part,
    fixture_path_edge_meta_walks_all_records_for_qualname,
    fixture_path_hop_citation_matches_record_that_owns_edge,
    fixture_path_no_path_returns_kind_no_path,
    fixture_path_not_found_returns_exit_4,
    fixture_path_accepts_dotted_qualname,
    fixture_dotted_qualname_respects_file_hint,
    fixture_path_max_depth_limits_walk,
    fixture_path_disambig_flags_resolve_ambiguous,
    fixture_path_merge_master_hop_kind_is_specific,
    fixture_payload_schema_stability,
    fixture_path_truncation_marker,
    fixture_describe_lists_body_level_methods,
    fixture_describe_annotates_datajoint_bases,
    fixture_describe_parses_pk_and_fk_renames,
    fixture_describe_walks_transitive_sub_mixin,
    fixture_describe_alias_merge_resolves_inherited_methods,
    fixture_describe_disambiguates_multi_file_class,
    fixture_describe_no_inherited_suppresses,
    fixture_describe_mixin_registry_path_miss_returns_unresolved,
    fixture_findmethod_lists_mixin_owner_and_inherited,
    fixture_findmethod_orders_multiple_owners,
    fixture_findmethod_returns_exit_4_for_unknown,
    fixture_parse_definition_handles_edge_cases,
    # Real-Spyglass smoke (gated; auto-skip when --spyglass-src isn't real).
    fixture_real_spyglass_up_lfpbandv1_picks_v1_lfpbandselection,
    fixture_real_spyglass_down_lfpv1_reaches_rippletimesv1,
    fixture_real_spyglass_down_lfpv1_excludes_sibling_and_v0_leaks,
    fixture_real_spyglass_position_chains_reach_linearized,
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--spyglass-src", type=Path, required=True,
        help="Path to spyglass src/ directory (parity with test_validator_regressions; "
        "synthetic trees handle most fixtures)",
    )
    args = parser.parse_args()
    print(f"Running {len(FIXTURES)} code_graph fixtures...")
    passed = 0
    for fixture in FIXTURES:
        print(f"\n{fixture.__name__}:")
        if fixture(args.spyglass_src):
            passed += 1
    print(f"\n{'=' * 60}")
    print(f"{passed}/{len(FIXTURES)} fixtures passed")
    return 0 if passed == len(FIXTURES) else 1


if __name__ == "__main__":
    sys.exit(main())
