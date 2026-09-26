"""Validate the reference corpus, not an unimplemented production kernel."""

from collections.abc import Callable

import numpy as np


def test_analytical_reference(
    field_reference: dict, coulomb_reference: Callable
) -> None:
    positions = np.asarray(field_reference["positions"], dtype=np.float64)
    charges = np.asarray(field_reference["charges"], dtype=np.float64)
    probes = np.asarray(field_reference["probes"], dtype=np.float64)
    expected = np.asarray(field_reference["expected_fields"], dtype=np.float64)

    assert positions.shape == (charges.size, 3)
    assert probes.shape == expected.shape
    assert probes.shape[1] == 3
    for values in (positions, charges, probes, expected):
        assert np.isfinite(values).all()

    actual = [
        coulomb_reference(
            field_reference["positions"], field_reference["charges"], probe
        )
        for probe in field_reference["probes"]
    ]
    # This budget covers decimal-to-float serialization, not backend accuracy.
    np.testing.assert_allclose(actual, expected, rtol=1e-14, atol=1e-12)


def test_recorded_summary_is_consistent(historical_summary: dict) -> None:
    record = historical_summary
    fields = np.tile(
        record["field_at_every_frame"], (record["frame_count"], 1)
    )
    assert len(record["times"]) == fields.shape[0]
    assert np.all(np.diff(record["times"]) > 0)
    assert record["columns"] == ["magnitude", "x", "y", "z"]
    np.testing.assert_allclose(
        fields.mean(axis=0), record["mean"], rtol=0, atol=1e-12
    )
    np.testing.assert_allclose(
        fields.std(axis=0, ddof=record["ddof"]),
        record["standard_deviation"],
        rtol=0,
        atol=1e-12,
    )

    # Both magnitudes and vector components were printed independently.
    # Reverse triangle inequality bounds the norm error by sqrt(3)*half_quantum.
    half_quantum = 0.5 * 10 ** -record["printed_decimal_places"]
    np.testing.assert_allclose(
        np.linalg.norm(fields[:, 1:], axis=1),
        fields[:, 0],
        rtol=0,
        atol=(1 + np.sqrt(3)) * half_quantum,
    )
