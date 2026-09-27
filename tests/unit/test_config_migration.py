"""Conversion contracts use newly written INI inputs, not legacy files."""

from pathlib import Path

import pytest

from tupa.config import ConfigurationError, load_config
from tupa.config.migration import migrate_config


def source_file(tmp_path: Path, probe: str, extra: str = "") -> Path:
    source = tmp_path / "old config.conf"
    source.write_text(
        "[Environment Selection]\nsele_environment = name ENV\n"
        f"[Probe Selection]\n{probe}\n{extra}",
        encoding="utf-8",
    )
    return source


@pytest.mark.parametrize(
    ("probe", "mode", "attribute"),
    [
        ("mode=ATOM\nselatom=name A", "ATOM", "selection"),
        ("mode=BOND\nselbond1=name A\nselbond2=name B", "BOND", "atom1"),
        (
            "mode=COORDINATE\nprobecoordinate=[1,2,3]",
            "COORDINATE",
            "position",
        ),
        (
            "mode=LIST\nfile_of_coordinates=points.csv",
            "LIST",
            "coordinates_file",
        ),
    ],
)
def test_mode_conversion(
    tmp_path: Path, probe: str, mode: str, attribute: str
) -> None:
    source = source_file(tmp_path, probe)
    result = migrate_config(
        source,
        topology=tmp_path / "system.psf",
        trajectory=tmp_path / "frames.dcd",
        coordinates=tmp_path / "points.csv" if mode == "LIST" else None,
    )
    assert result.config.analysis.mode == mode
    assert getattr(result.config.probe, attribute) is not None
    assert 'topology = "inputs/system.psf"' in result.toml
    assert 'trajectory = "inputs/frames.dcd"' in result.toml
    assert {item.source for item in result.inputs} == {
        tmp_path / "system.psf",
        tmp_path / "frames.dcd",
        *((tmp_path / "points.csv",) if mode == "LIST" else ()),
    }
    if mode == "LIST":
        assert result.config.probe.coordinates_file == Path(
            "inputs/points.csv"
        )


def test_section_aliases_and_ignored_time(tmp_path: Path) -> None:
    source = tmp_path / "old.conf"
    source.write_text(
        "[Elecfield Selection]\nsele_elecfield = name ENV\n"
        "[Target Selection]\nmode=COORDINATE\ntargetcoordinate=[0,1,2]\n"
        "remove_self=true\nremove_cutoff=2\n"
        "[Time]\ndt=2.5\nbegintime=10\nendtime=20\n",
        encoding="utf-8",
    )
    result = migrate_config(
        source,
        topology=tmp_path / "t.psf",
        trajectory=tmp_path / "t.dcd",
    )
    assert result.config.probe.position == (0, 1, 2)
    assert result.config.probe.remove_radius == 2
    assert result.config.trajectory.dt_ps == 2.5
    assert any("targetcoordinate" in item for item in result.warnings)
    assert any("begintime" in item for item in result.warnings)
    assert any("endtime" in item for item in result.warnings)


def test_solvent_box_and_inactive_options(tmp_path: Path) -> None:
    source = source_file(
        tmp_path,
        "mode=BOND\nselbond1=name A\nselbond2=name B\nselatom=name C",
        "[Solvent]\ninclude_solvent=true\n"
        "solvent_selection=resname WAT\nsolvent_cutoff=12\n"
        "[Box Info]\nredefine_box=true\n"
        "boxdimensions=[20,20,20,90,90,90]\n",
    )
    result = migrate_config(
        source,
        topology=tmp_path / "t.psf",
        trajectory=tmp_path / "t.dcd",
    )
    assert result.config.solvent.enabled
    assert result.config.solvent.radius == 12
    assert result.config.pbc.dimensions == (20, 20, 20, 90, 90, 90)
    assert any("selatom" in item for item in result.warnings)


@pytest.mark.parametrize(
    ("probe", "extra", "message"),
    [
        (
            "mode=COORDINATE\nprobecoordinate=[0,0,0]\n"
            "targetcoordinate=[1,1,1]",
            "",
            "Conflicting coordinate aliases",
        ),
        ("mode=ATOM\nselatom=name A\nunknown=1", "", "Unknown option"),
        (
            "mode=ATOM\nselatom=name A",
            "[Other]\nx=1",
            "Unknown legacy section",
        ),
        ("mode=COORDINATE\nprobecoordinate=[1,2]", "", "expected 3"),
        ("mode=ATOM\nselatom=name A", "[Time]\ndt=0", "invalid"),
    ],
)
def test_rejects_unsafe_inputs(
    tmp_path: Path, probe: str, extra: str, message: str
) -> None:
    source = source_file(tmp_path, probe, extra)
    with pytest.raises(ConfigurationError, match=message):
        migrate_config(
            source,
            topology=tmp_path / "t.psf",
            trajectory=tmp_path / "t.dcd",
        )


def test_generated_toml_loads_relative_to_new_directory(
    tmp_path: Path,
) -> None:
    source = source_file(tmp_path, "mode=ATOM\nselatom=name A")
    project = tmp_path / "new project"
    project.mkdir()
    result = migrate_config(
        source,
        topology=tmp_path / "t.psf",
        trajectory=tmp_path / "t.dcd",
    )
    target = project / "config.toml"
    target.write_text(result.toml, encoding="utf-8")
    assert load_config(target).system.topology == project / "inputs/t.psf"


def test_input_filename_collision_is_rejected(tmp_path: Path) -> None:
    source = source_file(tmp_path, "mode=ATOM\nselatom=name A")
    with pytest.raises(ConfigurationError, match="filename collision"):
        migrate_config(
            source,
            topology=tmp_path / "one/system.dat",
            trajectory=tmp_path / "two/system.dat",
        )


def test_relative_paths_resolve_from_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_file(tmp_path, "mode=LIST\nfile_of_coordinates=points.csv")
    monkeypatch.chdir(tmp_path)
    result = migrate_config(
        Path("old config.conf"),
        topology=Path("system.psf"),
        trajectory=Path("frames.dcd"),
    )
    assert {item.source for item in result.inputs} == {
        tmp_path / "system.psf",
        tmp_path / "frames.dcd",
        tmp_path / "points.csv",
    }


def test_absolute_list_path_in_conf_needs_no_override(tmp_path: Path) -> None:
    points = tmp_path / "points.csv"
    source = source_file(tmp_path, f"mode=LIST\nfile_of_coordinates={points}")
    result = migrate_config(
        source,
        topology=tmp_path / "system.psf",
        trajectory=tmp_path / "frames.dcd",
    )
    assert result.config.probe.coordinates_file == Path("inputs/points.csv")
