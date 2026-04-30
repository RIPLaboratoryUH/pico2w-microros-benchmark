# pico2w-microros-benchmark

Reproducibility repository for the IEEE conference paper:

> **Effectiveness of micro-ROS over WiFi**
> M. Ciaravino & Dr. Zachary Trimble 
> Department of Engineering, University of Hawaiʻi

A companion setup guide for general use of micro-ROS over WiFi on the Pico 2W
is available at
[`pico2w-microros-wifi-guide`](https://github.com/RIPLaboratoryUH/pico2w-microros-wifi-guide).

---

## Overview

This repository contains all code and data needed to reproduce the benchmark
experiment described in the paper. Four communication configurations were
evaluated between a host PC and a Raspberry Pi Pico 2W:

| Configuration | Transport | Framework |
|---|---|---|
| Serial, ad-hoc | UART | Custom Python script |
| WiFi, ad-hoc | UDP | Custom Python script |
| Serial, micro-ROS | UART + XRCE-DDS | micro-ROS |
| WiFi, micro-ROS | UDP + XRCE-DDS | micro-ROS |

Each configuration was run at **1, 10, and 100 Hz** for **1,000 request-reply
cycles per run**, repeated **10 times**, yielding 120 CSV files and 120,000
total records.

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

## Repository structure

```
├── PicoFirmware/                  MicroPython firmware for ad-hoc configs
├── SerialMicroros/                Modified files only — serial micro-ROS
├── WifiMicroros/                  Modified files only — WiFi micro-ROS
├── data/                          Raw experiment data (120 CSV files)
├── serial_adhoc_runner.py         Host runner — serial, ad-hoc
├── wifi_adhoc_runner.py           Host runner — WiFi, ad-hoc
├── serial_microros_runner.py      Host runner — serial, micro-ROS
├── wifi_microros_runner.py        Host runner — WiFi, micro-ROS
├── explore_stats.py               Computes summary statistics
├── generate_plots.py              Generates paper figures
└── requirements.txt               Python dependencies
```

The `SerialMicroros/` and `WifiMicroros/` folders contain only the files that
differ from the upstream
[micro-ROS Pico SDK](https://github.com/micro-ROS/micro_ros_raspberrypi_pico_sdk).
Each folder contains its own README explaining how to combine its files with a
fresh clone of the upstream SDK.

---

## Requirements (host PC)

- Ubuntu 24.04 LTS (or compatible Linux)
- ROS 2 Jazzy
- micro-ROS agent (for micro-ROS configurations)
- Python 3.10+
- Thonny (for flashing MicroPython firmware)

```bash
pip install -r requirements.txt
```

---

## Pico firmware setup

### Ad-hoc configurations

Open Thonny, connect the Pico via USB, and copy the contents of
`PicoFirmware/` onto the device.

### micro-ROS configurations

Follow the build instructions in the companion
[setup guide](https://github.com/RIPLaboratoryUH/pico2w-microros-wifi-guide),
then overlay the modified files from `SerialMicroros/` or `WifiMicroros/`
before building. See each folder's README for details.

---

## Running the experiment

### Ad-hoc configurations

```bash
python3 serial_adhoc_runner.py
python3 wifi_adhoc_runner.py
```

### micro-ROS configurations

Start the agent in a separate terminal first:

```bash
# Serial
ros2 run micro_ros_agent micro_ros_agent serial --dev /dev/ttyACM0
python3 serial_microros_runner.py

# WiFi
ros2 run micro_ros_agent micro_ros_agent udp4 --port 8888
python3 wifi_microros_runner.py
```

Each runner saves one CSV per run to `data/`.

---

## Reproducing statistics

```bash
python3 explore_stats.py
```

Prints median RTT, P95 RTT, and delivery rate (each with 95% CI) for all
configurations and frequencies, as reported in Table III of the paper.

---

## Reproducing figures

```bash
python3 generate_plots.py --data_dir ./data --out_dir ./outputs
```

For vector PDF output:

```bash
python3 generate_plots.py --data_dir ./data --out_dir ./outputs --ext pdf
```

---

## Notes

- All experiments were conducted in a single controlled indoor environment.
  WiFi performance may differ under network congestion, distance, or
  obstacles.
- This experiment used ROS 2 Jazzy. Results may differ on other distributions.
- Reliable QoS data is not included; Best-Effort was strictly superior in all
  conditions tested. See the paper for the QoS selection rationale.

---

## Citation

If you use this work, please cite the paper. See `CITATION.cff` for citation
metadata.

---

## License

MIT — see [LICENSE](LICENSE).
