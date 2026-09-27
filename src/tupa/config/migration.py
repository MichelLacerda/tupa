"""Read historical INI configurations without importing legacy code."""

import configparser
import json
import math
import tomllib
from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, PackageLoader, StrictUndefined
from pydantic import ValidationError

from .loader import ConfigurationError
from .models import TupaConfig

_SECTIONS = {
    "environment selection": "environment",
    "elecfield selection": "environment",
    "probe selection": "probe",
    "target selection": "probe",
    "solvent": "solvent",
    "time": "time",
    "box info": "box",
}
_KEYS = {
    "environment": {"sele_environment", "sele_elecfield"},
    "probe": {
        "mode",
        "selatom",
        "selbond1",
        "selbond2",
        "probecoordinate",
        "targetcoordinate",
        "file_of_coordinates",
        "remove_self",
        "remove_cutoff",
    },
    "solvent": {"include_solvent", "solvent_cutoff", "solvent_selection"},
    "time": {"dt", "begintime", "endtime"},
    "box": {"redefine_box", "boxdimensions"},
}


@dataclass(frozen=True)
class InputFile:
    source: Path
    destination: Path


@dataclass(frozen=True)
class MigrationResult:
    config: TupaConfig
    toml: str
    warnings: tuple[str, ...]
    inputs: tuple[InputFile, ...]


def _required(values: dict[str, str], key: str) -> str:
    value = values.get(key, "").strip().strip("\"'").strip()
    if not value:
        raise ConfigurationError(f"Missing required legacy option: {key}")
    return value


def _boolean(values: dict[str, str], key: str, default: bool = False) -> bool:
    if key not in values:
        return default
    value = values[key].strip().strip("\"'").lower()
    if value in {"true", "yes", "on", "1"}:
        return True
    if value in {"false", "no", "off", "0"}:
        return False
    raise ConfigurationError(f"{key}: expected a boolean, received {value!r}")


def _number(values: dict[str, str], key: str) -> float:
    try:
        value = float(_required(values, key))
    except ValueError as exc:
        raise ConfigurationError(f"{key}: expected a number") from exc
    if not math.isfinite(value):
        raise ConfigurationError(f"{key}: expected a finite number")
    return value


def _vector(values: dict[str, str], key: str, length: int) -> list[float]:
    raw = _required(values, key)
    if not raw.startswith("[") or not raw.endswith("]"):
        raise ConfigurationError(f"{key}: expected {length} bracketed numbers")
    parts = raw[1:-1].split(",")
    if len(parts) != length:
        raise ConfigurationError(f"{key}: expected {length} numbers")
    try:
        numbers = [float(part.strip()) for part in parts]
    except ValueError as exc:
        raise ConfigurationError(f"{key}: expected numeric values") from exc
    if not all(map(math.isfinite, numbers)):
        raise ConfigurationError(f"{key}: expected finite values")
    return numbers


def _input_path(value: Path, inputs: dict[Path, Path]) -> str:
    source = value.expanduser().resolve()
    destination = Path("inputs") / source.name
    existing = inputs.get(destination)
    if existing is not None and existing != source:
        raise ConfigurationError(
            f"Input filename collision: {existing} and {source} "
            f"would both become {destination}"
        )
    inputs[destination] = source
    return destination.as_posix()


def migrate_config(
    source: Path,
    *,
    topology: Path,
    trajectory: Path,
    coordinates: Path | None = None,
) -> MigrationResult:
    """Convert a historical INI file to validated TOML, without writing files."""
    parser = configparser.ConfigParser(
        interpolation=None, inline_comment_prefixes=("#",), strict=True
    )
    try:
        with source.open(encoding="utf-8") as handle:
            parser.read_file(handle)
    except (OSError, UnicodeError, configparser.Error) as exc:
        raise ConfigurationError(f"{source}: {exc}") from exc
    sections: dict[str, dict[str, str]] = {}
    for name in parser.sections():
        kind = _SECTIONS.get(name.lower())
        if kind is None:
            raise ConfigurationError(f"Unknown legacy section: {name}")
        if kind in sections:
            raise ConfigurationError(f"Conflicting legacy sections for {kind}")
        values = dict(parser.items(name))
        unknown = set(values) - _KEYS[kind]
        if unknown:
            raise ConfigurationError(
                f"Unknown option in [{name}]: {', '.join(sorted(unknown))}"
            )
        sections[kind] = values

    environment = sections.get("environment", {})
    probe = sections.get("probe", {})
    solvent = sections.get("solvent", {})
    time = sections.get("time", {})
    box = sections.get("box", {})
    warnings: list[str] = []
    if "sele_environment" in environment and "sele_elecfield" in environment:
        raise ConfigurationError(
            "Conflicting environment aliases: sele_environment and sele_elecfield"
        )
    selection_key = (
        "sele_environment"
        if "sele_environment" in environment
        else "sele_elecfield"
    )
    mode = _required(probe, "mode").upper()
    if mode not in {"ATOM", "BOND", "COORDINATE", "LIST"}:
        raise ConfigurationError(f"mode: unsupported value {mode!r}")
    if coordinates is not None and mode != "LIST":
        raise ConfigurationError("--coordinates is only valid for LIST mode")
    if "targetcoordinate" in probe and "probecoordinate" in probe:
        raise ConfigurationError(
            "Conflicting coordinate aliases: targetcoordinate and probecoordinate"
        )
    active = {
        "ATOM": {"selatom"},
        "BOND": {"selbond1", "selbond2"},
        "COORDINATE": {"probecoordinate", "targetcoordinate"},
        "LIST": {"file_of_coordinates"},
    }[mode]
    for key in sorted(
        set(probe)
        & {
            "selatom",
            "selbond1",
            "selbond2",
            "probecoordinate",
            "targetcoordinate",
            "file_of_coordinates",
        }
        - active
    ):
        warnings.append(f"Ignored inactive probe option: {key}")
    inputs: dict[Path, Path] = {}
    data: dict = {
        "schema_version": 2,
        "system": {
            "topology": _input_path(topology, inputs),
            "trajectory": _input_path(trajectory, inputs),
        },
        "analysis": {"mode": mode},
        "environment": {"selection": _required(environment, selection_key)},
        "probe": {},
    }
    if mode == "ATOM":
        data["probe"]["selection"] = _required(probe, "selatom")
    elif mode == "BOND":
        data["probe"]["atom1"] = _required(probe, "selbond1")
        data["probe"]["atom2"] = _required(probe, "selbond2")
    elif mode == "COORDINATE":
        key = (
            "probecoordinate"
            if "probecoordinate" in probe
            else "targetcoordinate"
        )
        data["probe"]["position"] = _vector(probe, key, 3)
        if key == "targetcoordinate":
            warnings.append("Mapped targetcoordinate to probe.position")
    else:
        legacy_coordinates = _required(probe, "file_of_coordinates")
        if coordinates is None:
            coordinates = Path(legacy_coordinates)
        elif str(coordinates) != legacy_coordinates:
            warnings.append(
                "Overrode legacy file_of_coordinates with --coordinates"
            )
        data["probe"]["coordinates_file"] = _input_path(coordinates, inputs)
    if mode in {"COORDINATE", "LIST"}:
        remove_self = _boolean(probe, "remove_self")
        data["probe"]["remove_self"] = remove_self
        if remove_self and "remove_cutoff" in probe:
            data["probe"]["remove_radius"] = _number(probe, "remove_cutoff")
        elif "remove_cutoff" in probe:
            warnings.append(
                "Ignored remove_cutoff because remove_self is false"
            )
    elif "remove_self" in probe or "remove_cutoff" in probe:
        warnings.append(f"Ignored self-removal options for {mode} mode")

    if _boolean(solvent, "include_solvent"):
        data["solvent"] = {
            "enabled": True,
            "selection": _required(solvent, "solvent_selection"),
            "radius": _number(solvent, "solvent_cutoff"),
        }
    elif "solvent_selection" in solvent or "solvent_cutoff" in solvent:
        warnings.append(
            "Ignored solvent settings because include_solvent is false"
        )
    if "dt" in time:
        data["trajectory"] = {"dt_ps": _number(time, "dt")}
    for key in ("begintime", "endtime"):
        if key in time:
            warnings.append(
                f"Ignored {key}: the historical parser did not use it"
            )
    if _boolean(box, "redefine_box"):
        data["pbc"] = {
            "override_box": True,
            "dimensions": _vector(box, "boxdimensions", 6),
        }
    elif "boxdimensions" in box:
        warnings.append("Ignored boxdimensions because redefine_box is false")
    try:
        config = TupaConfig.model_validate(data)
    except ValidationError as exc:
        raise ConfigurationError(
            f"Migrated configuration is invalid: {exc}"
        ) from exc
    env = Environment(
        loader=PackageLoader("tupa", "templates"),
        undefined=StrictUndefined,
        autoescape=False,
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["toml_string"] = lambda value: json.dumps(
        value, ensure_ascii=False
    )
    toml = env.get_template("migrated.toml.j2").render(config=config)
    if TupaConfig.model_validate(tomllib.loads(toml)) != config:
        raise ConfigurationError("Migration output did not round-trip")
    return MigrationResult(
        config=config,
        toml=toml,
        warnings=tuple(warnings),
        inputs=tuple(
            InputFile(source=source, destination=destination)
            for destination, source in inputs.items()
        ),
    )
