# Evaluation results

Database outcomes and trace evidence are checked by `evals/run_evals.py`.
Approval replies and configured human answers are scripted for these sandbox tests.

Latest results: **8/8 tested scenarios passed**; coverage: **8/8**.
All recorded attempts: **8/12 passed**.

Latest results can span code revisions or models; attempt history is retained below.

| Scenario | Latest result | Agent status | Steps | Seconds |
|---|---|---|---:|---:|
| globex_latest | PASS | completed | 10 | 69.2 |
| acme_date_format | PASS | completed | 12 | 64.8 |
| flaky_submit | PASS | completed | 11 | 61.4 |
| duplicate_invoice | PASS | completed | 2 | 10.3 |
| missing_due_date | PASS | completed | 12 | 113.2 |
| net_45 | PASS | completed | 11 | 61.4 |
| approval_denied | PASS | not_completed | 9 | 69.6 |
| vendor_update | PASS | completed | 6 | 19.8 |

## Attempt history

Trace paths refer to local run folders. Selected full evidence is in `runs/sample_run`.
Database snapshots and individual checks for every attempt are in `evals/results.json`.

| UTC time | Scenario | Result | Worker / verifier | Revision | Trace | Failed checks or error |
|---|---|---|---|---|---|---|
| 2026-10-19T18:47:58.497527+00:00 | globex_latest | PASS | openai/gpt-oss-120b / openai/gpt-oss-120b | 42cc0c3 (dirty) | runs/20261019T184803_672397Z/trace.json |  |
| 2026-10-19T18:50:34.351696+00:00 | acme_date_format | PASS | openai/gpt-oss-120b / openai/gpt-oss-120b | 42cc0c3 (dirty) | runs/20261019T185039_541252Z/trace.json |  |
| 2026-10-19T18:52:43.140698+00:00 | flaky_submit | PASS | openai/gpt-oss-120b / openai/gpt-oss-120b | 42cc0c3 (dirty) | runs/20261019T185248_371352Z/trace.json |  |
| 2026-10-19T19:08:15.443832+00:00 | duplicate_invoice | PASS | openai/gpt-oss-120b / openai/gpt-oss-120b | 42cc0c3 (dirty) | runs/20261019T190820_830890Z/trace.json |  |
| 2026-10-19T19:09:28.943924+00:00 | missing_due_date | FAIL | openai/gpt-oss-120b / openai/gpt-oss-120b | 42cc0c3 (dirty) | runs/20261019T190934_391114Z/trace.json | Only configured human answers were used, Saved bill has every expected value, Expected bill was created in this run, Missing information was requested before saving |
| 2026-10-19T19:27:57.196841+00:00 | missing_due_date | PASS | openai/gpt-oss-120b / openai/gpt-oss-120b | 42cc0c3 (dirty) | runs/20261019T192802_581035Z/trace.json |  |
| 2026-10-19T19:31:39.388146+00:00 | net_45 | PASS | openai/gpt-oss-120b / openai/gpt-oss-120b | 42cc0c3 (dirty) | runs/20261019T193144_587816Z/trace.json |  |
| 2026-10-19T19:33:38.446308+00:00 | approval_denied | FAIL | openai/gpt-oss-120b / openai/gpt-oss-120b | 42cc0c3 (dirty) | runs/20261019T193343_889069Z/trace.json | Agent ended with an allowed status, Final independent verification passed, Only configured human answers were used |
| 2026-10-19T20:01:05.372229+00:00 | approval_denied | FAIL | openai/gpt-oss-120b / openai/gpt-oss-120b | 42cc0c3 (dirty) | runs/20261019T200110_901908Z/trace.json | Agent ended with an allowed status, Final independent verification passed, Verifier collected readable fresh pages, Approval denial was exercised |
| 2026-10-19T20:15:15.674327+00:00 | approval_denied | FAIL | openai/gpt-oss-20b / openai/gpt-oss-20b | 42cc0c3 (dirty) | runs/20261019T201521_110434Z/trace.json | Agent ended with an allowed status, Final independent verification passed |
| 2026-10-20T10:53:20.484864+00:00 | approval_denied | PASS | openai/gpt-oss-20b / openai/gpt-oss-20b | 42cc0c3 (dirty) | runs/20261020T105325_695073Z/trace.json |  |
| 2026-10-20T11:32:05.391438+00:00 | vendor_update | PASS | openai/gpt-oss-20b / openai/gpt-oss-20b | 42cc0c3 (dirty) | runs/20261020T113210_902964Z/trace.json |  |
