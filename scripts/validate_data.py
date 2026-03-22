"""
validate_data.py — Data Validation & Profiling (Pipeline Stage 1)

Validates container movement data against schema requirements, checks data quality,
profiles distributions, and produces a structured quality report.

Usage:
    python scripts/validate_data.py \
        --input data/synthetic_containers.csv \
        --yard-config data/yard_config.json \
        --tariff-config data/tariff_config.json \
        --output data/data_quality_report.json

Output:
    JSON report with status (PASS/WARN/FAIL), quality metrics, and profiling.
"""

import argparse
import json
import sys
from datetime import datetime
import numpy as np
import pandas as pd


REQUIRED_COLUMNS = [
    "container_id", "size_ft", "container_type", "weight_tons",
    "gate_in_time", "gate_out_time", "movement_type", "yard_block"
]

OPTIONAL_COLUMNS = [
    "iso_type_code", "yard_bay", "yard_row", "yard_tier",
    "vessel_name", "shipping_line", "cargo_category",
    "gate_in_mode", "gate_out_mode"
]

VALID_CONTAINER_TYPES = {"dry", "reefer", "hazardous", "empty", "special", "tank"}
VALID_MOVEMENT_TYPES = {"import", "export", "transhipment"}
VALID_SIZES = {20, 40, 45}
VALID_GATE_MODES = {"vessel", "truck", "rail", "barge"}


def validate_schema(df):
    """Check all required columns exist."""
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    present_optional = [c for c in OPTIONAL_COLUMNS if c in df.columns]
    return missing, present_optional


def validate_types(df):
    """Validate data types and allowed values."""
    issues = []

    # size_ft: must be integer in {20, 40, 45}
    if "size_ft" in df.columns:
        invalid_sizes = df[~df["size_ft"].isin(VALID_SIZES) & df["size_ft"].notna()]
        if len(invalid_sizes) > 0:
            issues.append(f"size_ft has {len(invalid_sizes)} invalid values "
                          f"(expected 20, 40, or 45)")

    # container_type
    if "container_type" in df.columns:
        invalid_types = df[~df["container_type"].isin(VALID_CONTAINER_TYPES)
                           & df["container_type"].notna()]
        if len(invalid_types) > 0:
            vals = invalid_types["container_type"].unique()[:5]
            issues.append(f"container_type has {len(invalid_types)} invalid values: "
                          f"{list(vals)}")

    # movement_type
    if "movement_type" in df.columns:
        invalid_mv = df[~df["movement_type"].isin(VALID_MOVEMENT_TYPES)
                        & df["movement_type"].notna()]
        if len(invalid_mv) > 0:
            vals = invalid_mv["movement_type"].unique()[:5]
            issues.append(f"movement_type has {len(invalid_mv)} invalid values: "
                          f"{list(vals)}")

    # weight_tons: must be numeric and positive
    if "weight_tons" in df.columns:
        non_positive = df[(df["weight_tons"] <= 0) & df["weight_tons"].notna()]
        if len(non_positive) > 0:
            issues.append(f"weight_tons has {len(non_positive)} non-positive values")

    # gate_in_mode / gate_out_mode
    for col in ["gate_in_mode", "gate_out_mode"]:
        if col in df.columns:
            invalid = df[~df[col].isin(VALID_GATE_MODES) & df[col].notna()]
            if len(invalid) > 0:
                issues.append(f"{col} has {len(invalid)} invalid values")

    return issues


def validate_dates(df):
    """Parse and validate datetime columns."""
    errors = []
    warnings = []
    excluded_indices = set()

    # Parse gate_in_time
    df["gate_in_time"] = pd.to_datetime(df["gate_in_time"], errors="coerce")
    unparsed_in = df["gate_in_time"].isna().sum()
    original_nulls_in = 0  # gate_in shouldn't have nulls ideally
    if unparsed_in > 0:
        errors.append(f"gate_in_time: {unparsed_in} values could not be parsed as dates")

    # Parse gate_out_time (nulls are OK — means container is still in yard)
    original_nulls_out = df["gate_out_time"].isna().sum()
    df["gate_out_time"] = pd.to_datetime(df["gate_out_time"], errors="coerce")
    new_nulls_out = df["gate_out_time"].isna().sum() - original_nulls_out
    if new_nulls_out > 0:
        warnings.append(f"gate_out_time: {new_nulls_out} additional values could not "
                        f"be parsed (beyond {original_nulls_out} legitimate nulls)")

    # Check gate_out > gate_in
    has_both = df["gate_in_time"].notna() & df["gate_out_time"].notna()
    reversed_dates = df[has_both & (df["gate_out_time"] < df["gate_in_time"])]
    if len(reversed_dates) > 0:
        pct = len(reversed_dates) / len(df) * 100
        excluded_indices.update(reversed_dates.index)
        msg = (f"{len(reversed_dates)} rows ({pct:.1f}%) have gate_out before gate_in "
               f"— excluded from analysis")
        if pct > 5:
            errors.append(msg)
        else:
            warnings.append(msg)

    # Check for future dates
    now = pd.Timestamp.now()
    future_in = df[df["gate_in_time"] > now]
    future_out = df[df["gate_out_time"] > now]
    if len(future_in) > 0:
        excluded_indices.update(future_in.index)
        warnings.append(f"{len(future_in)} rows have future gate_in dates — excluded")
    if len(future_out) > 0:
        excluded_indices.update(future_out.index)
        warnings.append(f"{len(future_out)} rows have future gate_out dates — excluded")

    return errors, warnings, excluded_indices


def check_nulls(df):
    """Analyze null percentages per column."""
    null_report = {}
    errors = []
    warnings = []

    for col in df.columns:
        null_count = int(df[col].isna().sum())
        null_pct = round(null_count / len(df) * 100, 2)
        null_report[col] = {"nulls": null_count, "null_pct": null_pct}

        if col in REQUIRED_COLUMNS and col != "gate_out_time":
            if null_pct > 20:
                errors.append(f"{col}: {null_pct}% null (exceeds 20% threshold) "
                              f"— REJECT")
            elif null_pct > 10:
                warnings.append(f"{col}: {null_pct}% null (elevated)")
        elif col == "gate_out_time":
            if null_pct > 30:
                warnings.append(f"gate_out_time: {null_pct}% null — many containers "
                                f"may still be in yard")

    return null_report, errors, warnings


def check_duplicates(df):
    """Check for exact duplicates and container_id + gate_in duplicates."""
    warnings = []
    excluded = set()

    exact_dupes = df.duplicated()
    if exact_dupes.sum() > 0:
        warnings.append(f"{exact_dupes.sum()} exact duplicate rows found and removed")
        excluded.update(df[exact_dupes].index)

    if "container_id" in df.columns and "gate_in_time" in df.columns:
        key_dupes = df.duplicated(subset=["container_id", "gate_in_time"], keep="first")
        if key_dupes.sum() > 0:
            warnings.append(f"{key_dupes.sum()} duplicate (container_id, gate_in_time) "
                            f"pairs found and deduplicated")
            excluded.update(df[key_dupes].index)

    return warnings, excluded


def check_minimum_requirements(df):
    """Check minimum data thresholds."""
    errors = []
    warnings = []

    unique_containers = df["container_id"].nunique()
    if unique_containers < 100:
        errors.append(f"Only {unique_containers} unique containers "
                      f"(minimum 100 required)")

    if "gate_in_time" in df.columns and df["gate_in_time"].notna().any():
        date_min = df["gate_in_time"].min()
        date_max = df["gate_in_time"].max()
        span_days = (date_max - date_min).days
        if span_days < 30:
            errors.append(f"Date range is only {span_days} days "
                          f"(minimum 30 required)")

    unique_blocks = df["yard_block"].nunique() if "yard_block" in df.columns else 0
    if unique_blocks < 2:
        warnings.append(f"Only {unique_blocks} unique yard block(s) — limited "
                        f"block-level analysis possible")

    return errors, warnings


def profile_column(series, col_type="numeric"):
    """Compute profiling statistics for a column."""
    if col_type == "numeric":
        clean = pd.to_numeric(series, errors="coerce").dropna()
        if len(clean) == 0:
            return {"count": 0}
        return {
            "count": int(len(clean)),
            "min": round(float(clean.min()), 2),
            "max": round(float(clean.max()), 2),
            "mean": round(float(clean.mean()), 2),
            "median": round(float(clean.median()), 2),
            "std": round(float(clean.std()), 2),
            "skewness": round(float(clean.skew()), 2),
        }
    else:
        return {
            "count": int(series.notna().sum()),
            "unique": int(series.nunique()),
            "top_values": series.value_counts().head(10).to_dict(),
        }


def profile_dataset(df):
    """Compute full profiling for the dataset."""
    profiling = {}
    numeric_cols = ["size_ft", "weight_tons", "yard_bay", "yard_row", "yard_tier"]
    categorical_cols = ["container_type", "movement_type", "yard_block",
                        "shipping_line", "gate_in_mode", "gate_out_mode",
                        "cargo_category", "iso_type_code"]

    for col in numeric_cols:
        if col in df.columns:
            profiling[col] = profile_column(df[col], "numeric")

    for col in categorical_cols:
        if col in df.columns:
            profiling[col] = profile_column(df[col], "categorical")

    return profiling


def check_weight_outliers(df):
    """Flag weight outliers."""
    warnings = []
    if "weight_tons" in df.columns:
        over = df[df["weight_tons"] > 40]
        under = df[df["weight_tons"] < 1]
        if len(over) > 0:
            warnings.append(f"{len(over)} containers with weight > 40 tons "
                            f"(possible outliers)")
        if len(under) > 0:
            warnings.append(f"{len(under)} containers with weight < 1 ton "
                            f"(possible data error)")
    return warnings


def run_validation(input_path, yard_config_path=None, tariff_config_path=None):
    """Execute the full validation pipeline."""
    report = {
        "status": "PASS",
        "total_rows": 0,
        "valid_rows": 0,
        "excluded_rows": 0,
        "unique_containers": 0,
        "date_range": {},
        "column_quality": {},
        "warnings": [],
        "errors": [],
        "profiling": {},
        "optional_columns_present": [],
        "yard_config_provided": yard_config_path is not None,
        "tariff_config_provided": tariff_config_path is not None,
    }

    # Load data
    try:
        df = pd.read_csv(input_path)
    except Exception as e:
        report["status"] = "FAIL"
        report["errors"].append(f"Could not read CSV file: {str(e)}")
        return report, None

    report["total_rows"] = len(df)

    # Step 1: Schema validation
    missing_cols, optional_present = validate_schema(df)
    report["optional_columns_present"] = optional_present
    if missing_cols:
        report["status"] = "FAIL"
        report["errors"].append(
            f"Missing required columns: {missing_cols}. "
            f"Expected: {REQUIRED_COLUMNS}")
        return report, None

    # Step 2: Type validation
    type_issues = validate_types(df)
    report["warnings"].extend(type_issues)

    # Step 3: Null analysis
    null_report, null_errors, null_warnings = check_nulls(df)
    report["column_quality"] = null_report
    report["errors"].extend(null_errors)
    report["warnings"].extend(null_warnings)

    # Step 4: Date validation
    date_errors, date_warnings, date_excluded = validate_dates(df)
    report["errors"].extend(date_errors)
    report["warnings"].extend(date_warnings)

    # Step 5: Duplicate detection
    dupe_warnings, dupe_excluded = check_duplicates(df)
    report["warnings"].extend(dupe_warnings)

    # Step 6: Weight outliers
    weight_warnings = check_weight_outliers(df)
    report["warnings"].extend(weight_warnings)

    # Combine exclusions
    all_excluded = date_excluded | dupe_excluded
    report["excluded_rows"] = len(all_excluded)
    df_clean = df.drop(index=all_excluded).copy()
    report["valid_rows"] = len(df_clean)

    # Step 7: Minimum requirements
    min_errors, min_warnings = check_minimum_requirements(df_clean)
    report["errors"].extend(min_errors)
    report["warnings"].extend(min_warnings)

    # Step 8: Profiling
    report["profiling"] = profile_dataset(df_clean)

    # Compute date range
    if df_clean["gate_in_time"].notna().any():
        date_min = df_clean["gate_in_time"].min()
        date_max = df_clean["gate_in_time"].max()
        report["date_range"] = {
            "start": str(date_min.date()),
            "end": str(date_max.date()),
            "span_days": (date_max - date_min).days,
        }

    report["unique_containers"] = int(df_clean["container_id"].nunique())

    # Determine final status
    if report["errors"]:
        report["status"] = "FAIL"
    elif report["warnings"]:
        report["status"] = "WARN"
    else:
        report["status"] = "PASS"

    return report, df_clean


def main():
    parser = argparse.ArgumentParser(
        description="Validate and profile container movement data (Stage 1)")
    parser.add_argument("--input", required=True, help="Path to container CSV")
    parser.add_argument("--yard-config", default=None,
                        help="Path to yard configuration JSON")
    parser.add_argument("--tariff-config", default=None,
                        help="Path to tariff configuration JSON")
    parser.add_argument("--output", default="data/data_quality_report.json",
                        help="Path for quality report output")
    parser.add_argument("--validated-output", default="data/validated_containers.csv",
                        help="Path for cleaned/validated CSV output")
    args = parser.parse_args()

    print("=" * 60)
    print("STAGE 1: Data Validation & Profiling")
    print("=" * 60)

    report, df_clean = run_validation(
        args.input, args.yard_config, args.tariff_config)

    # Save report
    with open(args.output, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\nQuality report saved: {args.output}")

    # Save validated data
    if df_clean is not None and report["status"] != "FAIL":
        df_clean.to_csv(args.validated_output, index=False)
        print(f"Validated data saved: {args.validated_output} "
              f"({len(df_clean)} rows)")

    # Print summary
    print(f"\n--- Validation Result: {report['status']} ---")
    print(f"  Total rows: {report['total_rows']}")
    print(f"  Valid rows: {report['valid_rows']}")
    print(f"  Excluded: {report['excluded_rows']}")
    print(f"  Unique containers: {report['unique_containers']}")

    if report["date_range"]:
        print(f"  Date range: {report['date_range']['start']} to "
              f"{report['date_range']['end']} "
              f"({report['date_range']['span_days']} days)")

    if report["errors"]:
        print(f"\n  ERRORS ({len(report['errors'])}):")
        for e in report["errors"]:
            print(f"    ✗ {e}")

    if report["warnings"]:
        print(f"\n  WARNINGS ({len(report['warnings'])}):")
        for w in report["warnings"]:
            print(f"    ⚠ {w}")

    if report["status"] == "FAIL":
        print("\n  ❌ Pipeline STOPPED. Fix errors above and re-run.")
        sys.exit(1)
    else:
        print("\n  ✓ Validation passed. Proceed to Stage 2.")


if __name__ == "__main__":
    main()
