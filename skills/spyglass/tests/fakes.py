"""Fake DataJoint-like relation objects + sandbox shim for ``test_db_graph.py``.

The DataJoint surface ``db_graph.py`` exercises is small and well-bounded:
restriction (``__and__``), projection (``proj``), join (``__mul__``),
antijoin (``__sub__``), aggregation (``aggr``), bounded fetch
(``fetch("KEY")`` / ``fetch(*fields, as_dict=True)``), ``len(rel)``, and
the ``heading`` introspection (``names``, ``primary_key``,
``foreign_keys``, ``attributes``). Mocking these lets system-Python
fixtures exercise the real find-instance code path — restriction
parsing, field validation, count, fetch, truncation, safe
serialization, error classification — without a live database, without
the multi-second Spyglass cold-import cost, and without VPN
dependencies.

Two sibling artifacts live here:

* :class:`FakeHeading` and :class:`FakeRelation` — the in-process fakes
  used to construct synthetic test classes.
* :func:`build_fake_datajoint_sandbox` — writes a minimal ``datajoint``
  package shim into a temp directory. When the test runner sets
  ``PYTHONPATH`` to that directory, a ``db_graph.py`` subprocess
  imports the fake DataJoint instead of the real one. The fake
  exposes ``UserTable``, ``Manual``, ``Lookup``, ``Imported``,
  ``Computed``, ``Part``, ``schema``, and a ``config`` dict — enough
  for the predicate, the resolver, and the ``db`` envelope populator
  to function. Errors are imported via the same module so
  ``_classify_dj_error`` can exercise its ``OperationalError`` /
  ``LostConnectionError`` / ``AccessError`` branches.

The sandbox approach is deliberate: it lets fixtures execute the real
find-instance subprocess flow end-to-end, with the only difference
being which DataJoint implementation the subprocess imports. That
preserves the "subprocess-driven, mirrors test_code_graph.py" pattern
while still removing the live-DB requirement.
"""

from __future__ import annotations

import textwrap
from pathlib import Path


class FakeHeading:
    """Stand-in for ``datajoint.Heading``.

    Holds just the fields ``db_graph.py`` needs at heading time: the
    primary-key tuple, the full attribute name list, and the foreign-key
    declarations for merge-master resolution. ``attributes`` maps
    attribute name to a small object with a ``type`` string (``"int"``,
    ``"varchar(64)"``, ``"blob"``, ``"longblob"``, ``"json"``) so the
    blob-restriction refusal path can be tested without instantiating
    real DataJoint attribute objects.
    """

    def __init__(
        self,
        *,
        primary_key: tuple[str, ...] = (),
        names: tuple[str, ...] = (),
        attributes: dict[str, str] | None = None,
        foreign_keys: tuple[dict, ...] = (),
    ) -> None:
        self.primary_key = primary_key
        self.names = names
        # ``attributes`` is a name → simple object exposing ``.type``.
        # The real DataJoint Attribute is richer; this is the minimum
        # the blob-validation path inspects.
        attrs = attributes or {}
        self.attributes = {n: _FakeAttribute(t) for n, t in attrs.items()}
        self.foreign_keys = foreign_keys


class _FakeAttribute:
    """Tiny stand-in for ``datajoint.heading.Attribute`` — only ``.type``."""

    def __init__(self, type_str: str) -> None:
        self.type = type_str


class FakeRelation:
    """Stand-in for a DataJoint ``UserTable`` instance / query expression.

    Implements the operator surface ``find-instance`` actually uses:

    * ``rel & restriction_dict`` — returns a new ``FakeRelation`` with
      rows filtered by exact match on every key in ``restriction_dict``.
    * ``len(rel)`` — count of rows currently in the relation.
    * ``rel.fetch(*fields, as_dict=True, limit=N)`` — list of dicts.
      The ``KEY`` sentinel returns ``primary_key``-only dicts; an empty
      ``fields`` list returns all heading fields.
    * ``rel.heading`` — the :class:`FakeHeading` provided at
      construction.

    Methods not yet exercised (``__mul__``, ``__sub__``, ``proj``,
    ``aggr``) stay unimplemented; later batches will extend this class.
    Calling them today raises ``NotImplementedError`` rather than
    silently returning an empty relation.
    """

    def __init__(
        self,
        *,
        heading: FakeHeading,
        rows: list[dict] | tuple[dict, ...] = (),
    ) -> None:
        self.heading = heading
        self._rows: list[dict] = list(rows)

    def __and__(self, restriction) -> FakeRelation:
        # DataJoint accepts both dict (single AND-of-equalities) and
        # list-of-dicts (OR-of-AND-of-equalities). The merge-aware
        # path emits list-of-dicts when restricting the master by
        # multiple resolved part keys.
        if isinstance(restriction, list):
            filtered = [
                r
                for r in self._rows
                if any(
                    all(r.get(k) == v for k, v in single.items())
                    for single in restriction
                )
            ]
        else:
            filtered = [
                r
                for r in self._rows
                if all(r.get(k) == v for k, v in restriction.items())
            ]
        return FakeRelation(heading=self.heading, rows=filtered)

    def __len__(self) -> int:
        return len(self._rows)

    def fetch(self, *fields: str, **kwargs) -> list[dict]:
        # ``as_dict`` and ``limit`` are the only kwargs db_graph passes;
        # ignore everything else (test fakes are permissive about
        # extra DataJoint kwargs we have not modeled).
        limit = kwargs.get("limit")
        rows = self._rows
        if limit is not None:
            rows = rows[:limit]
        # Resolve "KEY" sentinel and empty list to the primary key.
        if not fields or list(fields) == ["KEY"]:
            keys = self.heading.primary_key
        else:
            keys = fields
        return [{k: row.get(k) for k in keys} for row in rows]


# ---------------------------------------------------------------------------
# Sandbox shim builder
# ---------------------------------------------------------------------------


def build_fake_datajoint_sandbox(target: Path) -> Path:
    """Write a minimal ``datajoint`` package into ``target`` and return ``target``.

    The shim is what enables system-Python subprocess fixtures to
    exercise the find-instance code path end-to-end. Setting
    ``PYTHONPATH=<target>`` puts this fake in front of the real
    DataJoint (or substitutes for a missing one), so:

    * ``import datajoint as dj`` succeeds.
    * ``from datajoint.user_tables import UserTable`` succeeds and the
      class is the same one we install on synthetic test classes.
    * ``dj.config`` exposes ``database.host``, ``database.user``, and
      ``database.prefix`` so the ``db`` envelope populator returns a
      non-null payload.
    * ``dj.errors`` exposes ``LostConnectionError`` / ``AccessError`` so
      the error-classification path can be exercised by raising those
      exceptions from a synthetic class's fetch.

    The fake intentionally provides no real DB connection. Synthetic
    test classes implement ``__and__`` / ``__len__`` / ``fetch`` /
    ``heading`` directly via :class:`FakeRelation`.
    """
    pkg = target / "datajoint"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text(
        textwrap.dedent(
            '''
            """Minimal datajoint package shim for db_graph.py tests."""
            from datajoint.user_tables import (
                UserTable,
                Manual,
                Lookup,
                Imported,
                Computed,
                Part,
            )
            from datajoint import errors

            __version__ = "0.fake"

            # Mirrors the surface ``_build_db_envelope`` pulls from. The
            # config values here are deliberately scrub-friendly (no
            # passwords) and match what an LLM would expect to see in a
            # provenance block.
            config = {
                "database.host": "fake-host.example",
                "database.user": "fake-user",
                "database.prefix": "fake_prefix_",
            }


            def schema(*args, **kwargs):
                """No-op schema decorator: classes are pre-built on import."""

                def _decorator(cls):
                    return cls

                if args and callable(args[0]) and not kwargs:
                    return args[0]
                return _decorator
            '''
        )
    )
    (pkg / "user_tables.py").write_text(
        textwrap.dedent(
            '''
            """User-table base classes used for the predicate check."""


            class UserTable:
                """Tagging base — subclassed by synthetic test classes."""


            class Manual(UserTable):
                pass


            class Lookup(UserTable):
                pass


            class Imported(UserTable):
                pass


            class Computed(UserTable):
                pass


            class Part(UserTable):
                pass
            '''
        )
    )
    (pkg / "errors.py").write_text(
        textwrap.dedent(
            '''
            """Error classes db_graph.py classifies via ``_classify_dj_error``."""


            class DataJointError(Exception):
                pass


            class LostConnectionError(DataJointError):
                pass


            class AccessError(DataJointError):
                pass
            '''
        )
    )
    return target


def write_fake_test_module(
    target: Path,
    *,
    module_name: str,
    class_name: str,
    primary_key: tuple[str, ...],
    names: tuple[str, ...],
    attributes: dict[str, str],
    rows: list[dict],
    base: str = "Manual",
    raises_on_fetch: str | None = None,
) -> None:
    """Write a synthetic test module into ``target``.

    The module exposes a single class subclassing the fake
    ``datajoint.<base>``. Its ``__init__`` returns a :class:`FakeRelation`
    pre-populated with ``rows`` and the supplied heading. ``raises_on_fetch``
    can name a ``datajoint.errors`` class — the synthetic relation then
    raises that error on the first ``len`` or ``fetch`` call, which lets
    fixtures exercise the ``_classify_dj_error`` path under the fake
    sandbox.

    Used in tandem with :func:`build_fake_datajoint_sandbox`: callers
    set ``PYTHONPATH=<sandbox>`` so the fake datajoint is on the path,
    then ``--import <module_name> --class <module_name>:<class_name>``
    on the find-instance subprocess to register and resolve.
    """
    # Construct the module source line-by-line so the rendered file has
    # canonical indentation. ``textwrap.dedent`` is fragile with embedded
    # multi-line substitutions (a sub-block at a different indent breaks
    # the common-whitespace prefix), so we just emit the lines directly.
    lines: list[str] = [
        '"""Synthetic test module — provides a UserTable-shaped class."""',
        f"from datajoint import {base}",
        "from fakes import FakeHeading, FakeRelation",
        "",
    ]
    if raises_on_fetch:
        lines.extend(
            [
                "",
                "def _raise_for_fixture():",
                f"    from datajoint.errors import {raises_on_fetch}",
                f'    raise {raises_on_fetch}('
                f'"synthetic {raises_on_fetch} for fixture")',
                "",
            ]
        )
    lines.extend(
        [
            "",
            f"class {class_name}({base}):",
            "    _heading_obj = FakeHeading(",
            f"        primary_key={primary_key!r},",
            f"        names={names!r},",
            f"        attributes={attributes!r},",
            "    )",
            f"    _rows = {rows!r}",
            "",
            "    def __new__(cls):",
            "        rel = FakeRelation("
            "heading=cls._heading_obj, rows=cls._rows)",
        ]
    )
    if raises_on_fetch:
        lines.extend(
            [
                "        rel.fetch = lambda *a, **k: _raise_for_fixture()",
                "        rel.__len__ = lambda: _raise_for_fixture()",
            ]
        )
    lines.extend(
        [
            "        return rel",
            "",
            "    @property",
            "    def heading(self):",
            "        return self._heading_obj",
            "",
        ]
    )
    module_path = target / f"{module_name}.py"
    module_path.write_text("\n".join(lines))
