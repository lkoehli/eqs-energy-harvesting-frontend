# Copyright 2026 ETH Zürich. Author: Lucas Köhli.
import math

import pytest

from hbcbench.instruments import B2902A, Keysight33600A, ManualSource, SkipPoint


class FakeResource:
    def __init__(self, replies=None):
        self.writes: list[str] = []
        self.replies = replies or {}

    def write(self, cmd):
        self.writes.append(cmd)

    def query(self, cmd):
        self.writes.append(cmd)
        return self.replies.get(cmd, "0")

    def close(self):
        pass


def test_smu_current_source_commands():
    res = FakeResource()
    B2902A(res, channel=1).source_current(-5e-6, v_compliance=3)
    assert res.writes == [
        ":SOUR1:FUNC:MODE CURR",
        ":SENS1:VOLT:PROT 3",
        ":SOUR1:CURR -5.000000e-06",
    ]


def test_smu_voltage_source_and_fixed_range():
    res = FakeResource()
    smu = B2902A(res, channel=2)
    smu.source_voltage(2.6, i_compliance=0.05)
    smu.set_current_range(100e-6)
    assert res.writes == [
        ":SOUR2:FUNC:MODE VOLT",
        ":SENS2:CURR:PROT 0.05",
        ":SOUR2:VOLT 2.600000e+00",
        ":SENS2:CURR:RANG:AUTO OFF",
        ":SENS2:CURR:RANG 0.0001",
    ]


def test_smu_overflow_reading_becomes_nan():
    res = FakeResource({":MEAS:VOLT? (@1)": "+9.910000E+37", ":MEAS:CURR? (@1)": "-1.5E-06"})
    smu = B2902A(res)
    assert math.isnan(smu.measure_voltage())
    assert smu.measure_current() == pytest.approx(-1.5e-6)


def test_generator_sets_load_before_amplitude():
    res = FakeResource()
    Keysight33600A(res).configure_sine(10e6, 0.1)
    assert res.writes.index("OUTP1:LOAD 50") < res.writes.index("SOUR1:VOLT 0.1")
    assert "SOUR1:VOLT:UNIT VPP" in res.writes and "SOUR1:FREQ 1e+07" in res.writes
    assert res.writes[0] == "OUTP1 OFF"  # never change settings with the output live


def test_manual_source_prompts_and_skips():
    answers = iter(["", "s"])
    prompts = []
    src = ManualSource(prompt=lambda msg: prompts.append(msg) or next(answers), say=lambda m: None)
    src.set_frequency(5e6)
    with pytest.raises(SkipPoint):
        src.set_amplitude(1.2)
    assert "5 MHz" in prompts[0] and "1.2 Vpp" in prompts[1]
