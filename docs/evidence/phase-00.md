# Phase 00 Evidence

Commit: not committed

Hermes version/commit: `801a9022a742562a3c4578c0d8dd12cfd393fc47`

Environment and dependency locks:

- BrandPilot host Python: 3.13
- Hermes managed Python: 3.14 required
- Hermes dependency graph: upstream `uv.lock` and `pm/lock.json` at the pinned commit
- BrandPilot Phase 0 third-party Python runtime dependencies: none

Implemented behaviors:

- Offline-by-default provider and cost admission.
- Private loopback-only Hermes client contract.
- Typed integration outcomes.
- Deterministic BrandPilot probe plugin.
- Reproducible environment and phase-gate scripts.

Commands executed:

- `uv lock`
- `npm install --package-lock-only --ignore-scripts`
- `docker compose -f infra/postgres/compose.yaml config`
- `python -m unittest discover -s tests -t . -v`
- `python scripts/phase_gate.py --phase 0 --offline --include-hermes`

Results:

- Combined gate: passed in approximately 133 seconds.
- Unit contracts: 16 passed.
- Hermes plugin: discovered and invoked through the real pinned core.
- Profile isolation: Workspace A 0 -> 6 -> 12 messages across restart; Workspace B
  retained its own 6 messages; marker cross-checks found no leakage.
- API authentication: missing key 401, wrong key 401, correct key 200; bind host
  `127.0.0.1`.
- API run: completed with `tool.started`, `tool.completed`, and `run.completed`
  events; fixture usage was 300 input, 40 output, 340 total tokens.
- PostgreSQL configuration: parsed successfully with a loopback-only published port.
- Lockfiles: BrandPilot `uv.lock` and `package-lock.json`, plus Hermes upstream
  `uv.lock` and `pm/lock.json`, were present and validated.

Live API calls made and their purpose: none.

Data mode and cost mode: `offline_test`, zero external model spending.

External approval/credential blockers:

- No Gemini key or verified free-tier project.
- OpenAI paid mode is intentionally disabled.

Gate decision: passed. Live-provider verification remains independently blocked by
credentials/cost policy and does not invalidate the explicit offline Phase 0 gate.

Next step: Phase 1 durable application foundation.
