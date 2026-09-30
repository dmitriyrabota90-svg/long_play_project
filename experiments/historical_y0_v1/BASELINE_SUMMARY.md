# HISTORICAL Y0 BASELINE V1 — compact freeze summary

## Verified snapshot

- Source/instrument: Sina via AKShare / `Y0`, daily main continuous series.
- Raw SHA-256: `47f1f8519b87ad8d002a5f5771f4bccd821b16990e494953fb9a6fec5208dd78`.
- Normalized SHA-256: `207b81576fa3db273cb8bb3e9a06ce91c95c0cc6481ce880661491ddaffe97b5`.
- Source payload fetched_at: `2026-09-30T12:01:11+00:00`.
- Input has 5,036 rows, `2006-01-09` through `2026-09-30`; supervised period has 2,674 valid bars, `2015-01-05` through `2025-12-31`.

The external final run is `/home/dmitriy/Projects/parser_dataset/historical_research/experiments/historical_y0_v1/20260930T125500Z_final/`. Its source report and numeric files are immutable inputs to this freeze.

## Fixed experiment

- Target: `log(close_next_published_session / close_t)` after EOD availability of selected daily fields.
- Features (10): `ret_1`, `ret_3`, `ret_5`, `ret_10`, `ret_20`, `volatility_5`, `volatility_20`, `distance_sma20`, `weekday_sin`, `weekday_cos`.
- Split: train 1,704 (2015–2021), validation 483 (2022–2023), test 484 (2024–2025).
- Selected Ridge alpha: `100.0`, selected on validation MAE log-return.

| test period | no-change MAE / RMSE | Ridge MAE / RMSE | Ridge MAE skill |
| --- | ---: | ---: | ---: |
| all | 0.00719484 / 0.00961992 | 0.00720524 / 0.00964411 | -0.001446 |
| 2024 | 0.00817640 / 0.01072225 | 0.00820735 / 0.01074385 | -0.003785 |
| 2025 | 0.00621327 / 0.00837372 | 0.00620313 / 0.00840164 | +0.001633 |

Price-space MAE is expressed only **in units of the source series**: its currency/unit is not confirmed by the saved experiment inputs.

## Limited conclusion

Overall test MAE and RMSE are worse for Ridge. Ridge has slightly lower 2025 MAE but higher 2025 RMSE, so “won in 2025” is not a supported unqualified statement. Paired moving-block bootstrap mean loss delta is `+0.0000104033`, with 95% CI `[-0.0000410812, +0.0000662772]`; stable advantage is inconclusive.

Reproducibility status: `CONFIRMED_FROM_EXISTING_RUNS`; see [REPRODUCIBILITY_VERIFICATION.json](REPRODUCIBILITY_VERIFICATION.json). Interpretive clarifications are in [REPORT_CLARIFICATIONS.md](REPORT_CLARIFICATIONS.md).

```
PIPELINE TECHNICALLY WORKS: YES
HISTORICAL SERIES USABLE FOR THIS RESEARCH: WITH_LIMITATIONS
POINT-IN-TIME CONTINUOUS-SERIES SEMANTICS: UNCONFIRMED
RIDGE IMPROVES TEST MAE: NO
EVIDENCE OF STABLE ADVANTAGE: INCONCLUSIVE
SUITABLE FOR REAL TRADING OR LOCAL FARM-GATE PRICE FORECAST: NOT_ESTABLISHED
```
