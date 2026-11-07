# hbcbench: bench automation

Python tooling that runs the automated [measurement setups](../docs/measurement-setups/README.md) with a Keysight B2902A SMU and a Keysight 33600A waveform generator. One TOML file describes one setup. Every run writes plain CSV data plus a JSON sidecar that records the configuration, the instrument IDs, timing and the software version.

## Install

```bash
cd bench-automation
python -m pip install -e ".[visa]"      # add ",dev" for tests and linting
```

Python ≥ 3.11. Instrument access goes through [PyVISA](https://pyvisa.readthedocs.io); either a vendor VISA library (Keysight IO Libraries) or the pure-Python `pyvisa-py` backend works.

## Use

```bash
hbcbench list-resources                               # find the instrument addresses
hbcbench show configs/storage-power-zmpp.toml         # print the sweep plan
hbcbench run  configs/storage-power-zmpp.toml         # measure → ./data/
hbcbench run  configs/onbody-coldstart.toml --simulate --out /tmp/dry-run
```

`--simulate` runs the whole procedure against simulated instruments: no hardware and no prompts. It checks a configuration end to end before a session on the bench. The simulated DUT is a toy model with arbitrary parameters, not a model of the board.

## Procedures

| Kind | What the SMU does | Setups |
|---|---|---|
| `iv` | For each amplitude or frequency, sweeps its current from open circuit towards short circuit and senses voltage. Extracts V_OC, I_SC, P_MPP, V_MPP and R_opt per curve. | [1](../docs/measurement-setups/01-dc-coupled-iv-sweep.md), [5](../docs/measurement-setups/05-floating-ground-sweeps.md), [6](../docs/measurement-setups/06-on-body.md) |
| `hold` | Holds a constant voltage (optionally after a high-range pre-charge) and measures current while the amplitude is stepped. Reports where the power first crosses given thresholds, and when a PMIC start-up is detected. | [2](../docs/measurement-setups/02-rectifier-coldstart-threshold.md), [3](../docs/measurement-setups/03-harvested-power-zmpp.md), [6](../docs/measurement-setups/06-on-body.md#on-body-cold-start) |

**Generator modes.**

- **`remote`:** drives the 33600A over VISA.
- **`manual`:** prompts the operator for every setting. This is required for floating-ground and on-body setups: a USB connection to the generator would bond its earth to the laptop and recreate the DC return path. Answer `s` at a prompt to skip that operating point.

**Safe exit.** On completion, error or Ctrl-C, the SMU returns to 0 and both outputs are switched off. Partial data is kept, and the JSON records the run as `aborted`.

## Output

```
data/
├── 20260512-141503_dc-iv-amplitude-sweep.csv           # every SMU point
├── 20260512-141503_dc-iv-amplitude-sweep_summary.csv   # one row per operating point
└── 20260512-141503_dc-iv-amplitude-sweep.json          # config, instruments, timing, version
```

## Layout

```
src/hbcbench/
├── instruments.py   SCPI drivers: B2902A, Keysight33600A, ManualSource
├── procedures.py    run_iv, run_hold
├── analysis.py      I–V evaluation, threshold crossings
├── config.py        TOML parsing, inclusive range tables
├── runlog.py        CSV + JSON output
├── simulated.py     simulated instruments for dry runs and tests
└── cli.py           hbcbench command
configs/             one file per measurement setup
tests/               pytest, runs without hardware
```

## Origin

This is a restructured version of the per-measurement scripts used during the thesis. The procedures and sweep settings are the same. The changes:

- One shared driver layer instead of a lab-internal SMU wrapper.
- Configuration files instead of constants edited in each script.
- No hard-coded paths.
- Machine-readable output.
- Tests that run without hardware.
