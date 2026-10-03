# Phase 07 Evidence

Mode: `offline_test` with an isolated local PostgreSQL test database.

## Implemented

- Added versioned, workspace-scoped weekly plans with PostgreSQL RLS. A new draft
  revision never overwrites the last approved plan.
- Added goal selection, a deterministic strategy direction, content mix, Facebook
  Pages/Instagram platform choice, bounded adaptive cadence, and Cairo-time slots.
- Generated briefs contain a purpose, format, concept, CTA, rationale, and exact
  confirmed profile, onboarding, or available-product fact references.
- Added owner/editor revision of strategy and briefs, lock/approve/reject controls,
  replan preservation, conflict flags, and final plan approval. Publishing is manual.

## Verification

- `uv run python scripts/phase_gate.py --phase 7 --offline`: passed.
- 98 backend tests passed, including 9 real PostgreSQL checks; 2 web tests and the
  production Vite build passed.
- Three fixture businesses received distinct, sourced plans. Tests covered
  exclusion of expired or unverified promotions and unavailable products, explicit
  factual references, replan preservation and conflicts, bounded cadence,
  Cairo-to-UTC conversion across December/January, offline manual revision,
  CSRF, and cross-workspace denial.
- Migration `0009_phase7_weekly_plans` applied to the local application database.
- [Generated gate report](generated/phase-07.json) records all steps.

## Limits

- These are deterministic offline starter strategies, not Hermes-written plans.
  The owner remains responsible for reviewing manually edited copy and current
  commercial terms before publication.
- Instagram live authorization is still pending in Phase 5. Calendar briefs can
  target Instagram for manual preparation; they do not claim a publishing scope.
- Phase 8 rendering and image exports have not started. No model, image-generation,
  or social publishing call was made by this gate.

Gate decision: passed for an owner-approvable, factual offline weekly plan.
