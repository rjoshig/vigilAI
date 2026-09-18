# Golden set results

- Provider: `synthetic` · model: `n/a`
- Cases: **12 / 12** met their oracle exactly
- Recall: **100%** (13 of 13 expected findings)
- Precision: **100%** (0 spurious)

## Per finding type

| Finding type | Expected | Found | Missed | Spurious | Recall |
| --- | ---: | ---: | ---: | ---: | ---: |
| count_does_not_reconcile | 1 | 1 | 0 | 0 | 100% |
| extra_rule_in_config | 2 | 2 | 0 | 0 | 100% |
| operator_mismatch | 1 | 1 | 0 | 0 | 100% |
| report_violates_rule | 4 | 4 | 0 | 0 | 100% |
| rule_missing_in_config | 3 | 3 | 0 | 0 | 100% |
| value_mismatch | 1 | 1 | 0 | 0 | 100% |
| waterfall_order_mismatch | 1 | 1 | 0 | 0 | 100% |

## Per case

| Case | Result | Missed | Spurious |
| --- | --- | --- | --- |
| baseline_match | pass | — | — |
| geography_extra_state | pass | — | — |
| score_value_mismatch | pass | — | — |
| rule_missing_in_config | pass | — | — |
| attributes_missing_in_report | pass | — | — |
| counts_do_not_reconcile | pass | — | — |
| operator_boundary_drift | pass | — | — |
| extra_config_filter | pass | — | — |
| report_violates_state_rule | pass | — | — |
| missing_waterfall_step | pass | — | — |
| reordered_waterfall | pass | — | — |
| missing_state_in_config | pass | — | — |
