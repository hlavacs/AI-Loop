"""Specification-to-code coverage derived only from existing ``@satisfies`` tags."""

from __future__ import annotations

from icoda_core import requirement_coverage
from icoda_core.model import DerivedModel, Entity, Kind


def test_projection_marks_requirement_without_satisfies_entity_uncovered() -> None:
    model = DerivedModel("/not-returned")
    model.add_entity(Entity("u:other", Kind.FUNCTION, "other", "app::other", "src/app.cpp", 7,
                            satisfies=("R-2",)))

    projection = requirement_coverage.project(
        {"goals": [], "requirements": [{"id": "R-1", "title": "Export the report"}]}, model)

    assert projection == (
        requirement_coverage.RequirementCoverage(
            "requirement", "R-1", "Export the report", (), True),
    )


def test_projection_names_explicitly_tagged_implementing_entity() -> None:
    model = DerivedModel("/not-returned")
    model.add_entity(Entity("u:z", Kind.METHOD, "render", "app::Report::render", "src/z.cpp", 9,
                            satisfies=("R-2", "G-1")))
    model.add_entity(Entity("u:a", Kind.FUNCTION, "load", "app::load", "src/a.cpp", 3,
                            satisfies=("R-2",)))

    projection = requirement_coverage.project(
        {
            "goals": ["Make reports useful"],
            "requirements": [
                {"id": "R-10", "title": "Archive reports"},
                {"id": "R-2", "title": "Render reports"},
            ],
        },
        model,
    )

    assert projection == (
        requirement_coverage.RequirementCoverage(
            "goal", "G-1", "Make reports useful",
            (requirement_coverage.ImplementingEntity("u:z", "app::Report::render"),), False),
        requirement_coverage.RequirementCoverage(
            "requirement", "R-2", "Render reports",
            (
                requirement_coverage.ImplementingEntity("u:a", "app::load"),
                requirement_coverage.ImplementingEntity("u:z", "app::Report::render"),
            ),
            False,
        ),
        requirement_coverage.RequirementCoverage(
            "requirement", "R-10", "Archive reports", (), True),
    )
