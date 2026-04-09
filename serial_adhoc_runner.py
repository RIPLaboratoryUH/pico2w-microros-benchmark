#!/usr/bin/env python3
"""
serial_adhoc_runner.py  —  Serial Ad-hoc RTT experiment runner.

Run this on the host PC while main.py + ads1x15.py are on the Pico.
The Pico must already be flashed and connected via USB before starting.

Usage:
    python3 serial_adhoc_runner.py --freq 100 --run 1
    python3 serial_adhoc_runner.py --freq 10  --run 1
    python3 serial_adhoc_runner.py --freq 1   --run 1

Required:
    pip install pyserial
    source /opt/ros/jazzy/setup.bash   (for rclpy)

Output:
    data/serial_adhoc_100hz_run01_<timestamp>.csv
"""

import argparse
import csv
import math
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import serial
import rclpy
from rclpy.node import Node
from std_msgs.msg import String

# ── Config ─────────────────────────────────────────────────────────────────────
PORT       = "/dev/ttyACM0"
BAUD       = 115200
TOTAL_MSGS = 1000
LATE_THRESHOLD_MS = 500.0
DATA_DIR   = Path("./data")

CONFIG_NAME = "serial_adhoc"


# ── Node ───────────────────────────────────────────────────────────────────────

class SerialAdHocRunner(Node):
    """
    Sends timestamped requests over UART, receives echoed replies,
    publishes them on /pico_data (same as before), AND records RTT
    per-message into a CSV — all in one process.
    """

    def __init__(self, freq_hz: int, run_idx: int, port: str, baud: int):
        super().__init__("serial_adhoc_runner")

        self.freq_hz   = freq_hz
        self.run_idx   = run_idx
        self.period_s  = 1.0 / freq_hz

        # Serial port
        self.ser = serial.Serial(port, baud, timeout=self.period_s * 3)
        self.get_logger().info(f"Serial open: {port} @ {baud}")

        # ROS publisher (keeps existing downstream tools working)
        self.publisher = self.create_publisher(String, "pico_data", 10)

        # Per-message RTT records
        self.records: list[dict] = []

        # Pending send timestamps keyed by message index
        self._pending: dict[int, float] = {}
        self._lock = threading.Lock()

        self.done = threading.Event()

        # Start listener thread
        self._listener_thread = threading.Thread(
            target=self._listener, daemon=True
        )
        self._listener_thread.start()

    # ── Listener thread ────────────────────────────────────────────────────────

    def _listener(self):
        """
        Reads reply lines from the Pico.  Each reply echoes the original
        message with Voltage appended, e.g.:
          Message Index: 7 Timestamp: 1234567890 Voltage: 1.234
        We match on the embedded message index to look up the send timestamp.
        """
        self.get_logger().info("Listener thread started.")
        while not self.done.is_set():
            try:
                raw = self.ser.readline()
                recv_ts_us = time.time_ns() // 1000

                if not raw:
                    continue  # timeout — no data

                line = raw.decode(errors="ignore").strip()
                if not line:
                    continue

                # Publish on ROS topic (unchanged behaviour)
                ros_msg = String()
                ros_msg.data = line + f" Final TS: {recv_ts_us}"
                self.publisher.publish(ros_msg)

                # Parse message index and original timestamp
                parts = line.split()
                try:
                    idx_pos  = parts.index("Index:") + 1
                    ts_pos   = parts.index("Timestamp:") + 1
                    msg_idx  = int(parts[idx_pos])
                    send_ts  = int(parts[ts_pos])        # microseconds
                    rtt_ms   = (recv_ts_us - send_ts) / 1000.0
                except (ValueError, IndexError):
                    self.get_logger().warn(f"Unrecognised reply: {line}")
                    continue

                if rtt_ms > LATE_THRESHOLD_MS:
                    status = "late"
                elif rtt_ms < 0:
                    status = "error"
                else:
                    status = "ok"

                with self._lock:
                    self.records.append({
                        "config":       CONFIG_NAME,
                        "frequency_hz": self.freq_hz,
                        "run":          self.run_idx,
                        "msg_index":    msg_idx,
                        "send_ts_us":   send_ts,
                        "recv_ts_us":   recv_ts_us,
                        "rtt_ms":       rtt_ms,
                        "status":       status,
                    })

            except serial.SerialException as e:
                self.get_logger().error(f"Serial error: {e}")
                break

    # ── Sender (called from main thread) ──────────────────────────────────────

    def send_all(self):
        """
        Sends TOTAL_MSGS requests at the target frequency using
        absolute-deadline scheduling to avoid drift accumulation.
        """
        self.get_logger().info(
            f"Sending {TOTAL_MSGS} messages @ {self.freq_hz} Hz "
            f"(period {self.period_s*1000:.1f} ms)"
        )
        self.ser.reset_input_buffer()

        t_start = time.perf_counter()
        for i in range(1, TOTAL_MSGS + 1):
            # Absolute target time for this message
            target = t_start + (i - 1) * self.period_s
            now    = time.perf_counter()
            if target > now:
                time.sleep(target - now)

            ts_us = time.time_ns() // 1000
            msg   = f"Message Index: {i} Timestamp: {ts_us}"
            self.ser.write((msg + "\n").encode())

            if i % 100 == 0:
                with self._lock:
                    n_recv = len(self.records)
                self.get_logger().info(
                    f"  Sent {i}/{TOTAL_MSGS}, received so far: {n_recv}"
                )

        self.get_logger().info("All messages sent. Waiting for remaining replies…")

        # Wait up to 3× the period per remaining message, or at least 3 s
        wait = max(3.0, self.period_s * 3 * TOTAL_MSGS * 0.02)
        time.sleep(wait)
        self.done.set()

    # ── Save CSV ───────────────────────────────────────────────────────────────

    def save_csv(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{CONFIG_NAME}_{self.freq_hz}hz_run{self.run_idx:02d}_{ts}.csv"
        path     = DATA_DIR / filename

        with self._lock:
            records_snapshot = list(self.records)

        # Figure out which indices were never replied to
        replied_indices = {r["msg_index"] for r in records_snapshot}
        for i in range(1, TOTAL_MSGS + 1):
            if i not in replied_indices:
                records_snapshot.append({
                    "config":       CONFIG_NAME,
                    "frequency_hz": self.freq_hz,
                    "run":          self.run_idx,
                    "msg_index":    i,
                    "send_ts_us":   "",
                    "recv_ts_us":   "",
                    "rtt_ms":       float("nan"),
                    "status":       "dropped",
                })

        records_snapshot.sort(key=lambda r: r["msg_index"])

        fieldnames = ["config", "frequency_hz", "run", "msg_index",
                      "send_ts_us", "recv_ts_us", "rtt_ms", "status"]
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(records_snapshot)

        # Print summary
        ok      = sum(1 for r in records_snapshot if r["status"] == "ok")
        late    = sum(1 for r in records_snapshot if r["status"] == "late")
        dropped = sum(1 for r in records_snapshot if r["status"] == "dropped")
        rtts    = [r["rtt_ms"] for r in records_snapshot
                   if r["status"] == "ok" and not math.isnan(r["rtt_ms"])]

        print("\n" + "="*55)
        print(f"  Config : {CONFIG_NAME}  |  Freq: {self.freq_hz} Hz  |  Run: {self.run_idx}")
        print(f"  Sent   : {TOTAL_MSGS}")
        print(f"  OK     : {ok}   ({100*ok/TOTAL_MSGS:.1f}%)")
        print(f"  Late   : {late}")
        print(f"  Dropped: {dropped}")
        if rtts:
            import statistics
            print(f"  Mean RTT : {sum(rtts)/len(rtts):.3f} ms")
            print(f"  Std dev  : {statistics.stdev(rtts):.3f} ms")
            print(f"  Min/Max  : {min(rtts):.3f} / {max(rtts):.3f} ms")
        print(f"  Saved  → {path}")
        print("="*55)

        return path

    def close(self):
        self.done.set()
        self.ser.close()


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Serial Ad-hoc RTT runner for IEEE paper experiment"
    )
    parser.add_argument(
        "--freq", required=True, type=int, choices=[1, 10, 100],
        help="Request frequency in Hz"
    )
    parser.add_argument(
        "--run", required=True, type=int,
        help="Run index (1–10)"
    )
    parser.add_argument(
        "--port", default=PORT,
        help=f"Serial port (default: {PORT})"
    )
    parser.add_argument(
        "--msgs", default=TOTAL_MSGS, type=int,
        help=f"Number of messages (default: {TOTAL_MSGS})"
    )
    args = parser.parse_args()

    rclpy.init()
    node = SerialAdHocRunner(
        freq_hz  = args.freq,
        run_idx  = args.run,
        port     = args.port,
        baud     = BAUD,
    )

    # Spin ROS callbacks in a background thread so timing isn't disrupted
    spin_thread = threading.Thread(
        target=lambda: rclpy.spin(node), daemon=True
    )
    spin_thread.start()

    try:
        time.sleep(2)          # let serial settle
        node.send_all()
        node.save_csv()

    except KeyboardInterrupt:
        print("\nInterrupted — saving partial data…")
        node.save_csv()

    finally:
        node.close()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
