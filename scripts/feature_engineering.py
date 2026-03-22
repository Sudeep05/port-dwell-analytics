"""
feature_engineering.py — Feature Engineering (Pipeline Stage 2)

Transforms validated container data into analysis-ready features: per-container
dwell metrics, per-block-per-day utilization, hourly gate throughput, and
storage cost calculations.

Usage:
    python scripts/feature_engineering.py \
        --input data/validated_containers.csv \
        --yard-config data/yard_config.json \
        --tariff-config data/tariff_config.json \
        --params '{"overstay_threshold_days": 7}' \
        --output-container data/dwell_features.csv \
        --output-block data/block_daily_features.csv

Outputs:
    - dwell_features.csv: Per-container features (dwell, TEU, cost, flow path)
    - block_daily_features.csv: Per-block-per-day utilization + hourly gate features
"""

import argparse
import json
import sys
import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# ISO 6346 Derivation
# ---------------------------------------------------------------------------

ISO_SIZE_MAP = {"2": 20, "4": 40, "L": 45}
ISO_HEIGHT_HC = {"5"}  # second character indicates high-cube
ISO_TYPE_MAP = {
    "G": "dry", "R": "reefer", "T": "tank", "U": "special",
    "P": "special", "B": "dry",
}


def derive_iso_fields(df):
    """Derive size_ft, container_type, is_high_cube from iso_type_code."""
    if "iso_type_code" not in df.columns:
        df["is_high_cube"] = False
        df["iso_container_group"] = df.get("container_type", "unknown")
        return df

    has_iso = df["iso_type_code"].notna() & (df["iso_type_code"].str.len() >= 4)

    # Size from first character
    df.loc[has_iso, "_iso_size"] = df.loc[has_iso, "iso_type_code"].str[0].map(
        ISO_SIZE_MAP)

    # High-cube from second character
    df["is_high_cube"] = False
    df.loc[has_iso, "is_high_cube"] = (
        df.loc[has_iso, "iso_type_code"].str[1].isin(ISO_HEIGHT_HC))

    # Type from third character
    df.loc[has_iso, "_iso_type"] = df.loc[has_iso, "iso_type_code"].str[2].map(
        ISO_TYPE_MAP)

    # Use ISO-derived container group; fallback to container_type
    df["iso_container_group"] = df.get("container_type", "unknown")
    mask = has_iso & df["_iso_type"].notna()
    df.loc[mask, "iso_container_group"] = df.loc[mask, "_iso_type"]

    # Clean up temp columns
    df.drop(columns=["_iso_size", "_iso_type"], errors="ignore", inplace=True)

    return df


# ---------------------------------------------------------------------------
# Per-Container Features
# ---------------------------------------------------------------------------

def compute_dwell(df):
    """Compute dwell hours and days for containers with gate_out."""
    df["gate_in_time"] = pd.to_datetime(df["gate_in_time"])
    df["gate_out_time"] = pd.to_datetime(df["gate_out_time"])

    has_out = df["gate_out_time"].notna()
    df["dwell_hours"] = np.nan
    df.loc[has_out, "dwell_hours"] = (
        (df.loc[has_out, "gate_out_time"] - df.loc[has_out, "gate_in_time"])
        .dt.total_seconds() / 3600
    )
    df["dwell_days"] = df["dwell_hours"] / 24.0
    return df


def compute_teu(df):
    """Convert container size to TEU equivalent."""
    df["teu_equivalent"] = df["size_ft"].map({20: 1, 40: 2, 45: 2}).fillna(2).astype(int)
    return df


def compute_dwell_category(df, overstay_threshold_days):
    """Assign dwell categories: short, normal, long, overstay."""
    conditions = [
        df["dwell_hours"] < 24,
        df["dwell_days"].between(1, 3, inclusive="right"),
        df["dwell_days"].between(3, overstay_threshold_days, inclusive="right"),
        df["dwell_days"] > overstay_threshold_days,
    ]
    choices = ["short", "normal", "long", "overstay"]
    df["dwell_category"] = np.select(conditions, choices, default="unknown")
    df["is_overstay"] = (df["dwell_days"] > overstay_threshold_days).astype(int)
    return df


def compute_storage_cost(df, tariff_config):
    """Compute storage cost using tiered tariff structure."""
    if tariff_config is None:
        df["storage_cost_usd"] = np.nan
        return df

    free_days = tariff_config.get("free_days", {})
    tiers = tariff_config.get("storage_tiers", [])
    reefer_surcharge = tariff_config.get("reefer_surcharge_per_day", 0)
    hazmat_surcharge = tariff_config.get("hazardous_surcharge_per_day", 0)

    costs = []
    for _, row in df.iterrows():
        if pd.isna(row.get("dwell_days")):
            costs.append(np.nan)
            continue

        free = free_days.get(row.get("movement_type", "import"), 3)
        billable_days = max(0, row["dwell_days"] - free)

        if billable_days <= 0:
            base_cost = 0.0
        else:
            base_cost = 0.0
            remaining = billable_days
            for tier in sorted(tiers, key=lambda t: t["from_day"]):
                tier_start = tier["from_day"]
                tier_end = tier.get("to_day") or 9999
                rate = tier["rate_per_teu_per_day"]

                tier_days = max(0, min(remaining, tier_end - tier_start + 1))
                base_cost += tier_days * rate * row.get("teu_equivalent", 1)
                remaining -= tier_days
                if remaining <= 0:
                    break

        # Surcharges
        total_cost = base_cost
        ctype = row.get("container_type", "")
        dwell = row["dwell_days"]
        if ctype == "reefer":
            total_cost += reefer_surcharge * dwell * row.get("teu_equivalent", 1)
        elif ctype == "hazardous":
            total_cost += hazmat_surcharge * dwell * row.get("teu_equivalent", 1)

        costs.append(round(total_cost, 2))

    df["storage_cost_usd"] = costs
    return df


def compute_flow_path(df):
    """Derive flow path from gate in/out modes."""
    if "gate_in_mode" in df.columns and "gate_out_mode" in df.columns:
        has_both = df["gate_in_mode"].notna() & df["gate_out_mode"].notna()
        df["flow_path"] = "unknown"
        df.loc[has_both, "flow_path"] = (
            df.loc[has_both, "gate_in_mode"].astype(str) + "→" +
            df.loc[has_both, "gate_out_mode"].astype(str)
        )
    else:
        df["flow_path"] = "unknown"
    return df


# ---------------------------------------------------------------------------
# Per-Block-Per-Day Features
# ---------------------------------------------------------------------------

def compute_block_daily_features(df, yard_config):
    """Compute daily utilization metrics per yard block."""
    df_valid = df[df["gate_in_time"].notna()].copy()
    df_valid["date"] = df_valid["gate_in_time"].dt.date

    # Build date range
    all_dates = pd.date_range(
        df_valid["gate_in_time"].min().normalize(),
        df_valid["gate_in_time"].max().normalize(),
        freq="D"
    ).date

    blocks = df_valid["yard_block"].unique()

    # Build capacity lookup
    capacity_map = {}
    reefer_plug_map = {}
    if yard_config:
        for b in yard_config.get("blocks", []):
            capacity_map[b["block_id"]] = b["teu_capacity"]
            if b.get("has_reefer_plugs"):
                reefer_plug_map[b["block_id"]] = b["reefer_plug_count"]

    records = []
    for date in all_dates:
        # Containers in yard on this date
        in_yard = df_valid[
            (df_valid["gate_in_time"].dt.date <= date) &
            ((df_valid["gate_out_time"].isna()) |
             (df_valid["gate_out_time"].dt.date >= date))
        ]

        for block in blocks:
            block_containers = in_yard[in_yard["yard_block"] == block]
            teu_occupied = int(block_containers["teu_equivalent"].sum())
            container_count = len(block_containers)

            # Utilization
            capacity = capacity_map.get(block)
            if capacity and capacity > 0:
                util_pct = round(teu_occupied / capacity * 100, 1)
            else:
                util_pct = None

            # Reefer plug utilization
            reefer_plug_util = None
            if block in reefer_plug_map:
                reefer_count = len(
                    block_containers[block_containers["container_type"] == "reefer"])
                plug_count = reefer_plug_map[block]
                if plug_count > 0:
                    reefer_plug_util = round(reefer_count / plug_count * 100, 1)

            # Average stack height
            avg_tier = None
            if "yard_tier" in block_containers.columns:
                tiers = block_containers["yard_tier"].dropna()
                if len(tiers) > 0:
                    avg_tier = round(float(tiers.mean()), 2)

            # Overstay ratio
            overstay_teu = int(
                block_containers[block_containers.get("is_overstay", 0) == 1]
                ["teu_equivalent"].sum()) if "is_overstay" in block_containers.columns else 0
            overstay_ratio = (round(overstay_teu / teu_occupied, 3)
                              if teu_occupied > 0 else 0)

            # Type mix
            type_counts = block_containers["container_type"].value_counts()
            type_mix = (type_counts / len(block_containers) * 100).round(1).to_dict() \
                if len(block_containers) > 0 else {}

            records.append({
                "date": date,
                "yard_block": block,
                "container_count": container_count,
                "teu_occupied": teu_occupied,
                "teu_capacity": capacity_map.get(block),
                "block_utilization_pct": util_pct,
                "reefer_plug_util_pct": reefer_plug_util,
                "avg_stack_height": avg_tier,
                "overstay_teu_ratio": overstay_ratio,
                "type_mix": json.dumps(type_mix),
            })

    return pd.DataFrame(records)


def compute_gate_hourly(df):
    """Compute hourly gate throughput features."""
    df_valid = df.copy()
    events = []

    # Gate-in events
    gate_in = df_valid[df_valid["gate_in_time"].notna()][["gate_in_time"]].copy()
    gate_in["hour"] = gate_in["gate_in_time"].dt.hour
    gate_in["date"] = gate_in["gate_in_time"].dt.date
    gate_in["direction"] = "in"
    events.append(gate_in.rename(columns={"gate_in_time": "timestamp"}))

    # Gate-out events
    gate_out = df_valid[df_valid["gate_out_time"].notna()][["gate_out_time"]].copy()
    gate_out["hour"] = gate_out["gate_out_time"].dt.hour
    gate_out["date"] = gate_out["gate_out_time"].dt.date
    gate_out["direction"] = "out"
    events.append(gate_out.rename(columns={"gate_out_time": "timestamp"}))

    all_events = pd.concat(events, ignore_index=True)

    hourly = (all_events.groupby(["date", "hour"])
              .size().reset_index(name="gate_throughput_hr"))

    # Peak hour flag: top 20% by volume
    threshold = hourly["gate_throughput_hr"].quantile(0.80)
    hourly["peak_hour_flag"] = (
        hourly["gate_throughput_hr"] >= threshold).astype(int)

    return hourly


def compute_vessel_surge(df, yard_config):
    """Detect vessel surge events (>15% capacity spike from single vessel)."""
    if "vessel_name" not in df.columns:
        return pd.DataFrame()

    df_valid = df[df["gate_in_time"].notna()].copy()
    df_valid["date"] = df_valid["gate_in_time"].dt.date

    total_capacity = sum(
        b["teu_capacity"] for b in yard_config.get("blocks", [])
    ) if yard_config else None

    if not total_capacity:
        return pd.DataFrame()

    threshold = total_capacity * 0.15

    vessel_daily = (df_valid.groupby(["date", "vessel_name"])
                    ["teu_equivalent"].sum().reset_index())
    surges = vessel_daily[vessel_daily["teu_equivalent"] >= threshold].copy()
    surges["vessel_surge_flag"] = 1

    return surges


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Feature Engineering (Stage 2)")
    parser.add_argument("--input", required=True,
                        help="Path to validated CSV")
    parser.add_argument("--yard-config", default=None)
    parser.add_argument("--tariff-config", default=None)
    parser.add_argument("--params", default="{}",
                        help="JSON string or path to params JSON")
    parser.add_argument("--output-container",
                        default="data/dwell_features.csv")
    parser.add_argument("--output-block",
                        default="data/block_daily_features.csv")
    args = parser.parse_args()

    print("=" * 60)
    print("STAGE 2: Feature Engineering")
    print("=" * 60)

    # Load data
    df = pd.read_csv(args.input)
    df["gate_in_time"] = pd.to_datetime(df["gate_in_time"])
    df["gate_out_time"] = pd.to_datetime(df["gate_out_time"])

    # Load configs
    yard_config = None
    if args.yard_config:
        with open(args.yard_config) as f:
            yard_config = json.load(f)
        print(f"  Yard config loaded: {len(yard_config.get('blocks', []))} blocks")

    tariff_config = None
    if args.tariff_config:
        with open(args.tariff_config) as f:
            tariff_config = json.load(f)
        print(f"  Tariff config loaded: {tariff_config.get('currency', 'N/A')}")

    # Parse params
    params = json.loads(args.params) if isinstance(args.params, str) else args.params
    overstay_threshold = params.get("overstay_threshold_days", 7)
    print(f"  Overstay threshold: {overstay_threshold} days")

    # ----- Per-Container Features -----
    print("\n  Computing per-container features...")
    df = derive_iso_fields(df)
    df = compute_dwell(df)
    df = compute_teu(df)
    df = compute_dwell_category(df, overstay_threshold)
    df = compute_storage_cost(df, tariff_config)
    df = compute_flow_path(df)

    # Summary
    has_dwell = df["dwell_hours"].notna()
    print(f"    Containers with dwell: {has_dwell.sum()}")
    print(f"    Mean dwell: {df.loc[has_dwell, 'dwell_days'].mean():.1f} days")
    print(f"    Overstay count: {df['is_overstay'].sum()}")
    if df["storage_cost_usd"].notna().any():
        print(f"    Total storage revenue: "
              f"${df['storage_cost_usd'].sum():,.0f}")

    # Save container features
    df.to_csv(args.output_container, index=False)
    print(f"    Saved: {args.output_container} ({len(df)} rows)")

    # ----- Per-Block-Per-Day Features -----
    print("\n  Computing block-daily features...")
    block_df = compute_block_daily_features(df, yard_config)
    print(f"    Block-day records: {len(block_df)}")

    # ----- Gate Hourly Features -----
    print("  Computing gate throughput...")
    hourly_df = compute_gate_hourly(df)
    print(f"    Hourly records: {len(hourly_df)}")

    # ----- Vessel Surge Detection -----
    print("  Detecting vessel surges...")
    surge_df = compute_vessel_surge(df, yard_config)
    if len(surge_df) > 0:
        print(f"    Surge events detected: {len(surge_df)}")
    else:
        print("    No surge events detected")

    # Save block features
    block_df.to_csv(args.output_block, index=False)
    print(f"    Saved: {args.output_block} ({len(block_df)} rows)")

    # Save hourly and surge as supplementary
    hourly_df.to_csv(data_dir(args.output_block, "gate_hourly.csv"), index=False)
    if len(surge_df) > 0:
        surge_df.to_csv(data_dir(args.output_block, "vessel_surges.csv"),
                        index=False)

    # Validation checks
    print("\n  Validation checks:")
    inf_count = np.isinf(df.select_dtypes(include=[np.number])).sum().sum()
    print(f"    Infinite values: {inf_count}")
    nan_features = df[["dwell_hours", "teu_equivalent"]].isna().sum()
    print(f"    NaN in key features: {nan_features.to_dict()}")

    print("\n  ✓ Feature engineering complete. Proceed to Stage 3.")


def data_dir(base_path, filename):
    """Get path in same directory as base_path."""
    import os
    return os.path.join(os.path.dirname(base_path), filename)


if __name__ == "__main__":
    main()
