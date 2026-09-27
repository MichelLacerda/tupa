# Migrating historical configurations

Use `tupa migrate` to convert a historical `.conf` file into a new project
directory:

```bash
tupa migrate project_name \
  --source old.conf \
  --topology data/system.psf \
  --trajectory data/frames.dcd
```

The command creates `project_name/config.toml` and copies the topology,
trajectory, and (for LIST mode) coordinate file into `project_name/inputs/`.
The generated TOML uses paths such as `inputs/system.psf`, so the project can
be moved as a unit. The original `.conf` and input files remain unchanged.
An existing project directory is never reused. The historical format did not
contain topology and trajectory paths, so both must be supplied. The source
`.conf` is an option too; `project_name` is the only positional argument.
Relative paths in these options, and a relative `file_of_coordinates` value in
LIST mode, resolve from the current working directory. Use `--coordinates` to
override the LIST coordinate path when needed. Migration fails if an input is
missing or two different inputs share a filename. Run
`tupa validate project_name/config.toml`
after migration to check molecular formats and selections.

The converter recognizes both `Environment Selection`/`Probe Selection` and
`Elecfield Selection`/`Target Selection` headings. It maps `sele_environment`
or `sele_elecfield` to `environment.selection`, and `selatom`, `selbond1`/
`selbond2`, `probecoordinate`, or `file_of_coordinates` to the corresponding
probe field. `targetcoordinate` is accepted as an alias for
`probecoordinate`; supplying both is an error. Solvent, `dt`, box override,
and self-removal settings are mapped when active.

Warnings identify inactive probe/solvent/box options and historical
`begintime`/`endtime`, which the old parser did not apply. Unknown sections,
unknown options, conflicting aliases, missing required fields, and values
rejected by the v2 schema stop migration before a project directory is made.
Review warnings and validate the result before using it. The v2 scientific
engine is not yet available, so migration cannot certify numerical equivalence
with historical results.
