# Scientific reference data

These files are new, independent test assets. No legacy program, configuration,
topology, or trajectory is imported, copied, or executed by the new tests.

## Analytical cases

`electrostatics.json` describes tiny nonperiodic systems in angstroms,
elementary charges, and MV/cm. It contains positive and negative charges,
vector cancellation, dipole addition, inverse-square scaling, zero charge,
six-decimal charge rounding, multiple probes, and a diagonal field.

Expected values are stored explicitly. They follow Coulomb's law with the
constants recorded during the initial audit:

- `k = 8987551792.261173 N m²/C²`.
- `e = 1.60217733e-19 C`.
- `1 angstrom = 1e-10 m`; convert N/C to MV/cm by multiplying by `1e-8`.
- Round partial charges to six decimal places before converting to coulombs.

For unit charge at unit distance the resulting scale is
`K = 1439.965173376172081980809 MV/cm`. A positive charge at `(1, 0, 0)`
produces `(-K, 0, 0)` at the origin. Reversing the charge reverses the field;
doubling the distance divides its magnitude by four. Symmetric equal charges
cancel, whereas opposite charges on opposite sides add. The diagonal case
has components `K / (100 * sqrt(2))` for a charge of `2e` at the origin and
a probe at `(10, 10, 0)`.

A scalar oracle in `tests/conftest.py` independently evaluates the formula
using 50-digit Decimal arithmetic. It is test support for small systems, not
a production kernel or a proposed performance implementation. The charge
rounding example deliberately avoids halfway cases, whose binary-float
behavior needs separate characterization.

The corpus check uses `rtol=1e-14` and `atol=1e-12 MV/cm` to allow the final
conversion of the decimal references into JSON/binary float64 values. These
are not yet CPU/GPU or float32 acceptance tolerances.

## Historical observation

`historical_summary.json` transcribes the ten-frame observation recorded in
the initial audit. It records software versions, execution conditions, units,
times, the repeated field row, mean, and population standard deviation.
The named original files document provenance only; they are not dependencies.

This is a summary observation, not a replacement copy of the original system.
The diagonal analytical case is independently constructed and has a similar
field scale; it does not recreate the historical topology. Differences in
the last printed digit must not be treated as a failure of Coulomb's law:
the historical computation used mixed precision before printing six decimals.

The summary consistency check accounts for independent rounding of magnitude
and vector components. Its absolute error bound is
`(1 + sqrt(3)) * 0.5e-6 MV/cm`, from the reverse triangle inequality.

## Scope and next steps

These checks validate the integrity of the reference data. They do not claim
that TUPÃ 2.0 can calculate fields yet. When the new NumPy kernel is implemented,
reuse the analytical inputs and fixed expected outputs to test it directly.
Do not generate expected values by calling the production implementation.

PBC, cutoff, residue selection, probe modes, self-exclusion, singularities,
bond projections, and GPU tolerances require additional cases in the scientific
characterization task. They are not covered by this minimal reference set.
