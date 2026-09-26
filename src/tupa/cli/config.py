"""Generate validated project configuration templates."""

import tomllib
from pathlib import Path
from typing import Annotated, Literal

import typer
from jinja2 import Environment, PackageLoader, StrictUndefined

from tupa.config.models import TupaConfig

from .app import CLIState, fail

app = typer.Typer(no_args_is_help=True, help="Configuration tools.")


@app.command()
def template(
    ctx: typer.Context,
    output: Annotated[Path, typer.Argument(help="Destination TOML file.")],
    mode: Literal["ATOM", "BOND", "COORDINATE", "LIST"] = typer.Option(
        "ATOM", "--mode", help="Analysis mode."
    ),
    force: bool = typer.Option(
        False, "--force", help="Replace an existing file."
    ),
) -> None:
    """Write a schema-valid starting configuration."""
    state: CLIState = ctx.obj
    environment = Environment(
        loader=PackageLoader("tupa", "templates"),
        undefined=StrictUndefined,
        autoescape=False,
        keep_trailing_newline=True,
    )
    content = environment.get_template("config.toml.j2").render(mode=mode)
    TupaConfig.model_validate(tomllib.loads(content))
    try:
        with output.open("w" if force else "x", encoding="utf-8") as handle:
            handle.write(content)
    except OSError as exc:
        fail(state, exc)
    if not state.quiet:
        state.out.print(f"Created {output}")
