---
name: port-dwell-analytics
description: >
  Perform a complete container dwell time analysis and yard throughput optimization
  for port terminals. Use this skill when the user provides container movement data
  (CSV/Excel) from a port or terminal and wants to understand dwell patterns, yard
  utilization, container segmentation, throughput forecasting, and revenue impact.
  Also use when the user mentions terminal analytics, yard congestion, demurrage
  analysis, container overstay, or port capacity planning. This skill runs a full
  6-stage analytics pipeline: data validation, feature engineering, multi-algorithm
  modelling, result validation, business interpretation, and professional report
  generation.
---

# Container Dwell Time Analysis & Yard Throughput Optimization

## Overview

This skill instructs the LLM to perform a complete analytics pipeline on container
movement data from a port terminal. It takes historical container records (gate-in/out
timestamps, container attributes, yard block assignments) and produces a professional
HTML report with dwell segmentation, yard utilization analysis, throughput forecasting,
revenue impact calculations, and actionable recommendations.

The user is a **terminal operator** — they manage yard space, equipment, and gates.
They are NOT a shipping line. Their revenue comes from handling throughput and storage
charges. Every insight must be framed from the terminal operator's perspective.

## Inputs

The skill expects up to four inputs. Only Input 1 is required.

### Input 1: Container Movement Data (REQUIRED)
A CSV or Excel file where each row is one container visit to the yard.

**Required columns** (reject if missing):
- `container_id` (string): Container identifier (e.g., MSCU7234561)
- `size_ft` (integer): Container size — 20 or 40
- `container_type` (string): One of dry, reefer, hazardous, empty
- `weight_tons` (float): Container gross weight in metric tons
- `gate_in_time` (datetime): When the container entered the yard
- `gate_out_time` (datetime): When the container left the yard (null = still in yard)
- `movement_type` (string): One of import, export, transhipment
- `yard_block` (string): Block identifier where container was stored

**Optional columns** (use if present, skip gracefully if absent):
- `iso_type_code` (string): ISO 6346 type code (e.g., 22G1, 45R1). If present, auto-derive `size_ft`, `container_type`, and `is_high_cube` from the code per REFERENCE.md Section 2.5. Cross-validate against `size_ft` and `container_type` if those are also provided.
- `yard_bay`, `yard_row`, `yard_tier` (int): 3D position — enables stack height analysis
- `vessel_name` (string): Associated vessel — enables vessel surge detection
- `shipping_line` (string): Carrier name — enables per-line dwell profiling
- `cargo_category` (string): Cargo type (food, chemicals, electronics, etc.)
- `gate_in_mode` (string): How container arrived — vessel, truck, rail, barge
- `gate_out_mode` (string): How container departed — vessel, truck, rail, barge

### Input 2: Yard Configuration (OPTIONAL)
A JSON file describing the terminal's physical layout. See REFERENCE.md Section 3 for
the full schema. If not provided, the skill estimates capacity from data (unique blocks,
max observed occupancy as proxy).

### Input 3: Tariff Configuration (OPTIONAL)
A JSON file with the terminal's storage tariff structure: free days by movement type,
tiered daily rates, reefer/hazardous surcharges, and average throughput revenue per TEU.
See REFERENCE.md Section 4 for the full schema. If not provided, the skill skips revenue
impact analysis and reports a warning.

### Input 4: Analysis Parameters (OPTIONAL)
User-specified parameters to customize the analysis. Defaults are used if not provided.

| Parameter | Type | Default | Valid Range | Purpose |
|-----------|------|---------|-------------|---------|
| analysis_date_start | date | min date in data | any valid date | Start of analysis window |
| analysis_date_end | date | max date in data | any valid date | End of analysis window |
| num_segments | int | 4 | 3–8 | Number of dwell behavior clusters |
| overstay_threshold_days | int | 7 | 3–14 | Days beyond which a container is "overstaying" |
| utilization_warning_pct | int | 80 | 60–95 | Block utilization alert threshold |
| forecast_horizon_days | int | 14 | 7–30 | Days to forecast ahead |
| container_types_focus | list | all | any subset of types | Filter analysis to specific types |
| target_blocks | list | all | any subset of blocks | Focus on specific yard blocks |

---

## Pipeline Execution

Execute these six stages **sequentially**. Do not skip stages. Each stage validates its
own output before the next stage begins. If a stage fails validation, produce a clear
error report and stop — do not proceed with invalid data.

---

### STAGE 1: Data Validation & Profiling

**Purpose:** Verify data integrity, profile distributions, and reject malformed input
before any computation.

**Script:** Run `python scripts/validate_data.py --input <csv_path> --yard-config <json_path> --tariff-config <json_path> --output data_quality_report.json`

**The script performs these checks in order:**

1. **Schema validation:** Verify all 8 required columns exist. If any are missing,
   STOP and report which columns are absent with exact expected names.

2. **Type checking:** Confirm `size_ft` contains only integers (20 or 40), `weight_tons`
   is numeric and positive, `gate_in_time` and `gate_out_time` parse as datetime,
   `container_type` contains only valid values (dry, reefer, hazardous, empty),
   `movement_type` contains only valid values (import, export, transhipment).

3. **Null analysis:** For each column, compute null count and null percentage. Apply
   these thresholds:
   - Required columns (except gate_out_time): reject if null > 20%
   - `gate_out_time`: warn if null > 30% (these are containers still in yard)
   - Optional columns: report nulls but do not reject

4. **Logical checks:**
   - `gate_out_time` must be after `gate_in_time` for every row. Flag violations as
     data errors and exclude them. If > 5% of rows have this error, warn the user.
   - No future dates (beyond today). Flag and exclude.
   - `weight_tons` must be between 1 and 45 (typical container range). Flag outliers.

5. **Duplicate detection:** Check for exact row duplicates AND duplicate
   `(container_id, gate_in_time)` pairs. Deduplicate and report count.

6. **Minimum data requirements:**
   - At least 100 unique containers (reject if fewer)
   - At least 30 days of date range span (reject if shorter)
   - At least 2 unique yard blocks (warn if only 1)

7. **Data profiling:** For all numeric columns, compute: min, max, mean, median,
   standard deviation, skewness. For categorical columns: unique value counts and
   distribution percentages. Compute: total rows, unique containers, date range,
   containers per day average.

**Output:** `data_quality_report.json` with structure:
```json
{
  "status": "PASS" | "WARN" | "FAIL",
  "total_rows": int,
  "valid_rows": int,
  "excluded_rows": int,
  "unique_containers": int,
  "date_range": {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD", "span_days": int},
  "column_quality": {"column_name": {"nulls": int, "null_pct": float, "type_valid": bool}},
  "warnings": ["list of warning messages"],
  "errors": ["list of error messages if FAIL"],
  "profiling": {"column_name": {"min": x, "max": x, "mean": x, ...}}
}
```

**If status is FAIL:** Stop the pipeline. Present the error report to the user with
specific guidance on how to fix each issue. Do not proceed.

**If status is WARN:** Continue but include all warnings prominently in the final report.

---

### STAGE 2: Data Preparation & Feature Engineering

**Purpose:** Transform validated raw data into analysis-ready features. Every feature
has a specific formula and business meaning documented in REFERENCE.md.

**Script:** Run `python scripts/feature_engineering.py --input <validated_csv> --yard-config <json_path> --tariff-config <json_path> --params <params_json> --output-container dwell_features.csv --output-block block_daily_features.csv`

**The script computes these features:**

#### Per-Container Features (output: `dwell_features.csv`)

| Feature | Formula | Type |
|---------|---------|------|
| `dwell_hours` | `(gate_out_time − gate_in_time).total_seconds() / 3600` | float |
| `dwell_days` | `dwell_hours / 24` | float |
| `teu_equivalent` | `1 if size_ft == 20 else 2` | int |
| `is_high_cube` | Derived from `iso_type_code` if present (2nd char == "5"), else False. See REFERENCE.md Section 2.4. | bool |
| `iso_container_group` | Derived from `iso_type_code` 3rd char: G=general, R=reefer, T=tank, U=open_top, P=flat_rack. Falls back to `container_type` if no ISO code. | string |
| `dwell_category` | `"short"` if < 24h, `"normal"` if 1–3d, `"long"` if 3–threshold, `"overstay"` if > threshold | string |
| `is_overstay` | `1 if dwell_days > overstay_threshold_days else 0` | int |
| `storage_cost_usd` | Tiered calculation per REFERENCE.md Section 4.3. If no tariff config, set to null. | float |
| `flow_path` | `f"{gate_in_mode}→{gate_out_mode}"` if both present, else `"unknown"` | string |

**Transforms before clustering:**
- Log-transform `dwell_hours` and `storage_cost_usd` if skewness > 2
- Z-score standardize all numeric features used for clustering
- One-hot encode `movement_type` and `container_type`

#### Per-Block-Per-Day Features (output: `block_daily_features.csv`)

| Feature | Formula |
|---------|---------|
| `block_teu_occupied` | Sum of `teu_equivalent` for containers in block on that date |
| `block_utilization_pct` | `(block_teu_occupied / teu_capacity) × 100`. If no yard config, use max observed occupancy as proxy for capacity. |
| `reefer_plug_util_pct` | `(reefer_count_in_block / reefer_plug_count) × 100`. Only for blocks with `has_reefer_plugs == true`. |
| `avg_stack_height` | `mean(yard_tier)` for containers in block on that date. Only if tier data present. |
| `overstay_teu_ratio` | `sum(teu_equivalent where is_overstay==1) / block_teu_occupied` |
| `type_mix_ratio` | Percentage split by container_type in the block that day |

#### Hourly Features (output: appended to `block_daily_features.csv`)

| Feature | Formula |
|---------|---------|
| `gate_throughput_hr` | Count of gate-in + gate-out events per hour |
| `peak_hour_flag` | `1` if hour is in top 20% by gate volume across all data |
| `vessel_surge_flag` | `1` if a single vessel's discharge causes > 15% capacity spike in any block |

**Validation after feature engineering:**
- Verify `dwell_features.csv` has same row count as valid input rows (minus excluded)
- Verify no infinite or NaN values in computed features
- Verify `block_utilization_pct` is between 0 and 150 (allow slight over-count due to timing)
- Report feature summary statistics to the user

---

### STAGE 3: Modelling & Analysis

**Purpose:** Apply multi-algorithm segmentation and forecasting. This stage runs TWO
distinct analyses: clustering for dwell behaviour segmentation, and time-series
forecasting for yard throughput prediction.

**Script:** Run `python scripts/run_models.py --container-features dwell_features.csv --block-features block_daily_features.csv --num-segments <N> --forecast-horizon <D> --random-seed 42 --output-clusters cluster_results.json --output-forecast forecast_results.json --output-validation validation_metrics.json`

#### Part A: Dwell Behaviour Clustering

Run both algorithms for k = 3, 4, 5, 6, 7 (or the user-specified `num_segments` ± 2):

**Algorithm 1 — K-Means:**
- Initialize with k-means++ for stability
- Run with `n_init=10`, `max_iter=300`, `random_state=42`
- Record: cluster labels, centroids, inertia, silhouette score, Calinski-Harabasz index

**Algorithm 2 — Hierarchical Clustering (Ward linkage):**
- Use Ward's minimum variance method
- Record: cluster labels, silhouette score, Calinski-Harabasz index

For each (algorithm, k) combination, store results in `cluster_results.json`.

#### Part B: Yard Throughput Forecasting

Use `block_daily_features.csv` aggregated to total terminal TEU per day as the time series.
Split: last 20% of dates = holdout test set; first 80% = training set.

**Model 1 — SARIMA:**
- Use auto_arima (or grid search) to find optimal (p,d,q)(P,D,Q,s) parameters
- Set s=7 for weekly seasonality
- Record: fitted parameters, in-sample and out-of-sample predictions

**Model 2 — Exponential Smoothing (Holt-Winters):**
- Fit additive and multiplicative seasonal models
- Select the one with lower AIC
- Record: fitted parameters, in-sample and out-of-sample predictions

Generate forecasts for the next `forecast_horizon_days` beyond the data.

---

### STAGE 4: Model/Result Validation

**Purpose:** Quantitatively evaluate all models and select the best ones. The skill
must NOT just pick a result — it must justify with numbers.

**Using validation_metrics.json from Stage 3:**

#### Clustering Validation

For each (algorithm, k) combination:
1. Report silhouette score. Interpret per REFERENCE.md Section 7.3:
   - \> 0.70 = Strong structure
   - 0.50–0.70 = Reasonable
   - 0.25–0.50 = Weak but usable
   - < 0.25 = No meaningful structure — warn user

2. Report Calinski-Harabasz index (higher = better).

3. **Selection logic:** The pipeline tests k=2 through k=10 for complete elbow and
   silhouette curves, but only **selects from k≤8** for interpretability. At k=9 or
   k=10, K-Means begins splitting the same dwell band by container size (20ft vs 40ft),
   producing duplicate archetypes that confuse stakeholders. The full k=2–10 range is
   shown in the charts for analytical transparency; the selection cap ensures the report
   remains operationally useful.

   Within the selectable range, pick the (algorithm, k) with the highest silhouette score,
   UNLESS:
   - The highest-silhouette option has a segment with < 5% of containers → try next best
   - The highest-silhouette option has a segment with > 40% of containers → try next best
   - Two options have silhouette within 0.02 of each other → prefer the one with
     fewer segments for interpretability
   - **k-cap at 8:** The pipeline tests k=2 through k=10 for complete elbow and
     silhouette curves, but only selects from k≤8. At k=9–10, K-Means splits the
     same dwell behavior band by container size (20ft vs 40ft), producing duplicate
     archetypes like four separate "Efficient Operators" segments with identical
     recommendations. The silhouette gain from k=8 to k=10 is marginal (~0.01)
     and not worth the interpretability loss. The full k=2–10 range is still shown
     in the charts for analytical transparency.

4. Generate these validation charts (saved as PNG for report):
   - **Elbow plot:** k on x-axis, inertia on y-axis (K-Means only). Title: "Elbow Plot for Optimal Cluster Count"
   - **Silhouette comparison:** k on x-axis, silhouette score on y-axis, one line per algorithm (k=2 through k=10). Title: "Silhouette Score: K-Means vs Hierarchical"
   - **Dendrogram:** Hierarchical clustering tree (Ward linkage) with red dashed cut line at selected k. Title: "Hierarchical Clustering Dendrogram"
   - **Centroid comparison:** Grouped bar chart showing standardized centroid values per cluster across all features. This is the unsupervised learning equivalent of feature importance — it shows what makes each segment different. Title: "What Makes Each Segment Different? (Cluster Centroids)"

#### Forecasting Validation

For each model, compute on the holdout test set:
1. MAPE (Mean Absolute Percentage Error): Interpret per REFERENCE.md Section 6.3.
2. RMSE (Root Mean Squared Error)
3. MAE (Mean Absolute Error)

**Selection logic:** Pick the model with lower MAPE on the holdout set.
If MAPE > 30%, include a warning: "Forecast reliability is limited. Consider providing
more historical data (ideally 6+ months)."

Generate: **Forecast plot** with actual vs predicted + 95% confidence interval. Title:
"Yard Throughput Forecast — {horizon}-Day Horizon"

---

### STAGE 5: Insight Generation & Interpretation

**Purpose:** Translate numbers into business language. This is where domain expertise
from REFERENCE.md becomes critical. The LLM reads results from Stages 3–4 and consults
REFERENCE.md to produce human-readable interpretations.

**Consult REFERENCE.md before writing any interpretation.** Specifically:
- Section 5 (Segment Archetypes) for labelling clusters
- Section 4 (Demurrage & Storage Revenue) for cost framing
- Section 3 (Yard Structure) for utilization benchmarks
- Section 6 (Forecasting context) for seasonal interpretation

#### Step 5.1: Label Each Segment
For each cluster from Stage 4, compute: mean dwell_days, container count, TEU share,
revenue share (if tariff provided), dominant movement_type, dominant container_type.
Match to the closest archetype in REFERENCE.md Section 5.1 by dwell range.
If > 60% empties → append "(Empties)". If > 40% reefer → append "(Reefers)".

#### Step 5.2: Revenue & Opportunity Cost Analysis (if tariff config provided)
Per segment compute:
- Total storage revenue: `sum(storage_cost_usd)` for all containers in segment
- Opportunity cost: `sum(teu_equivalent × (dwell_days − free_days) × avg_throughput_revenue_per_teu)` for overstaying containers only
- Net impact = opportunity cost − storage revenue (positive = net loss to terminal)

Frame the finding per REFERENCE.md Section 4.4 example format.

#### Step 5.3: Forecast Interpretation
Using the selected forecast model:
- Identify the first date when forecasted utilization exceeds `utilization_warning_pct`
- Compute days until breach from analysis_date_end
- If breach is within forecast horizon, flag as urgent

#### Step 5.4: Flow Path Analysis (if gate_in_mode / gate_out_mode present)
Compute mean dwell by flow_path. Identify the slowest path (e.g., vessel→rail) and
the fastest (e.g., vessel→truck). Frame insight with operational recommendation.

#### Step 5.5: Shipping Line Analysis (if shipping_line present)
Rank shipping lines by mean dwell. Identify the top 3 longest-dwelling lines.
Frame as "lines to engage for improved pickup performance."

#### Step 5.6: Per-Segment Recommendations
For each segment, pull the recommended actions from REFERENCE.md Section 5.3.
Rank recommendations by financial impact (highest opportunity cost first).

---

### STAGE 6: Report Generation

**Purpose:** Compile all results into a professional, multi-section HTML report.

**Script:** Run `python scripts/generate_report.py --quality-report data_quality_report.json --container-features dwell_features.csv --block-features block_daily_features.csv --cluster-results cluster_results.json --forecast-results forecast_results.json --validation-metrics validation_metrics.json --insights <insights_json> --tariff-config <json_path> --output final_report.html`

**The report MUST follow the exact section order defined in REFERENCE.md Section 10.**
Sections to include:

1. **Executive Summary** — 3–5 key findings, headline metrics, top recommendation
2. **Data Quality Summary** — Dataset dimensions, quality score, warnings
3. **Dwell Time Distribution** — Histogram, box plots by movement type and container type
4. **Yard Utilization Analysis** — Block utilization heatmap, reefer plug utilization, stack height
5. **Segmentation Results** — Algorithm comparison, elbow plot, silhouette chart, dendrogram, centroid comparison, segment profiles
6. **Forecasting Results** — Model comparison, forecast plot, breach prediction
7. **Revenue & Cost Impact** — Revenue by segment, opportunity cost, net impact chart
8. **Business Recommendations** — Per-segment actions, priority ranking
9. **Parameter Sensitivity** — If user ran multiple configs, show comparison
10. **Assumptions & Limitations** — Data constraints, model limitations, out-of-scope items
11. **Data Appendix** — Quality report table, correlation matrix, cluster centroids, parameters used

**Chart standards** (per REFERENCE.md Section 9.2):
- Every chart has a descriptive title, axis labels, and legend
- Use colour-blind-friendly palette
- Value labels on bar charts
- Colour bar on heatmaps
- 95% confidence band on forecast plots
- Currency values with symbol and thousand separators
- Save charts as PNG at 300 DPI, embedded in the HTML

**Report footer:** Include analysis timestamp, skill version, and all parameter values used.

**Delivery to user:** After `final_report.html` is generated:
1. Present the HTML file to the user as a viewable/downloadable file
2. Provide a brief summary in the chat (3–5 sentences) covering: total containers analyzed, number of segments found, key finding (e.g., highest-dwell segment), forecast outlook, and top recommendation
3. Ask if the user wants to explore any section in more detail or re-run with different parameters

The report is a self-contained HTML file with all charts embedded as base64 images — no external dependencies. The user can open it in any browser, print to PDF, or share directly.

---

## Error Handling

At every stage, if an error occurs:
1. Log the exact error with stage name, step number, and traceback
2. Produce a partial report containing everything computed so far
3. Clearly indicate which stages completed and which failed
4. Provide actionable guidance for the user to fix the issue and re-run

Common errors and remedies:
- "Column X not found" → Check column names match expected schema; provide mapping
- "Insufficient data" → Need ≥100 containers and ≥30 days of history
- "All clusters have silhouette < 0.25" → Data may lack natural groupings; try reducing features or increasing k range
- "Forecast MAPE > 50%" → Too little data or high volatility; recommend 6+ months of history

---

## File Structure

```
port-dwell-analytics/
├── SKILL.md                          # This file
├── REFERENCE.md                      # Domain knowledge (consult during Stages 5–6)
├── scripts/
│   ├── validate_data.py              # Stage 1
│   ├── feature_engineering.py        # Stage 2
│   ├── run_models.py                 # Stages 3–4
│   ├── generate_report.py            # Stage 6
│   └── generate_synthetic_data.py    # Test data generator
├── data/
│   └── data_dictionary.md            # Column definitions and schemas
├── templates/
│   └── report_template.html          # HTML report skeleton
└── README.md                         # Setup and usage instructions
```

---

## Testing Scenarios

Test this skill with at least these scenarios:

1. **Happy path:** Clean synthetic data with all required + optional columns, full yard config, full tariff config. Expect: complete report with all 11 sections, no warnings.

2. **Minimal input:** Only required columns, no yard config, no tariff config. Expect: report with utilization estimated from data, revenue section shows warning about missing tariff, stack height section skipped.

3. **Bad data:** CSV with > 30% nulls in `container_type`, negative weights, gate_out before gate_in for 10% of rows. Expect: FAIL status with clear error report listing every issue.

4. **Parameter sensitivity:** Same dataset run twice with `overstay_threshold_days=5` then `=10`. Expect: different segment compositions, different revenue calculations, comparison commentary.

5. **Single-type terminal:** Dataset with only reefer containers. Expect: skill handles gracefully, segments still meaningful, reefer plug utilization prominent in report.

---

## Reproducibility

All scripts use `random_state=42` (or user-specified seed) for:
- K-Means initialization
- Train/test split for forecasting
- Any sampling operations

Two runs with identical data and parameters MUST produce identical results.
