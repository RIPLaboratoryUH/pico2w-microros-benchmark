# micro-ROS over WiFi — Benchmark Experiment
### Raspberry Pi Pico 2W (RP2350)

Reproducibility repository for the IEEE conference paper

 Effectiveness of micro-ROS over WiFi  
 M. Ciaravino, L. Horsman, T. Istvan, J. Kanemoto  
 Department of Engineering, University of Hawaiʻi  
 Advisor Dr. A. Trimble

For the micro-ROS setup and configuration guide used in this
experiment, see the companion repository
[mciaravinopico_microros_wifi](httpsgithub.commciaravinopico_microros_wifi)

---

## Overview

This repository contains all code and data needed to reproduce the
experiment described in the paper. Four communication configurations
were benchmarked between a host PC and a Raspberry Pi Pico 2W

 #  Configuration  Transport  Framework 
------------
 1  Serial, ad-hoc  UART  Custom script 
 2  WiFi, ad-hoc  UDP  Custom script 
 3  Serial, micro-ROS  UART + XRCE-DDS  micro-ROS 
 4  WiFi, micro-ROS  UDP + XRCE-DDS  micro-ROS 

Each configuration was run at 1, 10, and 100 Hz for 1,000
request-reply cycles per run, repeated 10 times,
yielding 154,000 total records.

---

## Hardware

 Component  Device 
------
 Router  Netgear Nighthawk RAX10 (WiFi 6, 802.11ax) 
 Main controller (host)  Ubuntu 24.04.2 LTS, Intel Core i3-7020U 
 Microcontroller  Raspberry Pi Pico 2W (RP2350) 
 Sensor  ADS1115 analog-to-digital converter 

Wiring (Pico 2W ↔ ADS1115)
 Pico 2W Pin  ADS1115 Pin 
------
 3.3V  VDD 
 GND  GND 
 GP4 (SDA)  SDA 
 GP5 (SCL)  SCL 

---

## Repository Structure

```
├── PicoFirmware                  # Pico-side CC++ firmware
│   ├── serial_adhoc              # Firmware for config 1
│   ├── wifi_adhoc                # Firmware for config 2
│   ├── serial_microros           # Firmware for config 3
│   └── wifi_microros             # Firmware for config 4
│
├── data                          # Raw experiment data (154 CSV files)
│   └── config_freqhz_runn.csv
│
├── serial_adhoc_runner.py                  # Host runner — config 1
├── wifi_adhoc_runner.py                    # Host runner — config 2
├── serial_microros_besteffort_runner.py    # Host runner — config 3
├── wifi_microros_besteffort_runner.py      # Host runner — config 4
├── serial_microros_reliable_runner.py      # QoS comparison (not reported)
├── wifi_microros_reliable_runner.py        # QoS comparison (not reported)
│
├── explore_stats.py               # Computes summary statistics from data
├── generate_plots.py              # Generates all paper figures
└── requirements.txt               # Python dependencies
```

---

## Requirements

### Hardware
- Raspberry Pi Pico 2W flashed with the appropriate firmware (see below)
- ADS1115 wired as described above
- WiFi router accessible to both host and Pico 2W

### Software (host PC)
- Ubuntu 24.04 LTS (or compatible Linux)
- ROS 2 Jazzy installed and sourced
- micro-ROS agent (for configs 3 and 4 only)
- Python 3.10+

Install Python dependencies
```bash
pip install -r requirements.txt
```

---

## Flashing the Pico Firmware

Each configuration requires different firmware flashed to the Pico 2W.

1. Connect the Pico 2W via USB while holding the BOOTSEL button
2. It will appear as a mass storage device
3. Copy the appropriate `.uf2` file from `PicoFirmwareconfig` to the device
4. The Pico will reboot automatically

For WiFi configurations, update the WiFi credentials in the firmware
source before building. See the
[setup guide](httpsgithub.commciaravinopico_microros_wifi)
for full build instructions.

---

## Running the Experiment

### Configs 1 & 2 — Ad-hoc framework (no micro-ROS agent needed)

Config 1 Serial, ad-hoc
```bash
# Connect Pico via USB, then
python3 serial_adhoc_runner.py
```

Config 2 WiFi, ad-hoc
```bash
# Ensure Pico and host are on the same network, then
python3 wifi_adhoc_runner.py
```

### Configs 3 & 4 — micro-ROS framework (agent required)

Start the micro-ROS agent in a separate terminal before running
the host script

```bash
# Serial transport (config 3)
ros2 run micro_ros_agent micro_ros_agent serial --dev devttyACM0

# WiFiUDP transport (config 4)
ros2 run micro_ros_agent micro_ros_agent udp4 --port 8888
```

Then in a second terminal

```bash
# Config 3 Serial, micro-ROS
python3 serial_microros_besteffort_runner.py

# Config 4 WiFi, micro-ROS
python3 wifi_microros_besteffort_runner.py
```

### Output

Each runner saves one CSV file per run to the `data` directory with
the naming convention

```
config_freqhz_runn.csv
```

Each CSV contains one row per message with columns
`run`, `config`, `frequency_hz`, `message_index`, `rtt_ms`, `status`

---

## Reproducing Statistics

To reproduce the summary statistics reported in the paper (Table II)

```bash
python3 explore_stats.py
```

This will print median RTT ± 95% CI, P95 RTT ± 95% CI, and delivery
rate ± 95% CI for all configurations and frequencies, computed
across the 10 runs per cell using a Student-t confidence interval.

---

## Reproducing Figures

To reproduce all paper figures

```bash
python3 generate_plots.py --data_dir .data --out_dir .outputs
```

Figures are saved to `outputs` as PNG at 300 DPI. To save as PDF
for vector quality (recommended for final submission)

```bash
python3 generate_plots.py --data_dir .data --out_dir .outputs --ext pdf
```

 File  Description 
------
 `fig1_serial_adhoc.png`  Per-config results Serial, ad-hoc 
 `fig2_wifi_adhoc.png`  Per-config results WiFi, ad-hoc 
 `fig3_serial_microros.png`  Per-config results Serial, micro-ROS 
 `fig4_wifi_microros.png`  Per-config results WiFi, micro-ROS 
 `fig5_cross_1hz.png`  Cross-config comparison at 1 Hz 
 `fig6_cross_10hz.png`  Cross-config comparison at 10 Hz 
 `fig7_cross_100hz.png`  Cross-config comparison at 100 Hz 
 `fig8_cross_combined.png`  Combined three-panel comparison (horizontal bars) 
 `fig9_cross_combined_vertical.png`  Combined three-panel comparison (vertical bars) 

---

## Data

The `data` directory contains all 154 raw CSV files from the
experiment (154,000 records total). These are provided so that
all statistics and figures can be reproduced exactly from the
raw data without re-running the experiment.

The Reliable QoS data (`serial_microros_reliable` and
`wifi_microros_reliable`) are included in the raw data for
completeness but are not reported in the paper. Best-Effort QoS
was found to be strictly superior in all conditions; see the
paper for the QoS selection rationale.

---

## Notes on Reproducibility

- All experiments were conducted in a single controlled indoor
  environment with no network congestion.
- WiFi performance may differ under different router hardware,
  network load, physical distance, or obstacles.
- The ADS1115 operates in continuous conversion mode. At 100 Hz
  request frequency the Pico reads the most recently completed
  ADC sample rather than triggering a fresh conversion.
- The micro-ROS agent version and ROS 2 distribution may affect
  results. This experiment used ROS 2 Jazzy.

---

## License

MIT License. See `LICENSE` for details.