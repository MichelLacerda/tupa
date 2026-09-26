"""Create a project directory with a validated configuration template."""

import tomllib
from contextlib import suppress
from pathlib import Path
from typing import Annotated, Literal

import typer
from jinja2 import Environment, PackageLoader, StrictUndefined

from tupa.config.models import TupaConfig

from .app import CLIState, app, fail


@app.command()
def create(
    ctx: typer.Context,
    project_name: Annotated[
        Path, typer.Argument(help="Directory for the new project.")
    ],
    mode: Literal["ATOM", "BOND", "COORDINATE", "LIST"] = typer.Option(
        "ATOM", "--mode", help="Analysis mode."
    ),
) -> None:
    """Create PROJECT_NAME/config.toml with a starting configuration."""
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
        project_name.mkdir()
        try:
            config_file = project_name / "config.toml"
            with config_file.open("x", encoding="utf-8") as handle:
                handle.write(content)
        except OSError:
            with suppress(OSError):
                config_file.unlink(missing_ok=True)
                project_name.rmdir()
            raise
    except OSError as exc:
        fail(state, exc)
    if not state.quiet:
        state.out.print(f"Created {config_file}")
