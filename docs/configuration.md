# TOML configuration

TUPÃ 2.0 uses `tomllib` to read TOML and Pydantic 2 to validate its structure.
The CLI and Python configuration API are available. The scientific engine is
not implemented yet. Parsing or validating a configuration does not execute
any calculation.

## Reading a configuration

Generate a starting file, then replace its example paths and selections:

```bash
tupa create project_name --mode ATOM
tupa validate project_name/config.toml
tupa info project_name/system.psf project_name/trajectory.dcd
```

`tupa create` makes the project directory and writes `config.toml` inside it.
It also accepts BOND, COORDINATE, and LIST, and refuses to reuse an existing
directory. `tupa validate` checks the
configuration and first selected molecular frame without creating outputs.
`tupa run` performs the same preflight, then exits with a clear unavailable
message until the scientific engine is implemented. Global `--quiet` suppresses
status output, `--no-color` disables color, and `-v` increases log detail.
Configuration errors exit with code 2; an unavailable engine exits with code 3.

```python
from tupa.config import ConfigurationError, load_config

try:
    config = load_config("config.toml")
except ConfigurationError as error:
    print(error)
else:
    print(config.analysis.mode)
    print(config.system.topology)
```

`load_config` returns an immutable `TupaConfig`. It rejects unknown keys and
invalid types. Numeric strings and integer boolean substitutes are not accepted:
use `cutoff = 10.0`, not `cutoff = "10"`; use `enabled = true`, not `enabled = 1`.
Integer TOML values are accepted for floating-point quantities. NaN and infinity
are rejected. Mode names are uppercase; backend and policy names are lowercase.

Relative paths, including the default output directory, resolve against the
TOML file's directory, not the working directory. Absolute paths remain
absolute and `~` is expanded. Environment-variable substitution is not performed.
Input existence is checked separately. Loading creates no output directories
and imports neither MDAnalysis nor CuPy.

`TupaConfig.model_validate(...)` also accepts Python dictionaries, but leaves
relative paths unresolved. Prefer `load_config` for file-based configurations.

## Sections and fields

`system`, `analysis`, `environment`, and `probe` are required. Other sections
have defaults. An omitted `schema_version` means `2`; no other version is
accepted. Optional values are omitted rather than written as `null`, which is
not a TOML value.

| Section | Fields and defaults |
| --- | --- |
| `system` | Required `topology` and `trajectory` paths |
| `analysis` | Required `mode`: `ATOM`, `BOND`, `COORDINATE`, or `LIST` |
| `environment` | Required nonempty MDAnalysis `selection`; optional positive `cutoff` in angstroms |
| `probe` | Mode-specific fields below; `remove_self = false`; optional positive `remove_radius` in angstroms |
| `solvent` | `enabled = false`; when enabled, requires nonempty `selection` and positive `radius` in angstroms |
| `pbc` | `policy = "legacy"`; alternatives `"none"`, `"minimum_image"`; `override_box = false`; optional `dimensions` |
| `trajectory` | `start = 0`, optional exclusive `stop`, `step = 1`, `time_source = "legacy_dt"`, `dt_ps = 1.0` |
| `compute` | `backend = "auto"` (`auto/cpu/gpu`); `precision = "double"` (`single/double`); `chunk_size = "auto"` or positive integer; optional nonnegative `neighbor_skin` |
| `output` | `directory = "results"`, `format = "legacy"`, `atomic_contributions = false`, `residue_contributions = true`, `dump_times_ps = []` |

No global cutoff is enabled by default. An explicit `environment.cutoff` is a
new physical truncation, distinct from solvent selection by residue. A solvent
radius is required when enabled; no ambiguous default is inferred. Solvent
selection/radius fields are rejected when solvent is disabled.

`neighbor_skin` requires either an environment cutoff or enabled solvent with
a radius. It is a neighbor-search margin, not an additional physical cutoff.

These fields define the configuration contract. Accepting GPU, single precision,
cutoff, minimum-image PBC, or neighbor settings here does **not** imply that the
corresponding calculation backend is already available. Hardware availability
and execution capability checks belong to later backend/application tasks.

## Probe modes

| Mode | Required probe fields | Meaning |
| --- | --- | --- |
| ATOM | `selection` | Atom position or center of geometry for multiple atoms |
| BOND | `atom1`, `atom2` | Midpoint and directed axis from the first atom of atom1 to the first atom of atom2 |
| COORDINATE | `position = [x, y, z]` | Fixed coordinate in angstroms |
| LIST | `coordinates_file` | One XYZ coordinate per original trajectory frame |

Fields for other modes are rejected. For example, a BOND probe cannot also
specify `position`. BOND selections with multiple atoms produce a preflight
warning rather than silently choosing the first. Empty selections fail.
Coincident bond endpoints fail validation.

`remove_self` is supported only for COORDINATE/LIST. When enabled, an omitted
`remove_radius` means 1 angstrom; `config.probe.effective_remove_radius` exposes
the effective value. Providing a radius while removal is disabled is an error.
The intended scientific contract is residue-based exclusion, not automatic
removal of individual probe atoms in ATOM/BOND mode.

LIST files use comma-separated `x,y,z` in angstroms. Blank lines and lines
starting with `#` or `@` (after whitespace) are ignored. All coordinates must
be finite. The number of data lines must match the entire original trajectory,
even when only a slice of frames is requested. File errors include line numbers.
The validator streams the coordinate file instead of storing all rows.

## Frame ranges, time, and boxes

Frame indices are zero-based. `start` is nonnegative, `stop` is exclusive and
must exceed `start`, and `step` is a positive integer. Omit `stop` to process
the remaining frames; `-1` is rejected. Molecular validation rejects ranges
outside the trajectory instead of silently clamping them.

`legacy_dt` describes time as `dt_ps * (original_frame_index + 1)`. A positive
fractional `dt_ps` is allowed in the new schema. `time_source = "trajectory"`
selects reader-provided times and forbids an explicit `dt_ps` override.

`pbc.dimensions` is `[a, b, c, alpha, beta, gamma]`, with positive lengths in
angstroms and angles in degrees. An override requires both
`override_box = true` and `dimensions`. Periodic validation currently supports
orthorhombic boxes only. `policy = "none"` needs no box and rejects an override.

`legacy` describes the historical solvent re-image convention; `minimum_image`
is an explicit alternative for the future numerical implementation. The parser
and preflight validator do not apply either electrostatic convention.

## File and molecular preflight

Checks are separate so a caller can validate structure without expensive I/O:

```python
import MDAnalysis as mda

from tupa.config import load_config
from tupa.config.validation import validate_input_files, validate_molecular

config = load_config("config.toml")
validate_input_files(config)
universe = mda.Universe(config.system.topology, config.system.trajectory)
try:
    report = validate_molecular(config, universe)
    print(report.selected_frames)
    for warning in report.warnings:
        print(warning)
finally:
    universe.trajectory.close()
```

`validate_input_files` checks readable input files and rejects output paths
with an existing non-directory component. It does not create files or certify
that a molecular format is valid; opening the Universe performs that check.

`validate_molecular` checks the first selected frame: box, selections, finite
positions, partial charges on environment/solvent candidates, probe endpoints,
and frame bounds. It warns about overlapping environment/solvent and probe
selections without changing those selections. The returned dataclass contains
atom/frame counts, selected frame count, environment size, and warnings.
The original reader frame and dimensions are restored after success or error.
No field, residue contribution, or projection is calculated.

Frame-dependent validity can change later in the trajectory. The future
execution layer must recheck positions, charges, selections, boxes, and
singularities as it processes frames; a successful preflight is not proof of
validity for every frame.

## Templates

- [ATOM](examples/atom.toml)
- [BOND](examples/bond.toml)
- [COORDINATE](examples/coordinate.toml)
- [LIST](examples/list.toml)

These are schema-valid templates with placeholder input paths and selections.
Supply your own molecular data before calling file/molecular validation.

Implementation references: [Pydantic validators](https://docs.pydantic.dev/latest/concepts/validators/),
[Pydantic strict mode](https://docs.pydantic.dev/latest/concepts/strict_mode/),
and [MDAnalysis Universe](https://docs.mdanalysis.org/stable/documentation_pages/core/universe.html).
