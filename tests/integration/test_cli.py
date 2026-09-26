"""CLI contracts independent of legacy inputs."""

import subprocess
import sys
import tomllib
from pathlib import Path

import MDAnalysis as mda
import numpy as np
import pytest
from typer.testing import CliRunner

from tupa.cli.app import app
from tupa.config import TupaConfig


@pytest.mark.parametrize("mode", ["ATOM", "BOND", "COORDINATE", "LIST"])
def test_template_modes_and_existing_file(tmp_path: Path, mode: str) -> None:
    target = tmp_path / "project with spaces.toml"
    runner = CliRunner()
    created = runner.invoke(
        app, ["config", "template", str(target), "--mode", mode]
    )
    assert created.exit_code == 0, created.output
    assert (
        TupaConfig.model_validate(
            tomllib.loads(target.read_text())
        ).analysis.mode
        == mode
    )
    original = target.read_bytes()
    refused = runner.invoke(app, ["config", "template", str(target)])
    assert refused.exit_code == 2
    assert target.read_bytes() == original
    replaced = runner.invoke(
        app, ["config", "template", str(target), "--force"]
    )
    assert replaced.exit_code == 0
    assert 'mode = "ATOM"' in target.read_text()


def test_help_and_errors_from_external_directory(tmp_path: Path) -> None:
    command = [sys.executable, "-m", "tupa.cli"]
    help_result = subprocess.run(
        [*command, "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert help_result.returncode == 0
    assert all(
        name in help_result.stdout
        for name in ("run", "validate", "info", "config")
    )
    missing = subprocess.run(
        [*command, "validate", "missing config.toml"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert missing.returncode == 2
    assert "missing config.toml" in missing.stderr
    assert not list(tmp_path.iterdir())


def test_run_preflights_before_unavailable_message(tmp_path: Path) -> None:
    target = tmp_path / "config.toml"
    runner = CliRunner()
    assert (
        runner.invoke(app, ["config", "template", str(target)]).exit_code == 0
    )
    result = runner.invoke(app, ["run", str(target)])
    assert result.exit_code == 2
    assert "system.topology" in result.output
    assert "Scientific calculations are not available" not in result.output
    assert not (tmp_path / "results").exists()


def test_template_to_pipe_and_quiet(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tupa.cli",
            "--quiet",
            "config",
            "template",
            "a b.toml",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert (tmp_path / "a b.toml").is_file()


def molecular_files(tmp_path: Path) -> tuple[Path, Path]:
    universe = mda.Universe.empty(2, n_residues=1, trajectory=True)
    universe.add_TopologyAttr("names", ["A", "B"])
    universe.add_TopologyAttr("resnames", ["MOL"])
    universe.add_TopologyAttr("resids", [1])
    universe.add_TopologyAttr("charges", [-0.2, 0.2])
    universe.add_TopologyAttr("radii", [1.0, 1.0])
    universe.atoms.positions = np.array([[1, 0, 0], [2, 0, 0]])
    universe.dimensions = [20, 20, 20, 90, 90, 90]
    topology = tmp_path / "system with spaces.pqr"
    trajectory = tmp_path / "frames with spaces.dcd"
    with mda.Writer(str(topology), n_atoms=2) as writer:
        writer.write(universe.atoms)
    with mda.Writer(str(trajectory), n_atoms=2) as writer:
        writer.write(universe.atoms)
    return topology, trajectory


def test_info_reads_generated_molecular_files(tmp_path: Path) -> None:
    topology, trajectory = molecular_files(tmp_path)
    result = CliRunner().invoke(app, ["info", str(topology), str(trajectory)])
    assert result.exit_code == 0, result.output
    assert "Atoms: 2" in result.output
    assert "Frames: 1" in result.output
    assert "20, 20, 20, 90, 90, 90" in result.output


def test_validate_and_run_with_valid_inputs(tmp_path: Path) -> None:
    topology, trajectory = molecular_files(tmp_path)
    config = tmp_path / "valid config.toml"
    config.write_text(
        "schema_version = 2\n"
        "[system]\n"
        f'topology = "{topology.name}"\n'
        f'trajectory = "{trajectory.name}"\n'
        '[analysis]\nmode = "ATOM"\n'
        '[environment]\nselection = "name A"\n'
        '[probe]\nselection = "name B"\n',
        encoding="utf-8",
    )
    runner = CliRunner()
    validated = runner.invoke(app, ["validate", str(config)])
    assert validated.exit_code == 0, validated.output
    assert "Valid ATOM configuration" in validated.output
    run = runner.invoke(app, ["run", str(config)])
    assert run.exit_code == 3, run.output
    assert "Scientific calculations are not available yet" in run.output
    assert not (tmp_path / "results").exists()
