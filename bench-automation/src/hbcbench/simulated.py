# Copyright 2026 ETH Zürich. Author: Lucas Köhli.
"""Simulated instruments for dry runs and tests.

The DUT is a deliberately simple toy model: a Thevenin source whose
open-circuit voltage follows the input amplitude through a resonant gain
curve, plus an optional "PMIC" that latches on above a start-up amplitude.
The parameters are arbitrary and only produce plausible curve shapes. This is
**not** a model of the measured hardware.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass
class ToyHarvester:
    gain_peak: float = 3.0  # open-circuit V per input Vpp at resonance
    f0_hz: float = 10e6
    q: float = 1.0
    v_threshold: float = 0.05  # [V] amplitude lost to the diodes
    r_source_ohm: float = 5e3
    start_vpp: float = 0.9  # "PMIC" start-up amplitude for hold sweeps
    efficiency: float = 0.6
    noise_a: float = 0.0  # RMS current noise added to readings
    seed: int = 0

    amplitude_vpp: float = 0.0
    frequency_hz: float = 10e6
    output_on: bool = False
    pmic_running: bool = False

    def __post_init__(self) -> None:
        self._rng = np.random.default_rng(self.seed)

    def v_oc(self) -> float:
        if not self.output_on or self.frequency_hz <= 0:
            return 0.0
        x = self.frequency_hz / self.f0_hz - self.f0_hz / self.frequency_hz
        gain = self.gain_peak / math.sqrt(1 + (self.q * x) ** 2)
        return max(0.0, gain * self.amplitude_vpp - self.v_threshold)

    def noise(self) -> float:
        return float(self._rng.normal(0, self.noise_a)) if self.noise_a else 0.0


class SimulatedSource:
    remote = True

    def __init__(self, dut: ToyHarvester):
        self.dut = dut

    def idn(self) -> str:
        return "SIMULATED,33600A,0,0"

    def configure_sine(self, frequency_hz: float, amplitude_vpp: float) -> None:
        self.dut.frequency_hz, self.dut.amplitude_vpp = frequency_hz, amplitude_vpp

    def set_frequency(self, frequency_hz: float) -> None:
        self.dut.frequency_hz = frequency_hz

    def set_amplitude(self, amplitude_vpp: float) -> None:
        self.dut.amplitude_vpp = amplitude_vpp
        if self.dut.output_on and amplitude_vpp >= self.dut.start_vpp:
            self.dut.pmic_running = True  # start-up latches, like the real PMIC

    def output(self, on: bool) -> None:
        self.dut.output_on = on

    def close(self) -> None:
        pass


class SimulatedSMU:
    """Behaves like :class:`hbcbench.instruments.B2902A` against the toy DUT.

    In current mode it models the rectifier output (I–V sweeps). In voltage
    mode it models either the rectifier output or, when ``storage_node`` is
    set, the storage pads behind the PMIC.
    """

    def __init__(self, dut: ToyHarvester, storage_node: bool = False):
        self.dut = dut
        self.storage_node = storage_node
        self.mode = "CURR"
        self.level = 0.0
        self.compliance = 3.0
        self.on = False

    def idn(self) -> str:
        return "SIMULATED,B2902A,0,0"

    def source_current(self, amps: float, v_compliance: float) -> None:
        self.mode, self.compliance = "CURR", v_compliance
        self.level = amps

    def source_voltage(self, volts: float, i_compliance: float) -> None:
        self.mode, self.compliance = "VOLT", i_compliance
        self.level = volts

    def set_current(self, amps: float) -> None:
        self.level = amps

    def set_voltage(self, volts: float) -> None:
        self.level = volts

    def set_current_range(self, amps: float | None) -> None:
        pass

    def set_voltage_range(self, volts: float | None) -> None:
        pass

    def set_nplc(self, nplc: float) -> None:
        pass

    def set_remote_sense(self, on: bool) -> None:
        pass

    def output(self, on: bool) -> None:
        self.on = on

    def _operating_point(self) -> tuple[float, float]:
        """(voltage, current into DUT) at the SMU terminals."""
        d = self.dut
        if not self.on:
            return 0.0, 0.0
        if self.mode == "CURR":
            v = d.v_oc() + self.level * d.r_source_ohm
            v = max(-self.compliance, min(self.compliance, v))
            return v, self.level
        v = self.level
        if self.storage_node:
            if not (d.pmic_running and d.output_on):
                return v, 1e-9  # tiny leakage into the pads
            p_avail = d.v_oc() ** 2 / (4 * d.r_source_ohm)
            return v, -d.efficiency * p_avail / max(v, 1e-3)
        i = (v - d.v_oc()) / d.r_source_ohm
        return v, max(-self.compliance, min(self.compliance, i))

    def measure_voltage(self) -> float:
        return self._operating_point()[0]

    def measure_current(self) -> float:
        return self._operating_point()[1] + self.dut.noise()

    def close(self) -> None:
        pass
