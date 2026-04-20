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
    print(f"  [FAIL] expected one fail and one pass")
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
    print(f"  [FAIL] expected one fail and one pass")
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


FIXTURES = [
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
    fixture_bogus_citation_line,
    fixture_valid_citation_passes,
    fixture_multi_line_citation,
    fixture_harness_restores_collect_md_files,
    fixture_dash_range_citation,
    fixture_aliased_merge_classmethod_discard,
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
