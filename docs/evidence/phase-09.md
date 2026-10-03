# Phase 09 Evidence

Mode: `offline_test` with an isolated local PostgreSQL test database.

## Implemented

- Saved original feedback and owner-supplied interpretations against an exact design
  revision, with server-derived post, campaign-week, platform, or future scope.
- Added owner-only approval and rejection, explicit same-scope replacement, immutable
  preference versions, visible history, and rollback. Post-only notes stay local;
  fact corrections and performance hypotheses cannot become design preferences.
- Added a Studio feedback and "What I learned" panel. Fresh calendar briefs show
  applicable approved preferences; the reviewed Hermes brand-context tool reads
  workspace-wide preferences from the database on each eligible request. The free
  Gemini mode does not expose the owner's preference text through that tool.
- Added PostgreSQL RLS and compound workspace/design/feedback ownership constraints.

## Verification

- `.venv/Scripts/python.exe scripts/phase_gate.py --phase 9 --offline`: passed.
- 111 backend tests passed, including 11 real PostgreSQL checks; 2 web tests and
  the production Vite build passed. Migration `0011_phase9_feedback_learning`
  applied both to the isolated gate database and the local application database.
- Tests submitted 20 distinct corrections across four scopes and five categories;
  another 20 context cases verified scope precedence. CSRF, conflict handling,
  explicit replacement, rollback, restart retrieval, held-out brief annotations,
  and cross-workspace denial passed.
- A tool-context contract confirms free Gemini mode withholds learned preference
  text while an explicitly paid context can retrieve an approved rule.
- [Generated gate report](generated/phase-09.json) records every step.

## Limits

- Learned preferences are reviewed instructions and visible brief annotations, not
  verified brand facts or automatic graphical edits. The deterministic renderer
  does not yet use Gemini to improve composition. The current TepeS design remains
  a review artifact and is not approved for publication.
- A plan snapshots the preferences available when it is created; replan after a
  rollback to remove a stale annotation from a draft. Future retrieval and Hermes
  context omit reverted versions immediately.
- Phase 8 human design sign-off and Phase 5 Instagram authorization remain open.
  No external model, image-generation, or social publishing call was made.

Gate decision: passed for scoped, reversible offline learning. Phase 10 has not
started.
