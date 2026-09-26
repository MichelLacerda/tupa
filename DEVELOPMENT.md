# TUPÃ 2.0 Development

Requires Python >=3.13 and uv. New code lives in `src/tupa`; legacy files
serve only as references and are excluded from the distribution and new test suite.
The CLI is still the initial scaffold; TOML configuration and scientific
calculations will be implemented in subsequent tasks.

Write all new files, documentation, comments, and user-facing messages in English.

## Environment and checks

```bash
uv sync --locked
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pytest
uv build
```

`pyproject.toml` contains the tool configuration. The new test suite currently
lives in `tests/integration`; add new test directories to `testpaths`, Ruff's
file selection, and the sdist configuration when creating them.
The tests check installation and imports; they do not yet validate scientific results.

Pydantic 2 will validate TOML input read with `tomllib`. Internal data will use
dataclasses and NumPy/CuPy arrays, with explicit scientific validation.
The default installation uses the CPU and does not depend on CuPy.

## Distribution and CI

Hatchling generates the sdist and wheel from explicitly selected files.
`uv build` builds the wheel from the sdist, checking that the source distribution
contains the required files. The existing license is included in the artifacts.

The `.github/workflows/ci.yml` workflow checks Python 3.13 and 3.14 on Linux
using dependencies from the lockfile. After checking the source checkout, it
replaces the editable installation with the wheel and runs the installation
tests from an external directory. The workflow does not publish packages.

The external tests use Python's isolated mode and block imports of legacy
modules, so accidental dependencies on those modules cause the tests to fail.

Configuration references:
[Hatch](https://hatch.pypa.io/latest/config/build/),
[pytest](https://docs.pytest.org/en/stable/reference/customize.html),
[Ruff](https://docs.astral.sh/ruff/configuration/), and
[uv in GitHub Actions](https://docs.astral.sh/uv/guides/integration/github/).
