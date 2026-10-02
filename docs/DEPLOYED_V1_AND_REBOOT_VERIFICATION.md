# Deployed engineering v1 — source and reboot verification

Status as of 2026-10-02 07:49 UTC: **source recorded; controlled reboot NOT_RUN**.
This document records observed pre-reboot facts, not proof of post-reboot recovery.

| Item | Verified value |
| --- | --- |
| Source commit | `85021a6a93df21f79905aca87e9ec161bc7c9fc9` |
| Remote branch | `origin/main`; source commit was verified as its tip immediately after normal fast-forward push |
| Annotated deployment tag | `cdb-v1-deployed-20261002`, points to source commit |
| Release | `cdb-v1-rc-20261001-01` |
| Production app image ID | `sha256:6ce0f13e0ac232c785fee09d7382e11008e348e58433e25f7a2c5facc0a682ed` |
| Production DB revision | `0021_price_source_time (head)` |
| Restart mechanism | Docker service enabled and active; Compose `restart: unless-stopped` for `app` and `postgres` |
| Dependency | `app` waits for PostgreSQL service health; PostgreSQL was `healthy` |
| Production Compose override | Candidate image pinned, `pull_policy: never`, no app build; existing data/log/DB mounts retained |

The release manifest's 139 runtime files matched both the development checkout
and the candidate image's `/app`. Release regression was **562 passed, 1 skipped**;
packaged acceptance passed. A local focused check of the recorded source was
**21 passed, 1 deselected**. The production rollout on 2026-10-02 succeeded.
The source commit includes only deployed runtime, related tests, and the
daily-slice provenance document. Existing unrelated experiments, diagnostics,
raw data, archives, and untracked files were not staged.

## Pre-reboot checks

- Host: `ubuntu-server`; boot time before this task's reboot test:
  `2026-09-16 06:14:21` (host `uptime -s`).
- At 2026-10-02 07:47 UTC, app and PostgreSQL were running; PostgreSQL was
  healthy. Both containers had restart policy `unless-stopped`, restart count
  zero. The app had the exact image ID above, and Alembic reported the expected
  revision. Docker service was `enabled` and `active`.
- No active database-writing session was observed. The verified backup
  `commodity_dataset_before_cdb_v1_rc_20261002_20261002T061750Z.dump` was
  present with SHA-256
  `373f49c579ce64b966001fff1e27f2c36975f3b1ef2ed94837d13c49f6448974`.
  Free space was approximately 365 GB on `/` and 5.2 TB on `/data1`.
- At the later read-only check, current-price health was `ok`: database and
  raw storage available, last successful current-price run ID 402, no stale
  products or problematic checks in the preceding 24 hours. The database held
  403 collector runs, 428 daily-product rows, four slice revisions and four
  confirmed readiness timestamps. Previously verified CSV and evidence export
  files remained present.
- One `python` process appeared in the one app container. Building a separate,
  non-running scheduler object from the production configuration enumerated
  six expected jobs: hourly health; daily quality 03:00; current price
  09:00/18:00; CBR FX 10:00; daily builder 19:30, all Europe/Moscow. At
  approximately 10:49 MSK, its computed next current-price run was 18:00 MSK
  and next daily builder run 19:30 MSK. This is configuration evidence, **not**
  direct introspection of the running scheduler's internal job registry.

## Reboot and recovery status

| Check | Result |
| --- | --- |
| Controlled reboot command/time | **NOT_RUN** |
| New OS boot time | **NOT_CHECKED** |
| Time to service recovery | **NOT_CHECKED** |
| PostgreSQL autostart / health | **NOT_CHECKED** |
| App autostart / exact image / mounts | **NOT_CHECKED** |
| Scheduler autostart / in-process jobs | **NOT_CHECKED** |
| Data, exports, backup persistence after reboot | **NOT_CHECKED** |
| AC_POWER_RECOVERY | **USER_CHECK_REQUIRED** |

The SSH user cannot execute `sudo -n` (`a password is required`), and
systemd-logind returned `challenge` for `CanReboot`; the controlled reboot was
therefore not sent. No password was requested or stored. An authorized operator
must perform the normal reboot, after which the above recovery checks must be
completed **before** any manual `docker compose up`. A normal reboot would not
prove BIOS/UEFI recovery after a physical power loss; that remains a separate
user check. No autostart configuration was changed.

Raw production logs and full process command lines were not inspected because
they may expose secrets. The aggregate operational summary may remain degraded
by older classified quality incidents even when current-price health is `ok`;
post-reboot checks must distinguish new incidents from those historical ones.
