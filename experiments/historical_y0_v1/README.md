# HISTORICAL Y0 BASELINE V1

Это локальный freeze завершённого retrospective EOD baseline для опубликованного дневного continuous-ряда Sina/AKShare `Y0`. Он не относится к production-пайплайну, не использует БД, collectors, weather, frozen smoke-test и не доказывает прогнозирование JO_165951, spot/farm-gate цены или торговой доходности.

Методика была зафиксирована до оценки в [EXPERIMENT_PLAN.md](EXPERIMENT_PLAN.md) и в freeze не переписывается. Итоговые пояснения находятся в [REPORT_CLARIFICATIONS.md](REPORT_CLARIFICATIONS.md), компактная сводка — в [BASELINE_SUMMARY.md](BASELINE_SUMMARY.md), а проверка существующих двух прогонов — в [REPRODUCIBILITY_VERIFICATION.json](REPRODUCIBILITY_VERIFICATION.json).

## Проверенный snapshot

- source/instrument: Sina via AKShare / `Y0`;
- raw SHA-256: `47f1f8519b87ad8d002a5f5771f4bccd821b16990e494953fb9a6fec5208dd78`;
- normalized SHA-256: `207b81576fa3db273cb8bb3e9a06ce91c95c0cc6481ce880661491ddaffe97b5`;
- финальный локальный run: `/home/dmitriy/Projects/parser_dataset/historical_research/experiments/historical_y0_v1/20260930T125500Z_final/`.

Исходные котировки, модели, predictions и результаты остаются вне Git. `.gitignore` специально исключает их из commit.

## Окружение и команды

Проверенное окружение: Python 3.14.4, NumPy 2.5.3, pandas 3.0.6, scikit-learn 1.8.0 и joblib 1.6.0. Создавайте его вне репозитория и устанавливайте только зависимости эксперимента:

```bash
python3 -m venv /tmp/historical-y0-v1-venv
/tmp/historical-y0-v1-venv/bin/pip install -r experiments/historical_y0_v1/requirements.txt
```

Воспроизводимый запуск в новую пустую внешнюю run-директорию:

```bash
EXP=experiments/historical_y0_v1
DATA=/home/dmitriy/Projects/parser_dataset/historical_research
OUT=$DATA/experiments/historical_y0_v1/new_unique_run
PYTHONPATH=$EXP/src /tmp/historical-y0-v1-venv/bin/python -m historical_y0_v1.run \
  --source-path $DATA/normalized/akshare_sina/soybean_oil_Y0_full_quality_checked_47f1f8519b87.csv \
  --manifest-path $DATA/reports/DOWNLOAD_MANIFEST.csv \
  --output-dir $OUT
```

Отдельная проверка изолированных experiment tests:

```bash
PYTHONPATH=experiments/historical_y0_v1/src /tmp/historical-y0-v1-venv/bin/python -m pytest -q experiments/historical_y0_v1/tests
```

CLI отказывается писать в непустую run-директорию. Не используйте 2026-данные как samples/targets и не подменяйте `close` полем `settlement`.

## Ограничения

Цель — `log(close_next_published_session / close_t)`, то есть следующий опубликованный дневной бар. Локально не подтверждены независимый полный календарь DCE и методика roll/adjustment continuous series; их статус остаётся `UNKNOWN`. Поэтому вывод относится только к опубликованному ряду и не является point-in-time или торговым доказательством.
