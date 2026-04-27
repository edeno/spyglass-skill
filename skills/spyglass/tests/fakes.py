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

    Batch E adds the relational operator surface: ``proj`` (subset of
    fields, deduplicated), ``__mul__`` (natural join), ``__sub__``
    (antijoin), and ``aggr`` (group-by + count(distinct)). All four
    operate along shared-attribute names — the same semantics
    DataJoint enforces on the live server — so fakes-driven set-op
    fixtures pin the same algebra the production code-paths exercise.
    """

    def __init__(
        self,
        *,
        heading: FakeHeading,
        rows: list[dict] | tuple[dict, ...] = (),
        parents: tuple[str, ...] = (),
        children: tuple[str, ...] = (),
        parts: tuple[str, ...] = (),
    ) -> None:
        self.heading = heading
        self._rows: list[dict] = list(rows)
        # Batch F describe metadata. Synthetic test classes can supply
        # parent / child / part names so the describe handler's
        # adjacency block round-trips through the fakes sandbox.
        self._parents = tuple(parents)
        self._children = tuple(children)
        self._parts = tuple(parts)

    def parents(self) -> list[str]:
        return list(self._parents)

    def children(self) -> list[str]:
        return list(self._children)

    def parts(self) -> list[str]:
        return list(self._parts)

    def __and__(self, restriction) -> FakeRelation:
        # DataJoint's natural-restriction operator accepts:
        # * dict — AND-of-equalities (the basic --key form).
        # * list-of-dicts — OR-of-AND-of-equalities (merge-aware path
        #   emits this when restricting the master by multiple resolved
        #   part keys).
        # * FakeRelation — keep rows whose shared-attribute values
        #   match at least one row in the restricting relation. This
        #   is the ``L & R.proj()`` pattern used by --intersect.
        if isinstance(restriction, FakeRelation):
            shared = sorted(
                set(self.heading.names) & set(restriction.heading.names)
            )
            if not shared:
                from datajoint.errors import DataJointError  # ty: ignore[unresolved-import]

                raise DataJointError(
                    "Cannot apply relational restriction: no shared "
                    "attributes between operands"
                )
            other_keys = {
                tuple(r.get(f) for f in shared) for r in restriction._rows
            }
            filtered = [
                r
                for r in self._rows
                if tuple(r.get(f) for f in shared) in other_keys
            ]
        elif isinstance(restriction, list):
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

    def proj(self, *fields: str) -> FakeRelation:
        """Project onto ``fields`` (or PK if none), deduplicating rows.

        Mirrors ``datajoint.Table.proj``: when no fields are given,
        returns the relation projected to its primary key. With fields,
        returns those fields as the projection (heading attributes
        outside the projection are dropped, and the new primary key is
        the original PK ∩ projection).
        """
        proj_fields = tuple(fields) if fields else self.heading.primary_key
        seen: set[tuple] = set()
        out_rows: list[dict] = []
        for r in self._rows:
            key = tuple(r.get(f) for f in proj_fields)
            if key in seen:
                continue
            seen.add(key)
            out_rows.append({f: r.get(f) for f in proj_fields})
        new_pk = tuple(
            f for f in self.heading.primary_key if f in proj_fields
        )
        new_attrs = {
            f: self.heading.attributes[f].type
            for f in proj_fields
            if f in self.heading.attributes
        }
        new_heading = FakeHeading(
            primary_key=new_pk,
            names=proj_fields,
            attributes=new_attrs,
        )
        return FakeRelation(heading=new_heading, rows=out_rows)

    def __mul__(self, other: FakeRelation) -> FakeRelation:
        """Natural join: rows where every shared attribute matches.

        Raises a ``DataJointError``-shaped exception when no shared
        attributes exist (the canonical "Cannot join query
        expressions" error DataJoint raises in the live server).
        """
        from datajoint.errors import DataJointError  # ty: ignore[unresolved-import]

        shared = sorted(set(self.heading.names) & set(other.heading.names))
        if not shared:
            raise DataJointError(
                "Cannot join query expressions: no shared attributes "
                "between left and right operands"
            )
        out_rows: list[dict] = []
        for r1 in self._rows:
            for r2 in other._rows:
                if all(r1.get(f) == r2.get(f) for f in shared):
                    merged = {**r1, **r2}
                    out_rows.append(merged)
        all_names = tuple(
            sorted(set(self.heading.names) | set(other.heading.names))
        )
        all_pk = tuple(
            sorted(
                set(self.heading.primary_key)
                | set(other.heading.primary_key)
            )
        )
        all_attrs: dict[str, str] = {}
        for h in (self.heading, other.heading):
            for n, a in h.attributes.items():
                all_attrs.setdefault(n, a.type)
        new_heading = FakeHeading(
            primary_key=all_pk, names=all_names, attributes=all_attrs
        )
        return FakeRelation(heading=new_heading, rows=out_rows)

    def __sub__(self, other: FakeRelation) -> FakeRelation:
        """Antijoin: rows in self whose shared-attr tuple is not in other."""
        from datajoint.errors import DataJointError  # ty: ignore[unresolved-import]

        shared = sorted(set(self.heading.names) & set(other.heading.names))
        if not shared:
            raise DataJointError(
                "Cannot antijoin: no shared attributes between left "
                "and right operands"
            )
        other_keys = {
            tuple(r.get(f) for f in shared) for r in other._rows
        }
        out_rows = [
            r
            for r in self._rows
            if tuple(r.get(f) for f in shared) not in other_keys
        ]
        return FakeRelation(heading=self.heading, rows=out_rows)

    def aggr(self, source: FakeRelation, **expressions: str) -> FakeRelation:
        """Group-by + count(distinct ...) aggregation.

        Group keys come from ``self``'s primary_key tuples; for each
        group, the aggregator iterates over rows from ``source`` whose
        primary-key tuple matches and applies the named expression.
        Only ``count(distinct FIELD)`` is supported; anything else
        raises ``NotImplementedError`` (test fakes mirror the bounded
        MVP surface, no more).
        """
        import re
        from collections import defaultdict

        parsed: dict[str, str] = {}
        for name, expr in expressions.items():
            m = re.match(
                r"\s*count\s*\(\s*distinct\s+(\w+)\s*\)\s*$",
                expr,
                re.IGNORECASE,
            )
            if not m:
                raise NotImplementedError(
                    f"FakeRelation.aggr only supports count(distinct ...); "
                    f"got {expr!r}"
                )
            parsed[name] = m.group(1)
        pk = self.heading.primary_key
        groups: dict[tuple, list[dict]] = defaultdict(list)
        for r in source._rows:
            key = tuple(r.get(f) for f in pk)
            groups[key].append(r)
        out_rows: list[dict] = []
        for key_tuple, group_rows in groups.items():
            row: dict[str, object] = dict(zip(pk, key_tuple))
            for agg_name, field in parsed.items():
                # ``set`` deduplicates Nones too, mirroring SQL's COUNT
                # DISTINCT (NULLs are excluded). Skip None explicitly.
                distinct_vals = {
                    r.get(field)
                    for r in group_rows
                    if r.get(field) is not None
                }
                row[agg_name] = len(distinct_vals)
            out_rows.append(row)
        new_attrs = {
            f: self.heading.attributes[f].type
            for f in pk
            if f in self.heading.attributes
        }
        for n in parsed:
            new_attrs[n] = "int"
        new_heading = FakeHeading(
            primary_key=pk,
            names=pk + tuple(parsed.keys()),
            attributes=new_attrs,
        )
        return FakeRelation(heading=new_heading, rows=out_rows)


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


            def U(*fields):
                """Mimic ``datajoint.U(*fields)``: a Universal relation
                whose primary key is ``fields``. Used by the grouped-
                count code path: ``dj.U("subject_id").aggr(Electrode,
                n="count(distinct nwb_file_name)")`` groups by
                ``subject_id`` regardless of Electrode's PK shape."""
                from fakes import FakeHeading, FakeRelation

                heading = FakeHeading(
                    primary_key=tuple(fields),
                    names=tuple(fields),
                    attributes={f: "varchar(64)" for f in fields},
                )
                return FakeRelation(heading=heading, rows=[])
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
