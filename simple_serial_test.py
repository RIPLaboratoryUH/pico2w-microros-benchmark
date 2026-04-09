#!/usr/bin/env python3
"""
simple_serial_test.py — Send one request to the Pico, print the reply.
No ROS, no threading, nothing fancy.

Usage:
    python3 simple_serial_test.py
"""

import serial
import time

PORT = "/dev/ttyACM0"
BAUD = 115200

print(f"Opening {PORT} @ {BAUD}...")
ser = serial.Serial(PORT, BAUD, timeout=5)
time.sleep(2)  # let serial settle

print("Sending request...")
ts = int(time.time() * 1e6)
msg = f"Message Index: 1 Timestamp: {ts}\n"
ser.write(msg.encode())
print(f"  Sent: {msg.strip()}")

print("Waiting for reply (5s timeout)...")
reply = ser.readline()
print(f"  Raw reply bytes: {repr(reply)}")

if reply:
    print(f"  Decoded: {reply.decode(errors='ignore').strip()}")
else:
    print("  No reply received.")

ser.close()
