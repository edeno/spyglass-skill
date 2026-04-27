"""Shared fake DataJoint-like relation objects for ``test_db_graph.py``.

The DataJoint surface ``db_graph.py`` exercises is small and well-bounded:
restriction (``__and__``), projection (``proj``), join (``__mul__``),
antijoin (``__sub__``), aggregation (``aggr``), bounded fetch
(``fetch("KEY")`` / ``fetch(*fields, as_dict=True)``), ``len(rel)``, and
the ``heading`` introspection (``names``, ``primary_key``,
``foreign_keys``, ``attributes``). Mocking these lets unit tests run
without a live database, without DataJoint installed, and without paying
connection cost.

Batch A scope
-------------

Batch A only needs the **shape** of these objects for the schema-envelope
and exit-code fixtures (which exercise ``info`` and the ``find-instance``
stub, neither of which touch DataJoint). The full FakeRelation /
FakeHeading surface lands in Batch C alongside the real find-instance
implementation.

Keeping the skeleton here now serves two purposes: it pins the import
path (``from fakes import FakeHeading, FakeRelation``) so Batch C does
not have to re-route imports across the test file, and it documents the
fake-object contract in code rather than a comment in the plan.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class FakeHeading:
    """Stand-in for ``datajoint.Heading``.

    Holds just the fields ``db_graph.py`` needs at heading time: the
    primary-key tuple, the full attribute name list, and the foreign-key
    declarations for merge-master resolution. ``attributes`` maps
    attribute name to a stringified DataJoint type (``"int"``,
    ``"varchar(64)"``, ``"blob"``, ``"longblob"``, ``"json"``) so blob-
    restriction refusal can be tested without instantiating real
    DataJoint attribute objects.

    Frozen so a fixture cannot accidentally mutate it across tests.
    """

    primary_key: tuple[str, ...] = ()
    names: tuple[str, ...] = ()
    attributes: dict[str, str] = field(default_factory=dict)
    foreign_keys: tuple[dict, ...] = ()


@dataclass
class FakeRelation:
    """Stand-in for a DataJoint ``UserTable`` or query expression.

    Batch A leaves the operator surface unimplemented — fixtures that
    need ``& {...}``, ``* other``, ``- other``, ``.proj()``, ``.aggr()``,
    ``.fetch(...)``, or ``len(...)`` will be added in Batch C alongside
    the real find-instance code that calls them.

    The ``qualname`` field exists so error-payload fixtures (ambiguous,
    not_found) can verify the fake's identity ends up in the payload's
    ``query.resolved_class`` field.
    """

    qualname: str = "FakeTable"
    heading: FakeHeading = field(default_factory=FakeHeading)
    rows: tuple[dict, ...] = ()
