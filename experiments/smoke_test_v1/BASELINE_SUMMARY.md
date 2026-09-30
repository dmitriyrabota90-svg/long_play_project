# Frozen baseline summary

## Purpose

Phase 9.0 is a reproducible, offline technical smoke test. It confirms the
dataset-to-metric path; it does not establish a production market forecast.

## Frozen dataset and target

- Snapshot range: 2026-05-20 through 2026-09-29, 416 daily feature rows.
- Products: `rapeseed_meal`, `rapeseed_oil`, `soybean_oil`, `soybean_meal`.
- Strict supervised samples: 358 total — 91, 91, 91 and 85 respectively.
- Target: `log(price[t+1] / price[t])`, only when both adjacent calendar days
  contain observed 09:00 and 18:00 MSK price slots.
- No interpolation, carry-forward target, random split or production database
  write is used.

## Frozen feature whitelist

`price_last`, `price_delta_pct_1d`, `price_intraday_delta_pct`,
`price_rolling_mean_3d`, `price_rolling_std_7d`, `usd_rub`,
`usd_rub_delta_pct_1d`, `calendar_day_of_week`, `calendar_month`.

All learned preprocessing is fitted on train rows only. Split is chronological
70/15/15 per product. Pooled mode is diagnostic and uses global date
boundaries plus product one-hot encoding.

## Selected alpha

| Mode / product | Alpha |
| --- | ---: |
| Per-product rapeseed meal | 100 |
| Per-product rapeseed oil | 100 |
| Per-product soybean oil | 100 |
| Per-product soybean meal | 0.01 |
| Pooled diagnostic | 0.01 |

Alpha was selected on validation only; test was not used for selection.

## Test metrics

| Product | Baseline MAE | Ridge MAE | Baseline RMSE | Ridge RMSE | Direction baseline / Ridge |
| --- | ---: | ---: | ---: | ---: | --- |
| rapeseed meal | 0.010272 | 0.010560 | 0.015796 | 0.014798 | 46.7% / 33.3% |
| rapeseed oil | 0.005681 | 0.005740 | 0.008534 | 0.008195 | 33.3% / 40.0% |
| soybean meal | 0.007433 | 0.007134 | 0.010642 | 0.010310 | 35.7% / 35.7% |
| soybean oil | 0.004164 | 0.004736 | 0.006065 | 0.006361 | 33.3% / 33.3% |
| pooled diagnostic | 0.006925 | 0.007383 | 0.010852 | 0.010399 | 36.7% / 40.0% |

## Conclusion and limitations

- Pipeline technically works: **yes**.
- Data is sufficient for this smoke test: **yes**.
- Ridge consistently beats the no-change baseline: **inconclusive**.
- Data is sufficient for a meaningful production baseline: **no**.
- Overfitting risk: **high**; each product has only 59–63 training samples for
  nine numeric features, and the viewed test period must not be repeatedly
  tuned against.

The snapshot preserves useful historical evidence but includes a substantial
July price outage and no complete annual cycle. A later model review needs new
unseen data, stable collection and independently verified time semantics.
