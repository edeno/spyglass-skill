#!/usr/bin/env python3
"""Regression fixtures for the Spyglass skill validator.

Each fixture is a previously-fixed bug cast as a synthetic markdown input.
The test asserts that the validator still catches it. If a future refactor
accidentally stops detecting one of these classes of bug, the test fails.

Run:  python tests/test_validator_regressions.py --spyglass-src PATH/TO/src

Exit 0 if every fixture is still caught, 1 otherwise.
"""

import argparse
import sys
import tempfile
import textwrap
from contextlib import contextmanager
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import validate_skill as v  # noqa: E402


def _write_md(body):
    """Write a synthetic markdown file and return its path."""
    tmp = Path(tempfile.mkdtemp())
    md = tmp / "fixture.md"
    md.write_text(textwrap.dedent(body))
    return md


@contextmanager
def _with_md_files(md_path):
    """Temporarily point `v.collect_md_files` at one synthetic file.

    Restores the original binding on exit so a fixture that forgets to
    patch can't inherit the previous fixture's synthetic file. Use this
    anywhere a check reads through `collect_md_files`.
    """
    saved = v.collect_md_files
    v.collect_md_files = lambda: [md_path]
    try:
        yield
    finally:
        v.collect_md_files = saved


@contextmanager
def _with_md_file_list(md_paths):
    """Variant of `_with_md_files` accepting multiple synthetic files.

    Used by cross-file checks (like the duplication detector) that must
    see >1 file to produce a finding. Same restoration semantics.
    """
    saved = v.collect_md_files
    v.collect_md_files = lambda: list(md_paths)
    try:
        yield
    finally:
        v.collect_md_files = saved


def _write_named_md(dir_path, name, body):
    """Write a synthetic md file with a chosen name into an existing dir.

    Useful when a check reports by filename and the test asserts on those
    filenames; `_write_md` uses a fixed `fixture.md` which collides when a
    fixture needs >1 synthetic file.
    """
    md = dir_path / name
    md.write_text(textwrap.dedent(body))
    return md


def _run(check_fn, md_path, *args):
    """Run a single validator check against one synthetic md file."""
    with _with_md_files(md_path):
        results = v.ValidationResult()
        check_fn(*args, results) if args else check_fn(results)
    return results


def _assert_contains(results, needle, label):
    """Fail loud if the expected substring is missing from results.failed."""
    hits = [m for m in results.failed if needle in m]
    if hits:
        print(f"  [ok] {label}")
        return True
    print(f"  [FAIL] {label}")
    print(f"         expected fail containing: {needle!r}")
    print(f"         actual failures: {results.failed}")
    return False


def _assert_warn_contains(results, needle, label):
    hits = [m for m in results.warnings if needle in m]
    if hits:
        print(f"  [ok] {label}")
        return True
    print(f"  [FAIL] {label}")
    print(f"         expected warning containing: {needle!r}")
    print(f"         actual warnings: {results.warnings}")
    return False


def fixture_syntax_ellipsis_after_kwargs(src_root):
    """Real bug from figurl.md: `f(kw=1, ...)` raises SyntaxError."""
    md = _write_md(
        """
        # Test

        ```python
        CurationV1.insert_curation(sorting_id=sid, labels={}, ...)
        ```
        """
    )
    r = _run(v.check_python_syntax, md)
    return _assert_contains(
        r, "SyntaxError", "syntax: ellipsis after kwargs caught"
    )


def fixture_trailing_underscore_nwb(src_root):
    """insert_sessions with copy filename (ends in `_.nwb`)."""
    md = _write_md(
        """
        # Test

        ```python
        sgi.insert_sessions("my_session_.nwb")
        ```
        """
    )
    r = _run(v.check_anti_patterns, md)
    return _assert_contains(
        r, "trailing-underscore-nwb",
        "anti-pattern: trailing _.nwb copy name caught",
    )


def fixture_skip_duplicates_raw_ingestion(src_root):
    """skip_duplicates=True inside insert_sessions, even with nested parens."""
    md = _write_md(
        """
        # Test

        ```python
        sgi.insert_sessions(
            ("a.nwb", "b.nwb"),
            skip_duplicates=True,
        )
        ```
        """
    )
    r = _run(v.check_anti_patterns, md)
    return _assert_contains(
        r, "skip-duplicates-raw-ingestion",
        "anti-pattern: skip_duplicates + nested parens caught",
    )


def fixture_broken_anchor(src_root):
    """Typo in section anchor (#spyglasmixin vs #spyglassmixin)."""
    md = _write_md(
        """
        # Test

        - [Section](#nonexistent-section)

        ## Real Section
        body
        """
    )
    r = _run(v.check_markdown_links, md)
    return _assert_contains(
        r, "broken anchor", "link: broken anchor caught"
    )


def fixture_broken_file_link(src_root):
    """Typo in referenced file name."""
    md = _write_md(
        """
        # Test

        See [guide](references/does_not_exist.md) for details.
        """
    )
    r = _run(v.check_markdown_links, md)
    return _assert_contains(
        r, "broken link target", "link: broken file link caught"
    )


def fixture_stale_prose_path(src_root):
    """Prose references a non-existent repo path."""
    md = _write_md(
        """
        # Test

        See `src/spyglass/totally_fake_module.py` for details.
        """
    )
    r = _run(v.check_prose_paths, md, src_root)
    return _assert_contains(
        r, "totally_fake_module.py", "path: stale prose path caught"
    )


def fixture_glob_not_false_positive(src_root):
    """Glob pattern in prose must NOT trigger a path failure."""
    md = _write_md(
        """
        # Test

        See `src/spyglass/**/*.py` for the layout.
        """
    )
    r = _run(v.check_prose_paths, md, src_root)
    # expect no failures related to this glob path
    bad = [m for m in r.failed if "src/spyglass/**" in m]
    if not bad:
        print("  [ok] path: glob pattern not flagged as false positive")
        return True
    print("  [FAIL] glob triggered false positive:", bad)
    return False


def fixture_unresolved_uppercase_warns(src_root):
    """Typo in class name (uppercase-first) should produce a warning."""
    md = _write_md(
        """
        # Test

        ```python
        SpikeSortingRecordngSelection.insert_selection({"x": 1})
        ```
        """
    )
    with _with_md_files(md):
        results = v.ValidationResult()
        registry = v._ClassRegistry(src_root, results)
        v.check_methods(src_root, results, registry=registry)
    return _assert_warn_contains(
        results,
        "unresolved class 'SpikeSortingRecordngSelection'",
        "method: unresolved uppercase class warns",
    )


def fixture_spyglassmixin_not_first(src_root):
    """Class inherits from dj.X without SpyglassMixin/SpyglassMixinPart first."""
    md = _write_md(
        """
        # Test

        ```python
        import datajoint as dj

        @schema
        class BadComputed(dj.Computed):
            definition = ""

        @schema
        class AlsoBad(SomeOtherMixin, dj.Manual):
            definition = ""
        ```
        """
    )
    r = _run(v.check_anti_patterns, md)
    hits = [m for m in r.failed if "spyglassmixin-not-first" in m]
    if len(hits) >= 2:
        print("  [ok] anti-pattern: SpyglassMixin-not-first caught (both cases)")
        return True
    print(f"  [FAIL] expected >=2 hits, got {len(hits)}: {r.failed}")
    return False


def fixture_spyglassmixin_ordering_ok(src_root):
    """Correct ordering (SpyglassMixin first) must NOT trigger the check.

    Covers: single-line inheritance, multi-line inheritance,
    SpyglassMixinPart alone (no dj base), and SpyglassMixin + dj.Part
    (the canonical merge-part shape seen in real Spyglass code).
    """
    md = _write_md(
        """
        # Test

        ```python
        import datajoint as dj

        @schema
        class GoodComputed(SpyglassMixin, dj.Computed):
            definition = ""

        @schema
        class GoodPart(SpyglassMixinPart):
            definition = ""

        @schema
        class GoodMultiline(
            SpyglassMixin,
            dj.Computed,
        ):
            definition = ""

        class MergePart(SpyglassMixin, dj.Part):
            definition = ""
        ```
        """
    )
    r = _run(v.check_anti_patterns, md)
    hits = [m for m in r.failed if "spyglassmixin-not-first" in m]
    if not hits:
        print("  [ok] anti-pattern: correct ordering not false-positive")
        return True
    print(f"  [FAIL] correct ordering triggered check: {hits}")
    return False


def fixture_missing_notebook(src_root):
    """Reference to a notebook that doesn't exist in py_scripts/."""
    md = _write_md(
        """
        # Test

        See `99_Nonexistent_Notebook.py` for details.
        """
    )
    r = _run(v.check_notebook_names, md, src_root)
    return _assert_contains(
        r, "99_Nonexistent_Notebook.py",
        "notebook: missing notebook filename caught",
    )


def fixture_merge_classmethod_discard(src_root):
    """(Table & key).merge_*() classmethod-restriction-discard footgun."""
    md = _write_md(
        """
        # Test

        ```python
        # Dangerous: merge_delete is a classmethod, `& merge_key` discarded
        (PositionOutput & merge_key).merge_delete()

        # Also dangerous: merge_restrict returns whole-table view here
        (LFPOutput & {"nwb_file_name": f}).merge_restrict()
        ```
        """
    )
    r = _run(v.check_anti_patterns, md)
    hits = [m for m in r.failed if "merge-classmethod-discard" in m]
    if len(hits) >= 2:
        print("  [ok] anti-pattern: (Table & k).merge_*() discard caught (both)")
        return True
    print(f"  [FAIL] expected >=2 hits, got {len(hits)}: {r.failed}")
    return False


def fixture_merge_classmethod_multiline(src_root):
    """Multi-line restriction + nested-parens forms that the old regex missed.

    Regex used `[^)]+` for the restriction expression and wasn't multiline,
    so `(PositionOutput & get_key()).merge_delete()` (nested parens) and
    multi-line restrictions could both evade detection. The AST matcher
    resolves BinOp receivers regardless of formatting.
    """
    md = _write_md(
        '''
        # Test

        ```python
        def get_key():
            return {"x": 1}

        # Nested parens in the restriction — old regex missed this
        (PositionOutput & get_key()).merge_delete()

        # Multi-line restriction — old regex sometimes missed, sometimes not
        (
            LFPOutput
            & {"nwb_file_name": "x",
               "epoch": 1}
        ).merge_restrict()
        ```
        '''
    )
    r = _run(v.check_anti_patterns, md)
    hits = [m for m in r.failed if "merge-classmethod-discard" in m]
    if len(hits) >= 2:
        print("  [ok] anti-pattern: nested-parens + multi-line merge "
              "discard caught")
        return True
    print(f"  [FAIL] expected >=2 hits, got {len(hits)}: {r.failed}")
    return False


def fixture_required_claim_alternatives(src_root):
    """Grouped-alternative needles: any of the listed phrasings should pass.

    Routes through the real `_evaluate_required_claim` helper (extracted
    from `check_prose_assertions` so this test doesn't have to mirror the
    whole SKILL_DIR). A prior version re-implemented the match logic
    inline, which meant the test couldn't catch a refactor that broke the
    isinstance(needle, str) branch.
    """
    positive = _write_md(
        """
        # Test

        The skill demands user confirmation before any destructive op.
        """
    )
    negative = _write_md(
        """
        # Test

        Just delete whatever you need.
        """
    )
    alts = ["explicit confirmation", "user confirmation",
            "user confirms", "get user confirmation"]
    pos_results = v.ValidationResult()
    v._evaluate_required_claim(
        positive, "fixture.md", "test-rule", "alt-form accepted",
        alts, pos_results,
    )
    neg_results = v.ValidationResult()
    v._evaluate_required_claim(
        negative, "fixture.md", "test-rule", "alt-form accepted",
        alts, neg_results,
    )
    passed = len(pos_results.passed) == 1 and len(pos_results.failed) == 0
    failed = len(neg_results.failed) == 1 and len(neg_results.passed) == 0
    if passed and failed:
        print("  [ok] prose: grouped-alternative needle accepts any match")
        return True
    print(f"  [FAIL] positive {pos_results.passed=} {pos_results.failed=}; "
          f"negative {neg_results.passed=} {neg_results.failed=}")
    return False


def fixture_harness_restores_collect_md_files(src_root):
    """The `_with_md_files` context manager must restore the original
    binding, even when the body raises. If restore ever breaks, a later
    fixture that forgets to patch will silently inherit this fixture's
    md_path — a class of flaky-test bug the code review flagged.
    """
    sentinel = _write_md("# Test\n")
    before = v.collect_md_files
    try:
        with _with_md_files(sentinel):
            raise RuntimeError("forced")
    except RuntimeError:
        pass
    after = v.collect_md_files
    if before is after:
        print("  [ok] harness: _with_md_files restores on exception")
        return True
    print(f"  [FAIL] collect_md_files not restored (before={before!r} "
          f"after={after!r})")
    return False


def fixture_dash_range_citation(src_root):
    """Dash-range `file.py:N-M` must validate both endpoints, not just N.

    Regression: the first-cut regex matched only `N,M` (comma lists); any
    `N-M` range silently under-checked because the engine stopped at the
    dash. Stale upper bounds slipped through on citations like `:88-108`.
    """
    md = _write_md(
        """
        # Test

        In-range range `src/spyglass/common/common_nwbfile.py:1-5` is fine,
        but `src/spyglass/common/common_nwbfile.py:1-9999999` must fail.
        """
    )
    r = _run(v.check_citation_lines, md, src_root)
    # The in-range line should pass, the out-of-range endpoint should fail
    hits = [m for m in r.failed if "9999999" in m and "out of range" in m]
    if hits:
        print("  [ok] citation: dash-range upper bound bounds-checked")
        return True
    print(f"  [FAIL] dash-range upper not caught: {r.failed}")
    return False


def fixture_aliased_merge_classmethod_discard(src_root):
    """Aliased merge-table class in `(Alias & key).merge_delete()` must
    still fire the classmethod-discard anti-pattern.

    Regression: the check originally compared `left.id` directly to
    MERGE_TABLE_CLASSES, missing aliased imports like
    `from ... import PositionOutput as PO`. Fixed by routing the receiver
    name through `build_alias_map` before the membership test.
    """
    md = _write_md(
        """
        # Test

        ```python
        from spyglass.position.position_merge import PositionOutput as PO

        (PO & merge_key).merge_delete()
        ```
        """
    )
    r = _run(v.check_anti_patterns, md)
    hits = [m for m in r.failed if "merge-classmethod-discard" in m]
    if hits:
        print("  [ok] anti-pattern: aliased merge-table discard caught")
        return True
    print(f"  [FAIL] aliased merge-table discard missed: {r.failed}")
    return False


def fixture_eval_hallucinated_method(src_root):
    """Synthetic evals.json must catch three distinct failure shapes:

    1. Hallucinated method (AttributeError at runtime) — this was the
       first class of bug the check was designed to prevent.
    2. Instance method called on bare class like `LFPBandV1.compute_signal_power(...)`
       (TypeError: missing self) — this is the bug that actually shipped
       in eval 6 and motivated extending the validator to scan evals.
    3. forbidden_substrings entries must be SKIPPED entirely, since
       they're adversarial wrong-by-design patterns the eval rejects.
    """
    import json
    import tempfile
    from pathlib import Path as P
    tmp = P(tempfile.mkdtemp())
    evals_dir = tmp / "evals"
    evals_dir.mkdir()
    evals_file = evals_dir / "evals.json"
    evals_file.write_text(json.dumps({
        "evals": [{
            "id": 999,
            "eval_name": "synthetic-hallucination",
            "expected_output": (
                "The answer is `LFPBandV1.totally_fake_method(foo=1)` "
                "which does not exist. Also `LFPBandV1.compute_signal_power(band_key)` "
                "on the bare class should be flagged — compute_signal_power "
                "is an instance method and must be called on "
                "`(LFPBandV1 & key)()` / `LFPBandV1().compute_signal_power(...)`."
            ),
            "assertions": {
                "required_substrings": [],
                "forbidden_substrings": ["LFPBandV1.yet_another_fake()"],
                "behavioral_checks": [],
            },
        }],
    }))
    original = v.SKILL_DIR
    v.SKILL_DIR = tmp
    try:
        results = v.ValidationResult()
        v.check_evals_content(src_root, results)
    finally:
        v.SKILL_DIR = original

    hits_hallucinated = [m for m in results.failed if "totally_fake_method" in m]
    # The instance-method failure message includes "instance method" in the
    # standard format produced by check_evals_content.
    hits_instance = [
        m for m in results.failed
        if "compute_signal_power" in m and "instance method" in m
    ]
    bad_hits = [m for m in results.failed if "yet_another_fake" in m]

    if hits_hallucinated and hits_instance and not bad_hits:
        print(
            "  [ok] evals: hallucinated method + instance-on-bare-class caught; "
            "forbidden_substrings skipped"
        )
        return True
    print("  [FAIL] expected both failure shapes flagged; forbidden skipped")
    print(f"         hallucinated hits: {hits_hallucinated}")
    print(f"         instance hits:     {hits_instance}")
    print(f"         forbidden bad:     {bad_hits}")
    print(f"         failed:            {results.failed}")
    return False


def fixture_eval_citation_lines_out_of_range(src_root):
    """Eval prose with `file.py:NNN` citing a line past EOF should fail.
    Mirrors check_citation_lines (markdown) onto evals.json."""
    import json
    import tempfile
    from pathlib import Path as P
    tmp = P(tempfile.mkdtemp())
    (tmp / "evals").mkdir()
    (tmp / "evals" / "evals.json").write_text(json.dumps({
        "evals": [{
            "id": 999,
            "eval_name": "synthetic-citation-out-of-range",
            "expected_output": (
                "See `src/spyglass/common/common_nwbfile.py:9999999` "
                "(this is wrong on purpose — past EOF)."
            ),
            "assertions": {
                "required_substrings": [],
                "forbidden_substrings": [],
                "behavioral_checks": [],
            },
        }],
    }))
    original = v.SKILL_DIR
    v.SKILL_DIR = tmp
    try:
        results = v.ValidationResult()
        v.check_eval_citation_lines(src_root, results)
    finally:
        v.SKILL_DIR = original
    hits = [
        m for m in results.failed
        if "evals.json[id=999]" in m and "out of range" in m
    ]
    if hits:
        print("  [ok] evals: out-of-range citation in eval prose caught")
        return True
    print("  [FAIL] expected out-of-range citation fail")
    print(f"         failed: {results.failed}")
    return False


def fixture_eval_pr_citation_warns(src_root):
    """Eval prose with `PR #nnn` should warn — same rule as markdown.
    Mirrors check_no_pr_citations onto evals.json."""
    import json
    import tempfile
    from pathlib import Path as P
    tmp = P(tempfile.mkdtemp())
    (tmp / "evals").mkdir()
    (tmp / "evals" / "evals.json").write_text(json.dumps({
        "evals": [{
            "id": 999,
            "eval_name": "synthetic-pr-citation",
            "expected_output": (
                "Fixed in PR #1234 — this prose mention should warn."
            ),
            "assertions": {
                "required_substrings": [],
                "forbidden_substrings": [],
                "behavioral_checks": [],
            },
        }],
    }))
    original = v.SKILL_DIR
    v.SKILL_DIR = tmp
    try:
        results = v.ValidationResult()
        v.check_eval_no_pr_citations(results)
    finally:
        v.SKILL_DIR = original
    hits = [
        m for m in results.warnings
        if "evals.json[id=999]" in m and "PR #1234" in m
    ]
    if hits:
        print("  [ok] evals: PR-number citation in eval prose caught")
        return True
    print("  [FAIL] expected PR-citation warning")
    print(f"         warnings: {results.warnings}")
    return False


def fixture_eval_prose_path_missing(src_root):
    """Eval prose with `src/spyglass/...` pointing at a non-existent
    path should fail. Mirrors check_prose_paths onto evals.json."""
    import json
    import tempfile
    from pathlib import Path as P
    tmp = P(tempfile.mkdtemp())
    (tmp / "evals").mkdir()
    (tmp / "evals" / "evals.json").write_text(json.dumps({
        "evals": [{
            "id": 999,
            "eval_name": "synthetic-stale-path",
            "expected_output": (
                "See `src/spyglass/zzz_no_such_module/imaginary.py` "
                "(this path does not exist in the repo)."
            ),
            "assertions": {
                "required_substrings": [],
                "forbidden_substrings": [],
                "behavioral_checks": [],
            },
        }],
    }))
    original = v.SKILL_DIR
    v.SKILL_DIR = tmp
    try:
        results = v.ValidationResult()
        v.check_eval_prose_paths(src_root, results)
    finally:
        v.SKILL_DIR = original
    hits = [
        m for m in results.failed
        if "evals.json[id=999]" in m and "does not exist" in m
    ]
    if hits:
        print("  [ok] evals: stale src/spyglass path in eval prose caught")
        return True
    print("  [FAIL] expected stale-path fail")
    print(f"         failed: {results.failed}")
    return False


def fixture_eval_citation_content_drift_warns(src_root):
    """Eval prose with a `file.py:N` citation whose line doesn't contain
    the named backticked identifier within ±8 lines should warn.

    This generalizes check_citation_content (markdown-only) to evals.json,
    closing the gap that let the round-3 'position_merge.py:16 (registers
    IntervalPositionInfo)' off-by-one ship — actual entry was line 15.
    """
    import json
    import tempfile
    from pathlib import Path as P
    tmp = P(tempfile.mkdtemp())
    evals_dir = tmp / "evals"
    evals_dir.mkdir()
    evals_file = evals_dir / "evals.json"
    # Cite common_session.py:1 (top of file: imports / module docstring),
    # then back-tick a class name from far below it. The real Session class
    # in spyglass starts well below line 9; line 1 is import area, so the
    # ±8 window can't see it and the warn must fire.
    evals_file.write_text(json.dumps({
        "evals": [{
            "id": 999,
            "eval_name": "synthetic-citation-drift",
            "expected_output": (
                "The `Session` table is fully described at "
                "`src/spyglass/common/common_session.py:1` (this is wrong on "
                "purpose — line 1 is imports, not the class)."
            ),
            "assertions": {
                "required_substrings": [],
                "forbidden_substrings": [],
                "behavioral_checks": [],
            },
        }],
    }))
    original = v.SKILL_DIR
    v.SKILL_DIR = tmp
    try:
        results = v.ValidationResult()
        v.check_eval_citation_content(src_root, results)
    finally:
        v.SKILL_DIR = original

    drift_hits = [
        m for m in results.warnings
        if "evals.json[id=999]" in m and "citation may be stale" in m
    ]
    if drift_hits:
        print("  [ok] evals: citation-content drift caught in eval prose")
        return True
    print("  [FAIL] expected eval-prose citation-drift warning")
    print(f"         warnings: {results.warnings}")
    return False


def fixture_bogus_citation_line(src_root):
    """Line number in `file.py:NNN` must actually exist in the file."""
    md = _write_md(
        """
        # Test

        The bug lives at `src/spyglass/common/common_nwbfile.py:9999999`.
        """
    )
    r = _run(v.check_citation_lines, md, src_root)
    return _assert_contains(
        r, "out of range",
        "citation: out-of-range line number caught",
    )


def fixture_valid_citation_passes(src_root):
    """Real citation (existing file, in-range line) must not fail."""
    md = _write_md(
        """
        # Test

        See `src/spyglass/common/common_nwbfile.py:1` for context.
        """
    )
    r = _run(v.check_citation_lines, md, src_root)
    bad = [m for m in r.failed if "common_nwbfile.py" in m]
    if not bad:
        print("  [ok] citation: valid in-range citation passes")
        return True
    print(f"  [FAIL] valid citation rejected: {bad}")
    return False


def fixture_multi_line_citation(src_root):
    """`file.py:N, M` must validate each cited line."""
    md = _write_md(
        """
        # Test

        See `src/spyglass/utils/dj_merge_tables.py:1, 9999999`.
        """
    )
    r = _run(v.check_citation_lines, md, src_root)
    # Expect a failure mentioning only the out-of-range line
    hits = [m for m in r.failed if "out of range" in m and "9999999" in m]
    if hits:
        print("  [ok] citation: multi-line citation catches bogus line")
        return True
    print(f"  [FAIL] multi-line citation not checked correctly: {r.failed}")
    return False


def fixture_wrong_field_name_warns(src_root):
    """Typo in a dict restriction key should warn via field-name check.

    Paradigm case from the code-review audit: `moseq_model_params_name` is
    not the real column — it's `model_params_name`. This check would have
    flagged that typo at skill-write time.
    """
    md = _write_md(
        """
        # Test

        ```python
        from spyglass.behavior.v1.moseq import MoseqModelParams

        # Wrong: real field is `model_params_name` (no `moseq_` prefix)
        (MoseqModelParams & {"moseq_model_params_name": "x"}).fetch1()
        ```
        """
    )
    with _with_md_files(md):
        results = v.ValidationResult()
        v.check_restriction_fields(src_root, results)
    return _assert_warn_contains(
        results, "moseq_model_params_name",
        "schema: wrong field name in dict restriction warns",
    )


def fixture_correct_field_name_no_warn(src_root):
    """Correct field name must NOT trigger the schema check."""
    md = _write_md(
        """
        # Test

        ```python
        from spyglass.behavior.v1.moseq import MoseqModelParams

        (MoseqModelParams & {"model_params_name": "x"}).fetch1()
        ```
        """
    )
    with _with_md_files(md):
        results = v.ValidationResult()
        v.check_restriction_fields(src_root, results)
    bad = [w for w in results.warnings if "model_params_name" in w]
    if not bad:
        print("  [ok] schema: correct field name does not warn")
        return True
    print(f"  [FAIL] correct field name triggered warn: {bad}")
    return False


def fixture_merge_restriction_not_false_positive(src_root):
    """`(PositionOutput & {"nwb_file_name": f})` is legitimate — the master
    has only (merge_id, source), but users restrict merges with part-table
    fields. The schema check skips merge-table classes to avoid flagging
    this canonical pattern.
    """
    md = _write_md(
        """
        # Test

        ```python
        from spyglass.position.position_merge import PositionOutput

        (PositionOutput & {"nwb_file_name": "x.nwb"}).fetch(as_dict=True)
        ```
        """
    )
    with _with_md_files(md):
        results = v.ValidationResult()
        v.check_restriction_fields(src_root, results)
    bad = [w for w in results.warnings if "nwb_file_name" in w]
    if not bad:
        print("  [ok] schema: merge-table restriction not flagged")
        return True
    print(f"  [FAIL] merge-table restriction triggered warn: {bad}")
    return False


def fixture_alias_import_resolves(src_root):
    """Aliased `from spyglass.X import Class as Alias` must resolve through
    the alias to validate `Alias.method()` against the real class.

    Regression: pre-AST validator only matched bare class names via regex and
    silently skipped `Sess.insert_selection(...)` as an unresolved name.
    """
    md = _write_md(
        """
        # Test

        ```python
        from spyglass.spikesorting.v1 import SpikeSortingRecordingSelection as SSR

        # Real method — must resolve through alias and pass
        SSR.insert_selection({"nwb_file_name": "x"})

        # Bogus method — must resolve through alias and fail
        SSR.nonexistent_method({"x": 1})
        ```
        """
    )
    with _with_md_files(md):
        results = v.ValidationResult()
        registry = v._ClassRegistry(src_root, results)
        v.check_methods(src_root, results, registry=registry)
    bad = [m for m in results.failed if "nonexistent_method" in m]
    good = [m for m in results.passed if "insert_selection" in m]
    if bad and good:
        print("  [ok] method: alias import resolves (valid + invalid)")
        return True
    print("  [FAIL] expected one fail and one pass")
    print(f"         failures: {results.failed}")
    print(f"         passes:   {[p for p in results.passed if 'SpikeSorting' in p]}")
    return False


def fixture_module_qualified_resolves(src_root):
    """`import spyglass.X as sgc; sgc.Class.method()` must resolve to Class.

    Regression: module-qualified receivers (two dots) did not match the old
    regex at all and were silently skipped.
    """
    md = _write_md(
        """
        # Test

        ```python
        import spyglass.spikesorting.v1 as ssv1

        # Real method via module alias
        ssv1.SpikeSortingRecordingSelection.insert_selection({"nwb_file_name": "x"})

        # Bogus method via module alias
        ssv1.SpikeSortingRecordingSelection.nonexistent_method({"x": 1})
        ```
        """
    )
    with _with_md_files(md):
        results = v.ValidationResult()
        registry = v._ClassRegistry(src_root, results)
        v.check_methods(src_root, results, registry=registry)
    bad = [m for m in results.failed if "nonexistent_method" in m]
    good = [m for m in results.passed if "insert_selection" in m]
    if bad and good:
        print("  [ok] method: module-qualified call resolves (valid + invalid)")
        return True
    print("  [FAIL] expected one fail and one pass")
    print(f"         failures: {results.failed}")
    print(f"         passes:   {[p for p in results.passed if 'SpikeSorting' in p]}")
    return False


def fixture_alias_kwarg_validation(src_root):
    """Kwarg checking must follow aliases too — `Sess.method(bogus_kw=...)`
    should fail exactly like `Session.method(bogus_kw=...)` would.
    """
    md = _write_md(
        """
        # Test

        ```python
        from spyglass.spikesorting.v1 import SpikeSortingRecordingSelection as SSR

        SSR.insert_selection({"nwb_file_name": "x"}, totally_fake_kwarg=True)
        ```
        """
    )
    with _with_md_files(md):
        results = v.ValidationResult()
        registry = v._ClassRegistry(src_root, results)
        v.check_kwargs(src_root, results, registry=registry)
    return _assert_contains(
        results, "totally_fake_kwarg",
        "kwarg: alias-resolved call still kwarg-checks",
    )


def fixture_binop_receiver_not_false_positive(src_root):
    """`(Table & key).method()` must NOT produce a bogus method-not-found
    failure. BinOp receivers resolve to None in the new AST checker, which
    is the same intentional skip the old regex accidentally produced.
    """
    md = _write_md(
        """
        # Test

        ```python
        from spyglass.position.position_merge import PositionOutput

        # Restricted relation — receiver is a BinOp expression. This is
        # the merge-classmethod anti-pattern for merge_delete (caught by
        # the dedicated check), but for a non-merge method like
        # insert_selection it's a legitimate if-unusual pattern we don't
        # want to flag as a method lookup failure.
        result = (PositionOutput & {"x": 1}).fetch(limit=10)
        ```
        """
    )
    with _with_md_files(md):
        results = v.ValidationResult()
        registry = v._ClassRegistry(src_root, results)
        v.check_methods(src_root, results, registry=registry)
    bad = [m for m in results.failed if "PositionOutput" in m]
    if not bad:
        print("  [ok] method: BinOp receiver not flagged as unresolved method")
        return True
    print(f"  [FAIL] BinOp receiver triggered false positive: {bad}")
    return False


def fixture_merge_classmethod_correct_form_ok(src_root):
    """Correct forms `Table.merge_*(restriction)` must NOT trigger."""
    md = _write_md(
        """
        # Test

        ```python
        PositionOutput.merge_delete(merge_key)
        PositionOutput.merge_delete_parent(merge_key, dry_run=True)
        LFPOutput.merge_restrict({"nwb_file_name": f})
        LFPOutput.merge_get_part(key)
        ```
        """
    )
    r = _run(v.check_anti_patterns, md)
    hits = [m for m in r.failed if "merge-classmethod-discard" in m]
    if not hits:
        print("  [ok] anti-pattern: correct Table.merge_*() form not false-positive")
        return True
    print(f"  [FAIL] correct form triggered check: {hits}")
    return False


def fixture_insert1_wrong_pk_field(src_root):
    """LinearizationSelection.insert1({"merge_id": ...}) must warn.

    Apr 21 bug: the example used the un-projected parent field `merge_id`.
    LinearizationSelection is defined with `-> PositionOutput.proj(
    pos_merge_id='merge_id')`, so the valid FK name is `pos_merge_id`.

    Includes a `<!-- pipeline-version: v1 -->` marker so the multi-
    version class resolves to v1's schema (the post-graph-resolution
    fail-loud policy returns None for unmarked multi-version refs).
    """
    md = _write_md(
        """
        <!-- pipeline-version: v1 -->
        # Test

        ```python
        from spyglass.linearization.v1.main import LinearizationSelection

        LinearizationSelection.insert1({
            "merge_id": "bad",
            "track_graph_name": "x",
            "linearization_param_name": "y",
        })
        ```
        """
    )
    with _with_md_files(md):
        results = v.ValidationResult()
        v.check_insert_key_shape(src_root, results)
    return _assert_warn_contains(
        results, "key 'merge_id' not in schema",
        "key-shape: un-projected parent PK caught",
    )


def fixture_insert1_extraneous_field(src_root):
    """`interval_list_name` isn't in LinearizationSelection's schema. Must warn."""
    md = _write_md(
        """
        <!-- pipeline-version: v1 -->
        # Test

        ```python
        from spyglass.linearization.v1.main import LinearizationSelection

        LinearizationSelection.insert1({
            "pos_merge_id": "ok",
            "track_graph_name": "x",
            "linearization_param_name": "y",
            "interval_list_name": "nope",
        })
        ```
        """
    )
    with _with_md_files(md):
        results = v.ValidationResult()
        v.check_insert_key_shape(src_root, results)
    return _assert_warn_contains(
        results, "key 'interval_list_name' not in schema",
        "key-shape: extraneous non-schema field caught",
    )


def fixture_insert1_proj_renamed_ok(src_root):
    """Correct projected name `pos_merge_id` must NOT warn."""
    md = _write_md(
        """
        <!-- pipeline-version: v1 -->
        # Test

        ```python
        from spyglass.linearization.v1.main import LinearizationSelection

        LinearizationSelection.insert1({
            "pos_merge_id": "ok",
            "track_graph_name": "x",
            "linearization_param_name": "y",
        })
        ```
        """
    )
    with _with_md_files(md):
        results = v.ValidationResult()
        v.check_insert_key_shape(src_root, results)
    # Assert zero warnings on this call — not just zero mentioning a
    # particular field name. A narrower filter would pass even if the
    # check spuriously flagged `track_graph_name` or any other valid key.
    bad = [w for w in results.warnings if "LinearizationSelection" in w]
    if not bad:
        print("  [ok] key-shape: correct projected name accepted")
        return True
    print(f"  [FAIL] projected name wrongly warned: {bad}")
    return False


def fixture_insert1_spread_kwargs(src_root):
    """`.insert1({**something, ...})` must be skipped (can't verify spread)."""
    md = _write_md(
        """
        <!-- pipeline-version: v1 -->
        # Test

        ```python
        from spyglass.linearization.v1.main import LinearizationSelection

        base = {"track_graph_name": "x"}
        LinearizationSelection.insert1({
            **base,
            "merge_id": "would_normally_be_flagged",
        })
        ```
        """
    )
    with _with_md_files(md):
        results = v.ValidationResult()
        v.check_insert_key_shape(src_root, results)
    bad = [w for w in results.warnings if "LinearizationSelection" in w]
    if not bad:
        print("  [ok] key-shape: **spread dict skipped (fail-open)")
        return True
    print(f"  [FAIL] spread dict wrongly warned: {bad}")
    return False


def fixture_insert1_diamond_projection(src_root):
    """Diamond inheritance where sibling parents project the same ancestor
    must correctly apply BOTH renames.

    Synthetic schema:
        D  has pk {x}
        B  `-> D.proj(x_from_b='x')`   own PK {x_from_b}
        C  `-> D.proj(x_from_c='x')`   own PK {x_from_c}
        A  `-> B`, `-> C`              own PK {x_from_b, x_from_c}

    Valid insert keys for A = {x_from_b, x_from_c}. `x` (D's raw name)
    must NOT appear. The old shared-_seen implementation would union
    D's un-renamed fields in through B's walk, then cycle-guard out
    of C's walk of D, leaving `x` spuriously in the accepted set.

    Uses a synthetic `schemas` dict so the test doesn't depend on real
    Spyglass having this exact shape — today it doesn't, which is why
    the bug stayed latent.
    """
    import tempfile
    import textwrap
    from pathlib import Path as P

    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = P(tmp_str)
        files = {
            "fakepipe/d.py": '''
                class D:
                    definition = """
                    x: int
                    ---
                    """
            ''',
            "fakepipe/b.py": '''
                class B:
                    definition = """
                    -> D.proj(x_from_b='x')
                    ---
                    """
            ''',
            "fakepipe/c.py": '''
                class C:
                    definition = """
                    -> D.proj(x_from_c='x')
                    ---
                    """
            ''',
            "fakepipe/a.py": '''
                class A:
                    definition = """
                    -> B
                    -> C
                    ---
                    """
            ''',
        }
        for rel, body in files.items():
            path = tmp / "spyglass" / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(textwrap.dedent(body))

        v.clear_caches()
        try:
            idx = v._index.scan(tmp)
            fields = idx.insert_fields_for("A")
        finally:
            v.clear_caches()

        expected = {"x_from_b", "x_from_c"}
        if fields == expected:
            print("  [ok] key-shape: diamond projection resolves both renames")
            return True
        print(f"  [FAIL] diamond projection returned {fields!r}, expected {expected!r}")
        return False


def fixture_singular_plural_hint_added(src_root):
    """Singular/plural near-miss adds a 'did you mean ...?' suggestion.

    Real bug class from audit rounds: ``trodes_pos_param_name`` (singular)
    instead of the actual schema field ``trodes_pos_params_name``. The
    existing field-missing warning would catch the typo, but the new hint
    makes it actionable.
    """
    md = _write_md(
        """
        # Test

        ```python
        TrodesPosParams & {"trodes_pos_param_name": "default"}
        ```
        """
    )
    with _with_md_files(md):
        results = v.ValidationResult()
        v.check_restriction_fields(src_root, results)
    return _assert_warn_contains(
        results, "did you mean 'trodes_pos_params_name'?",
        "key-shape: singular/plural hint surfaces correct field",
    )


def fixture_partial_populate_pk_warns(src_root):
    """`Class.populate({...})` covering a strict subset of PK must warn.

    Real bug from PR #22 round-3 in `spikesorting_v1_pipeline.md`:
    ``BurstPair.populate({"metric_curation_id": ...})`` left
    ``burst_params_name`` open and re-ran across every BurstPairParams
    row paired with that curation. Synthetic schema mirrors the shape:
    PK is {a, b}, populate restricts only by {a}.
    """
    import tempfile
    import textwrap
    from pathlib import Path as P

    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = P(tmp_str)
        files = {
            "fakepipe/t.py": '''
                class T:
                    definition = """
                    a: int
                    b: varchar(80)
                    ---
                    """
            ''',
        }
        for rel, body in files.items():
            path = tmp / "spyglass" / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(textwrap.dedent(body))

        md = _write_md(
            """
            # Test

            ```python
            T.populate({"a": 1})
            ```
            """
        )
        v.clear_caches()
        try:
            with _with_md_files(md):
                results = v.ValidationResult()
                v.check_insert_key_shape(tmp, results)
        finally:
            v.clear_caches()
    return _assert_warn_contains(
        results, "partial PK",
        "key-shape: partial-PK populate caught (BurstPair-shape regression)",
    )


def fixture_full_populate_pk_no_warn(src_root):
    """`Class.populate({...})` covering the full PK must NOT warn.

    Pairs with `fixture_partial_populate_pk_warns` to confirm the new
    check doesn't fire false positives on correctly-scoped populate
    calls. Same synthetic schema; restricts every PK field.
    """
    import tempfile
    import textwrap
    from pathlib import Path as P

    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = P(tmp_str)
        files = {
            "fakepipe/t.py": '''
                class T:
                    definition = """
                    a: int
                    b: varchar(80)
                    ---
                    """
            ''',
        }
        for rel, body in files.items():
            path = tmp / "spyglass" / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(textwrap.dedent(body))

        md = _write_md(
            """
            # Test

            ```python
            T.populate({"a": 1, "b": "x"})
            ```
            """
        )
        v.clear_caches()
        try:
            with _with_md_files(md):
                results = v.ValidationResult()
                v.check_insert_key_shape(tmp, results)
        finally:
            v.clear_caches()
    bad = [w for w in results.warnings if "partial PK" in w]
    if not bad:
        print("  [ok] key-shape: full-PK populate produces no partial-PK warning")
        return True
    print(f"  [FAIL] full-PK populate wrongly warned: {bad}")
    return False


def fixture_insert1_unknown_class(src_root):
    """`.insert1()` on a class not in KNOWN_CLASSES / auto-discovery skipped."""
    md = _write_md(
        """
        # Test

        ```python
        TotallyNotAClass.insert1({"anything": 1, "goes": 2})
        ```
        """
    )
    with _with_md_files(md):
        results = v.ValidationResult()
        v.check_insert_key_shape(src_root, results)
    bad = [w for w in results.warnings if "TotallyNotAClass" in w]
    if not bad:
        print("  [ok] key-shape: unknown class skipped (fail-open)")
        return True
    print(f"  [FAIL] unknown class wrongly warned: {bad}")
    return False


def fixture_duplicated_block_across_files(src_root):
    """A ≥5-line normalized block in 2+ files must warn.

    Guards the "bloat via accumulation" failure mode where similar examples
    leak into multiple references during per-PR review.
    """
    block = """
        # Test

        ```python
        key = {"nwb_file_name": "session.nwb"}
        rows = (SomeTable & key).fetch()
        for row in rows:
            processed = transform(row)
            results.append(processed)
        ```
        """
    tmp = Path(tempfile.mkdtemp())
    md_a = _write_named_md(tmp, "a.md", block)
    md_b = _write_named_md(tmp, "b.md", block)
    with _with_md_file_list([md_a, md_b]):
        results = v.ValidationResult()
        v.check_duplicated_blocks(results)
    return _assert_warn_contains(
        results, "duplication:",
        "duplication: 5+ line cross-file duplication caught",
    )


def fixture_duplicated_within_file_ok(src_root):
    """Same block repeated within one file must NOT warn — only cross-file
    duplication is flagged (the skill's bloat failure mode is accumulation
    across references, not redundancy inside one reference).
    """
    md = _write_md(
        """
        # Test

        ```python
        key = {"nwb_file_name": "session.nwb"}
        rows = (SomeTable & key).fetch()
        for row in rows:
            processed = transform(row)
            results.append(processed)
        ```

        ```python
        key = {"nwb_file_name": "session.nwb"}
        rows = (SomeTable & key).fetch()
        for row in rows:
            processed = transform(row)
            results.append(processed)
        ```
        """
    )
    r = _run(v.check_duplicated_blocks, md)
    hits = [w for w in r.warnings if "duplication:" in w]
    if not hits:
        print("  [ok] duplication: within-file repetition not flagged")
        return True
    print(f"  [FAIL] within-file repetition wrongly flagged: {hits}")
    return False


def fixture_shared_imports_not_dup(src_root):
    """Two files sharing only import lines (no executable code) must not
    warn. Import lines are excluded from the normalization — they're too
    commonly shared to be meaningful duplication signal.
    """
    imports_only = """
        # Test

        ```python
        from spyglass.common import Session
        from spyglass.common import IntervalList
        from spyglass.common import Nwbfile
        from spyglass.common import Electrode
        from spyglass.common import BrainRegion
        from spyglass.common import Subject
        ```
        """
    tmp = Path(tempfile.mkdtemp())
    md_a = _write_named_md(tmp, "a.md", imports_only)
    md_b = _write_named_md(tmp, "b.md", imports_only)
    with _with_md_file_list([md_a, md_b]):
        results = v.ValidationResult()
        v.check_duplicated_blocks(results)
    hits = [w for w in results.warnings if "duplication:" in w]
    if not hits:
        print("  [ok] duplication: import-only shared blocks not flagged")
        return True
    print(f"  [FAIL] import-only blocks wrongly flagged: {hits}")
    return False


@contextmanager
def _with_patched_attr(module, name, value):
    """Temporarily replace `module.name` with `value`, restoring on exit.

    Fixtures below patch `_discover_merge_masters_in_source` or
    `_parse_merge_registry_from_markdown` to simulate upstream drift
    without having to scaffold a synthetic Spyglass checkout. Using a
    context manager so a fixture that forgets to restore can't poison
    downstream fixtures.
    """
    saved = getattr(module, name)
    setattr(module, name, value)
    try:
        yield
    finally:
        setattr(module, name, saved)


def fixture_merge_registry_baseline_passes(src_root):
    """Current tree's merge-registry cross-check passes cleanly.

    If the tuple, markdown, and source fall out of sync in a real commit,
    the other two fixtures cover the failure paths. This fixture exists
    to catch a different kind of regression: a refactor that accidentally
    makes the check vacuous (e.g. the parser returns empty sets and every
    comparison is `empty ⊆ empty`). The baseline fixture asserts we see
    the three affirmative `[ok]` messages.
    """
    results = v.ValidationResult()
    v.check_merge_registry(src_root, results)
    required_phrases = [
        "merge masters in MERGE_MASTERS match Spyglass source",
        "merge_methods.md registry table matches MERGE_MASTERS",
        "NOT-a-merge entries confirmed as non-_Merge in source",
    ]
    passed_msgs = " ".join(results.passed)
    missing = [p for p in required_phrases if p not in passed_msgs]
    if missing or results.failed:
        print(f"  [FAIL] baseline merge-registry check didn't produce "
              f"all three affirmatives. missing={missing}, "
              f"failed={results.failed}")
        return False
    print("  [ok] merge-registry: baseline tree passes all three sub-checks")
    return True


def fixture_merge_registry_source_addition_caught(src_root):
    """Simulated new `_Merge` subclass upstream must fail the check.

    The most important drift case — if Spyglass adds a sixth merge
    master, the skill's registry is stale and the validator must say so.
    Simulated by patching the source-discovery helper to return an extra
    class name.
    """
    results = v.ValidationResult()
    simulated_source = set(v.MERGE_MASTERS) | {"FakeNewMergeOutput"}
    with _with_patched_attr(
        v, "_discover_merge_masters_in_source", lambda _src: simulated_source
    ):
        v.check_merge_registry(src_root, results)
    hit = any(
        "FakeNewMergeOutput" in msg and "new merge master upstream" in msg
        for msg in results.failed
    )
    if hit:
        print("  [ok] merge-registry: new upstream merge master caught")
        return True
    print(f"  [FAIL] expected a 'new merge master upstream' failure for "
          f"FakeNewMergeOutput. failed={results.failed}")
    return False


def fixture_merge_registry_md_misclassification_caught(src_root):
    """Markdown claiming a non-merge as a merge master must fail.

    Mirrors the `MuaEventsV1` slip we shipped pre-Phase-0: the registry
    listed a `dj.Computed` as a merge master. Simulated by patching the
    markdown parser to add a non-`_Merge` class to the claimed-merges
    set while the tuple stays correct.
    """
    results = v.ValidationResult()
    bogus_claimed_merges = set(v.MERGE_MASTERS) | {"MuaEventsV1"}
    bogus_claimed_non_merges = set()  # empty to isolate the failure
    with _with_patched_attr(
        v, "_parse_merge_registry_from_markdown",
        # 3-tuple: (claimed_merges, claimed_non_merges, marker_found).
        # marker_found=True so we don't cross-fire the marker-missing
        # check (3) path and confuse the assertion on check (2).
        lambda: (bogus_claimed_merges, bogus_claimed_non_merges, True),
    ):
        v.check_merge_registry(src_root, results)
    hit = any(
        "MuaEventsV1" in msg
        and "claimed as a merge master" in msg
        and "not in MERGE_MASTERS" in msg
        for msg in results.failed
    )
    if hit:
        print("  [ok] merge-registry: md claiming non-merge as merge caught")
        return True
    print(f"  [FAIL] expected a 'claimed as a merge master but not in "
          f"MERGE_MASTERS' failure for MuaEventsV1. failed={results.failed}")
    return False


def fixture_merge_registry_inverse_misclassification_caught(src_root):
    """Markdown's NOT-a-merge list containing an actual merge must fail.

    The inverse of the previous fixture — if upstream reclassifies a
    table (e.g. converts `MuaEventsV1` to a merge master) and the skill
    still lists it under NOT a merge, the check must catch the lie.
    Simulated by patching the parser to include `PositionOutput` (a real
    merge master) in the NOT-a-merge set.
    """
    results = v.ValidationResult()
    with _with_patched_attr(
        v, "_parse_merge_registry_from_markdown",
        lambda: (set(v.MERGE_MASTERS), {"PositionOutput"}, True),
    ):
        v.check_merge_registry(src_root, results)
    hit = any(
        "PositionOutput" in msg and "NOT a merge" in msg
        and "skill contradicts source" in msg
        for msg in results.failed
    )
    if hit:
        print("  [ok] merge-registry: md listing real merge as NOT-a-merge caught")
        return True
    print(f"  [FAIL] expected a 'skill contradicts source' failure for "
          f"PositionOutput in the NOT-a-merge list. failed={results.failed}")
    return False


def fixture_merge_registry_marker_missing_caught(src_root):
    """Dropping the `**Common lookalikes that are NOT merge tables`
    marker must produce a loud failure, not a silent skip.

    Before the fix this failed silently — the parser returned
    `claimed_non_merges=set()` and the NOT-a-merge subcheck did nothing.
    That would let an unrelated edit (reorganizing merge_methods.md to
    remove the bolded subsection header) quietly disable a third of the
    merge-registry check. The fix threads a `marker_found` flag through
    the parser return so check_merge_registry can emit an explicit fail
    when the marker isn't there.
    """
    results = v.ValidationResult()
    with _with_patched_attr(
        v, "_parse_merge_registry_from_markdown",
        # 3-tuple with marker_found=False — simulates the marker being
        # removed from merge_methods.md. The first two elements stay
        # consistent with the real tree so checks (1) and (2) pass
        # cleanly and only check (3) gates on the marker absence.
        lambda: (set(v.MERGE_MASTERS), set(), False),
    ):
        v.check_merge_registry(src_root, results)
    hit = any(
        "marker missing from merge_methods.md" in msg
        and "check (3) cannot run" in msg
        for msg in results.failed
    )
    if hit:
        print("  [ok] merge-registry: missing NOT-a-merge marker caught")
        return True
    print(f"  [FAIL] expected a 'marker missing' failure. "
          f"failed={results.failed}")
    return False


def fixture_skip_methods_spyglass_subset_still_exists(src_root):
    """Canonical DataJoint/Spyglass methods in SKIP_METHODS must still exist
    somewhere in the Spyglass source. Guards against silent erosion:
    adding a method to SKIP_METHODS suppresses real regressions for it,
    so renames upstream could silently un-police parts of the API.

    Only the DJ/Spyglass-facing subset is spot-checked — the set also
    contains Python builtins (keys/values/append), matplotlib methods
    (plot/set_xlabel/imshow), and pandas methods (where/idxmax) whose
    existence inside the Spyglass tree is not meaningful to verify.
    """
    # Curated list: methods the skill documents as DataJoint/Spyglass API
    # surface, not Python/matplotlib/pandas. If SKIP_METHODS drifts to no
    # longer contain one of these, the fixture fails loudly — prompting a
    # choice between updating the list here or reviving the suppression.
    canonical_spyglass_methods = [
        "fetch1", "fetch_nwb", "populate", "cautious_delete",
        "merge_delete", "merge_populate", "merge_get_part",
        "merge_restrict", "restrict_by", "insert_selection",
    ]
    missing_from_skip = [
        m for m in canonical_spyglass_methods if m != "insert_selection"
        and m not in v.SKIP_METHODS
    ]
    if missing_from_skip:
        print(f"  [FAIL] expected in SKIP_METHODS but absent: "
              f"{missing_from_skip}")
        return False
    # insert_selection is explicitly NOT in SKIP_METHODS — it's a Spyglass
    # convention the validator actively checks. Verify that intent holds.
    if "insert_selection" in v.SKIP_METHODS:
        print("  [FAIL] insert_selection wrongly added to SKIP_METHODS — "
              "it's a Spyglass convention the validator should check, "
              "not skip")
        return False
    # Grep-scope existence: each method name should appear as `def NAME`
    # somewhere under src/spyglass. Using plain text search (not AST walk)
    # keeps this cheap and matches inherited/overridden definitions on
    # mixin classes whose exact class name we don't want to hardcode.
    pkg_root = src_root / "spyglass"
    import re as _re
    missing_in_source = []
    for method in canonical_spyglass_methods:
        pattern = _re.compile(rf"\bdef\s+{_re.escape(method)}\b")
        found = False
        for py_file in pkg_root.rglob("*.py"):
            try:
                if pattern.search(py_file.read_text()):
                    found = True
                    break
            except (OSError, UnicodeDecodeError):
                continue
        if not found:
            missing_in_source.append(method)
    if missing_in_source:
        print(f"  [FAIL] SKIP_METHODS entries no longer defined in "
              f"Spyglass source: {missing_in_source} — rename/removal "
              f"upstream would silently un-police these")
        return False
    print("  [ok] SKIP_METHODS: canonical DJ/Spyglass entries still exist")
    return True


def fixture_known_classes_eval_targets_registered(src_root):
    """Eval-target classes added in round-3 must remain resolvable via
    `_index.scan`. If they're not, the method-existence check silently
    skips them and bugs slip through. All four are singletons today;
    pin the resolution path so a future Spyglass refactor that splits
    one into multi-version surfaces here.
    """
    expected = {
        "UserEnvironment": "spyglass/common/common_user.py",
        "IntervalPositionInfo": "spyglass/common/common_position.py",
        "RippleParameters": "spyglass/ripple/v1/ripple.py",
        "RippleLFPSelection": "spyglass/ripple/v1/ripple.py",
    }
    v.clear_caches()
    index = v._index.scan(src_root)
    missing_or_wrong = []
    for cls, want_path in expected.items():
        top_level = [r for r in index.get(cls, ()) if r.qualname == cls]
        got = top_level[0].file if len(top_level) == 1 else None
        if got != want_path:
            missing_or_wrong.append((cls, want_path, got))
    if missing_or_wrong:
        print("  [FAIL] auto-registry drift on round-3 eval targets:")
        for cls, want, got in missing_or_wrong:
            print(f"         {cls}: want {want!r}, got {got!r}")
        return False
    import re as _re
    not_in_source = []
    for cls, rel_path in expected.items():
        py_file = src_root / rel_path
        if not py_file.exists():
            not_in_source.append((cls, str(py_file), "file missing"))
            continue
        pattern = _re.compile(rf"^class\s+{_re.escape(cls)}\b", _re.MULTILINE)
        if not pattern.search(py_file.read_text()):
            not_in_source.append((cls, str(py_file), "class decl missing"))
    if not_in_source:
        print("  [FAIL] resolved path no longer matches source:")
        for cls, path, reason in not_in_source:
            print(f"         {cls} @ {path}: {reason}")
        return False
    print("  [ok] auto-registry: round-3 eval-target classes still resolve")
    return True


def fixture_link_landing_negative(src_root):
    """Link whose text content words don't appear in the target must warn.

    The heuristic is: if NONE of the link text's content words (stopwords
    stripped, ≥4 chars) appear anywhere in the target .md, emit a warning
    that the link may not cover what the text promises.
    """
    tmp = Path(tempfile.mkdtemp())
    source_md = _write_named_md(
        tmp, "source.md",
        """
        # Source

        See [cardinality discovery step](target.md) for details.
        """,
    )
    target_md = _write_named_md(
        tmp, "target.md",
        """
        # Target

        This file talks about shoes and boats. Completely unrelated words.
        """,
    )
    with _with_md_file_list([source_md, target_md]):
        # check_link_landing resolves relative paths against md_file.parent,
        # so both files living in the same tmp dir resolves correctly.
        results = v.ValidationResult()
        v.check_link_landing(results)
    return _assert_warn_contains(
        results, "none of [cardinality, discovery, step]",
        "link-landing: mismatched text/target caught",
    )


def fixture_link_landing_positive(src_root):
    """Link whose text words DO appear in the target must NOT warn."""
    tmp = Path(tempfile.mkdtemp())
    source_md = _write_named_md(
        tmp, "source.md",
        """
        # Source

        See [cardinality discovery step](target.md) for details.
        """,
    )
    target_md = _write_named_md(
        tmp, "target.md",
        """
        # Target

        The cardinality discovery step is described here.
        """,
    )
    with _with_md_file_list([source_md, target_md]):
        results = v.ValidationResult()
        v.check_link_landing(results)
    hits = [w for w in results.warnings if "link" in w]
    if not hits:
        print("  [ok] link-landing: matching text/target not flagged")
        return True
    print(f"  [FAIL] matching text wrongly warned: {hits}")
    return False


def fixture_citation_content_direct_match(src_root):
    """Citation where cited line range contains the identifier must pass.

    Rule (a) of _citation_matches_identifier: direct ±8 substring match.
    Finds the actual line in dj_mixin.py where `class SpyglassMixin`
    lives, so this survives upstream refactors that shift line numbers
    — the test's intent is the rule, not the specific number.
    """
    target = src_root / "spyglass/utils/dj_mixin.py"
    if not target.exists():
        print("  [skip] cite-content: dj_mixin.py not in src tree")
        return True
    decl_line = None
    for i, line in enumerate(target.read_text().splitlines(), 1):
        if line.startswith("class SpyglassMixin"):
            decl_line = i
            break
    if decl_line is None:
        print("  [skip] cite-content: SpyglassMixin class not found")
        return True
    md = _write_md(
        f"""
        # Test

        `SpyglassMixin` is the common base — see
        `src/spyglass/utils/dj_mixin.py:{decl_line}`.
        """
    )
    r = _run(v.check_citation_content, md, src_root)
    bad = [w for w in r.warnings if "dj_mixin.py" in w]
    if not bad:
        print("  [ok] cite-content: direct match at cited line passes")
        return True
    print(f"  [FAIL] direct match wrongly warned: {bad}")
    return False


def fixture_citation_content_enclosing_def(src_root):
    """Citation pointing INSIDE a function body must pass when the
    enclosing def's name matches (rule b: enclosing-scope walk).

    Regression guard for the indent-cap walk that climbs through nested
    scopes — breaking that loop silently turns this fixture into a warn.
    """
    # Find a real enclosing scope we can cite. cautious_delete is known
    # to be in cautious_delete.py; pick a line inside its body and cite it.
    target = src_root / "spyglass/utils/mixins/cautious_delete.py"
    if not target.exists():
        print("  [skip] cite-content: cautious_delete.py not in src tree")
        return True
    source = target.read_text().splitlines()
    def_line = None
    for i, line in enumerate(source, 1):
        if line.lstrip().startswith("def cautious_delete"):
            def_line = i
            break
    if def_line is None:
        print("  [skip] cite-content: cautious_delete not found in file")
        return True
    body_line = def_line + 5  # a line a few steps inside the def body
    md = _write_md(
        f"""
        # Test

        The `cautious_delete` method is at
        `src/spyglass/utils/mixins/cautious_delete.py:{body_line}`.
        """
    )
    r = _run(v.check_citation_content, md, src_root)
    bad = [w for w in r.warnings if "cautious_delete" in w
           and "does not contain" in w]
    if not bad:
        print("  [ok] cite-content: enclosing-def walk accepts body citation")
        return True
    print(f"  [FAIL] enclosing-def rule wrongly warned: {bad}")
    return False


def fixture_citation_content_stale(src_root):
    """Citation where neither direct match nor enclosing def matches must warn."""
    # Cite line 1 of a real file under a completely unrelated identifier.
    # Line 1 is usually a docstring / import; no identifier match expected.
    md = _write_md(
        """
        # Test

        `NonexistentSymbolThatWontBeFound` is at
        `src/spyglass/common/common_nwbfile.py:1`.
        """
    )
    r = _run(v.check_citation_content, md, src_root)
    return _assert_warn_contains(
        r, "NonexistentSymbolThatWontBeFound",
        "cite-content: stale citation (no match anywhere) caught",
    )


def fixture_pr_citation_in_prose_warns(src_root):
    """`PR #1234` in prose must warn."""
    md = _write_md(
        """
        # Test

        This behavior was fixed in PR #1234 when we did the thing.
        """
    )
    r = _run(v.check_no_pr_citations, md)
    return _assert_warn_contains(
        r, "PR #1234",
        "pr-citation: prose mention caught",
    )


def fixture_pr_citation_in_code_block_ok(src_root):
    """`PR #1234` inside a fenced code block must NOT warn.

    Regression guard for _strip_fenced_blocks: the helper replaces fenced
    bodies with blank lines before regex-scanning prose, so comments inside
    python blocks can legitimately mention PR numbers without tripping the
    prose-only check.
    """
    md = _write_md(
        """
        # Test

        ```python
        # See PR #1234 for the rationale behind this flag
        x = True
        ```
        """
    )
    r = _run(v.check_no_pr_citations, md)
    hits = [w for w in r.warnings if "PR #1234" in w]
    if not hits:
        print("  [ok] pr-citation: mentions inside code blocks not flagged")
        return True
    print(f"  [FAIL] code-block PR mention wrongly warned: {hits}")
    return False


def _run_eval_hygiene_on(evals_obj, src_root):
    """Shared scaffolding: write a synthetic evals.json, run the two
    new eval-assertion rules against it, return the ValidationResult.
    """
    import json
    import tempfile
    from pathlib import Path as P
    tmp = P(tempfile.mkdtemp())
    (tmp / "evals").mkdir()
    (tmp / "evals" / "evals.json").write_text(json.dumps(evals_obj))
    original = v.SKILL_DIR
    v.SKILL_DIR = tmp
    try:
        results = v.ValidationResult()
        registry = v._ClassRegistry(src_root, results)
        v.check_eval_required_substring_hygiene(
            src_root, results, registry=registry,
        )
        v.check_eval_required_substring_completeness(
            src_root, results, registry=registry,
        )
        return results
    finally:
        v.SKILL_DIR = original


def fixture_eval_bare_word_required_substring(src_root):
    """Bare single English word in required_substrings must warn.

    `"legacy"` is exactly the kind of bare word the evals/README
    substring-hygiene rule warns about: it matches 'v0 is legacy' and
    'v0 is NOT legacy' equally well. The hygiene check should flag it.
    """
    r = _run_eval_hygiene_on({"evals": [{
        "id": 901, "expected_output": "v0 is legacy.",
        "assertions": {
            "required_substrings": ["legacy"],
            "forbidden_substrings": [], "behavioral_checks": [],
        },
    }]}, src_root)
    hits = [w for w in r.warnings if "id=901" in w and "bare word" in w]
    if hits:
        print("  [ok] eval-hygiene: bare single-word required_substring caught")
        return True
    print(f"  [FAIL] expected bare-word warning; got warnings: {r.warnings}")
    return False


def fixture_eval_known_class_not_flagged_as_bare(src_root):
    """Known Spyglass class names look like bare words (single capital +
    lowercase) but ARE discriminating identifiers. The hygiene rule
    exempts them via the registry so `Electrode`, `Session`, `LFPV1`
    don't false-warn.
    """
    r = _run_eval_hygiene_on({"evals": [{
        "id": 902,
        "expected_output": "Use Electrode as the upstream table.",
        "assertions": {
            "required_substrings": ["Electrode"],  # known class, not bare
            "forbidden_substrings": [], "behavioral_checks": [],
        },
    }]}, src_root)
    bad = [w for w in r.warnings if "id=902" in w and "bare word" in w]
    if not bad:
        print("  [ok] eval-hygiene: known Spyglass class not flagged as bare")
        return True
    print(f"  [FAIL] known class wrongly flagged: {bad}")
    return False


def fixture_eval_trailing_paren_required_substring(src_root):
    """Required substring ending with `(` locks the match to one call
    form (`SpikeSorting.populate(` won't match `.populate()`). Warn.
    """
    r = _run_eval_hygiene_on({"evals": [{
        "id": 903, "expected_output": "Call SpikeSorting.populate()",
        "assertions": {
            "required_substrings": ["SpikeSorting.populate("],
            "forbidden_substrings": [], "behavioral_checks": [],
        },
    }]}, src_root)
    hits = [w for w in r.warnings if "id=903" in w and "ends with '('" in w]
    if hits:
        print("  [ok] eval-hygiene: trailing-paren required_substring caught")
        return True
    print(f"  [FAIL] expected trailing-paren warning; got: {r.warnings}")
    return False


def fixture_eval_backtick_wrapped_required_substring(src_root):
    """Required substring wrapped in literal backticks locks the match
    to one code-style rendering (`` `Raw` `` won't match plain `Raw`).
    Warn.
    """
    r = _run_eval_hygiene_on({"evals": [{
        "id": 904, "expected_output": "Upstream includes `Raw`.",
        "assertions": {
            "required_substrings": ["`Raw`"],
            "forbidden_substrings": [], "behavioral_checks": [],
        },
    }]}, src_root)
    hits = [w for w in r.warnings if "id=904" in w and "backticks" in w]
    if hits:
        print("  [ok] eval-hygiene: backtick-wrapped required_substring caught")
        return True
    print(f"  [FAIL] expected backtick warning; got: {r.warnings}")
    return False


def fixture_eval_required_substrings_exempt_silences_warning(src_root):
    """`required_substrings_exempt` list silences the hygiene warning
    for specific substrings the author has reviewed and accepted as
    discriminating despite looking bare.
    """
    r = _run_eval_hygiene_on({"evals": [{
        "id": 905, "expected_output": "The Nyquist rate...",
        "assertions": {
            "required_substrings": ["Nyquist"],
            "required_substrings_exempt": ["Nyquist"],
            "forbidden_substrings": [], "behavioral_checks": [],
        },
    }]}, src_root)
    bad = [w for w in r.warnings if "id=905" in w and "bare word" in w]
    if not bad:
        print("  [ok] eval-hygiene: required_substrings_exempt silences bare-word warning")
        return True
    print(f"  [FAIL] exempt list ignored: {bad}")
    return False


def fixture_eval_completeness_missing_table(src_root):
    """expected_output names a Spyglass class that no required_substring
    requires → completeness check warns (eval 72 pattern pre-fix).
    """
    r = _run_eval_hygiene_on({"evals": [{
        "id": 906,
        "expected_output": (
            "Upstream chain: LFPSelection → LFPV1 → LFPOutput → LFPBandSelection."
        ),
        "assertions": {
            "required_substrings": ["LFPSelection"],  # misses LFPV1, LFPOutput, LFPBandSelection
            "forbidden_substrings": [], "behavioral_checks": [],
        },
    }]}, src_root)
    hits = [w for w in r.warnings if "id=906" in w and "expected_output names" in w]
    # Expect warnings for LFPV1, LFPOutput, LFPBandSelection
    missing = {cls for cls in ("LFPV1", "LFPOutput", "LFPBandSelection")
               if not any(cls in h for h in hits)}
    if not missing:
        print("  [ok] eval-completeness: missing tables in required_substrings caught")
        return True
    print(f"  [FAIL] expected warnings naming each missing table; missing: {missing}")
    return False


def fixture_eval_completeness_exempt_silences_warning(src_root):
    """`expected_output_tables_exempt` silences the completeness warning
    for tables mentioned as context/distractor.
    """
    r = _run_eval_hygiene_on({"evals": [{
        "id": 907,
        "expected_output": "Like LFPV1, LFPBandV1 is Computed.",
        "assertions": {
            "required_substrings": ["LFPBandV1"],
            "expected_output_tables_exempt": ["LFPV1"],
            "forbidden_substrings": [], "behavioral_checks": [],
        },
    }]}, src_root)
    bad = [w for w in r.warnings if "id=907" in w and "LFPV1" in w and "expected_output names" in w]
    if not bad:
        print("  [ok] eval-completeness: expected_output_tables_exempt silences warning")
        return True
    print(f"  [FAIL] exempt list ignored: {bad}")
    return False


def fixture_schema_resolution_fails_loud_on_ambiguity(src_root):
    """`resolve_schema` returns None for ambiguous multi-version references
    when no version is given; returns the matching record when version IS
    given.

    Pins the FAIL-LOUD contract: validator does NOT guess maintainer
    intent. The caller surfaces ambiguity as a warning telling the
    maintainer to rewrite prose to use a version-specific class name
    (e.g. SpikeSortingV1) or rename the file with a `_v(N)_` segment.
    Explicit prose fixes ambiguity at the source rather than at
    validate-time guessing.
    """
    import tempfile
    import textwrap
    from pathlib import Path as P

    if "_index" not in dir(v):
        print("  [FAIL] validate_skill does not expose `_index`")
        return False

    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = P(tmp_str)
        for name, body in {
            "fakepipe/v0/main.py": '''
                class FakeMultiVerSel:
                    definition = """
                    sel_id: int
                    ---
                    """
            ''',
            "fakepipe/v1/main.py": '''
                class FakeMultiVerSel:
                    definition = """
                    sel_id: int
                    ---
                    """
            ''',
        }.items():
            path = tmp / "spyglass" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(textwrap.dedent(body))

        v.clear_caches()
        try:
            idx = v._index.scan(tmp)
            records = idx.schema_records("FakeMultiVerSel")
            if len(records) != 2:
                print(f"  [FAIL] expected 2 records, got: {records!r}")
                return False
            # No version → ambiguous → None.
            if idx.resolve_record("FakeMultiVerSel") is not None:
                print("  [FAIL] no-version multi-record should return None")
                return False
            if idx.resolve_record("FakeMultiVerSel", version=None) is not None:
                print("  [FAIL] explicit None version should still return None")
                return False
            # version="v1" → the v1 record.
            chosen_v1 = idx.resolve_record("FakeMultiVerSel", version="v1")
            if chosen_v1 is None or "/v1/" not in chosen_v1.file:
                print(f"  [FAIL] version='v1' should pick the v1 record: {chosen_v1!r}")
                return False
            # version="v0" → the v0 record.
            chosen_v0 = idx.resolve_record("FakeMultiVerSel", version="v0")
            if chosen_v0 is None or "/v0/" not in chosen_v0.file:
                print(f"  [FAIL] version='v0' should pick the v0 record: {chosen_v0!r}")
                return False
        finally:
            v.clear_caches()
    print("  [ok] resolve_record: ambiguous→None; versioned→matching record")
    return True


def fixture_check_restriction_emits_ambiguity_warning(src_root):
    """End-to-end: cross-cutting markdown (no version marker) restricting
    a multi-version class triggers an ambiguity warning that names the
    class and points at the marker as the fix.

    Pins the integration path between ``resolve_schema``'s fail-loud
    return value and the user-facing warning emitted by
    ``check_restriction_fields`` / ``check_insert_key_shape``. A regression
    that accidentally silences this warning (e.g. dropping the
    ``len(records) > 1`` guard or skipping the ambiguity branch) would
    pass ``fixture_schema_resolution_fails_loud_on_ambiguity`` (unit
    contract) but fail this fixture (warning dispatch).
    """
    import tempfile
    import textwrap as tw
    from pathlib import Path as P

    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = P(tmp_str)
        for name, body in {
            "fakepipe/v0/main.py": '''
                class AmbigSel:
                    definition = """
                    sel_id: int
                    ---
                    other_v0_only: varchar(8)
                    """
            ''',
            "fakepipe/v1/main.py": '''
                class AmbigSel:
                    definition = """
                    sel_id: int
                    ---
                    other_v1_only: varchar(8)
                    """
            ''',
        }.items():
            path = tmp / "spyglass" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(tw.dedent(body))

        v.clear_caches()

        # Synthetic md file WITHOUT a marker — should warn ambiguous.
        md = _write_md(
            """
            # Test (cross-cutting, no marker)

            ```python
            (AmbigSel & {"sel_id": 1})
            AmbigSel.insert1({"sel_id": 2})
            ```
            """
        )
        try:
            results = v.ValidationResult()
            with _with_md_files(md):
                v.check_restriction_fields(tmp, results)
                v.check_insert_key_shape(tmp, results)
        finally:
            v.clear_caches()

        warnings = [w for w in results.warnings if "AmbigSel" in w]
        if not any("ambiguous multi-version reference" in w for w in warnings):
            print(f"  [FAIL] no ambiguity warning emitted: {warnings!r}")
            return False
        if not any("pipeline-version" in w for w in warnings):
            print(f"  [FAIL] warning doesn't mention marker fix: {warnings!r}")
            return False

    # Same synth dir + a marked md file → no ambiguity warning.
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = P(tmp_str)
        for name, body in {
            "fakepipe/v0/main.py": '''
                class AmbigSel:
                    definition = """
                    sel_id: int
                    ---
                    """
            ''',
            "fakepipe/v1/main.py": '''
                class AmbigSel:
                    definition = """
                    sel_id: int
                    ---
                    """
            ''',
        }.items():
            path = tmp / "spyglass" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(tw.dedent(body))

        v.clear_caches()

        md = _write_md(
            """
            <!-- pipeline-version: v1 -->
            # Test (marked)

            ```python
            (AmbigSel & {"sel_id": 1})
            ```
            """
        )
        try:
            results = v.ValidationResult()
            with _with_md_files(md):
                v.check_restriction_fields(tmp, results)
        finally:
            v.clear_caches()

        bad = [w for w in results.warnings if "ambiguous" in w.lower()]
        if bad:
            print(f"  [FAIL] marker present but ambiguity still warned: {bad!r}")
            return False

    print("  [ok] ambiguity warning fires on unmarked + suppressed by marker")
    return True


def fixture_resolve_table_fields_propagates_ambiguity_to_parents(src_root):
    """Single-version child + multi-version transitive parent + no
    version context → ``resolve_table_fields`` returns None (not a
    partial field set). Otherwise ``check_restriction_fields`` would
    emit false positives for inherited fields silently dropped from
    the partial walk.

    Pins the parent-chain ambiguity contract added in the post-review
    fix-up. A regression that reverts to "skip None parents and union
    siblings" would warn on legitimate inherited keys when the
    child happens to be single-version but its parent is multi-version
    in unmarked prose.
    """
    import tempfile
    import textwrap
    from pathlib import Path as P

    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = P(tmp_str)
        files = {
            "fakepipe/v1/child.py": '''
                class ChildOnlyV1:
                    definition = """
                    -> ParentMultiVer
                    child_id: int
                    ---
                    """
            ''',
            "fakepipe/v0/parent.py": '''
                class ParentMultiVer:
                    definition = """
                    parent_id_v0: int
                    ---
                    """
            ''',
            "fakepipe/v1/parent.py": '''
                class ParentMultiVer:
                    definition = """
                    parent_id_v1: int
                    ---
                    """
            ''',
        }
        for rel, body in files.items():
            path = tmp / "spyglass" / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(textwrap.dedent(body))

        v.clear_caches()
        try:
            idx = v._index.scan(tmp)
            # No version → parent ambiguous → None (not partial).
            if idx.fields_for("ChildOnlyV1") is not None:
                print("  [FAIL] expected None on ambiguous parent")
                return False
            # version="v1" → parent disambiguates → full set returned.
            fields = idx.fields_for("ChildOnlyV1", version="v1")
            if fields != {"child_id", "parent_id_v1"}:
                print(f"  [FAIL] versioned walk wrong: {fields!r}")
                return False
            culprit, reason = idx.find_ambiguous_in_chain(
                "ChildOnlyV1", version=None,
            )
            if culprit != "ParentMultiVer" or reason != "ambiguous":
                print(
                    "  [FAIL] expected (ParentMultiVer, 'ambiguous'), "
                    f"got: {(culprit, reason)!r}"
                )
                return False
        finally:
            v.clear_caches()

    print("  [ok] fields_for propagates ambiguity to indirect parents")
    return True


def fixture_index_scan_parses_projection_rename(src_root):
    """`_index.scan` extracts projected FK rename pairs as
    ``FKEdge.renames`` (a tuple of ``(new, old)`` pairs) and accepts a
    field-name lookup via ``ClassIndex.fields_for`` that returns the
    new name (post-projection) but not the old one.
    """
    import tempfile
    import textwrap
    from pathlib import Path as P

    if "_index" not in dir(v):
        print("  [FAIL] validate_skill does not expose `_index`")
        return False

    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = P(tmp_str)
        synth = tmp / "spyglass" / "merge_pipe" / "tables.py"
        synth.parent.mkdir(parents=True, exist_ok=True)
        synth.write_text(textwrap.dedent('''
            class FakeMaster:
                definition = """
                merge_id: uuid
                ---
                source: varchar(32)
                """

            class FakeSelection:
                definition = """
                -> FakeMaster.proj(fake_merge_id='merge_id')
                filter_name: varchar(80)
                ---
                """
        '''))
        v.clear_caches()
        try:
            idx = v._index.scan(tmp)
            sel = idx.resolve_record("FakeSelection")
            if sel is None:
                print(f"  [FAIL] FakeSelection not resolved: {sorted(idx)!r}")
                return False
            # Exactly one FK edge with the rename.
            if len(sel.fk_edges) != 1:
                print(f"  [FAIL] expected 1 FK edge, got: {sel.fk_edges!r}")
                return False
            edge = sel.fk_edges[0]
            if edge.parent != "FakeMaster":
                print(f"  [FAIL] edge.parent wrong: {edge.parent!r}")
                return False
            if edge.renames_dict() != {"fake_merge_id": "merge_id"}:
                print(f"  [FAIL] renames_dict wrong: {edge.renames_dict()!r}")
                return False
            # Insert-fields: new name accepted, old name dropped.
            fields = idx.insert_fields_for("FakeSelection")
            if fields is None or "fake_merge_id" not in fields:
                print(f"  [FAIL] fake_merge_id missing from insert_fields: {fields!r}")
                return False
            if "merge_id" in fields:
                print(f"  [FAIL] merge_id (old name) leaked into insert_fields: {fields!r}")
                return False
            if "filter_name" not in fields:
                print(f"  [FAIL] filter_name missing from insert_fields: {fields!r}")
                return False
        finally:
            v.clear_caches()
    print("  [ok] _index.scan: projection rename surfaces via ClassIndex.insert_fields_for")
    return True


def fixture_class_registry_picks_version_by_filename(src_root):
    """`_ClassRegistry.methods(name, location=...)` resolves multi-version
    classes via location-driven policy:

      * **Versioned location** (filename matches ``_v(\\d+)_``) →
        STRICT to that version. A method that exists only on the other
        version is treated as missing.
      * **Unversioned location** → UNION across all version records.
        A method valid on any version is valid in unversioned prose.

    No version is preferred as a default. v0 isn't legacy-deprecated —
    neuroscience analysis pipelines run for years, and a user who started
    on v0 may still be using v0 today even though v1 exists. The skill
    serves both audiences; the validator's semantics reflect that.

    Synthetic spyglass tree has FakeMultiVerTable in both v0 and v1 with
    different method sets:

      * v0: set_group_by_electrode_group + make
      * v1: set_group_by_shank + make
    """
    import tempfile
    import textwrap
    from pathlib import Path as P

    if "_index" not in dir(v):
        print("  [FAIL] validate_skill does not expose `_index`")
        return False

    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = P(tmp_str)
        for name, body in {
            "spikesorting/v0/recording.py": '''
                class FakeMultiVerTable:
                    def set_group_by_electrode_group(self): pass
                    def make(self): pass
            ''',
            "spikesorting/v1/recording.py": '''
                class FakeMultiVerTable:
                    def set_group_by_shank(self): pass
                    def make(self): pass
            ''',
        }.items():
            path = tmp / "spyglass" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(textwrap.dedent(body))

        v.clear_caches()
        registry = v._ClassRegistry(tmp, v.ValidationResult())

        # Unversioned location — union across versions. Both v0-only and
        # v1-only methods should be accepted as available.
        m_union = registry.methods("FakeMultiVerTable", location="common_mistakes.md:42")
        if m_union is None:
            print("  [FAIL] unversioned location: methods returned None")
            return False
        if "set_group_by_electrode_group" not in m_union:
            print(
                f"  [FAIL] unversioned location should union v0 methods: "
                f"missing set_group_by_electrode_group: {set(m_union)!r}"
            )
            return False
        if "set_group_by_shank" not in m_union:
            print(
                f"  [FAIL] unversioned location should union v1 methods: "
                f"missing set_group_by_shank: {set(m_union)!r}"
            )
            return False

        # v0-marked location — strict to v0. v1-only methods absent.
        registry._cache.clear()
        m_v0 = registry.methods(
            "FakeMultiVerTable", location="spikesorting_v0_legacy.md:42"
        )
        if m_v0 is None:
            print("  [FAIL] v0 location: methods returned None")
            return False
        if "set_group_by_electrode_group" not in m_v0:
            print(
                f"  [FAIL] v0 context should include v0 methods: "
                f"{set(m_v0)!r}"
            )
            return False
        if "set_group_by_shank" in m_v0:
            print(
                f"  [FAIL] v0 context must NOT include v1-only methods "
                f"(set_group_by_shank): {set(m_v0)!r}"
            )
            return False

        # No location — same as unversioned (union).
        registry._cache.clear()
        m_none = registry.methods("FakeMultiVerTable")
        if "set_group_by_electrode_group" not in m_none:
            print(
                f"  [FAIL] no location should default to union: "
                f"missing set_group_by_electrode_group: {set(m_none)!r}"
            )
            return False
        if "set_group_by_shank" not in m_none:
            print(
                f"  [FAIL] no location should default to union: "
                f"missing set_group_by_shank: {set(m_none)!r}"
            )
            return False

        v.clear_caches()
    print("  [ok] _ClassRegistry: versioned location strict; unversioned union")
    return True


def fixture_class_registry_uses_code_graph_index(src_root):
    """Validator's `_ClassRegistry` consumes `_index.scan`. Pins the
    integration so that a synth Spyglass tree resolves classes by name
    and surfaces their body-level methods.
    """
    import tempfile
    import textwrap
    from pathlib import Path as P

    if "_index" not in dir(v):
        print("  [FAIL] validate_skill does not expose `_index` — integration missing")
        return False

    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = P(tmp_str)
        synth = tmp / "spyglass" / "synth_pipe" / "tables.py"
        synth.parent.mkdir(parents=True, exist_ok=True)
        synth.write_text(textwrap.dedent('''
            class FreshlyMintedTable:
                definition = """
                fresh_id: int
                ---
                """
                def helper(self, x): pass
                def make(self, key): pass
        '''))
        v.clear_caches()
        results = v.ValidationResult()
        registry = v._ClassRegistry(tmp, results)
        methods = registry.methods("FreshlyMintedTable")
        if methods is None:
            print(f"  [FAIL] _ClassRegistry could not resolve FreshlyMintedTable: {methods!r}")
            return False
        if "helper" not in methods or "make" not in methods:
            print(f"  [FAIL] resolved methods missing helper/make: {set(methods)!r}")
            return False
        v.clear_caches()
    print("  [ok] _ClassRegistry resolves classes via _index.scan")
    return True


def fixture_marker_hygiene_warnings(src_root):
    """Pin the two marker-hygiene warnings in `_version_from_markdown_file`:

    1. Filename-vs-marker disagreement (filename declares vN, body marker
       declares vM).
    2. Multiple distinct markers in one body (only the first takes effect;
       silently ignoring the others would surprise the maintainer).

    These warnings exist to keep the marker mechanism honest. A regression
    that drops `results.warn(...)` on either branch would silently pass
    everything green.
    """
    import tempfile
    from pathlib import Path as P

    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = P(tmp_str)
        # Case 1: filename says v0, body marker says v1.
        conflict = tmp / "fakepipe_v0_legacy.md"
        conflict.write_text(
            "<!-- pipeline-version: v1 -->\n# Test\n\nbody\n",
        )
        results = v.ValidationResult()
        ver = v._version_from_markdown_file(conflict, results=results)
        if ver != "v0":
            print(f"  [FAIL] filename should win, got: {ver!r}")
            return False
        if not any(
            "filename declares v0 but body marker declares v1" in w
            for w in results.warnings
        ):
            print(
                "  [FAIL] expected filename↔marker conflict warning, "
                f"got: {results.warnings!r}"
            )
            return False

        # Case 2: two distinct markers in one body (no versioned filename
        # so the marker code path runs in full).
        multi = tmp / "fakepipe_two_markers.md"
        multi.write_text(
            "<!-- pipeline-version: v0 -->\n# Test\n\n"
            "<!-- pipeline-version: v1 -->\nbody\n",
        )
        results = v.ValidationResult()
        ver = v._version_from_markdown_file(multi, results=results)
        if ver != "v0":  # first marker wins
            print(f"  [FAIL] first marker should win, got: {ver!r}")
            return False
        if not any(
            "multiple distinct" in w and "v0" in w and "v1" in w
            for w in results.warnings
        ):
            print(
                "  [FAIL] expected multi-marker warning naming v0+v1, "
                f"got: {results.warnings!r}"
            )
            return False

        # Case 3: no warnings when filename and marker agree.
        agree = tmp / "fakepipe_v1_canonical.md"
        agree.write_text(
            "<!-- pipeline-version: v1 -->\n# Test\n\nbody\n",
        )
        results = v.ValidationResult()
        v._version_from_markdown_file(agree, results=results)
        if results.warnings:
            print(f"  [FAIL] agreement should not warn: {results.warnings!r}")
            return False

    print("  [ok] _version_from_markdown_file: filename↔marker + multi-marker warnings")
    return True


def fixture_resolve_insert_fields_propagates_version(src_root):
    """`ClassIndex.insert_fields_for` propagates ``version`` through the
    FK walk so a single-version child whose multi-version transitive
    parent is unresolved returns None (not a partial union). Mirrors
    `fixture_resolve_table_fields_propagates_ambiguity_to_parents` for
    the insert-side resolver.

    The two methods are 30 lines of nearly-parallel code; a copy-paste
    regression that drops the `version` propagation arg in only one
    would slip through if only the table-fields side were tested.
    """
    import tempfile
    import textwrap
    from pathlib import Path as P

    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = P(tmp_str)
        files = {
            "fakepipe/v1/child.py": '''
                class ChildOnlyV1:
                    definition = """
                    -> ParentMultiVer
                    child_id: int
                    ---
                    """
            ''',
            "fakepipe/v0/parent.py": '''
                class ParentMultiVer:
                    definition = """
                    parent_id_v0: int
                    ---
                    """
            ''',
            "fakepipe/v1/parent.py": '''
                class ParentMultiVer:
                    definition = """
                    parent_id_v1: int
                    ---
                    """
            ''',
        }
        for rel, body in files.items():
            path = tmp / "spyglass" / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(textwrap.dedent(body))

        v.clear_caches()
        try:
            idx = v._index.scan(tmp)
            if idx.insert_fields_for("ChildOnlyV1") is not None:
                print("  [FAIL] expected None on ambiguous parent")
                return False
            fields = idx.insert_fields_for("ChildOnlyV1", version="v1")
            if fields != {"child_id", "parent_id_v1"}:
                print(f"  [FAIL] versioned insert walk wrong: {fields!r}")
                return False
        finally:
            v.clear_caches()
    print("  [ok] insert_fields_for propagates version through parent chain")
    return True


def fixture_find_ambiguous_chain_version_mismatch(src_root):
    """`ClassIndex.find_ambiguous_in_chain` distinguishes two reasons for
    ambiguity in unmarked or wrongly-marked prose:

    * ``"ambiguous"``: multiple records, no version → add a marker.
    * ``"version_mismatch"``: file declares vN but the named class
      doesn't have a vN record → fix the marker or the prose.

    Pre-fix, only the ambiguous case fired; a wrongly-marked file
    would silently fail-open.
    """
    import tempfile
    import textwrap
    from pathlib import Path as P

    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = P(tmp_str)
        files = {
            "fakepipe/v0/main.py": '''
                class MultiVer:
                    definition = """
                    x: int
                    ---
                    """
                class OnlyV0:
                    definition = """
                    y: int
                    ---
                    """
            ''',
            "fakepipe/v1/main.py": '''
                class MultiVer:
                    definition = """
                    x: int
                    ---
                    """
            ''',
        }
        for rel, body in files.items():
            path = tmp / "spyglass" / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(textwrap.dedent(body))

        v.clear_caches()
        try:
            idx = v._index.scan(tmp)
            cases = [
                (("MultiVer", None), ("MultiVer", "ambiguous")),
                (("MultiVer", "v2"), ("MultiVer", "version_mismatch")),
                (("OnlyV0", "v1"), ("OnlyV0", "version_mismatch")),
                (("OnlyV0", "v0"), (None, None)),
            ]
            for (cls, ver), expected in cases:
                got = idx.find_ambiguous_in_chain(cls, version=ver)
                if got != expected:
                    print(
                        f"  [FAIL] {cls} @ version={ver}: "
                        f"expected {expected!r}, got {got!r}"
                    )
                    return False
        finally:
            v.clear_caches()
    print("  [ok] find_ambiguous_in_chain: ambiguous + version_mismatch reasons")
    return True


def fixture_placeholder_shadow_filtered(src_root):
    """`ClassIndex.schema_records` filters out placeholder/shadow records
    whose `definition` is a non-DataJoint sentinel string (e.g.
    Spyglass's `common/custom_nwbfile.py` AnalysisNwbfile shadow with
    `definition = "This definition is managed by SpyglassAnalysis"`).

    Pins the content-based filter (sentinel substrings + structural
    DataJoint tokens) — content rather than parser-output, so a
    `parse_definition` regression that produces empty pk/attrs/fks for
    a real class would NOT be silenced by the same filter.
    """
    import tempfile
    import textwrap
    from pathlib import Path as P

    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = P(tmp_str)
        # File 1: real DataJoint class.
        real = tmp / "spyglass" / "common" / "real_table.py"
        real.parent.mkdir(parents=True, exist_ok=True)
        real.write_text(textwrap.dedent('''
            class ShadowTarget:
                definition = """
                target_id: int
                ---
                payload: varchar(80)
                """
        '''))
        # File 2: placeholder shadow with the same name.
        shadow = tmp / "spyglass" / "common" / "shadow_table.py"
        shadow.write_text(textwrap.dedent('''
            class ShadowTarget:
                definition = """This definition is managed by SpyglassAnalysis"""
        '''))

        v.clear_caches()
        try:
            idx = v._index.scan(tmp)
            records = idx.schema_records("ShadowTarget")
            if len(records) != 1:
                print(
                    f"  [FAIL] expected 1 record (placeholder filtered), "
                    f"got: {records!r}"
                )
                return False
            if "real_table.py" not in records[0].file:
                print(
                    "  [FAIL] expected real_table.py to win, got: "
                    f"{records[0].file!r}"
                )
                return False
            # Singleton: resolve_record returns it without version
            # filtering, so the field check would pass cleanly.
            if idx.resolve_record("ShadowTarget") is None:
                print("  [FAIL] resolve_record unexpectedly returned None")
                return False
        finally:
            v.clear_caches()

    print("  [ok] schema_records: placeholder shadow filtered by content")
    return True


def fixture_clear_caches_invalidates_index(src_root):
    """`clear_caches()` drops `_index.scan`'s lru_cache. Pins the
    contract — without the clear, a fresh scan against an updated
    source tree would return the stale prior result.
    """
    import tempfile
    import textwrap
    from pathlib import Path as P

    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = P(tmp_str)
        synth = tmp / "spyglass" / "fakepipe" / "main.py"
        synth.parent.mkdir(parents=True, exist_ok=True)
        synth.write_text(textwrap.dedent('''
            class CacheTest:
                definition = """
                cache_id: int
                ---
                """
        '''))
        v.clear_caches()
        index_a = v._index.scan(tmp)
        if "CacheTest" not in index_a:
            print("  [FAIL] CacheTest not in initial index")
            return False
        # Clear and rewrite the file with a new class name.
        v.clear_caches()
        synth.write_text(textwrap.dedent('''
            class RenamedAfterClear:
                definition = """
                renamed_id: int
                ---
                """
        '''))
        index_b = v._index.scan(tmp)
        if "CacheTest" in index_b:
            print("  [FAIL] stale CacheTest survived clear_caches")
            return False
        if "RenamedAfterClear" not in index_b:
            print("  [FAIL] new class missing after clear_caches + rescan")
            return False
        v.clear_caches()
    print("  [ok] clear_caches: index invalidated; rescan returns updated content")
    return True


FIXTURES = [
    fixture_class_registry_picks_version_by_filename,
    fixture_class_registry_uses_code_graph_index,
    fixture_marker_hygiene_warnings,
    fixture_resolve_insert_fields_propagates_version,
    fixture_find_ambiguous_chain_version_mismatch,
    fixture_placeholder_shadow_filtered,
    fixture_clear_caches_invalidates_index,
    fixture_index_scan_parses_projection_rename,
    fixture_schema_resolution_fails_loud_on_ambiguity,
    fixture_check_restriction_emits_ambiguity_warning,
    fixture_resolve_table_fields_propagates_ambiguity_to_parents,
    fixture_syntax_ellipsis_after_kwargs,
    fixture_trailing_underscore_nwb,
    fixture_skip_duplicates_raw_ingestion,
    fixture_broken_anchor,
    fixture_broken_file_link,
    fixture_stale_prose_path,
    fixture_glob_not_false_positive,
    fixture_unresolved_uppercase_warns,
    fixture_missing_notebook,
    fixture_spyglassmixin_not_first,
    fixture_spyglassmixin_ordering_ok,
    fixture_merge_classmethod_discard,
    fixture_merge_classmethod_correct_form_ok,
    fixture_alias_import_resolves,
    fixture_module_qualified_resolves,
    fixture_alias_kwarg_validation,
    fixture_binop_receiver_not_false_positive,
    fixture_merge_classmethod_multiline,
    fixture_required_claim_alternatives,
    fixture_wrong_field_name_warns,
    fixture_correct_field_name_no_warn,
    fixture_merge_restriction_not_false_positive,
    fixture_eval_hallucinated_method,
    fixture_eval_citation_content_drift_warns,
    fixture_eval_citation_lines_out_of_range,
    fixture_eval_pr_citation_warns,
    fixture_eval_prose_path_missing,
    fixture_bogus_citation_line,
    fixture_valid_citation_passes,
    fixture_multi_line_citation,
    fixture_harness_restores_collect_md_files,
    fixture_dash_range_citation,
    fixture_aliased_merge_classmethod_discard,
    fixture_duplicated_block_across_files,
    fixture_duplicated_within_file_ok,
    fixture_shared_imports_not_dup,
    fixture_insert1_wrong_pk_field,
    fixture_insert1_extraneous_field,
    fixture_insert1_proj_renamed_ok,
    fixture_insert1_spread_kwargs,
    fixture_insert1_unknown_class,
    fixture_insert1_diamond_projection,
    fixture_singular_plural_hint_added,
    fixture_partial_populate_pk_warns,
    fixture_full_populate_pk_no_warn,
    fixture_link_landing_positive,
    fixture_link_landing_negative,
    fixture_citation_content_direct_match,
    fixture_citation_content_enclosing_def,
    fixture_citation_content_stale,
    fixture_pr_citation_in_prose_warns,
    fixture_pr_citation_in_code_block_ok,
    fixture_skip_methods_spyglass_subset_still_exists,
    fixture_known_classes_eval_targets_registered,
    fixture_merge_registry_baseline_passes,
    fixture_merge_registry_source_addition_caught,
    fixture_merge_registry_md_misclassification_caught,
    fixture_merge_registry_inverse_misclassification_caught,
    fixture_merge_registry_marker_missing_caught,
    fixture_eval_bare_word_required_substring,
    fixture_eval_known_class_not_flagged_as_bare,
    fixture_eval_trailing_paren_required_substring,
    fixture_eval_backtick_wrapped_required_substring,
    fixture_eval_required_substrings_exempt_silences_warning,
    fixture_eval_completeness_missing_table,
    fixture_eval_completeness_exempt_silences_warning,
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--spyglass-src", type=Path, required=True,
        help="Path to spyglass src/ directory (same as validator)",
    )
    args = parser.parse_args()

    if not (args.spyglass_src / "spyglass").is_dir():
        print(f"ERROR: {args.spyglass_src} is not a spyglass src/ dir")
        return 1

    print(f"Running {len(FIXTURES)} regression fixtures...")
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
