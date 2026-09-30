# Offline ML smoke test v1

This directory freezes a small, local-only technical check of the commodity
dataset pipeline. It verifies snapshot loading, strict target construction,
chronological splitting, train-only preprocessing, a zero-return baseline and
Ridge regression. It is **not** a production forecasting model.

## Scope

Only price, FX and deterministic calendar fields are admitted. Weather, news,
trade, supply/demand, benchmarks and energy are explicitly excluded. No script
in this directory connects to production or changes the production application.

## Environment

The frozen run used Python 3.14.4, NumPy 2.5.3 and pytest 9.1.1. Use an
isolated local environment; do not install these experiment dependencies in
production or the system Python.

```bash
python3 -m venv /tmp/commodity-phase9-venv
/tmp/commodity-phase9-venv/bin/pip install -r experiments/smoke_test_v1/requirements.txt
```

## Tests

The experiment tests are outside the repository's configured `tests/`
collection path and must be run explicitly:

```bash
/tmp/commodity-phase9-venv/bin/python -m pytest -q experiments/smoke_test_v1/tests
```

Run the main project suite separately:

```bash
/tmp/commodity-phase9-venv/bin/python -m pytest -q
```

## Reproduce from a local snapshot

`data/dataset_snapshot.csv` is a production-derived local artifact and is
ignored by Git. It must already be present and match `SNAPSHOT_REFERENCE.json`.
Never overwrite it. Write a verification rerun to a new `/tmp` directory:

```bash
EXP=experiments/smoke_test_v1
OUT=/tmp/commodity-smoke-test-v1-rerun
mkdir -p "$OUT/data" "$OUT/reports"
cp "$EXP/data/dataset_snapshot.csv" "$OUT/data/dataset_snapshot.csv"

/tmp/commodity-phase9-venv/bin/python "$EXP/src/build_dataset.py" \
  --snapshot "$OUT/data/dataset_snapshot.csv" \
  --metadata "$OUT/data/dataset_snapshot_metadata.json" \
  --samples "$OUT/data/supervised_samples.csv" \
  --validation "$OUT/reports/data_validation.json" \
  --production-head 2284aeba2a4fef45a269f0e9116a046119fe33e8 \
  --extraction-timestamp 2026-09-30T09:09:46+00:00

/tmp/commodity-phase9-venv/bin/python "$EXP/src/train_smoke_test.py" \
  --samples "$OUT/data/supervised_samples.csv" \
  --metrics "$OUT/reports/metrics.csv" \
  --predictions "$OUT/reports/predictions.csv" \
  --feature-summary "$OUT/reports/feature_summary.csv" \
  --run-summary "$OUT/reports/run_summary.json"

/tmp/commodity-phase9-venv/bin/python "$EXP/src/generate_report.py" \
  --metadata "$OUT/data/dataset_snapshot_metadata.json" \
  --validation "$OUT/reports/data_validation.json" \
  --samples "$OUT/data/supervised_samples.csv" \
  --metrics "$OUT/reports/metrics.csv" \
  --run-summary "$OUT/reports/run_summary.json" \
  --output "$OUT/reports/SMOKE_TEST_REPORT.md"
```

The commands do not tune hyperparameters or change the frozen snapshot. They
are a reproducibility check only.

## Limitations

The snapshot contains 358 strict h=1 samples across four products, a major
historical price gap and no annual seasonal cycle. The final test period has
already been inspected; it is not an independent future evaluation set. See
`BASELINE_SUMMARY.md` for the verified findings.
