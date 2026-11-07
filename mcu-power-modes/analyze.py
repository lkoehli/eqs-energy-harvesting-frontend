# Copyright 2026 ETH Zürich. Author: Lucas Köhli.
"""STM32U3 low-power mode characterization from Nordic PPK2 exports.

Reproduces every number in results/ and every figure in figures/ from the raw
PPK2 CSV exports (Timestamp(ms), Current(uA), D0-D7; 100 kHz). Place the
exports in data/ (plain or .csv.gz), then run:

    python analyze.py            # or: python analyze.py --data path/to/exports
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402

HERE = Path(__file__).resolve().parent
DT_MS = 0.01  # PPK2 sample period at 100 kHz
SUPPLY_V = 3.3  # NUCLEO-U385RG-Q MCU supply (JP4), PPK2 in ampere-meter mode


@dataclass(frozen=True)
class Recording:
    mode: str
    file: str
    threshold_ua: float  # separates the low-power phase from the active loop
    note: str


# Single-shot recordings: one active burst between two low-power phases.
SINGLE = [
    Recording("Sleep", "ppk-20260422T145749.csv", 1500, "single-shot"),
    Recording("Stop 1", "stop1.csv", 1000, "single-shot"),
    Recording("Stop 2", "stop2.csv", 1000, "single-shot"),
    Recording("Standby", "stand-by.csv", 1000, "single-shot, CPU runs with the LED off after wake-up"),
]
# 5 s cycle recordings: 5 s active loop / 5 s low-power mode, same firmware for all three.
CYCLE = [
    Recording("Stop 2", "stop2(5s_cycle).csv", 1000, "5 s cycle"),
    Recording("Stop 3", "stop3(5s_cycle).csv", 1000, "5 s cycle"),
    Recording("Standby", "Stand_by(5s_cycle).csv", 1000, "5 s cycle"),
]

# Colors: categorical slots in fixed order, one per compared mode; neutral for the rest.
COLOR = {"Stop 2": "#2a78d6", "Stop 3": "#eb6834", "Standby": "#1baf7a"}
NEUTRAL = "#8a8984"
INK, INK2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e7e6e2", "#ffffff"
plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Inter", "Segoe UI", "Helvetica", "Arial", "DejaVu Sans"],
    "font.size": 10.5, "axes.edgecolor": "#c9c8c2", "axes.labelcolor": INK2,
    "xtick.color": INK2, "ytick.color": INK2, "axes.grid": True, "grid.color": GRID,
    "grid.linewidth": 0.8, "axes.spines.top": False, "axes.spines.right": False,
    "axes.titlelocation": "left", "axes.titlesize": 12.5, "axes.titleweight": "semibold",
    "axes.titlecolor": INK, "legend.frameon": False, "figure.dpi": 100,
})


# ------------------------------------------------------------------------- loading
def load(data: Path, name: str) -> tuple[np.ndarray, np.ndarray]:
    path = data / name
    if not path.exists() and (data / (name + ".gz")).exists():
        path = data / (name + ".gz")
    df = pd.read_csv(path)
    t = df["Timestamp(ms)"].to_numpy()
    return t - t[0], df["Current(uA)"].to_numpy()


def edges(i: np.ndarray, threshold: float, hold_ms: float = 5.0) -> list[tuple[int, str]]:
    """Debounced threshold crossings: a new state must persist for ``hold_ms``.

    Wake-up transients can chatter across the threshold several times within
    a millisecond; without debouncing they would count as separate events.
    """
    hi = i > threshold
    hold = int(hold_ms / DT_MS)
    out, state, k = [], bool(hi[0]), 0
    while True:
        change = np.flatnonzero(hi[k + 1:] != state)
        if not change.size:
            return out
        j = k + 1 + int(change[0])
        if np.all(hi[j:j + hold] != state):
            out.append((j, "fall" if state else "rise"))
            state = not state
        k = j


def phases(i: np.ndarray, threshold: float):
    """Yield (kind, start, stop) for each low / active phase."""
    e = edges(i, threshold)
    bounds = [0] + [j for j, _ in e] + [len(i)]
    kind = "active" if np.median(i[:100]) > threshold else "low"
    for a, b in zip(bounds[:-1], bounds[1:], strict=True):
        yield kind, a, b
        kind = "low" if kind == "active" else "active"


def core(i, a, b, n, skip_start_ms):
    """Phase samples without the transitions at either end."""
    a2 = a + int(skip_start_ms / DT_MS) if a > 0 else a
    b2 = b - int(1 / DT_MS) if b < n else b
    return i[a2:b2]


# ------------------------------------------------------------------------- metrics
def levels(t, i, rec: Recording) -> dict:
    lows, acts = [], []
    for kind, a, b in phases(i, rec.threshold_ua):
        if kind == "low":
            seg = core(i, a, b, len(i), 50)
            # drop the LED-off running phase after wake-up (single-shot Standby recording)
            lows.append(seg[seg < max(50.0, 20 * np.median(seg))])
        else:
            acts.append(core(i, a, b, len(i), 10))
    low, act = np.concatenate(lows), np.concatenate(acts)
    return {"mode": rec.mode, "recording": rec.file, "note": rec.note,
            "low_mean_uA": low.mean(), "low_median_uA": np.median(low),
            "active_median_uA": np.median(act), "low_time_s": low.size * DT_MS / 1e3}


def wakeups(t, i, rec: Recording, i_low: float) -> list[dict]:
    """Peak, duration and excess charge of every wake-up in a recording.

    Wake-up starts at the first sample above max(50 µA, 20 × sleep current) and
    ends once the current stays within ±5 % of the active level for 1 ms.
    Excess charge is the integral of (I − I_active) over that interval: the
    cost of waking up beyond simply running.
    """
    out = []
    for j, kind in edges(i, rec.threshold_ua):
        if kind != "rise":
            continue
        w0 = max(0, j - int(5 / DT_MS))
        w = i[w0:j + int(20 / DT_MS)]
        act = np.median(i[j + int(50 / DT_MS):j + int(500 / DT_MS)])
        s = int(np.flatnonzero(w > max(50.0, 20 * i_low))[0])
        ok, run = np.abs(w - act) < 0.05 * act, int(1 / DT_MS)
        e = next(k for k in range(s, len(w) - run) if ok[k:k + run].all())
        out.append({"mode": rec.mode, "t_s": t[w0 + s] / 1e3, "peak_uA": w[s:e + run].max(),
                    "duration_ms": (e - s) * DT_MS,
                    "excess_charge_uC": np.sum(w[s:e] - act) * DT_MS * 1e-3,
                    "active_uA": act})
    return out


def led_off_phase(t, i, rec: Recording) -> dict:
    """Phase between wake-up and LED-on in the single-shot Standby recording.

    The CPU runs at 96 MHz with the user LED still off, so its median is an
    estimate of the core run current without the LED.
    """
    s = int(np.flatnonzero(i > 50)[0])
    j = next(k for k, kind in edges(i, rec.threshold_ua) if kind == "rise")
    seg = i[s:j]
    return {"duration_ms": seg.size * DT_MS, "median_uA": np.median(seg[int(5 / DT_MS):]),
            "charge_uC": seg.sum() * DT_MS * 1e-3}


# ------------------------------------------------------------------------- figures
def card(fig, pad=0.012):
    """White rounded card behind the figure, transparent outside (works on dark pages)."""
    fig.patch.set_alpha(0)
    fig.patches.append(FancyBboxPatch((pad, pad), 1 - 2 * pad, 1 - 2 * pad,
                                      boxstyle="round,pad=0,rounding_size=0.025",
                                      transform=fig.transFigure, facecolor=SURFACE,
                                      edgecolor="none", zorder=-10))
    for ax in fig.axes:
        ax.set_facecolor("none")


def save(fig, out: Path):
    card(fig)
    fig.savefig(out, dpi=200, transparent=False, facecolor="none")
    plt.close(fig)


def subtitle(ax, text):
    ax.text(0, 1.02, text, transform=ax.transAxes, color=INK2, fontsize=10, va="bottom")


def fig_ladder(summary: pd.DataFrame, out: Path):
    order = ["Active (96 MHz, LED on)", "Sleep", "Stop 1", "Stop 2", "Stop 3", "Standby"]
    rows = summary.set_index("mode").reindex(order)
    fig, ax = plt.subplots(figsize=(8.8, 3.9))
    fig.subplots_adjust(left=0.235, right=0.95, top=0.78, bottom=0.16)
    y = np.arange(len(order))[::-1]
    for yy, (mode, r) in zip(y, rows.iterrows(), strict=True):
        c = COLOR.get(mode, NEUTRAL)
        v = r["current_uA"]
        ax.plot([0.5, v], [yy, yy], color=GRID, lw=2, zorder=1, solid_capstyle="round")
        ax.scatter([v], [yy], s=90, color=c, zorder=3, edgecolor=SURFACE, linewidth=2)
        label = f"{v / 1000:.2f} mA" if v >= 1000 else f"{v:.3g} µA"
        ax.text(v * 1.35, yy, label, va="center", color=INK, fontsize=10.5,
                fontweight="semibold" if mode in COLOR else "normal")
    ax.set_xscale("log")
    ax.set_xlim(0.5, 2e4)
    ax.set_yticks(y, order)
    ax.tick_params(axis="y", length=0, labelsize=10.5, labelcolor=INK)
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("Current (µA, log scale)")
    ax.set_title("STM32U3 current per power mode", pad=26)
    subtitle(ax, "NUCLEO-U385RG-Q, MCU supply only (3.3 V), Nordic PPK2 at 100 kHz")
    save(fig, out)


def fig_cycle(t, i, out: Path):
    """One full 5 s on / 5 s off cycle (Stop 3), min/max per 1 ms bin."""
    n = int(1 / DT_MS)
    m = len(i) // n
    blk = i[: m * n].reshape(m, n)
    tb = t[: m * n].reshape(m, n)[:, 0] / 1e3
    fig, ax = plt.subplots(figsize=(8.8, 3.4))
    fig.subplots_adjust(left=0.09, right=0.97, top=0.76, bottom=0.17)
    ax.fill_between(tb, np.maximum(blk.min(1), 0.3), blk.max(1), color=COLOR["Stop 3"], alpha=0.25,
                    lw=0)
    ax.plot(tb, blk.mean(1), color=COLOR["Stop 3"], lw=1.6)
    ax.set_yscale("log")
    ax.set_ylim(0.8, 3e4)
    ax.set_xlim(tb[0], tb[-1])
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Current (µA)")
    ax.set_title("Duty cycle: active phase and Stop 3", pad=26)
    subtitle(ax, "5 s active / 5 s Stop 3; band = min–max per 1 ms, line = mean")
    act = np.median(i[i > 1000])
    low = i[i < 50].mean()
    ax.text(2.5, act * 1.6, f"active, 96 MHz + LED ≈ {act / 1000:.2f} mA", ha="center", color=INK)
    ax.text(7.6, low * 2.4, f"Stop 3 ≈ {low:.2f} µA", ha="center", color=INK)
    save(fig, out)


def fig_wakeup(traces: dict, out: Path):
    fig, ax = plt.subplots(figsize=(8.8, 4.0))
    fig.subplots_adjust(left=0.09, right=0.97, top=0.79, bottom=0.15)
    for mode in ["Stop 2", "Stop 3", "Standby"]:
        tw, w, wk = traces[mode]
        ax.plot(tw, w, color=COLOR[mode], lw=1.8,
                label=f"{mode}:  {wk['duration_ms']:.2f} ms,  {wk['excess_charge_uC']:.2f} µC extra")
    ax.set_yscale("log")
    ax.set_ylim(0.5, 3e4)
    ax.set_xlim(-0.5, 1.5)
    ax.axvline(0, color="#c9c8c2", lw=1, ls=(0, (3, 3)))
    ax.set_xlabel("Time from wake-up (ms)")
    ax.set_ylabel("Current (µA)")
    ax.set_title("Wake-up transient", pad=26)
    subtitle(ax, "Standby resets: ~15 mA spike, then boot and full init until the LED turns on")
    ax.legend(loc="lower right", fontsize=9.5, title="wake-up duration, charge above the active level",
              title_fontsize=9, alignment="left")
    save(fig, out)


def fig_baseline(windows: dict, means: dict, out: Path):
    fig, ax = plt.subplots(figsize=(8.8, 3.6))
    fig.subplots_adjust(left=0.09, right=0.83, top=0.77, bottom=0.16)
    k = int(20 / DT_MS)  # 20 ms moving average
    for mode in ["Stop 2", "Stop 3", "Standby"]:
        tw, w = windows[mode]
        sm = np.convolve(w, np.ones(k) / k, mode="valid")
        ts = tw[k // 2: k // 2 + sm.size]
        ax.plot(ts, sm, color=COLOR[mode], lw=1.8, label=mode)
        ax.text(ts[-1] + 15, sm[-200:].mean(), f"{mode}  {means[mode]:.2f} µA", va="center",
                color=INK, fontsize=9.5)
    ax.set_ylim(0, 6)
    ax.set_xlim(windows["Stop 2"][0][0], windows["Stop 2"][0][-1])
    ax.set_xlabel("Time in low-power mode (ms)")
    ax.set_ylabel("Current (µA)")
    ax.set_title("Low-power floor", pad=26)
    subtitle(ax, "1 s inside each mode, 20 ms moving average; values are the full-phase mean")
    ax.legend(loc="upper left", ncols=3, fontsize=9.5)
    save(fig, out)


EXAMPLE_INIT_MS = 10.0  # illustrative extra application init after a Standby reset


def fig_breakeven(lv: dict, wk: dict, i_run: float, out: Path):
    T = np.logspace(-2, 3, 400)  # sleep interval, s
    fig, ax = plt.subplots(figsize=(8.8, 4.2))
    fig.subplots_adjust(left=0.09, right=0.97, top=0.79, bottom=0.15)
    curves = {}
    for mode in ["Stop 2", "Stop 3", "Standby"]:
        q = wk[mode]
        curves[mode] = lv[mode] + q / T
        ax.plot(T, curves[mode], color=COLOR[mode], lw=1.8, label=mode)
    q_init = i_run * EXAMPLE_INIT_MS * 1e-3  # µA · ms -> µC
    with_init = lv["Standby"] + (wk["Standby"] + q_init) / T
    ax.plot(T, with_init, color=COLOR["Standby"], lw=1.8, ls=(0, (4, 3)),
            label=f"Standby + {EXAMPLE_INIT_MS:g} ms app. init (example)")
    for q_extra, offset in ((0.0, (-62, -30)), (q_init, (0, 26))):
        tb = (wk["Standby"] + q_extra - wk["Stop 3"]) / (lv["Stop 3"] - lv["Standby"])
        yb = lv["Standby"] + (wk["Standby"] + q_extra) / tb
        ax.scatter([tb], [yb], s=40, color=INK, zorder=4, edgecolor=SURFACE, linewidth=1.5)
        ax.annotate(f"Standby beats Stop 3\nafter {tb:.2g} s" if tb < 10 else
                    f"Standby beats Stop 3\nafter {tb:.0f} s", xy=(tb, yb), xytext=offset,
                    textcoords="offset points", ha="center", color=INK, fontsize=9.5,
                    arrowprops={"arrowstyle": "-", "color": INK2, "lw": 0.8})
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_ylim(0.25, 3e4)
    ax.set_xlim(T[0], T[-1])
    ax.set_xlabel("Time between wake-ups (s)")
    ax.set_ylabel("Average current (µA)")
    ax.set_title("Which mode wins for a given wake-up interval?", pad=26)
    subtitle(ax, "Low-power current + wake-up charge spread over the interval (active work excluded)")
    ax.legend(loc="upper right", fontsize=9.5)
    save(fig, out)


# ------------------------------------------------------------------------- main
def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--data", type=Path, default=HERE / "data")
    args = p.parse_args(argv)
    res, figs = HERE / "results", HERE / "figures"
    res.mkdir(exist_ok=True)
    figs.mkdir(exist_ok=True)

    rows, wake_rows, lv, wk, traces, windows = [], [], {}, {}, {}, {}
    for rec in SINGLE + CYCLE:
        t, i = load(args.data, rec.file)
        rows.append(levels(t, i, rec))
    single = pd.DataFrame(rows)

    for rec in CYCLE:
        t, i = load(args.data, rec.file)
        r = single[(single["recording"] == rec.file)].iloc[0]
        lv[rec.mode] = r["low_mean_uA"]
        ws = wakeups(t, i, rec, r["low_median_uA"])
        wake_rows += ws
        wk[rec.mode] = float(np.mean([w["excess_charge_uC"] for w in ws]))
        # aligned wake-up trace (first event)
        j = int(round(ws[0]["t_s"] * 1e3 / DT_MS))
        a = j - int(0.5 / DT_MS)
        traces[rec.mode] = ((np.arange(int(2 / DT_MS)) - int(0.5 / DT_MS)) * DT_MS,
                            np.maximum(i[a:a + int(2 / DT_MS)], 0.5), ws[0])
        # last second before the first wake-up
        windows[rec.mode] = (np.arange(int(1000 / DT_MS)) * DT_MS,
                             i[j - int(1010 / DT_MS):j - int(10 / DT_MS)])
        if rec.mode == "Stop 3":
            fig_cycle(t, i, figs / "duty-cycle.png")

    t, i = load(args.data, "stand-by.csv")
    led_off = led_off_phase(t, i, SINGLE[3])
    i_run = led_off["median_uA"]

    # summary: one value per mode (5 s-cycle recordings where available)
    summary = []
    for mode in ["Sleep", "Stop 1"]:
        r = single[(single["mode"] == mode)].iloc[0]
        summary.append({"mode": mode, "current_uA": r["low_mean_uA"], "source": r["recording"]})
    for mode in ["Stop 2", "Stop 3", "Standby"]:
        r = single[(single["mode"] == mode) & (single["note"] == "5 s cycle")].iloc[0]
        summary.append({"mode": mode, "current_uA": r["low_mean_uA"], "source": r["recording"]})
    act = single[single["note"] == "5 s cycle"]["active_median_uA"].mean()
    summary.insert(0, {"mode": "Active (96 MHz, LED on)", "current_uA": act,
                       "source": "5 s cycle recordings"})
    summary = pd.DataFrame(summary)
    summary["power_uW_at_3V3"] = summary["current_uA"] * SUPPLY_V

    single.round(4).to_csv(res / "levels.csv", index=False)
    pd.DataFrame(wake_rows).round(4).to_csv(res / "wakeups.csv", index=False)
    summary.round(4).to_csv(res / "summary.csv", index=False)
    be = {o: (wk["Standby"] - wk[o]) / (lv[o] - lv["Standby"]) for o in ["Stop 2", "Stop 3"]}
    per_ms = {o: i_run * 1e-3 / (lv[o] - lv["Standby"]) for o in be}  # s per ms of init
    pd.DataFrame([{"versus": o, "break_even_s": be[o], "extra_s_per_ms_of_init": per_ms[o]}
                  for o in be]).round(3).to_csv(res / "break_even.csv", index=False)
    pd.DataFrame([led_off]).round(3).to_csv(res / "led_off_phase.csv", index=False)

    fig_ladder(summary, figs / "mode-ladder.png")
    fig_wakeup(traces, figs / "wakeup-transient.png")
    fig_baseline(windows, lv, figs / "low-power-floor.png")
    fig_breakeven(lv, wk, i_run, figs / "break-even.png")

    print(summary.round(3).to_string(index=False))
    print(pd.DataFrame(wake_rows).round(3).to_string(index=False))
    print("LED-off phase:", {k: round(float(v), 3) for k, v in led_off.items()})
    print("break-even vs Standby (s):", {k: round(float(v), 3) for k, v in be.items()},
          "+ s per ms of init:", {k: round(float(v), 3) for k, v in per_ms.items()})


if __name__ == "__main__":
    main()
