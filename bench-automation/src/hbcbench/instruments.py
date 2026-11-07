# Copyright 2026 ETH Zürich. Author: Lucas Köhli.
"""Thin SCPI drivers for the bench instruments.

Only the commands the measurement procedures need are wrapped. Everything goes
through a VISA resource with ``write`` / ``query``, so the drivers can be
tested against a fake resource without hardware.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Protocol

# The B2900 series reports overflow / invalid readings as 9.9e37.
_OVERFLOW_LIMIT = 1e30


class Resource(Protocol):
    def write(self, command: str) -> object: ...
    def query(self, command: str) -> str: ...
    def close(self) -> None: ...


class SkipPoint(Exception):  # noqa: N818  (reads better at call sites than SkipPointError)
    """The operator chose to skip the current operating point."""


def open_resource(address: str, timeout_ms: int = 10_000) -> Resource:
    """Open a VISA resource (requires the optional ``visa`` dependencies)."""
    import pyvisa

    resource = pyvisa.ResourceManager().open_resource(address)
    resource.timeout = timeout_ms
    return resource


def list_resources() -> tuple[str, ...]:
    import pyvisa

    return pyvisa.ResourceManager().list_resources()


def _reading(raw: str) -> float:
    value = float(raw)
    return math.nan if abs(value) > _OVERFLOW_LIMIT else value


def _on_off(on: bool) -> str:
    return "ON" if on else "OFF"


# --------------------------------------------------------------------------------------
# Source / measure unit
# --------------------------------------------------------------------------------------
class B2902A:
    """Keysight B2900-series SMU, single channel.

    Sign convention: a positive current is sourced *into* the DUT. A harvesting
    DUT therefore shows a negative measured current.
    """

    def __init__(self, resource: Resource, channel: int = 1):
        self.res = resource
        self.ch = channel

    def idn(self) -> str:
        return self.res.query("*IDN?").strip()

    def reset(self) -> None:
        self.res.write("*RST")

    # source -----------------------------------------------------------------------
    def source_current(self, amps: float, v_compliance: float) -> None:
        """Force current, sense voltage, with a voltage compliance."""
        c = self.ch
        self.res.write(f":SOUR{c}:FUNC:MODE CURR")
        self.res.write(f":SENS{c}:VOLT:PROT {v_compliance:g}")
        self.set_current(amps)

    def source_voltage(self, volts: float, i_compliance: float) -> None:
        """Force voltage, sense current, with a current compliance."""
        c = self.ch
        self.res.write(f":SOUR{c}:FUNC:MODE VOLT")
        self.res.write(f":SENS{c}:CURR:PROT {i_compliance:g}")
        self.set_voltage(volts)

    def set_current(self, amps: float) -> None:
        self.res.write(f":SOUR{self.ch}:CURR {amps:.6e}")

    def set_voltage(self, volts: float) -> None:
        self.res.write(f":SOUR{self.ch}:VOLT {volts:.6e}")

    # measurement settings ---------------------------------------------------------
    def set_current_range(self, amps: float | None) -> None:
        """Fixed current measurement range, or ``None`` for auto-range."""
        c = self.ch
        if amps is None:
            self.res.write(f":SENS{c}:CURR:RANG:AUTO ON")
        else:
            self.res.write(f":SENS{c}:CURR:RANG:AUTO OFF")
            self.res.write(f":SENS{c}:CURR:RANG {amps:g}")

    def set_voltage_range(self, volts: float | None) -> None:
        c = self.ch
        if volts is None:
            self.res.write(f":SENS{c}:VOLT:RANG:AUTO ON")
        else:
            self.res.write(f":SENS{c}:VOLT:RANG:AUTO OFF")
            self.res.write(f":SENS{c}:VOLT:RANG {volts:g}")

    def set_nplc(self, nplc: float) -> None:
        self.res.write(f":SENS{self.ch}:VOLT:NPLC {nplc:g}")
        self.res.write(f":SENS{self.ch}:CURR:NPLC {nplc:g}")

    def set_remote_sense(self, on: bool) -> None:
        """4-wire (Kelvin) sensing."""
        self.res.write(f":SENS{self.ch}:REM {_on_off(on)}")

    def output(self, on: bool) -> None:
        self.res.write(f":OUTP{self.ch} {_on_off(on)}")

    # spot measurements ------------------------------------------------------------
    def measure_voltage(self) -> float:
        return _reading(self.res.query(f":MEAS:VOLT? (@{self.ch})"))

    def measure_current(self) -> float:
        return _reading(self.res.query(f":MEAS:CURR? (@{self.ch})"))

    def close(self) -> None:
        self.res.close()


# --------------------------------------------------------------------------------------
# Signal sources
# --------------------------------------------------------------------------------------
class Keysight33600A:
    """Keysight 33600A-series waveform generator, sine output.

    Amplitudes are peak-to-peak into the configured load setting (50 Ω by
    default), matching how the generator front panel displays them.
    """

    remote = True

    def __init__(self, resource: Resource, channel: int = 1, load_ohm: float | str = 50):
        self.res = resource
        self.ch = channel
        self.load = load_ohm

    def idn(self) -> str:
        return self.res.query("*IDN?").strip()

    def configure_sine(self, frequency_hz: float, amplitude_vpp: float) -> None:
        c = self.ch
        self.res.write(f"OUTP{c} OFF")
        self.res.write(f"SOUR{c}:FUNC SIN")
        # The load setting changes how the amplitude is interpreted: set it first.
        self.res.write(f"OUTP{c}:LOAD {self.load}")
        self.res.write(f"SOUR{c}:VOLT:UNIT VPP")
        self.res.write(f"SOUR{c}:VOLT:OFFS 0")
        self.set_frequency(frequency_hz)
        self.set_amplitude(amplitude_vpp)

    def set_frequency(self, frequency_hz: float) -> None:
        self.res.write(f"SOUR{self.ch}:FREQ {frequency_hz:.6g}")

    def set_amplitude(self, amplitude_vpp: float) -> None:
        self.res.write(f"SOUR{self.ch}:VOLT {amplitude_vpp:.6g}")

    def output(self, on: bool) -> None:
        self.res.write(f"OUTP{self.ch} {_on_off(on)}")

    def close(self) -> None:
        self.res.close()


def fmt_hz(hz: float) -> str:
    return f"{hz / 1e6:g} MHz" if hz >= 1e6 else f"{hz / 1e3:g} kHz"


def fmt_vpp(vpp: float) -> str:
    return f"{vpp * 1e3:g} mVpp" if vpp < 1 else f"{vpp:g} Vpp"


class ManualSource:
    """Generator operated by hand from its front panel.

    Used for floating-ground and on-body setups: a USB connection to the
    generator would bond its earth to the battery-powered laptop and recreate
    the DC return path the setup is meant to break. Each call prompts the
    operator and waits for confirmation; answering ``s`` raises
    :class:`SkipPoint`.
    """

    remote = False

    def __init__(
        self,
        prompt: Callable[[str], str] = input,
        say: Callable[[str], None] = print,
    ):
        self._prompt = prompt
        self._say = say

    def idn(self) -> str:
        return "manual (front panel)"

    def _ask(self, message: str) -> None:
        answer = self._prompt(f">>> {message}, then press Enter ('s' to skip): ")
        if answer.strip().lower() == "s":
            raise SkipPoint(message)

    def configure_sine(self, frequency_hz: float, amplitude_vpp: float) -> None:
        self._prompt(
            f">>> Configure the generator: sine, offset 0 V, load 50 Ω, "
            f"{fmt_hz(frequency_hz)}, {fmt_vpp(amplitude_vpp)}; press Enter when done: "
        )

    def set_frequency(self, frequency_hz: float) -> None:
        self._ask(f"Set the generator to {fmt_hz(frequency_hz)}")

    def set_amplitude(self, amplitude_vpp: float) -> None:
        self._ask(f"Set the generator to {fmt_vpp(amplitude_vpp)}")

    def output(self, on: bool) -> None:
        if on:
            self._prompt(">>> Turn the generator output ON; press Enter: ")
        else:
            self._say("Remember to turn the generator output OFF.")

    def close(self) -> None:
        pass
