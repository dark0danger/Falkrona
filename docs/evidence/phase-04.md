# Phase 04 Evidence

Commit: not committed

Mode: `offline_test`

## Implemented behavior

- Added durable workspace-scoped agent runs, model budget reservations, usage ledger
  entries, and reviewed tool-call audit records protected by PostgreSQL RLS.
- Added provider selection, explicit model configuration, pre-transport
  classification/redaction, Gemini private-data rejection, and fail-closed image
  admission.
- Added signed run credentials for exactly two Falkrona Hermes tools: confirmed brand
  context reads and plain-text artifact storage.
- Added `/v1/runs/{id}/stop` support to the Hermes client and a real gateway proof
  using the pinned Hermes runtime on `127.0.0.1:8642`.

## Commands and results

- `uv run python scripts/phase_gate.py --phase 4 --offline`: passed.
- 62 backend tests passed, including 6 real PostgreSQL checks.
- 2 web tests passed and the production Vite build passed.
- Dependency inventory: 45 Python packages, 138 Node packages, and 0 undeclared
  licenses.
- The real Hermes gateway accepted one `/v1/runs` request, reached `completed`, made
  4 fixture-provider turns, invoked `falkrona_get_brand_context` and
  `falkrona_store_artifact`, and persisted one Falkrona artifact through the signed
  app-tool endpoint. No external provider call occurred.

## Safety and recovery evidence

- Forged workspace scope, private Gemini payloads, image calls without explicit
  enablement, exhausted reservations, and malformed plugin arguments failed closed.
- The gateway proof starts and stops the pinned loopback service cleanly. The
  application retains its durable records and artifact if a later live provider is
  disabled or unavailable.

Gate decision: passed. The selected live provider remains unverified because no key
or paid opt-in was supplied; Phase 5 has not started.
