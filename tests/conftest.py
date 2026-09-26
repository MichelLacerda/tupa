"""Independent reference data for the new test suites."""

import json
from collections.abc import Callable
from copy import deepcopy
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"

# Keep explicit `pytest tests` runs from collecting the legacy executable test.
collect_ignore = ["test_run.py"]


def _load_reference(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


_CASES = _load_reference("electrostatics.json")["cases"]


@pytest.fixture(params=_CASES, ids=lambda case: case["id"])
def field_reference(request: pytest.FixtureRequest) -> dict:
    # Return fresh data so mutations in one test cannot affect another.
    return deepcopy(request.param)


@pytest.fixture
def historical_summary() -> dict:
    return _load_reference("historical_summary.json")


@pytest.fixture
def coulomb_reference() -> Callable:
    """Scalar Decimal oracle for tiny, nonperiodic test systems only."""

    def compute(positions: list, charges: list, probe: list) -> tuple:
        with localcontext() as context:
            context.prec = 50
            # Recorded scientific conventions, not imported from production.
            k = Decimal("8987551792.261173")
            elementary_charge = Decimal("1.60217733e-19")
            angstrom_to_meter = Decimal("1e-10")
            si_to_mv_per_cm = Decimal("1e-8")
            total = [Decimal(0), Decimal(0), Decimal(0)]
            for position, charge in zip(positions, charges, strict=True):
                displacement = [
                    (Decimal(str(p)) - Decimal(str(a))) * angstrom_to_meter
                    for p, a in zip(probe, position, strict=True)
                ]
                distance_squared = sum(d * d for d in displacement)
                if distance_squared == 0:
                    raise ValueError("Coincident probe and charge")
                rounded_charge = Decimal(str(charge)).quantize(
                    Decimal("0.000001"), rounding=ROUND_HALF_EVEN
                )
                factor = (
                    k
                    * elementary_charge
                    * rounded_charge
                    * si_to_mv_per_cm
                    / (distance_squared * distance_squared.sqrt())
                )
                for axis, delta in enumerate(displacement):
                    total[axis] += factor * delta
            return tuple(float(value) for value in total)

    return compute
