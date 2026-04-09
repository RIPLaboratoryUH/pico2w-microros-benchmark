#!/usr/bin/env python3
"""
wifi_microros_reliable_runner.py  —  WiFi micro-ROS RTT experiment runner
                                      (RELIABLE QoS).

Architecture:
    [This script] --> /voltage_request (UInt64) --> [micro-ROS agent]
                                                         |
                                                    UDP :8899
                                                         |
                                                    [Pico W @ WiFi]
                                                         |
                                                    UDP :8899
                                                         |
    [This script] <-- /voltage_reading (String) <-- [micro-ROS agent]

Prerequisites (in order):
    1. Flash pico_micro_ros_example.c firmware to Pico W
       Firmware must use rclc_*_init_default for both pub and sub (RELIABLE).
       (uses picow_udp_transports.c — agent IP hardcoded in picow_udp_transports.h)
    2. Pico W boots and connects to WiFi SSID "Detroit"
    3. Start the micro-ROS agent in a separate terminal:
           sudo docker run -it --rm --net=host \\
               microros/micro-ros-agent:jazzy udp4 --port 8899
    4. Wait for agent to print "Session established"
    5. Run this script:
           python3 wifi_microros_reliable_runner.py --freq 100 --run 1

Output:
    data/wifi_microros_reliable_100hz_run01_<timestamp>.csv
"""

import argparse
import csv
import math
import statistics
import threading
import time
from datetime import datetime
from pathlib import Path

import rclpy
from rclpy.node import Node
from std_msgs.msg import String, UInt64

# ── Config ─────────────────────────────────────────────────────────────────────
TOTAL_MSGS        = 1000
LATE_THRESHOLD_MS = 500.0
DATA_DIR          = Path("./data")
CONFIG_NAME       = "wifi_microros_reliable"

# How long to wait for the agent/Pico to be ready before sending
WARMUP_S = 3.0


class WiFiMicroROSReliableRunner(Node):
    """
    Publishes UInt64 timestamps on /voltage_request and receives
    String replies on /voltage_reading, computing RTT for each message.

    Transport from host to Pico is UDP via the micro-ROS agent (udp4 mode).
    QoS is RELIABLE on both pub and sub to match the Pico firmware's
    rclc_*_init_default calls. Note that RELIABLE over lossy WiFi can stall
    or accumulate large tail latencies as the XRCE-DDS client retransmits.
    """

    def __init__(self, freq_hz: int, run_idx: int):
        super().__init__("wifi_microros_reliable_runner")

        self.freq_hz  = freq_hz
        self.run_idx  = run_idx
        self.period_s = 1.0 / freq_hz

        # Match the Pico firmware, which uses rclc_*_init_default (RELIABLE)
        # on both the voltage_request subscriber and voltage_reading publisher.
        # rclpy's default QoS is also RELIABLE, so we pass depth=10 directly.
        self.pub = self.create_publisher(UInt64, "voltage_request", 10)
        self.sub = self.create_subscription(
            String,
            "voltage_reading",
            self._reply_callback,
            10,
        )

        self.records: list[dict] = []
        self._lock   = threading.Lock()
        self.done    = threading.Event()

        self.get_logger().info(
            f"Runner ready — {CONFIG_NAME} @ {freq_hz} Hz, run {run_idx}"
        )

    # ── Reply callback ─────────────────────────────────────────────────────────

    def _reply_callback(self, msg: String):
        """
        Expected format from Pico firmware:
          "voltage reading reply with timestamp: <us>, voltage: <V>"
        """
        recv_ts_us = time.time_ns() // 1000

        try:
            # Parse original timestamp embedded in the reply
            parts = msg.data.split("timestamp:")
            if len(parts) < 2:
                self.get_logger().warn(f"Unexpected format: {msg.data}")
                return

            send_ts_us = int(parts[1].split(",")[0].strip())
            rtt_ms     = (recv_ts_us - send_ts_us) / 1000.0

            status = "ok" if rtt_ms <= LATE_THRESHOLD_MS else "dropped"

            with self._lock:
                self.records.append({
                    "config":       CONFIG_NAME,
                    "frequency_hz": self.freq_hz,
                    "run":          self.run_idx,
                    "send_ts_us":   send_ts_us,
                    "recv_ts_us":   recv_ts_us,
                    "rtt_ms":       rtt_ms,
                    "status":       status,
                })

        except Exception as e:
            self.get_logger().error(f"Parse error: {e}  msg={msg.data}")

    # ── Sender ─────────────────────────────────────────────────────────────────

    def send_all(self):
        self.get_logger().info(
            f"Sending {TOTAL_MSGS} messages @ {self.freq_hz} Hz "
            f"(period {self.period_s*1000:.1f} ms)"
        )

        t_start = time.perf_counter()
        for i in range(1, TOTAL_MSGS + 1):
            # Absolute deadline scheduling — no drift accumulation
            target = t_start + (i - 1) * self.period_s
            now    = time.perf_counter()
            if target > now:
                time.sleep(target - now)

            ts_us = time.time_ns() // 1000
            msg   = UInt64()
            msg.data = ts_us
            self.pub.publish(msg)

            if i % 100 == 0:
                with self._lock:
                    n_recv = len(self.records)
                self.get_logger().info(
                    f"  Sent {i}/{TOTAL_MSGS}, received so far: {n_recv}"
                )

        self.get_logger().info("All messages sent. Waiting for remaining replies…")

        # Wait for in-flight replies — longer wait for low frequencies
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

        # Mark messages that never got a reply as dropped
        n_replied = len(records_snapshot)
        n_dropped = max(0, TOTAL_MSGS - n_replied)
        for i in range(n_dropped):
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


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="WiFi micro-ROS RTT runner (RELIABLE QoS)"
    )
    parser.add_argument(
        "--freq", required=True, type=int, choices=[1, 10, 100],
        help="Request frequency in Hz"
    )
    parser.add_argument(
        "--run", required=True, type=int,
        help="Run index (1–10)"
    )
    args = parser.parse_args()

    rclpy.init()
    node = WiFiMicroROSReliableRunner(freq_hz=args.freq, run_idx=args.run)

    # Spin ROS callbacks in background thread
    spin_thread = threading.Thread(
        target=lambda: rclpy.spin(node), daemon=True
    )
    spin_thread.start()

    try:
        # Warmup — give agent session time to stabilise
        print(f"Waiting {WARMUP_S}s for agent session to stabilise…")
        time.sleep(WARMUP_S)

        node.send_all()
        node.save_csv()

    except KeyboardInterrupt:
        print("\nInterrupted — saving partial data…")
        node.save_csv()

    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
