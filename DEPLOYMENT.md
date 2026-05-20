# Deployment Guide

This project is deployed as an independent Docker Compose application. It is not a Telegram bot and does not depend on Telegram code or databases.

## Current Server Layout

Production path:

```text
/data1/long_play_project
```

Important project directories:

```text
/data1/long_play_project/data/raw
/data1/long_play_project/data/exports
/data1/long_play_project/logs
```

PostgreSQL data is stored in the Docker named volume:

```text
long_play_project_postgres_data
```

Do not delete `data/raw`, `data/exports`, `logs`, or the PostgreSQL volume during routine updates.

## Daily Commands

```bash
cd /data1/long_play_project
docker compose ps
docker compose logs app --tail=200
docker compose run --rm app python scripts/health_report.py
docker compose run --rm app python scripts/operational_report.py
docker compose run --rm app python scripts/backup.py --dry-run
```

## Updating Code

```bash
cd /data1/long_play_project
git pull
docker compose build app
docker compose up -d app
docker compose ps
docker compose logs app --tail=100
docker compose run --rm app python scripts/health_report.py
docker compose run --rm app python scripts/operational_report.py
```

Only the app container needs rebuilding for Python code changes. Do not recreate or remove the PostgreSQL volume unless there is an explicit database maintenance plan.

## Checking The Collector

Manual run:

```bash
docker compose run --rm app python scripts/run_collector.py current_price_source
docker compose run --rm app python scripts/operational_report.py
```

Expected healthy result:

```text
status=success
records_found=3
records_written=3
errors_count=0
```

Raw files should appear under:

```text
data/raw/current_price_source/{yyyy}/{mm}/{dd}/{collector_run_id}/
```

## Checking The Production Scheduler

Production `.env` should use:

```env
CURRENT_PRICE_SCHEDULER_ENABLED=true
CURRENT_PRICE_SCHEDULE_TIMES=09:00,18:00
CURRENT_PRICE_TEST_INTERVAL_SECONDS=
```

Check scheduler registration:

```bash
docker compose logs app --tail=200
```

The logs should show `current_price_source_0900` and `current_price_source_1800`. The test interval job should not be present in normal production mode.

## Test Scheduler Mode

Use only for a short verification window:

```env
CURRENT_PRICE_TEST_INTERVAL_SECONDS=300
```

After testing, set it back to an empty value and recreate the app container:

```bash
docker compose up -d app
```

## Backup Dry Run

```bash
docker compose run --rm app python scripts/backup.py --dry-run
```

The script prints the planned `pg_dump`, raw-data backup, exports backup, and verification steps. It does not delete or overwrite source data.

## Directory Ownership

The app container runs as non-root `appuser` by default. The image build args default to UID/GID `1000`, matching the `dmitriy` user on the current server:

```env
APP_UID=1000
APP_GID=1000
```

If bind-mounted paths are not writable, fix only project-owned directories:

```bash
chown -R dmitriy:dmitriy /data1/long_play_project/logs
chown -R dmitriy:dmitriy /data1/long_play_project/data
```

Do not change ownership of `/data1` itself and do not touch other projects.

## PostgreSQL Password Rotation

For an existing PostgreSQL Docker volume, do not change only `.env`. The safe sequence is:

1. Generate a strong password outside git.
2. Apply it inside PostgreSQL with `ALTER USER collector WITH PASSWORD '<new-password>';`.
3. Update `DATABASE_URL` in `/data1/long_play_project/.env`.
4. Recreate only the app container.
5. Run `health_report.py` and `operational_report.py`.

Do not print the new password in command logs or reports. Do not commit `.env`.

## Do Not Touch During Routine Deploys

- Existing nginx configuration.
- Existing PM2 applications.
- SSL certificates.
- Firewall rules.
- Other systemd services.
- Other directories under `/data1`, `/data2`, `/opt`, or `/home`.
- `data/raw` source data.
- PostgreSQL Docker volume.
