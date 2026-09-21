# Anomaly check — synthetic benchmark

Produced by `scripts/anomaly_benchmark.py` · 400 deliveries per scenario · 8 deliveries of history each · seed 20260921.

The check compares a delivery against the median and median absolute deviation of the previous finalized deliveries of the same configuration (`checks/anomaly.py`). No model is involved.

**Precision 92.3% · recall 100.0%**, at the shipped sensitivity of 4 and a minimum history of 3.

| Scenario | Should fire | Did fire | What it is |
| --- | --- | --- | --- |
| ordinary · steady | no | 3.5% | A null rate that sits where it always sits. |
| ordinary · noisy | no | 5.0% | The same, on a measure that moves a lot between deliveries. |
| ordinary · a nudge, steady | no | 15.8% | Up a tenth on a measure that varies by a twentieth. Within reach. |
| ordinary · a nudge, noisy | no | 9.0% | Up by 40% on a measure that already wanders by a quarter. |
| anomaly · four times | yes | 100.0% | The design doc's own example: 4% becoming 18%. |
| anomaly · ten times | yes | 100.0% | A field that has quietly stopped being populated. |
| anomaly · collapse | yes | 100.0% | A rate that goes to zero, which is as odd as one that spikes. |
| anomaly · four times, noisy | yes | 100.0% | The hard case: a real shift on a measure that already wanders. |

## What these numbers are, and are not

The histories are drawn from a normal distribution around a fixed level and the shifts are step changes. Real deliveries drift, have seasons, and change when a customer changes their file — none of which this simulates. **These numbers bound the arithmetic, not the product.** They say the method does what it claims on data that behaves; whether real deliveries behave is a Phase 7 question, and the sensitivity is a console setting for exactly that reason.

## What building it taught

The first version of this table had a scenario asserting that a null rate up by 40% should *not* fire. It fired every time, and the benchmark was right: on a measure that has sat at 4.0% ± 0.2% for eight deliveries, 5.6% is eight deviations out and something has changed. The assumption was wrong, not the check. What counts as a nudge is relative to how much that measure normally moves — which is the entire reason this compares against a spread rather than against a fixed percentage, and it is worth stating because it reads as counterintuitive until you do the arithmetic.
