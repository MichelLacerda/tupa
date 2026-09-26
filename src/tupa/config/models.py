"""Typed configuration contracts, independent of trajectory readers."""

from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)


def _path(value: object) -> Path:
    if isinstance(value, Path):
        return value
    if not isinstance(value, str) or not value.strip() or "\0" in value:
        raise ValueError("expected a nonempty path string")
    return Path(value)


def _tuple(value: object) -> object:
    # TOML arrays are lists; only this container conversion is intentional.
    return tuple(value) if isinstance(value, list) else value


type FilePath = Annotated[Path, BeforeValidator(_path)]
type Selection = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1)
]
type FiniteNumber = Annotated[float, Field(allow_inf_nan=False)]
type PositiveNumber = Annotated[FiniteNumber, Field(gt=0)]
type NonnegativeNumber = Annotated[FiniteNumber, Field(ge=0)]
type PositiveInteger = Annotated[int, Field(gt=0)]
type NonnegativeInteger = Annotated[int, Field(ge=0)]
type Vector3 = Annotated[
    tuple[FiniteNumber, FiniteNumber, FiniteNumber], BeforeValidator(_tuple)
]
type BoxDimensions = Annotated[
    tuple[
        PositiveNumber,
        PositiveNumber,
        PositiveNumber,
        Annotated[PositiveNumber, Field(lt=180)],
        Annotated[PositiveNumber, Field(lt=180)],
        Annotated[PositiveNumber, Field(lt=180)],
    ],
    BeforeValidator(_tuple),
]


class ConfigModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid", strict=True, frozen=True, validate_default=True
    )


class SystemConfig(ConfigModel):
    topology: FilePath
    trajectory: FilePath


class AnalysisConfig(ConfigModel):
    mode: Literal["ATOM", "BOND", "COORDINATE", "LIST"]


class EnvironmentConfig(ConfigModel):
    selection: Selection
    cutoff: PositiveNumber | None = None


class ProbeConfig(ConfigModel):
    selection: Selection | None = None
    atom1: Selection | None = None
    atom2: Selection | None = None
    position: Vector3 | None = None
    coordinates_file: FilePath | None = None
    remove_self: bool = False
    remove_radius: PositiveNumber | None = None

    @model_validator(mode="after")
    def check_removal(self) -> Self:
        if self.remove_radius is not None and not self.remove_self:
            raise ValueError("probe.remove_radius requires remove_self=true")
        return self

    @property
    def effective_remove_radius(self) -> float:
        """The historical radius is 1 angstrom when removal is enabled."""
        return (self.remove_radius or 1.0) if self.remove_self else 0.0


class SolventConfig(ConfigModel):
    enabled: bool = False
    selection: Selection | None = None
    radius: PositiveNumber | None = None

    @model_validator(mode="after")
    def check_enabled_fields(self) -> Self:
        if self.enabled and (self.selection is None or self.radius is None):
            raise ValueError(
                "solvent.selection and solvent.radius are required "
                "when solvent.enabled=true"
            )
        if not self.enabled and (
            self.selection is not None or self.radius is not None
        ):
            raise ValueError(
                "solvent.selection and solvent.radius require enabled=true"
            )
        return self


class PBCConfig(ConfigModel):
    policy: Literal["legacy", "none", "minimum_image"] = "legacy"
    override_box: bool = False
    dimensions: BoxDimensions | None = None

    @model_validator(mode="after")
    def check_override(self) -> Self:
        if self.override_box != (self.dimensions is not None):
            raise ValueError(
                "pbc.override_box and pbc.dimensions must be provided together"
            )
        if self.policy == "none" and self.override_box:
            raise ValueError(
                "pbc.override_box is incompatible with policy=none"
            )
        if self.dimensions is not None and self.dimensions[3:] != (90, 90, 90):
            raise ValueError("pbc.dimensions only supports orthorhombic boxes")
        return self


class TrajectoryConfig(ConfigModel):
    start: NonnegativeInteger = 0
    stop: PositiveInteger | None = None
    step: PositiveInteger = 1
    time_source: Literal["legacy_dt", "trajectory"] = "legacy_dt"
    dt_ps: PositiveNumber = 1.0

    @model_validator(mode="after")
    def check_interval(self) -> Self:
        if self.stop is not None and self.stop <= self.start:
            raise ValueError("trajectory.stop must be greater than start")
        if (
            self.time_source == "trajectory"
            and "dt_ps" in self.model_fields_set
        ):
            raise ValueError(
                "trajectory.dt_ps cannot override time_source=trajectory"
            )
        return self


class ComputeConfig(ConfigModel):
    backend: Literal["auto", "cpu", "gpu"] = "auto"
    precision: Literal["single", "double"] = "double"
    chunk_size: PositiveInteger | Literal["auto"] = "auto"
    neighbor_skin: NonnegativeNumber | None = None


class OutputConfig(ConfigModel):
    directory: FilePath = Path("results")
    format: Literal["legacy"] = "legacy"
    atomic_contributions: bool = False
    residue_contributions: bool = True
    dump_times_ps: Annotated[
        tuple[NonnegativeNumber, ...], BeforeValidator(_tuple)
    ] = ()


class TupaConfig(ConfigModel):
    schema_version: Annotated[int, Field(ge=2, le=2)] = 2
    system: SystemConfig
    analysis: AnalysisConfig
    environment: EnvironmentConfig
    probe: ProbeConfig
    solvent: SolventConfig = Field(default_factory=SolventConfig)
    pbc: PBCConfig = Field(default_factory=PBCConfig)
    trajectory: TrajectoryConfig = Field(default_factory=TrajectoryConfig)
    compute: ComputeConfig = Field(default_factory=ComputeConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)

    @model_validator(mode="after")
    def check_mode_and_neighbors(self) -> Self:
        required = {
            "ATOM": {"selection"},
            "BOND": {"atom1", "atom2"},
            "COORDINATE": {"position"},
            "LIST": {"coordinates_file"},
        }[self.analysis.mode]
        provided = {
            name
            for name in (
                "selection",
                "atom1",
                "atom2",
                "position",
                "coordinates_file",
            )
            if getattr(self.probe, name) is not None
        }
        missing, unexpected = required - provided, provided - required
        if missing:
            keys = ", ".join(f"probe.{key}" for key in sorted(missing))
            raise ValueError(f"{keys} required for {self.analysis.mode} mode")
        if unexpected:
            keys = ", ".join(f"probe.{key}" for key in sorted(unexpected))
            raise ValueError(f"{keys} not valid for {self.analysis.mode} mode")
        if self.probe.remove_self and self.analysis.mode in {"ATOM", "BOND"}:
            raise ValueError(
                "probe.remove_self is only valid for COORDINATE and LIST"
            )
        if (
            self.compute.neighbor_skin is not None
            and self.environment.cutoff is None
            and not self.solvent.enabled
        ):
            raise ValueError(
                "compute.neighbor_skin requires environment.cutoff "
                "or enabled solvent with a finite radius"
            )
        return self
