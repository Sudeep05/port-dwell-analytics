# Container Dwell Time Analysis & Yard Throughput Optimization

An LLM-powered data analytics skill that performs end-to-end container dwell time analysis for port terminals. Produces professional reports with dwell segmentation, yard utilization analysis, throughput forecasting, revenue impact calculations, and actionable operational recommendations.

**Assignment**: AMPBA Batch 24 — Term 4, CT2 Group Assignment

---

## Domain

**Ports & Terminals — Cargoes Logistics**

This skill is designed for terminal operators who manage yard space, equipment, and gates — not shipping companies. It analyzes historical container movement data to provide strategic insights for yard planning, resource allocation, and revenue optimization. The synthetic data model has been validated against real-time terminal reports from an operational container terminal (March 2026).

---

## How This Skill Works in Practice

This skill is designed to be invoked by any LLM that supports tool use, file handling, and script execution — not tied to any specific platform. The interaction flow:

1. **User uploads** their container movement CSV (and optionally `yard_config.json` + `tariff_config.json`)
2. **User prompts** the LLM with something like: *"Analyze dwell time patterns in this data and generate a report"*
3. **LLM reads SKILL.md** which contains the complete 6-stage pipeline instructions, CLI commands, validation thresholds, and formulas
4. **LLM executes** the pipeline scripts in sequence — validation → feature engineering → modelling → report generation
5. **LLM reads REFERENCE.md** during Stage 5 to apply domain benchmarks, label segments with archetypes, and generate business recommendations
6. **LLM delivers** the final HTML report to the user as a viewable/downloadable file, along with a brief chat summary of key findings (segments found, top recommendation, forecast outlook)

If the user provides only a CSV (no configs), the pipeline runs with graceful degradation — utilization and revenue sections note what's missing instead of crashing. If the user provides configs for a completely different terminal, all calculations adapt automatically — block capacities, tariff tiers, free days, and surcharges are read from the config files, not hardcoded.

The report is a **self-contained HTML file** — all charts are embedded as base64 images, no external dependencies. The user can open it in any browser, print to PDF, email it, or share it directly. No server or internet connection needed to view it.

The skill can also be run standalone without an LLM by executing the scripts manually (see Quick Start below).

---

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

Requires Python 3.9+. Key dependencies: pandas, numpy, scikit-learn, matplotlib, seaborn, statsmodels.

### 2. Generate Synthetic Test Data

```bash
python scripts/generate_synthetic_data.py \
    --num-containers 50000 \
    --seed 42
```

Produces `data/synthetic_containers.csv` (50K containers, 180 days), `data/yard_config.json`, and `data/tariff_config.json`.

### 3. Run the Full Pipeline (4 commands)

```bash
# Stage 1: Data Validation & Profiling
python scripts/validate_data.py \
    --input data/synthetic_containers.csv \
    --yard-config data/yard_config.json \
    --tariff-config data/tariff_config.json

# Stage 2: Feature Engineering
python scripts/feature_engineering.py \
    --input data/validated_containers.csv \
    --yard-config data/yard_config.json \
    --tariff-config data/tariff_config.json

# Stages 3-4: Modelling & Validation
python scripts/run_models.py \
    --container-features data/dwell_features.csv \
    --block-features data/block_daily_features.csv \
    --output-dir data/model_outputs

# Stage 6: Report Generation
python scripts/generate_report.py \
    --container-features data/dwell_features.csv \
    --block-features data/block_daily_features.csv \
    --model-dir data/model_outputs \
    --quality-report data/data_quality_report.json \
    --yard-config data/yard_config.json \
    --tariff-config data/tariff_config.json \
    --output data/final_report.html
```

### 4. View the Report

```bash
open data/final_report.html
```

### 5. Run All 5 Test Scenarios (one command)

```bash
python scripts/run_all_scenarios.py
```

This runs all 5 test scenarios automatically and generates `evaluation/scenario_results.md` with a summary table. Takes approximately 10-15 minutes.

---

## Why 50,000 Containers?

The default dataset size (50K containers over 180 days) is calibrated against real terminal throughput:

| Terminal | Annual TEU | ~Containers/6 months | Our 50K represents |
|----------|-----------|----------------------|---------------------|
| Mid-size Canadian port terminal | ~300K TEU | ~100K containers | 50% of a mid-size terminal's half-year |
| DP World Nhava Sheva, India | ~2M TEU | ~650K containers | ~8% of a major gateway terminal |
| Jebel Ali, Dubai | ~14M TEU | ~4.5M containers | ~1% of a mega-hub |
| Small feeder terminal | ~50-100K TEU | ~25-50K containers | Full 6-month dataset |

**50K is the sweet spot** because:

- It's realistic for a **small-to-mid-size terminal** (like a mid-size Canadian port or a regional Indian port) running at full volume for 6 months, or a slice of a larger terminal's operations.
- It's large enough that **K-Means clustering finds meaningful segments** — with fewer than 10K containers, the long-tail segments (overstayers, chronic blockers) have too few members for statistical significance.
- It's small enough that the **full pipeline runs in under 5 minutes** on a laptop. At 500K+ containers, the Hierarchical clustering step would require significant sampling or a server.
- The **180-day window** (Jan–Jun) captures seasonal variation (winter slack, Ramadan slowdowns, spring peak season) while staying within a single fiscal half-year for reporting.

The `--num-containers` parameter is configurable. For a full-year analysis of a major terminal, use `--num-containers 500000 --start-date 2024-01-01 --end-date 2024-12-31`.

> **Real-data validation**: Our synthetic distributions (avg dwell 4.9 days, 12.4% overstay, import-dominated volume, right-skewed long tail) were validated against live "Inventory on Dock" and "Dwell Time" reports from an operational terminal in March 2026. See `docs/PROJECT_DECISIONS.md` Section 10 for the full comparison.

---

## Pipeline Architecture

```
CSV Data ──► Stage 1 ──► Stage 2 ──► Stages 3-4 ──► Stage 5 ──► Stage 6
             Validate    Features    Model+Valid     LLM          Report
                │            │           │          Insight         │
                ▼            ▼           ▼            │             ▼
           quality.json  features.csv  clusters     labels    final_report.html
                                       forecast    revenue
                                       metrics     recs
```

| Stage | Script | What It Does |
|-------|--------|-------------|
| 1 | `validate_data.py` | Schema validation, null analysis, type checking, duplicate detection, profiling. Outputs `data_quality_report.json`. |
| 2 | `feature_engineering.py` | Dwell hours/days, TEU conversion, ISO code derivation, storage cost, flow path, block-daily utilization. Outputs `dwell_features.csv` + `block_daily_features.csv`. |
| 3-4 | `run_models.py` | K-Means + Hierarchical clustering (k=2–10 tested, selection capped at k≤8 for interpretability — higher k produces duplicate archetypes); Holt-Winters + StatsModels for throughput forecasting. Validates with silhouette, MAPE. Outputs `model_outputs/`. |
| 5 | LLM (via SKILL.md) | Reads REFERENCE.md for domain benchmarks. Labels segments with archetypes, interprets revenue impact, generates per-segment recommendations. |
| 6 | `generate_report.py` | Professional HTML report with embedded charts, insight boxes, tariff assumptions, opportunity cost analysis, what-if sensitivity. |

---

## Inputs

### Required: Container Movement CSV

8 required columns: `container_id`, `size_ft`, `container_type`, `weight_tons`, `gate_in_time`, `gate_out_time`, `movement_type`, `yard_block`.

### Optional: Enrichment Columns

`iso_type_code`, `yard_bay`, `yard_row`, `yard_tier`, `vessel_name`, `shipping_line`, `cargo_category`, `gate_in_mode`, `gate_out_mode`.

### Optional: Configuration Files

- **Yard Config JSON** — terminal block layout, TEU capacities, reefer plug counts
- **Tariff Config JSON** — free days per movement type, tiered storage rates, surcharges

The pipeline degrades gracefully when optional inputs are missing — it skips the corresponding analysis sections and notes what's missing in the report.

See `data/data_dictionary.md` for full column definitions and JSON schemas.

---

## Output: The Report

A self-contained HTML file (no external dependencies) with 10 sections:

1. **Executive Summary** — headline KPIs (avg dwell, overstay rate, revenue, peak utilization)
2. **Data Quality** — validation status, exclusion reasons, null analysis
3. **Dwell Time Distribution** — histogram, cumulative departure curve, faceted movement-type charts, container-type comparison bars
4. **Yard Utilization** — weekly heatmap by block, congestion and under-utilization detection
5. **Segmentation** — K-Means clusters with WHO/BEHAVIOR/WHY/ACTION narrative cards per segment
6. **Forecasting** — Holt-Winters vs StatsModels comparison, MAPE quality interpretation, 14-day forecast
7. **Revenue & Cost Impact** — full tariff assumptions table, opportunity cost with realization caveat, what-if sensitivity
8. **Recommendations** — per-segment actions prioritized by dwell impact, with 20ft/40ft TEU context
9. **Priority Action List** — top 30 overstaying containers by name, shipping line, vessel, block, cost — the "pick up the phone" list
10. **Assumptions & Limitations** — honest scope boundaries, future enhancements

Every section includes a green **insight box** explaining what the chart/table means in plain business language for non-technical stakeholders.

---

## Test Scenarios

All 5 scenarios pass. Run them with `python scripts/run_all_scenarios.py`.

| # | Scenario | Input | Expected | Result |
|---|----------|-------|----------|--------|
| 1 | **Happy Path** | 50K containers, full config | Complete pipeline, full report | ✅ PASS — 3,600 KB report, MAPE 3.6% |
| 2 | **Minimal Input** | 5K containers, 8 columns only, no configs | Pipeline runs, revenue section warns | ✅ PASS — 2,397 KB report, graceful degradation |
| 3 | **Bad Data** | 35% nulls, negative weights, reversed dates | FAIL with clear errors | ✅ FAIL (expected) — 3 errors, 3 warnings detected |
| 4 | **Param Sensitivity** | Same data, threshold=5d vs 10d | Different overstay rates | ✅ PASS — 22.0% vs 8.7% overstay, revenue identical |
| 5 | **Reefer-Only** | 3K reefers, 2 blocks | Single-type handled | ✅ PASS — 1,975 KB report, MAPE 13.3% |

Detailed results: `evaluation/scenario_results.md`

---

## Project Structure

```
port-dwell-analytics/
├── SKILL.md                         # LLM pipeline instructions (6 stages, exact formulas)
├── REFERENCE.md                     # Domain knowledge (benchmarks, archetypes, ISO codes)
├── README.md                        # This file
├── requirements.txt                 # Python dependencies
│
├── scripts/
│   ├── generate_synthetic_data.py   # Synthetic data generator (configurable size/seed)
│   ├── validate_data.py             # Stage 1: Validation & profiling
│   ├── feature_engineering.py       # Stage 2: Feature computation
│   ├── run_models.py                # Stages 3-4: Clustering + forecasting + validation
│   ├── generate_report.py           # Stage 6: HTML report generation
│   └── run_all_scenarios.py         # Automated test runner (all 5 scenarios)
│
├── data/
│   ├── data_dictionary.md           # Column definitions & JSON schemas
│   ├── synthetic_containers.csv     # Generated test data (50K rows)
│   ├── yard_config.json             # Terminal block layout
│   ├── tariff_config.json           # Storage pricing structure
│   ├── validated_containers.csv     # Stage 1 output
│   ├── dwell_features.csv           # Stage 2 output (container-level)
│   ├── block_daily_features.csv     # Stage 2 output (block-daily)
│   ├── data_quality_report.json     # Stage 1 validation report
│   ├── model_outputs/               # Stage 3-4 outputs
│   │   ├── cluster_results.json
│   │   ├── forecast_results.json
│   │   ├── validation_metrics.json
│   │   ├── cluster_labels.csv
│   │   └── charts/*.png
│   └── final_report.html            # Stage 6 output
│
├── outputs/                         # Test scenario results
│   ├── scenario_1_happy_path/       # Full pipeline output
│   ├── scenario_2_minimal_input/    # Minimal columns, no configs
│   ├── scenario_3_bad_data/         # Corrupted data → validation FAIL
│   ├── scenario_4_param_sensitivity/# threshold_5d/ and threshold_10d/
│   └── scenario_5_reefer_only/      # Single container type
│
├── evaluation/
│   └── scenario_results.md          # Auto-generated test results summary
│
├── docs/
│   ├── PROJECT_DECISIONS.md         # Domain decisions, real-data validation
│   ├── BUILD_ORDER.md               # Development chronology
│   └── SETUP_AND_TEST_GUIDE.md      # Detailed setup instructions
│
└── templates/
    └── report_template.html         # Report skeleton
```

---

## Synthetic Data Design Rationale

The data generator isn't random noise — every distribution is calibrated to match real port operations:

| Parameter | Value | Real-world basis |
|-----------|-------|------------------|
| **Movement split** | 44% import, 34% export, 22% transhipment | Typical for a gateway terminal with some relay traffic |
| **Container size** | 40% 20ft, 60% 40ft | Industry standard; real terminals see 55-65% 40ft |
| **Empty rate** | ~14% | Global average 12-18% depending on trade imbalance |
| **Dwell clusters** | 15% fast, 52% normal, 22% extended, 8% overstay, 3% chronic | Matches the "80/20 rule" — 80% of containers clear within a week, 20% linger |
| **Shipping line multipliers** | Maersk 0.85x, ZIM 1.35x, HMM 1.25x | Larger lines have more efficient logistics; smaller lines tend to have longer dwell |
| **Flow path multipliers** | Rail 1.4x, Barge 1.2x, Truck 1.0x | Rail-bound containers wait for scheduled services; trucks are on-demand |
| **Free days** | Import 3d, Export 5d, Transhipment 7d | Standard industry practice; transhipment gets more because it's vessel-to-vessel |
| **Demurrage tiers** | $15→$30→$55→$85/TEU/day | Escalating tiers incentivize faster clearance; rates match mid-range global tariffs |
| **Reefer surcharge** | $25/day, Hazmat $18/day | Reefers consume power; hazmat requires segregation and monitoring |

These aren't arbitrary — they come from industry benchmarks (Drewry Maritime Research, JOC Inland Distribution Report, terminal operator tariff schedules) and the team member's direct operational experience. See `REFERENCE.md` for full source citations.

---

## Key Features Beyond Standard Requirements

| Feature | What It Does | Why It Matters |
|---------|-------------|----------------|
| **Dual analytics** | Clustering (dwell segmentation) + Forecasting (throughput prediction) | Two required algorithms in one coherent pipeline |
| **Revenue & opportunity cost** | Quantifies blocked-capacity cost vs demurrage income | Translates data into dollar decisions |
| **Opportunity cost caveat** | Notes 40-70% realization rate for theoretical maximum | Honest, not inflated — builds stakeholder trust |
| **ISO 6346 support** | Auto-derives size, type, high-cube from standard codes | Works with real terminal data formats |
| **Flow path analysis** | Vessel→truck vs vessel→rail dwell comparison | Identifies infrastructure-dependent delays |
| **Shipping line profiling** | Identifies carriers with worst dwell patterns | Enables targeted engagement |
| **Segment narrative cards** | WHO/BEHAVIOR/WHY/ACTION per cluster | Stakeholders understand what to do, not just what happened |
| **Faceted charts** | Separate panels per movement type (no overlap) | Readable by non-analysts |
| **Cumulative departure curve** | "90% of containers leave by day X" | The single most useful chart for operations managers |
| **Tariff transparency** | Full rate card displayed with source attribution | Auditable, adjustable |
| **What-if sensitivity** | ±30%, ±50% throughput revenue scenarios | Strategic planning support |
| **Graceful degradation** | Works with 8 columns, progressively adds analysis | No crash on missing optional data |
| **Real-data validation** | Synthetic model validated against live terminal reports | Confirms distributions match real operations |

---

## Reproducibility

All scripts use `random_state=42` (or `--seed 42`) for deterministic results. Two runs with identical inputs and seeds produce identical outputs. The `run_all_scenarios.py` script captures full console output in `scenario_log.txt` files for each scenario.

---

## 📋 Execution Evidence (Test Scenarios)

> **NOTE:** All 5 test scenarios have been executed with full pipeline runs. The execution evidence, intermediate outputs, and final reports are available in the `outputs/` folder.

| Scenario | Location | Evidence Files |
|----------|----------|----------------|
| **1. Happy Path** (50K containers) | `outputs/scenario_1_happy_path/` | `scenario_log.txt`, `final_report.html`, `dwell_features.csv`, `data_quality_report.json` |
| **2. Minimal Input** (5K, no configs) | `outputs/scenario_2_minimal_input/` | `scenario_log.txt`, `final_report.html`, all intermediate CSVs |
| **3. Bad Data** (35% nulls, adversarial) | `outputs/scenario_3_bad_data/` | `scenario_log.txt`, `data_quality_report.json` (shows FAIL detection) |
| **4. Parameter Sensitivity** (5d vs 10d) | `outputs/scenario_4_param_sensitivity/` | `threshold_5d/` and `threshold_10d/` subfolders with full outputs |
| **5. Reefer-Only Terminal** | `outputs/scenario_5_reefer_only/` | `scenario_log.txt`, `final_report.html`, reefer-specific configs |

**Summary of results:** See `evaluation/scenario_results.md` for the consolidated test results table.

---

## Authors

AMPBA Batch 24 — Term 4, CT2 Group Assignment

## License

Academic use only — ISB AMPBA program.
