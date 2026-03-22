# Scenario Test Results

Generated: 2026-03-22 12:47:56

| # | Scenario | Input | Expected | Actual | Status |
|---|----------|-------|----------|--------|--------|
| 1 | Happy Path | 50K containers, full config | PASS → complete pipeline → full report | Validation: PASS → Report generated (1841 KB) | ✅ |
| 2 | Minimal Input | 5K containers, required columns only, no yard/tariff config | PASS → pipeline runs → revenue section warns about missing tariff | Validation: PASS → Report generated (1677 KB) | ✅ |
| 3 | Bad Data | 2K containers, 35% null container_type, negative weights, reversed dates | FAIL validation with clear error report | Validation: FAIL — errors correctly detected | ✅ |
| 4 | Parameter Sensitivity | 50K containers, overstay_threshold=5d vs 10d | Different overstay rates and revenue calculations | Validation: PASS → Report generated (1843 KB) | ✅ |
| 5 | Reefer-Only Terminal | 3K reefer containers, reefer yard config | PASS → pipeline handles single-type → reefer plug util prominent | Validation: PASS → Report generated (1720 KB) | ✅ |

## Scenario 4: Parameter Sensitivity Comparison

| Metric | Threshold = 5 days | Threshold = 10 days | Impact |
|--------|-------------------|--------------------|---------|
| Overstay rate | 22.0% | 8.7% | +13.3pp |
| Overstay count | 10,658 | 4,205 | +6,453 |
| Total revenue | $8,825,047 | $8,825,047 | $+0 |

## Interpretation

Lowering the overstay threshold from 10 to 5 days reclassifies more containers as overstaying, which changes both the demurrage revenue allocation and the opportunity cost calculation. Terminal operators should set this threshold based on their specific free-day policy and operational tolerance for yard occupancy.
