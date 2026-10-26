"""Canonical Diamond Mind Universe taxonomy used by Diamond Core."""

from dataclasses import dataclass


@dataclass(frozen=True)
class UniverseProject:
    """One canonical project or operating function in the Universe."""

    project_id: str
    name: str
    parent_id: str | None
    aliases: tuple[str, ...] = ()


PROJECTS = (
    UniverseProject("UNIVERSE", "Diamond Mind Universe", None),
    UniverseProject("CORE", "Diamond Core", "UNIVERSE"),
    UniverseProject("DMIO", "DMIO", "CORE", ("Diamond Mind Intelligence Officer",)),
    UniverseProject("PS", "Pinky's Space", "UNIVERSE"),
    UniverseProject("HRX", "HatsRx", "UNIVERSE"),
    UniverseProject(
        "DOCC",
        "DOCC",
        "HRX",
        ("DOC", "The DOC", "Director of Creative Care"),
    ),
    UniverseProject(
        "TM",
        "Tennismoon",
        "UNIVERSE",
        ("TennisMoon", "TennisMooner"),
    ),
    UniverseProject("LIFE", "LIFE", "UNIVERSE"),
    UniverseProject("DM-ART", "Diamond Mind Art", "UNIVERSE"),
    UniverseProject("PHOTO", "Photography", "UNIVERSE"),
    UniverseProject("MOSS", "Planet Moss", "UNIVERSE"),
    UniverseProject("PENNY", "Penny Collective", "UNIVERSE"),
    UniverseProject("DEV", "Developing Creations", "UNIVERSE"),
)

PROJECTS_BY_ID = {project.project_id: project for project in PROJECTS}
PROJECTS_BY_NAME = {project.name: project for project in PROJECTS}

# DMIO may route an opportunity to any canonical home except the temporary
# Developing Creations intake bucket.
DMIO_PROJECT_NAMES = tuple(
    project.name for project in PROJECTS if project.project_id != "DEV"
)


def canonical_project_name(name: str) -> str:
    """Resolve a canonical name or historical alias to its current name."""
    normalized = name.strip().casefold()
    for project in PROJECTS:
        if project.name.casefold() == normalized:
            return project.name
        if any(alias.casefold() == normalized for alias in project.aliases):
            return project.name
    raise ValueError(f"Unknown Diamond Mind project: {name}")


def validate_hierarchy() -> None:
    """Raise ValueError when IDs, names, or parent relationships are invalid."""
    if len(PROJECTS_BY_ID) != len(PROJECTS):
        raise ValueError("Diamond Mind project IDs must be unique")
    if len(PROJECTS_BY_NAME) != len(PROJECTS):
        raise ValueError("Diamond Mind project names must be unique")

    for project in PROJECTS:
        if project.parent_id is not None and project.parent_id not in PROJECTS_BY_ID:
            raise ValueError(
                f"Unknown parent {project.parent_id} for {project.project_id}"
            )


validate_hierarchy()
