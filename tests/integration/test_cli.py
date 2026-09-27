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
from tupa.config import TupaConfig, load_config


@pytest.mark.parametrize("mode", ["ATOM", "BOND", "COORDINATE", "LIST"])
def test_create_modes_and_existing_directory(
    tmp_path: Path, mode: str
) -> None:
    project = tmp_path / "project with spaces"
    target = project / "config.toml"
    runner = CliRunner()
    created = runner.invoke(app, ["create", str(project), "--mode", mode])
    assert created.exit_code == 0, created.output
    assert (
        TupaConfig.model_validate(
            tomllib.loads(target.read_text())
        ).analysis.mode
        == mode
    )
    original = target.read_bytes()
    refused = runner.invoke(app, ["create", str(project)])
    assert refused.exit_code == 2
    assert target.read_bytes() == original


def test_create_refuses_existing_empty_directory(tmp_path: Path) -> None:
    project = tmp_path / "existing"
    project.mkdir()
    result = CliRunner().invoke(app, ["create", str(project)])
    assert result.exit_code == 2
    assert not list(project.iterdir())


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
        for name in ("run", "validate", "info", "create")
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
    project = tmp_path / "project"
    target = project / "config.toml"
    runner = CliRunner()
    assert runner.invoke(app, ["create", str(project)]).exit_code == 0
    result = runner.invoke(app, ["run", str(target)])
    assert result.exit_code == 2
    assert "system.topology" in result.output
    assert "Scientific calculations are not available" not in result.output
    assert not (project / "results").exists()


def test_create_to_pipe_and_quiet(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tupa.cli",
            "--quiet",
            "create",
            "a b",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert (tmp_path / "a b" / "config.toml").is_file()


def test_migrate_creates_project_and_preserves_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "old config.conf"
    source.write_text(
        "[Environment Selection]\nsele_environment=name ENV\n"
        "[Probe Selection]\nmode=ATOM\nselatom=name A\n"
        "[Time]\nbegintime=5\n",
        encoding="utf-8",
    )
    original = source.read_bytes()
    (tmp_path / "system.psf").write_bytes(b"topology")
    (tmp_path / "frames.dcd").write_bytes(b"trajectory")
    project = tmp_path / "new project"
    monkeypatch.chdir(tmp_path)
    args = [
        "migrate",
        project.name,
        "--source",
        source.name,
        "--topology",
        "system.psf",
        "--trajectory",
        "frames.dcd",
    ]
    runner = CliRunner()
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    assert "Ignored begintime" in result.output
    assert source.read_bytes() == original
    config = project / "config.toml"
    assert config.is_file()
    assert (project / "inputs/system.psf").read_bytes() == b"topology"
    assert (project / "inputs/frames.dcd").read_bytes() == b"trajectory"
    assert 'topology = "inputs/system.psf"' in config.read_text()
    assert 'trajectory = "inputs/frames.dcd"' in config.read_text()
    assert (
        TupaConfig.model_validate(
            tomllib.loads(config.read_text())
        ).analysis.mode
        == "ATOM"
    )
    assert runner.invoke(app, args).exit_code == 2
    assert source.read_bytes() == original


def test_migrate_failure_leaves_no_project(tmp_path: Path) -> None:
    source = tmp_path / "invalid.conf"
    source.write_text("[Unknown]\nx=y\n", encoding="utf-8")
    project = tmp_path / "project"
    result = CliRunner().invoke(
        app,
        [
            "migrate",
            str(project),
            "--source",
            str(source),
            "--topology",
            str(tmp_path / "t.psf"),
            "--trajectory",
            str(tmp_path / "t.dcd"),
        ],
    )
    assert result.exit_code == 2
    assert "Unknown legacy section" in result.output
    assert not project.exists()


def test_migrate_list_copies_coordinates_from_explicit_path(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "old"
    source_dir.mkdir()
    inputs_dir = tmp_path / "original inputs"
    inputs_dir.mkdir()
    source = source_dir / "config.conf"
    source.write_text(
        "[Environment Selection]\nsele_environment=name ENV\n"
        "[Probe Selection]\nmode=LIST\n"
        "file_of_coordinates=points.csv\nremove_self=true\n",
        encoding="utf-8",
    )
    for name, content in (
        ("system.psf", b"topology"),
        ("frames.dcd", b"trajectory"),
        ("points.csv", b"1,2,3\n"),
    ):
        (inputs_dir / name).write_bytes(content)
    project = tmp_path / "new"
    result = CliRunner().invoke(
        app,
        [
            "migrate",
            str(project),
            "--source",
            str(source),
            "--topology",
            str(inputs_dir / "system.psf"),
            "--trajectory",
            str(inputs_dir / "frames.dcd"),
            "--coordinates",
            str(inputs_dir / "points.csv"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert (project / "inputs/points.csv").read_bytes() == b"1,2,3\n"
    assert load_config(project / "config.toml").probe.coordinates_file == (
        project / "inputs/points.csv"
    )
    assert (inputs_dir / "points.csv").read_bytes() == b"1,2,3\n"


def test_migrate_missing_input_creates_nothing(tmp_path: Path) -> None:
    source = tmp_path / "config.conf"
    source.write_text(
        "[Environment Selection]\nsele_environment=name ENV\n"
        "[Probe Selection]\nmode=ATOM\nselatom=name A\n",
        encoding="utf-8",
    )
    project = tmp_path / "new"
    result = CliRunner().invoke(
        app,
        [
            "migrate",
            str(project),
            "--source",
            str(source),
            "--topology",
            str(tmp_path / "missing.psf"),
            "--trajectory",
            str(tmp_path / "missing.dcd"),
        ],
    )
    assert result.exit_code == 2
    assert "Input file does not exist" in result.output
    assert not project.exists()


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
