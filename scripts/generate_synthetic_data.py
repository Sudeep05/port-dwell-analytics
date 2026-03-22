"""
generate_synthetic_data.py — Synthetic Container Movement Data Generator (Vectorized)

Generates realistic container movement records for testing the Container Dwell Time
Analysis & Yard Throughput Optimization skill. Uses vectorized numpy/pandas operations
for fast generation (~30 seconds for 50K containers vs 25 minutes with loops).

Usage:
    python scripts/generate_synthetic_data.py \
        --num-containers 50000 \
        --start-date 2025-01-01 \
        --end-date 2025-06-30 \
        --seed 42 \
        --output data/synthetic_containers.csv \
        --yard-config-output data/yard_config.json \
        --tariff-config-output data/tariff_config.json

Outputs:
    - CSV file with container movement records
    - JSON yard configuration file
    - JSON tariff configuration file
"""

import argparse
import json
import time
from datetime import datetime, timedelta
import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Terminal configuration — models a realistic mid-size multi-purpose terminal
# (~300K TEU/year capacity)
# ---------------------------------------------------------------------------

YARD_CONFIG = {
    "terminal_name": "Greenfield Container Terminal — Berth 3",
    "blocks": [
        {"block_id": "A01", "rows": 8, "bays": 40, "max_tier": 5,
         "teu_capacity": 1600, "accepts_types": ["dry", "empty"],
         "has_reefer_plugs": False, "reefer_plug_count": 0},
        {"block_id": "A02", "rows": 8, "bays": 40, "max_tier": 5,
         "teu_capacity": 1600, "accepts_types": ["dry", "empty"],
         "has_reefer_plugs": False, "reefer_plug_count": 0},
        {"block_id": "B01", "rows": 8, "bays": 35, "max_tier": 5,
         "teu_capacity": 1400, "accepts_types": ["dry", "special"],
         "has_reefer_plugs": False, "reefer_plug_count": 0},
        {"block_id": "R01", "rows": 6, "bays": 25, "max_tier": 4,
         "teu_capacity": 720, "accepts_types": ["reefer"],
         "has_reefer_plugs": True, "reefer_plug_count": 180},
        {"block_id": "R02", "rows": 5, "bays": 20, "max_tier": 4,
         "teu_capacity": 480, "accepts_types": ["reefer"],
         "has_reefer_plugs": True, "reefer_plug_count": 100},
        {"block_id": "H01", "rows": 4, "bays": 15, "max_tier": 3,
         "teu_capacity": 270, "accepts_types": ["hazardous"],
         "has_reefer_plugs": False, "reefer_plug_count": 0},
        {"block_id": "E01", "rows": 8, "bays": 45, "max_tier": 6,
         "teu_capacity": 2160, "accepts_types": ["empty"],
         "has_reefer_plugs": False, "reefer_plug_count": 0},
    ],
    "gate_count_in": 6,
    "gate_count_out": 4
}

TARIFF_CONFIG = {
    "currency": "USD",
    "free_days": {"import": 3, "export": 5, "transhipment": 7},
    "storage_tiers": [
        {"from_day": 1, "to_day": 4, "rate_per_teu_per_day": 15},
        {"from_day": 5, "to_day": 10, "rate_per_teu_per_day": 30},
        {"from_day": 11, "to_day": 21, "rate_per_teu_per_day": 55},
        {"from_day": 22, "to_day": None, "rate_per_teu_per_day": 85}
    ],
    "reefer_surcharge_per_day": 25,
    "hazardous_surcharge_per_day": 18,
    "avg_throughput_revenue_per_teu": 85
}


# ---------------------------------------------------------------------------
# Lookup tables for vectorized generation
# ---------------------------------------------------------------------------

ISO_CODES_LIST = ["22G1", "42G1", "45G1", "22R1", "45R1", "22T1", "42P1", "22U1", "22G1_E", "42G1_E"]
ISO_WEIGHTS = np.array([0.24, 0.30, 0.22, 0.04, 0.08, 0.02, 0.01, 0.01, 0.03, 0.05])
ISO_WEIGHTS = ISO_WEIGHTS / ISO_WEIGHTS.sum()

ISO_SIZE = {"22G1": 20, "42G1": 40, "45G1": 40, "22R1": 20, "45R1": 40,
            "22T1": 20, "42P1": 40, "22U1": 20, "22G1_E": 20, "42G1_E": 40}
ISO_TYPE = {"22G1": "dry", "42G1": "dry", "45G1": "dry", "22R1": "reefer",
            "45R1": "reefer", "22T1": "hazardous", "42P1": "special",
            "22U1": "special", "22G1_E": "empty", "42G1_E": "empty"}
ISO_DISPLAY = {"22G1_E": "22G1", "42G1_E": "42G1"}  # empties show standard code

CLUSTER_NAMES = ["fast", "normal", "extended", "overstay", "chronic"]
CLUSTER_WEIGHTS = np.array([0.15, 0.52, 0.22, 0.08, 0.03])

SHIPPING_NAMES = ["MSC", "Maersk", "CMA CGM", "COSCO", "Hapag-Lloyd", "ONE", "Evergreen", "HMM", "ZIM"]
SHIPPING_WEIGHTS = np.array([0.22, 0.18, 0.14, 0.12, 0.10, 0.08, 0.07, 0.05, 0.04])
SHIPPING_WEIGHTS = SHIPPING_WEIGHTS / SHIPPING_WEIGHTS.sum()

LINE_DWELL_MULT = {"MSC": 0.90, "Maersk": 0.85, "CMA CGM": 0.95, "COSCO": 1.05,
                    "Hapag-Lloyd": 1.10, "ONE": 1.00, "Evergreen": 1.00, "HMM": 1.25, "ZIM": 1.35}

FLOW_DWELL_MULT = {"rail": 1.40, "barge": 1.20, "truck": 1.00, "vessel": 1.00}

VESSEL_NAMES = [
    "MSC ANNA", "MSC GULSUN", "Maersk Elba", "Maersk Seletar",
    "CMA CGM Marco Polo", "CMA CGM Antoine", "COSCO Shipping Universe",
    "COSCO Shipping Leo", "Hapag-Lloyd Express", "ONE Commitment",
    "Evergreen Champion", "HMM Copenhagen", "ZIM Antwerp",
    "MSC Lorena", "Maersk Enshi", "CMA CGM Concorde",
]

CARGO_NAMES = ["electronics", "food_perishable", "textiles", "chemicals", "machinery",
               "auto_parts", "furniture", "building_materials", "pharmaceuticals", "consumer_goods"]
CARGO_WEIGHTS = np.array([0.15, 0.12, 0.14, 0.08, 0.10, 0.09, 0.07, 0.08, 0.05, 0.12])
CARGO_WEIGHTS = CARGO_WEIGHTS / CARGO_WEIGHTS.sum()

# BIC-compliant prefixes: 3 owner letters + U (cargo container equipment identifier)
# Real registered codes for major shipping lines
CONTAINER_PREFIXES = ["MSCU", "MEDU", "MRKU", "MSKU",   # MSC
                      "MAEU", "MRSU", "MSKU",              # Maersk
                      "CMAU", "CGMU",                       # CMA CGM
                      "CCLU", "COSU",                       # COSCO
                      "HLCU", "HLXU",                       # Hapag-Lloyd
                      "ONEU", "KKFU",                       # ONE
                      "EISU", "EGHU",                       # Evergreen
                      "HMMU", "HDMU",                       # HMM
                      "ZIMU", "ZCSU"]                       # ZIM

HOUR_WEIGHTS = np.array([0.01]*6 + [0.06, 0.09, 0.11, 0.10, 0.09, 0.08,
                          0.08, 0.09, 0.08, 0.07, 0.05, 0.03] + [0.01]*6)
HOUR_WEIGHTS = HOUR_WEIGHTS / HOUR_WEIGHTS.sum()


# ---------------------------------------------------------------------------
# Block assignment lookup
# ---------------------------------------------------------------------------

def build_block_lookup():
    """Create type→block_ids mapping for fast assignment."""
    lookup = {}
    for b in YARD_CONFIG["blocks"]:
        for t in b["accepts_types"]:
            lookup.setdefault(t, []).append(b["block_id"])
    return lookup

def get_block_info(block_id):
    """Get block config by ID."""
    for b in YARD_CONFIG["blocks"]:
        if b["block_id"] == block_id:
            return b
    return YARD_CONFIG["blocks"][0]

BLOCK_LOOKUP = build_block_lookup()


# ---------------------------------------------------------------------------
# Vectorized generation
# ---------------------------------------------------------------------------

def generate_dataset(num_containers, start_date, end_date, seed=42):
    """Generate the complete dataset using vectorized numpy operations."""
    t0 = time.time()
    rng = np.random.default_rng(seed)
    n = num_containers

    date_start = pd.Timestamp(start_date)
    date_end = pd.Timestamp(end_date)
    total_days = (date_end - date_start).days

    print(f"  Generating {n:,} containers vectorized...")

    # --- 0. Generate container IDs with repeat visits (~8% duplicates) ---
    # In reality, the same physical container visits a terminal multiple times
    n_unique = int(n * 0.92)  # ~92% unique containers
    n_repeat = n - n_unique   # ~8% are repeat visits of existing containers

    # Generate unique IDs: 3 owner letters + U + 6 digits + check digit
    prefixes = rng.choice(CONTAINER_PREFIXES, size=n_unique)
    serials = rng.integers(100000, 999999, size=n_unique)
    # Simplified check digit (mod 10 of serial sum)
    check_digits = np.array([s % 10 for s in serials])
    unique_ids = np.array([f"{p}{s}{c}" for p, s, c in zip(prefixes, serials, check_digits)])

    # Pick ~8% of unique IDs for repeat visits (2-3 visits each)
    repeat_source = rng.choice(unique_ids, size=n_repeat, replace=True)
    all_ids = np.concatenate([unique_ids, repeat_source])
    # Shuffle so repeats are interspersed
    all_ids = rng.permutation(all_ids)
    container_id = all_ids[:n]  # ensure exactly n
    print(f"    [0/8] Container IDs: {n_unique:,} unique + {n_repeat:,} repeat visits ({time.time()-t0:.1f}s)")

    # --- 1. Dwell clusters ---
    clusters = rng.choice(CLUSTER_NAMES, size=n, p=CLUSTER_WEIGHTS)
    print(f"    [1/8] Clusters assigned ({time.time()-t0:.1f}s)")

    # --- 2. ISO codes ---
    iso_keys = rng.choice(ISO_CODES_LIST, size=n, p=ISO_WEIGHTS)
    # Override: chronic cluster → 40% chance of empty
    chronic_mask = clusters == "chronic"
    chronic_empty = rng.random(n) < 0.40
    iso_keys = np.where(chronic_mask & chronic_empty,
                        rng.choice(["22G1_E", "42G1_E"], size=n), iso_keys)

    size_ft = np.array([ISO_SIZE[k] for k in iso_keys])
    container_type = np.array([ISO_TYPE[k] for k in iso_keys])
    iso_display = np.array([ISO_DISPLAY.get(k, k) for k in iso_keys])
    print(f"    [2/8] ISO codes + types ({time.time()-t0:.1f}s)")

    # --- 3. Movement type ---
    movement_type = np.empty(n, dtype=object)
    empty_mask = container_type == "empty"
    # Empties: 60/40 import/export
    movement_type[empty_mask] = rng.choice(["import", "export"],
                                            size=empty_mask.sum(), p=[0.6, 0.4])
    # Non-empties: 45/35/20
    non_empty = ~empty_mask
    movement_type[non_empty] = rng.choice(["import", "export", "transhipment"],
                                           size=non_empty.sum(), p=[0.45, 0.35, 0.20])
    print(f"    [3/8] Movement types ({time.time()-t0:.1f}s)")

    # --- 4. Transport modes ---
    gate_in_mode = np.empty(n, dtype=object)
    gate_out_mode = np.empty(n, dtype=object)

    imp = movement_type == "import"
    exp = movement_type == "export"
    trn = movement_type == "transhipment"

    gate_in_mode[imp] = "vessel"
    gate_out_mode[imp] = rng.choice(["truck", "rail", "barge"], size=imp.sum(), p=[0.70, 0.20, 0.10])
    gate_in_mode[exp] = rng.choice(["truck", "rail", "barge"], size=exp.sum(), p=[0.72, 0.18, 0.10])
    gate_out_mode[exp] = "vessel"
    gate_in_mode[trn] = "vessel"
    gate_out_mode[trn] = "vessel"

    # --- 5. Shipping line ---
    shipping_line = rng.choice(SHIPPING_NAMES, size=n, p=SHIPPING_WEIGHTS)
    print(f"    [4/8] Transport + shipping ({time.time()-t0:.1f}s)")

    # --- 6. Dwell hours (vectorized per cluster) ---
    dwell_hours = np.zeros(n)
    for cluster_name in CLUSTER_NAMES:
        mask = clusters == cluster_name
        cnt = mask.sum()
        if cnt == 0:
            continue
        if cluster_name == "fast":
            dwell_hours[mask] = np.maximum(2, rng.lognormal(2.5, 0.5, cnt))
        elif cluster_name == "normal":
            # Base varies by movement type
            # Import: 72h (3 days), Export: 60h (2.5 days), Transhipment: 56h (2.3 days)
            # Validated against 2025 benchmarks: Singapore 3.1d median, Hamburg 3.7d avg,
            # LA truck 2.73d avg. Our terminal models an efficient mid-size operation.
            base_mu = np.where(movement_type[mask] == "export", 60,
                      np.where(movement_type[mask] == "transhipment", 56, 72))
            dwell_hours[mask] = np.maximum(12, rng.normal(base_mu, base_mu * 0.25))
        elif cluster_name == "extended":
            dwell_hours[mask] = np.maximum(96, rng.normal(120, 36, cnt))
        elif cluster_name == "overstay":
            dwell_hours[mask] = np.maximum(200, rng.normal(336, 72, cnt))
        elif cluster_name == "chronic":
            dwell_hours[mask] = np.maximum(720, rng.lognormal(7.5, 0.6, cnt))

    # Apply shipping line multiplier
    line_mult = np.array([LINE_DWELL_MULT.get(l, 1.0) for l in shipping_line])
    dwell_hours *= line_mult

    # Apply flow-path multiplier (based on out_mode)
    flow_mult = np.array([FLOW_DWELL_MULT.get(m, 1.0) for m in gate_out_mode])
    dwell_hours *= flow_mult
    print(f"    [5/8] Dwell hours computed ({time.time()-t0:.1f}s)")

    # --- 7. Gate-in timestamps (vectorized) ---
    day_offsets = rng.integers(0, total_days, size=n)
    hours = rng.choice(24, size=n, p=HOUR_WEIGHTS)
    minutes = rng.integers(0, 60, size=n)
    seconds = rng.integers(0, 60, size=n)

    # Compute gate_in as Timestamp array
    gate_in_time = (date_start
                    + pd.to_timedelta(day_offsets, unit="D")
                    + pd.to_timedelta(hours, unit="h")
                    + pd.to_timedelta(minutes, unit="m")
                    + pd.to_timedelta(seconds, unit="s"))

    # Weekend suppression: 70% of weekend entries shift to Monday
    weekdays = gate_in_time.weekday
    is_weekend = weekdays >= 5
    shift_to_monday = is_weekend & (rng.random(n) < 0.70)
    days_to_monday = np.where(weekdays == 5, 2, 1)  # Sat→Mon=2, Sun→Mon=1
    gate_in_time = np.where(shift_to_monday,
                            gate_in_time + pd.to_timedelta(days_to_monday, unit="D"),
                            gate_in_time)
    gate_in_time = pd.to_datetime(gate_in_time)

    # Gate-out
    dwell_td = pd.to_timedelta(dwell_hours, unit="h")
    gate_out_time = gate_in_time + dwell_td

    # Still in yard: gate_out after end_date
    still_in_yard = gate_out_time > date_end + pd.Timedelta(days=1)
    gate_out_time_str = gate_out_time.strftime("%Y-%m-%d %H:%M:%S")
    gate_out_time_str = np.where(still_in_yard, None, gate_out_time_str)
    gate_in_time_str = gate_in_time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"    [6/8] Timestamps computed ({time.time()-t0:.1f}s)")

    # --- 8. Block, bay, row, tier, weight, vessel, cargo ---
    # Block assignment
    yard_block = np.empty(n, dtype=object)
    for ctype in np.unique(container_type):
        mask = container_type == ctype
        valid_blocks = BLOCK_LOOKUP.get(ctype, BLOCK_LOOKUP.get("dry", ["A01"]))
        yard_block[mask] = rng.choice(valid_blocks, size=mask.sum())

    # Bay, row, tier per block
    yard_bay = np.zeros(n, dtype=int)
    yard_row = np.zeros(n, dtype=int)
    yard_tier = np.zeros(n, dtype=int)
    for bid in np.unique(yard_block):
        binfo = get_block_info(bid)
        mask = yard_block == bid
        cnt = mask.sum()
        yard_bay[mask] = rng.integers(1, binfo["bays"] + 1, size=cnt)
        yard_row[mask] = rng.integers(1, binfo["rows"] + 1, size=cnt)
        yard_tier[mask] = rng.integers(1, min(binfo["max_tier"], 5) + 1, size=cnt)

    # Weight
    weight = np.zeros(n)
    weight[empty_mask] = rng.uniform(2.0, 4.5, empty_mask.sum())
    sz20 = (~empty_mask) & (size_ft == 20)
    sz40 = (~empty_mask) & (size_ft == 40)
    weight[sz20] = rng.uniform(5, 24, sz20.sum())
    weight[sz40] = rng.uniform(8, 32, sz40.sum())
    weight = np.round(weight, 1)

    # Vessel name
    vessel_name = rng.choice(VESSEL_NAMES, size=n)

    # Cargo category
    cargo_category = np.empty(n, dtype=object)
    cargo_category[empty_mask] = "empty"
    reef = container_type == "reefer"
    haz = container_type == "hazardous"
    other = ~empty_mask & ~reef & ~haz
    cargo_category[reef] = rng.choice(["food_perishable", "pharmaceuticals", "chemicals"],
                                       size=reef.sum(), p=[0.65, 0.25, 0.10])
    cargo_category[haz] = rng.choice(["chemicals", "pharmaceuticals", "machinery"],
                                      size=haz.sum(), p=[0.70, 0.20, 0.10])
    cargo_category[other] = rng.choice(CARGO_NAMES, size=other.sum(), p=CARGO_WEIGHTS)

    # Container IDs already generated in step 0
    print(f"    [7/8] Attributes computed ({time.time()-t0:.1f}s)")

    # --- Assemble DataFrame ---
    df = pd.DataFrame({
        "container_id": container_id,
        "iso_type_code": iso_display,
        "size_ft": size_ft,
        "container_type": container_type,
        "weight_tons": weight,
        "gate_in_time": gate_in_time_str,
        "gate_out_time": gate_out_time_str,
        "movement_type": movement_type,
        "yard_block": yard_block,
        "yard_bay": yard_bay,
        "yard_row": yard_row,
        "yard_tier": yard_tier,
        "vessel_name": vessel_name,
        "shipping_line": shipping_line,
        "cargo_category": cargo_category,
        "gate_in_mode": gate_in_mode,
        "gate_out_mode": gate_out_mode,
    })

    # Ground truth (kept separate for evaluation)
    ground_truth = pd.DataFrame({
        "container_id": container_id,
        "_dwell_cluster": clusters,
    })

    # Shuffle
    idx = rng.permutation(n)
    df = df.iloc[idx].reset_index(drop=True)
    ground_truth = ground_truth.iloc[idx].reset_index(drop=True)

    print(f"    [8/8] DataFrame assembled ({time.time()-t0:.1f}s)")
    return df, ground_truth


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Generate synthetic container movement data")
    parser.add_argument("--num-containers", type=int, default=50000)
    parser.add_argument("--start-date", default="2025-01-01")
    parser.add_argument("--end-date", default="2025-06-30")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", default="data/synthetic_containers.csv")
    parser.add_argument("--ground-truth-output",
                        default="data/ground_truth_clusters.csv")
    parser.add_argument("--yard-config-output",
                        default="data/yard_config.json")
    parser.add_argument("--tariff-config-output",
                        default="data/tariff_config.json")
    args = parser.parse_args()

    t_start = time.time()
    print(f"Generating {args.num_containers:,} containers "
          f"({args.start_date} to {args.end_date}, seed={args.seed})...")

    df, ground_truth = generate_dataset(
        args.num_containers, args.start_date, args.end_date, args.seed)

    # Save outputs
    df.to_csv(args.output, index=False)
    print(f"  Container data saved: {args.output} ({len(df):,} rows)")

    ground_truth.to_csv(args.ground_truth_output, index=False)
    print(f"  Ground truth saved: {args.ground_truth_output}")

    with open(args.yard_config_output, "w") as f:
        json.dump(YARD_CONFIG, f, indent=2)
    print(f"  Yard config saved: {args.yard_config_output}")

    with open(args.tariff_config_output, "w") as f:
        json.dump(TARIFF_CONFIG, f, indent=2)
    print(f"  Tariff config saved: {args.tariff_config_output}")

    # Quick summary
    elapsed = time.time() - t_start
    print(f"\n--- Dataset Summary (generated in {elapsed:.1f}s) ---")
    n_unique_actual = df['container_id'].nunique()
    n_repeat_actual = len(df) - n_unique_actual
    print(f"  Unique containers: {n_unique_actual:,} ({n_repeat_actual:,} repeat visits = {n_repeat_actual/len(df)*100:.1f}%)")
    print(f"  Container ID format sample: {df['container_id'].iloc[0]}, {df['container_id'].iloc[1]}, {df['container_id'].iloc[2]}")
    print(f"  Date range: {df['gate_in_time'].min()} to {df['gate_in_time'].max()}")
    print(f"  Container types: {df['container_type'].value_counts().to_dict()}")
    print(f"  Movement types: {df['movement_type'].value_counts().to_dict()}")
    print(f"  Yard blocks: {sorted(df['yard_block'].unique())}")
    print(f"  Null gate_out (still in yard): {df['gate_out_time'].isna().sum():,}")
    print(f"  Size mix: {df['size_ft'].value_counts().to_dict()}")
    print(f"  Shipping lines: {df['shipping_line'].nunique()}")
    print(f"  Empty rate: {(df['container_type']=='empty').mean()*100:.1f}%")


if __name__ == "__main__":
    main()
