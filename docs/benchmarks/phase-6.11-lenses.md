# Golden set results

- Provider: `synthetic` · model: `n/a` · lenses: `delivery,compliance,requirements`
- Cases: **15 / 15** met their oracle exactly
- Recall: **100%** (14 of 14 expected findings)
- Precision: **100%** (0 spurious)
- Coverage: **99%** of requirements were compared against a report (105 of 106); 1 left unevidenced
- Model calls: **345** across every case

Precision and recall say how often the tool is right about what it looked at.
Coverage says how much it looked at. A run that finds nothing because it
compared nothing scores perfectly on the first two (ADR-035).

## Per finding type

| Finding type | Expected | Found | Missed | Spurious | Recall |
| --- | ---: | ---: | ---: | ---: | ---: |
| count_does_not_reconcile | 1 | 1 | 0 | 0 | 100% |
| credit_date_missing | 1 | 1 | 0 | 0 | 100% |
| extra_rule_in_config | 2 | 2 | 0 | 0 | 100% |
| operator_mismatch | 1 | 1 | 0 | 0 | 100% |
| report_violates_rule | 4 | 4 | 0 | 0 | 100% |
| rule_missing_in_config | 3 | 3 | 0 | 0 | 100% |
| value_mismatch | 1 | 1 | 0 | 0 | 100% |
| waterfall_order_mismatch | 1 | 1 | 0 | 0 | 100% |

## Per programme

The rollout gates are per programme, so the numbers are too (`gd-rollout-plan.md`).

| Programme | Cases | Passed | Recall | Precision |
| --- | ---: | ---: | ---: | ---: |
| (none) | 13 | 13 | 100% | 100% |
| AM | 1 | 1 | — | — |
| AS | 1 | 1 | — | — |

## Per case

| Case | Result | Missed | Spurious | Checked | Unevidenced | Reports with no check |
| --- | --- | --- | --- | ---: | ---: | --- |
| baseline_match | pass | — | — | 7/7 | 0 | billing, field_distribution |
| geography_extra_state | pass | — | — | 7/7 | 0 | billing, field_distribution |
| score_value_mismatch | pass | — | — | 7/7 | 0 | billing, field_distribution |
| rule_missing_in_config | pass | — | — | 7/7 | 0 | billing, field_distribution |
| attributes_missing_in_report | pass | — | — | 7/7 | 0 | billing, field_distribution |
| counts_do_not_reconcile | pass | — | — | 7/7 | 0 | billing, field_distribution |
| operator_boundary_drift | pass | — | — | 7/7 | 0 | billing, field_distribution |
| extra_config_filter | pass | — | — | 7/7 | 0 | billing, field_distribution |
| report_violates_state_rule | pass | — | — | 7/7 | 0 | billing, field_distribution |
| missing_waterfall_step | pass | — | — | 7/7 | 0 | billing, field_distribution |
| reordered_waterfall | pass | — | — | 7/7 | 0 | billing, field_distribution |
| missing_state_in_config | pass | — | — | 7/7 | 0 | billing, field_distribution |
| unevidenced_requirement | pass | — | — | 7/8 | 1 | billing, field_distribution |
| report_nothing_checks | pass | — | — | 7/7 | 0 | billing, field_distribution, segment_summary |
| credit_date_not_in_reports | pass | — | — | 7/7 | 0 | billing, field_distribution |
