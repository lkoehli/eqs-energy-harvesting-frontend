# Copyright 2026 ETH Zürich. Author: Lucas Köhli.
import math

import numpy as np
import pytest

from hbcbench.analysis import analyze_iv, first_crossing


def thevenin_sweep(v_oc=1.2, r=5e3, i_max_factor=1.5, n=301):
    i_sc = v_oc / r
    i = np.linspace(0, i_max_factor * i_sc, n)
    return v_oc - r * i, i


def test_thevenin_source_matches_closed_form():
    v_oc, r = 1.2, 5e3
    v, i = thevenin_sweep(v_oc, r)
    s = analyze_iv(v, i)
    assert s.v_oc == pytest.approx(v_oc)
    assert s.i_sc == pytest.approx(v_oc / r, rel=1e-9)  # linear → interpolation is exact
    assert s.p_mpp == pytest.approx(v_oc**2 / (4 * r), rel=1e-3)
    assert s.v_mpp == pytest.approx(v_oc / 2, rel=1e-2)
    assert s.r_opt == pytest.approx(r, rel=2e-2)


def test_isc_is_nan_when_sweep_never_reaches_zero_volts():
    v, i = thevenin_sweep(i_max_factor=0.5)
    s = analyze_iv(v, i)
    assert math.isnan(s.i_sc)
    assert s.p_mpp > 0


def test_nan_readings_are_ignored():
    v, i = thevenin_sweep()
    v[10] = np.nan
    i[20] = np.nan
    s = analyze_iv(v, i)
    assert s.p_mpp == pytest.approx(1.2**2 / (4 * 5e3), rel=1e-3)


def test_no_positive_voltage_gives_nan_mpp():
    s = analyze_iv(np.array([-0.1, -0.2]), np.array([0.0, 1e-6]))
    assert math.isnan(s.p_mpp) and math.isnan(s.r_opt)


def test_empty_input():
    assert math.isnan(analyze_iv(np.array([]), np.array([])).v_oc)


def test_first_crossing_interpolates():
    x = np.array([0.1, 0.2, 0.3, 0.4])
    y = np.array([0.0, 1.0, 3.0, 5.0])
    assert first_crossing(x, y, 2.0) == pytest.approx(0.25)
    assert first_crossing(x, y, 0.0) == pytest.approx(0.1)
    assert math.isnan(first_crossing(x, y, 10.0))
