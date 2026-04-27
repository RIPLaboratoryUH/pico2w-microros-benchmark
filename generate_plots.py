#!/usr/bin/env python3
"""
generate_plots.py — IEEE publication figures for
"Effectiveness of micro-ROS over WiFi"

Produces 9 figures:
    Figures 1-4: Per-config grouped bar charts (Median RTT + P95 RTT by
                 frequency, with 95% CI error bars and delivery-rate
                 annotations).
    Figures 5-7: Cross-config horizontal grouped bar charts, one per
                 frequency (Median RTT + P95 RTT across all 4 configs,
                 log x-axis, 20 ms reference line).
    Figure 8:    Full-width combined three-panel cross-config figure.
    Figure 9:    Full-width combined vertical cross-config figure.

Statistics:
    Each run (10 runs per cell) is the unit of replication.  For every
    (config, frequency) cell we compute a per-run median, per-run P95,
    and per-run delivery rate, then report the across-run mean with a
    Student-t 95% CI.

Configurations plotted (reliable QoS variants intentionally excluded):
    serial_adhoc, wifi_adhoc,
    serial_microros_besteffort, wifi_microros_besteffort

CSV files prefixed with "default_pm_" are archived (default power-save
enabled) runs and are EXCLUDED from all plots, which reflect the
final no-powersave data reported in the paper.

Usage:
    python3 generate_plots.py --data_dir ./data --out_dir ./outputs
    python3 generate_plots.py --ext pdf       # for IEEE final submission
"""

import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats


# ── Experiment definition ────────────────────────────────────────────────────

CONFIGS = [
    ("serial_adhoc",               "Serial, Ad-hoc",       "serial_adhoc"),
    ("wifi_adhoc",                 "WiFi, Ad-hoc",         "wifi_adhoc"),
    ("serial_microros_besteffort", "Serial, micro-ROS",    "serial_microros"),
    ("wifi_microros_besteffort",   "WiFi, micro-ROS",      "wifi_microros"),
]

FREQS = [1, 10, 100]
FREQ_LABELS = {1: "1 Hz", 10: "10 Hz", 100: "100 Hz"}

COLORS = {
    "serial_adhoc":               {"median": "#1f3a68", "p95": "#6b8bb8"},
    "serial_microros_besteffort": {"median": "#1f3a68", "p95": "#6b8bb8"},
    "wifi_adhoc":                 {"median": "#b35900", "p95": "#f0a060"},
    "wifi_microros_besteffort":   {"median": "#b35900", "p95": "#f0a060"},
}

Y_CAP_SERIAL = 130.0
Y_CAP_WIFI   = 260.0
REF_LINE_MS  = 20.0
FIG_W        = 3.5


# ── IEEE rcParams ─────────────────────────────────────────────────────────────

def apply_rc():
    mpl.rcParams["font.family"]       = "serif"
    mpl.rcParams["font.size"]         = 10
    mpl.rcParams["axes.labelsize"]    = 10
    mpl.rcParams["axes.titlesize"]    = 10
    mpl.rcParams["xtick.labelsize"]   = 9
    mpl.rcParams["ytick.labelsize"]   = 9
    mpl.rcParams["legend.fontsize"]   = 8
    mpl.rcParams["axes.spines.top"]   = False
    mpl.rcParams["axes.spines.right"] = False
    mpl.rcParams["axes.grid"]         = True
    mpl.rcParams["grid.alpha"]        = 0.3
    mpl.rcParams["grid.linewidth"]    = 0.4
    mpl.rcParams["axes.axisbelow"]    = True
    mpl.rcParams["errorbar.capsize"]  = 2.5
    mpl.rcParams["savefig.dpi"]       = 300
    mpl.rcParams["savefig.bbox"]      = "tight"
    mpl.rcParams["savefig.pad_inches"] = 0.02


# ── Data loading & statistics ────────────────────────────────────────────────

def load_data(data_dir):
    """Load all CSVs, EXCLUDING archived default_pm_* files."""
    all_csvs = sorted(data_dir.glob("*.csv"))
    if not all_csvs:
        raise FileNotFoundError(f"No CSVs in {data_dir}")

    csvs = [c for c in all_csvs if not c.name.startswith("default_pm_")]
    skipped = len(all_csvs) - len(csvs)
    if not csvs:
        raise FileNotFoundError(
            f"All CSVs in {data_dir} are default_pm_* archives; "
            f"no current data to plot."
        )

    df = pd.concat([pd.read_csv(c) for c in csvs], ignore_index=True)
    df["rtt_ms"] = pd.to_numeric(df["rtt_ms"], errors="coerce")
    keep = {c[0] for c in CONFIGS}
    df = df[df["config"].isin(keep)].copy()

    print(f"  Loaded {len(csvs)} CSV files "
          f"(skipped {skipped} archived default_pm_* files)")
    return df


def ci95(values):
    arr = np.asarray(values, dtype=float)
    arr = arr[~np.isnan(arr)]
    n = len(arr)
    if n == 0:
        return float("nan"), float("nan")
    if n == 1:
        return float(arr[0]), 0.0
    mean = arr.mean()
    sem = arr.std(ddof=1) / np.sqrt(n)
    tcrit = stats.t.ppf(0.975, df=n - 1)
    return float(mean), float(tcrit * sem)


def cell_stats(df, config, freq):
    sub = df[(df["config"] == config) & (df["frequency_hz"] == freq)]

    medians, p95s, deliveries = [], [], []
    for _, run_df in sub.groupby("run"):
        ok = run_df.loc[run_df["status"] == "ok", "rtt_ms"].dropna().values
        if len(ok) > 0:
            medians.append(float(np.median(ok)))
            p95s.append(float(np.percentile(ok, 95)))
        total = len(run_df)
        delivered = int((run_df["status"] == "ok").sum())
        deliveries.append(100.0 * delivered / total if total > 0 else float("nan"))

    med_m, med_hw = ci95(medians)
    p95_m, p95_hw = ci95(p95s)
    del_m, del_hw = ci95(deliveries)
    return {
        "median_mean": med_m, "median_hw": med_hw,
        "p95_mean":    p95_m, "p95_hw":    p95_hw,
        "delivery_mean": del_m, "delivery_hw": del_hw,
        "n_runs": len(medians),
    }


# ── Figures 1-4: Per-config grouped bar charts ───────────────────────────────

def _delivery_label(mean, hw):
    if np.isnan(mean):
        return None
    if mean >= 99.95:
        return None
    if np.isnan(hw) or hw == 0:
        return f"{mean:.1f}%"
    return f"{mean:.1f}% ±{hw:.1f}"


def plot_per_config(df, out_dir, ext):
    apply_rc()

    for idx, (key, label, slug) in enumerate(CONFIGS, start=1):
        is_wifi = key.startswith("wifi")
        y_cap = Y_CAP_WIFI if is_wifi else Y_CAP_SERIAL
        colors = COLORS[key]

        med_means, med_hws = [], []
        p95_means, p95_hws = [], []
        del_means, del_hws = [], []
        for f in FREQS:
            s = cell_stats(df, key, f)
            med_means.append(s["median_mean"])
            med_hws.append(s["median_hw"])
            p95_means.append(s["p95_mean"])
            p95_hws.append(s["p95_hw"])
            del_means.append(s["delivery_mean"])
            del_hws.append(s["delivery_hw"])

        fig, ax = plt.subplots(figsize=(FIG_W, 2.9))

        x = np.arange(len(FREQS))
        bar_w = 0.38

        ax.bar(
            x - bar_w/2, med_means, bar_w,
            yerr=med_hws,
            color=colors["median"], edgecolor="black", linewidth=0.5,
            label="Median RTT",
            error_kw=dict(ecolor="black", elinewidth=0.8),
        )
        ax.bar(
            x + bar_w/2, p95_means, bar_w,
            yerr=p95_hws,
            color=colors["p95"], edgecolor="black", linewidth=0.5,
            label="P95 RTT",
            error_kw=dict(ecolor="black", elinewidth=0.8),
        )

        ax.set_xticks(x)
        ax.set_xticklabels([FREQ_LABELS[f] for f in FREQS])
        ax.set_xlabel("Request Frequency")
        ax.set_ylabel("Round-Trip Time (ms)")
        ax.set_ylim(0, y_cap)
        ax.set_title(label)

        ax.yaxis.grid(True, alpha=0.3)
        ax.xaxis.grid(False)

        ax.legend(loc="upper left", framealpha=0.9, edgecolor="gray")

        for i, f in enumerate(FREQS):
            text = _delivery_label(del_means[i], del_hws[i])
            if text is None:
                continue
            bar_top = max(
                (med_means[i] or 0) + (med_hws[i] or 0),
                (p95_means[i] or 0) + (p95_hws[i] or 0),
            )
            y_text = min(bar_top + y_cap * 0.035, y_cap * 0.96)
            ax.text(
                x[i], y_text, text,
                ha="center", va="bottom",
                fontsize=7.5, color="#444444",
            )

        if key == "serial_microros_besteffort":
            ax.text(
                0.02, 0.97, "Error bars present but < 0.1 ms",
                transform=ax.transAxes,
                ha="left", va="top",
                fontsize=7, style="italic", color="#555555",
            )

        fig.tight_layout()
        out_path = out_dir / f"fig{idx}_{slug}.{ext}"
        fig.savefig(out_path)
        plt.close(fig)
        print(f"  Saved {out_path.name}")


# ── Figures 5-7: Cross-config horizontal grouped bar charts ──────────────────

def plot_cross_config(df, out_dir, ext):
    apply_rc()

    for fi, freq in enumerate(FREQS, start=5):
        fig, ax = plt.subplots(figsize=(FIG_W, 3.3))

        order = CONFIGS
        n = len(order)
        y_positions = np.arange(n)[::-1]
        bar_h = 0.36

        med_handle = None
        p95_handle = None

        for row_i, (key, label, _slug) in enumerate(order):
            y = y_positions[row_i]
            colors = COLORS[key]
            s = cell_stats(df, key, freq)

            med_bar = ax.barh(
                y + bar_h/2, s["median_mean"], bar_h,
                xerr=s["median_hw"],
                color=colors["median"], edgecolor="black", linewidth=0.5,
                label="Median RTT" if row_i == 0 else None,
                error_kw=dict(ecolor="black", elinewidth=0.8),
            )
            p95_bar = ax.barh(
                y - bar_h/2, s["p95_mean"], bar_h,
                xerr=s["p95_hw"],
                color=colors["p95"], edgecolor="black", linewidth=0.5,
                label="P95 RTT" if row_i == 0 else None,
                error_kw=dict(ecolor="black", elinewidth=0.8),
            )
            if med_handle is None: med_handle = med_bar
            if p95_handle is None: p95_handle = p95_bar

            text = _delivery_label(s["delivery_mean"], s["delivery_hw"])
            if text is not None and not np.isnan(s["median_mean"]):
                x_text = (s["median_mean"] or 0.01) * 1.15
                ax.text(
                    x_text, y + bar_h/2, text,
                    va="center", ha="left",
                    fontsize=7.5, color="#444444",
                )

        ax.set_yticks(y_positions)
        ax.set_yticklabels([label for (_k, label, _s) in order])
        ax.set_xscale("log")
        ax.set_xlabel("RTT (ms) — log scale")
        ax.set_title(f"Cross-Configuration Comparison — {FREQ_LABELS[freq]}")

        ax.xaxis.grid(True, alpha=0.3)
        ax.yaxis.grid(False)

        ax.axvline(REF_LINE_MS, linestyle="--", color="#666666",
                   linewidth=0.8, zorder=0)
        ymin, ymax = ax.get_ylim()
        ax.text(
            REF_LINE_MS * 1.05, ymax - 0.2,
            "20 ms threshold",
            fontsize=7, style="italic", color="#666666",
            ha="left", va="top",
        )

        ax.legend(
            handles=[med_handle, p95_handle],
            labels=["Median RTT", "P95 RTT"],
            loc="lower right", framealpha=0.9, edgecolor="gray",
        )

        fig.tight_layout()
        out_path = out_dir / f"fig{fi}_cross_{freq}hz.{ext}"
        fig.savefig(out_path)
        plt.close(fig)
        print(f"  Saved {out_path.name}")


# ── Figure 8: Combined three-panel cross-config (full-width IEEE) ─────────────

def plot_combined(df, out_dir, ext):
    apply_rc()
    mpl.rcParams["axes.grid.axis"] = "x"

    fig, axes = plt.subplots(1, 3, figsize=(7.16, 4.0), sharey=False)

    order = CONFIGS
    n = len(order)
    y_positions = np.arange(n)[::-1] * 1.3
    bar_h = 0.36

    med_handle = None
    p95_handle = None

    for col, (ax, freq) in enumerate(zip(axes, FREQS)):
        for row_i, (key, label, _slug) in enumerate(order):
            y = y_positions[row_i]
            colors = COLORS[key]
            s = cell_stats(df, key, freq)

            med_bar = ax.barh(
                y + bar_h / 2, s["median_mean"], bar_h,
                xerr=s["median_hw"],
                color=colors["median"], edgecolor="black", linewidth=0.4,
                hatch="",
                label="Median RTT" if (col == 0 and row_i == 0) else None,
                error_kw=dict(ecolor="black", elinewidth=0.7),
            )
            p95_bar = ax.barh(
                y - bar_h / 2, s["p95_mean"], bar_h,
                xerr=s["p95_hw"],
                color=colors["p95"], edgecolor="black", linewidth=0.4,
                hatch="//",
                label="P95 RTT" if (col == 0 and row_i == 0) else None,
                error_kw=dict(ecolor="black", elinewidth=0.7),
            )
            if med_handle is None:
                med_handle = med_bar
            if p95_handle is None:
                p95_handle = p95_bar

            del_m = s["delivery_mean"]
            del_hw = s["delivery_hw"]
            if not np.isnan(del_m):
                del_text = "100%" if del_m >= 99.95 else f"{del_m:.1f}%±{del_hw:.1f}"
            else:
                del_text = ""
            if del_text:
                ax.text(
                    0.01, y - bar_h - 0.08,
                    del_text,
                    va="top", ha="left",
                    fontsize=6.5, color="#666666", style="italic",
                    transform=ax.get_yaxis_transform(),
                )

        ax.set_xscale("log")
        ax.set_xlabel("RTT (ms)", fontsize=9)
        ax.set_title(FREQ_LABELS[freq], fontsize=9, fontweight="normal")
        ax.xaxis.grid(True, alpha=0.3)
        ax.yaxis.grid(False)
        ax.tick_params(axis="x", labelsize=8)

        ax.set_yticks(y_positions)
        if col == 0:
            ax.set_yticklabels([label for (_k, label, _s) in order], fontsize=8)
            ax.set_ylabel("Configuration", fontsize=9)
        else:
            ax.set_yticklabels([""] * n)
            ax.tick_params(axis="y", length=0)

        ax.set_ylim(y_positions[-1] - 0.8, y_positions[0] + 0.8)

    fig.legend(
        handles=[med_handle, p95_handle],
        labels=["Median RTT (solid)", "P95 RTT (hatched)"],
        loc="lower center",
        bbox_to_anchor=(0.5, -0.04),
        ncol=2,
        framealpha=0.9,
        edgecolor="gray",
        fontsize=8,
    )

    fig.suptitle("Cross-Configuration RTT Comparison", fontsize=10, y=1.01)
    fig.tight_layout(rect=[0, 0.06, 1, 1])

    out_path = out_dir / f"fig8_cross_combined.{ext}"
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved {out_path.name}")


# ── Figure 9: Combined three-panel cross-config, vertical bars ───────────────

def plot_combined_vertical(df, out_dir, ext):
    apply_rc()
    mpl.rcParams["axes.grid.axis"] = "y"

    SHORT_LABELS = [
        "Serial, Ad-hoc",
        "WiFi, Ad-hoc",
        "Serial, micro-ROS",
        "WiFi, micro-ROS",
    ]

    fig, axes = plt.subplots(1, 3, figsize=(7.16, 4.4), sharey=True)

    order = CONFIGS
    n = len(order)
    x_positions = np.arange(n)
    bar_w = 0.36

    med_handle = None
    p95_handle = None

    for col, (ax, freq) in enumerate(zip(axes, FREQS)):
        for xi, (key, label, _slug) in enumerate(order):
            x = x_positions[xi]
            colors = COLORS[key]
            s = cell_stats(df, key, freq)

            med_bar = ax.bar(
                x - bar_w / 2, s["median_mean"], bar_w,
                yerr=s["median_hw"],
                color=colors["median"], edgecolor="black", linewidth=0.4,
                hatch="",
                label="Median RTT" if (col == 0 and xi == 0) else None,
                error_kw=dict(ecolor="black", elinewidth=0.7),
            )
            p95_bar = ax.bar(
                x + bar_w / 2, s["p95_mean"], bar_w,
                yerr=s["p95_hw"],
                color=colors["p95"], edgecolor="black", linewidth=0.4,
                hatch="//",
                label="P95 RTT" if (col == 0 and xi == 0) else None,
                error_kw=dict(ecolor="black", elinewidth=0.7),
            )
            if med_handle is None:
                med_handle = med_bar
            if p95_handle is None:
                p95_handle = p95_bar

            # Delivery rate above the taller bar (mean ± CI, whole percents)
            del_m = s["delivery_mean"]
            del_hw = s["delivery_hw"]
            if not np.isnan(del_m):
                if del_m >= 99.95:
                    del_text = "100%"
                elif np.isnan(del_hw) or del_hw == 0:
                    del_text = f"{del_m:.0f}%"
                else:
                    del_text = f"{del_m:.0f}±{del_hw:.0f}%"
            else:
                del_text = ""
            if del_text:
                bar_top = max(
                    (s["median_mean"] or 0) + (s["median_hw"] or 0),
                    (s["p95_mean"] or 0) + (s["p95_hw"] or 0),
                )
                ax.text(
                    x, bar_top * 1.15,
                    del_text,
                    ha="center", va="bottom",
                    fontsize=6.5, color="#666666", style="italic",
                )

        ax.set_yscale("log")
        ax.set_title(FREQ_LABELS[freq], fontsize=9, fontweight="normal")
        ax.set_xticks(x_positions)
        ax.set_xticklabels(SHORT_LABELS, fontsize=7.5, rotation=35, ha="right")
        ax.yaxis.grid(True, alpha=0.3)
        ax.xaxis.grid(False)
        ax.tick_params(axis="y", labelsize=8)

        if col == 0:
            ax.set_ylabel("RTT (ms) — log scale", fontsize=9)

    fig.legend(
        handles=[med_handle, p95_handle],
        labels=["Median RTT (solid)", "P95 RTT (hatched)"],
        loc="lower center",
        bbox_to_anchor=(0.5, -0.04),
        ncol=2,
        framealpha=0.9,
        edgecolor="gray",
        fontsize=8,
    )

    fig.suptitle("Cross-Configuration RTT Comparison", fontsize=10, y=1.01)
    fig.tight_layout(rect=[0, 0.06, 1, 1])

    out_path = out_dir / f"fig9_cross_combined_vertical.{ext}"
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved {out_path.name}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--data_dir", default="./data")
    p.add_argument("--out_dir",  default="./outputs")
    p.add_argument("--ext",      default="png", choices=["png", "pdf"],
                   help="Figure file format (default: png per brief; "
                        "use pdf for final IEEE submission).")
    args = p.parse_args()

    data_dir = Path(args.data_dir)
    out_dir  = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Loading data from {data_dir} …")
    df = load_data(data_dir)
    print(f"  {len(df):,} records, "
          f"{df['config'].nunique()} configs, "
          f"{df['frequency_hz'].nunique()} frequencies")
    print()

    print("Generating per-config figures (1-4) …")
    plot_per_config(df, out_dir, args.ext)

    print("\nGenerating cross-config figures (5-7) …")
    plot_cross_config(df, out_dir, args.ext)

    print("\nGenerating combined cross-config figure (8) …")
    plot_combined(df, out_dir, args.ext)

    print("\nGenerating combined vertical cross-config figure (9) …")
    plot_combined_vertical(df, out_dir, args.ext)

    print(f"\n✓ All figures written to {out_dir}/ as .{args.ext}")


if __name__ == "__main__":
    main()