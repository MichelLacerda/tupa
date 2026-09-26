"""Top-level Typer application and terminal presentation."""

import logging
from dataclasses import dataclass

import typer
from rich.console import Console

app = typer.Typer(no_args_is_help=True, help="TUPÃ molecular analysis tools.")


@dataclass
class CLIState:
    quiet: bool
    out: Console
    err: Console


def fail(state: CLIState, error: Exception, code: int = 2) -> None:
    state.err.print(f"Error: {error}")
    raise typer.Exit(code)


@app.callback()
def main(
    ctx: typer.Context,
    quiet: bool = typer.Option(
        False, "--quiet", help="Suppress status output."
    ),
    no_color: bool = typer.Option(False, "--no-color", help="Disable colors."),
    verbose: int = typer.Option(
        0, "--verbose", "-v", count=True, help="Increase log detail."
    ),
) -> None:
    logging.basicConfig(
        level=logging.WARNING
        if verbose == 0
        else logging.INFO
        if verbose == 1
        else logging.DEBUG,
        format="%(levelname)s: %(message)s",
    )
    ctx.obj = CLIState(
        quiet=quiet,
        out=Console(no_color=no_color, highlight=False, soft_wrap=True),
        err=Console(
            stderr=True, no_color=no_color, highlight=False, soft_wrap=True
        ),
    )


from . import create, info, run, validate  # noqa: E402, F401
