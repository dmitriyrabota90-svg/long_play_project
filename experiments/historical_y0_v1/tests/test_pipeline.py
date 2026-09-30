from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from historical_y0_v1.modeling import final_model, metric_values, metrics_table, moving_block_bootstrap, select_alpha
from historical_y0_v1.pipeline import FEATURES, build_supervised_samples, prepare_bars


def raw_bars(start: str, periods: int, *, freq: str = "B") -> pd.DataFrame:
    dates = pd.date_range(start, periods=periods, freq=freq)
    close = np.linspace(5000, 5000 + periods - 1, periods)
    return pd.DataFrame({"trading_date": dates, "open": close, "high": close + 2, "low": close - 2, "close": close,
                         "volume": 100, "open_interest": 200, "settlement": close, "source": "akshare_sina", "instrument": "Y0"})


def samples_from(raw: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    bars, issues = prepare_bars(raw)
    samples, excluded = build_supervised_samples(bars)
    return bars, samples, excluded


def test_next_published_session_can_cross_weekend_without_calling_it_missing() -> None:
    _, samples, _ = samples_from(raw_bars("2019-11-01", 70))
    friday = samples[samples.feature_date == "2020-01-03"].iloc[0]
    assert friday.target_date == "2020-01-06"


def test_invalid_bar_blocks_both_adjacent_target_transitions() -> None:
    raw = raw_bars("2020-01-01", 60)
    raw.loc[30, "high"] = raw.loc[30, "open"] - 1
    bars, samples, _ = samples_from(raw)
    invalid_id = int(bars.loc[30, "source_row_id"])
    assert invalid_id not in set(samples.source_row_id)
    assert invalid_id not in set(samples.target_source_row_id)


def test_target_never_crosses_split_boundary() -> None:
    _, samples, excluded = samples_from(raw_bars("2021-10-01", 100))
    assert not ((samples.feature_date <= "2021-12-31") & (samples.target_date >= "2022-01-01")).any()
    assert "target_crosses_split_boundary" in set(excluded.reason)


def test_last_2025_target_cannot_use_2026() -> None:
    raw = raw_bars("2025-10-01", 80)
    _, samples, excluded = samples_from(raw)
    assert not (samples.target_date > "2025-12-31").any()
    assert "target_outside_experiment_period" in set(excluded.reason)


def test_features_are_causal_when_future_price_changes() -> None:
    raw = raw_bars("2020-01-01", 100)
    _, before, _ = samples_from(raw)
    raw.loc[80:, ["open", "high", "low", "close", "settlement"]] *= 2
    _, after, _ = samples_from(raw)
    key = before.iloc[40].feature_date
    assert before[before.feature_date == key].iloc[0][list(FEATURES)].to_dict() == after[after.feature_date == key].iloc[0][list(FEATURES)].to_dict()


def test_interrupted_causal_window_is_excluded() -> None:
    raw = raw_bars("2020-01-01", 70)
    raw.loc[30, "low"] = raw.loc[30, "open"] + 1
    _, samples, excluded = samples_from(raw)
    assert not (samples.feature_date == "2020-02-13").any()
    assert "insufficient_or_interrupted_causal_window" in set(excluded.reason)


def test_scaler_is_fit_on_train_only_and_alpha_is_deterministic() -> None:
    raw = pd.concat([raw_bars("2015-01-01", 1800), raw_bars("2022-01-01", 600), raw_bars("2024-01-01", 600)]).drop_duplicates("trading_date").sort_values("trading_date").reset_index(drop=True)
    _, samples, _ = samples_from(raw)
    alpha_a, _, model_a = select_alpha(samples)
    alpha_b, _, _ = select_alpha(samples)
    train = samples[samples.split == "train"]
    assert alpha_a == alpha_b
    assert np.allclose(model_a.named_steps["scaler"].mean_, train[list(FEATURES)].mean().to_numpy())


def test_no_change_and_price_space_reconstruction() -> None:
    actual = np.array([0.1, -0.1])
    predicted = np.zeros(2)
    values = metric_values(actual, predicted, np.array([100.0, 100.0]))
    assert values["prediction_zero_share"] == 1.0
    assert values["mae_price"] == pytest.approx((abs(100 * np.exp(0.1) - 100) + abs(100 * np.exp(-0.1) - 100)) / 2)


def test_paired_moving_block_bootstrap_is_deterministic_and_uses_single_delta_series() -> None:
    delta = np.linspace(-0.1, 0.1, 60)
    first = moving_block_bootstrap(delta, repetitions=100, seed=7)
    second = moving_block_bootstrap(delta, repetitions=100, seed=7)
    assert first == second
    assert first["method"] == "paired_moving_block_bootstrap"


def test_final_model_uses_train_and_validation_only() -> None:
    raw = raw_bars("2015-01-01", 3000)
    _, samples, _ = samples_from(raw)
    alpha, _, _ = select_alpha(samples)
    model = final_model(samples, alpha)
    expected = samples[samples.split.isin(["train", "validation"])][list(FEATURES)].mean().to_numpy()
    assert np.allclose(model.named_steps["scaler"].mean_, expected)


def test_yearly_mae_skill_uses_that_years_no_change_baseline() -> None:
    raw = raw_bars("2015-01-01", 3000)
    _, samples, _ = samples_from(raw)
    alpha, _, selected = select_alpha(samples)
    metrics, _ = metrics_table(samples, selected, final_model(samples, alpha))
    annual = metrics[(metrics.stage == "final_test") & (metrics.period == "2024")]
    base = float(annual[annual.model == "no_change"].iloc[0].mae_log_return)
    ridge = float(annual[annual.model == "ridge"].iloc[0].mae_log_return)
    recorded = float(annual[annual.model == "ridge"].iloc[0].mae_skill_vs_no_change)
    assert recorded == pytest.approx(1 - ridge / base)
