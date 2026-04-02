# Evaluation Report — Scenario Test Results

**Skill:** Container Dwell Time Analysis & Yard Throughput Optimization
**Generated:** 2026-03-22 (re-run after k-cap and forecast chart fixes)
**Pipeline runtime:** ~33 seconds per scenario (50K containers on MacOS laptop)
**Reproducibility:** All runs use `random_state=42` / `--seed 42` — identical results on re-run

---

## Summary

| # | Scenario | Input | Expected | Actual | Status |
|---|----------|-------|----------|--------|--------|
| 1 | Happy Path | 50K containers, full config | PASS → complete pipeline → full report | Validation: PASS → Report generated (1,656 KB) | ✅ |
| 2 | Minimal Input | 5K containers, required columns only, no configs | PASS → graceful degradation → revenue warns | Validation: PASS → Report generated (1,540 KB) | ✅ |
| 3 | Bad Data | 2K containers, 35% nulls, negative weights, reversed dates | FAIL with clear error report | Validation: FAIL — 3 errors, 3 warnings detected | ✅ |
| 4 | Parameter Sensitivity | 50K containers, threshold=5d vs 10d | Different overstay rates and revenue | Validation: PASS → two reports generated (1,657 KB each) | ✅ |
| 5 | Reefer-Only Terminal | 3K reefer containers, 2 blocks | PASS → single-type handled | Validation: PASS → Report generated (1,552 KB) | ✅ |

All 5 scenarios exercised different paths through the pipeline. Full console traces for each run are in `outputs/scenario_*/scenario_log.txt`.

---

## Scenario 1: Happy Path (50K containers, full configuration)

**Purpose:** Verify the complete pipeline works end-to-end with realistic data and all optional inputs provided.

**Input:** `synthetic_containers.csv` (50,000 rows, 17 columns) + `yard_config.json` (7 blocks) + `tariff_config.json` (4 tiers)

**Key results:**

| Metric | Value | Interpretation |
|--------|-------|---------------|
| Validation status | PASS | All 50,000 rows valid, 0 excluded |
| Unique containers | 45,942 | ~8% repeat visits (realistic) |
| Mean dwell | 4.9 days | Within industry benchmark (3–7 days) |
| Overstay rate | 12.4% (5,989 containers) | Healthy range (10–15% is typical) |
| Total storage revenue | $8,825,047 | Over 6-month period |
| Clustering | KMeans, k=8 | Silhouette 0.3709 (Weak but usable) |
| Forecasting | Holt-Winters Additive | MAPE 3.6% (Excellent) |
| Report | 1,656 KB, 10 sections | All charts embedded, self-contained HTML |

**What this proves:** The full 6-stage pipeline produces a complete, professional report from raw CSV to stakeholder-ready output in ~33 seconds. All 10 report sections generate correctly including the Priority Action List (top 30 overstaying containers by name, shipping line, vessel, and cost).

**Trace location:** `outputs/scenario_1_happy_path/scenario_log.txt`

---

## Scenario 2: Minimal Input (5K containers, 8 columns only, no configs)

**Purpose:** Verify graceful degradation when only the 8 required columns are provided and no yard/tariff configuration files are supplied.

**Input:** `synthetic_containers.csv` stripped to 8 required columns only (5,000 rows). No `yard_config.json`, no `tariff_config.json`.

**Key results:**

| Metric | Value | Interpretation |
|--------|-------|---------------|
| Validation status | PASS | Pipeline proceeds with available data |
| Yard utilization | Estimated from data | Max observed occupancy used as proxy for capacity (no config) |
| Revenue section | Warning displayed | "Tariff configuration not provided — storage cost calculations unavailable" |
| Stack height analysis | Skipped | No yard_tier column present |
| Shipping line analysis | Skipped | No shipping_line column present |
| Report | 1,540 KB | Smaller because fewer sections have data, but no crash |

**What this proves:** The pipeline doesn't crash when optional data is missing. It produces a useful (if less detailed) report and clearly communicates what's missing and why. A real terminal operator can start with just 8 columns and progressively add enrichment data.

**Trace location:** `outputs/scenario_2_minimal_input/scenario_log.txt`

---

## Scenario 3: Bad Data (Deliberately corrupted — pipeline should STOP)

**Purpose:** Verify that the pipeline correctly identifies data quality issues and refuses to produce a misleading report rather than silently proceeding with bad data.

**Input:** 2,000 containers with 4 deliberate corruptions:
- 35.25% null values in `container_type` (exceeds 20% rejection threshold)
- 50 negative weight values
- 14.4% of rows have `gate_out_time` before `gate_in_time` (reversed dates)
- 30 invalid movement_type values ('INVALID_TYPE')

**Key results:**

| Check | Result | Pipeline response |
|-------|--------|------------------|
| container_type nulls | 35.25% (threshold: 20%) | ✗ **REJECT** — error reported |
| Date parsing | 11 unparseable values | ✗ Error reported |
| Reversed dates | 288 rows (14.4%) | ✗ Excluded with count reported |
| Invalid movement_type | 30 values | ⚠ Warning reported |
| Negative weights | 50 values | ⚠ Warning reported |
| Pipeline status | **FAIL — STOPPED** | "Fix errors above and re-run" |

**What this proves:** The validation guardrail works. The pipeline detected all 4 corruption types, quantified each with exact counts and percentages, and stopped rather than producing a misleading report. The error messages are specific enough to be actionable: "container_type: 35.25% null (exceeds 20% threshold) — REJECT" tells the operator exactly which column to clean.

**Trace location:** `outputs/scenario_3_bad_data/scenario_log.txt`

---

## Scenario 4: Parameter Sensitivity (Overstay threshold 5 days vs 10 days)

**Purpose:** Demonstrate that changing a key user parameter produces meaningfully different results, and that the pipeline correctly recalculates all downstream metrics. This fulfills the assignment's "Interactive Parameter Sensitivity" requirement.

**Input:** Same 50K-container dataset run twice with `overstay_threshold_days=5` and `overstay_threshold_days=10`.

**Key results:**

| Metric | Threshold = 5 days | Threshold = 10 days | Impact |
|--------|-------------------|---------------------|--------|
| Overstay rate | 22.0% | 8.7% | +13.3 percentage points |
| Overstay count | 10,658 | 4,205 | +6,453 containers reclassified |
| Total storage revenue | $8,825,047 | $8,825,047 | Identical ($0 change) |
| Dwell category breakdown | More "overstay", fewer "long" | More "long", fewer "overstay" | Classification shifts, not billing |
| Opportunity cost estimate | Higher (more blocked TEU) | Lower (fewer blocked TEU) | Directly proportional to overstay count |

**What this proves:**
1. The threshold changes *classification* (which containers are flagged as overstaying) but not *billing* (total storage revenue is computed from actual dwell, not from the overstay label). This is correct behavior — a terminal doesn't earn more money by lowering its threshold.
2. The opportunity cost estimate changes because more containers are now counted as "blocking capacity." This shows why the threshold should be set based on the terminal's actual free-day policy, not an arbitrary number.
3. Both reports generate identically-structured output — the pipeline is deterministic and parameter-responsive.

**Commentary for terminal operators:** A 5-day threshold is appropriate for terminals with short free-day policies (import free days = 3). A 10-day threshold suits terminals with longer contractual free periods. The "right" value depends on your specific tariff structure and operational tolerance.

**Trace location:** `outputs/scenario_4_param_sensitivity/scenario_log.txt`

---

## Scenario 5: Reefer-Only Terminal (Single container type, 2 blocks)

**Purpose:** Test edge case where the terminal handles only one container type. Many algorithms assume diversity in the data — this scenario verifies the pipeline doesn't break when that assumption fails.

**Input:** 3,000 reefer containers, 2 reefer blocks (R01 with 180 plugs, R02 with 100 plugs).

**Key results:**

| Metric | Value | Interpretation |
|--------|-------|---------------|
| Validation status | PASS | Single-type data is valid |
| Container type distribution | 100% reefer | No dry/empty/hazmat |
| Reefer plug utilization | Prominently featured | Both blocks tracked, plug % calculated |
| Clustering | Still finds meaningful segments | Segments differentiated by dwell + TEU, not by type |
| Forecasting MAPE | 13.3% | Higher than 50K scenario (less data = less pattern) — still "Good" range |
| Report | 1,552 KB | All sections generate, type-mix charts show single bar |

**What this proves:** The pipeline handles edge cases without crashing. Even with only reefer containers, clustering still finds meaningful dwell behavior segments (fast reefers vs slow reefers). The reefer plug utilization section becomes the most prominent analysis — appropriate for a reefer-only terminal. Charts with single-bar distributions still render cleanly (no empty/broken charts).

**Trace location:** `outputs/scenario_5_reefer_only/scenario_log.txt`

---

## Cross-Scenario Observations

1. **Validation guardrails work:** Scenario 3 proves the pipeline refuses bad data. This is critical — an analytics tool that produces confident-looking reports from garbage data is worse than no tool at all.

2. **Graceful degradation works:** Scenario 2 proves the pipeline adapts to available data instead of crashing on missing optional inputs. Real-world terminal data comes in varying levels of completeness.

3. **Parameter sensitivity is meaningful:** Scenario 4 shows the threshold changes classification but not billing — an important insight that demonstrates the pipeline computes metrics correctly from first principles, not from labels.

4. **Edge cases handled:** Scenario 5 proves single-type terminals work. Combined with Scenario 1 (mixed types), this covers the realistic range of terminal configurations.

5. **Reproducibility confirmed:** All scenarios use `random_state=42`. Re-running produces identical outputs — verified during development.

---

## Where to Find Full Evidence

| Evidence type | Location |
|--------------|----------|
| Console traces (all 5 scenarios) | `outputs/scenario_*/scenario_log.txt` |
| Generated reports (4 HTML files) | `outputs/scenario_*/final_report.html` |
| Intermediate data (CSVs, JSONs) | `outputs/scenario_*/` |
| Validation failure details | `outputs/scenario_3_bad_data/data_quality_report.json` |
| Parameter comparison (two full runs) | `outputs/scenario_4_param_sensitivity/threshold_5d/` and `threshold_10d/` |
| Model validation metrics | `outputs/scenario_*/model_outputs/validation_metrics.json` |
| Chart PNGs | `outputs/scenario_*/model_outputs/charts/` |
| Pipeline trace in design document | `docs/design_walkthrough.html` (Page 4) |
