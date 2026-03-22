# REFERENCE.md — Domain Knowledge Guide
# Container Dwell Time Analysis & Yard Throughput Optimization

> This file encodes all domain-specific knowledge the LLM needs to interpret data,
> label segments, validate results, and generate actionable business recommendations.
> The LLM MUST consult this file during Stage 5 (Insight Generation) and Stage 6 (Report Generation).
> Do NOT hallucinate domain facts — if it is not documented here, do not claim it.

---

## 1. Container Terminal Operations — Primer

### 1.1 What Is a Container Terminal?

A container terminal is the interface between sea and land transport. It receives containers
from vessels (import), dispatches containers to vessels (export), transfers containers between
vessels (transhipment), and stores empty containers awaiting repositioning.

The terminal operator manages the **yard** (temporary storage area), **berths** (where vessels dock),
**gates** (entry/exit for trucks), and **equipment** (cranes, reach stackers, terminal tractors).

The terminal operator is NOT the shipping line. The operator charges shipping lines, freight
forwarders, and importers/exporters for storage, handling, and demurrage. Terminal revenue
depends on two levers: **throughput** (volume of containers processed) and **storage revenue**
(fees for containers occupying yard space).

### 1.2 The Dwell Time Problem

Container Dwell Time (CDT) is the duration a container physically occupies yard space,
measured from gate-in (or vessel discharge) to gate-out (or vessel loading). It is the single
most important driver of yard capacity.

**Why it matters:**
- Longer dwell = more yard space consumed per container
- More space consumed = fewer containers the terminal can handle
- Fewer containers handled = lower throughput revenue
- At the same time, longer dwell = more demurrage revenue (but with diminishing returns)

The terminal faces a fundamental tension: demurrage revenue from long-dwelling containers
versus the opportunity cost of blocked yard capacity that could serve additional vessel calls.

### 1.3 Real-World Dwell Benchmarks (2025 Data)

| Port | Avg Import Dwell | Median | Source |
|------|-----------------|--------|--------|
| LA/Long Beach (truck) | 2.73 days | — | PMSA Dec 2025 |
| Singapore | 4.2 days | 3.1 days | GoComet 2025 |
| Hamburg | 3.7 days | — | Vizion TradeView 2025 |
| LA/Long Beach (rail) | 4.98 days | — | PMSA Dec 2025 |
| Colombo | 7.8 days | 5.4 days | GoComet 2025 |
| Shanghai | 6.5 days | — | Vizion TradeView 2025 |
| Rotterdam | 9.3 days | 7.8 days | GoComet 2025 |
| Antwerp | 11.4 days | 8.9 days | GoComet 2025 |

**Flow-path validation (LA/Long Beach 2025):**
Truck pickup: 2.73 days average. Rail pickup: 4.98 days average.
Rail-to-truck ratio: 1.82x — validates our generator's 1.40x rail multiplier
(conservative, as LA is a high-frequency rail corridor).

### 1.4 Dwell Time vs. Container Age

**Dwell time** can only be measured for containers that have ALREADY left the facility.
It equals: `gate_out_time − gate_in_time`.

**Container age** is the elapsed time for containers CURRENTLY in the yard. Age is always
less than final dwell time. Terminals that report "average dwell" using container age
underestimate true dwell. This skill uses only completed dwell times (containers with
both gate-in and gate-out timestamps).

**Long-stay containers:** Some containers (especially empties) can sit in the yard for months.
When reporting on specific time periods, long-stay containers may be excluded from averages
but MUST be counted separately, as they consume real capacity. This skill flags containers
with dwell > 30 days as "long-stay" and reports them in a separate section.

---

## 2. Container Types & Space Economics

### 2.1 TEU — The Universal Unit

TEU (Twenty-foot Equivalent Unit) is the standard measure of container capacity.

| Container Size | TEU Equivalent | Ground Slots | Notes |
|---------------|---------------|-------------|-------|
| 20-foot (20') | 1 TEU | 1 slot | Standard dry container |
| 40-foot (40') | 2 TEU | 2 slots | Most common size globally |
| 45-foot (45') | 2.25 TEU | 2+ slots | High-cube, less common |

**Typical port mix:** ~55–65% are 40-foot containers, ~35–45% are 20-foot. This varies by
trade lane — Asian exports tend toward more 40-foot; intra-regional feeders carry more 20-foot.

When computing yard utilization, ALWAYS convert to TEU. A block with 100 containers is NOT
100 TEU — if 60 are 40-foot and 40 are 20-foot, that is (60×2) + (40×1) = 160 TEU.

### 2.2 Container Types by Cargo

| Type | Code | Special Requirements | Typical Dwell |
|------|------|---------------------|---------------|
| Dry / General Purpose | DRY | None — standard stacking | Varies |
| Reefer (Refrigerated) | REF | Power plug (typically 440V), temperature monitoring | Shorter (perishable urgency) |
| Hazardous / Dangerous Goods | HAZ | Segregation from other cargo, distance rules, special blocks | Variable, regulatory-dependent |
| Empty | MTY | No cargo — awaiting repositioning or return | Often very long (low pickup priority) |
| Open Top | OT | Cannot stack other containers on top | Special handling |
| Flat Rack | FR | Oversized cargo, out-of-gauge | Special handling |

**Reefer economics:** Reefer blocks have a hard constraint beyond space — **power plug count**.
A reefer block may have 480 TEU of ground space but only 120 power plugs. Once plugs are
exhausted, no more reefers can be accepted regardless of available space. The skill tracks
`reefer_plug_util_pct` as a separate constraint metric.

### 2.3 Movement Types

| Movement | Definition | Typical Free Days | Typical Dwell |
|----------|-----------|-------------------|---------------|
| Import | Container discharged from vessel, awaiting truck/rail pickup | 3–5 days | 3–5 days (truck), 4–6 days (rail) |
| Export | Container brought by truck/rail, awaiting vessel loading | 5–7 days | 2.5–4 days |
| Transhipment | Container transferred between vessels via yard | 5–10 days | 2–5 days |
| Empty Repositioning | Empty container stored awaiting shipping line instructions | Often no free period | 7–90+ days |

Free days vary by terminal policy, shipping line agreement, and local regulation. The tariff
configuration input allows users to specify their terminal's specific free-day structure.

### 2.4 ISO 6346 Container Type Codes

Real Terminal Operating Systems classify containers using the ISO 6346 standard — a 4-character
code encoding size, type, and characteristics. When the user provides `iso_type_code`, the
skill auto-derives `size_ft`, `container_type`, and `is_high_cube`.

**ISO code structure:** The first character = length, second = height, third+fourth = type.

| ISO Code | Size | Height | Type | Derived container_type | Derived size_ft | High Cube |
|----------|------|--------|------|----------------------|-----------------|-----------|
| 22G1 | 20ft | 8'6" | Standard dry | dry | 20 | No |
| 42G1 | 40ft | 8'6" | Standard dry | dry | 40 | No |
| 45G1 | 40ft | 9'6" | High-cube dry | dry | 40 | Yes |
| 22R1 | 20ft | 8'6" | Reefer | reefer | 20 | No |
| 45R1 | 40ft | 9'6" | High-cube reefer | reefer | 40 | Yes |
| 22T1 | 20ft | 8'6" | Tank container | tank | 20 | No |
| 22U1 | 20ft | 8'6" | Open top | special | 20 | No |
| 42P1 | 40ft | 8'6" | Flat rack | special | 40 | No |
| 42P3 | 40ft | 8'6" | Flat rack (collapsible) | special | 40 | No |

**Derivation rules:**
- First character: "2" = 20ft, "4" = 40ft, "L" = 45ft
- Second character: "2" or "5" = standard height, "5" = high-cube (9'6")
- Third character: "G" = general purpose (dry), "R" = reefer, "T" = tank, "U" = open top, "P" = platform/flat rack
- If `iso_type_code` is provided alongside `size_ft` and `container_type`, cross-validate.
  Flag mismatches as data quality warnings.

**High-cube stacking impact:** High-cube containers (9'6") affect stacking because they
reduce clearance for the tier above. When `is_high_cube` is derived, the skill factors
this into stack height analysis — a block with many HC containers at lower tiers has
effectively reduced stacking capacity.

**Special container types (open top, flat rack, tank):**
- Open top: Cannot have containers stacked on top → effectively max_tier = 1 for that slot
- Flat rack: Out-of-gauge cargo may occupy adjacent slots → TEU consumption can be > 2
- Tank: May have hazardous content, segregation rules apply
- These are grouped as "special" in the simplified type mapping but tracked separately
  when ISO codes are available, enabling finer analysis in the report.

---

## 2.5 Transport Modes & Flow Paths

Containers enter and leave the terminal via different transport modes. The combination
of inbound and outbound mode is the **flow path** — a powerful analytical dimension.

| Flow Path | Typical Scenario | Expected Dwell |
|-----------|-----------------|---------------|
| vessel → truck | Standard import: discharged, picked up by truck | 3–5 days |
| truck → vessel | Standard export: trucked in, loaded onto vessel | 2–4 days |
| vessel → vessel | Transhipment: transferred between vessels via yard | 2–10 days |
| vessel → rail | Intermodal import: discharged, awaits rail departure | 5–10 days (rail schedules less frequent) |
| rail → vessel | Intermodal export: arrives by train, loaded onto vessel | 3–6 days |
| truck → truck | Temporary storage / consolidation | 1–3 days |

**Key insight:** Rail-bound containers consistently dwell longer because rail services
operate on fixed schedules (often 1–3 departures per week), unlike trucks which can
arrive on demand. A terminal showing high average dwell may discover that the "problem"
is concentrated in the vessel→rail flow path, pointing to a scheduling issue rather
than a general operational failure.

**Operational recommendation template:** "Containers on the {flow_path} path average
{mean_dwell:.1f} days dwell, which is {comparison} the terminal average of
{overall_mean:.1f} days. {recommendation}."

---

## 3. Yard Structure & Capacity

### 3.1 Yard Block Layout

A typical container yard is divided into **blocks**. Each block contains:
- **Bays**: Positions along the length of the block (typically 20–50 bays)
- **Rows**: Positions across the width of the block (typically 4–10 rows)
- **Tiers**: Stack height (typically 3–6 tiers for operating stacks)

**Block capacity in TEU** = bays × rows × max_tier × TEU_per_slot

For example: 30 bays × 6 rows × 5 tiers = 900 ground slots × max stacking = capacity.
Actual TEU capacity depends on the mix of 20-foot and 40-foot containers.

### 3.2 Yard Utilization Benchmarks

| Utilization Level | Percentage | Operational Impact |
|-------------------|-----------|-------------------|
| Under-utilized | < 40% | Wasted infrastructure investment |
| Healthy | 40–65% | Optimal balance of capacity and access |
| High | 65–75% | Manageable but requires careful planning |
| Congested | 75–85% | Positioning inefficiency increases; reshuffles rise |
| Critical | > 85% | Terminal struggles to accept new containers; delays cascade |

**Key benchmark:** Container yards operating above 75–80% utilization struggle with
positioning efficiency. High yard density forces additional container moves (reshuffles),
slowing vessel loading and discharge operations. It creates a vicious cycle: congestion
produces high yard density, which creates more congestion.

The recommended maximum sustained utilization is **60–65%** for operational flexibility.
Peak utilization should not exceed **80%** for more than 48 hours.

### 3.3 Stacking & Reshuffles

When containers are stacked, only the topmost container is directly accessible. To retrieve
a container below the top, all containers above it must be moved — these are **reshuffles**
(also called rehandles or relocations).

**Reshuffle impact by stack height:**

| Average Stack Height | Reshuffle Probability | Operational Impact |
|---------------------|----------------------|-------------------|
| 1–2 tiers | ~5–10% | Minimal |
| 3 tiers | ~15–20% | Acceptable |
| 4 tiers | ~25–35% | Noticeable delay |
| 5+ tiers | ~40–55% | Severe — each retrieval may require 2+ reshuffles |

**Cost per reshuffle:** Each reshuffle costs approximately 3–5 minutes of crane time.
At typical equipment operating costs, this translates to $5–15 per reshuffle move.
A terminal processing 1,000 containers/day with a 30% reshuffle rate incurs 300
unnecessary moves daily.

**Rule of thumb:** If `avg_stack_height` for a block exceeds 3.5 and the block
utilization is above 70%, the block is a reshuffle hotspot and likely causing
operational delays.

---

## 4. Demurrage & Storage Revenue

### 4.1 Terminology

| Term | Charged By | Charged To | Where |
|------|-----------|-----------|-------|
| **Demurrage** | Shipping line | Importer/consignee | Container sitting at terminal beyond free days |
| **Storage** | Terminal operator | Shipping line (passed to customer) | Container occupying yard space beyond terminal free days |
| **Detention** | Shipping line | Importer/exporter | Container held outside terminal beyond free days |

This skill focuses on **storage charges** (terminal operator's revenue) and uses "demurrage"
colloquially to mean any time-based yard storage charge.

### 4.2 Tiered Pricing Structure

Storage charges typically follow an escalating tier structure designed to incentivize
faster container pickup:

**Example tariff structure (USD per TEU per day):**

| Period | Rate | Rationale |
|--------|------|-----------|
| Day 1 to free_days | $0 (free) | Grace period |
| Day (free+1) to Day 7 | $10–25 | Gentle nudge |
| Day 8 to Day 14 | $25–50 | Stronger incentive |
| Day 15 to Day 21 | $50–100 | Punitive |
| Day 22+ | $75–200 | Highly punitive |

**Reefer surcharge:** Additional $15–40 per day for power supply and monitoring.
**Hazardous surcharge:** Additional $10–30 per day for safety compliance costs.

**Real-world reference:** Major ports like Los Angeles can charge up to $2,000+ after
two weeks of delay. Some Asian ports like Busan charge as low as $40 per TEU for similar
periods. Charges vary enormously by geography and market conditions.

### 4.3 Storage Cost Computation Formula

For each container:

```
billable_days = max(0, dwell_days − free_days_for_movement_type)
storage_cost = sum across tiers:
    for each tier where billable_days falls:
        days_in_tier × rate_per_teu_per_day × teu_equivalent
    + reefer_surcharge_per_day × dwell_days (if container_type == 'reefer')
    + hazardous_surcharge_per_day × dwell_days (if container_type == 'hazardous')
```

### 4.4 Opportunity Cost Framework

**This is the key strategic insight the report must convey.**

Every TEU-slot occupied by an overstaying container is a slot that cannot serve a new
container. The opportunity cost is:

```
opportunity_cost_per_day = blocked_teu × avg_throughput_revenue_per_teu
```

Where `avg_throughput_revenue_per_teu` is the average handling revenue the terminal earns
per TEU moved (typically $50–150, depending on the terminal and services provided).

**Example insight:** "The overstay cluster contains 187 containers occupying 310 TEU-slots.
At $85 throughput revenue per TEU, these blocked slots represent $26,350/day in lost
throughput capacity — far exceeding the $4,700/day earned in demurrage from these same
containers."

This framing transforms the report from a descriptive analysis into a business case for
action.

---

## 5. Dwell Behaviour Segmentation

### 5.1 Segment Archetypes

After clustering containers by dwell characteristics, assign human-readable labels using
these archetypes. Match clusters to the closest archetype based on mean dwell, TEU share,
and revenue contribution.

| Archetype | Typical Dwell | TEU Share | Revenue Impact | Operational Behaviour |
|-----------|--------------|-----------|---------------|----------------------|
| **Fast Movers** | < 24 hours | 10–20% | Low storage revenue, high throughput value | Transhipment or pre-cleared imports; minimal yard impact |
| **Efficient Operators** | 1–3 days | 30–45% | Moderate storage, high throughput | Standard import/export within free period; ideal behaviour |
| **Standard Dwellers** | 3–7 days | 20–30% | Growing storage revenue | Within or slightly beyond free days; normal operations |
| **Extended Stay** | 7–14 days | 10–20% | High storage revenue | Beyond free period; customs delays, documentation issues |
| **Overstayers** | 14–30 days | 5–15% | Very high storage but high opportunity cost | Blocking capacity; likely abandoned or disputed cargo |
| **Chronic Blockers** | 30+ days | 1–5% | Diminishing returns vs massive opportunity cost | Often empties or abandoned cargo; yard planning nightmare |

### 5.2 Segment Labelling Rules

When assigning labels to clusters produced by the modelling stage:

1. Compute the mean dwell_days for each cluster.
2. Match to the closest archetype by dwell range.
3. Cross-validate with the cluster's dominant movement_type and container_type.
4. If a cluster has >60% empty containers, append "(Empties)" to the label.
5. If a cluster has >40% reefer containers, append "(Reefers)" to the label.
6. Report the label, count, TEU share, and revenue share for each segment.

### 5.3 Segment-Specific Recommendations

| Segment | Recommended Actions |
|---------|-------------------|
| **Fast Movers** | Optimize gate scheduling to reduce wait times; pre-position near berth for transhipment efficiency |
| **Efficient Operators** | Maintain current process; consider loyalty incentives for shipping lines with consistently low dwell |
| **Standard Dwellers** | Monitor for drift toward Extended Stay; send automated pickup reminders at day 3–4 |
| **Extended Stay** | Investigate root causes (customs holds, documentation gaps); consider dedicated liaison with freight forwarders; tiered surcharge enforcement |
| **Overstayers** | Escalate demurrage notices; engage directly with shipping line for container clearance; consider relocation to overflow area to free prime yard space |
| **Chronic Blockers** | Initiate formal clearance procedures; assess legal options for abandoned cargo; relocate to peripheral storage blocks immediately |

---

## 6. Forecasting — Domain Context

### 6.1 Seasonality Patterns in Port Operations

Container terminals exhibit multiple seasonal patterns:

- **Weekly cycle:** Lower gate activity on weekends; vessel arrivals clustered on specific weekdays
- **Monthly cycle:** End-of-month and beginning-of-month volume spikes (inventory cycles)
- **Quarterly cycle:** Pre-holiday surges (Q3–Q4 for retail goods, especially Asia-to-West trade lanes)
- **Annual cycle:** Lunar New Year dip (January/February), monsoon disruptions (June–September for Indian subcontinent ports)

The forecasting model should test for and accommodate these seasonal components.

### 6.2 Forecasting Methods

| Method | Strengths | Weaknesses | Best For |
|--------|-----------|-----------|---------|
| **ARIMA/SARIMA** | Handles trend + seasonality; well-understood statistical properties | Assumes stationarity (after differencing); struggles with multiple seasonal periods | Short-to-medium term forecasting with clear seasonal patterns |
| **Exponential Smoothing (Holt-Winters)** | Intuitive; handles level, trend, and seasonality; robust to noise | Limited to single seasonal period; can overfit short series | Medium-term forecasting with dominant single seasonal cycle |
| **Prophet** (optional) | Handles multiple seasonalities, holidays, changepoints automatically | Black-box; requires more data for good fits | When > 1 year of daily data is available |

### 6.3 Forecast Validation Metrics

| Metric | Formula | Interpretation |
|--------|---------|---------------|
| **MAPE** (Mean Absolute Percentage Error) | mean(\|actual − forecast\| / actual) × 100 | < 10% = Excellent; 10–20% = Good; 20–30% = Acceptable; > 30% = Poor |
| **RMSE** (Root Mean Squared Error) | sqrt(mean((actual − forecast)²)) | Scale-dependent; compare between models only |
| **MAE** (Mean Absolute Error) | mean(\|actual − forecast\|) | Easier to interpret than RMSE; less sensitive to outliers |

**Validation approach:** Use the last 20% of dates as a holdout test set. Report both
in-sample and out-of-sample metrics. If MAPE > 30% on the holdout set, warn the user
that the forecast may not be reliable and recommend collecting more historical data.

---

## 7. Clustering — Domain Context

### 7.1 Feature Selection for Dwell Clustering

The primary features for dwell behaviour segmentation are:

| Feature | Transform | Rationale |
|---------|----------|-----------|
| dwell_hours | Log-transform if skewness > 2 | Core metric |
| teu_equivalent | None (binary: 1 or 2) | Space consumption proxy |
| storage_cost_usd | Log-transform if skewness > 2 | Revenue impact |
| movement_type | One-hot encode | Behavioural context |
| container_type | One-hot encode | Operational context |

Before clustering, standardize all numeric features using Z-score normalization.
Log-transform highly skewed features (dwell, cost) first, then standardize.

### 7.2 Algorithm Comparison

| Algorithm | Approach | Strengths | Weaknesses |
|-----------|----------|-----------|-----------|
| **K-Means** | Centroid-based partitioning | Fast; scales well; interpretable centroids | Assumes spherical clusters; sensitive to outliers and initialization |
| **Hierarchical (Ward)** | Agglomerative with Ward linkage | Produces dendrogram for visual inspection; no need to pre-specify k; handles non-spherical shapes better | Slower for large datasets; memory-intensive |

### 7.3 Validation Metrics

| Metric | Range | Interpretation |
|--------|-------|---------------|
| **Silhouette Score** | −1 to +1 | > 0.70 = Strong structure; 0.50–0.70 = Reasonable; 0.25–0.50 = Weak but usable; < 0.25 = No meaningful structure |
| **Calinski-Harabasz Index** | 0 to ∞ | Higher = better separation between clusters; compare across k values |
| **Davies-Bouldin Index** | 0 to ∞ | Lower = better; measures avg similarity ratio between clusters |

### 7.4 Sanity Checks After Clustering

After selecting the best (algorithm, k) combination:

1. **No tiny segments:** No cluster should contain < 5% of total containers. If it does,
   consider merging with the nearest cluster or reducing k.
2. **No dominant segments:** No cluster should contain > 40% of total containers.
   If it does, the segmentation is not granular enough — increase k.
3. **Interpretability check:** Each cluster must have a distinguishable dwell profile.
   If two clusters have mean dwell within 10% of each other and similar type mix,
   they are not meaningfully different — reduce k.
4. **Revenue validation:** Compute per-segment revenue share. If one segment generates
   > 60% of storage revenue, it likely needs further decomposition.

---

## 8. Data Quality Thresholds

### 8.1 Minimum Data Requirements

| Requirement | Threshold | Action if Violated |
|-------------|-----------|-------------------|
| Unique containers | ≥ 100 | Reject — insufficient data for meaningful segmentation |
| Date range span | ≥ 30 days | Reject — insufficient history for trend/seasonality analysis |
| Null % in required columns | ≤ 20% | Warn if 10–20%; Reject if > 20% |
| Null % in gate_out_time | ≤ 30% | Warn — containers without gate-out are still in yard (use for age analysis only) |
| Duplicate container_id + gate_in_time pairs | ≤ 2% | Deduplicate and warn |
| Negative dwell (gate_out < gate_in) | 0% tolerance | Flag as data error; exclude from analysis |
| Future dates | 0% tolerance | Flag as data error; exclude from analysis |

### 8.2 Data Profiling Checklist

The validation script MUST compute and report ALL of the following:

1. Total row count and unique container count
2. Date range (min date, max date, span in days)
3. Column-by-column: type detected, null count, null %, unique values (for categorical)
4. Numeric distributions: min, max, mean, median, std, skewness (for dwell, weight, etc.)
5. Container size distribution (% 20ft vs 40ft)
6. Container type distribution (% dry vs reefer vs hazardous vs empty)
7. Movement type distribution (% import vs export vs transhipment)
8. Duplicate check (exact row duplicates + container_id + gate_in duplicates)
9. Date parsing success rate
10. Outlier detection: containers with dwell > 365 days, weight > 40 tons, weight < 0

---

## 9. Visualization Specifications

### 9.1 Required Charts in the Report

| Chart | X-Axis | Y-Axis | Color | Title |
|-------|--------|--------|-------|-------|
| Dwell distribution histogram | Dwell days (bins) | Container count | Single color | "Container Dwell Time Distribution" |
| Dwell by movement type | Movement type | Dwell days (box plot) | By movement type | "Dwell Time by Movement Type" |
| Block utilization heatmap | Date | Block ID | Utilization % (gradient) | "Yard Block Utilization Over Time" |
| Segment bar chart | Segment label | Container count | By segment | "Container Count by Dwell Segment" |
| Segment radar chart | Metric axes (dwell, TEU, cost, count) | Value (normalized) | By segment | "Segment Profile Comparison" |
| Revenue by segment | Segment label | Storage revenue (USD) | By segment | "Storage Revenue by Dwell Segment" |
| Opportunity cost comparison | Segment label | USD value | Stacked: demurrage vs opportunity cost | "Revenue vs Opportunity Cost by Segment" |
| Clustering validation | k value | Silhouette score | By algorithm | "Silhouette Score: K-Means vs Hierarchical" |
| Elbow plot | k value | Inertia / Within-cluster SS | Single line | "Elbow Plot for Optimal Cluster Count" |
| Forecast plot | Date | TEU throughput or utilization % | Actual vs forecast + confidence interval | "Yard Throughput Forecast — {horizon} Day Horizon" |
| Gate throughput | Hour of day | Gate movement count | In vs Out | "Hourly Gate Throughput Pattern" |
| Reefer plug utilization | Date | Utilization % | By reefer block | "Reefer Plug Utilization Trend" |

### 9.2 Chart Formatting Standards

- All charts MUST have a descriptive title, axis labels, and legend (where applicable).
- Use colour-blind-friendly palettes (avoid red-green only distinctions).
- Include value labels on bar charts (count or percentage above each bar).
- Heatmaps MUST include a colour bar with clear min/max labels.
- Forecast plots MUST show a 95% confidence interval as a shaded band.
- All monetary values formatted with currency symbol and thousand separators.
- Save each chart as PNG (300 DPI) for the HTML report embedding.

---

## 10. Report Template — Section Blueprint

The final report MUST follow this exact section order and heading structure:

### Section 1: Executive Summary
- 3–5 bullet points summarizing key findings
- Total containers analyzed, date range, terminal name
- Headline metric: average dwell time, peak block utilization
- Headline insight: dominant dwell segment, biggest cost driver
- Top recommendation

### Section 2: Data Quality Summary
- Dataset dimensions (rows, columns, date range)
- Data quality score (% of checks passed)
- Any warnings or exclusions applied
- Summary table of column-level quality metrics

### Section 3: Dwell Time Distribution Analysis
- Overall dwell distribution (histogram)
- Dwell by movement type (box plots)
- Dwell by container type (box plots)
- Dwell category breakdown (short / normal / long / overstay percentages)
- Long-stay container analysis (> 30 days)

### Section 4: Yard Utilization Analysis
- Block-level utilization summary table
- Utilization heatmap over time
- Peak utilization events and dates
- Reefer plug utilization (if reefer blocks present)
- Stack height analysis (if tier data available)

### Section 5: Segmentation Results
- Algorithm comparison table (K-Means vs Hierarchical × k values)
- Silhouette score comparison chart
- Elbow plot
- Selected model justification
- Segment profile table (count, mean dwell, TEU share, revenue share)
- Segment radar charts
- Segment label assignments with archetype mapping

### Section 6: Forecasting Results
- Model comparison table (ARIMA vs Holt-Winters: MAPE, RMSE, MAE)
- Forecast plot (actual vs predicted + confidence interval)
- Selected model justification
- Forecast for upcoming period
- Utilization breach prediction (when will utilization exceed warning threshold?)

### Section 7: Revenue & Cost Impact Analysis
- Storage revenue by segment
- Opportunity cost by segment
- Revenue vs opportunity cost comparison chart
- Total terminal revenue impact summary
- ROI of reducing dwell by 1 day (sensitivity calculation)

### Section 8: Business Recommendations
- Per-segment actionable recommendations (from Section 5.3 of this reference)
- Priority ranking by financial impact
- Quick wins vs strategic initiatives

### Section 9: Parameter Sensitivity (if applicable)
- Comparison of results under different parameter configurations
- Impact of changing overstay threshold on segment composition
- Impact of changing number of segments on cluster quality

### Section 10: Assumptions & Limitations
- Data limitations (missing columns, date range constraints)
- Model limitations (stationarity assumptions, cluster shape assumptions)
- Excluded scenarios (long-stay containers, data quality exclusions)

### Section 11: Data Appendix
- Full data quality report table
- Feature correlation matrix
- Complete cluster centroid table
- Forecast model parameters
- Analysis timestamp and configuration parameters used

---

## 11. Glossary of Terminal Operations Terms

| Term | Definition |
|------|-----------|
| **TEU** | Twenty-foot Equivalent Unit — standard container size measure |
| **CDT** | Container Dwell Time — duration a container occupies yard space |
| **RTG** | Rubber-Tyred Gantry crane — yard equipment for stacking/retrieving |
| **RMG** | Rail-Mounted Gantry crane — automated yard stacking equipment |
| **QC / STS** | Quay Crane / Ship-to-Shore crane — loads/unloads vessels |
| **Reach Stacker** | Mobile equipment for stacking containers (common in smaller terminals) |
| **TOS** | Terminal Operating System — software managing all terminal operations |
| **BAPLIE** | EDI message format containing vessel stowage/bay plan information |
| **Reshuffle / Rehandle** | Moving a container to access one beneath it in the stack |
| **Free Days / Free Time** | Grace period before storage charges begin accruing |
| **Demurrage** | Charge for container occupying terminal space beyond free days |
| **Detention** | Charge for keeping shipping line equipment outside terminal beyond free time |
| **Transhipment** | Container transferred between vessels through the yard (not destined for hinterland) |
| **Berth** | Designated docking position for a vessel at the terminal |
| **Bay / Row / Tier** | 3D coordinates of a container's position in a yard block |
| **PCS** | Port Community System — shared data platform connecting terminal stakeholders |
| **Gate-in / Gate-out** | Container entering or leaving the terminal through the truck gate |
| **Vessel Surge** | Sudden volume spike when a large vessel discharges containers |

---

## 12. Industry References & Data Sources

### Public Datasets
- **Mendeley Data — Container Dwell Time Event Log**: 6-month event log from a real container
  terminal, containing dwelling time process data with anonymized fields.
  (Source: data.mendeley.com/datasets/yvp2b4rtp3/2)
- **Kaggle — Global Container Transportation Dataset**: Container shipping records with
  port information. (Source: kaggle.com/datasets/datapsych212/global-container-transportation-datset)

### Industry Benchmarks Referenced
- Terminal KPI benchmarks: Opsima (2025), Envision Technology (2025)
- Dwell time measurement methodology: Portwise Consultancy (2025)
- Demurrage rate structures: Maersk D&D Tariff (2026), MSC D&D Schedule (2025)
- Yard utilization thresholds: Kpler Port Congestion Guide (2025)
- Reshuffle analysis: Dekker et al. (2006), "Advanced Methods for Container Stacking"
- Container stacking optimization: ScienceDirect, Loadmaster.ai research (2024-2026)
- **Port dwell time benchmarks (2025):** Vizion TradeView (Hamburg, Shanghai), GoComet
  Port Congestion Report (Singapore, Colombo, Antwerp, Rotterdam), PMSA Dwell Time
  Reports (LA/Long Beach truck & rail, monthly 2025)
- **Container ID standard:** ISO 6346:2022, BIC Code Register (bic-code.org)
- **Flow-path dwell validation:** PMSA Dec 2025 — truck 2.73d vs rail 4.98d at LA/LB

### Key Industry KPIs (for benchmarking in reports — validated 2025 data)
- Import dwell (truck pickup): 2.7–3.7 days efficient (LA 2.73d, Hamburg 3.7d, Singapore 3.1d median)
- Import dwell (rail pickup): 4.0–5.0 days efficient (LA rail 4.98d — Dec 2025)
- Import dwell (congested): 6.5–11.4 days (Shanghai 6.5d, Antwerp 11.4d)
- Export dwell: 2.0–3.0 days typical (shorter than import — vessel schedule is known)
- Rail-to-truck dwell ratio: 1.4–1.8x (LA data: 4.98/2.73 = 1.82x)
- Yard utilization: 60–65% (healthy sustained), 80% (congestion threshold)
- Crane moves per hour: 25–35 (efficient terminal)
- Truck turnaround time: 30–45 minutes (target)
- Reshuffle rate: < 20% (acceptable), > 35% (problematic)

---

## 13. Future Enhancements — Not in Current Skill Scope

The following capabilities are out of scope for this skill version but represent natural
extensions for production deployment:

1. **BAPLIE Integration via MCP**: Parse vessel stowage plans to predict container arrivals
   24–48 hours ahead, enabling proactive yard space pre-allocation.
2. **Equipment Utilization Correlation**: Link dwell patterns to RTG/reach stacker utilization
   data to quantify the equipment cost of long-dwell containers.
3. **Real-time Gate Scheduling**: Use gate throughput forecasts to recommend optimal truck
   appointment windows, reducing peak-hour congestion.
4. **Port Community System (PCS) Integration**: Connect to PCS APIs via MCP for live customs
   clearance status, enabling root-cause analysis of import dwell delays.
5. **Automated Demurrage Invoicing**: Generate per-container storage invoices directly from
   dwell calculations, integrating with terminal billing systems.
6. **Multi-Terminal Benchmarking**: Compare dwell performance across terminals within the
   same port authority, identifying best practices for replication.
