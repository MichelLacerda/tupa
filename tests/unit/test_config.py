"""Configuration rules do not depend on MDAnalysis or input files."""

import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from tupa.config import ConfigurationError, TupaConfig, load_config


@pytest.fixture
def config_data() -> dict:
    return {
        "system": {"topology": "system.psf", "trajectory": "frames.dcd"},
        "analysis": {"mode": "ATOM"},
        "environment": {"selection": "protein"},
        "probe": {"selection": "resname LIG"},
    }


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(
        '[system]\ntopology = "system.psf"\ntrajectory = "frames.dcd"\n'
        '[analysis]\nmode = "ATOM"\n'
        '[environment]\nselection = "protein"\n'
        '[probe]\nselection = "resname LIG"\n',
        encoding="utf-8",
    )
    return path


@pytest.mark.parametrize(
    ("mode", "probe"),
    [
        ("ATOM", {"selection": "resname LIG"}),
        ("BOND", {"atom1": "name A", "atom2": "name B"}),
        ("COORDINATE", {"position": [1, 2, 3]}),
        ("LIST", {"coordinates_file": "points.csv"}),
    ],
)
def test_modes_and_defaults(config_data: dict, mode: str, probe: dict) -> None:
    config_data["analysis"]["mode"] = mode
    config_data["probe"] = probe
    config = TupaConfig.model_validate(config_data)
    assert config.analysis.mode == mode
    assert config.environment.cutoff is None
    assert config.pbc.policy == "legacy"
    assert config.compute.precision == "double"
    assert config.compute.backend == "auto"
    assert config.trajectory.stop is None
    assert config.trajectory.dt_ps == 1.0
    assert not config.solvent.enabled
    assert config.probe.effective_remove_radius == 0


@pytest.mark.parametrize(
    ("section", "key", "value"),
    [
        ("environment", "cutoff", -1),
        ("environment", "cutoff", 0),
        ("environment", "cutoff", "10"),
        ("environment", "cutoff", True),
        ("environment", "cutoff", float("nan")),
        ("environment", "cutoff", float("inf")),
        ("environment", "selection", "   "),
        ("environment", "typo", 1),
        ("analysis", "mode", "UNKNOWN"),
        ("compute", "backend", "cuda"),
        ("compute", "precision", "half"),
        ("compute", "chunk_size", 0),
        ("compute", "chunk_size", True),
        ("compute", "chunk_size", 2.5),
        ("compute", "neighbor_skin", -1),
        ("trajectory", "start", -1),
        ("trajectory", "step", 0),
        ("trajectory", "stop", -1),
        ("trajectory", "dt_ps", "1"),
        ("trajectory", "dt_ps", 0),
        ("solvent", "enabled", "false"),
        ("output", "atomic_contributions", 1),
        ("output", "format", "unknown"),
        ("output", "dump_times_ps", [-1]),
        ("output", "dump_times_ps", [float("inf")]),
        ("system", "topology", " "),
        ("system", "trajectory", 123),
    ],
)
def test_rejects_invalid_fields(config_data, section, key, value):
    config_data.setdefault(section, {})[key] = value
    with pytest.raises(ValidationError) as error:
        TupaConfig.model_validate(config_data)
    assert any(
        item["loc"][:2] == (section, key) for item in error.value.errors()
    )


@pytest.mark.parametrize("version", [True, "2", 2.0, 1, 3])
def test_schema_version_is_strict(config_data, version):
    config_data["schema_version"] = version
    with pytest.raises(ValidationError, match="schema_version"):
        TupaConfig.model_validate(config_data)


@pytest.mark.parametrize(
    "changes",
    [
        {"analysis": {"mode": "BOND"}, "probe": {"atom1": "name A"}},
        {"probe": {"selection": "all", "position": [0, 0, 0]}},
        {"probe": {"selection": "all", "remove_self": True}},
        {"probe": {"selection": "all", "remove_radius": 1}},
        {"solvent": {"enabled": True}},
        {"solvent": {"enabled": True, "selection": "all"}},
        {"solvent": {"enabled": False, "radius": 10}},
        {"pbc": {"override_box": True}},
        {"pbc": {"dimensions": [10, 10, 10, 90, 90, 90]}},
        {
            "pbc": {
                "override_box": True,
                "dimensions": [10, 10, 10, 90, 80, 90],
            }
        },
        {"pbc": {"override_box": True, "dimensions": [0, 10, 10, 90, 90, 90]}},
        {
            "pbc": {
                "policy": "none",
                "override_box": True,
                "dimensions": [10, 10, 10, 90, 90, 90],
            }
        },
        {"trajectory": {"start": 5, "stop": 5}},
        {"trajectory": {"time_source": "trajectory", "dt_ps": 2}},
        {"compute": {"neighbor_skin": 2}},
        {"unknown_section": {}},
    ],
)
def test_incompatible_options(config_data, changes):
    config_data.update(changes)
    with pytest.raises(ValidationError):
        TupaConfig.model_validate(config_data)


@pytest.mark.parametrize(
    "position",
    [[0, 1], [0, 1, 2, 3], [0, True, 2], [0, "1", 2], [0, float("nan"), 2]],
)
def test_coordinate_shape_and_types(config_data, position):
    config_data["analysis"]["mode"] = "COORDINATE"
    config_data["probe"] = {"position": position}
    with pytest.raises(ValidationError, match="position"):
        TupaConfig.model_validate(config_data)


def test_removal_and_neighbor_settings(config_data):
    config_data["analysis"]["mode"] = "COORDINATE"
    config_data["probe"] = {"position": [0, 0, 0], "remove_self": True}
    config_data["solvent"] = {
        "enabled": True,
        "selection": "water",
        "radius": 10,
    }
    config_data["compute"] = {"neighbor_skin": 0, "chunk_size": 128}
    config = TupaConfig.model_validate(config_data)
    assert config.probe.effective_remove_radius == 1.0
    assert config.compute.neighbor_skin == 0.0
    assert config.compute.chunk_size == 128
    assert config.probe.position == (0.0, 0.0, 0.0)
    with pytest.raises(ValidationError, match="frozen"):
        config.probe.remove_self = False


def test_paths_resolve_against_config_not_cwd(
    config_file, tmp_path, monkeypatch
):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    config = load_config(config_file)
    assert config.system.topology == tmp_path / "system.psf"
    assert config.system.trajectory == tmp_path / "frames.dcd"
    assert config.output.directory == tmp_path / "results"
    assert not config.output.directory.exists()
    assert not config.system.topology.exists()


def test_list_and_absolute_paths(config_file, tmp_path):
    text = config_file.read_text().replace('mode = "ATOM"', 'mode = "LIST"')
    text = text.replace(
        'selection = "resname LIG"', 'coordinates_file = "points.csv"'
    )
    text += f'\n[output]\ndirectory = "{tmp_path.as_posix()}/absolute"\n'
    config_file.write_text(text)
    config = load_config(config_file)
    assert config.probe.coordinates_file == tmp_path / "points.csv"
    assert config.output.directory == tmp_path / "absolute"


@pytest.mark.parametrize(
    "content", ["[broken", 'invalid = "\\u0000"', "schema_version = 3"]
)
def test_invalid_toml_or_structure_has_source_path(tmp_path, content):
    path = tmp_path / "broken.toml"
    path.write_text(content)
    with pytest.raises(ConfigurationError) as error:
        load_config(path)
    assert str(path) in str(error.value)


def test_error_names_field_and_value(config_file):
    with config_file.open("a") as handle:
        handle.write("\n[compute]\nchunk_size = -5\n")
    with pytest.raises(
        ConfigurationError, match=r"compute.chunk_size.*received -5"
    ):
        load_config(config_file)


def test_missing_config(tmp_path):
    with pytest.raises(ConfigurationError, match="missing.toml"):
        load_config(tmp_path / "missing.toml")


def test_loading_does_not_import_molecular_or_gpu_libraries(
    config_file, tmp_path
):
    script = """
import importlib.abc
import sys
class BlockReaders(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'MDAnalysis', 'cupy', 'lib', 'TUPA'}:
            raise ImportError(f'Unexpected import: {fullname}')
sys.meta_path.insert(0, BlockReaders())
from tupa.config import load_config
load_config(sys.argv[1])
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", script, str(config_file)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("mode", ["ATOM", "BOND", "COORDINATE", "LIST"])
def test_documented_examples(mode):
    root = Path(__file__).resolve().parents[2]
    config = load_config(root / "docs" / "examples" / f"{mode.lower()}.toml")
    assert config.analysis.mode == mode
