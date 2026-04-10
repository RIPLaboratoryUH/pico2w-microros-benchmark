# pico2w-microros-benchmark

Reproducibility repository for the IEEE conference paper:

> **Effectiveness of micro-ROS over WiFi**  
> M. Ciaravino  
> Department of Engineering, University of Hawaiʻi  
> Advisor: Dr. A. Trimble

---

## Overview

This repository contains all code and data needed to reproduce the
benchmark experiment described in the paper. Four communication
configurations were evaluated between a host PC and a
Raspberry Pi Pico 2W:

| Configuration | Transport | Framework |
|---|---|---|
| Serial, ad-hoc | UART | Custom Python script |
| WiFi, ad-hoc | UDP | Custom Python script |
| Serial, micro-ROS | UART + XRCE-DDS | micro-ROS |
| WiFi, micro-ROS | UDP + XRCE-DDS | micro-ROS |

Each configuration was run at **1, 10, and 100 Hz** for
**1,000 request-reply cycles per run**, repeated **10 times**,
yielding 154,000 total records.

---

## Hardware

| Component | Device |
|---|---|
| Router | Netgear Nighthawk RAX10 (WiFi 6, 802.11ax) |
| Host PC | Ubuntu 24.04.2 LTS, Intel Core i3-7020U |
| Microcontroller | Raspberry Pi Pico 2W (RP2350) |
| Sensor | ADS1115 analog-to-digital converter |

**Wiring (Pico 2W ↔ ADS1115):**

| Pico 2W Pin | ADS1115 Pin |
|---|---|
| 3.3V | VDD |
| GND | GND |
| GP4 (SDA) | SDA |
| GP5 (SCL) | SCL |

---

## Repository Structure

```
├── PicoFirmware/                  # MicroPython files for ad-hoc configs
│                                  # Drop onto Pico via Thonny
│
├── SerialMircorosBestEffort/      # Full build folder for serial micro-ROS
│                                  # Modify and build before flashing
│
├── WifiMicrorosBestEffort/        # Full build folder for WiFi micro-ROS
│                                  # Modify and build before flashing
│
├── data/                          # Raw experiment data (154 CSV files)
│
├── serial_adhoc_runner.py         # Host runner — serial, ad-hoc
├── wifi_adhoc_runner.py           # Host runner — WiFi, ad-hoc
├── serial_microros_besteffort_runner.py   # Host runner — serial, micro-ROS
├── wifi_microros_besteffort_runner.py     # Host runner — WiFi, micro-ROS
│
├── explore_stats.py               # Computes summary statistics from data/
├── generate_plots.py              # Generates all paper figures
└── requirements.txt               # Python dependencies
```

---

## Requirements

### Software (host PC)
- Ubuntu 24.04 LTS (or compatible Linux)
- ROS 2 Jazzy installed and sourced
- micro-ROS agent (for micro-ROS configs only)
- Python 3.10+
- Thonny IDE (for flashing ad-hoc Pico firmware)

Install Python dependencies:
```bash
pip install -r requirements.txt
```

---

## Pico Firmware Setup

### Ad-hoc configurations (serial and WiFi)

The Pico runs MicroPython for the ad-hoc configurations.
The firmware files are in `PicoFirmware/`.

1. Open Thonny IDE
2. Connect the Pico 2W via USB
3. Copy the files from `PicoFirmware/` onto the Pico

### micro-ROS configurations (serial and WiFi)

The Pico runs a compiled micro-ROS firmware for these configurations.
The full build folders are included so you can modify and rebuild
for your own hardware setup.

**Before building**, update the relevant source files:

**Serial micro-ROS** (`SerialMircorosBestEffort/`):
- `pico_micro_ros_example.c` — update any pin or topic configuration

**WiFi micro-ROS** (`WifiMicrorosBestEffort/`):
- `pico_micro_ros_example.c` — update any pin or topic configuration
- `udp_transports.h` — update WiFi SSID, password, and agent IP address

For full build instructions see the setup guide:
[mciaravino/pico_microros_wifi](https://github.com/mciaravino/pico_microros_wifi)

Once built, flash the resulting `.uf2` to the Pico:
1. Hold the BOOTSEL button while connecting the Pico via USB
2. It will appear as a mass storage device
3. Drag and drop the `.uf2` file onto it
4. The Pico will reboot automatically

---

## Running the Experiment

### Ad-hoc configurations (no micro-ROS agent needed)

**Serial, ad-hoc:**
```bash
python3 serial_adhoc_runner.py
```

**WiFi, ad-hoc:**
```bash
python3 wifi_adhoc_runner.py
```

### micro-ROS configurations (agent required)

Start the micro-ROS agent in a separate terminal before running
the host script.

**Serial micro-ROS:**
```bash
# Terminal 1 — start the agent
ros2 run micro_ros_agent micro_ros_agent serial --dev /dev/ttyACM0

# Terminal 2 — run the experiment
python3 serial_microros_besteffort_runner.py
```

**WiFi micro-ROS:**
```bash
# Terminal 1 — start the agent
ros2 run micro_ros_agent micro_ros_agent udp4 --port 8888

# Terminal 2 — run the experiment
python3 wifi_microros_besteffort_runner.py
```

### Output

Each runner saves one CSV file per run to the `data/` directory.
Each CSV contains one row per message with columns:
`run`, `config`, `frequency_hz`, `message_index`, `rtt_ms`, `status`

---

## Reproducing Statistics

To reproduce the summary statistics reported in Table II of the paper:

```bash
python3 explore_stats.py
```

This prints median RTT ± 95% CI, P95 RTT ± 95% CI, and delivery
rate ± 95% CI for all configurations and frequencies, computed
across 10 runs per condition using a Student-t confidence interval.

---

## Reproducing Figures

```bash
python3 generate_plots.py --data_dir ./data --out_dir ./outputs
```

Figures are saved to `outputs/` as PNG at 300 DPI. For vector PDF:

```bash
python3 generate_plots.py --data_dir ./data --out_dir ./outputs --ext pdf
```

---

## Data

The `data/` directory contains all 154 raw CSV files from the
experiment (154,000 records total). All statistics and figures
can be reproduced directly from these files without re-running
the experiment.

Reliable QoS data is not included. Best-Effort QoS was found to
be strictly superior in all conditions; see the paper for the
QoS selection rationale.

---

## Notes on Reproducibility

- All experiments were conducted in a single controlled indoor
  environment with no network congestion.
- WiFi performance may differ under different network hardware,
  load, distance, or physical obstacles.
- The ADS1115 operates in continuous conversion mode. At high
  request frequencies the Pico reads the most recently completed
  ADC sample rather than triggering a fresh conversion.
- This experiment used ROS 2 Jazzy. Results may differ on other
  ROS 2 distributions.
- Messages that received no reply were counted as undelivered.
  No replies exceeding 500 ms were observed; all replies arrived
  well under 500 ms or not at all.

---

## License

MIT License. See `LICENSE` for details.