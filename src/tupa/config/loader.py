"""Read TOML without opening molecular inputs or creating output files."""

import tomllib
from pathlib import Path

from pydantic import ValidationError

from .models import TupaConfig


class ConfigurationError(ValueError):
    """A readable configuration or molecular preflight error."""


def load_config(path: str | Path) -> TupaConfig:
    """Load a config and resolve all paths against the TOML file directory."""
    try:
        source = Path(path).expanduser().resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        raise ConfigurationError(
            f"Invalid config path {path!r}: {exc}"
        ) from exc
    try:
        with source.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise ConfigurationError(f"{source}: {exc}") from exc
    try:
        config = TupaConfig.model_validate(data)
    except ValidationError as exc:
        details = []
        for error in exc.errors(include_url=False):
            key = ".".join(map(str, error["loc"])) or "configuration"
            value = repr(error["input"])
            if len(value) > 120:
                value = value[:117] + "..."
            details.append(f"{key}: {error['msg']} (received {value})")
        raise ConfigurationError(f"{source}:\n" + "\n".join(details)) from exc

    def resolve(key: str, value: Path) -> Path:
        try:
            expanded = value.expanduser()
            return (source.parent / expanded).resolve()
        except (OSError, RuntimeError, ValueError) as exc:
            raise ConfigurationError(
                f"{source}: {key}: cannot resolve {value}: {exc}"
            ) from exc

    system = config.system.model_copy(
        update={
            "topology": resolve("system.topology", config.system.topology),
            "trajectory": resolve(
                "system.trajectory", config.system.trajectory
            ),
        }
    )
    output = config.output.model_copy(
        update={
            "directory": resolve("output.directory", config.output.directory),
        }
    )
    probe = config.probe
    if probe.coordinates_file is not None:
        probe = probe.model_copy(
            update={
                "coordinates_file": resolve(
                    "probe.coordinates_file", probe.coordinates_file
                ),
            }
        )
    return config.model_copy(
        update={
            "system": system,
            "output": output,
            "probe": probe,
        }
    )
