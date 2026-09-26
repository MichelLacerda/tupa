"""Explicit file and molecular checks, separate from TOML parsing."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from .loader import ConfigurationError
from .models import TupaConfig

if TYPE_CHECKING:
    from MDAnalysis import Universe
    from MDAnalysis.core.groups import AtomGroup


@dataclass(frozen=True)
class MolecularValidation:
    atom_count: int
    frame_count: int
    selected_frames: int
    environment_atoms: int
    warnings: tuple[str, ...]


def validate_input_files(config: TupaConfig) -> None:
    """Check input readability and output shape without creating anything."""
    paths = {
        "system.topology": config.system.topology,
        "system.trajectory": config.system.trajectory,
    }
    if config.probe.coordinates_file is not None:
        paths["probe.coordinates_file"] = config.probe.coordinates_file
    for key, path in paths.items():
        if not path.is_file():
            raise ConfigurationError(
                f"{key}: expected an existing file: {path}"
            )
        try:
            with path.open("rb"):
                pass
        except OSError as exc:
            raise ConfigurationError(
                f"{key}: cannot read {path}: {exc}"
            ) from exc
    output = config.output.directory
    for path in (output, *output.parents):
        if path.exists() and not path.is_dir():
            raise ConfigurationError(
                f"output.directory: path component is not a directory: {path}"
            )


def validate_coordinate_file(path: Path, frame_count: int) -> None:
    """Validate LIST coordinates without retaining the whole file in memory."""
    count = 0
    try:
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                line = line.strip()
                if not line or line.startswith(("#", "@")):
                    continue
                columns = line.split(",")
                try:
                    values = [float(value) for value in columns]
                except ValueError as exc:
                    raise ConfigurationError(
                        f"probe.coordinates_file: {path}:{line_number}: "
                        "expected three finite numbers separated by commas"
                    ) from exc
                if len(values) != 3 or not all(map(math.isfinite, values)):
                    raise ConfigurationError(
                        f"probe.coordinates_file: {path}:{line_number}: "
                        "expected three finite numbers separated by commas"
                    )
                count += 1
    except (OSError, UnicodeError) as exc:
        raise ConfigurationError(
            f"probe.coordinates_file: cannot read {path}: {exc}"
        ) from exc
    if count != frame_count:
        raise ConfigurationError(
            f"probe.coordinates_file: expected {frame_count} coordinates "
            f"(one per original frame), received {count}"
        )


def validate_molecular(
    config: TupaConfig, universe: Universe
) -> MolecularValidation:
    """Check the first selected frame of an already opened Universe.

    Reader position and box dimensions are restored, including overridden
    dimensions in memory-backed trajectories. No field is computed. Subsequent
    frame-dependent conditions must be checked by the future execution layer.
    """
    from MDAnalysis.exceptions import NoDataError, SelectionError

    frame_count = len(universe.trajectory)
    start = config.trajectory.start
    stop = config.trajectory.stop
    if start >= frame_count:
        raise ConfigurationError(
            f"trajectory.start: {start} is outside {frame_count} frames"
        )
    if stop is not None and stop > frame_count:
        raise ConfigurationError(
            f"trajectory.stop: {stop} exceeds {frame_count} frames"
        )
    stop = frame_count if stop is None else stop
    selected_frames = len(range(start, stop, config.trajectory.step))
    if config.probe.coordinates_file is not None:
        validate_coordinate_file(config.probe.coordinates_file, frame_count)

    warnings = []

    def select(key: str, expression: str) -> AtomGroup:
        try:
            group = universe.select_atoms(
                expression, periodic=config.pbc.policy != "none"
            )
        except (
            SelectionError,
            NoDataError,
            ValueError,
            AttributeError,
        ) as exc:
            raise ConfigurationError(
                f"{key}: invalid selection {expression!r}: {exc}"
            ) from exc
        if not len(group):
            raise ConfigurationError(
                f"{key}: selection {expression!r} contains no atoms "
                f"at frame {start}"
            )
        if not np.isfinite(group.positions).all():
            raise ConfigurationError(f"{key}: positions must be finite")
        return group

    original_frame = universe.trajectory.ts.frame
    original_dimensions = universe.dimensions
    if original_dimensions is not None:
        original_dimensions = original_dimensions.copy()
    universe.trajectory[start]
    dimensions = universe.dimensions
    saved_dimensions = None if dimensions is None else dimensions.copy()
    try:
        if config.pbc.override_box:
            universe.dimensions = config.pbc.dimensions
        if config.pbc.policy != "none":
            box = universe.dimensions
            if (
                box is None
                or not np.isfinite(box).all()
                or np.any(box[:3] <= 0)
            ):
                raise ConfigurationError(
                    "pbc.dimensions: periodic policies require finite, "
                    "positive box lengths or an explicit override"
                )
            if not np.all(box[3:] == 90):
                raise ConfigurationError(
                    "pbc.policy: only orthorhombic boxes are supported"
                )

        environment = select(
            "environment.selection", config.environment.selection
        )
        indices = environment.indices
        if config.solvent.enabled:
            solvent = select("solvent.selection", config.solvent.selection)
            if np.intersect1d(indices, solvent.indices).size:
                warnings.append(
                    "solvent.selection overlaps environment.selection; "
                    "historical concatenation can count atoms more than once"
                )
            indices = np.union1d(indices, solvent.indices)
        try:
            charges = universe.atoms[indices].charges
        except NoDataError as exc:
            raise ConfigurationError(
                "system.topology: selected environment/solvent atoms "
                "require partial charges"
            ) from exc
        if not np.isfinite(charges).all():
            raise ConfigurationError(
                "system.topology: selected partial charges must be finite"
            )

        probe_groups = []
        if config.analysis.mode == "ATOM":
            probe_groups.append(
                select("probe.selection", config.probe.selection)
            )
        elif config.analysis.mode == "BOND":
            for name in ("atom1", "atom2"):
                group = select(f"probe.{name}", getattr(config.probe, name))
                if len(group) > 1:
                    warnings.append(
                        f"probe.{name} selects {len(group)} atoms; "
                        "BOND uses the first atom in topology order"
                    )
                probe_groups.append(group[:1])
            if np.array_equal(
                probe_groups[0].positions, probe_groups[1].positions
            ):
                raise ConfigurationError(
                    "probe.atom1/probe.atom2: bond endpoints must be distinct"
                )
        if any(
            np.intersect1d(indices, group.indices).size
            for group in probe_groups
        ):
            warnings.append(
                "Probe atoms overlap the environment/solvent; "
                "exclude unwanted self contributions explicitly"
            )
        return MolecularValidation(
            atom_count=len(universe.atoms),
            frame_count=frame_count,
            selected_frames=selected_frames,
            environment_atoms=len(environment),
            warnings=tuple(warnings),
        )
    finally:
        universe.dimensions = saved_dimensions
        universe.trajectory[original_frame]
        universe.dimensions = original_dimensions
