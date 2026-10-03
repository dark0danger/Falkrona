# Phase 02 Evidence

Commit: not committed

Mode: `offline_test`

## Implemented behavior

- Protected local owner bootstrap, Argon2id passwords, opaque server-side sessions,
  secure cookies, CSRF checks, expiry, revocation, and login throttling.
- Workspace memberships with owner/editor/analyst permissions and immediate
  revocation checks.
- Browser owner setup/sign-in, session restoration, workspace list, and sign-out.
- Workspace-scoped job APIs and SSE status, short-lived signed downloads, encrypted
  credential records, audit rows, and two similar but isolated business fixtures.
- Non-owner PostgreSQL application role, transaction-local workspace context, RLS on
  workspace-owned tables, and compound workspace/job integrity.
- Signed run credentials binding plugin requests to workspace, job, operation, expiry,
  nonce, and revision.

## Commands and results

- `uv lock` and `uv sync --group dev`: passed; security dependencies locked.
- `docker compose -f infra/postgres/compose.yaml up -d --wait postgres`: healthy.
- `.venv\Scripts\python.exe scripts/phase_gate.py --phase 2 --offline`: passed.
- Backend: 44 tests passed, including 5 against real PostgreSQL.
- Web: 2 Vitest tests passed; production TypeScript/Vite build passed.
- Desktop and 390x844 browser views were inspected without overlap or overflow.
- Inventory: 36 Python and 138 Node packages; 0 licenses missing declarations.

## Adversarial evidence

- Anonymous API, job, SSE, and file requests were denied.
- Cross-workspace route IDs, job IDs, asset IDs, and request workspace fields could
  not read or mutate the other fixture business.
- The actual `brandpilot_app` PostgreSQL role saw only the active workspace across a
  reused one-connection pool and rejected a mismatched insert.
- Analysts could read but could not write, approve, or publish; revocation took effect
  while the existing session was still active.
- Missing CSRF, expired/revoked sessions, repeated login failures, altered run tokens,
  and forged plugin workspace identities failed closed.
- Credential plaintext appeared in neither stored ciphertext nor API responses.
- The live Phase 2 API reported ready database/storage components, exposed the new
  session/setup routes, and returned 401 for anonymous `/api/v1/me`.

Gate decision: passed. Zero cross-workspace reads/writes were observed in the tested
matrix, and no credential or session secrets were returned by protected APIs.

Next step: Phase 3 assets, imports, and adaptive onboarding.
