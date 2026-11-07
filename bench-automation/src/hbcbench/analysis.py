# Copyright 2026 ETH Zürich. Author: Lucas Köhli.
"""Evaluation of I–V sweeps and threshold sweeps.

All functions take the *harvested* current, i.e. positive when the DUT
delivers current (``i_harv = -i_measured`` with the SMU sign convention).
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import numpy as np


@dataclass(frozen=True)
class IVSummary:
    v_oc: float  # [V]   voltage at the sweep point closest to zero current
    i_sc: float  # [A]   current at V = 0, linearly interpolated
    p_mpp: float  # [W]  maximum power over points with V > 0
    v_mpp: float  # [V]
    r_opt: float  # [Ω]  V_MPP / I_MPP

    def as_dict(self) -> dict[str, float]:
        return asdict(self)

    def describe(self) -> str:
        def f(x: float, scale: float, unit: str, fmt: str = ".2f") -> str:
            return "n/a" if math.isnan(x) else f"{x * scale:{fmt}} {unit}"

        return (
            f"V_OC {f(self.v_oc, 1, 'V', '.3f')} | I_SC {f(self.i_sc, 1e6, 'µA')} | "
            f"P_MPP {f(self.p_mpp, 1e6, 'µW')} @ {f(self.v_mpp, 1, 'V', '.3f')} | "
            f"R_opt {f(self.r_opt, 1e-3, 'kΩ')}"
        )


NAN_SUMMARY = IVSummary(math.nan, math.nan, math.nan, math.nan, math.nan)


def analyze_iv(v: np.ndarray, i_harv: np.ndarray) -> IVSummary:
    """Extract V_OC, I_SC, P_MPP, V_MPP and R_opt from one I–V sweep.

    The sweep is expected to start near open circuit (zero current) and move
    towards short circuit, as the SMU current sweep does.
    """
    v = np.asarray(v, dtype=float)
    i = np.asarray(i_harv, dtype=float)
    ok = np.isfinite(v) & np.isfinite(i)
    v, i = v[ok], i[ok]
    if v.size == 0:
        return NAN_SUMMARY

    v_oc = float(v[np.argmin(np.abs(i))])
    i_sc = _interp_at_zero_voltage(v, i)

    p = v * i
    candidates = np.flatnonzero(v > 0)
    if candidates.size == 0:
        return IVSummary(v_oc, i_sc, math.nan, math.nan, math.nan)
    k = int(candidates[np.argmax(p[candidates])])
    p_mpp, v_mpp, i_mpp = float(p[k]), float(v[k]), float(i[k])
    r_opt = v_mpp / i_mpp if i_mpp > 0 else math.inf
    return IVSummary(v_oc, i_sc, p_mpp, v_mpp, r_opt)


def _interp_at_zero_voltage(v: np.ndarray, i: np.ndarray) -> float:
    """Current where V first crosses from >= 0 to < 0 (linear interpolation)."""
    crossings = np.flatnonzero((v[:-1] >= 0) & (v[1:] < 0))
    if crossings.size == 0:
        return math.nan
    k = int(crossings[0])
    v_a, v_b, i_a, i_b = v[k], v[k + 1], i[k], i[k + 1]
    return float(i_a + (i_b - i_a) * v_a / (v_a - v_b))


def first_crossing(x: np.ndarray, y: np.ndarray, threshold: float) -> float:
    """x at which y first rises to ``threshold`` (linear interpolation).

    Returns ``nan`` if y never reaches the threshold, and ``x[0]`` if it is
    already above it at the first point.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    above = np.flatnonzero(y >= threshold)
    if above.size == 0:
        return math.nan
    k = int(above[0])
    if k == 0:
        return float(x[0])
    x_a, x_b, y_a, y_b = x[k - 1], x[k], y[k - 1], y[k]
    if not np.isfinite(y_a) or y_b == y_a:
        return float(x_b)
    return float(x_a + (x_b - x_a) * (threshold - y_a) / (y_b - y_a))
