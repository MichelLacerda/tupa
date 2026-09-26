"""Validate a TOML configuration and molecular inputs."""

from pathlib import Path
from typing import Annotated

import typer

from tupa.application.run import validate_project
from tupa.config import ConfigurationError

from .app import CLIState, app, fail


@app.command()
def validate(
    ctx: typer.Context,
    config: Annotated[Path, typer.Argument(help="TOML configuration file.")],
) -> None:
    """Check configuration, files, selections, charges, and frame bounds."""
    state: CLIState = ctx.obj
    try:
        settings, report = validate_project(config)
    except ConfigurationError as exc:
        fail(state, exc)
    if settings.compute.backend == "gpu":
        fail(state, ConfigurationError("GPU backend is not available yet"))
    if not state.quiet:
        state.out.print(
            f"Valid {settings.analysis.mode} configuration: "
            f"{report.atom_count} atoms, {report.frame_count} frames, "
            f"{report.selected_frames} selected frames."
        )
    for warning in report.warnings:
        state.err.print(f"Warning: {warning}")
