"""Migrate a historical configuration into a new project directory."""

from contextlib import suppress
from pathlib import Path
from shutil import copy2, rmtree
from typing import Annotated

import typer

from tupa.config import ConfigurationError
from tupa.config.migration import migrate_config

from .app import CLIState, app, fail


@app.command()
def migrate(
    ctx: typer.Context,
    project_name: Annotated[
        Path, typer.Argument(help="Directory for the migrated project.")
    ],
    source: Annotated[Path, typer.Option(help="Historical .conf file.")],
    topology: Annotated[Path, typer.Option(help="Topology file path.")],
    trajectory: Annotated[Path, typer.Option(help="Trajectory file path.")],
    coordinates: Annotated[
        Path | None, typer.Option(help="Override LIST coordinate file path.")
    ] = None,
) -> None:
    """Create PROJECT_NAME/config.toml from a historical .conf file."""
    state: CLIState = ctx.obj
    try:
        result = migrate_config(
            source,
            topology=topology,
            trajectory=trajectory,
            coordinates=coordinates,
        )
    except ConfigurationError as exc:
        fail(state, exc)
    for item in result.inputs:
        if not item.source.is_file():
            fail(
                state,
                ConfigurationError(
                    f"Input file does not exist: {item.source}"
                ),
            )
    try:
        project_name.mkdir()
        try:
            (project_name / "inputs").mkdir()
            for item in result.inputs:
                copy2(item.source, project_name / item.destination)
            config_file = project_name / "config.toml"
            with config_file.open("x", encoding="utf-8") as handle:
                handle.write(result.toml)
        except OSError:
            with suppress(OSError):
                rmtree(project_name)
            raise
    except OSError as exc:
        fail(state, exc)
    if not state.quiet:
        state.out.print(f"Created {config_file}")
    for warning in result.warnings:
        state.err.print(f"Warning: {warning}")
