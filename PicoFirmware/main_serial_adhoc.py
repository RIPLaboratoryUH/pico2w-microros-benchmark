# main.py  —  Pico 2W (RP2350), Serial Ad-hoc config
# Flash this alongside ads1x15.py
#
# Protocol:
#   Host sends:   "Message Index: <N> Timestamp: <us>\n"
#   Pico replies: "Message Index: <N> Timestamp: <us> Voltage: <V>\r\n"
#
# The reply echoes the full request line with Voltage appended so the
# host can match on Index and compute RTT from the original Timestamp.

import sys
import time
from machine import I2C, Pin
from ads1x15 import ADS1115

# ── Hardware setup ─────────────────────────────────────────────────────────────
i2c = I2C(0, scl=Pin(5), sda=Pin(4), freq=400000)
adc = ADS1115(i2c, address=0x48, gain=1)


def read_sensor():
    """Read AIN2 vs AIN3 differential at 1600 SPS."""
    raw     = adc.read(4, 2, 3)   # rate index 4 = 1600 SPS
    voltage = adc.raw_to_v(raw)
    return voltage


def main():
    # Flush any garbage in stdin before we start
    # (MicroPython doesn't have a flush, so just drain it)
    buf = b""

    print("Pico ready — waiting for host messages")

    while True:
        # readline() blocks until '\n' with no busy-waiting.
        # At 115200 baud, receiving ~50 chars takes < 0.5 ms.
        try:
            line = sys.stdin.readline()
        except Exception:
            continue

        if not line:
            continue

        msg = line.strip()
        if not msg:
            continue

        # Read sensor immediately on receipt
        voltage = read_sensor()

        # Echo back with voltage appended
        reply = msg + " Voltage: " + str(voltage)
        sys.stdout.write(reply + "\r\n")
        # Note: no flush needed on MicroPython USB CDC — writes go out immediately


if __name__ == "__main__":
    main()
