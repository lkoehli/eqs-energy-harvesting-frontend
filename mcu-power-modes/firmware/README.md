# Power-mode test firmware

`main.c` variants for the NUCLEO-U385RG-Q (STM32U385) that produced the 5 s-cycle recordings in [STM32U3 power-mode measurements](../README.md). Each one alternates 5 s active and 5 s in one low-power mode, indefinitely.

| File | Mode |
|---|---|
| `main_stop1.c` | Stop 1 |
| `main_stop2.c` | Stop 2 |
| `main_stop3.c` | Stop 3 |
| `main_standby.c` | Standby |

## Use

1. Create an STM32CubeIDE / STM32CubeMX project for the NUCLEO-U385RG-Q. It needs:
   - LSE on; RTC enabled with its wake-up timer.
   - USART1 enabled.
   - PA5 and PA8 as push-pull outputs.
   - SMPS supply.
2. Replace `Core/Src/main.c` with the variant for the mode you want to measure.
3. Remove the JP4 (IDD) jumper and connect the PPK2 across it: `VIN` → pin 1, `VOUT` → pin 2, `GND` → board ground.
4. Optionally connect PA8 (Arduino D7 on CN9) to the PPK2's digital input D0 to mark the sleep phases (high while asleep).

## Pins

| Pin | Function |
|---|---|
| PA5 | User LED LD2: on during the active phase. Driven from an MCU pin, so its current is included in the measurement |
| PA8 | Trigger for the PPK2 digital input: low = awake, high = asleep |

## Clock and wake-up

- **Clock:** SYSCLK runs from MSIS on MSIRC0, undivided (96 MHz), in voltage range 1 with the EPOD booster enabled.
- **Wake-up:** the RTC wake-up timer runs from LSE / 16 = 2048 Hz, so 10 240 counts give 5 s.
- **Stop 3 and Standby:** both additionally need RTC wake-up line 7 (`PWR_WAKEUP_SELECT_3`).
- **After Stop 1/2/3:** the firmware calls `SystemClock_Config()` again to restore 96 MHz, then resumes SysTick.

## Changes since the measurements

The files were tidied after the recordings were taken. The code path that runs during a measurement is unchanged:

- **Named constants:** `LED_PIN`, `TRIG_PIN`, `ACTIVE_MS` and `WAKEUP_COUNTS` replace the raw pin numbers, `5000` and `10240`.
- **Comments** are aligned across the four files.
- **Error path:** if arming the RTC wake-up timer fails, SysTick is now resumed before the error blink. Before, `HAL_Delay()` waited forever because SysTick had already been suspended. This only matters when arming fails.
- **Standby:** the wake-up polarity `0` is written as `PWR_WAKEUP_POLARITY_HIGH`, which the HAL defines as `0U`.
- **Stop 3:** a duplicate `HAL_PWR_EnableBkUpAccess()` before `HAL_Init()` was removed. Backup access is still enabled in `SysInit` once the PWR clock is on.

The flag-clearing sequences before entry still differ slightly between the variants, as in the measured firmware.
