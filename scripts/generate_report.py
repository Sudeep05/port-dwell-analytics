"""
generate_report.py — Professional Report Generation (Pipeline Stage 6)

Compiles all pipeline outputs into a multi-section HTML report with embedded
charts, segment profiles, revenue impact analysis, and business recommendations.
Each section includes interpretive commentary explaining findings to stakeholders.

Usage:
    python scripts/generate_report.py \
        --container-features data/dwell_features.csv \
        --block-features data/block_daily_features.csv \
        --model-dir data/model_outputs \
        --quality-report data/data_quality_report.json \
        --yard-config data/yard_config.json \
        --tariff-config data/tariff_config.json \
        --output data/final_report.html

Output:
    Professional HTML report with embedded charts and stakeholder-facing insights.
"""

import argparse
import base64
import io
import json
import os
from datetime import datetime
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns


# ---------------------------------------------------------------------------
# Chart Generation Helpers
# ---------------------------------------------------------------------------

def fig_to_base64(fig):
    """Convert matplotlib figure to base64 string for HTML embedding."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight",
                facecolor="white", edgecolor="none")
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("utf-8")


def embed_existing_chart(path):
    """Read existing PNG chart and convert to base64."""
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def chart_dwell_distribution(df):
    """Histogram of dwell time distribution."""
    fig, ax = plt.subplots(figsize=(10, 5))
    data = df[df["dwell_days"].notna() & (df["dwell_days"] < 60)]["dwell_days"]
    ax.hist(data, bins=50, color="#1D9E75", edgecolor="white", alpha=0.85)
    ax.set_xlabel("Dwell Time (Days)", fontsize=12)
    ax.set_ylabel("Container Count", fontsize=12)
    ax.set_title("Container Dwell Time Distribution", fontsize=14, fontweight="bold")
    ax.axvline(data.median(), color="#E24B4A", linestyle="--", linewidth=1.5,
               label=f"Median: {data.median():.1f} days")
    ax.axvline(data.mean(), color="#534AB7", linestyle="--", linewidth=1.5,
               label=f"Mean: {data.mean():.1f} days")
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.2)
    return fig_to_base64(fig)


def chart_dwell_by_movement(df):
    """Faceted small-multiple histograms — one per movement type, stacked vertically.
    
    Each movement type gets its own panel so shapes don't overlap. Much clearer
    than overlaid histograms where import hides behind export.
    """
    data = df[df["dwell_days"].notna() & (df["dwell_days"] < 45)]
    mtypes = ["import", "export", "transhipment"]
    colors = {"import": "#378ADD", "export": "#1D9E75", "transhipment": "#D85A30"}
    
    fig, axes = plt.subplots(len(mtypes), 1, figsize=(10, 8), sharex=True)
    fig.suptitle("Dwell Time Distribution by Movement Type", fontsize=14, fontweight="bold", y=0.98)
    
    max_count = 0  # For consistent y-axis
    for mtype in mtypes:
        subset = data[data["movement_type"] == mtype]["dwell_days"]
        if len(subset) > 0:
            counts, _, _ = axes[0].hist(subset, bins=40)  # Just to get max
            max_count = max(max_count, counts.max())
            axes[0].clear()
    
    for i, mtype in enumerate(mtypes):
        ax = axes[i]
        subset = data[data["movement_type"] == mtype]["dwell_days"]
        if len(subset) > 0:
            ax.hist(subset, bins=40, color=colors.get(mtype, "#888"),
                    edgecolor="white", linewidth=0.5, alpha=0.85)
            median_val = subset.median()
            mean_val = subset.mean()
            ax.axvline(median_val, color="#E24B4A", linestyle="--", linewidth=1.2)
            
            # Stats annotation
            stats_text = (f"{mtype.title()}  |  n={len(subset):,}  |  "
                         f"median: {median_val:.1f}d  |  mean: {mean_val:.1f}d  |  "
                         f"P95: {subset.quantile(0.95):.1f}d")
            ax.text(0.98, 0.85, stats_text, transform=ax.transAxes,
                    fontsize=10, ha="right", va="top",
                    bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.8))
        
        ax.set_ylabel("Count", fontsize=10)
        ax.grid(True, alpha=0.15)
        ax.set_ylim(0, max_count * 1.15)
    
    axes[-1].set_xlabel("Dwell Time (Days)", fontsize=12)
    plt.tight_layout()
    return fig_to_base64(fig)


def chart_dwell_by_type(df):
    """Horizontal bar chart of mean dwell per container type with overstay %.
    
    Replaces box plots: a single glance tells you which container types dwell
    longest and what fraction overstay. No quartile knowledge required.
    """
    data = df[df["dwell_days"].notna()]
    type_stats = data.groupby("container_type").agg(
        mean_dwell=("dwell_days", "mean"),
        median_dwell=("dwell_days", "median"),
        count=("dwell_days", "count"),
        overstay_rate=("is_overstay", "mean"),
    ).sort_values("mean_dwell", ascending=True)

    fig, ax = plt.subplots(figsize=(10, 5))
    colors_map = {"dry": "#378ADD", "reefer": "#1D9E75", "empty": "#BA7517",
                  "hazardous": "#E24B4A", "special": "#534AB7"}
    bar_colors = [colors_map.get(t, "#888") for t in type_stats.index]

    bars = ax.barh(type_stats.index, type_stats["mean_dwell"], color=bar_colors,
                   edgecolor="white", height=0.6, alpha=0.85)

    for i, (ctype, row) in enumerate(type_stats.iterrows()):
        ax.text(row["mean_dwell"] + 0.2, i,
                f"  avg {row['mean_dwell']:.1f}d  |  median {row['median_dwell']:.1f}d  |  "
                f"{row['overstay_rate']*100:.0f}% overstay  |  n={int(row['count']):,}",
                va="center", fontsize=10, color="#444")

    ax.set_xlabel("Average Dwell Time (Days)", fontsize=12)
    ax.set_ylabel("")
    ax.set_title("Average Dwell Time by Container Type", fontsize=14, fontweight="bold")
    ax.grid(True, alpha=0.2, axis="x")
    ax.set_xlim(0, type_stats["mean_dwell"].max() * 2.2)
    plt.tight_layout()
    return fig_to_base64(fig)


def chart_dwell_cumulative(df):
    """Cumulative % curve — the killer stakeholder chart.
    
    Answers: 'What % of containers have left by day X?'
    This is the most intuitive chart for operations managers.
    """
    fig, ax = plt.subplots(figsize=(10, 5))
    data = df[df["dwell_days"].notna()]["dwell_days"].sort_values()
    cumulative_pct = np.arange(1, len(data) + 1) / len(data) * 100

    ax.plot(data.values, cumulative_pct, color="#085041", linewidth=2.5)
    ax.fill_between(data.values, cumulative_pct, alpha=0.08, color="#1D9E75")

    # Mark key percentiles
    for pct in [50, 75, 90, 95]:
        day_val = data.quantile(pct / 100)
        ax.axhline(y=pct, color="#ccc", linestyle="-", linewidth=0.5)
        ax.axvline(x=day_val, color="#ccc", linestyle="-", linewidth=0.5)
        ax.plot(day_val, pct, "o", color="#E24B4A", markersize=7, zorder=5)
        ax.annotate(f"{pct}% by day {day_val:.1f}",
                    xy=(day_val, pct), xytext=(day_val + 1.5, pct - 3),
                    fontsize=10, color="#333", fontweight="bold")

    ax.set_xlabel("Dwell Time (Days)", fontsize=12)
    ax.set_ylabel("Cumulative % of Containers Departed", fontsize=12)
    ax.set_title("Cumulative Container Departure Curve", fontsize=14, fontweight="bold")
    ax.set_xlim(0, min(60, data.quantile(0.99)))
    ax.set_ylim(0, 101)
    ax.grid(True, alpha=0.2)
    plt.tight_layout()
    return fig_to_base64(fig)


def chart_block_utilization_heatmap(block_df):
    """Heatmap of block utilization over time with readable date labels."""
    block_df = block_df.copy()
    block_df["date"] = pd.to_datetime(block_df["date"])
    block_df["block_utilization_pct"] = pd.to_numeric(
        block_df["block_utilization_pct"], errors="coerce")
    
    # Aggregate to weekly averages for cleaner display
    block_df["week"] = block_df["date"].dt.to_period("W").dt.start_time
    weekly = block_df.groupby(["yard_block", "week"])["block_utilization_pct"].mean().reset_index()
    
    pivot = weekly.pivot_table(index="yard_block", columns="week",
                                values="block_utilization_pct", aggfunc="mean")
    if pivot.empty:
        return None

    # Format column labels to readable dates
    pivot.columns = [d.strftime("%b %d") for d in pivot.columns]

    # Sort blocks by average utilization (busiest at top)
    pivot = pivot.loc[pivot.mean(axis=1).sort_values(ascending=False).index]

    fig, ax = plt.subplots(figsize=(14, max(4, len(pivot) * 0.7)))
    sns.heatmap(pivot, cmap="RdYlGn_r", ax=ax,
                cbar_kws={"label": "Utilization %", "shrink": 0.8},
                xticklabels=True, yticklabels=True,
                vmin=0, vmax=100, linewidths=0.5, linecolor="white",
                annot=False)
    
    # Rotate x-axis labels for readability
    ax.set_xticklabels(ax.get_xticklabels(), rotation=45, ha="right", fontsize=9)
    ax.set_yticklabels(ax.get_yticklabels(), fontsize=11, fontweight="bold")
    
    ax.set_xlabel("Week Starting", fontsize=12)
    ax.set_ylabel("Yard Block", fontsize=12)
    ax.set_title("Yard Block Utilization Over Time (Weekly Average)",
                 fontsize=14, fontweight="bold")
    plt.tight_layout()
    return fig_to_base64(fig)


def chart_segment_bar(segment_profiles):
    """Bar chart of container count by segment."""
    fig, ax = plt.subplots(figsize=(8, 5))
    segments = [f"Seg {s['cluster']}" for s in segment_profiles]
    counts = [s["count"] for s in segment_profiles]
    colors = sns.color_palette("Set2", len(segments))
    bars = ax.bar(segments, counts, color=colors, edgecolor="white")
    for bar, count in zip(bars, counts):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 10,
                f"{count:,}", ha="center", fontsize=10, fontweight="bold")
    ax.set_xlabel("Segment", fontsize=12)
    ax.set_ylabel("Container Count", fontsize=12)
    ax.set_title("Container Count by Dwell Segment", fontsize=14, fontweight="bold")
    ax.grid(True, alpha=0.2, axis="y")
    return fig_to_base64(fig)


def chart_revenue_by_segment(df, cluster_labels):
    """Revenue by segment bar chart."""
    merged = df.merge(cluster_labels, on="container_id", how="inner")
    if "storage_cost_usd" not in merged.columns or merged["storage_cost_usd"].isna().all():
        return None

    seg_rev = merged.groupby("cluster")["storage_cost_usd"].sum().round(0)

    fig, ax = plt.subplots(figsize=(8, 5))
    segments = [f"Seg {s}" for s in seg_rev.index]
    values = seg_rev.values
    colors = sns.color_palette("Set2", len(segments))
    bars = ax.bar(segments, values, color=colors, edgecolor="white")
    for bar, val in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 100,
                f"${val:,.0f}", ha="center", fontsize=9, fontweight="bold")
    ax.set_xlabel("Segment", fontsize=12)
    ax.set_ylabel("Storage Revenue (USD)", fontsize=12)
    ax.set_title("Storage Revenue by Dwell Segment", fontsize=14, fontweight="bold")
    ax.grid(True, alpha=0.2, axis="y")
    return fig_to_base64(fig)


def chart_gate_throughput(hourly_path):
    """Hourly gate throughput pattern."""
    if not os.path.exists(hourly_path):
        return None
    hourly = pd.read_csv(hourly_path)
    hourly_avg = hourly.groupby("hour")["gate_throughput_hr"].mean()

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.bar(hourly_avg.index, hourly_avg.values, color="#378ADD", edgecolor="white")
    ax.set_xlabel("Hour of Day", fontsize=12)
    ax.set_ylabel("Average Gate Movements", fontsize=12)
    ax.set_title("Hourly Gate Throughput Pattern", fontsize=14, fontweight="bold")
    ax.set_xticks(range(24))
    ax.grid(True, alpha=0.2, axis="y")
    return fig_to_base64(fig)


# ---------------------------------------------------------------------------
# Segment Archetype Labelling
# ---------------------------------------------------------------------------

ARCHETYPES = [
    {"label": "Fast Movers", "dwell_max": 1, "color": "#1D9E75"},
    {"label": "Efficient Operators", "dwell_max": 3, "color": "#378ADD"},
    {"label": "Standard Dwellers", "dwell_max": 7, "color": "#BA7517"},
    {"label": "Extended Stay", "dwell_max": 14, "color": "#D85A30"},
    {"label": "Overstayers", "dwell_max": 30, "color": "#E24B4A"},
    {"label": "Chronic Blockers", "dwell_max": 999, "color": "#791F1F"},
]


def label_segments(profiles):
    """Assign archetype labels to cluster profiles.
    
    When multiple segments get the same base label (e.g., two 'Efficient Operators'),
    differentiate by TEU size (20ft vs 40ft) and relative dwell within the group.
    This produces unique, operationally meaningful labels like:
    'Efficient Operators (20ft)' vs 'Efficient Operators (40ft)'
    """
    # First pass: assign base archetype by dwell
    for p in profiles:
        mean_dwell = p.get("mean_dwell_days", 0)
        for arch in ARCHETYPES:
            if mean_dwell <= arch["dwell_max"]:
                p["_base_label"] = arch["label"]
                p["color"] = arch["color"]
                break
        else:
            p["_base_label"] = "Chronic Blockers"
            p["color"] = "#791F1F"

    # Second pass: detect duplicate labels and differentiate
    from collections import Counter
    label_counts = Counter(p["_base_label"] for p in profiles)

    for p in profiles:
        base = p["_base_label"]
        if label_counts[base] == 1:
            p["label"] = base
        else:
            # Differentiate by TEU size
            teu = p.get("mean_teu", 1.5)
            size_tag = "20ft" if teu < 1.5 else "40ft"

            # Further differentiate by relative dwell within same-label group
            same_label = [pp for pp in profiles if pp["_base_label"] == base]
            same_label_sorted = sorted(same_label, key=lambda x: x.get("mean_dwell_days", 0))

            if len(same_label) == 2:
                p["label"] = f"{base} ({size_tag})"
            elif len(same_label) >= 3:
                rank = same_label_sorted.index(p)
                if rank == 0:
                    p["label"] = f"{base} ({size_tag})"
                elif rank == len(same_label) - 1:
                    p["label"] = f"{base} ({size_tag}, longest dwell)"
                else:
                    p["label"] = f"{base} ({size_tag}, mid-range)"
            else:
                p["label"] = f"{base} ({size_tag})"

    # Cleanup
    for p in profiles:
        p.pop("_base_label", None)

    return profiles


# ---------------------------------------------------------------------------
# HTML Report Template
# ---------------------------------------------------------------------------

CSS_BLOCK = """
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
         color: #2c2c2a; line-height: 1.6; background: #f8f7f4; padding: 24px; }
  .container { max-width: 1100px; margin: 0 auto; }
  .header { background: linear-gradient(135deg, #085041 0%, #0F6E56 100%);
             color: white; padding: 40px; border-radius: 12px; margin-bottom: 32px; }
  .header h1 { font-size: 28px; font-weight: 600; margin-bottom: 8px; }
  .header p { opacity: 0.85; font-size: 14px; }
  .section { background: white; border-radius: 12px; padding: 32px;
              margin-bottom: 24px; box-shadow: 0 1px 3px rgba(0,0,0,0.06); }
  .section h2 { font-size: 20px; font-weight: 600; color: #085041;
                 margin-bottom: 16px; padding-bottom: 8px;
                 border-bottom: 2px solid #E1F5EE; }
  .section h3 { font-size: 16px; font-weight: 600; margin: 16px 0 8px; }
  .metric-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                  gap: 16px; margin: 16px 0; }
  .metric { background: #f8f7f4; padding: 16px; border-radius: 8px;
             border-left: 4px solid #1D9E75; }
  .metric .value { font-size: 24px; font-weight: 700; color: #085041; }
  .metric .label { font-size: 12px; color: #888780; text-transform: uppercase;
                    letter-spacing: 0.5px; }
  .chart { text-align: center; margin: 20px 0; }
  .chart img { max-width: 100%; border-radius: 8px; border: 1px solid #e8e7e3; }
  table { width: 100%; border-collapse: collapse; margin: 16px 0; font-size: 14px; }
  th { background: #085041; color: white; padding: 10px 12px; text-align: left;
       font-weight: 500; }
  td { padding: 10px 12px; border-bottom: 1px solid #e8e7e3; }
  tr:nth-child(even) { background: #fafaf8; }
  .badge { display: inline-block; padding: 3px 10px; border-radius: 12px;
            font-size: 12px; font-weight: 600; }
  .badge-pass { background: #E1F5EE; color: #085041; }
  .badge-warn { background: #FAEEDA; color: #633806; }
  .badge-fail { background: #FCEBEB; color: #791F1F; }
  .recommendation { background: #E6F1FB; border-left: 4px solid #378ADD;
                     padding: 12px 16px; border-radius: 0 8px 8px 0; margin: 8px 0; }
  .warning { background: #FAEEDA; border-left: 4px solid #BA7517;
              padding: 12px 16px; border-radius: 0 8px 8px 0; margin: 8px 0; }
  .insight { background: #f0f7f4; border: 1px solid #c8e6d8; border-radius: 8px;
             padding: 16px 20px; margin: 16px 0; font-size: 14px; line-height: 1.7; }
  .insight .insight-title { font-weight: 600; color: #085041; margin-bottom: 6px;
                            font-size: 13px; text-transform: uppercase; letter-spacing: 0.5px; }
  .insight ul { padding-left: 18px; margin: 8px 0 0; }
  .insight li { margin: 4px 0; }
  .footer { text-align: center; color: #888780; font-size: 12px;
             margin-top: 32px; padding: 16px; }
"""


def generate_html_report(sections, terminal_name, timestamp):
    """Assemble final HTML report from section content."""
    html = "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n"
    html += "<meta charset=\"UTF-8\">\n"
    html += "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">\n"
    html += f"<title>Container Dwell Time Analysis — {terminal_name}</title>\n"
    html += f"<style>{CSS_BLOCK}</style>\n"
    html += "</head>\n<body>\n<div class=\"container\">\n"
    html += f"  <div class=\"header\">\n"
    html += f"    <h1>Container Dwell Time Analysis &amp; Yard Throughput Optimization</h1>\n"
    html += f"    <p>{terminal_name} &mdash; Report generated {timestamp}</p>\n"
    html += f"  </div>\n"
    html += "".join(sections)
    html += f"  <div class=\"footer\">\n"
    html += f"    Generated by Container Dwell Time Analytics Skill v1.0 &mdash; {timestamp}<br>\n"
    html += "    Pipeline: Data Validation &rarr; Feature Engineering &rarr; Multi-Algorithm Modelling &rarr;\n"
    html += "    Validation &rarr; Insight Generation &rarr; Report Generation\n"
    html += "  </div>\n</div>\n</body>\n</html>"
    return html


# ---------------------------------------------------------------------------
# Section Builders — each with interpretive commentary
# ---------------------------------------------------------------------------

def section_executive_summary(df, quality, cluster_info, forecast_info, block_df):
    """Section 1: Executive Summary."""
    has_dwell = df[df["dwell_days"].notna()]
    avg_dwell = has_dwell["dwell_days"].mean()
    median_dwell = has_dwell["dwell_days"].median()
    overstay_pct = (has_dwell["is_overstay"].sum() / len(has_dwell) * 100)
    total_rev = df["storage_cost_usd"].sum() if df["storage_cost_usd"].notna().any() else 0

    block_df_parsed = block_df.copy()
    block_df_parsed["block_utilization_pct"] = pd.to_numeric(
        block_df_parsed["block_utilization_pct"], errors="coerce")
    peak_util = block_df_parsed["block_utilization_pct"].max()

    best = cluster_info.get('best', {})

    s = '<div class="section">\n'
    s += '  <h2>1. Executive Summary</h2>\n'
    s += '  <div class="metric-grid">\n'
    s += f'    <div class="metric"><div class="value">{len(df):,}</div><div class="label">Total Containers</div></div>\n'
    s += f'    <div class="metric"><div class="value">{avg_dwell:.1f} days</div><div class="label">Average Dwell Time</div></div>\n'
    s += f'    <div class="metric"><div class="value">{overstay_pct:.1f}%</div><div class="label">Overstay Rate</div></div>\n'
    s += f'    <div class="metric"><div class="value">${total_rev:,.0f}</div><div class="label">Total Storage Revenue</div></div>\n'
    s += f'    <div class="metric"><div class="value">{peak_util:.0f}%</div><div class="label">Peak Block Utilization</div></div>\n'
    s += f'    <div class="metric"><div class="value">{best.get("k", "N/A")}</div><div class="label">Dwell Segments Found</div></div>\n'
    s += '  </div>\n'
    s += f'  <p>This report analyzes <strong>{len(df):,} container movements</strong> over '
    s += f'<strong>{quality.get("date_range", {}).get("span_days", "N/A")} days</strong>. '
    s += f'The average container dwell time is <strong>{avg_dwell:.1f} days</strong> '
    s += f'(median: {median_dwell:.1f} days), with <strong>{overstay_pct:.1f}%</strong> of containers exceeding the overstay threshold.</p>\n'
    s += '  <div class="insight">\n'
    s += '    <div class="insight-title">How to read this report</div>\n'
    s += '    This report is structured as a diagnostic tool for your terminal\'s yard operations. '
    s += '    <strong>Sections 1&ndash;4</strong> describe <em>what is happening</em> (data quality, dwell patterns, yard load). '
    s += '    <strong>Sections 5&ndash;6</strong> apply <em>analytical models</em> to segment container behaviour and forecast future utilization. '
    s += '    <strong>Section 7</strong> translates findings into <em>dollar-value business impact</em>. '
    s += '    <strong>Section 8</strong> provides <em>specific, actionable recommendations</em> per container segment.\n'
    s += '  </div>\n'
    s += '</div>'
    return s


def section_data_quality(quality):
    """Section 2: Data Quality Summary."""
    status = quality.get("status", "UNKNOWN")
    badge_class = {"PASS": "badge-pass", "WARN": "badge-warn",
                   "FAIL": "badge-fail"}.get(status, "badge-warn")

    warnings_html = ""
    for w in quality.get("warnings", []):
        warnings_html += f'<div class="warning">{w}</div>\n'

    s = '<div class="section">\n'
    s += '  <h2>2. Data Quality Summary</h2>\n'
    s += f'  <p>Status: <span class="badge {badge_class}">{status}</span></p>\n'
    s += '  <div class="metric-grid">\n'
    s += f'    <div class="metric"><div class="value">{quality.get("total_rows", 0):,}</div><div class="label">Total Rows</div></div>\n'
    s += f'    <div class="metric"><div class="value">{quality.get("valid_rows", 0):,}</div><div class="label">Valid Rows</div></div>\n'
    s += f'    <div class="metric"><div class="value">{quality.get("excluded_rows", 0):,}</div><div class="label">Excluded Rows</div></div>\n'
    s += f'    <div class="metric"><div class="value">{quality.get("unique_containers", 0):,}</div><div class="label">Unique Containers</div></div>\n'
    s += '  </div>\n'
    s += f'  <p>Date range: {quality.get("date_range", {}).get("start", "N/A")} to '
    s += f'{quality.get("date_range", {}).get("end", "N/A")} '
    s += f'({quality.get("date_range", {}).get("span_days", "N/A")} days)</p>\n'
    opt_cols = ', '.join(quality.get('optional_columns_present', [])) or 'None'
    s += f'  <p>Optional columns present: {opt_cols}</p>\n'
    yard_yn = 'Yes' if quality.get('yard_config_provided') else 'No'
    tariff_yn = 'Yes' if quality.get('tariff_config_provided') else 'No'
    s += f'  <p>Yard config provided: {yard_yn} | Tariff config provided: {tariff_yn}</p>\n'
    s += warnings_html
    s += '  <div class="insight">\n'
    s += '    <div class="insight-title">What this means</div>\n'
    s += '    Data quality checks ensure the analytics pipeline is working with clean, reliable records. '
    excluded = quality.get('excluded_rows', 0)
    total = quality.get('total_rows', 1)
    if excluded == 0:
        s += 'All records passed validation with no exclusions &mdash; this is an ideal dataset. '
    else:
        s += f'{excluded:,} rows ({excluded/total*100:.1f}%) were excluded due to data issues (e.g., missing timestamps, logical errors). '
    null_out = quality.get("column_quality", {}).get("gate_out_time", {}).get("null_pct", 0)
    if null_out > 0:
        s += f'{null_out:.1f}% of containers have no gate-out timestamp &mdash; these are containers <strong>currently still in the yard</strong> and are excluded from dwell time calculations but included in utilization analysis.'
    s += '\n  </div>\n'
    s += '</div>'
    return s


def section_dwell_analysis(df, charts):
    """Section 3: Dwell Time Distribution with interpretive commentary."""
    has_dwell = df[df["dwell_days"].notna()]
    cat_counts = has_dwell["dwell_category"].value_counts()
    mean_dwell = has_dwell["dwell_days"].mean()
    median_dwell = has_dwell["dwell_days"].median()
    p95 = has_dwell["dwell_days"].quantile(0.95)
    overstay_count = int(has_dwell["is_overstay"].sum())
    long_stay = int((has_dwell["dwell_days"] > 30).sum())

    cat_table = "".join(
        f"<tr><td>{cat}</td><td>{count:,}</td><td>{count/len(has_dwell)*100:.1f}%</td></tr>"
        for cat, count in cat_counts.items()
    )

    # Compute flow path dwell if available
    flow_insight = ""
    if "flow_path" in has_dwell.columns and has_dwell["flow_path"].nunique() > 1:
        fp_means = has_dwell.groupby("flow_path")["dwell_days"].agg(["mean", "count"])
        fp_means = fp_means[fp_means["count"] > 50].sort_values("mean", ascending=False)
        if len(fp_means) >= 2:
            slowest = fp_means.index[0]
            fastest = fp_means.index[-1]
            flow_insight = (
                f'<li><strong>Flow path impact:</strong> Containers on the <em>{slowest}</em> path '
                f'average {fp_means.loc[slowest, "mean"]:.1f} days dwell, while <em>{fastest}</em> '
                f'averages {fp_means.loc[fastest, "mean"]:.1f} days. '
            )
            if "rail" in slowest:
                flow_insight += 'Rail-bound containers dwell longer because rail departure schedules are less frequent than truck pickups. Consider coordinating additional rail services to reduce this gap.'
            flow_insight += '</li>\n'

    # Compute shipping line dwell if available
    line_insight = ""
    if "shipping_line" in has_dwell.columns and has_dwell["shipping_line"].nunique() > 1:
        sl_means = has_dwell.groupby("shipping_line")["dwell_days"].agg(["mean", "count"])
        sl_means = sl_means[sl_means["count"] > 100].sort_values("mean", ascending=False)
        if len(sl_means) >= 2:
            slowest_line = sl_means.index[0]
            fastest_line = sl_means.index[-1]
            line_insight = (
                f'<li><strong>Shipping line variation:</strong> <em>{slowest_line}</em> containers average '
                f'{sl_means.loc[slowest_line, "mean"]:.1f} days vs <em>{fastest_line}</em> at '
                f'{sl_means.loc[fastest_line, "mean"]:.1f} days. Engage slower lines about improving pickup performance.</li>\n'
            )

    s = '<div class="section">\n'
    s += '  <h2>3. Dwell Time Distribution Analysis</h2>\n'
    s += f'  <div class="chart"><img src="data:image/png;base64,{charts["dwell_dist"]}" alt="Dwell Distribution"></div>\n'
    s += '  <div class="insight">\n'
    s += '    <div class="insight-title">Reading the histogram</div>\n'
    s += f'    The histogram shows how container dwell times are distributed. The tall bars on the left represent '
    s += f'the majority of containers that move through the terminal within 1&ndash;5 days. The <strong>median '
    s += f'({median_dwell:.1f} days)</strong> is lower than the <strong>mean ({mean_dwell:.1f} days)</strong> because '
    s += f'a small number of long-dwelling containers pull the average up &mdash; this right-skewed "long tail" is '
    s += f'typical of port operations and represents customs delays, documentation disputes, and abandoned cargo.\n'
    s += '  </div>\n'

    # Cumulative departure curve
    if charts.get("dwell_cumulative"):
        s += f'  <div class="chart"><img src="data:image/png;base64,{charts["dwell_cumulative"]}" alt="Cumulative Departure Curve"></div>\n'
        s += '  <div class="insight">\n'
        s += '    <div class="insight-title">How to read the cumulative curve</div>\n'
        s += f'    This chart answers the most important operational question: <em>&ldquo;What percentage of containers '
        s += f'have left the yard by day X?&rdquo;</em> Each red dot marks a key milestone. '
        s += f'For example, <strong>50% of containers depart by day {has_dwell["dwell_days"].quantile(0.50):.1f}</strong>, '
        s += f'and <strong>90% depart by day {has_dwell["dwell_days"].quantile(0.90):.1f}</strong>. '
        s += f'The remaining {100 - 90}% &mdash; the long tail above the 90% line &mdash; are the containers '
        s += f'that consume disproportionate yard capacity and drive congestion. '
        s += f'<strong>{overstay_count:,} containers</strong> exceed the overstay threshold, and {long_stay:,} have dwelled more than 30 days.\n'
        s += '  </div>\n'

    # Movement type histogram
    s += f'  <div class="chart"><img src="data:image/png;base64,{charts["dwell_movement"]}" alt="Dwell by Movement"></div>\n'
    s += '  <div class="insight">\n'
    s += '    <div class="insight-title">Dwell patterns by movement type</div>\n'
    s += '    Each panel shows one movement type\'s dwell distribution separately, so you can compare shapes '
    s += '    without overlap. The red dashed line marks the median. The stats box in each panel shows count, '
    s += '    median, mean, and 95th percentile. Import containers typically dwell longest because they depend '
    s += '    on consignee pickup timing. Exports are tighter because they\'re time-bound to vessel departure '
    s += '    schedules. Transhipment has the shortest tail &mdash; these move vessel-to-vessel on fixed schedules.\n'
    s += '  </div>\n'

    # Container type bar chart
    s += f'  <div class="chart"><img src="data:image/png;base64,{charts["dwell_type"]}" alt="Dwell by Type"></div>\n'
    s += '  <div class="insight">\n'
    s += '    <div class="insight-title">Container type comparison</div>\n'
    s += '    Each bar shows the average dwell time for that container type. The annotations show median dwell, '
    s += '    overstay percentage, and container count. Types with higher overstay rates are consuming '
    s += '    disproportionate yard capacity and should be targeted for clearance improvement.\n'
    s += '    <ul>\n'
    s += f'    <li>95% of all containers leave within <strong>{p95:.1f} days</strong>. The remaining 5% are the long tail driving congestion.</li>\n'
    s += f'    {flow_insight}'
    s += f'    {line_insight}'
    s += '    </ul>\n'
    s += '  </div>\n'

    s += '  <h3>Dwell Category Breakdown</h3>\n'
    s += '  <table>\n    <tr><th>Category</th><th>Count</th><th>Percentage</th></tr>\n'
    s += f'    {cat_table}\n'
    s += '  </table>\n'
    s += '  <div class="insight">\n'
    s += '    <div class="insight-title">Dwell categories explained</div>\n'
    s += '    <strong>Short</strong> (&lt;24h): Transhipment or pre-cleared imports moving through rapidly. '
    s += '    <strong>Normal</strong> (1&ndash;3 days): Standard operations within free period. '
    s += '    <strong>Long</strong> (3&ndash;7 days): Approaching or at free-day limit; may start incurring charges. '
    s += '    <strong>Overstay</strong> (&gt;7 days): Beyond the threshold; generating demurrage revenue but consuming yard capacity.\n'
    s += '  </div>\n'
    s += '</div>'
    return s


def section_yard_utilization(block_df, charts):
    """Section 4: Yard Utilization with insights."""
    block_df_p = block_df.copy()
    block_df_p["block_utilization_pct"] = pd.to_numeric(
        block_df_p["block_utilization_pct"], errors="coerce")

    block_summary = block_df_p.groupby("yard_block").agg(
        mean_util=("block_utilization_pct", "mean"),
        max_util=("block_utilization_pct", "max"),
        mean_teu=("teu_occupied", "mean"),
    ).round(1)

    rows = "".join(
        f"<tr><td>{block}</td><td>{r['mean_util']:.1f}%</td>"
        f"<td>{r['max_util']:.1f}%</td><td>{r['mean_teu']:.0f}</td></tr>"
        for block, r in block_summary.iterrows()
    )

    # Find congested and under-used blocks
    congested = block_summary[block_summary["max_util"] > 75]
    underused = block_summary[block_summary["mean_util"] < 30]

    heatmap_html = ""
    if charts.get("util_heatmap"):
        heatmap_html = f'<div class="chart"><img src="data:image/png;base64,{charts["util_heatmap"]}" alt="Utilization Heatmap"></div>\n'

    s = '<div class="section">\n'
    s += '  <h2>4. Yard Utilization Analysis</h2>\n'
    s += heatmap_html
    s += '  <div class="insight">\n'
    s += '    <div class="insight-title">Reading the heatmap</div>\n'
    s += '    Each row is a yard block (busiest at top); each column is a week. '
    s += '    <strong>Green = low utilization</strong> (plenty of space), '
    s += '    <strong>yellow = moderate (40&ndash;65%)</strong>, '
    s += '    <strong>orange/red = high utilization (65%+)</strong> (approaching capacity). '
    s += '    Industry benchmark: sustained utilization above <strong>75&ndash;80%</strong> causes operational congestion '
    s += '    (more reshuffles, slower crane operations, gate delays). '
    s += '    Look for blocks that are consistently yellow/orange &mdash; these are your chronic congestion risks. '
    s += '    Blocks that are consistently dark green may be candidates for reallocation.\n'
    s += '  </div>\n'
    s += '  <h3>Block Summary</h3>\n'
    s += '  <table>\n    <tr><th>Block</th><th>Avg Utilization</th><th>Peak Utilization</th><th>Avg TEU</th></tr>\n'
    s += f'    {rows}\n'
    s += '  </table>\n'

    s += '  <div class="insight">\n'
    s += '    <div class="insight-title">Block-level findings</div>\n'
    s += '    <ul>\n'
    if len(congested) > 0:
        for block, r in congested.iterrows():
            s += f'    <li><strong>{block}</strong> peaked at {r["max_util"]:.0f}% utilization &mdash; '
            s += f'this block experienced congestion events. Consider redistributing containers or increasing clearance speed for this block.</li>\n'
    else:
        s += '    <li>No blocks exceeded the 75% congestion threshold &mdash; yard capacity is currently healthy.</li>\n'
    if len(underused) > 0:
        blocks_str = ", ".join(underused.index)
        s += f'    <li>Blocks {blocks_str} are under-utilized (avg &lt;30%). These may be specialty blocks (hazardous, reefer) with lower volume by design, or candidates for reallocation.</li>\n'
    s += '    </ul>\n'
    s += '  </div>\n'
    s += '</div>'
    return s


def section_segmentation(cluster_info, charts):
    """Section 5: Segmentation Results with interpretation."""
    profiles = label_segments(cluster_info.get("segment_profiles", []))

    profile_rows = ""
    for p in profiles:
        label = p.get('label', 'Segment ' + str(p.get('cluster', '?')))
        color = p.get('color', '#333')
        count = p.get('count', 0)
        dwell = p.get('mean_dwell_days', 0)
        teu = p.get('mean_teu', 0)
        cost = p.get('mean_storage_cost', 0) or 0
        profile_rows += (
            f"<tr><td><span style='color:{color};font-weight:600'>"
            f"{label}</span></td>"
            f"<td>{count:,}</td><td>{dwell:.1f}</td>"
            f"<td>{teu:.1f}</td>"
            f"<td>${cost:,.0f}</td></tr>\n"
        )

    chart_htmls = ""
    for key, alt in [("elbow", "Elbow Plot"), ("silhouette", "Silhouette Comparison"),
                      ("dendrogram", "Dendrogram"), ("centroid", "Centroid Comparison")]:
        if charts.get(key):
            chart_htmls += f'<div class="chart"><img src="data:image/png;base64,{charts[key]}" alt="{alt}"></div>\n'

    best = cluster_info.get("best", {})

    s = '<div class="section">\n'
    s += '  <h2>5. Segmentation Results</h2>\n'
    s += f'  <p>Best model: <strong>{best.get("algorithm", "N/A")}</strong> with '
    s += f'  <strong>k={best.get("k", "N/A")}</strong> segments. '
    s += f'  Silhouette score: <strong>{best.get("silhouette_score", "N/A")}</strong> '
    s += f'  ({best.get("quality", "N/A")})</p>\n'
    s += chart_htmls

    s += '  <div class="insight">\n'
    s += '    <div class="insight-title">Understanding the clustering charts</div>\n'
    s += '    <ul>\n'
    s += '    <li><strong>Elbow Plot:</strong> Shows how adding more clusters reduces within-cluster variation. The "elbow" (where the curve bends) suggests the natural number of groups in the data.</li>\n'
    s += '    <li><strong>Silhouette Score:</strong> Measures how well-separated the clusters are (0 to 1). Higher is better. Scores above 0.5 indicate clear, distinct groups. The curve shows scores for k=2 through k=10 for both K-Means and Hierarchical.</li>\n'
    s += '    <li><strong>Dendrogram:</strong> The hierarchical clustering tree shows how containers merge into groups from bottom to top. The red dashed line marks where we "cut" the tree to get our chosen number of segments. Tall vertical lines before a merge indicate well-separated groups.</li>\n'
    s += '    <li><strong>Centroid Comparison:</strong> This is the key interpretability chart &mdash; it shows <em>what makes each segment different</em>. Each cluster of bars represents one feature (dwell, TEU, cost, weight). Segments with tall bars on &ldquo;Dwell Hours&rdquo; but short bars on &ldquo;TEU&rdquo; are defined by long dwell, not container size. This is the unsupervised learning equivalent of feature importance.</li>\n'

    s += '    </ul>\n'
    s += '  </div>\n'

    s += '  <div class="insight">\n'
    s += '    <div class="insight-title">Why data-driven segmentation instead of fixed rules?</div>\n'
    s += '    You could classify containers with fixed rules (e.g., &ldquo;under 3 days = fast, over 7 = overstay&rdquo;). '
    s += '    However, fixed rules are arbitrary &mdash; the right threshold depends on your terminal\'s specific patterns. '
    s += '    K-Means clustering lets the <strong>data reveal natural groupings</strong> based on actual dwell time, '
    s += '    container size (TEU), and storage cost together. The algorithm finds where the real breaks are in '
    s += '    <em>your</em> data, not where a textbook says they should be. This means the segments are specific to '
    s += '    your terminal\'s operations and will shift as your operations change over time.\n'
    s += '  </div>\n'

    # --- Enriched segment profile table ---
    s += '  <h3>Segment Profiles</h3>\n'
    s += '  <table>\n    <tr><th>Segment</th><th>Count</th><th>Avg Dwell</th><th>Median Dwell</th>'
    s += '<th>Overstay %</th><th>Dominant Type</th><th>Dominant Movement</th><th>Top Flow Path</th><th>Avg Cost</th></tr>\n'
    for p in sorted(profiles, key=lambda x: x.get("mean_dwell_days", 0)):
        label = p.get('label', 'Segment ' + str(p.get('cluster', '?')))
        color = p.get('color', '#333')
        count = p.get('count', 0)
        mean_d = p.get('mean_dwell_days', 0)
        med_d = p.get('median_dwell_days', mean_d)
        overstay = p.get('overstay_pct', 0)
        dom_type = p.get('dominant_container_type', 'N/A')
        type_pct = p.get('container_type_pct', 0)
        dom_move = p.get('dominant_movement', 'N/A')
        move_pct = p.get('movement_pct', 0)
        flow = p.get('dominant_flow_path', 'N/A')
        cost = p.get('mean_storage_cost', 0) or 0

        s += f'    <tr><td><span style="color:{color};font-weight:600">{label}</span></td>'
        s += f'<td>{count:,}</td><td>{mean_d:.1f}d</td><td>{med_d:.1f}d</td>'
        s += f'<td>{overstay:.0f}%</td>'
        s += f'<td>{dom_type} ({type_pct:.0f}%)</td>'
        s += f'<td>{dom_move} ({move_pct:.0f}%)</td>'
        s += f'<td>{flow}</td>'
        s += f'<td>${cost:,.0f}</td></tr>\n'
    s += '  </table>\n'

    # --- Per-segment narrative cards ---
    s += '  <h3>Segment-by-Segment Inference</h3>\n'
    for p in sorted(profiles, key=lambda x: x.get("mean_dwell_days", 0)):
        label = p.get("label", "Unknown")
        color = p.get("color", "#333")
        count = p.get("count", 0)
        mean_d = p.get("mean_dwell_days", 0)
        med_d = p.get("median_dwell_days", mean_d)
        overstay = p.get("overstay_pct", 0)
        dom_type = p.get("dominant_container_type", "N/A")
        type_pct = p.get("container_type_pct", 0)
        dom_move = p.get("dominant_movement", "N/A")
        move_pct = p.get("movement_pct", 0)
        flow = p.get("dominant_flow_path", "N/A")
        cost = p.get("mean_storage_cost", 0) or 0

        s += f'  <div style="border-left:4px solid {color};padding:12px 16px;margin:10px 0;'
        s += f'background:#fafaf8;border-radius:0 8px 8px 0">\n'
        s += f'    <strong style="color:{color};font-size:16px">{label}</strong>'
        s += f' &mdash; {count:,} containers ({count/sum(pp.get("count",0) for pp in profiles)*100:.1f}% of total)<br>\n'

        # WHO are they?
        s += f'    <strong>Who:</strong> Primarily <em>{dom_type}</em> containers ({type_pct:.0f}%), '
        s += f'mainly <em>{dom_move}</em> ({move_pct:.0f}%) movement, '
        s += f'most common flow path: <em>{flow}</em>.<br>\n'

        # WHAT is their behavior?
        s += f'    <strong>Behavior:</strong> Average dwell {mean_d:.1f} days (median {med_d:.1f}), '
        s += f'{overstay:.0f}% overstaying, avg storage cost ${cost:,.0f} per container.<br>\n'

        # WHY and WHAT TO DO — dynamic per archetype (match base label)
        if "Fast Movers" in label:
            s += '    <strong>Why:</strong> Transhipment cargo or pre-cleared imports with efficient pickup logistics.<br>\n'
            s += '    <strong>Action:</strong> These are your best performers. Protect their fast-track lane; '
            s += 'optimize gate scheduling to minimize their wait time. Any increase in this segment\'s size '
            s += 'means your terminal is getting more efficient.\n'
        elif "Efficient Operators" in label:
            s += '    <strong>Why:</strong> Well-coordinated supply chains with timely customs clearance and pickup.<br>\n'
            s += '    <strong>Action:</strong> The ideal segment to grow. Consider loyalty incentives for '
            s += 'shipping lines that consistently land here. These containers generate throughput revenue '
            s += 'without clogging yard space.\n'
        elif "Standard Dwellers" in label:
            s += '    <strong>Why:</strong> Typical operations approaching or at the free-day boundary. '
            s += 'Some delays from documentation or customs processing.<br>\n'
            s += '    <strong>Action:</strong> Monitor for drift toward Extended Stay. Automated pickup '
            s += 'reminders at day 3&ndash;4 can nudge containers out before they cross into penalty territory. '
            s += 'Small improvements here have large aggregate impact due to segment size.\n'
        elif "Extended Stay" in label:
            s += '    <strong>Why:</strong> Customs holds, incomplete documentation, consignee delays, or '
            s += 'coordination gaps with freight forwarders. '
            if "rail" in str(flow).lower():
                s += 'The rail flow path suggests some containers are waiting for infrequent rail departures.<br>\n'
            else:
                s += '<br>\n'
            s += '    <strong>Action:</strong> Investigate root causes. Engage freight forwarders serving this segment. '
            s += 'These containers are generating demurrage revenue but consuming yard space for extended periods. '
            s += f'At ${cost:,.0f} avg storage cost per container, the revenue is real &mdash; but the capacity cost may be higher.\n'
        elif "Overstayers" in label:
            s += '    <strong>Why:</strong> Likely disputed cargo, failed customs clearance, or consignees '
            s += 'unable to take delivery. Some may be using your terminal as cheap warehousing.<br>\n'
            s += '    <strong>Action:</strong> Escalate demurrage notices immediately. Consider relocating '
            s += 'to overflow or peripheral blocks to free prime yard space. Engage shipping lines directly. '
            s += f'This segment generates significant revenue (${cost:,.0f}/container) but blocks capacity '
            s += 'that could serve multiple normal-dwell containers in the same period.\n'
        elif "Chronic Blockers" in label:
            s += '    <strong>Why:</strong> Almost certainly abandoned cargo, unclaimed empties awaiting '
            s += 'repositioning orders, or containers in legal disputes.<br>\n'
            s += '    <strong>Action:</strong> URGENT &mdash; initiate formal clearance procedures. '
            s += 'Assess legal options for disposal of abandoned cargo. Relocate immediately to peripheral '
            s += 'storage. Each container in this segment has been consuming a TEU-slot for '
            s += f'{mean_d:.0f}+ days &mdash; that\'s {mean_d:.0f} days of lost throughput capacity per slot.\n'
        else:
            s += f'    <strong>Action:</strong> Review this segment\'s characteristics and develop a targeted strategy.\n'

        s += '  </div>\n'

    s += '  <div class="insight">\n'
    s += '    <div class="insight-title">Key takeaway for terminal management</div>\n'
    s += '    The segmentation reveals that your containers are NOT one homogeneous group &mdash; they have '
    s += '    distinct behavior patterns requiring different management strategies. A blanket &ldquo;reduce dwell '
    s += '    time&rdquo; policy misses the nuance. Instead, target each segment with the specific action described '
    s += '    above. The highest ROI comes from converting <em>Extended Stay</em> containers into <em>Standard '
    s += '    Dwellers</em> (reduce by 3&ndash;5 days) and clearing <em>Overstayers</em> and <em>Chronic '
    s += '    Blockers</em> to free yard capacity for additional throughput.\n'
    s += '  </div>\n'
    s += '</div>'
    return s


def section_forecast(forecast_info, charts):
    """Section 6: Forecasting Results with interpretation."""
    m1 = forecast_info.get("model1", {})
    m2 = forecast_info.get("model2", {})
    best = forecast_info.get("best_model", "N/A")
    horizon = forecast_info.get("forecast_horizon_days", 14)
    best_mape = min(
        m1.get("metrics", {}).get("mape", 999),
        m2.get("metrics", {}).get("mape", 999)
    )

    forecast_chart = ""
    if charts.get("forecast"):
        forecast_chart = f'<div class="chart"><img src="data:image/png;base64,{charts["forecast"]}" alt="Forecast"></div>\n'

    s = '<div class="section">\n'
    s += '  <h2>6. Forecasting Results</h2>\n'
    s += '  <h3>Model Comparison</h3>\n'
    s += '  <table>\n    <tr><th>Model</th><th>MAPE</th><th>RMSE</th><th>MAE</th></tr>\n'
    s += f'    <tr><td>{m1.get("model","N/A")}</td><td>{m1.get("metrics",{}).get("mape","N/A")}%</td>'
    s += f'<td>{m1.get("metrics",{}).get("rmse","N/A")}</td><td>{m1.get("metrics",{}).get("mae","N/A")}</td></tr>\n'
    s += f'    <tr><td>{m2.get("model","N/A")}</td><td>{m2.get("metrics",{}).get("mape","N/A")}%</td>'
    s += f'<td>{m2.get("metrics",{}).get("rmse","N/A")}</td><td>{m2.get("metrics",{}).get("mae","N/A")}</td></tr>\n'
    s += '  </table>\n'
    s += f'  <p>Selected model: <strong>{best}</strong> (forecast horizon: {horizon} days)</p>\n'
    s += forecast_chart

    s += '  <div class="insight">\n'
    s += '    <div class="insight-title">Understanding the forecast</div>\n'
    s += '    <ul>\n'
    s += '    <li><strong>MAPE</strong> (Mean Absolute Percentage Error) measures forecast accuracy. '
    if best_mape < 10:
        s += '<strong>Under 10%</strong> = excellent accuracy. Your forecast is highly reliable.</li>\n'
    elif best_mape < 20:
        s += '<strong>10&ndash;20%</strong> = good accuracy. The forecast captures the main trends reliably.</li>\n'
    elif best_mape < 30:
        s += '<strong>20&ndash;30%</strong> = acceptable accuracy. Directional trends are captured but day-to-day precision is limited.</li>\n'
    else:
        s += f'<strong>{best_mape:.0f}%</strong> = limited accuracy. The forecast shows general direction but should not be used for precise daily planning. Consider providing more historical data (6+ months) for better results.</li>\n'
    s += '    <li>The <strong>shaded band</strong> around the forecast line represents the 95% confidence interval &mdash; the actual value is expected to fall within this range 95% of the time.</li>\n'
    s += '    <li>The forecast is based on <strong>historical patterns only</strong>. External events (vessel schedule changes, weather disruptions, policy changes) are not predicted.</li>\n'
    s += '    </ul>\n'
    s += '  </div>\n'
    s += '</div>'
    return s


def section_revenue(df, cluster_labels, tariff_config=None):
    """Section 7: Revenue & Cost Impact with full transparency and interpretation."""
    if df["storage_cost_usd"].isna().all():
        return ('<div class="section"><h2>7. Revenue & Cost Impact</h2>'
                '<div class="warning">Tariff configuration not provided. Revenue analysis skipped. '
                'Provide a tariff JSON to enable this section.</div></div>')

    total_rev = df["storage_cost_usd"].sum()
    overstay_rev = df[df["is_overstay"] == 1]["storage_cost_usd"].sum()
    overstay_teu = df[df["is_overstay"] == 1]["teu_equivalent"].sum()
    overstay_days = df[df["is_overstay"] == 1]["dwell_days"].mean()
    overstay_count = int((df["is_overstay"] == 1).sum())

    throughput_rev = 85
    if tariff_config:
        throughput_rev = tariff_config.get("avg_throughput_revenue_per_teu", 85)
    opportunity_cost_daily = overstay_teu * throughput_rev
    rev_pct = overstay_rev / total_rev * 100 if total_rev > 0 else 0
    demurrage_daily = overstay_rev / max(overstay_days, 1)
    net_position = "EXCEEDS" if opportunity_cost_daily > demurrage_daily else "is below"

    # Tariff assumptions table
    tariff_table = ""
    if tariff_config:
        currency = tariff_config.get("currency", "USD")
        free_days = tariff_config.get("free_days", {})
        tiers = tariff_config.get("storage_tiers", [])
        reefer_sur = tariff_config.get("reefer_surcharge_per_day", 0)
        hazmat_sur = tariff_config.get("hazardous_surcharge_per_day", 0)

        tier_rows = ""
        for t in tiers:
            to_day = t.get("to_day") or "&infin;"
            tier_rows += (f'<tr><td>Day {t["from_day"]}&ndash;{to_day} after free period</td>'
                          f'<td>${t["rate_per_teu_per_day"]}/TEU/day</td>'
                          f'<td>User-provided tariff config</td></tr>\n')

        tariff_table = '<h3>Tariff assumptions used in this analysis</h3>\n'
        tariff_table += '<div class="warning">Financial figures below are computed using the tariff structure '
        tariff_table += 'provided in tariff_config.json. Actual billed amounts may vary based on contractual '
        tariff_table += 'terms, volume discounts, and negotiated free-day allowances. Adjust the tariff '
        tariff_table += 'configuration file to reflect your terminal\'s specific rate card.</div>\n'
        tariff_table += '<table>\n  <tr><th>Parameter</th><th>Value</th><th>Source</th></tr>\n'
        tariff_table += f'  <tr><td>Currency</td><td>{currency}</td><td>User-provided</td></tr>\n'
        tariff_table += f'  <tr><td>Free days (import)</td><td>{free_days.get("import", "N/A")} days</td><td>User-provided</td></tr>\n'
        tariff_table += f'  <tr><td>Free days (export)</td><td>{free_days.get("export", "N/A")} days</td><td>User-provided</td></tr>\n'
        tariff_table += f'  <tr><td>Free days (transhipment)</td><td>{free_days.get("transhipment", "N/A")} days</td><td>User-provided</td></tr>\n'
        tariff_table += tier_rows
        tariff_table += f'  <tr><td>Reefer surcharge</td><td>${reefer_sur}/TEU/day</td><td>User-provided</td></tr>\n'
        tariff_table += f'  <tr><td>Hazardous surcharge</td><td>${hazmat_sur}/TEU/day</td><td>User-provided</td></tr>\n'
        tariff_table += f'  <tr><td>Avg throughput revenue</td><td>${throughput_rev}/TEU</td><td>User-provided (for opportunity cost)</td></tr>\n'
        tariff_table += '</table>\n'

    s = '<div class="section">\n'
    s += '  <h2>7. Revenue &amp; Cost Impact Analysis</h2>\n'
    s += tariff_table

    s += '  <h3>Revenue summary</h3>\n'
    s += '  <div class="metric-grid">\n'
    s += f'    <div class="metric"><div class="value">${total_rev:,.0f}</div><div class="label">Total Storage Revenue</div></div>\n'
    s += f'    <div class="metric"><div class="value">${overstay_rev:,.0f}</div><div class="label">Revenue from Overstayers</div></div>\n'
    s += f'    <div class="metric"><div class="value">{rev_pct:.1f}%</div><div class="label">Overstayer Revenue Share</div></div>\n'
    s += f'    <div class="metric" style="border-left-color:#E24B4A"><div class="value">${opportunity_cost_daily:,.0f}/day</div><div class="label">Opportunity Cost (Blocked Capacity)</div></div>\n'
    s += '  </div>\n'

    s += '  <h3>Opportunity cost analysis</h3>\n'
    s += f'  <p>Overstaying containers ({overstay_count:,} containers) occupy <strong>{overstay_teu:,.0f} TEU-slots</strong> '
    s += f'(avg dwell: {overstay_days:.1f} days). At <strong>${throughput_rev}/TEU</strong> '
    s += f'throughput revenue, these blocked slots represent '
    s += f'<strong>${opportunity_cost_daily:,.0f}/day</strong> in lost capacity &mdash; compared to '
    s += f'<strong>${demurrage_daily:,.0f}/day</strong> earned in demurrage.</p>\n'

    if opportunity_cost_daily > demurrage_daily:
        s += '  <div class="recommendation"><strong>Key insight:</strong> The opportunity cost of blocked capacity EXCEEDS demurrage revenue. Prioritize clearance of overstaying containers to unlock throughput capacity.</div>\n'
    else:
        s += '  <div class="recommendation"><strong>Key insight:</strong> Demurrage revenue currently covers the opportunity cost. Monitor for changes in throughput volume that could shift this balance.</div>\n'

    s += '  <div class="insight">\n'
    s += '    <div class="insight-title">What is opportunity cost and why it matters</div>\n'
    s += '    Every TEU-slot occupied by an overstaying container is a slot that <strong>cannot serve a new container</strong>. '
    s += f'    If your terminal earns ${throughput_rev} per TEU in handling/throughput revenue, then {overstay_teu:,} blocked TEU-slots '
    s += f'    represent ${opportunity_cost_daily:,.0f} in revenue that <em>could have been earned</em> each day those slots are occupied. '
    s += '    <br><br><strong>Important caveat:</strong> This is a <em>theoretical maximum</em> &mdash; it assumes every freed slot '
    s += '    would immediately be filled by a new revenue-generating container. In practice, actual recovered revenue depends '
    s += '    on your terminal\'s demand pipeline and vessel call schedule. Typically <strong>40&ndash;70%</strong> of the '
    s += '    theoretical maximum is realizable. Even at 50% realization, the impact is substantial and should inform '
    s += '    clearance prioritization.\n'
    s += '  </div>\n'

    s += '  <h3>What-if: throughput revenue sensitivity</h3>\n'
    s += '  <table>\n    <tr><th>If throughput revenue is...</th><th>Daily opportunity cost becomes...</th><th>vs demurrage earned</th></tr>\n'
    for mult, label in [(0.7, "-30%"), (1.0, "current"), (1.3, "+30%"), (1.5, "+50%")]:
        adj_rev = throughput_rev * mult
        adj_cost = overstay_teu * adj_rev
        vs = "Exceeds" if adj_cost > demurrage_daily else "Below"
        s += f'    <tr><td>${adj_rev:.0f}/TEU ({label})</td><td>${adj_cost:,.0f}/day</td><td>{vs} demurrage</td></tr>\n'
    s += '  </table>\n'
    s += '  <div class="insight">\n'
    s += '    <div class="insight-title">How to use the sensitivity table</div>\n'
    s += '    The table above shows how the opportunity cost calculation changes if your actual throughput revenue per TEU '
    s += '    is different from the configured value. If your terminal serves higher-value cargo or has premium service contracts, '
    s += '    the true opportunity cost may be significantly higher. Adjust the <code>avg_throughput_revenue_per_teu</code> value '
    s += '    in your tariff configuration to reflect your terminal\'s actual economics.\n'
    s += '  </div>\n'
    s += '</div>'
    return s


def section_recommendations(cluster_info):
    """Section 8: Business Recommendations."""
    profiles = label_segments(cluster_info.get("segment_profiles", []))

    recs = {
        "Fast Movers": "Optimize gate scheduling to reduce wait times. Pre-position near berth for transhipment efficiency.",
        "Efficient Operators": "Maintain current processes. Consider loyalty incentives for shipping lines with consistently low dwell.",
        "Standard Dwellers": "Monitor for drift toward Extended Stay. Send automated pickup reminders at day 3-4.",
        "Extended Stay": "Investigate root causes (customs holds, documentation gaps). Engage with freight forwarders for improved clearance timelines.",
        "Overstayers": "Escalate demurrage notices. Relocate to overflow areas to free prime yard space. Engage shipping lines directly for container clearance.",
        "Chronic Blockers": "Initiate formal clearance procedures. Assess legal options for abandoned cargo. Relocate to peripheral blocks immediately to free operational capacity.",
    }

    rec_html = ""
    for p in sorted(profiles, key=lambda x: x.get("mean_dwell_days", 0), reverse=True):
        label = p.get("label", "Unknown")
        # Match recommendation by base archetype
        rec = "Review segment characteristics and develop targeted strategy."
        for key, val in recs.items():
            if key in label:
                rec = val
                break
        # Add size-specific context
        teu = p.get("mean_teu", 1.5)
        if teu >= 1.5:
            rec += " Note: these are predominantly 40ft (2-TEU) containers — each one blocks double the yard capacity of a 20ft unit."
        rec_html += f'<div class="recommendation"><strong>{label}</strong> ({p["count"]:,} containers, avg {p["mean_dwell_days"]:.1f} days): {rec}</div>\n'

    s = '<div class="section">\n'
    s += '  <h2>8. Business Recommendations</h2>\n'
    s += '  <p>Recommendations are prioritized by segment dwell impact (longest-dwelling first):</p>\n'
    s += rec_html
    s += '  <div class="insight">\n'
    s += '    <div class="insight-title">Implementation priority</div>\n'
    s += '    Start with the top segment (longest dwell) as it has the highest financial impact per container. '
    s += '    Even small improvements in clearing overstaying containers can unlock significant yard capacity. '
    s += '    For example, reducing the overstayer segment\'s average dwell by just 2 days frees TEU-slots '
    s += '    equivalent to adding virtual yard capacity without any infrastructure investment.\n'
    s += '  </div>\n'
    s += '</div>'
    return s


def section_priority_action_list(df, cluster_labels):
    """Section 9: Priority Action List — top overstaying containers with actionable details.
    
    This is the 'pick up the phone' section. Instead of just saying '12% overstay',
    it gives the operator a list of specific containers to chase, who owns them,
    which vessel brought them, how long they've been sitting, and how much they're
    costing. This bridges the gap between analytics insight and operational action.
    """
    merged = df.merge(cluster_labels, on="container_id", how="inner")

    # Filter to overstaying containers
    overstay = merged[merged.get("is_overstay", pd.Series(dtype=float)) == 1].copy()
    if len(overstay) == 0:
        # Fallback: top dwellers even if no overstay flag
        overstay = merged.nlargest(50, "dwell_days").copy()
    
    # Sort by storage cost (highest cost = highest priority)
    sort_col = "storage_cost_usd" if "storage_cost_usd" in overstay.columns and overstay["storage_cost_usd"].notna().any() else "dwell_days"
    overstay = overstay.sort_values(sort_col, ascending=False)

    # Take top 30
    top_n = min(30, len(overstay))
    top = overstay.head(top_n)

    # Build columns dynamically based on what's available
    cols = ["container_id", "dwell_days"]
    headers = ["Container ID", "Dwell (days)"]
    
    if "yard_block" in top.columns:
        cols.append("yard_block")
        headers.append("Block")
    if "movement_type" in top.columns:
        cols.append("movement_type")
        headers.append("Movement")
    if "container_type" in top.columns:
        cols.append("container_type")
        headers.append("Type")
    if "size_ft" in top.columns:
        cols.append("size_ft")
        headers.append("Size")
    if "shipping_line" in top.columns and top["shipping_line"].notna().any():
        cols.append("shipping_line")
        headers.append("Shipping Line")
    if "vessel_name" in top.columns and top["vessel_name"].notna().any():
        cols.append("vessel_name")
        headers.append("Vessel")
    if "storage_cost_usd" in top.columns and top["storage_cost_usd"].notna().any():
        cols.append("storage_cost_usd")
        headers.append("Storage Cost")

    # Build table
    header_row = "".join(f"<th>{h}</th>" for h in headers)
    rows_html = ""
    for _, row in top.iterrows():
        cells = ""
        for col in cols:
            val = row.get(col, "")
            if col == "dwell_days" and pd.notna(val):
                cells += f'<td><strong>{val:.1f}</strong></td>'
            elif col == "storage_cost_usd" and pd.notna(val):
                cells += f'<td>${val:,.0f}</td>'
            elif col == "size_ft" and pd.notna(val):
                cells += f'<td>{int(val)}ft</td>'
            elif pd.notna(val):
                cells += f'<td>{val}</td>'
            else:
                cells += '<td>—</td>'
        rows_html += f'<tr>{cells}</tr>\n'

    total_overstay = len(overstay)
    total_cost = overstay["storage_cost_usd"].sum() if "storage_cost_usd" in overstay.columns else 0

    s = '<div class="section">\n'
    s += '  <h2>9. Priority Action List</h2>\n'
    s += f'  <p>The following <strong>{top_n} containers</strong> are your highest-priority clearance targets '
    s += f'(out of {total_overstay:,} total overstaying containers'
    if total_cost > 0:
        s += f', generating ${total_cost:,.0f} in total storage charges'
    s += '). These are sorted by storage cost — clearing the top of this list has the biggest financial and capacity impact.</p>\n'
    s += f'  <table>\n    <tr>{header_row}</tr>\n'
    s += rows_html
    s += '  </table>\n'
    s += '  <div class="insight">\n'
    s += '    <div class="insight-title">How to use this list</div>\n'
    s += '    <ul>\n'
    s += '    <li><strong>Contact shipping lines</strong> listed in the table — escalate demurrage notices for their specific containers.</li>\n'
    s += '    <li><strong>Check customs status</strong> for import containers — many long-dwell imports are stuck in customs clearance, not abandoned.</li>\n'
    s += '    <li><strong>Cross-reference with vessel visits</strong> — if multiple containers from the same vessel are overstaying, there may be a systemic issue (incomplete documentation, disputed cargo).</li>\n'
    s += '    <li><strong>Relocate chronic blockers</strong> — containers dwelling 30+ days should be moved to peripheral blocks to free prime operating space.</li>\n'
    s += '    <li>For the complete list of all containers with their segment assignments, see <code>dwell_features.csv</code> merged with <code>cluster_labels.csv</code>.</li>\n'
    s += '    </ul>\n'
    s += '  </div>\n'
    s += '</div>'
    return s


def section_limitations():
    """Section 10: Assumptions & Limitations."""
    s = '<div class="section">\n'
    s += '  <h2>10. Assumptions &amp; Limitations</h2>\n'
    s += '  <ul style="padding-left:20px;line-height:2">\n'
    s += '    <li>Dwell time is measured only for containers with both gate-in and gate-out timestamps. Containers still in yard are excluded from dwell calculations but included in utilization analysis.</li>\n'
    s += '    <li>Clustering assumes Euclidean distance in standardized feature space. Non-spherical cluster shapes may not be well captured by K-Means.</li>\n'
    s += '    <li>Forecasting models assume historical patterns continue. External disruptions (weather, labor actions, policy changes) are not modelled.</li>\n'
    s += '    <li>Storage cost calculations depend on the accuracy of the tariff configuration provided. Actual invoiced amounts may differ due to negotiated rates and volume discounts.</li>\n'
    s += '    <li>Yard utilization is computed from container records; physical constraints like broken equipment, reserved lanes, or maintenance areas are not modelled.</li>\n'
    s += '    <li>This skill analyzes containerized cargo only. General/breakbulk cargo requires a separate analytics methodology.</li>\n'
    s += '    <li><strong>Future enhancements:</strong> BAPLIE integration for predictive yard planning, equipment utilization correlation, real-time gate scheduling via MCP, Port Community System integration for customs clearance tracking.</li>\n'
    s += '  </ul>\n'
    s += '</div>'
    return s


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Report Generation (Stage 6)")
    parser.add_argument("--container-features", required=True)
    parser.add_argument("--block-features", required=True)
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--quality-report", required=True)
    parser.add_argument("--yard-config", default=None)
    parser.add_argument("--tariff-config", default=None)
    parser.add_argument("--output", default="data/final_report.html")
    args = parser.parse_args()

    print("=" * 60)
    print("STAGE 6: Report Generation")
    print("=" * 60)

    # Load all data
    df = pd.read_csv(args.container_features)
    block_df = pd.read_csv(args.block_features)

    with open(args.quality_report) as f:
        quality = json.load(f)

    with open(os.path.join(args.model_dir, "cluster_results.json")) as f:
        cluster_info = json.load(f)

    with open(os.path.join(args.model_dir, "forecast_results.json")) as f:
        forecast_info = json.load(f)

    cluster_labels = pd.read_csv(
        os.path.join(args.model_dir, "cluster_labels.csv"))

    # Terminal name
    terminal_name = "Container Terminal"
    if args.yard_config and os.path.exists(args.yard_config):
        with open(args.yard_config) as f:
            yc = json.load(f)
            terminal_name = yc.get("terminal_name", terminal_name)

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Generate charts
    print("  Generating charts...")
    charts = {}
    charts["dwell_dist"] = chart_dwell_distribution(df)
    charts["dwell_cumulative"] = chart_dwell_cumulative(df)
    charts["dwell_movement"] = chart_dwell_by_movement(df)
    charts["dwell_type"] = chart_dwell_by_type(df)
    charts["util_heatmap"] = chart_block_utilization_heatmap(block_df)
    charts["revenue"] = chart_revenue_by_segment(df, cluster_labels)
    charts["gate_throughput"] = chart_gate_throughput(
        os.path.join(os.path.dirname(args.block_features), "gate_hourly.csv"))

    # Embed model charts from Stage 3-4
    chart_dir = os.path.join(args.model_dir, "charts")
    charts["elbow"] = embed_existing_chart(os.path.join(chart_dir, "elbow_plot.png"))
    charts["silhouette"] = embed_existing_chart(
        os.path.join(chart_dir, "silhouette_comparison.png"))
    charts["dendrogram"] = embed_existing_chart(os.path.join(chart_dir, "dendrogram.png"))
    charts["centroid"] = embed_existing_chart(os.path.join(chart_dir, "centroid_comparison.png"))
    charts["forecast"] = embed_existing_chart(
        os.path.join(chart_dir, "forecast_plot.png"))

    # Load tariff config for revenue section transparency
    tariff_config = None
    if args.tariff_config and os.path.exists(args.tariff_config):
        with open(args.tariff_config) as f:
            tariff_config = json.load(f)

    # Build sections
    print("  Building report sections...")
    sections = [
        section_executive_summary(df, quality, cluster_info, forecast_info, block_df),
        section_data_quality(quality),
        section_dwell_analysis(df, charts),
        section_yard_utilization(block_df, charts),
        section_segmentation(cluster_info, charts),
        section_forecast(forecast_info, charts),
        section_revenue(df, cluster_labels, tariff_config),
        section_recommendations(cluster_info),
        section_priority_action_list(df, cluster_labels),
        section_limitations(),
    ]

    # Assemble HTML
    html = generate_html_report(sections, terminal_name, timestamp)

    # Save
    with open(args.output, "w") as f:
        f.write(html)

    file_size = os.path.getsize(args.output) / 1024
    print(f"\n  Report saved: {args.output} ({file_size:.0f} KB)")
    print("  ✓ Report generation complete.")


if __name__ == "__main__":
    main()
