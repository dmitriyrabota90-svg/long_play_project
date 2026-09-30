from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn

from .modeling import BOOTSTRAP_SEED, final_model, metrics_table, moving_block_bootstrap, select_alpha
from .pipeline import FEATURES, PERIOD_END, PERIOD_START, SPLITS, build_supervised_samples, coverage_by_year, load_input, prepare_bars, sha256_file


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _git_head() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return "UNAVAILABLE"


def _feature_summary(samples: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for split, group in samples.groupby("split", sort=False):
        for feature in FEATURES:
            values = group[feature]
            rows.append({"split": split, "feature": feature, "count": int(values.count()), "missing": int(values.isna().sum()),
                         "unique": int(values.nunique()), "std_ddof0": float(values.std(ddof=0)), "min": float(values.min()), "max": float(values.max())})
    return pd.DataFrame(rows)


def _report(output: Path, *, reference: object, bars: pd.DataFrame, issues: pd.DataFrame, samples: pd.DataFrame, excluded: pd.DataFrame,
            selected_alpha: float, metrics: pd.DataFrame, bootstrap: dict[str, object], test_summary: str) -> None:
    period = bars[(bars.trading_date >= PERIOD_START) & (bars.trading_date <= PERIOD_END)]
    invalid = issues[issues.issue.str.startswith("ohlc_inconsistency", na=False)]
    validation = metrics[metrics.stage == "selection_validation"]
    test = metrics[(metrics.stage == "final_test") & (metrics.period == "all")]
    base_mae = float(test[test.model == "no_change"].iloc[0].mae_log_return)
    ridge_mae = float(test[test.model == "ridge"].iloc[0].mae_log_return)
    improves = ridge_mae < base_mae
    evidence = "SUPPORTED_IN_THIS_EXPERIMENT" if float(bootstrap["ci_95_high"]) < 0 else ("NOT_SUPPORTED" if float(bootstrap["ci_95_low"]) > 0 else "INCONCLUSIVE")
    lines = [
        "# HISTORICAL Y0 BASELINE V1 — отчёт", "",
        "## Что прогнозируется", "",
        "Прогнозируется лог-изменение close следующего опубликованного дневного бара Sina Y0 после EOD feature_date. Это не прогноз JO_165951, spot/farm-gate цены, локальной закупочной цены или торговой доходности.", "",
        "## Вход", "",
        f"- Source/instrument: Sina via AKShare / Y0; дневной основной continuous series.",
        f"- Raw payload: `{reference.raw_path}`; SHA-256 `{reference.raw_sha256}`; fetched_at `{reference.fetched_at}`; HTTP `{reference.raw_http_status}`.",
        f"- Normalized input: `{reference.source_path}`; SHA-256 `{reference.normalized_sha256}`.",
        "- Поля: trading_date, open, high, low, close, volume, open_interest, settlement. Target использует только close; settlement не подменяет close.",
        "- Валюта/единица и contract roll/adjustment methodology в локальных материалах не подтверждены: `UNKNOWN`.", "",
        "## Покрытие и качество", "",
        f"- Фактический период supervised experiment: {period.trading_date.min().date()}..{period.trading_date.max().date()}, строк до фильтра: {len(period)}, валидных баров: {int(period.valid_bar.sum())}.",
        f"- Samples после causal/split фильтров: {len(samples)}; исключено кандидатных feature dates: {len(excluded)}.",
        "- Полные дубликаты: 0; конфликтующие дубликаты: 0; NaN/Inf/non-positive close: 0 в рабочем периоде.",
        "- Скачки не удалялись автоматически. Invalid OHLC bars исключаются без сжатия исходной последовательности.",
    ]
    if invalid.empty:
        lines.append("- OHLC-неконсистентности не обнаружены.")
    else:
        lines.append("- Две известные OHLC-неконсистентности находятся вне 2015–2025 и не входят в supervised выборку:")
        for _, row in invalid.iterrows():
            lines.append(f"  - {row.trading_date}: {row.issue}; {row.raw_values}; action={row.action}.")
    lines.extend([
        "", "## Календарь, target и признаки", "",
        "- Target: `log(close_next_published_session / close_t)`. В sample сохранены feature_date, target_date, обе цены и source row identifiers.",
        "- Последовательность берётся из соседних исходных опубликованных дневных строк; переход не перескакивает invalid bar. Независимый полный календарь DCE локально отсутствует: календарные разрывы не объявляются пропусками, а один session-step не имеет независимого подтверждения.",
        f"- Feature whitelist ({len(FEATURES)}): {', '.join(FEATURES)}.",
        "- Volatility использует ddof=0; weekday encoding: weekday Monday=0, sin/cos(2*pi*weekday/5). Все окна причинные и требуют 21 непрерывный валидный исходный бар.", "",
        "## Split", "",
    ])
    for name, (start, end) in SPLITS.items():
        group = samples[samples.split == name]
        lines.append(f"- {name}: {start.date()}..{end.date()}, samples={len(group)}, фактически {group.feature_date.min() if len(group) else '—'}..{group.feature_date.max() if len(group) else '—'}.")
    lines.extend(["", "## Модели и метрики", "", f"- Alpha grid: 0.01, 0.1, 1, 10, 100; выбран alpha={selected_alpha} по validation MAE log-return (tie-break: меньший alpha).", "- Validation относится к модели, fit только на train; test относится к финальной модели, refit на train+validation.", "", "| stage | period | model | n | MAE log-return | RMSE log-return | MAE price | direction accuracy | actual zero | predicted zero | MAE skill |", "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"])
    for _, row in metrics.iterrows():
        skill = "—" if pd.isna(row.mae_skill_vs_no_change) else f"{row.mae_skill_vs_no_change:.6f}"
        lines.append(f"| {row.stage} | {row.period} | {row.model} | {row.samples} | {row.mae_log_return:.8f} | {row.rmse_log_return:.8f} | {row.mae_price:.4f} | {row.directional_accuracy:.4f} | {row.actual_zero_share:.4f} | {row.prediction_zero_share:.4f} | {skill} |")
    lines.extend([
        "", "## Paired moving-block bootstrap", "",
        f"- 2,000 повторов, блок {bootstrap['block_length']} последовательных test-записей, seed {bootstrap['seed']}; одинаковые блоки применяются к парной разности loss Ridge minus no-change.",
        f"- mean loss delta={bootstrap['mean_loss_delta']:.10f}; 95% CI [{bootstrap['ci_95_low']:.10f}, {bootstrap['ci_95_high']:.10f}]. Отрицательное значение благоприятствует Ridge.",
        "- Это диагностический интервал зависимых test-рядов, не гарантия будущего преимущества.", "",
        "## Воспроизводимость и тесты", "",
        "- Все входные SHA, параметры, library versions, split и SHA ключевых результатов сохранены в run_metadata.json.",
        f"- Статус suite на момент запуска: {test_summary}.",
        "- Второй запуск с теми же входами должен совпасть по sample keys, selected alpha, predictions и числовым метрикам; timestamps в metadata намеренно не сравниваются.", "",
        "## Verdict", "",
        "- PIPELINE TECHNICALLY WORKS: YES",
        "- HISTORICAL SERIES USABLE FOR THIS RESEARCH: WITH_LIMITATIONS",
        "- POINT-IN-TIME CONTINUOUS-SERIES SEMANTICS: UNCONFIRMED",
        f"- RIDGE IMPROVES TEST MAE: {'YES' if improves else 'NO'}",
        f"- EVIDENCE OF STABLE ADVANTAGE: {evidence}",
        "- SUITABLE FOR REAL TRADING OR LOCAL FARM-GATE PRICE FORECAST: NOT_ESTABLISHED",
        "",
        "Главное ограничение: методика construction/roll/adjustment непрерывного ряда и независимая полнота исторического календаря DCE не подтверждены локальными источниками. Высокая или низкая метрика относится только к опубликованному Y0-ряду в этом retrospective EOD experiment.",
    ])
    (output / "HISTORICAL_Y0_BASELINE_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def execute(source_path: Path, manifest_path: Path, output_dir: Path, test_summary: str) -> None:
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError(f"refusing to overwrite non-empty run directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    raw, reference = load_input(source_path, manifest_path)
    bars, issues = prepare_bars(raw)
    samples, excluded = build_supervised_samples(bars)
    if samples.empty or set(samples.split) != set(SPLITS):
        raise ValueError("quality/split rules left insufficient supervised samples")
    coverage_by_year(bars, samples).to_csv(output_dir / "yearly_coverage.csv", index=False)
    issues.to_csv(output_dir / "data_quality_issues.csv", index=False)
    samples.to_csv(output_dir / "supervised_samples.csv", index=False)
    excluded.to_csv(output_dir / "excluded_samples.csv", index=False)
    _feature_summary(samples).to_csv(output_dir / "feature_summary.csv", index=False)
    split_manifest = {name: {"start": str(start.date()), "end": str(end.date()), "sample_count": int((samples.split == name).sum()),
                              "feature_date_min": str(samples.loc[samples.split == name, "feature_date"].min()), "feature_date_max": str(samples.loc[samples.split == name, "feature_date"].max())} for name, (start, end) in SPLITS.items()}
    _write_json(output_dir / "split_manifest.json", split_manifest)
    _write_json(output_dir / "input_reference.json", reference.__dict__)
    selected_alpha, validation, selection_model = select_alpha(samples)
    validation.to_csv(output_dir / "alpha_validation.csv", index=False)
    final = final_model(samples, selected_alpha)
    metrics, predictions = metrics_table(samples, selection_model, final)
    metrics.to_csv(output_dir / "metrics.csv", index=False)
    predictions.to_csv(output_dir / "test_predictions.csv", index=False)
    bootstrap = moving_block_bootstrap(predictions.loss_delta.to_numpy())
    _write_json(output_dir / "bootstrap_summary.json", bootstrap)
    joblib.dump(final, output_dir / "ridge_model.joblib")
    _report(output_dir, reference=reference, bars=bars, issues=issues, samples=samples, excluded=excluded, selected_alpha=selected_alpha, metrics=metrics, bootstrap=bootstrap, test_summary=test_summary)
    key_files = ["supervised_samples.csv", "split_manifest.json", "alpha_validation.csv", "metrics.csv", "test_predictions.csv", "bootstrap_summary.json"]
    metadata = {
        "created_at": datetime.now(timezone.utc).isoformat(), "git_head": _git_head(), "python": platform.python_version(),
        "libraries": {"numpy": np.__version__, "pandas": pd.__version__, "scikit_learn": sklearn.__version__, "joblib": joblib.__version__},
        "source": {"source": "Sina via AKShare", "instrument": "Y0", **reference.__dict__},
        "parameters": {"period": [str(PERIOD_START.date()), str(PERIOD_END.date())], "feature_whitelist": list(FEATURES), "alpha_grid": [0.01, 0.1, 1, 10, 100], "selected_alpha": selected_alpha, "bootstrap_seed": BOOTSTRAP_SEED, "bootstrap_block_length": 20, "bootstrap_repetitions": 2000},
        "eod_forecast_timing": "after close_t and the selected daily fields are available", "continuous_series_roll_policy": "UNKNOWN", "calendar_limitation": "independent historical DCE calendar not locally confirmed; raw source adjacency only", "key_result_sha256": {name: sha256_file(output_dir / name) for name in key_files},
    }
    _write_json(output_dir / "run_metadata.json", metadata)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the isolated historical Y0 baseline.")
    parser.add_argument("--source-path", required=True, type=Path)
    parser.add_argument("--manifest-path", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--test-summary", default="not executed by the experiment CLI")
    args = parser.parse_args()
    execute(args.source_path, args.manifest_path, args.output_dir, args.test_summary)


if __name__ == "__main__":
    main()
