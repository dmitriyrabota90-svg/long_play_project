from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


FEATURES = (
    "ret_1", "ret_3", "ret_5", "ret_10", "ret_20", "volatility_5",
    "volatility_20", "distance_sma20", "weekday_sin", "weekday_cos",
)
SPLITS = {
    "train": (pd.Timestamp("2015-01-01"), pd.Timestamp("2021-12-31")),
    "validation": (pd.Timestamp("2022-01-01"), pd.Timestamp("2023-12-31")),
    "test": (pd.Timestamp("2024-01-01"), pd.Timestamp("2025-12-31")),
}
PERIOD_START = pd.Timestamp("2015-01-01")
PERIOD_END = pd.Timestamp("2025-12-31")


@dataclass(frozen=True)
class InputReference:
    source_path: str
    normalized_sha256: str
    raw_path: str
    raw_sha256: str
    fetched_at: str
    source_url: str
    raw_http_status: str


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_input(source_path: Path, manifest_path: Path) -> tuple[pd.DataFrame, InputReference]:
    rows = list(csv.DictReader(manifest_path.open(encoding="utf-8")))
    candidates = [r for r in rows if r["download_name"] == "Y0" and r["source"] == "Sina via AKShare"]
    if len(candidates) != 1:
        raise ValueError("manifest must contain exactly one Sina via AKShare Y0 record")
    manifest = candidates[0]
    raw_path = Path(manifest["raw_path"])
    if not raw_path.is_file() or sha256_file(raw_path) != manifest["sha256"]:
        raise ValueError("stored raw Y0 payload is missing or its SHA-256 disagrees with manifest")
    frame = pd.read_csv(source_path)
    required = {"trading_date", "open", "high", "low", "close", "volume", "open_interest", "settlement", "source", "instrument"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"source CSV missing required columns: {sorted(missing)}")
    if set(frame["source"].dropna().unique()) != {"akshare_sina"} or set(frame["instrument"].dropna().unique()) != {"Y0"}:
        raise ValueError("source CSV is not exclusively the normalized AKShare Sina Y0 series")
    return frame, InputReference(
        source_path=str(source_path), normalized_sha256=sha256_file(source_path), raw_path=str(raw_path),
        raw_sha256=manifest["sha256"], fetched_at=manifest["fetched_at"], source_url=manifest["url"],
        raw_http_status=manifest["http_status"],
    )


def prepare_bars(raw: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    frame = raw.copy().reset_index(names="source_row_id")
    issues: list[dict[str, object]] = []
    frame["trading_date"] = pd.to_datetime(frame["trading_date"], errors="coerce")
    for column in ("open", "high", "low", "close", "volume", "open_interest", "settlement"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    for index, row in frame[frame["trading_date"].isna()].iterrows():
        issues.append(_issue(row, "invalid_trading_date", "excluded_as_invalid_bar", ""))
    frame = frame.sort_values(["trading_date", "source_row_id"], kind="stable").reset_index(drop=True)
    duplicate_dates = frame[frame.duplicated("trading_date", keep=False)]
    if not duplicate_dates.empty:
        for date, group in duplicate_dates.groupby("trading_date", dropna=False):
            comparable = group.drop(columns=["source_row_id"]).nunique(dropna=False).max() == 1
            action = "collapsed_exact_duplicate" if comparable else "blocked_conflicting_duplicate"
            for _, row in group.iterrows():
                issues.append(_issue(row, "duplicate_natural_key", action, str(date.date()) if pd.notna(date) else ""))
        if any(item["action"] == "blocked_conflicting_duplicate" for item in issues):
            raise ValueError("conflicting duplicate trading dates cannot be resolved deterministically")
        frame = frame.drop_duplicates("trading_date", keep="first").reset_index(drop=True)
    invalid_numeric = ~np.isfinite(frame[["open", "high", "low", "close"]]).all(axis=1) | (frame["close"] <= 0)
    ohlc_invalid = (frame["high"] < frame[["open", "low", "close"]].max(axis=1)) | (frame["low"] > frame[["open", "high", "close"]].min(axis=1))
    frame["valid_bar"] = ~(invalid_numeric | ohlc_invalid | frame["trading_date"].isna())
    for _, row in frame[invalid_numeric].iterrows():
        issues.append(_issue(row, "nonfinite_or_nonpositive_ohlc", "excluded_as_invalid_bar", ""))
    for _, row in frame[ohlc_invalid].iterrows():
        condition = "high_below_open_low_or_close" if row.high < max(row.open, row.low, row.close) else "low_above_open_high_or_close"
        issues.append(_issue(row, f"ohlc_inconsistency:{condition}", "excluded_as_invalid_bar", ""))
    finite_positive_close = frame["close"].where(frame["close"] > 0)
    suspicious_jumps = finite_positive_close.pct_change(fill_method=None).abs() > 0.20
    for _, row in frame[suspicious_jumps.fillna(False)].iterrows():
        issues.append(_issue(row, "suspicious_abs_close_jump_over_20pct", "retained_not_automatically_removed", ""))
    frame["sequence_position"] = np.arange(len(frame))
    issue_frame = pd.DataFrame(issues, columns=["source_row_id", "trading_date", "issue", "action", "affected_sample_dates", "raw_values"])
    return frame, issue_frame


def _issue(row: pd.Series, issue: str, action: str, affected: str) -> dict[str, object]:
    return {
        "source_row_id": int(row.source_row_id),
        "trading_date": "" if pd.isna(row.trading_date) else row.trading_date.date().isoformat(),
        "issue": issue, "action": action, "affected_sample_dates": affected,
        "raw_values": json.dumps({k: row[k] for k in ("open", "high", "low", "close", "volume", "open_interest", "settlement")}, default=str),
    }


def split_for_date(value: pd.Timestamp) -> str | None:
    for name, (start, end) in SPLITS.items():
        if start <= value <= end:
            return name
    return None


def build_supervised_samples(bars: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    samples: list[dict[str, object]] = []
    excluded: list[dict[str, object]] = []
    for i, current in bars.iterrows():
        feature_date = current.trading_date
        if pd.isna(feature_date) or not (PERIOD_START <= feature_date <= PERIOD_END):
            continue
        base = {"source_row_id": int(current.source_row_id), "feature_date": feature_date.date().isoformat()}
        if not bool(current.valid_bar):
            excluded.append(base | {"reason": "invalid_feature_bar", "target_date": ""})
            continue
        if i + 1 >= len(bars):
            excluded.append(base | {"reason": "no_next_published_bar", "target_date": ""})
            continue
        target = bars.iloc[i + 1]
        if not bool(target.valid_bar):
            excluded.append(base | {"reason": "next_bar_invalid_no_jump_allowed", "target_date": target.trading_date.date().isoformat()})
            continue
        if int(target.sequence_position) != int(current.sequence_position) + 1:
            excluded.append(base | {"reason": "nonconsecutive_source_sequence", "target_date": target.trading_date.date().isoformat()})
            continue
        if not (PERIOD_START <= target.trading_date <= PERIOD_END):
            excluded.append(base | {"reason": "target_outside_experiment_period", "target_date": target.trading_date.date().isoformat()})
            continue
        split = split_for_date(feature_date)
        if split is None or split != split_for_date(target.trading_date):
            excluded.append(base | {"reason": "target_crosses_split_boundary", "target_date": target.trading_date.date().isoformat()})
            continue
        window = bars.iloc[i - 20:i + 1]
        if len(window) != 21 or not window.valid_bar.all() or not np.all(np.diff(window.sequence_position) == 1):
            excluded.append(base | {"reason": "insufficient_or_interrupted_causal_window", "target_date": target.trading_date.date().isoformat()})
            continue
        closes = window.close.to_numpy(dtype=float)
        returns = np.log(closes[1:] / closes[:-1])
        weekday = int(feature_date.weekday())
        samples.append(base | {
            "target_date": target.trading_date.date().isoformat(), "target_source_row_id": int(target.source_row_id),
            "split": split, "close_t": float(current.close), "close_next_session": float(target.close),
            "target_log_return": float(np.log(target.close / current.close)),
            "session_transition_status": "adjacent_source_published_daily_bars_independent_calendar_unconfirmed",
            "ret_1": float(returns[-1]), "ret_3": float(np.log(closes[-1] / closes[-4])),
            "ret_5": float(np.log(closes[-1] / closes[-6])), "ret_10": float(np.log(closes[-1] / closes[-11])),
            "ret_20": float(np.log(closes[-1] / closes[0])), "volatility_5": float(np.std(returns[-5:], ddof=0)),
            "volatility_20": float(np.std(returns, ddof=0)), "distance_sma20": float(np.log(closes[-1] / closes[-20:].mean())),
            "weekday_sin": float(np.sin(2 * np.pi * weekday / 5)), "weekday_cos": float(np.cos(2 * np.pi * weekday / 5)),
        })
    return pd.DataFrame(samples), pd.DataFrame(excluded, columns=["source_row_id", "feature_date", "target_date", "reason"])


def coverage_by_year(bars: pd.DataFrame, samples: pd.DataFrame) -> pd.DataFrame:
    scoped = bars[(bars.trading_date >= PERIOD_START) & (bars.trading_date <= PERIOD_END)].copy()
    scoped["year"] = scoped.trading_date.dt.year
    coverage = scoped.groupby("year", as_index=False).agg(source_rows=("source_row_id", "size"), valid_bars=("valid_bar", "sum"))
    if not samples.empty:
        counts = samples.assign(year=pd.to_datetime(samples.feature_date).dt.year).groupby("year", as_index=False).size().rename(columns={"size": "supervised_samples"})
        coverage = coverage.merge(counts, on="year", how="left")
    if "supervised_samples" not in coverage:
        coverage["supervised_samples"] = 0
    coverage["supervised_samples"] = coverage["supervised_samples"].fillna(0).astype(int)
    return coverage
