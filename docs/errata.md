# Errata: rev 1.0

Hardware issues found during bring-up and characterization of the rev 1.0 board.

| ID | Issue | Rev 1.0 workaround | Schematic | Layout |
|---|---|---|---|---|
| [HW-1](#hw-1) | MAX5395 reference terminal on GND instead of `SRC` | Bodge wire, or fixed R_ZMPP between `ZMPP` and `SRC` | ✅ fixed | ⏳ open |
| [HW-2](#hw-2) | TPS62840 `VOS` tied to GND | Bodge wire | ✅ fixed | ⏳ open |

The corrections are already in the KiCad schematic and in [`schematic.pdf`](../hardware/schematic.pdf) (see the note on the *Energy Management* sheet). The KiCad layout and the Gerbers in [`fabrication/rev1.0`](../hardware/fabrication/rev1.0) still match the board as fabricated.

---

## HW-1

**R_ZMPP wired between `ZMPP` and GND instead of `ZMPP` and `SRC`**

- **Location:** U4 (MAX5395LATA+) pin 1 `L`; U6 (AEM30300) pin 1 `ZMPP` and pin 2 `SRC`.
- **Description:** The `L` terminal of the digital potentiometer is connected to GND. With `W` and `H` tied together at `ZMPP`, the potentiometer acts as a rheostat from `ZMPP` to GND. The AEM30300 datasheet (section 10.1, figure 7) specifies the resistance between `ZMPP` and `SRC`.
- **Impact:** The MPP reference network is in a configuration the datasheet does not cover. The relation between wiper code and MPP set-point does not follow the datasheet equations, so sweeps over wiper settings describe the board as built and cannot be compared directly to datasheet predictions.
- **Rework on rev 1.0:** Cut the trace from U4 pin 1 to GND, then add a bodge wire from U4 pin 1 to `SRC` (easiest at U6 pin 2). For fixed-resistor measurements, connect a discrete R_ZMPP between `ZMPP` and `SRC` instead.
- **Fix:** Route U4 pin 1 to `SRC`. `W` and `H` stay at `ZMPP`.

## HW-2

**TPS62840 `VOS` connected to GND instead of the output node**

- **Location:** U2 (TPS62840) pin 8 `VOS`; L2 / C17 output node.
- **Description:** `VOS` is the regulator's output-sense input. It must connect to the output capacitor after the inductor. On rev 1.0 it is tied to GND.
- **Impact:** The feedback loop senses 0 V regardless of the actual output, so the regulator runs open-loop and cannot produce its VSET-selected 1.8 V. The internal output-discharge function, which also uses `VOS`, is affected as well. The control domain cannot be powered from the harvester as designed.
- **Rework on rev 1.0:** Cut the `VOS` connection to GND and add a short bodge wire from U2 pin 8 to the L2 / C17 node. Keep it away from the `SW` node: `VOS` is high-impedance and noise-sensitive.
- **Fix:** Route `VOS` to the output capacitor C17, away from `SW`.
