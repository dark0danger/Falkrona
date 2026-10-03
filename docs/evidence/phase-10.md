# Phase 10 Evidence

Mode: `offline_test` with an isolated local PostgreSQL test database.

## Implemented

- Added workspace-scoped, RLS-protected publication approvals and attempts. An owner
  confirms an approved calendar brief, exact design revision, rendered artifact
  hashes, facts, destination, and a Cairo-local slot before approval. A content
  snapshot and digest bind those inputs; later edits invalidate the export.
- Added idempotent approval requests, cancellation, permission and connection
  rechecks, and explicit handling for Cairo daylight-saving gaps, overlaps, and
  missed times. Duplicate requests create one local attempt.
- Added a manual ZIP with PNG/JPEG renders, caption, source manifest, and an
  approval receipt naming the destination, slot, and content hash. The receipt
  explicitly states `published: false`; downloading never calls Meta.
- Added internal remote-attempt transition and recovery contracts. An uncertain
  upload or publish outcome requires reconciliation rather than a blind retry.
  No live connector or scheduler invokes these contracts yet.

## Verification

- `.venv\Scripts\python.exe scripts/phase_gate.py --phase 10 --offline`: automated
  checks passed; the full Phase 10 gate did not pass.
- 120 backend tests passed, including real PostgreSQL/RLS checks; 2 web tests and
  the production Vite build passed.
- Focused approval and recovery tests passed (8 tests, 9 schedule subtests),
  covering stale content, CSRF, scope and role denial, connection loss, cancellation,
  exact package receipt, duplicate requests, Cairo DST, and uncertain remote writes.
- Migration `0012_phase10_publication` applied to the local application database.
  [Generated gate report](generated/phase-10.json) records the full result.

## Open Gate

- Phase 8 TepeS artwork still needs owner design approval. Existing Meta Page access
  is read-only and Instagram authorization remains open; no publish capability has
  been verified.
- No public-media derivative/URL, live publish worker, or authorized remote post
  with an owner-verified ID was implemented or tested. The remote state machine is
  a safety contract, not proof of a working connector or two-worker live delivery.
- Phase 10 therefore remains in progress with
  `live_publication_status: blocked_no_verified_write_capability`. Manual export
  is usable now but must never be displayed as published. Phase 11 has not started.
