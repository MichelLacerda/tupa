"""Check the installed package from outside the source checkout."""

import subprocess
import sys
from pathlib import Path


def test_entry_point_without_legacy_modules(tmp_path: Path) -> None:
    script = """
import importlib.abc
from importlib.metadata import distribution
import sys

class BlockLegacy(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'lib', 'TUPA', 'pyTUPAmol'}:
            raise ImportError(f'Legacy dependency: {fullname}')

sys.meta_path.insert(0, BlockLegacy())
package = distribution('tupa')
entry_points = [
    entry for entry in package.entry_points
    if entry.group == 'console_scripts' and entry.name == 'tupa'
]
assert len(entry_points) == 1, entry_points
sys.argv = ['tupa', '--help']
entry_points[0].load()()
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", script],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_cpu_dependencies_import_without_gpu(tmp_path: Path) -> None:
    script = """
import importlib.abc
import importlib
import sys

class BlockGPU(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] == 'cupy':
            raise ModuleNotFoundError('GPU is not installed', name=fullname)

sys.meta_path.insert(0, BlockGPU())
for name in ('numpy', 'MDAnalysis', 'pydantic', 'rich', 'typer', 'tupa'):
    importlib.import_module(name)
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", script],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
