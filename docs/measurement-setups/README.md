# Measurement setups

How the frontend was characterized, from controlled bench conditions to the human body. Each page describes one setup: what it measures, how it is wired, the sweep parameters, the procedure and its pitfalls. Where a setup is automated, the matching [bench configuration](../../bench-automation/configs) is linked.

| # | Setup | Characterizes | Ground handling | Automation |
|---|---|---|---|---|
| 1 | [DC-coupled I–V sweep](01-dc-coupled-iv-sweep.md) | Rectifier output I–V / P–V vs input amplitude | DC-coupled | `dc-iv-amplitude-sweep.toml` |
| 2 | [Rectifier cold-start threshold](02-rectifier-coldstart-threshold.md) | Input amplitude at which a doubler meets the PMIC cold-start condition | DC-coupled | `rectifier-coldstart-threshold.toml` |
| 3 | [Harvested power vs R_ZMPP](03-harvested-power-zmpp.md) | Power delivered into storage by the full chain | DC-coupled | `storage-power-zmpp.toml` |
| 4 | [Input impedance (VNA)](04-input-impedance-vna.md) | S11 / Z_in of each doubler vs frequency and load | DC-coupled | VNA software |
| 5 | [Floating-ground sweeps](05-floating-ground-sweeps.md) | Amplitude and frequency response with a capacitive return path, plus repeatability | Floating | `floating-*.toml` |
| 6 | [On-body measurements](06-on-body.md) | Forearm and arm-to-leg channels, indoors and outdoors; on-body cold-start | Floating | `onbody-*.toml` |

## Instruments

| Instrument | Model | Used for |
|---|---|---|
| Waveform generator | Keysight 33600A series | Sine source, 50 Ω output, amplitudes in Vpp into a 50 Ω load setting |
| Source/measure unit | Keysight B2902A | I–V sweeps (current source, voltage sense) and constant-voltage loads |
| Vector network analyzer | PicoVNA 108 | One-port S11 |
| Battery power station | EcoFlow (portable) | Powers the SMU (and the generator outdoors) without an earth connection |
| Laptop | on battery | Runs the SMU over USB without bonding it to mains earth |

## Conventions

**SMU sign convention (B2902A).** Positive current means the SMU sources current *into* the DUT. When the DUT harvests, the SMU sinks current, so the measured current is negative. All scripts report harvested current as `I_harv = −I_meas` and power as `P = V · I_harv`.

**I–V sweep quantities.** For every operating point the SMU sweeps the output current from 0 (open circuit) towards the short-circuit current while sensing voltage. From each curve:

| Quantity | Definition |
|---|---|
| V_OC | Voltage at zero current |
| I_SC | Linear interpolation between the two sweep points that straddle V = 0 |
| P_MPP, V_MPP | Maximum of P = V · I_harv over the points with V > 0 |
| R_opt | V_MPP / I_harv at the maximum power point |

**Two ground-handling contexts.** How the grounds are connected decides how the circuit returns to the source, so every setup is one of the following:

| Context | Return path | Consequence for the setup |
|---|---|---|
| **DC-coupled** | Generator, board and SMU share ground; the board is earthed through the SMU `F−` terminal | Characterizes a topology in isolation, with no environmental coupling. The generator can be scripted over USB. |
| **Floating** | No DC path between the source side and the board side; the return closes capacitively through the environment | Represents the real operating condition. The SMU and laptop run on battery. **The generator must not be connected over USB**, because that would bond its earth to the laptop. Amplitude and frequency are set by hand. |

**Forward-path model.** Bench setups that emulate the body channel insert the network below between the generator and the board input. It follows Huang et al., "Channel modeling and characterization of EQS capacitive coupling human body communication," MWSCAS 2023.

```mermaid
flowchart LR
    G["Generator"] --- P["10 kΩ ∥ 500 pF<br/>(skin)"] --- R["200 Ω<br/>(body)"] --- B["Board input SMA"]
```

**What is not in this repository yet.** The measured data and plots feed into a publication in preparation (expected early 2027) and will be added afterwards. In brief: on the body, the frontend harvests power at the microwatt level and cold-starts unaided from a depleted storage element.
