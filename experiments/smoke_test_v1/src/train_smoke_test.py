"""Train deterministic zero-return and Ridge smoke-test modes from a local snapshot."""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Sequence

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from smoke_test import (  # noqa: E402
    CANDIDATE_FEATURES,
    chronological_split,
    feature_diagnostics,
    fit_preprocessor,
    fit_ridge,
    load_snapshot,
    metrics,
    pooled_chronological_split,
    price_array,
    subset,
    target_array,
    write_csv,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    root = HERE.parent
    parser.add_argument("--samples", type=Path, default=root / "data" / "supervised_samples.csv")
    parser.add_argument("--metrics", type=Path, default=root / "reports" / "metrics.csv")
    parser.add_argument("--predictions", type=Path, default=root / "reports" / "predictions.csv")
    parser.add_argument("--feature-summary", type=Path, default=root / "reports" / "feature_summary.csv")
    parser.add_argument("--run-summary", type=Path, default=root / "reports" / "run_summary.json")
    return parser.parse_args()


def load_samples(path: Path) -> list[dict[str, Any]]:
    rows = load_snapshot(path)
    # `load_snapshot` only needs the original snapshot columns; restore local target fields here.
    with path.open(newline="", encoding="utf-8") as stream:
        raw_rows = list(csv.DictReader(stream))
    for row, raw in zip(rows, raw_rows, strict=True):
        from datetime import date
        row["target_date"] = date.fromisoformat(raw["target_date"])
        row["target_return"] = float(raw["target_return"])
        row["future_price"] = float(raw["future_price"])
    return rows


def model_rows(
    *,
    mode: str,
    product: str,
    rows: Sequence[dict[str, Any]],
    split,
    append_product_one_hot: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    partitions = {"train": subset(rows, split.train), "validation": subset(rows, split.validation), "test": subset(rows, split.test)}
    preprocessor = fit_preprocessor(partitions["train"])
    feature_names = list(preprocessor.feature_names)

    def transformed(partition_rows: Sequence[dict[str, Any]]) -> np.ndarray:
        matrix = preprocessor.transform(partition_rows)
        if not append_product_one_hot:
            return matrix
        categories = sorted({item["product_code"] for item in rows})
        encoded = np.asarray([[1.0 if item["product_code"] == category else 0.0 for category in categories] for item in partition_rows])
        return np.column_stack((matrix, encoded))

    train_matrix = transformed(partitions["train"])
    validation_matrix = transformed(partitions["validation"])
    test_matrix = transformed(partitions["test"])
    validation_target = target_array(partitions["validation"])
    alpha, selected_model = min(
        (
            (
                metrics(
                    validation_target,
                    candidate.predict(validation_matrix),
                    price_array(partitions["validation"]),
                )["mae_return"],
                candidate,
            )
            for candidate in (fit_ridge(train_matrix, target_array(partitions["train"]), candidate_alpha) for candidate_alpha in (0.01, 0.1, 1.0, 10.0, 100.0))
        ),
        key=lambda item: (item[0], item[1].alpha),
    )
    alpha = selected_model.alpha
    # The alpha was selected from the validation set using the train-only preprocessor;
    # refit model parameters on train+validation after alpha selection only.
    refit_rows = partitions["train"] + partitions["validation"]
    refit_matrix = np.vstack((train_matrix, validation_matrix))
    refit_target = target_array(refit_rows)
    final_model = fit_ridge(refit_matrix, refit_target, alpha)

    predictions_by_split = {
        "train": selected_model.predict(train_matrix),
        "validation": selected_model.predict(validation_matrix),
        "test": final_model.predict(test_matrix),
    }
    metric_rows: list[dict[str, Any]] = []
    prediction_rows: list[dict[str, Any]] = []
    for split_name, partition_rows in partitions.items():
        truth = target_array(partition_rows)
        current_prices = price_array(partition_rows)
        baseline_prediction = np.zeros(len(partition_rows))
        ridge_prediction = predictions_by_split[split_name]
        for model_name, prediction in (("zero_return_baseline", baseline_prediction), ("ridge", ridge_prediction)):
            for metric_name, value in metrics(truth, prediction, current_prices).items():
                metric_rows.append({"mode": mode, "product": product, "split": split_name, "model": model_name, "metric": metric_name, "value": value})
            for row, predicted in zip(partition_rows, prediction, strict=True):
                prediction_rows.append(
                    {
                        "mode": mode,
                        "product": product,
                        "split": split_name,
                        "model": model_name,
                        "feature_date": row["feature_date"].isoformat(),
                        "target_date": row["target_date"].isoformat(),
                        "price_t": row["price_last"],
                        "actual_return": row["target_return"],
                        "predicted_return": float(predicted),
                        "actual_next_price": row["future_price"],
                        "predicted_next_price": float(row["price_last"] * math.exp(predicted)),
                    }
                )
    summary = {
        "mode": mode,
        "product": product,
        "alpha_selected_on_validation": alpha,
        "features_after_train_only_filtering": feature_names + (["product_one_hot"] if append_product_one_hot else []),
        "partition_counts": {name: len(values) for name, values in partitions.items()},
        "samples_per_feature_train": len(partitions["train"]) / train_matrix.shape[1],
    }
    return metric_rows, prediction_rows, summary


def main() -> None:
    args = parse_args()
    rows = load_samples(args.samples)
    metrics_rows: list[dict[str, Any]] = []
    prediction_rows: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["product_code"])].append(row)
    for product in sorted(grouped):
        product_rows = sorted(grouped[product], key=lambda row: row["feature_date"])
        metric_rows, predictions, summary = model_rows(mode="per_product", product=product, rows=product_rows, split=chronological_split(product_rows))
        metrics_rows.extend(metric_rows)
        prediction_rows.extend(predictions)
        summaries.append(summary)

    pooled_rows = sorted(rows, key=lambda row: (row["feature_date"], row["product_code"]))
    metric_rows, predictions, summary = model_rows(
        mode="pooled", product="all_products", rows=pooled_rows, split=pooled_chronological_split(pooled_rows), append_product_one_hot=True
    )
    metrics_rows.extend(metric_rows)
    prediction_rows.extend(predictions)
    summaries.append(summary)

    diagnostics = feature_diagnostics(rows, CANDIDATE_FEATURES)
    write_csv(args.metrics, metrics_rows, ["mode", "product", "split", "model", "metric", "value"])
    write_csv(
        args.predictions,
        prediction_rows,
        ["mode", "product", "split", "model", "feature_date", "target_date", "price_t", "actual_return", "predicted_return", "actual_next_price", "predicted_next_price"],
    )
    write_csv(args.feature_summary, diagnostics, ["feature", "dtype", "missing_pct", "unique_values", "std", "variance"])
    args.run_summary.parent.mkdir(parents=True, exist_ok=True)
    args.run_summary.write_text(json.dumps({"candidate_features": list(CANDIDATE_FEATURES), "runs": summaries}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"runs": summaries}, sort_keys=True))


if __name__ == "__main__":
    main()
