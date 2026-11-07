# Copyright 2026 ETH Zürich. Author: Lucas Köhli.
"""Command-line entry point: ``hbcbench run <config.toml>``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import config as cfgmod
from .instruments import B2902A, Keysight33600A, ManualSource, fmt_hz, fmt_vpp
from .procedures import Bench, columns_for, run
from .runlog import RunLog
from .simulated import SimulatedSMU, SimulatedSource, ToyHarvester


def _plan(cfg: cfgmod.RunConfig) -> str:
    sw = cfg.sweep
    lines = [f"{cfg.name}: {cfg.description}".rstrip(": ")]
    if isinstance(sw, cfgmod.IVSweep):
        vals = sw.outer_values
        fmt = fmt_vpp if sw.outer == "amplitude" else fmt_hz
        fixed = (
            fmt_hz(sw.fixed_frequency_hz)
            if sw.outer == "amplitude"
            else fmt_vpp(sw.fixed_amplitude_vpp)
        )
        lines.append(
            f"  I–V sweep over {sw.outer}: {len(vals)} points, "
            f"{fmt(vals[0])} → {fmt(vals[-1])} at {fixed}"
        )
        grids = sw.current_grids_a
        ends = sorted({g[-1] for g in grids})
        end = (
            f"{ends[0] * 1e6:g} µA"
            if len(ends) == 1
            else (f"{ends[-1] * 1e6:g} … {ends[0] * 1e6:g} µA (per point)")
        )
        lines.append(f"  SMU current {grids[0][0] * 1e6:g} → {end} in {len(grids[0])} steps")
    else:
        a = sw.amplitudes_vpp
        lines.append(
            f"  Hold {sw.hold_voltage_v:g} V, {len(a)} amplitudes "
            f"{fmt_vpp(a[0])} → {fmt_vpp(a[-1])} at {fmt_hz(sw.frequency_hz)}"
        )
        if sw.precharge_range_a:
            lines.append(
                f"  Pre-charge {sw.precharge_s:g} s on the {sw.precharge_range_a * 1e3:g} mA range"
            )
    lines.append(f"  Generator: {cfg.source.mode}")
    return "\n".join(lines)


def _floating_warning(cfg: cfgmod.RunConfig) -> str | None:
    if cfg.source.mode != "manual":
        return None
    return (
        "Floating setup: the generator must NOT be connected over USB, and the SMU "
        "and laptop must run on battery."
    )


def _build_bench(cfg: cfgmod.RunConfig, simulate: bool) -> Bench:
    if simulate:
        dut = ToyHarvester(noise_a=2e-9, seed=1)
        storage = cfg.kind == "hold" and cfg.sweep.hold_voltage_v > 1.0
        smu, src = SimulatedSMU(dut, storage_node=storage), SimulatedSource(dut)
        return Bench(
            smu=smu,
            source=src,
            sleep=lambda s: None,
            identities={"smu": smu.idn(), "source": src.idn()},
        )

    from .instruments import open_resource

    if not cfg.smu.address:
        raise SystemExit("[smu] address is not set (find it with: hbcbench list-resources)")
    smu = B2902A(open_resource(cfg.smu.address), channel=cfg.smu.channel)
    if cfg.source.mode == "remote":
        if not cfg.source.address:
            raise SystemExit("[source] address is not set for a remote generator")
        src = Keysight33600A(
            open_resource(cfg.source.address),
            channel=cfg.source.channel,
            load_ohm=cfg.source.load_ohm,
        )
    else:
        src = ManualSource()
    return Bench(smu=smu, source=src, identities={"smu": smu.idn(), "source": src.idn()})


def cmd_run(args: argparse.Namespace) -> int:
    cfg = cfgmod.load(args.config)
    print(_plan(cfg))
    warning = _floating_warning(cfg)
    if warning and not args.simulate:
        print(f"\n!! {warning}")
    if not (args.yes or args.simulate):
        if input("\nStart? [y/N] ").strip().lower() != "y":
            print("Aborted.")
            return 1

    bench = _build_bench(cfg, args.simulate)
    columns, summary_columns = columns_for(cfg)
    meta = {
        "name": cfg.name,
        "description": cfg.description,
        "dut": cfg.dut,
        "simulated": args.simulate,
        "instruments": bench.identities,
        "config_file": Path(args.config).name,
        "config": cfg.raw,
    }
    log = RunLog(args.out, cfg.name, columns, summary_columns, meta)
    status, results = "aborted", {}
    try:
        results = run(bench, cfg, log)
        status = "completed"
    except KeyboardInterrupt:
        print("\nInterrupted: outputs switched off, partial data kept.")
    finally:
        log.finish(status, results)
    print(f"\nData:     {log.data_path}\nSummary:  {log.summary_path}\nMetadata: {log.meta_path}")
    return 0 if status == "completed" else 2


def cmd_show(args: argparse.Namespace) -> int:
    cfg = cfgmod.load(args.config)
    print(_plan(cfg))
    warning = _floating_warning(cfg)
    if warning:
        print(f"  Note: {warning}")
    return 0


def cmd_list(_: argparse.Namespace) -> int:
    from .instruments import list_resources

    for r in list_resources():
        print(r)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="hbcbench", description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)

    r = sub.add_parser("run", help="run a measurement from a TOML configuration")
    r.add_argument("config")
    r.add_argument("--out", default="data", help="output directory (default: ./data)")
    r.add_argument(
        "--simulate",
        action="store_true",
        help="dry run against simulated instruments (no hardware, no prompts)",
    )
    r.add_argument("-y", "--yes", action="store_true", help="do not ask for confirmation")
    r.set_defaults(func=cmd_run)

    s = sub.add_parser("show", help="print the sweep plan of a configuration")
    s.add_argument("config")
    s.set_defaults(func=cmd_show)

    ls = sub.add_parser("list-resources", help="list VISA instruments")
    ls.set_defaults(func=cmd_list)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
