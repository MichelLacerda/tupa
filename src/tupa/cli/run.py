"""Scientific run command."""

from pathlib import Path
from typing import Annotated

import typer

from tupa.application.run import prepare_run
from tupa.config import ConfigurationError

from .app import CLIState, app, fail


@app.command()
def run(
    ctx: typer.Context,
    config: Annotated[Path, typer.Argument(help="TOML configuration file.")],
) -> None:
    """Preflight a run; the scientific engine is not implemented yet."""
    state: CLIState = ctx.obj
    try:
        prepare_run(config)
    except ConfigurationError as exc:
        fail(state, exc)
    fail(
        state, RuntimeError("Scientific calculations are not available yet"), 3
    )
