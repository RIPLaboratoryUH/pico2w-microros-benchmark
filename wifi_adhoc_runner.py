#!/usr/bin/env python3
"""
wifi_adhoc_runner.py  —  WiFi Ad-hoc RTT experiment runner.

The Pico runs main.py (MicroPython, no micro-ROS), connected to your
home router via WiFi. The host PC sends UDP requests and receives
UDP replies, computing RTT per message.

Architecture:
    [This script] --UDP:5005--> [Pico @ 192.168.50.106]
    [This script] <--UDP:5006-- [Pico @ 192.168.50.106]

Prerequisites:
    1. Flash main.py + ads1x15.py to Pico (MicroPython)
    2. Pico boots and connects to WiFi — note its IP from Thonny output
    3. Both host PC and Pico on same network (router: Detroit)
    4. Update PICO_IP below if Pico got a different DHCP address
    5. Run:
           python3 wifi_adhoc_runner.py --freq 100 --run 1

Output:
    data/wifi_adhoc_100hz_run01_<timestamp>.csv
"""

import argparse
import csv
import math
import socket
import statistics
import threading
import time
from datetime import datetime
from pathlib import Path

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

# ── Network config — update PICO_IP if DHCP gave it a different address ───────
PICO_IP      = "192.168.50.106"
PICO_PORT    = 5005   # Pico listens here
LISTEN_PORT  = 5006   # Host listens here for replies

# ── Experiment config ──────────────────────────────────────────────────────────
TOTAL_MSGS        = 1000
LATE_THRESHOLD_MS = 500.0
DATA_DIR          = Path("./data")
CONFIG_NAME       = "wifi_adhoc"


class WiFiAdHocRunner(Node):
    """
    Sends timestamped UDP requests to the Pico, receives UDP replies,
    publishes on /pico_data (same as original hostPCScript.py),
    and saves per-message RTT to CSV.
    """

    def __init__(self, freq_hz: int, run_idx: int, pico_ip: str):
        super().__init__("wifi_adhoc_runner")

        self.freq_hz  = freq_hz
        self.run_idx  = run_idx
        self.period_s = 1.0 / freq_hz
        self.pico_ip  = pico_ip

        # ROS publisher — keeps existing downstream tools working
        self.publisher = self.create_publisher(String, "pico_data", 10)

        # UDP send socket
        self.send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.send_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

        # UDP receive socket
        self.recv_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.recv_sock.bind(("0.0.0.0", LISTEN_PORT))
        self.recv_sock.settimeout(0.5)  # 500ms timeout per recv

        self.records: list[dict] = []
        self._lock = threading.Lock()
        self.done  = threading.Event()

        # Start listener thread
        self._listener_thread = threading.Thread(
            target=self._listener, daemon=True
        )
        self._listener_thread.start()

        self.get_logger().info(
            f"WiFi ad-hoc runner ready — Pico @ {pico_ip}:{PICO_PORT}, "
            f"listening on :{LISTEN_PORT}"
        )

    # ── Listener thread ────────────────────────────────────────────────────────

    def _listener(self):
        self.get_logger().info("UDP listener thread started.")
        while not self.done.is_set():
            try:
                data, addr = self.recv_sock.recvfrom(1024)
                recv_ts_us = time.time_ns() // 1000

                if not data:
                    continue

                line = data.decode(errors="ignore").strip()

                # Publish on ROS topic
                ros_msg = String()
                ros_msg.data = line + f" Final TS: {recv_ts_us}"
                self.publisher.publish(ros_msg)

                # Parse original timestamp from echoed message
                # Format: "Message Index: N Timestamp: <us> Voltage: <V>"
                parts = line.split()
                try:
                    ts_pos   = parts.index("Timestamp:") + 1
                    send_ts  = int(parts[ts_pos])
                    rtt_ms   = (recv_ts_us - send_ts) / 1000.0
                except (ValueError, IndexError):
                    self.get_logger().warn(f"Unrecognised reply: {line}")
                    continue

                status = "ok" if rtt_ms <= LATE_THRESHOLD_MS else "dropped"

                with self._lock:
                    self.records.append({
                        "config":       CONFIG_NAME,
                        "frequency_hz": self.freq_hz,
                        "run":          self.run_idx,
                        "send_ts_us":   send_ts,
                        "recv_ts_us":   recv_ts_us,
                        "rtt_ms":       rtt_ms,
                        "status":       status,
                    })

            except socket.timeout:
                continue
            except Exception as e:
                self.get_logger().error(f"UDP receive error: {e}")
                break

    # ── Sender ─────────────────────────────────────────────────────────────────

    def send_all(self):
        self.get_logger().info(
            f"Sending {TOTAL_MSGS} messages @ {self.freq_hz} Hz "
            f"(period {self.period_s*1000:.1f} ms) to {self.pico_ip}:{PICO_PORT}"
        )

        t_start = time.perf_counter()
        for i in range(1, TOTAL_MSGS + 1):
            target = t_start + (i - 1) * self.period_s
            now    = time.perf_counter()
            if target > now:
                time.sleep(target - now)

            ts_us = time.time_ns() // 1000
            msg   = f"Message Index: {i} Timestamp: {ts_us}"
            self.send_sock.sendto(msg.encode(), (self.pico_ip, PICO_PORT))

            if i % 100 == 0:
                with self._lock:
                    n_recv = len(self.records)
                self.get_logger().info(
                    f"  Sent {i}/{TOTAL_MSGS}, received so far: {n_recv}"
                )

        self.get_logger().info("All messages sent. Waiting for remaining replies…")

        # WiFi can have longer tail latency — wait generously
        wait = max(3.0, self.period_s * 5)
        time.sleep(wait)
        self.done.set()

    # ── Save CSV ───────────────────────────────────────────────────────────────

    def save_csv(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = (f"{CONFIG_NAME}_{self.freq_hz}hz"
                    f"_run{self.run_idx:02d}_{ts}.csv")
        path     = DATA_DIR / filename

        with self._lock:
            records_snapshot = list(self.records)

        # Mark unreplied messages as dropped
        n_replied = len(records_snapshot)
        n_dropped = max(0, TOTAL_MSGS - n_replied)
        for _ in range(n_dropped):
            records_snapshot.append({
                "config":       CONFIG_NAME,
                "frequency_hz": self.freq_hz,
                "run":          self.run_idx,
                "send_ts_us":   "",
                "recv_ts_us":   "",
                "rtt_ms":       float("nan"),
                "status":       "dropped",
            })

        fieldnames = ["config", "frequency_hz", "run",
                      "send_ts_us", "recv_ts_us", "rtt_ms", "status"]
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(records_snapshot)

        # Summary
        ok      = sum(1 for r in records_snapshot if r["status"] == "ok")
        dropped = sum(1 for r in records_snapshot if r["status"] == "dropped")
        rtts    = [r["rtt_ms"] for r in records_snapshot
                   if r["status"] == "ok" and not math.isnan(r["rtt_ms"])]

        print("\n" + "="*55)
        print(f"  Config : {CONFIG_NAME}  |  Freq: {self.freq_hz} Hz  |  Run: {self.run_idx}")
        print(f"  Sent   : {TOTAL_MSGS}")
        print(f"  OK     : {ok}   ({100*ok/TOTAL_MSGS:.1f}%)")
        print(f"  Dropped: {dropped}")
        if rtts:
            print(f"  Median RTT : {statistics.median(rtts):.3f} ms")
            print(f"  Std dev    : {statistics.stdev(rtts):.3f} ms")
            print(f"  Min/Max    : {min(rtts):.3f} / {max(rtts):.3f} ms")
        print(f"  Saved  → {path}")
        print("="*55)

        return path

    def close(self):
        self.done.set()
        self.send_sock.close()
        self.recv_sock.close()


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="WiFi Ad-hoc RTT runner"
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
        "--pico_ip", default=PICO_IP,
        help=f"Pico IP address (default: {PICO_IP})"
    )
    args = parser.parse_args()

    rclpy.init()
    node = WiFiAdHocRunner(
        freq_hz  = args.freq,
        run_idx  = args.run,
        pico_ip  = args.pico_ip,
    )

    # Spin ROS callbacks in background thread
    spin_thread = threading.Thread(
        target=lambda: rclpy.spin(node), daemon=True
    )
    spin_thread.start()

    try:
        time.sleep(2)   # let sockets settle
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
