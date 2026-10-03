# Phase 06 Evidence

Mode: `offline_test` with an isolated local PostgreSQL test database.

## Implemented

- Added workspace-scoped metric snapshots and redacted comment records with
  PostgreSQL RLS and compound post ownership constraints. Observations carry source
  references, UTC windows, traffic scope, and explicit observed/suppressed states.
- Added deterministic Facebook/Instagram audit output with source evidence IDs,
  freshness, post ages, per-account and per-window metric coverage, and themes from
  owner-supplied redacted comments. Unique reach is never summed. Missing,
  suppressed, and measured zero remain distinct.
- Added evidence inspection and invalidation. Re-reading the audit recomputes only
  from active observations; no external provider or model call is made.
- Added an Insights workspace view and narrowed Social choices to the two
  in-scope platforms, Facebook Pages and Instagram.

## Verification

- `uv run python scripts/phase_gate.py --phase 6 --offline`: passed.
- 90 backend tests passed, including 8 real PostgreSQL checks;
  2 web tests and the production Vite build passed.
- Fixtures checked additive arithmetic, measured zero, missing and suppressed
  values, replacement of repeated snapshots, per-post unique reach, paid versus
  organic scope, account and UTC-window separation, comment redaction and themes,
  invalidation, cold start, CSRF, and cross-workspace denial.
- The additive `0008_phase6_sourced_audit` migration applied to the local application
  database without changing the existing Facebook connection or posts.
- [Generated gate report](generated/phase-06.json) contains step results.

## Limits

- Meta post reads are verified; live Page metrics and comments are not. Instagram's
  authorized connector remains pending in Phase 5. The audit labels these
  capabilities unavailable and accepts documented owner observations only.
- Pattern redaction covers email addresses, links, handles, and phone-like numbers.
  Owners must review supplied comments for other personal information.
- No live provider requests, paid image generation, or publishing occurred.

Gate decision: passed for the deterministic, source-linked offline audit. Phase 5's
Instagram work remains open; Phase 7 has not started.
