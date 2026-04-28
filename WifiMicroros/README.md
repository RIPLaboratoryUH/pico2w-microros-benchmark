# Wi-Fi micro-ROS Firmware (Pico 2W)

This folder contains the **modified files only** for the Wi-Fi + micro-ROS
configuration used in the IEEE paper benchmark. To build a working firmware,
overlay these files on top of the upstream Raspberry Pi Pico micro-ROS SDK
template (with Wi-Fi/UDP transport added).

## Files

- `CMakeLists.txt` — build configuration with the experiment's targets and
  Wi-Fi/lwIP flags
- `lwipopts.h` — lwIP TCP/IP stack configuration tuned for this workload
- `pico_micro_ros_example.c` — main firmware: ADS1115 read, micro-ROS
  publisher, request-reply communication chain. Includes the
  `cyw43_wifi_pm(&cyw43_state, CYW43_NO_POWERSAVE_MODE)` call required to
  obtain the latency results reported in the paper (see Section III-F).
- `picow_udp_transports.c` / `.h` — custom micro-ROS UDP transport layer
  for the Pico 2W's CYW43439 radio

## How to use

1. Clone the upstream micro-ROS Pico SDK template:

   ```bash
   git clone -b jazzy https://github.com/micro-ROS/micro_ros_raspberrypi_pico_sdk.git
   ```

2. Copy the five files in this folder into the cloned project, replacing
   any defaults of the same name and adding `picow_udp_transports.{c,h}`
   and `lwipopts.h` as new files.

3. Set the agent IP address and Wi-Fi credentials at the top of
   `picow_udp_transports.h` before building.

4. Build with the standard Pico SDK toolchain (see upstream README).

For a complete step-by-step setup guide independent of this experiment —
including agent setup, network configuration, and troubleshooting — see
the companion repository:
**https://github.com/RIPLaboratoryUH/[guide-repo-name-tbd]**

## Pairing

This firmware is exercised by `wifi_microros_runner.py` in the
repository root.

## Note on power save

The CYW43439 radio defaults to a power-save mode that imposes a wake-up
penalty when the inter-message interval exceeds ~200 ms (i.e., at message
rates ≤ 5 Hz). The line:

```c
cyw43_wifi_pm(&cyw43_state, CYW43_NO_POWERSAVE_MODE);
```

near the top of `pico_micro_ros_example.c` disables this behavior.
Removing or commenting out this line will reproduce the default-PM latency
characteristics described in Section III-F of the paper.
