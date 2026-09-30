from __future__ import annotations

from math import ceil

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from .pipeline import FEATURES


ALPHAS = (0.01, 0.1, 1.0, 10.0, 100.0)
BOOTSTRAP_SEED = 20260930


def metric_values(actual: np.ndarray, predicted: np.ndarray, close_t: np.ndarray) -> dict[str, float]:
    errors = actual - predicted
    signs_equal = np.sign(actual) == np.sign(predicted)
    return {
        "mae_log_return": float(np.mean(np.abs(errors))), "rmse_log_return": float(np.sqrt(np.mean(errors**2))),
        "mae_price": float(np.mean(np.abs(close_t * np.exp(actual) - close_t * np.exp(predicted)))),
        "directional_accuracy": float(np.mean(signs_equal)), "actual_zero_share": float(np.mean(actual == 0)),
        "prediction_zero_share": float(np.mean(predicted == 0)),
    }


def make_pipeline(alpha: float) -> Pipeline:
    return Pipeline([("scaler", StandardScaler()), ("ridge", Ridge(alpha=alpha))])


def select_alpha(samples: pd.DataFrame) -> tuple[float, pd.DataFrame, Pipeline]:
    train = samples[samples.split == "train"]
    validation = samples[samples.split == "validation"]
    x_train, y_train = train[list(FEATURES)], train.target_log_return.to_numpy()
    x_valid, y_valid = validation[list(FEATURES)], validation.target_log_return.to_numpy()
    records = []
    models: dict[float, Pipeline] = {}
    for alpha in ALPHAS:
        model = make_pipeline(alpha)
        model.fit(x_train, y_train)
        values = metric_values(y_valid, model.predict(x_valid), validation.close_t.to_numpy())
        records.append({"alpha": alpha, **values})
        models[alpha] = model
    validation_table = pd.DataFrame(records).sort_values(["mae_log_return", "alpha"], kind="stable").reset_index(drop=True)
    selected = float(validation_table.iloc[0].alpha)
    return selected, validation_table, models[selected]


def final_model(samples: pd.DataFrame, alpha: float) -> Pipeline:
    fit_rows = samples[samples.split.isin(["train", "validation"])]
    model = make_pipeline(alpha)
    model.fit(fit_rows[list(FEATURES)], fit_rows.target_log_return)
    return model


def metrics_table(samples: pd.DataFrame, selected_train_model: Pipeline, final: Pipeline) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, object]] = []
    for stage, subset, ridge_model in (
        ("selection_train", samples[samples.split == "train"], selected_train_model),
        ("selection_validation", samples[samples.split == "validation"], selected_train_model),
        ("final_test", samples[samples.split == "test"], final),
    ):
        actual, close = subset.target_log_return.to_numpy(), subset.close_t.to_numpy()
        for model_name, predicted in (("no_change", np.zeros(len(subset))), ("ridge", ridge_model.predict(subset[list(FEATURES)]))):
            rows.append({"stage": stage, "period": "all", "model": model_name, "samples": len(subset), **metric_values(actual, predicted, close)})
    test = samples[samples.split == "test"].copy()
    test["ridge_prediction"] = final.predict(test[list(FEATURES)])
    test["baseline_prediction"] = 0.0
    test["predicted_next_close_ridge"] = test.close_t * np.exp(test.ridge_prediction)
    test["predicted_next_close_baseline"] = test.close_t
    test["loss_delta"] = np.abs(test.target_log_return - test.ridge_prediction) - np.abs(test.target_log_return)
    for year, subset in test.groupby(pd.to_datetime(test.feature_date).dt.year):
        actual, close = subset.target_log_return.to_numpy(), subset.close_t.to_numpy()
        for model_name, predicted in (("no_change", subset.baseline_prediction.to_numpy()), ("ridge", subset.ridge_prediction.to_numpy())):
            rows.append({"stage": "final_test", "period": str(year), "model": model_name, "samples": len(subset), **metric_values(actual, predicted, close)})
    result = pd.DataFrame(rows)
    result["mae_skill_vs_no_change"] = np.nan
    for (stage, period), group in result.groupby(["stage", "period"], sort=False):
        baseline = group[group.model == "no_change"]
        ridge = group[group.model == "ridge"]
        if baseline.empty or ridge.empty:
            continue
        baseline_mae = float(baseline.iloc[0].mae_log_return)
        skill = np.nan if baseline_mae == 0 else 1 - float(ridge.iloc[0].mae_log_return) / baseline_mae
        result.loc[(result.stage == stage) & (result.period == period) & (result.model == "ridge"), "mae_skill_vs_no_change"] = skill
    return result, test


def moving_block_bootstrap(loss_delta: np.ndarray, *, block_length: int = 20, repetitions: int = 2000, seed: int = BOOTSTRAP_SEED) -> dict[str, object]:
    if len(loss_delta) < block_length:
        raise ValueError("test sample is shorter than the fixed bootstrap block")
    rng = np.random.default_rng(seed)
    n = len(loss_delta)
    draws = np.empty(repetitions)
    blocks_per_draw = ceil(n / block_length)
    for i in range(repetitions):
        starts = rng.integers(0, n - block_length + 1, size=blocks_per_draw)
        indexes = np.concatenate([np.arange(start, start + block_length) for start in starts])[:n]
        draws[i] = float(loss_delta[indexes].mean())
    return {
        "method": "paired_moving_block_bootstrap", "block_length": block_length, "repetitions": repetitions, "seed": seed,
        "test_samples": n, "mean_loss_delta": float(loss_delta.mean()),
        "ci_95_low": float(np.quantile(draws, 0.025)), "ci_95_high": float(np.quantile(draws, 0.975)),
        "bootstrap_share_loss_delta_below_zero": float(np.mean(draws < 0)),
        "interpretation": "negative values favour Ridge; diagnostic only, not a guarantee of future advantage",
    }
