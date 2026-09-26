"""Preflight and execution availability for a scientific run."""

import logging
from pathlib import Path

import MDAnalysis as mda

from tupa.config import ConfigurationError, load_config
from tupa.config.models import TupaConfig
from tupa.config.validation import (
    MolecularValidation,
    validate_input_files,
    validate_molecular,
)

logger = logging.getLogger(__name__)


def inspect_system(
    topology: Path, trajectory: Path
) -> tuple[int, int, tuple[float, ...] | None]:
    """Read basic trajectory metadata without calculating a field."""
    for name, path in (("topology", topology), ("trajectory", trajectory)):
        if not path.is_file():
            raise ConfigurationError(
                f"{name}: expected an existing file: {path}"
            )
    try:
        logger.info(
            "Opening topology %s and trajectory %s", topology, trajectory
        )
        universe = mda.Universe(str(topology), str(trajectory))
        try:
            frame_count = len(universe.trajectory)
            if not frame_count:
                raise ConfigurationError("trajectory: contains no frames")
            dimensions = universe.trajectory[0].dimensions
            box = None if dimensions is None else tuple(map(float, dimensions))
            logger.debug(
                "Read %d atoms and %d frames", len(universe.atoms), frame_count
            )
            return len(universe.atoms), frame_count, box
        finally:
            universe.trajectory.close()
    except (OSError, ValueError, IndexError, NotImplementedError) as exc:
        raise ConfigurationError(
            f"Cannot read molecular system: {exc}"
        ) from exc


def validate_project(path: Path) -> tuple[TupaConfig, MolecularValidation]:
    """Validate a configuration and its first selected molecular frame."""
    config = load_config(path)
    logger.info("Loaded %s configuration from %s", config.analysis.mode, path)
    validate_input_files(config)
    try:
        logger.info("Opening topology and trajectory for molecular preflight")
        universe = mda.Universe(
            str(config.system.topology), str(config.system.trajectory)
        )
        try:
            report = validate_molecular(config, universe)
            logger.debug(
                "Validated %d of %d trajectory frames",
                report.selected_frames,
                report.frame_count,
            )
        finally:
            universe.trajectory.close()
    except (OSError, ValueError, IndexError, NotImplementedError) as exc:
        if isinstance(exc, ConfigurationError):
            raise
        raise ConfigurationError(
            f"Cannot validate molecular system: {exc}"
        ) from exc
    return config, report


def prepare_run(path: Path) -> MolecularValidation:
    """Preflight before reporting that the new scientific engine is pending."""
    config, report = validate_project(path)
    if config.compute.backend == "gpu":
        raise ConfigurationError("GPU backend is not available yet")
    return report
