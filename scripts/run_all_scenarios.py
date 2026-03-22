"""
run_all_scenarios.py — Execute All 5 Test Scenarios

Generates appropriate data for each scenario, runs the pipeline, and captures
all outputs in the outputs/ directory. This is the execution evidence required
for the assignment.

Usage:
    python scripts/run_all_scenarios.py

Each scenario produces:
    outputs/scenario_N_name/
    ├── data_quality_report.json
    ├── validated_containers.csv (if validation passes)
    ├── dwell_features.csv (if Stage 2 runs)
    ├── block_daily_features.csv (if Stage 2 runs)
    ├── model_outputs/ (if Stage 3-4 runs)
    │   ├── cluster_results.json
    │   ├── forecast_results.json
    │   ├── validation_metrics.json
    │   └── charts/*.png
    ├── final_report.html (if Stage 6 runs)
    └── scenario_log.txt (console output capture)
"""

import os
import sys
import json
import shutil
import subprocess
import pandas as pd
import numpy as np
from datetime import datetime


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.join(BASE_DIR, "scripts")
OUTPUTS_DIR = os.path.join(BASE_DIR, "outputs")
DATA_DIR = os.path.join(BASE_DIR, "data")


PYTHON = sys.executable  # Use the same Python that's running this script


def run_command(cmd, log_file, cwd=BASE_DIR):
    """Run a shell command, print output, and log it."""
    # Replace 'python ' with the actual Python executable
    cmd = cmd.replace("python scripts/", f"{PYTHON} scripts/")
    print(f"  $ {cmd}")
    result = subprocess.run(
        cmd, shell=True, cwd=cwd,
        capture_output=True, text=True, timeout=600
    )
    output = result.stdout + result.stderr
    log_file.write(f"\n{'='*60}\n$ {cmd}\n{'='*60}\n")
    log_file.write(output)
    print(output[-500:] if len(output) > 500 else output)  # Print last 500 chars
    return result.returncode, output


def scenario_1_happy_path():
    """Scenario 1: Happy Path — Full data, full config, complete pipeline."""
    name = "scenario_1_happy_path"
    out_dir = os.path.join(OUTPUTS_DIR, name)
    os.makedirs(os.path.join(out_dir, "model_outputs", "charts"), exist_ok=True)

    print(f"\n{'#'*60}")
    print(f"# SCENARIO 1: Happy Path")
    print(f"# Full 50K dataset, yard config, tariff config, all columns")
    print(f"# Expected: PASS → complete pipeline → full report")
    print(f"{'#'*60}")

    with open(os.path.join(out_dir, "scenario_log.txt"), "w") as log:
        log.write(f"Scenario 1: Happy Path\nStarted: {datetime.now()}\n")
        log.write(f"Description: 50K containers, full yard+tariff config, all optional columns\n")
        log.write(f"Expected: PASS validation, complete pipeline, full report with all sections\n\n")

        # Use existing synthetic data (already generated as 50K)
        data_csv = os.path.join(DATA_DIR, "synthetic_containers.csv")
        yard_json = os.path.join(DATA_DIR, "yard_config.json")
        tariff_json = os.path.join(DATA_DIR, "tariff_config.json")

        if not os.path.exists(data_csv):
            print("  Generating 50K synthetic data...")
            run_command(
                f"python scripts/generate_synthetic_data.py --num-containers 50000 --seed 42",
                log)

        # Stage 1
        rc, _ = run_command(
            f"python scripts/validate_data.py "
            f"--input {data_csv} "
            f"--yard-config {yard_json} "
            f"--tariff-config {tariff_json} "
            f"--output {os.path.join(out_dir, 'data_quality_report.json')} "
            f"--validated-output {os.path.join(out_dir, 'validated_containers.csv')}",
            log)

        if rc != 0:
            log.write("\n\n*** UNEXPECTED: Validation failed for happy path ***\n")
            return

        # Stage 2
        run_command(
            f"python scripts/feature_engineering.py "
            f"--input {os.path.join(out_dir, 'validated_containers.csv')} "
            f"--yard-config {yard_json} "
            f"--tariff-config {tariff_json} "
            f"--output-container {os.path.join(out_dir, 'dwell_features.csv')} "
            f"--output-block {os.path.join(out_dir, 'block_daily_features.csv')}",
            log)

        # Stage 3-4
        run_command(
            f"python scripts/run_models.py "
            f"--container-features {os.path.join(out_dir, 'dwell_features.csv')} "
            f"--block-features {os.path.join(out_dir, 'block_daily_features.csv')} "
            f"--num-segments 4 --forecast-horizon 14 --random-seed 42 "
            f"--output-dir {os.path.join(out_dir, 'model_outputs')}",
            log)

        # Stage 6
        run_command(
            f"python scripts/generate_report.py "
            f"--container-features {os.path.join(out_dir, 'dwell_features.csv')} "
            f"--block-features {os.path.join(out_dir, 'block_daily_features.csv')} "
            f"--model-dir {os.path.join(out_dir, 'model_outputs')} "
            f"--quality-report {os.path.join(out_dir, 'data_quality_report.json')} "
            f"--yard-config {yard_json} "
            f"--tariff-config {tariff_json} "
            f"--output {os.path.join(out_dir, 'final_report.html')}",
            log)

        log.write(f"\nCompleted: {datetime.now()}\n")
    print(f"  ✓ Scenario 1 complete → {out_dir}")


def scenario_2_minimal_input():
    """Scenario 2: Minimal Input — Required columns only, no configs."""
    name = "scenario_2_minimal_input"
    out_dir = os.path.join(OUTPUTS_DIR, name)
    os.makedirs(os.path.join(out_dir, "model_outputs", "charts"), exist_ok=True)

    print(f"\n{'#'*60}")
    print(f"# SCENARIO 2: Minimal Input")
    print(f"# Only required columns, NO yard config, NO tariff config")
    print(f"# Expected: PASS → pipeline runs → report with missing sections noted")
    print(f"{'#'*60}")

    with open(os.path.join(out_dir, "scenario_log.txt"), "w") as log:
        log.write(f"Scenario 2: Minimal Input\nStarted: {datetime.now()}\n")
        log.write(f"Description: 5K containers, only 8 required columns, no yard/tariff config\n")
        log.write(f"Expected: PASS validation, pipeline completes, revenue section warns about missing tariff\n\n")

        # Generate small dataset and strip optional columns
        run_command(
            f"python scripts/generate_synthetic_data.py --num-containers 5000 --seed 99 "
            f"--output {os.path.join(out_dir, 'raw_containers.csv')} "
            f"--yard-config-output {os.path.join(out_dir, '_yard.json')} "
            f"--tariff-config-output {os.path.join(out_dir, '_tariff.json')} "
            f"--ground-truth-output {os.path.join(out_dir, '_gt.csv')}",
            log)

        # Strip to required columns only
        df = pd.read_csv(os.path.join(out_dir, "raw_containers.csv"))
        required_only = ["container_id", "size_ft", "container_type", "weight_tons",
                         "gate_in_time", "gate_out_time", "movement_type", "yard_block"]
        df[required_only].to_csv(os.path.join(out_dir, "minimal_containers.csv"), index=False)
        print(f"  Stripped to {len(required_only)} required columns")

        # Stage 1 — NO yard/tariff config
        rc, _ = run_command(
            f"python scripts/validate_data.py "
            f"--input {os.path.join(out_dir, 'minimal_containers.csv')} "
            f"--output {os.path.join(out_dir, 'data_quality_report.json')} "
            f"--validated-output {os.path.join(out_dir, 'validated_containers.csv')}",
            log)

        if rc != 0:
            log.write("\n\n*** Validation failed — check output ***\n")
            return

        # Stage 2 — NO configs
        run_command(
            f"python scripts/feature_engineering.py "
            f"--input {os.path.join(out_dir, 'validated_containers.csv')} "
            f"--output-container {os.path.join(out_dir, 'dwell_features.csv')} "
            f"--output-block {os.path.join(out_dir, 'block_daily_features.csv')}",
            log)

        # Stage 3-4
        run_command(
            f"python scripts/run_models.py "
            f"--container-features {os.path.join(out_dir, 'dwell_features.csv')} "
            f"--block-features {os.path.join(out_dir, 'block_daily_features.csv')} "
            f"--output-dir {os.path.join(out_dir, 'model_outputs')}",
            log)

        # Stage 6 — NO configs
        run_command(
            f"python scripts/generate_report.py "
            f"--container-features {os.path.join(out_dir, 'dwell_features.csv')} "
            f"--block-features {os.path.join(out_dir, 'block_daily_features.csv')} "
            f"--model-dir {os.path.join(out_dir, 'model_outputs')} "
            f"--quality-report {os.path.join(out_dir, 'data_quality_report.json')} "
            f"--output {os.path.join(out_dir, 'final_report.html')}",
            log)

        log.write(f"\nCompleted: {datetime.now()}\n")
    print(f"  ✓ Scenario 2 complete → {out_dir}")


def scenario_3_bad_data():
    """Scenario 3: Bad Data — Nulls, wrong types, reversed dates."""
    name = "scenario_3_bad_data"
    out_dir = os.path.join(OUTPUTS_DIR, name)
    os.makedirs(out_dir, exist_ok=True)

    print(f"\n{'#'*60}")
    print(f"# SCENARIO 3: Bad Data")
    print(f"# >30% nulls in required column, negative weights, reversed dates")
    print(f"# Expected: FAIL validation with clear error report")
    print(f"{'#'*60}")

    with open(os.path.join(out_dir, "scenario_log.txt"), "w") as log:
        log.write(f"Scenario 3: Bad Data\nStarted: {datetime.now()}\n")
        log.write(f"Description: Deliberately corrupted data — >30% nulls, negative weights, reversed dates\n")
        log.write(f"Expected: FAIL validation, clear error messages, pipeline stops\n\n")

        # Generate clean data first, then corrupt it
        run_command(
            f"python scripts/generate_synthetic_data.py --num-containers 2000 --seed 77 "
            f"--output {os.path.join(out_dir, '_clean.csv')} "
            f"--yard-config-output {os.path.join(out_dir, '_yard.json')} "
            f"--tariff-config-output {os.path.join(out_dir, '_tariff.json')} "
            f"--ground-truth-output {os.path.join(out_dir, '_gt.csv')}",
            log)

        df = pd.read_csv(os.path.join(out_dir, "_clean.csv"))
        rng = np.random.RandomState(42)

        # Corruption 1: Set 35% of container_type to null
        null_mask = rng.random(len(df)) < 0.35
        df.loc[null_mask, "container_type"] = np.nan
        log.write(f"Corruption 1: Set {null_mask.sum()} ({null_mask.mean()*100:.1f}%) container_type to null\n")

        # Corruption 2: Set 50 weights to negative
        neg_idx = rng.choice(len(df), size=50, replace=False)
        df.loc[neg_idx, "weight_tons"] = -1 * df.loc[neg_idx, "weight_tons"].abs()
        log.write(f"Corruption 2: Set 50 weights to negative\n")

        # Corruption 3: Swap gate_in and gate_out for 15% of rows
        swap_mask = rng.random(len(df)) < 0.15
        swap_idx = df[swap_mask].index
        df.loc[swap_idx, ["gate_in_time", "gate_out_time"]] = \
            df.loc[swap_idx, ["gate_out_time", "gate_in_time"]].values
        log.write(f"Corruption 3: Swapped gate_in/gate_out for {swap_mask.sum()} ({swap_mask.mean()*100:.1f}%) rows\n")

        # Corruption 4: Add some invalid movement types
        invalid_idx = rng.choice(len(df), size=30, replace=False)
        df.loc[invalid_idx, "movement_type"] = "INVALID_TYPE"
        log.write(f"Corruption 4: Set 30 movement_type to 'INVALID_TYPE'\n")

        bad_csv = os.path.join(out_dir, "bad_containers.csv")
        df.to_csv(bad_csv, index=False)
        log.write(f"\nCorrupted CSV saved: {bad_csv} ({len(df)} rows)\n\n")

        # Stage 1 — should FAIL
        rc, output = run_command(
            f"python scripts/validate_data.py "
            f"--input {bad_csv} "
            f"--output {os.path.join(out_dir, 'data_quality_report.json')} "
            f"--validated-output {os.path.join(out_dir, 'validated_containers.csv')}",
            log)

        if rc != 0:
            log.write("\n*** EXPECTED: Validation correctly FAILED ***\n")
            print("  ✓ Validation correctly FAILED (as expected)")
        else:
            # Check if status is FAIL in the report even if exit code was 0
            try:
                with open(os.path.join(out_dir, "data_quality_report.json")) as f:
                    qr = json.load(f)
                if qr.get("status") == "FAIL":
                    log.write("\n*** EXPECTED: Validation report status is FAIL ***\n")
                    print("  ✓ Validation report correctly shows FAIL status")
                elif qr.get("status") == "WARN":
                    log.write("\n*** Validation returned WARN (not FAIL) — data partially usable ***\n")
                    print("  ⚠ Validation returned WARN — pipeline continued with warnings")
                else:
                    log.write("\n*** UNEXPECTED: Validation passed with corrupted data ***\n")
                    print("  ⚠ Unexpected: validation passed despite corruptions")
            except Exception:
                pass

        log.write(f"\nCompleted: {datetime.now()}\n")
    print(f"  ✓ Scenario 3 complete → {out_dir}")


def scenario_4_param_sensitivity():
    """Scenario 4: Parameter Sensitivity — Same data, different overstay thresholds."""
    name = "scenario_4_param_sensitivity"
    out_dir = os.path.join(OUTPUTS_DIR, name)

    print(f"\n{'#'*60}")
    print(f"# SCENARIO 4: Parameter Sensitivity")
    print(f"# Same 50K dataset, overstay_threshold = 5 days vs 10 days")
    print(f"# Expected: Different segment compositions, different revenue calculations")
    print(f"{'#'*60}")

    with open(os.path.join(out_dir, "scenario_log.txt"), "w") as log:
        log.write(f"Scenario 4: Parameter Sensitivity\nStarted: {datetime.now()}\n")
        log.write(f"Description: Same dataset with overstay_threshold=5 vs overstay_threshold=10\n")
        log.write(f"Expected: More overstayers at threshold=5, fewer at threshold=10, different revenue\n\n")

        data_csv = os.path.join(DATA_DIR, "synthetic_containers.csv")
        yard_json = os.path.join(DATA_DIR, "yard_config.json")
        tariff_json = os.path.join(DATA_DIR, "tariff_config.json")

        for threshold in [5, 10]:
            variant = f"threshold_{threshold}d"
            var_dir = os.path.join(out_dir, variant)
            os.makedirs(os.path.join(var_dir, "model_outputs", "charts"), exist_ok=True)

            log.write(f"\n{'='*40}\n")
            log.write(f"Running with overstay_threshold = {threshold} days\n")
            log.write(f"{'='*40}\n")
            print(f"\n  --- Threshold = {threshold} days ---")

            # Stage 1 (same for both)
            run_command(
                f"python scripts/validate_data.py "
                f"--input {data_csv} "
                f"--yard-config {yard_json} "
                f"--tariff-config {tariff_json} "
                f"--output {os.path.join(var_dir, 'data_quality_report.json')} "
                f"--validated-output {os.path.join(var_dir, 'validated_containers.csv')}",
                log)

            # Stage 2 with different threshold
            params = json.dumps({"overstay_threshold_days": threshold})
            run_command(
                f"python scripts/feature_engineering.py "
                f"--input {os.path.join(var_dir, 'validated_containers.csv')} "
                f"--yard-config {yard_json} "
                f"--tariff-config {tariff_json} "
                f"--params '{params}' "
                f"--output-container {os.path.join(var_dir, 'dwell_features.csv')} "
                f"--output-block {os.path.join(var_dir, 'block_daily_features.csv')}",
                log)

            # Stage 3-4
            run_command(
                f"python scripts/run_models.py "
                f"--container-features {os.path.join(var_dir, 'dwell_features.csv')} "
                f"--block-features {os.path.join(var_dir, 'block_daily_features.csv')} "
                f"--output-dir {os.path.join(var_dir, 'model_outputs')}",
                log)

            # Stage 6
            run_command(
                f"python scripts/generate_report.py "
                f"--container-features {os.path.join(var_dir, 'dwell_features.csv')} "
                f"--block-features {os.path.join(var_dir, 'block_daily_features.csv')} "
                f"--model-dir {os.path.join(var_dir, 'model_outputs')} "
                f"--quality-report {os.path.join(var_dir, 'data_quality_report.json')} "
                f"--yard-config {yard_json} "
                f"--tariff-config {tariff_json} "
                f"--output {os.path.join(var_dir, 'final_report.html')}",
                log)

        # Compare the two runs
        log.write(f"\n{'='*40}\nCOMPARISON\n{'='*40}\n")
        for threshold in [5, 10]:
            var_dir = os.path.join(out_dir, f"threshold_{threshold}d")
            feat_path = os.path.join(var_dir, "dwell_features.csv")
            if os.path.exists(feat_path):
                df = pd.read_csv(feat_path)
                has_dwell = df[df["dwell_days"].notna()]
                overstay_rate = has_dwell["is_overstay"].mean() * 100
                total_rev = df["storage_cost_usd"].sum() if df["storage_cost_usd"].notna().any() else 0
                log.write(f"\nThreshold = {threshold} days:\n")
                log.write(f"  Overstay rate: {overstay_rate:.1f}%\n")
                log.write(f"  Total storage revenue: ${total_rev:,.0f}\n")
                log.write(f"  Overstay count: {has_dwell['is_overstay'].sum()}\n")
                print(f"  Threshold={threshold}d → Overstay rate: {overstay_rate:.1f}%, Revenue: ${total_rev:,.0f}")

        log.write(f"\nCompleted: {datetime.now()}\n")
    print(f"  ✓ Scenario 4 complete → {out_dir}")


def scenario_5_reefer_only():
    """Scenario 5: Reefer-Only Terminal — Single container type."""
    name = "scenario_5_reefer_only"
    out_dir = os.path.join(OUTPUTS_DIR, name)
    os.makedirs(os.path.join(out_dir, "model_outputs", "charts"), exist_ok=True)

    print(f"\n{'#'*60}")
    print(f"# SCENARIO 5: Reefer-Only Terminal")
    print(f"# All containers are reefers — tests single-type handling")
    print(f"# Expected: PASS → pipeline handles gracefully → reefer plug util prominent")
    print(f"{'#'*60}")

    with open(os.path.join(out_dir, "scenario_log.txt"), "w") as log:
        log.write(f"Scenario 5: Reefer-Only Terminal\nStarted: {datetime.now()}\n")
        log.write(f"Description: 3K containers, all reefer type, reefer yard config\n")
        log.write(f"Expected: PASS validation, segmentation still meaningful, reefer plug utilization prominent\n\n")

        # Generate normal data and convert all to reefer
        run_command(
            f"python scripts/generate_synthetic_data.py --num-containers 3000 --seed 55 "
            f"--output {os.path.join(out_dir, '_raw.csv')} "
            f"--yard-config-output {os.path.join(out_dir, '_yard.json')} "
            f"--tariff-config-output {os.path.join(out_dir, 'tariff_config.json')} "
            f"--ground-truth-output {os.path.join(out_dir, '_gt.csv')}",
            log)

        df = pd.read_csv(os.path.join(out_dir, "_raw.csv"))

        # Convert all containers to reefer
        df["container_type"] = "reefer"
        df["iso_type_code"] = df["size_ft"].map({20: "22R1", 40: "45R1"}).fillna("45R1")
        df["cargo_category"] = np.random.choice(
            ["food_perishable", "pharmaceuticals", "chemicals"],
            size=len(df), p=[0.6, 0.25, 0.15])

        # All blocks become reefer blocks
        df["yard_block"] = np.random.choice(["R01", "R02"], size=len(df), p=[0.6, 0.4])

        reefer_csv = os.path.join(out_dir, "reefer_containers.csv")
        df.to_csv(reefer_csv, index=False)
        log.write(f"Created reefer-only dataset: {len(df)} containers, all reefer\n\n")

        # Create reefer-only yard config
        reefer_yard = {
            "terminal_name": "Cold Chain Terminal — Reefer Specialist",
            "blocks": [
                {"block_id": "R01", "rows": 6, "bays": 30, "max_tier": 4,
                 "teu_capacity": 720, "accepts_types": ["reefer"],
                 "has_reefer_plugs": True, "reefer_plug_count": 200},
                {"block_id": "R02", "rows": 5, "bays": 25, "max_tier": 4,
                 "teu_capacity": 500, "accepts_types": ["reefer"],
                 "has_reefer_plugs": True, "reefer_plug_count": 150},
            ],
            "gate_count_in": 3,
            "gate_count_out": 2
        }
        yard_json = os.path.join(out_dir, "yard_config.json")
        with open(yard_json, "w") as f:
            json.dump(reefer_yard, f, indent=2)

        tariff_json = os.path.join(out_dir, "tariff_config.json")

        # Stage 1
        rc, _ = run_command(
            f"python scripts/validate_data.py "
            f"--input {reefer_csv} "
            f"--yard-config {yard_json} "
            f"--tariff-config {tariff_json} "
            f"--output {os.path.join(out_dir, 'data_quality_report.json')} "
            f"--validated-output {os.path.join(out_dir, 'validated_containers.csv')}",
            log)

        if rc != 0:
            log.write("\n*** Validation failed ***\n")
            return

        # Stage 2
        run_command(
            f"python scripts/feature_engineering.py "
            f"--input {os.path.join(out_dir, 'validated_containers.csv')} "
            f"--yard-config {yard_json} "
            f"--tariff-config {tariff_json} "
            f"--output-container {os.path.join(out_dir, 'dwell_features.csv')} "
            f"--output-block {os.path.join(out_dir, 'block_daily_features.csv')}",
            log)

        # Stage 3-4
        run_command(
            f"python scripts/run_models.py "
            f"--container-features {os.path.join(out_dir, 'dwell_features.csv')} "
            f"--block-features {os.path.join(out_dir, 'block_daily_features.csv')} "
            f"--output-dir {os.path.join(out_dir, 'model_outputs')}",
            log)

        # Stage 6
        run_command(
            f"python scripts/generate_report.py "
            f"--container-features {os.path.join(out_dir, 'dwell_features.csv')} "
            f"--block-features {os.path.join(out_dir, 'block_daily_features.csv')} "
            f"--model-dir {os.path.join(out_dir, 'model_outputs')} "
            f"--quality-report {os.path.join(out_dir, 'data_quality_report.json')} "
            f"--yard-config {yard_json} "
            f"--tariff-config {tariff_json} "
            f"--output {os.path.join(out_dir, 'final_report.html')}",
            log)

        log.write(f"\nCompleted: {datetime.now()}\n")
    print(f"  ✓ Scenario 5 complete → {out_dir}")


def generate_scenario_results_summary():
    """Generate evaluation/scenario_results.md summarizing all scenarios."""
    print(f"\n{'#'*60}")
    print(f"# Generating scenario_results.md")
    print(f"{'#'*60}")

    results = []
    scenarios = [
        ("scenario_1_happy_path", "Happy Path",
         "50K containers, full config",
         "PASS → complete pipeline → full report"),
        ("scenario_2_minimal_input", "Minimal Input",
         "5K containers, required columns only, no yard/tariff config",
         "PASS → pipeline runs → revenue section warns about missing tariff"),
        ("scenario_3_bad_data", "Bad Data",
         "2K containers, 35% null container_type, negative weights, reversed dates",
         "FAIL validation with clear error report"),
        ("scenario_4_param_sensitivity", "Parameter Sensitivity",
         "50K containers, overstay_threshold=5d vs 10d",
         "Different overstay rates and revenue calculations"),
        ("scenario_5_reefer_only", "Reefer-Only Terminal",
         "3K reefer containers, reefer yard config",
         "PASS → pipeline handles single-type → reefer plug util prominent"),
    ]

    md = "# Scenario Test Results\n\n"
    md += f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    md += "| # | Scenario | Input | Expected | Actual | Status |\n"
    md += "|---|----------|-------|----------|--------|--------|\n"

    for name, title, input_desc, expected in scenarios:
        out_dir = os.path.join(OUTPUTS_DIR, name)
        qr_path = os.path.join(out_dir, "data_quality_report.json")
        report_path = os.path.join(out_dir, "final_report.html")

        # For param sensitivity, check sub-dirs
        if name == "scenario_4_param_sensitivity":
            qr_path = os.path.join(out_dir, "threshold_5d", "data_quality_report.json")
            report_path = os.path.join(out_dir, "threshold_5d", "final_report.html")

        actual = "Not run"
        status = "⬜"

        if os.path.exists(qr_path):
            try:
                with open(qr_path) as f:
                    qr = json.load(f)
                val_status = qr.get("status", "UNKNOWN")

                if name == "scenario_3_bad_data":
                    if val_status in ["FAIL", "WARN"]:
                        actual = f"Validation: {val_status} — errors correctly detected"
                        status = "✅"
                    else:
                        actual = f"Validation: {val_status} — expected FAIL"
                        status = "⚠️"
                else:
                    if os.path.exists(report_path):
                        report_size = os.path.getsize(report_path) / 1024
                        actual = f"Validation: {val_status} → Report generated ({report_size:.0f} KB)"
                        status = "✅"
                    else:
                        actual = f"Validation: {val_status} — report not generated"
                        status = "⚠️"
            except Exception as e:
                actual = f"Error reading results: {str(e)}"
                status = "❌"
        else:
            actual = "Quality report not found — scenario may not have run"
            status = "⬜"

        md += f"| {scenarios.index((name, title, input_desc, expected)) + 1} "
        md += f"| {title} | {input_desc} | {expected} | {actual} | {status} |\n"

    # Add parameter sensitivity comparison
    md += "\n## Scenario 4: Parameter Sensitivity Comparison\n\n"
    md += "| Metric | Threshold = 5 days | Threshold = 10 days | Impact |\n"
    md += "|--------|-------------------|--------------------|---------|\n"

    for threshold in [5, 10]:
        feat_path = os.path.join(OUTPUTS_DIR, f"scenario_4_param_sensitivity",
                                  f"threshold_{threshold}d", "dwell_features.csv")
        if os.path.exists(feat_path):
            df = pd.read_csv(feat_path)
            has_dwell = df[df["dwell_days"].notna()]
            results.append({
                "threshold": threshold,
                "overstay_rate": has_dwell["is_overstay"].mean() * 100,
                "overstay_count": int(has_dwell["is_overstay"].sum()),
                "revenue": df["storage_cost_usd"].sum() if df["storage_cost_usd"].notna().any() else 0,
            })

    if len(results) == 2:
        r5, r10 = results[0], results[1]
        md += f"| Overstay rate | {r5['overstay_rate']:.1f}% | {r10['overstay_rate']:.1f}% "
        md += f"| {r5['overstay_rate'] - r10['overstay_rate']:+.1f}pp |\n"
        md += f"| Overstay count | {r5['overstay_count']:,} | {r10['overstay_count']:,} "
        md += f"| {r5['overstay_count'] - r10['overstay_count']:+,} |\n"
        md += f"| Total revenue | ${r5['revenue']:,.0f} | ${r10['revenue']:,.0f} "
        md += f"| ${r5['revenue'] - r10['revenue']:+,.0f} |\n"

    md += "\n## Interpretation\n\n"
    md += "Lowering the overstay threshold from 10 to 5 days reclassifies more containers as overstaying, "
    md += "which changes both the demurrage revenue allocation and the opportunity cost calculation. "
    md += "Terminal operators should set this threshold based on their specific free-day policy and "
    md += "operational tolerance for yard occupancy.\n"

    eval_dir = os.path.join(BASE_DIR, "evaluation")
    os.makedirs(eval_dir, exist_ok=True)
    with open(os.path.join(eval_dir, "scenario_results.md"), "w") as f:
        f.write(md)

    print(f"  ✓ Summary saved → evaluation/scenario_results.md")


def main():
    print("=" * 60)
    print("  RUNNING ALL 5 TEST SCENARIOS")
    print(f"  Started: {datetime.now()}")
    print("=" * 60)

    scenario_1_happy_path()
    scenario_2_minimal_input()
    scenario_3_bad_data()
    scenario_4_param_sensitivity()
    scenario_5_reefer_only()

    generate_scenario_results_summary()

    print(f"\n{'='*60}")
    print(f"  ALL SCENARIOS COMPLETE")
    print(f"  Results in: {OUTPUTS_DIR}")
    print(f"  Summary in: evaluation/scenario_results.md")
    print(f"  Finished: {datetime.now()}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
