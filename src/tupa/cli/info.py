"""Inspect molecular input metadata."""

from pathlib import Path
from typing import Annotated

import typer

from tupa.application.run import inspect_system
from tupa.config import ConfigurationError

from .app import CLIState, app, fail


@app.command()
def info(
    ctx: typer.Context,
    topology: Annotated[Path, typer.Argument(help="Topology file.")],
    trajectory: Annotated[Path, typer.Argument(help="Trajectory file.")],
) -> None:
    """Show atom count, frame count, and first-frame box."""
    state: CLIState = ctx.obj
    try:
        atoms, frames, dimensions = inspect_system(topology, trajectory)
    except ConfigurationError as exc:
        fail(state, exc)
    if not state.quiet:
        state.out.print(f"Atoms: {atoms}")
        state.out.print(f"Frames: {frames}")
        box = (
            "none"
            if dimensions is None
            else ", ".join(f"{value:g}" for value in dimensions)
        )
        state.out.print(f"First-frame box: {box}")
