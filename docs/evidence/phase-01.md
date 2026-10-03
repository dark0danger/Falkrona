# Phase 01 Evidence

Commit: not committed

Mode: `offline_test`

## Implemented behavior

- FastAPI, React/Vite, and restartable worker bootstraps.
- PostgreSQL jobs, steps, outbox, leases, checkpoints, heartbeats, bounded attempts,
  expired-lease recovery, and dedupe constraints.
- Two-step Alembic migration chain for clean install and prior-fixture upgrade.
- Private local storage, structured redacted logs, component health, strict config,
  deterministic fixtures, and generated dependency/license inventory.

## Commands and results

- `uv lock` and `uv sync --all-groups`: locked Python environment resolved.
- `npm install --ignore-scripts`: locked web environment installed.
- `npm audit --json`: zero vulnerabilities after upgrading Vitest to `5.0.2`.
- `docker compose -f infra/postgres/compose.yaml up -d --wait postgres`: service healthy.
- `.venv\Scripts\python.exe scripts/phase_gate.py --phase 1 --offline`: passed.
- Backend: 34 tests passed, including 3 against real PostgreSQL.
- Web: 2 Vitest tests passed; production Vite build passed.
- Inventory: 31 Python and 138 Node packages; 0 licenses not declared in metadata.

## Recovery evidence

- Two PostgreSQL workers produced one claim for one queued job.
- The same job was reclaimed after lease expiry with attempt count incremented.
- After simulated termination following an artifact checkpoint, a new engine/worker
  resumed and completed with exactly one `result.json` output.
- Duplicate job and outbox requests returned their existing IDs.
- Database/storage faults produced component-level degraded health.
- Missing/invalid startup settings raised named configuration errors.

## Offline and UI evidence

- Boot test allowed loopback only and observed no external startup request.
- Model and image calls remained disabled; live provider status is unchanged.
- Desktop and 390x844 mobile layouts were visually inspected with no overlap.
- The fixture disclosure `Sample data / Offline` remained visible at both sizes.

Gate decision: passed.

Next step: Phase 2 accounts, authorization, and workspace isolation.
