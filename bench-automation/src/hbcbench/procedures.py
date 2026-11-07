# Copyright 2026 ETH Zürich. Author: Lucas Köhli.
"""Measurement procedures.

Two procedures cover all automated setups in ``docs/measurement-setups``:

* :func:`run_iv` – for each outer operating point (amplitude or frequency),
  the SMU sweeps its current from open circuit towards short circuit and
  senses the voltage. Setups 1, 5 and 6 (frequency response).
* :func:`run_hold` – the SMU holds a constant voltage (PMIC cold-start
  voltage at the rectifier output, or a storage voltage at the storage pads)
  and measures the current while the input amplitude is stepped. Setups 2, 3
  and 6 (on-body cold-start).
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

import numpy as np

from .analysis import analyze_iv, first_crossing
from .config import HoldSweep, IVSweep, RunConfig
from .instruments import SkipPoint, fmt_hz, fmt_vpp
from .runlog import RunLog


class SMU(Protocol):
    def source_current(self, amps: float, v_compliance: float) -> None: ...
    def source_voltage(self, volts: float, i_compliance: float) -> None: ...
    def set_current(self, amps: float) -> None: ...
    def set_voltage(self, volts: float) -> None: ...
    def set_current_range(self, amps: float | None) -> None: ...
    def set_voltage_range(self, volts: float | None) -> None: ...
    def set_nplc(self, nplc: float) -> None: ...
    def set_remote_sense(self, on: bool) -> None: ...
    def output(self, on: bool) -> None: ...
    def measure_voltage(self) -> float: ...
    def measure_current(self) -> float: ...


class Source(Protocol):
    remote: bool

    def configure_sine(self, frequency_hz: float, amplitude_vpp: float) -> None: ...
    def set_frequency(self, frequency_hz: float) -> None: ...
    def set_amplitude(self, amplitude_vpp: float) -> None: ...
    def output(self, on: bool) -> None: ...


@dataclass
class Bench:
    smu: SMU
    source: Source
    sleep: Callable[[float], None] = time.sleep
    say: Callable[[str], None] = print
    identities: dict[str, str] = field(default_factory=dict)


def averaged(read: Callable[[], float], n: int, delay_s: float, sleep: Callable) -> float:
    """Mean of ``n`` readings, ignoring overflow/NaN readings."""
    values = []
    for k in range(n):
        values.append(read())
        if delay_s and k < n - 1:
            sleep(delay_s)
    arr = np.asarray(values, dtype=float)
    return float(np.nanmean(arr)) if np.isfinite(arr).any() else math.nan


def _apply_smu_settings(bench: Bench, cfg: RunConfig) -> None:
    bench.smu.set_nplc(cfg.smu.nplc)
    bench.smu.set_remote_sense(cfg.smu.remote_sense)


# --------------------------------------------------------------------------------------
# I–V sweep
# --------------------------------------------------------------------------------------
IV_COLUMNS = ["amplitude_vpp", "frequency_hz", "i_set_a", "v_meas_v", "i_meas_a", "p_harv_w"]
IV_SUMMARY = ["amplitude_vpp", "frequency_hz", "v_oc", "i_sc", "p_mpp", "v_mpp", "r_opt"]


def run_iv(bench: Bench, cfg: RunConfig, log: RunLog) -> dict[str, Any]:
    sw = cfg.sweep
    assert isinstance(sw, IVSweep)
    smu, src = bench.smu, bench.source

    def operating_point(value: float) -> tuple[float, float]:
        if sw.outer == "amplitude":
            return value, sw.fixed_frequency_hz
        return sw.fixed_amplitude_vpp, value

    smu.source_current(0.0, sw.v_compliance_v)
    smu.set_voltage_range(sw.v_compliance_v)
    _apply_smu_settings(bench, cfg)
    smu.output(True)

    first_a, first_f = operating_point(sw.outer_values[0])
    src.configure_sine(first_f, first_a)
    src.output(True)

    measured = skipped = 0
    try:
        for index, value in enumerate(sw.outer_values):
            amp, freq = operating_point(value)
            try:
                if sw.outer == "amplitude":
                    src.set_amplitude(amp)
                else:
                    src.set_frequency(freq)
            except SkipPoint:
                skipped += 1
                log.note(f"skipped {fmt_vpp(amp)} @ {fmt_hz(freq)}")
                continue
            bench.sleep(cfg.source.settle_s)

            v_arr, i_arr = [], []
            for i_set in sw.currents_a(index):
                smu.set_current(i_set)
                bench.sleep(sw.settle_s)
                v = averaged(
                    smu.measure_voltage, cfg.smu.averages, cfg.smu.sample_delay_s, bench.sleep
                )
                i = averaged(
                    smu.measure_current, cfg.smu.averages, cfg.smu.sample_delay_s, bench.sleep
                )
                if math.isnan(v) or math.isnan(i):
                    continue
                v_arr.append(v)
                i_arr.append(-i)
                log.row([amp, freq, i_set, v, i, v * -i])
            smu.set_current(0.0)
            log.flush()

            summary = analyze_iv(np.array(v_arr), np.array(i_arr))
            log.summary({"amplitude_vpp": amp, "frequency_hz": freq, **summary.as_dict()})
            bench.say(f"  {fmt_vpp(amp):>10} @ {fmt_hz(freq):>9}:  {summary.describe()}")
            measured += 1
    finally:
        smu.set_current(0.0)
        smu.output(False)
        src.output(False)

    return {"operating_points": measured, "skipped": skipped}


# --------------------------------------------------------------------------------------
# Constant-voltage (hold) sweep
# --------------------------------------------------------------------------------------
HOLD_COLUMNS = [
    "amplitude_vpp",
    "frequency_hz",
    "v_meas_v",
    "i_meas_a",
    "i_harv_a",
    "p_harv_w",
    "started",
]
HOLD_SUMMARY = ["quantity", "value", "unit"]


def run_hold(bench: Bench, cfg: RunConfig, log: RunLog) -> dict[str, Any]:
    sw = cfg.sweep
    assert isinstance(sw, HoldSweep)
    smu, src = bench.smu, bench.source

    smu.source_voltage(sw.hold_voltage_v, sw.i_compliance_a)
    _apply_smu_settings(bench, cfg)
    if sw.precharge_range_a is not None and sw.precharge_s > 0:
        # Phase 1: a sensitive range alone cannot charge the storage-node
        # capacitance to the set-point, so pre-charge on a higher range first.
        smu.set_current_range(sw.precharge_range_a)
        smu.output(True)
        bench.say(f"Pre-charging to {sw.hold_voltage_v:g} V for {sw.precharge_s:g} s ...")
        bench.sleep(sw.precharge_s)
        smu.set_current_range(sw.current_range_a)  # phase 2: measurement range
    else:
        smu.set_current_range(sw.current_range_a)
        smu.output(True)

    src.configure_sine(sw.frequency_hz, sw.amplitudes_vpp[0])
    src.output(True)

    amps, powers = [], []
    first_start = math.nan
    try:
        for amp in sw.amplitudes_vpp:
            try:
                src.set_amplitude(amp)
            except SkipPoint:
                log.note(f"skipped {fmt_vpp(amp)}")
                continue
            bench.sleep(sw.settle_s)
            v = averaged(smu.measure_voltage, cfg.smu.averages, cfg.smu.sample_delay_s, bench.sleep)
            i = averaged(smu.measure_current, cfg.smu.averages, cfg.smu.sample_delay_s, bench.sleep)
            i_harv = -i
            p = v * i_harv
            started = sw.start_current_a is not None and i_harv >= sw.start_current_a
            if started and math.isnan(first_start):
                first_start = amp
            log.row([amp, sw.frequency_hz, v, i, i_harv, p, int(started)])
            log.flush()
            amps.append(amp)
            powers.append(p)
            flag = "  running" if started else ""
            bench.say(
                f"  {fmt_vpp(amp):>10}:  V {v:.4f} V | I_harv {i_harv * 1e6:8.3f} µA | "
                f"P {p * 1e6:8.3f} µW{flag}"
            )
    finally:
        src.output(False)
        smu.set_voltage(0.0)
        smu.output(False)

    results: dict[str, Any] = {"points": len(amps)}
    for thr in sw.power_thresholds_w:
        x = first_crossing(np.array(amps), np.array(powers), thr)
        key = f"amplitude_at_{thr * 1e6:g}uW_vpp"
        results[key] = x
        log.summary({"quantity": key, "value": x, "unit": "Vpp"})
        bench.say(
            f"  P >= {thr * 1e6:g} µW first reached at {'n/a' if math.isnan(x) else fmt_vpp(x)}"
        )
    if sw.start_current_a is not None:
        results["first_running_amplitude_vpp"] = first_start
        log.summary({"quantity": "first_running_amplitude", "value": first_start, "unit": "Vpp"})
    return results


def run(bench: Bench, cfg: RunConfig, log: RunLog) -> dict[str, Any]:
    if cfg.kind == "iv":
        return run_iv(bench, cfg, log)
    return run_hold(bench, cfg, log)


def columns_for(cfg: RunConfig) -> tuple[list[str], list[str]]:
    return (IV_COLUMNS, IV_SUMMARY) if cfg.kind == "iv" else (HOLD_COLUMNS, HOLD_SUMMARY)
