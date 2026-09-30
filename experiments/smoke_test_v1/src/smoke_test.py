"""Deterministic, local-only utilities for the Phase 9.0 ML smoke test.

The module deliberately reads a checked-in-style CSV snapshot rather than a
database.  Production extraction is performed separately and is read-only.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import mean, pstdev
from typing import Any, Iterable, Sequence

import numpy as np


PRODUCTS = ("rapeseed_meal", "rapeseed_oil", "soybean_oil", "soybean_meal")
TARGET_NAME = "log_return_h1_calendar_day"
ALPHAS = (0.01, 0.1, 1.0, 10.0, 100.0)

# Only these price, FX, and deterministic calendar fields can reach a model.
CANDIDATE_FEATURES = (
    "price_last",
    "price_delta_pct_1d",
    "price_intraday_delta_pct",
    "price_rolling_mean_3d",
    "price_rolling_std_7d",
    "usd_rub",
    "usd_rub_delta_pct_1d",
    "calendar_day_of_week",
    "calendar_month",
)
FORBIDDEN_FEATURE_MARKERS = (
    "weather",
    "energy",
    "benchmark",
    "news",
    "trade",
    "supply",
    "production",
    "consumption",
    "stock",
    "yield",
    "harvest",
    "plant",
)
REQUIRED_SNAPSHOT_COLUMNS = {
    "product_code",
    "feature_date",
    "as_of_at",
    "price_last",
    "price_observations_count",
    "fx_as_of_date",
    "has_regular_price_slots",
    *CANDIDATE_FEATURES,
}


class SmokeTestValidationError(ValueError):
    """Raised when the immutable snapshot cannot safely form samples."""


@dataclass(frozen=True)
class SplitIndices:
    train: tuple[int, ...]
    validation: tuple[int, ...]
    test: tuple[int, ...]


@dataclass(frozen=True)
class FittedPreprocessor:
    feature_names: tuple[str, ...]
    medians: np.ndarray
    means: np.ndarray
    scales: np.ndarray

    def transform(self, rows: Sequence[dict[str, Any]]) -> np.ndarray:
        raw = matrix_from_rows(rows, self.feature_names)
        filled = np.where(np.isnan(raw), self.medians, raw)
        return (filled - self.means) / self.scales


@dataclass(frozen=True)
class RidgeModel:
    alpha: float
    coefficients: np.ndarray
    intercept: float

    def predict(self, matrix: np.ndarray) -> np.ndarray:
        return matrix @ self.coefficients + self.intercept


def parse_optional_float(value: str | None) -> float:
    if value is None or value.strip().lower() in {"", "nan"}:
        return math.nan
    result = float(value)
    if not math.isfinite(result):
        raise SmokeTestValidationError(f"Non-finite numeric input: {value!r}")
    return result


def load_snapshot(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None:
            raise SmokeTestValidationError("Snapshot has no CSV header")
        missing = REQUIRED_SNAPSHOT_COLUMNS.difference(reader.fieldnames)
        if missing:
            raise SmokeTestValidationError(f"Snapshot misses required columns: {sorted(missing)}")
        rows: list[dict[str, Any]] = []
        numeric_columns = set(CANDIDATE_FEATURES) | {"price_last"}
        for raw in reader:
            row: dict[str, Any] = dict(raw)
            row["feature_date"] = date.fromisoformat(raw["feature_date"])
            row["as_of_at"] = datetime.fromisoformat(raw["as_of_at"])
            row["fx_as_of_date"] = date.fromisoformat(raw["fx_as_of_date"]) if raw["fx_as_of_date"] else None
            row["price_observations_count"] = int(raw["price_observations_count"] or 0)
            row["has_regular_price_slots"] = raw["has_regular_price_slots"].strip().lower() in {"t", "true", "1"}
            for column in numeric_columns:
                row[column] = parse_optional_float(raw[column])
            row["calendar_day_of_week"] = parse_optional_float(raw["calendar_day_of_week"])
            row["calendar_month"] = parse_optional_float(raw["calendar_month"])
            rows.append(row)
    return rows


def validate_snapshot(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        raise SmokeTestValidationError("Snapshot has no rows")
    seen: set[tuple[str, date]] = set()
    duplicate_keys: list[str] = []
    future_as_of = 0
    future_fx = 0
    invalid_prices = 0
    unknown_products: set[str] = set()
    for row in rows:
        key = (str(row["product_code"]), row["feature_date"])
        if key in seen:
            duplicate_keys.append(f"{key[0]}:{key[1].isoformat()}")
        seen.add(key)
        if row["product_code"] not in PRODUCTS:
            unknown_products.add(str(row["product_code"]))
        if row["as_of_at"].date() > row["feature_date"]:
            future_as_of += 1
        fx_as_of = row["fx_as_of_date"]
        if fx_as_of is not None and fx_as_of > row["feature_date"]:
            future_fx += 1
        if not math.isfinite(row["price_last"]) or row["price_last"] <= 0:
            invalid_prices += 1
    forbidden = [
        feature
        for feature in CANDIDATE_FEATURES
        if any(marker in feature.lower() for marker in FORBIDDEN_FEATURE_MARKERS)
    ]
    if duplicate_keys or future_as_of or future_fx or invalid_prices or unknown_products or forbidden:
        raise SmokeTestValidationError(
            "Snapshot validation failed: "
            f"duplicates={len(duplicate_keys)}, future_as_of={future_as_of}, "
            f"future_fx={future_fx}, invalid_prices={invalid_prices}, "
            f"unknown_products={sorted(unknown_products)}, forbidden_features={forbidden}"
        )
    return {
        "row_count": len(rows),
        "duplicate_natural_keys": 0,
        "future_as_of_rows": 0,
        "future_fx_rows": 0,
        "invalid_price_rows": 0,
        "forbidden_features": [],
        "min_feature_date": min(row["feature_date"] for row in rows).isoformat(),
        "max_feature_date": max(row["feature_date"] for row in rows).isoformat(),
    }


def build_supervised_samples(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build exact h=1 targets from consecutive full regular-slot dates only."""
    by_product: dict[str, dict[date, dict[str, Any]]] = {product: {} for product in PRODUCTS}
    for row in rows:
        by_product[str(row["product_code"])][row["feature_date"]] = row

    samples: list[dict[str, Any]] = []
    for product in PRODUCTS:
        product_rows = by_product[product]
        for feature_day in sorted(product_rows):
            current = product_rows[feature_day]
            target_day = feature_day + timedelta(days=1)
            future = product_rows.get(target_day)
            if future is None:
                continue
            if not current["has_regular_price_slots"] or not future["has_regular_price_slots"]:
                continue
            current_price = current["price_last"]
            future_price = future["price_last"]
            if not math.isfinite(current_price) or not math.isfinite(future_price) or current_price <= 0 or future_price <= 0:
                continue
            if current["fx_as_of_date"] is None or current["fx_as_of_date"] > feature_day:
                continue
            sample = dict(current)
            sample["target_date"] = target_day
            sample["target_return"] = math.log(future_price / current_price)
            sample["future_price"] = future_price
            samples.append(sample)
    return sorted(samples, key=lambda row: (row["product_code"], row["feature_date"]))


def chronological_split(rows: Sequence[dict[str, Any]]) -> SplitIndices:
    if len(rows) < 10:
        raise SmokeTestValidationError("At least ten samples are required for a 70/15/15 split")
    ordered = sorted(range(len(rows)), key=lambda index: rows[index]["feature_date"])
    train_end = int(len(ordered) * 0.70)
    validation_end = train_end + int(len(ordered) * 0.15)
    if train_end == 0 or validation_end == train_end or validation_end == len(ordered):
        raise SmokeTestValidationError("Split produced an empty partition")
    return SplitIndices(
        train=tuple(ordered[:train_end]),
        validation=tuple(ordered[train_end:validation_end]),
        test=tuple(ordered[validation_end:]),
    )


def pooled_chronological_split(rows: Sequence[dict[str, Any]]) -> SplitIndices:
    """Split on global source dates, so no product leaks a later day into train."""
    unique_days = sorted({row["feature_date"] for row in rows})
    train_end = int(len(unique_days) * 0.70)
    validation_end = train_end + int(len(unique_days) * 0.15)
    if train_end == 0 or validation_end == train_end or validation_end == len(unique_days):
        raise SmokeTestValidationError("Pooled split produced an empty date partition")
    train_days = set(unique_days[:train_end])
    validation_days = set(unique_days[train_end:validation_end])
    test_days = set(unique_days[validation_end:])
    return SplitIndices(
        train=tuple(index for index, row in enumerate(rows) if row["feature_date"] in train_days),
        validation=tuple(index for index, row in enumerate(rows) if row["feature_date"] in validation_days),
        test=tuple(index for index, row in enumerate(rows) if row["feature_date"] in test_days),
    )


def subset(rows: Sequence[dict[str, Any]], indices: Iterable[int]) -> list[dict[str, Any]]:
    return [rows[index] for index in indices]


def matrix_from_rows(rows: Sequence[dict[str, Any]], features: Sequence[str]) -> np.ndarray:
    return np.asarray([[float(row[feature]) for feature in features] for row in rows], dtype=float)


def fit_preprocessor(train_rows: Sequence[dict[str, Any]], candidate_features: Sequence[str] = CANDIDATE_FEATURES) -> FittedPreprocessor:
    matrix = matrix_from_rows(train_rows, candidate_features)
    missing_share = np.mean(np.isnan(matrix), axis=0)
    medians = np.nanmedian(matrix, axis=0)
    filled = np.where(np.isnan(matrix), medians, matrix)
    variances = np.var(filled, axis=0)
    usable = (missing_share < 0.95) & np.isfinite(medians) & (variances > 0)
    if not np.any(usable):
        raise SmokeTestValidationError("No usable train-only features after missingness/variance filtering")
    feature_names = tuple(np.asarray(candidate_features)[usable].tolist())
    selected = filled[:, usable]
    means = np.mean(selected, axis=0)
    scales = np.std(selected, axis=0)
    scales = np.where(scales == 0, 1.0, scales)
    return FittedPreprocessor(feature_names, medians[usable], means, scales)


def fit_ridge(matrix: np.ndarray, target: np.ndarray, alpha: float) -> RidgeModel:
    if matrix.shape[0] != target.shape[0]:
        raise SmokeTestValidationError("Feature and target row counts differ")
    intercept = float(np.mean(target))
    centered_target = target - intercept
    gram = matrix.T @ matrix
    coefficients = np.linalg.solve(gram + alpha * np.eye(matrix.shape[1]), matrix.T @ centered_target)
    return RidgeModel(alpha=float(alpha), coefficients=coefficients, intercept=intercept)


def metrics(true: Sequence[float], predicted: Sequence[float], current_prices: Sequence[float]) -> dict[str, float]:
    truth = np.asarray(true, dtype=float)
    prediction = np.asarray(predicted, dtype=float)
    prices = np.asarray(current_prices, dtype=float)
    if not (np.all(np.isfinite(truth)) and np.all(np.isfinite(prediction)) and np.all(np.isfinite(prices))):
        raise SmokeTestValidationError("Metrics received NaN or Inf")
    error = prediction - truth
    predicted_next_price = prices * np.exp(prediction)
    actual_next_price = prices * np.exp(truth)
    return {
        "mae_return": float(np.mean(np.abs(error))),
        "rmse_return": float(np.sqrt(np.mean(np.square(error)))),
        "directional_accuracy": float(np.mean(np.sign(truth) == np.sign(prediction))),
        "mae_next_price": float(np.mean(np.abs(predicted_next_price - actual_next_price))),
    }


def select_alpha(train_rows: Sequence[dict[str, Any]], validation_rows: Sequence[dict[str, Any]]) -> tuple[float, FittedPreprocessor, RidgeModel]:
    preprocessor = fit_preprocessor(train_rows)
    train_matrix = preprocessor.transform(train_rows)
    validation_matrix = preprocessor.transform(validation_rows)
    train_target = target_array(train_rows)
    validation_target = target_array(validation_rows)
    candidates: list[tuple[float, RidgeModel]] = [(alpha, fit_ridge(train_matrix, train_target, alpha)) for alpha in ALPHAS]
    ranked = sorted(
        ((metrics(validation_target, model.predict(validation_matrix), price_array(validation_rows))["mae_return"], alpha, model) for alpha, model in candidates),
        key=lambda item: (item[0], item[1]),
    )
    _, alpha, model = ranked[0]
    return alpha, preprocessor, model


def target_array(rows: Sequence[dict[str, Any]]) -> np.ndarray:
    return np.asarray([row["target_return"] for row in rows], dtype=float)


def price_array(rows: Sequence[dict[str, Any]]) -> np.ndarray:
    return np.asarray([row["price_last"] for row in rows], dtype=float)


def feature_diagnostics(rows: Sequence[dict[str, Any]], features: Sequence[str]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for feature in features:
        values = [float(row[feature]) for row in rows]
        non_missing = [value for value in values if math.isfinite(value)]
        result.append(
            {
                "feature": feature,
                "dtype": "float64",
                "missing_pct": 100.0 * (len(values) - len(non_missing)) / len(values),
                "unique_values": len(set(non_missing)),
                "std": pstdev(non_missing) if len(non_missing) > 1 else 0.0,
                "variance": (pstdev(non_missing) ** 2) if len(non_missing) > 1 else 0.0,
            }
        )
    return result


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_csv(path: Path, rows: Sequence[dict[str, Any]], fieldnames: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_snapshot_metadata(path: Path, snapshot_path: Path, rows: Sequence[dict[str, Any]], production_head: str, extraction_timestamp: str) -> None:
    metadata = {
        "extraction_timestamp": extraction_timestamp,
        "production_head": production_head,
        "min_feature_date": min(row["feature_date"] for row in rows).isoformat(),
        "max_feature_date": max(row["feature_date"] for row in rows).isoformat(),
        "products": list(PRODUCTS),
        "row_count": len(rows),
        "selected_columns": [
            "product_code", "feature_date", "as_of_at", "price_last", "price_observations_count",
            "price_delta_pct_1d", "price_intraday_delta_pct", "price_rolling_mean_3d",
            "price_rolling_std_7d", "usd_rub", "usd_rub_delta_pct_1d", "fx_as_of_date",
            "calendar_day_of_week", "calendar_month", "has_regular_price_slots",
        ],
        "snapshot_sha256": sha256_file(snapshot_path),
        "read_only_source": "production PostgreSQL SELECT via SSH; no credentials stored",
        "excluded_feature_groups": ["weather", "news", "trade", "supply_demand", "benchmarks", "energy"],
    }
    path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
