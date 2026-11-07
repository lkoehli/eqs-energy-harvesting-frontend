# Copyright 2026 ETH Zürich. Author: Lucas Köhli.
from pathlib import Path

import pytest

from hbcbench import config
from hbcbench.config import ConfigError, expand

CONFIG_DIR = Path(__file__).resolve().parents[1] / "configs"


def test_range_is_inclusive_and_free_of_float_noise():
    values = expand({"start": 0.01, "stop": 0.30, "step": 0.01}, "a")
    assert len(values) == 30
    assert values[0] == 0.01 and values[-1] == 0.3
    assert values[2] == 0.03  # not 0.030000000000000002


def test_frequency_range():
    values = expand({"start": 1e6, "stop": 21e6, "step": 0.5e6}, "f")
    assert len(values) == 41 and values[-1] == 21e6


@pytest.mark.parametrize("spec", [{"start": 1, "stop": 0, "step": 0.1}, {"start": 0, "stop": 1}])
def test_bad_ranges(spec):
    with pytest.raises(ConfigError):
        expand(spec, "x")


def test_list_and_scalar():
    assert expand([1, 2.5], "x") == [1.0, 2.5]
    assert expand(3, "x") == [3.0]


def minimal(kind="iv", **sweep):
    base = {
        "iv": {
            "kind": "iv",
            "outer": "amplitude",
            "amplitudes_vpp": [0.1, 0.2],
            "frequency_hz": 1e7,
            "current_stop_a": -1e-4,
            "points": 5,
        },
        "hold": {
            "kind": "hold",
            "hold_voltage_v": 0.275,
            "amplitudes_vpp": [0.1, 0.2],
            "frequency_hz": 1e7,
        },
    }[kind]
    base.update(sweep)
    return {"sweep": base}


def test_iv_current_grid():
    cfg = config.parse(minimal())
    assert cfg.kind == "iv"
    for k in range(2):
        assert cfg.sweep.currents_a(k) == pytest.approx([0, -2.5e-5, -5e-5, -7.5e-5, -1e-4])


def test_per_point_current_stop():
    cfg = config.parse(minimal(current_stop_a=[-2e-5, -1e-4]))
    assert cfg.sweep.currents_a(0)[-1] == pytest.approx(-2e-5)
    assert cfg.sweep.currents_a(1)[-1] == pytest.approx(-1e-4)
    with pytest.raises(ConfigError, match="entries"):
        config.parse(minimal(current_stop_a=[-1e-5]))


def test_ascending_only_is_enforced():
    with pytest.raises(ConfigError, match="monotonically"):
        config.parse(minimal("hold", amplitudes_vpp=[0.3, 0.2], ascending_only=True))


def test_unknown_kind_and_mode():
    with pytest.raises(ConfigError):
        config.parse({"sweep": {"kind": "magic"}})
    raw = minimal()
    raw["source"] = {"mode": "usb"}
    with pytest.raises(ConfigError):
        config.parse(raw)


@pytest.mark.parametrize("path", sorted(CONFIG_DIR.glob("*.toml")), ids=lambda p: p.stem)
def test_shipped_configs_parse(path):
    cfg = config.load(path)
    assert cfg.name == path.stem
