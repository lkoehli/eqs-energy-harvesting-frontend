# Copyright 2026 ETH Zürich. Author: Lucas Köhli.
"""Run configuration: one TOML file per measurement setup.

Sweep values can be given as an explicit list or as a range table
``{ start = ..., stop = ..., step = ... }`` (stop inclusive).
"""

from __future__ import annotations

import math
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class ConfigError(ValueError):
    pass


def expand(spec: Any, name: str) -> list[float]:
    """Expand a list or an inclusive ``{start, stop, step}`` range into floats."""
    if isinstance(spec, (int, float)):
        return [float(spec)]
    if isinstance(spec, list):
        if not spec:
            raise ConfigError(f"{name}: empty list")
        return [float(v) for v in spec]
    if isinstance(spec, dict):
        try:
            start, stop, step = float(spec["start"]), float(spec["stop"]), float(spec["step"])
        except KeyError as e:
            raise ConfigError(f"{name}: range needs start, stop and step") from e
        if step == 0 or (stop - start) / step < 0:
            raise ConfigError(f"{name}: step {step} does not lead from {start} to {stop}")
        n = math.floor((stop - start) / step + 1e-9) + 1
        # Round to suppress float noise (0.1 + 0.2 ...); 12 significant digits is plenty.
        return [float(f"{start + k * step:.12g}") for k in range(n)]
    raise ConfigError(f"{name}: expected a number, a list or a range table")


@dataclass
class SourceConfig:
    mode: str = "remote"  # "remote" (VISA) or "manual" (front panel, floating setups)
    address: str | None = None
    channel: int = 1
    load_ohm: float | str = 50
    settle_s: float = 0.5  # wait after changing amplitude or frequency


@dataclass
class SMUConfig:
    address: str | None = None
    channel: int = 1
    nplc: float = 1.0
    averages: int = 1
    sample_delay_s: float = 0.0
    remote_sense: bool = False


@dataclass
class IVSweep:
    outer: str  # "amplitude" or "frequency"
    outer_values: list[float]
    fixed_frequency_hz: float
    fixed_amplitude_vpp: float
    current_grids_a: list[list[float]]  # one SMU current grid per outer operating point
    settle_s: float
    v_compliance_v: float

    def currents_a(self, index: int) -> list[float]:
        return self.current_grids_a[index]


@dataclass
class HoldSweep:
    hold_voltage_v: float
    amplitudes_vpp: list[float]
    frequency_hz: float
    i_compliance_a: float
    current_range_a: float | None
    settle_s: float
    precharge_range_a: float | None = None
    precharge_s: float = 0.0
    power_thresholds_w: list[float] = field(default_factory=list)
    start_current_a: float | None = None


@dataclass
class RunConfig:
    name: str
    description: str
    dut: dict[str, Any]
    source: SourceConfig
    smu: SMUConfig
    sweep: IVSweep | HoldSweep
    raw: dict[str, Any]

    @property
    def kind(self) -> str:
        return "iv" if isinstance(self.sweep, IVSweep) else "hold"


def load(path: str | Path) -> RunConfig:
    path = Path(path)
    with path.open("rb") as fh:
        raw = tomllib.load(fh)
    return parse(raw, default_name=path.stem)


def parse(raw: dict[str, Any], default_name: str = "run") -> RunConfig:
    run = raw.get("run", {})
    sweep_raw = dict(raw.get("sweep", {}))
    kind = sweep_raw.pop("kind", None)
    if kind == "iv":
        sweep = _parse_iv(sweep_raw)
    elif kind == "hold":
        sweep = _parse_hold(sweep_raw)
    else:
        raise ConfigError(f"[sweep] kind must be 'iv' or 'hold', got {kind!r}")

    source = SourceConfig(**raw.get("source", {}))
    if source.mode not in ("remote", "manual"):
        raise ConfigError(f"[source] mode must be 'remote' or 'manual', got {source.mode!r}")
    smu = SMUConfig(**raw.get("smu", {}))
    if smu.averages < 1:
        raise ConfigError("[smu] averages must be >= 1")

    return RunConfig(
        name=run.get("name", default_name),
        description=run.get("description", ""),
        dut=dict(raw.get("dut", {})),
        source=source,
        smu=smu,
        sweep=sweep,
        raw=raw,
    )


def _parse_iv(s: dict[str, Any]) -> IVSweep:
    outer = s.get("outer")
    if outer == "amplitude":
        values = expand(s["amplitudes_vpp"], "amplitudes_vpp")
        fixed_f, fixed_a = float(s["frequency_hz"]), math.nan
    elif outer == "frequency":
        values = expand(s["frequencies_hz"], "frequencies_hz")
        fixed_f, fixed_a = math.nan, float(s["amplitude_vpp"])
    else:
        raise ConfigError("[sweep] outer must be 'amplitude' or 'frequency'")
    points = int(s.get("points", 50))
    if points < 2:
        raise ConfigError("[sweep] points must be >= 2")
    i0 = float(s.get("current_start_a", 0.0))
    # current_stop_a: one value for all operating points, or a list with one end
    # point per operating point (lets the sweep just pass V = 0 at every amplitude).
    stops = s["current_stop_a"]
    if isinstance(stops, list):
        if len(stops) != len(values):
            raise ConfigError(
                f"[sweep] current_stop_a has {len(stops)} entries, "
                f"but there are {len(values)} operating points"
            )
        stops = [float(x) for x in stops]
    else:
        stops = [float(stops)] * len(values)
    grids = [[i0 + (i1 - i0) * k / (points - 1) for k in range(points)] for i1 in stops]
    return IVSweep(
        outer=outer,
        outer_values=values,
        fixed_frequency_hz=fixed_f,
        fixed_amplitude_vpp=fixed_a,
        current_grids_a=grids,
        settle_s=float(s.get("settle_s", 0.3)),
        v_compliance_v=float(s.get("v_compliance_v", 3.0)),
    )


def _parse_hold(s: dict[str, Any]) -> HoldSweep:
    amps = expand(s["amplitudes_vpp"], "amplitudes_vpp")
    if s.get("ascending_only", False) and any(b <= a for a, b in zip(amps, amps[1:], strict=False)):
        raise ConfigError(
            "amplitudes_vpp must increase monotonically (ascending_only = true): "
            "PMIC cold-start is a one-shot event"
        )
    pre = s.get("precharge")
    return HoldSweep(
        hold_voltage_v=float(s["hold_voltage_v"]),
        amplitudes_vpp=amps,
        frequency_hz=float(s["frequency_hz"]),
        i_compliance_a=float(s.get("i_compliance_a", 10e-3)),
        current_range_a=_opt_float(s.get("current_range_a")),
        settle_s=float(s.get("settle_s", 1.0)),
        precharge_range_a=_opt_float(pre.get("current_range_a")) if pre else None,
        precharge_s=float(pre.get("duration_s", 0.0)) if pre else 0.0,
        power_thresholds_w=[float(x) for x in s.get("power_thresholds_w", [])],
        start_current_a=_opt_float(s.get("start_current_a")),
    )


def _opt_float(x: Any) -> float | None:
    return None if x is None else float(x)
