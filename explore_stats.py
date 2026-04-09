#!/usr/bin/env python3
"""
explore_stats.py — Exploratory stats for the micro-ROS RTT experiment.

For each (config, frequency) cell, reports (across the 10 runs):
  - Median RTT (ms) with 95% CI
  - P95 RTT (ms) with 95% CI
  - Max RTT (ms) with 95% CI
  - Delivery rate (%) with 95% CI

Each run is the unit of replication. 95% CIs are Student-t intervals
computed across per-run statistics:
    mean ± t_{0.975, n-1} * (std / sqrt(n))
This reports run-to-run reproducibility, not within-run message variance.

Also reports:
  - Exact payload sizes (request + reply) for ad-hoc configs, measured from
    the actual runner format strings. For micro-ROS configs, reports
    application-level message sizes (ROS 2 type sizes, not wire bytes).

Usage:
    python3 explore_stats.py --data_dir ./data
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

CONFIGS_ORDER = [
    "serial_adhoc",
    "wifi_adhoc",
    "serial_microros_reliable",
    "serial_microros_besteffort",
    "wifi_microros_reliable",
    "wifi_microros_besteffort",
]
FREQS = [1, 10, 100]


# ── Statistics helpers ────────────────────────────────────────────────────────

def ci95(values):
    """Return (mean, half_width) for a 95% Student-t CI."""
    arr = np.asarray(values, dtype=float)
    arr = arr[~np.isnan(arr)]
    n = len(arr)
    if n == 0:
        return float("nan"), float("nan")
    if n == 1:
        return float(arr[0]), float("nan")
    mean = arr.mean()
    sem = arr.std(ddof=1) / np.sqrt(n)
    tcrit = stats.t.ppf(0.975, df=n - 1)
    return mean, tcrit * sem


def fmt(mean, hw):
    if np.isnan(mean):
        return "      n/a     "
    if np.isnan(hw):
        return f"{mean:7.2f}         "
    return f"{mean:7.2f} ± {hw:6.2f}"


# ── RTT / delivery table ──────────────────────────────────────────────────────

def print_rtt_table(df):
    header = (
        f"{'Configuration':<32}{'Freq':>6}  "
        f"{'Median RTT (ms)':>18}  "
        f"{'P95 RTT (ms)':>18}  "
        f"{'Max RTT (ms)':>18}  "
        f"{'Delivery (%)':>18}"
    )
    print(header)
    print("-" * len(header))

    for cfg in CONFIGS_ORDER:
        if cfg not in df["config"].unique():
            continue
        for freq in FREQS:
            sub = df[(df["config"] == cfg) & (df["frequency_hz"] == freq)]
            if len(sub) == 0:
                continue

            per_run_median = []
            per_run_p95 = []
            per_run_max = []
            per_run_delivery = []
            for run_idx, run_df in sub.groupby("run"):
                ok = run_df.loc[run_df["status"] == "ok", "rtt_ms"].dropna().values
                if len(ok) > 0:
                    per_run_median.append(float(np.median(ok)))
                    per_run_p95.append(float(np.percentile(ok, 95)))
                    per_run_max.append(float(np.max(ok)))
                total = len(run_df)
                delivered = int((run_df["status"] == "ok").sum())
                per_run_delivery.append(100.0 * delivered / total if total > 0 else float("nan"))

            med_mean, med_hw = ci95(per_run_median)
            p95_mean, p95_hw = ci95(per_run_p95)
            max_mean, max_hw = ci95(per_run_max)
            del_mean, del_hw = ci95(per_run_delivery)

            print(
                f"{cfg:<32}{freq:>5}Hz  "
                f"{fmt(med_mean, med_hw):>18}  "
                f"{fmt(p95_mean, p95_hw):>18}  "
                f"{fmt(max_mean, max_hw):>18}  "
                f"{fmt(del_mean, del_hw):>16}"
            )
        print()


# ── Payload size analysis ─────────────────────────────────────────────────────

def analyze_payloads():
    """
    Compute exact byte counts for ad-hoc requests/replies from the known
    runner format strings, and report application-level sizes for the
    micro-ROS typed messages.
    """
    print("Payload Size Analysis")
    print("=" * 80)
    print()

    # --- Ad-hoc ------------------------------------------------------------
    # Runners use: f"Message Index: {i} Timestamp: {ts_us}"
    # Index range: 1..1000, timestamp: 16 digits (microseconds since epoch)
    request_lengths = []
    for i in range(1, 1001):
        msg = f"Message Index: {i} Timestamp: 1775645376851015"
        request_lengths.append(len(msg.encode()))

    request_min = min(request_lengths)
    request_max = max(request_lengths)
    request_mean = float(np.mean(request_lengths))

    rep_short = "Message Index: 1 Timestamp: 1775645376851015 Voltage: 0.0"
    rep_typ   = "Message Index: 500 Timestamp: 1775645376851015 Voltage: 0.1234"
    rep_long  = "Message Index: 1000 Timestamp: 1775645376851015 Voltage: -0.12345"

    print("Ad-hoc configurations (ASCII payloads on the wire)")
    print("-" * 80)
    print(f"  Request (host -> Pico):")
    print(f"    Format  : 'Message Index: <N> Timestamp: <us>'")
    print(f"    Size    : {request_min}-{request_max} bytes (varies with index digits)")
    print(f"    Mean    : {request_mean:.1f} bytes")
    print()
    print(f"  Reply (Pico -> host):")
    print(f"    Format  : '<request> Voltage: <V>'")
    print(f"    Example : '{rep_typ}'")
    print(f"    Size    : {len(rep_short.encode())}-{len(rep_long.encode())} bytes")
    print(f"              (varies with index digits and voltage formatting)")
    print()
    print(f"  Paper-ready: ~{round(request_mean)} B request, "
          f"~{round(len(rep_typ.encode()))} B reply")
    print()

    # --- micro-ROS ---------------------------------------------------------
    # From pico_micro_ros_example.c the firmware formats:
    #   "voltage reading reply with timestamp: <N>, voltage: %.3f V"
    uros_reply_example = "voltage reading reply with timestamp: 1775645376851015, voltage: 0.123 V"
    uros_reply_short   = "voltage reading reply with timestamp: 1, voltage: 0.000 V"
    uros_reply_long    = "voltage reading reply with timestamp: 1775645376851015, voltage: -0.123 V"

    print("micro-ROS configurations (ROS 2 typed messages)")
    print("-" * 80)
    print(f"  Request (host -> Pico): std_msgs/UInt64")
    print(f"    Application payload : 8 bytes (uint64 timestamp)")
    print(f"    Wire size           : 8 B + XRCE-DDS framing overhead")
    print()
    print(f"  Reply (Pico -> host): std_msgs/String")
    print(f"    Example content     : '{uros_reply_example}'")
    print(f"    Application payload : {len(uros_reply_short.encode())}-"
          f"{len(uros_reply_long.encode())} bytes")
    print(f"    Wire size           : content + String length prefix + "
          f"XRCE-DDS framing overhead")
    print()
    print(f"  Paper-ready: 8 B request (UInt64), "
          f"~{len(uros_reply_example.encode())} B reply (String content)")
    print()

    # --- Summary table for paper ------------------------------------------
    print("Summary (for paper Table / Methods section)")
    print("-" * 80)
    print(f"  {'Configuration':<40}{'Request':>15}{'Reply':>15}")
    print(f"  {'-'*40}{'-'*15}{'-'*15}")
    print(f"  {'Ad-hoc (serial & Wi-Fi)':<40}{'~45 B ASCII':>15}{'~60 B ASCII':>15}")
    print(f"  {'micro-ROS (serial & Wi-Fi)':<40}{'8 B UInt64':>15}{'~72 B String':>15}")
    print()
    print("  Note: micro-ROS sizes are application-level; XRCE-DDS adds")
    print("  framing overhead on top (typically ~20 bytes per message).")
    print()


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data_dir", default="./data")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    csvs = sorted(data_dir.glob("*.csv"))
    if not csvs:
        raise SystemExit(f"No CSVs in {data_dir}")

    df = pd.concat([pd.read_csv(c) for c in csvs], ignore_index=True)
    df["rtt_ms"] = pd.to_numeric(df["rtt_ms"], errors="coerce")

    print(f"Loaded {len(df):,} records from {len(csvs)} files")
    print(f"Configs found: {sorted(df['config'].unique())}")
    print(f"Frequencies found: {sorted(df['frequency_hz'].unique())}")
    print()

    print("RTT and Delivery Statistics (mean ± 95% CI across 10 runs)")
    print("=" * 80)
    print()
    print_rtt_table(df)

    analyze_payloads()


if __name__ == "__main__":
    main()
