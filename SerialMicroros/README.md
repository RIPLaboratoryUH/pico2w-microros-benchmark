# Serial micro-ROS Firmware (Pico 2W)

This folder contains the **modified files only** for the Serial + micro-ROS
configuration used in the IEEE paper benchmark. To build a working firmware,
overlay these files on top of the upstream Raspberry Pi Pico micro-ROS SDK
template.

## Files

- `CMakeLists.txt` — build configuration with the experiment's targets and flags
- `pico_micro_ros_example.c` — main firmware: ADS1115 read, micro-ROS publisher,
  request-reply communication chain

## How to use

1. Clone the upstream micro-ROS Pico SDK template:

   ```bash
   git clone -b jazzy https://github.com/micro-ROS/micro_ros_raspberrypi_pico_sdk.git
   ```

2. Copy the two files in this folder over the matching files in that clone,
   replacing the upstream defaults.

3. Build with the standard Pico SDK toolchain (see upstream README for
   prerequisites and build steps).

For a full step-by-step setup guide independent of this experiment, see the
companion repository:
**https://github.com/RIPLaboratoryUH/pico2w-microros-wifi-guide**

## Pairing

This firmware is exercised by `serial_microros_besteffort_runner.py` in the
repository root.
