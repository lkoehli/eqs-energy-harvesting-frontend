# Copyright 2026 ETH Zürich. Author: Lucas Köhli.
import csv
import json
from pathlib import Path

import pytest

from hbcbench import cli, config
from hbcbench.instruments import ManualSource
from hbcbench.procedures import Bench, columns_for, run
from hbcbench.runlog import RunLog
from hbcbench.simulated import SimulatedSMU, SimulatedSource, ToyHarvester

CONFIG_DIR = Path(__file__).resolve().parents[1] / "configs"


def bench(storage=False, source=None):
    dut = ToyHarvester()
    return Bench(
        SimulatedSMU(dut, storage_node=storage),
        source or SimulatedSource(dut),
        sleep=lambda s: None,
        say=lambda m: None,
    ), dut


def new_log(tmp_path, cfg):
    cols, summ = columns_for(cfg)
    return RunLog(tmp_path, cfg.name, cols, summ, {"name": cfg.name})


def read(path):
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


def test_iv_amplitude_sweep_writes_curves_and_summary(tmp_path):
    cfg = config.parse(
        {
            "sweep": {
                "kind": "iv",
                "outer": "amplitude",
                "amplitudes_vpp": [0.2, 0.5],
                "frequency_hz": 10e6,
                "current_stop_a": -400e-6,
                "points": 41,
            }
        }
    )
    b, dut = bench()
    log = new_log(tmp_path, cfg)
    result = run(b, cfg, log)
    log.finish("completed", result)

    assert result == {"operating_points": 2, "skipped": 0}
    assert len(read(log.data_path)) == 2 * 41
    summary = read(log.summary_path)
    assert [float(r["amplitude_vpp"]) for r in summary] == [0.2, 0.5]
    # Toy model is a Thevenin source: P_MPP ≈ V_OC² / 4R
    v_oc = float(summary[1]["v_oc"])
    assert float(summary[1]["p_mpp"]) == pytest.approx(v_oc**2 / (4 * dut.r_source_ohm), rel=0.02)
    assert float(summary[1]["r_opt"]) == pytest.approx(dut.r_source_ohm, rel=0.1)
    assert not b.smu.on  # outputs switched off at the end


def test_manual_source_skip_is_logged(tmp_path):
    cfg = config.parse(
        {
            "source": {"mode": "manual"},
            "sweep": {
                "kind": "iv",
                "outer": "frequency",
                "frequencies_hz": [5e6, 10e6, 15e6],
                "amplitude_vpp": 1.2,
                "current_stop_a": -1e-4,
                "points": 5,
            },
        }
    )
    answers = iter(["", "", "", "s", ""])  # configure, output on, 5 MHz, skip 10, 15 MHz
    dut = ToyHarvester()
    manual = ManualSource(prompt=lambda m: next(answers, ""), say=lambda m: None)
    b = Bench(SimulatedSMU(dut), manual, sleep=lambda s: None, say=lambda m: None)
    log = new_log(tmp_path, cfg)
    result = run(b, cfg, log)
    log.finish("completed", result)
    assert result["skipped"] == 1
    assert len(read(log.summary_path)) == 2
    assert "10 MHz" in json.loads(log.meta_path.read_text())["notes"][0]


def test_hold_sweep_finds_power_threshold(tmp_path):
    cfg = config.parse(
        {
            "sweep": {
                "kind": "hold",
                "hold_voltage_v": 0.275,
                "amplitudes_vpp": {"start": 0.05, "stop": 0.5, "step": 0.01},
                "frequency_hz": 10e6,
                "power_thresholds_w": [3e-6],
            }
        }
    )
    b, _ = bench()
    log = new_log(tmp_path, cfg)
    result = run(b, cfg, log)
    log.finish("completed", result)
    x = result["amplitude_at_3uW_vpp"]
    assert 0.05 < x < 0.5
    rows = read(log.data_path)
    p = [float(r["p_harv_w"]) for r in rows]
    a = [float(r["amplitude_vpp"]) for r in rows]
    below = [pi for ai, pi in zip(a, p, strict=True) if ai < x]
    above = [pi for ai, pi in zip(a, p, strict=True) if ai > x]
    assert max(below) < 3e-6 <= min(above)


def test_hold_sweep_flags_pmic_start_with_precharge(tmp_path):
    cfg = config.parse(
        {
            "sweep": {
                "kind": "hold",
                "hold_voltage_v": 2.2,
                "amplitudes_vpp": {"start": 0.6, "stop": 1.5, "step": 0.3},
                "ascending_only": True,
                "frequency_hz": 10e6,
                "precharge": {"current_range_a": 10e-3, "duration_s": 4},
                "current_range_a": 100e-6,
                "start_current_a": 0.5e-6,
            }
        }
    )
    b, dut = bench(storage=True)
    log = new_log(tmp_path, cfg)
    result = run(b, cfg, log)
    log.finish("completed", result)
    assert result["first_running_amplitude_vpp"] == pytest.approx(0.9)  # toy start-up at 0.9 Vpp
    started = [int(r["started"]) for r in read(log.data_path)]
    assert started == [0, 1, 1, 1]


@pytest.mark.parametrize("path", sorted(CONFIG_DIR.glob("*.toml")), ids=lambda p: p.stem)
def test_every_shipped_config_runs_simulated(path, tmp_path, capsys):
    assert cli.main(["run", str(path), "--simulate", "--out", str(tmp_path)]) == 0
    meta = json.loads(next(tmp_path.glob("*.json")).read_text())
    assert meta["status"] == "completed" and meta["simulated"] is True
    assert meta["rows"] > 0
    for f in meta["files"].values():
        assert (tmp_path / f).exists()
