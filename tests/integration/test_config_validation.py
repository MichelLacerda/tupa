"""Molecular preflight uses newly constructed, in-memory systems."""

from pathlib import Path

import MDAnalysis as mda
import numpy as np
import pytest

from tupa.config import ConfigurationError, TupaConfig
from tupa.config.validation import (
    validate_coordinate_file,
    validate_input_files,
    validate_molecular,
)


@pytest.fixture
def universe():
    u = mda.Universe.empty(
        5, n_residues=3, atom_resindex=[0, 0, 1, 2, 2], trajectory=True
    )
    u.add_TopologyAttr("names", ["A", "B", "P", "OW", "HW"])
    u.add_TopologyAttr("resnames", ["ENV", "PRB", "SOL"])
    u.add_TopologyAttr("charges", [-0.2, 0.2, 0, -0.8, 0.8])
    positions = np.array(
        [[1, 0, 0], [-1, 0, 0], [0, 0, 0], [8, 0, 0], [9, 0, 0]],
        dtype=np.float32,
    )
    u.load_new(
        np.repeat(positions[None, :, :], 3, axis=0),
        dimensions=np.tile([20, 20, 20, 90, 90, 90], (3, 1)),
    )
    return u


@pytest.fixture
def data(tmp_path):
    return {
        "system": {
            "topology": tmp_path / "system.psf",
            "trajectory": tmp_path / "frames.dcd",
        },
        "analysis": {"mode": "ATOM"},
        "environment": {"selection": "resname ENV"},
        "probe": {"selection": "name P"},
        "output": {"directory": tmp_path / "results"},
    }


def test_preflight_and_frame_restoration(data, universe):
    data["trajectory"] = {"start": 1, "stop": 3, "step": 1}
    data["pbc"] = {
        "override_box": True,
        "dimensions": [40, 40, 40, 90, 90, 90],
    }
    universe.trajectory[2]
    original_boxes = universe.trajectory.dimensions_array.copy()
    report = validate_molecular(TupaConfig.model_validate(data), universe)
    assert report.atom_count == 5
    assert report.environment_atoms == 2
    assert report.frame_count == 3
    assert report.selected_frames == 2
    assert report.warnings == ()
    assert universe.trajectory.ts.frame == 2
    np.testing.assert_array_equal(
        universe.trajectory.dimensions_array, original_boxes
    )


@pytest.mark.parametrize("selection", ["nonsense syntax", "name MISSING"])
def test_invalid_or_empty_selection_restores_frame(data, universe, selection):
    data["environment"]["selection"] = selection
    data["trajectory"] = {"start": 1}
    data["pbc"] = {
        "override_box": True,
        "dimensions": [40, 40, 40, 90, 90, 90],
    }
    boxes = universe.trajectory.dimensions_array.copy()
    with pytest.raises(ConfigurationError, match="environment.selection"):
        validate_molecular(TupaConfig.model_validate(data), universe)
    assert universe.trajectory.ts.frame == 0
    np.testing.assert_array_equal(universe.trajectory.dimensions_array, boxes)


def test_missing_charges(data, universe):
    universe.del_TopologyAttr("charges")
    with pytest.raises(ConfigurationError, match="partial charges"):
        validate_molecular(TupaConfig.model_validate(data), universe)


def test_nonfinite_charge(data, universe):
    universe.atoms[0].charge = np.nan
    with pytest.raises(ConfigurationError, match="charges must be finite"):
        validate_molecular(TupaConfig.model_validate(data), universe)


def test_nonfinite_position(data, universe):
    universe.atoms[0].position = [np.nan, 0, 0]
    with pytest.raises(ConfigurationError, match="positions must be finite"):
        validate_molecular(TupaConfig.model_validate(data), universe)


def test_explicit_nonperiodic_policy(data, universe):
    universe.dimensions = None
    with pytest.raises(ConfigurationError, match="positive box lengths"):
        validate_molecular(TupaConfig.model_validate(data), universe)
    data["pbc"] = {"policy": "none"}
    assert (
        validate_molecular(
            TupaConfig.model_validate(data), universe
        ).frame_count
        == 3
    )


def test_triclinic_periodic_box_is_rejected(data, universe):
    universe.dimensions = [20, 20, 20, 90, 80, 90]
    with pytest.raises(ConfigurationError, match="orthorhombic"):
        validate_molecular(TupaConfig.model_validate(data), universe)


@pytest.mark.parametrize("interval", [{"start": 3}, {"stop": 4}])
def test_frame_bounds(data, universe, interval):
    data["trajectory"] = interval
    with pytest.raises(ConfigurationError, match="trajectory"):
        validate_molecular(TupaConfig.model_validate(data), universe)


def test_bond_first_atom_is_explicit(data, universe):
    data["analysis"]["mode"] = "BOND"
    data["probe"] = {"atom1": "resname ENV", "atom2": "name P"}
    report = validate_molecular(TupaConfig.model_validate(data), universe)
    assert any("first atom" in message for message in report.warnings)
    assert any("Probe atoms overlap" in message for message in report.warnings)
    data["probe"]["atom2"] = "name A"
    with pytest.raises(ConfigurationError, match="endpoints must be distinct"):
        validate_molecular(TupaConfig.model_validate(data), universe)


def test_solvent_selection_and_overlap(data, universe):
    data["solvent"] = {"enabled": True, "selection": "all", "radius": 10}
    report = validate_molecular(TupaConfig.model_validate(data), universe)
    assert any(
        "count atoms more than once" in message for message in report.warnings
    )
    data["solvent"]["selection"] = "resname MISSING"
    with pytest.raises(ConfigurationError, match="solvent.selection"):
        validate_molecular(TupaConfig.model_validate(data), universe)


def test_list_count_uses_original_frames(data, universe, tmp_path):
    path = tmp_path / "probes.csv"
    path.write_text("# coordinates\n@ metadata\n\n0,0,0\n1,1,1\n2,2,2\n")
    data["analysis"]["mode"] = "LIST"
    data["probe"] = {"coordinates_file": path}
    data["trajectory"] = {"start": 1, "stop": 2}
    report = validate_molecular(TupaConfig.model_validate(data), universe)
    assert report.selected_frames == 1
    path.write_text("1,1,1\n")
    with pytest.raises(ConfigurationError, match="expected 3 coordinates"):
        validate_molecular(TupaConfig.model_validate(data), universe)


@pytest.mark.parametrize(
    "line", ["1,2", "1,2,3,4", "nan,0,0", "inf,0,0", "x,0,0"]
)
def test_invalid_list_row_has_line_number(tmp_path: Path, line: str):
    path = tmp_path / "points.csv"
    path.write_text(f"# header\n{line}\n")
    with pytest.raises(ConfigurationError, match=r"points.csv:2:"):
        validate_coordinate_file(path, frame_count=1)


def test_input_files_checked_without_output_creation(data):
    config = TupaConfig.model_validate(data)
    with pytest.raises(ConfigurationError, match="system.topology"):
        validate_input_files(config)
    config.system.topology.touch()
    config.system.trajectory.touch()
    validate_input_files(config)
    assert not config.output.directory.exists()
    config.output.directory.touch()
    with pytest.raises(ConfigurationError, match="output.directory"):
        validate_input_files(config)
