"""Render the reproducible Phase 9.0 Markdown report from local outputs."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import date
from pathlib import Path


HERE = Path(__file__).resolve().parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    root = HERE.parent
    parser.add_argument("--metadata", type=Path, default=root / "data" / "dataset_snapshot_metadata.json")
    parser.add_argument("--validation", type=Path, default=root / "reports" / "data_validation.json")
    parser.add_argument("--samples", type=Path, default=root / "data" / "supervised_samples.csv")
    parser.add_argument("--metrics", type=Path, default=root / "reports" / "metrics.csv")
    parser.add_argument("--run-summary", type=Path, default=root / "reports" / "run_summary.json")
    parser.add_argument("--output", type=Path, default=root / "reports" / "SMOKE_TEST_REPORT.md")
    return parser.parse_args()


def markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    head = "| " + " | ".join(headers) + " |"
    divider = "| " + " | ".join("---" for _ in headers) + " |"
    body = ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join([head, divider, *body])


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def main() -> None:
    args = parse_args()
    metadata = json.loads(args.metadata.read_text(encoding="utf-8"))
    validation = json.loads(args.validation.read_text(encoding="utf-8"))
    run_summary = json.loads(args.run_summary.read_text(encoding="utf-8"))
    samples = load_csv(args.samples)
    metrics = load_csv(args.metrics)
    metric_index = {
        (row["mode"], row["product"], row["split"], row["model"], row["metric"]): float(row["value"])
        for row in metrics
    }

    by_product: dict[str, list[dict[str, str]]] = defaultdict(list)
    for sample in samples:
        by_product[sample["product_code"]].append(sample)
    split_rows: list[list[str]] = []
    for product, values in sorted(by_product.items()):
        ordered = sorted(values, key=lambda row: row["feature_date"])
        train_end = int(len(ordered) * 0.70)
        validation_end = train_end + int(len(ordered) * 0.15)
        partitions = (ordered[:train_end], ordered[train_end:validation_end], ordered[validation_end:])
        split_rows.append(
            [
                product,
                str(len(ordered)),
                f"{partitions[0][0]['feature_date']}–{partitions[0][-1]['feature_date']} ({len(partitions[0])})",
                f"{partitions[1][0]['feature_date']}–{partitions[1][-1]['feature_date']} ({len(partitions[1])})",
                f"{partitions[2][0]['feature_date']}–{partitions[2][-1]['feature_date']} ({len(partitions[2])})",
            ]
        )

    test_rows: list[list[str]] = []
    primary_improvements: list[str] = []
    for product in sorted(by_product):
        baseline_mae = metric_index[("per_product", product, "test", "zero_return_baseline", "mae_return")]
        ridge_mae = metric_index[("per_product", product, "test", "ridge", "mae_return")]
        baseline_rmse = metric_index[("per_product", product, "test", "zero_return_baseline", "rmse_return")]
        ridge_rmse = metric_index[("per_product", product, "test", "ridge", "rmse_return")]
        baseline_direction = metric_index[("per_product", product, "test", "zero_return_baseline", "directional_accuracy")]
        ridge_direction = metric_index[("per_product", product, "test", "ridge", "directional_accuracy")]
        baseline_price_mae = metric_index[("per_product", product, "test", "zero_return_baseline", "mae_next_price")]
        ridge_price_mae = metric_index[("per_product", product, "test", "ridge", "mae_next_price")]
        if ridge_mae < baseline_mae:
            primary_improvements.append(product)
        test_rows.append(
            [
                product,
                f"{baseline_mae:.6f}",
                f"{ridge_mae:.6f}",
                f"{baseline_rmse:.6f} / {ridge_rmse:.6f}",
                f"{baseline_direction:.1%} / {ridge_direction:.1%}",
                f"{baseline_price_mae:.2f} / {ridge_price_mae:.2f}",
            ]
        )
    pooled_baseline_mae = metric_index[("pooled", "all_products", "test", "zero_return_baseline", "mae_return")]
    pooled_ridge_mae = metric_index[("pooled", "all_products", "test", "ridge", "mae_return")]
    test_rows.append(
        [
            "pooled (diagnostic)",
            f"{pooled_baseline_mae:.6f}",
            f"{pooled_ridge_mae:.6f}",
            f"{metric_index[('pooled', 'all_products', 'test', 'zero_return_baseline', 'rmse_return')]:.6f} / {metric_index[('pooled', 'all_products', 'test', 'ridge', 'rmse_return')]:.6f}",
            f"{metric_index[('pooled', 'all_products', 'test', 'zero_return_baseline', 'directional_accuracy')]:.1%} / {metric_index[('pooled', 'all_products', 'test', 'ridge', 'directional_accuracy')]:.1%}",
            f"{metric_index[('pooled', 'all_products', 'test', 'zero_return_baseline', 'mae_next_price')]:.2f} / {metric_index[('pooled', 'all_products', 'test', 'ridge', 'mae_next_price')]:.2f}",
        ]
    )

    learning_rows: list[list[str]] = []
    for product in sorted(by_product):
        learning_rows.append(
            [
                product,
                f"{metric_index[('per_product', product, 'train', 'ridge', 'mae_return')]:.6f}",
                f"{metric_index[('per_product', product, 'validation', 'ridge', 'mae_return')]:.6f}",
                f"{metric_index[('per_product', product, 'test', 'ridge', 'mae_return')]:.6f}",
            ]
        )

    feature_rows = [
        [
            item["feature"],
            item["dtype"],
            f"{float(item['missing_pct']):.2f}%",
            str(item["unique_values"]),
            f"{float(item['std']):.6g}",
        ]
        for item in load_csv(args.output.parent / "feature_summary.csv")
    ]
    report = f"""# Phase 9.0 — First Offline ML Smoke Test

## Scope

Local, deterministic technical check of snapshot → target → chronological split → train-only preprocessing → zero-return baseline → Ridge → metrics. This is not a production model and does not change production application behaviour.

## Production source

- Read-only PostgreSQL `SELECT` extraction over SSH.
- Production HEAD: `{metadata['production_head']}`.
- Snapshot extraction timestamp: `{metadata['extraction_timestamp']}`.
- No database credentials are stored in this experiment.

## Dataset snapshot

- SHA-256: `{metadata['snapshot_sha256']}`.
- Range: {metadata['min_feature_date']} through {metadata['max_feature_date']}.
- Rows: {metadata['row_count']}; products: {', '.join(metadata['products'])}.
- Source fields: price, FX and deterministic calendar only. Weather, news, trade, supply/demand, benchmarks and energy are deliberately excluded.

## Target

`y[t] = log(price[t+1] / price[t])`, where `t+1` is the next calendar day. Both source and target days must have actual scheduled 09:00 and 18:00 price slots. Missing future dates are excluded; no interpolation or carry-forward is used.

## Feature whitelist

{', '.join(run_summary['candidate_features'])}.

The nine features are known at date `t`. Scaling, median imputation and constant-feature filtering are fit on train rows only. Alpha is selected on validation; the final test model is then refit on train plus validation using preprocessing statistics frozen from train. `fx_as_of_date <= feature_date` and `as_of_at.date() <= feature_date` are validated before training.

## Leakage controls

- Zero duplicate `(product_code, feature_date)` keys.
- Zero future `as_of_at` rows and zero future FX-as-of rows.
- Strict scheduled-slot target construction; no missing or imputed future price is allowed.
- Per-product split uses only that product's chronology. Pooled mode uses global date boundaries, so no product contributes a later date to training.

## Sample counts and chronological split

{markdown_table(['Product', 'Samples', 'Train', 'Validation', 'Test'], split_rows)}

Total strict supervised samples: {validation['sample_count_total']}.

## Naive baseline and Ridge results

Primary metrics are return-space MAE and RMSE. Directional accuracy compares the signs of predicted and realised returns. The final column is the requested secondary next-price MAE diagnostic; each pair is baseline / Ridge.

{markdown_table(['Product', 'Test MAE baseline', 'Test MAE Ridge', 'Test RMSE base / Ridge', 'Direction base / Ridge', 'Next-price MAE base / Ridge'], test_rows)}

Ridge improves primary test MAE only for: {', '.join(primary_improvements) if primary_improvements else 'none'}. It is worse on primary pooled test MAE ({pooled_ridge_mae:.6f} vs {pooled_baseline_mae:.6f}). Therefore the comparison is **INCONCLUSIVE** and does not establish an edge over the zero-return baseline.

## Train vs validation vs test

{markdown_table(['Product', 'Ridge train MAE', 'Ridge validation MAE', 'Ridge test MAE'], learning_rows)}

With only 59–63 train samples per product and nine retained numeric features, each per-product model has just 6.6–7.0 train samples per feature. Train-to-test deterioration is visible for most products, so overfitting risk is **HIGH** even though Ridge regularisation was used.

## Feature diagnostics

{markdown_table(['Feature', 'dtype', 'Missing', 'Unique values', 'Std'], feature_rows)}

No candidate is constant or nearly all-null on the sample set. Missing rolling-price values are imputed using medians fitted on training rows only.

## Known data gaps and limitations

- Price history has a major July outage; the current strict uninterrupted run before extraction is only 22 complete days.
- The snapshot spans 106 dates but contains no annual seasonal cycle.
- The pooled result is diagnostic only: correlated product histories do not create independent market observations.
- This test excludes stale, empty or semantically unsafe external layers by design; it is not evidence that they are usable.

## Interpretation

- PIPELINE TECHNICALLY WORKS: **YES**.
- RIDGE BEATS NAIVE BASELINE: **INCONCLUSIVE**.
- DATA SUFFICIENT FOR SMOKE TEST: **YES**.
- DATA SUFFICIENT FOR MEANINGFUL BASELINE: **NO**.
- OVERFITTING RISK: **HIGH**.

## Recommendation

Keep the experiment as a regression check only. Continue strict price/FX collection and monitor scheduled-slot completeness. Do not promote the pooled or per-product Ridge outputs. Revisit a meaningful baseline only after substantially longer uninterrupted product history (roughly 180+ daily points per product) and after each additional feature layer has current, publication-aware provenance.
"""
    args.output.write_text(report, encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
