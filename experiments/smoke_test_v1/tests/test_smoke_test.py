from __future__ import annotations

import math
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from smoke_test import (  # noqa: E402
    CANDIDATE_FEATURES,
    SmokeTestValidationError,
    build_supervised_samples,
    chronological_split,
    fit_preprocessor,
    fit_ridge,
    metrics,
    pooled_chronological_split,
    validate_snapshot,
)


def row(day: date, *, product: str = "rapeseed_meal", price: float = 100.0, full: bool = True, fx_day: date | None = None) -> dict[str, object]:
    return {
        "product_code": product,
        "feature_date": day,
        "as_of_at": datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc),
        "price_last": price,
        "price_observations_count": 2,
        "price_delta_pct_1d": 0.01,
        "price_intraday_delta_pct": 0.02,
        "price_rolling_mean_3d": price,
        "price_rolling_std_7d": 1.0,
        "usd_rub": 80.0,
        "usd_rub_delta_pct_1d": 0.001,
        "fx_as_of_date": fx_day or day,
        "calendar_day_of_week": float(day.isoweekday()),
        "calendar_month": float(day.month),
        "has_regular_price_slots": full,
    }


def test_target_shift_uses_exact_next_calendar_day() -> None:
    start = date(2026, 1, 1)
    samples = build_supervised_samples([row(start, price=100), row(start + timedelta(days=1), price=110)])
    assert len(samples) == 1
    assert samples[0]["target_date"] == start + timedelta(days=1)
    assert samples[0]["target_return"] == pytest.approx(math.log(1.1))


def test_missing_or_incomplete_future_price_excludes_sample() -> None:
    start = date(2026, 1, 1)
    assert build_supervised_samples([row(start)]) == []
    assert build_supervised_samples([row(start), row(start + timedelta(days=1), full=False)]) == []


def test_validation_rejects_future_fx_as_of_date() -> None:
    start = date(2026, 1, 1)
    with pytest.raises(SmokeTestValidationError, match="future_fx=1"):
        validate_snapshot([row(start, fx_day=start + timedelta(days=1))])


def test_chronological_split_preserves_source_date_order() -> None:
    start = date(2026, 1, 1)
    rows = [{"feature_date": start + timedelta(days=index)} for index in range(20)]
    split = chronological_split(rows)
    assert max(rows[index]["feature_date"] for index in split.train) < min(rows[index]["feature_date"] for index in split.validation)
    assert max(rows[index]["feature_date"] for index in split.validation) < min(rows[index]["feature_date"] for index in split.test)


def test_chronological_split_labels_do_not_extend_past_next_partition_prediction() -> None:
    start = date(2026, 1, 1)
    rows = [
        {"feature_date": start + timedelta(days=index), "target_date": start + timedelta(days=index + 1)}
        for index in range(20)
    ]
    split = chronological_split(rows)
    assert max(rows[index]["target_date"] for index in split.train) <= min(rows[index]["feature_date"] for index in split.validation)
    assert max(rows[index]["target_date"] for index in split.validation) <= min(rows[index]["feature_date"] for index in split.test)


def test_pooled_split_has_global_date_boundaries() -> None:
    start = date(2026, 1, 1)
    rows = [
        {"feature_date": start + timedelta(days=day), "product_code": product}
        for day in range(20)
        for product in ("rapeseed_meal", "rapeseed_oil")
    ]
    split = pooled_chronological_split(rows)
    assert max(rows[index]["feature_date"] for index in split.train) < min(rows[index]["feature_date"] for index in split.validation)
    assert max(rows[index]["feature_date"] for index in split.validation) < min(rows[index]["feature_date"] for index in split.test)


def test_pooled_split_labels_do_not_extend_past_next_partition_prediction() -> None:
    start = date(2026, 1, 1)
    rows = [
        {
            "feature_date": start + timedelta(days=day),
            "target_date": start + timedelta(days=day + 1),
            "product_code": product,
        }
        for day in range(20)
        for product in ("rapeseed_meal", "rapeseed_oil")
    ]
    split = pooled_chronological_split(rows)
    assert max(rows[index]["target_date"] for index in split.train) <= min(rows[index]["feature_date"] for index in split.validation)
    assert max(rows[index]["target_date"] for index in split.validation) <= min(rows[index]["feature_date"] for index in split.test)


def test_preprocessor_is_fit_on_train_only() -> None:
    start = date(2026, 1, 1)
    train = [row(start, price=100), row(start + timedelta(days=1), price=102)]
    test = [row(start + timedelta(days=2), price=10_000)]
    fitted = fit_preprocessor(train)
    price_index = fitted.feature_names.index("price_last")
    assert fitted.means[price_index] == pytest.approx(101.0)
    transformed = fitted.transform(test)
    assert transformed[0, price_index] > 100.0


def test_ridge_fit_is_deterministic() -> None:
    matrix = np.asarray([[0.0], [1.0], [2.0], [3.0]])
    target = np.asarray([0.0, 0.1, 0.2, 0.3])
    first = fit_ridge(matrix, target, alpha=1.0).predict(matrix)
    second = fit_ridge(matrix, target, alpha=1.0).predict(matrix)
    assert np.array_equal(first, second)


def test_zero_return_baseline_metrics_are_correct() -> None:
    result = metrics([0.1, -0.1], [0.0, 0.0], [100.0, 100.0])
    assert result["mae_return"] == pytest.approx(0.1)
    assert result["rmse_return"] == pytest.approx(0.1)
    assert result["directional_accuracy"] == 0.0


def test_only_allowed_feature_groups_are_candidates() -> None:
    forbidden = ("weather", "news", "trade", "supply", "benchmark", "energy")
    assert all(not any(marker in feature for marker in forbidden) for feature in CANDIDATE_FEATURES)
