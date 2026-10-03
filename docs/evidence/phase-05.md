# Phase 05 Evidence

Mode: offline_test gate plus live Meta development-app probe

Status: Facebook Pages identity, managed Page listing, and post reads passed.
Instagram remains pending under the updated Phase 5 scope.

## Implemented contracts

- Workspace-scoped Meta authorization transaction, callback browser binding,
  one-use state, owner Page selection, encrypted credentials, and disconnect.
- Separate identity, account-list, and post-read capability state; no analytics
  or publishing capability is advertised.
- Queued Page post sync with bounded cursor pages, durable checkpoints,
  idempotent source-ID upserts, and explicit rate-limit/revocation outcomes.
- Arabic/English CSV post import preview and confirmation with private source
  storage and owner_imported provenance; workspace-scoped CSV export with
  spreadsheet-safe cells.
- Same-Page reconnect rotates encrypted credentials without deleting imported
  history. A queued sync fails without reading posts after disconnect.
- Migration 0007_phase5_social_connections and PostgreSQL RLS.

## Verification

- Local PostgreSQL migration: passed.
- Consolidated Phase 5 gate: passed with 83 backend tests, including 7 real
  PostgreSQL checks, 2 web tests, a production Vite build, and
  dependency inventory of 45 Python and 138 Node packages with no undeclared
  licenses.
- The gate uses a separate local `brandpilot_phase_gate` database so test cleanup
  cannot remove application jobs. Its generated [phase-05.json](generated/phase-05.json)
  records both offline checks and read-only live capability evidence.
- A Meta development app now lists the exact HTTPS callback used by Falkrona.
  The tunnel serves the owner UI, the proxied API reports `gemini_free`, and
  the API readiness check passes.
- On 2026-09-29, the owner completed Meta consent and selected the managed
  TepeS Page through Falkrona. The application recorded `connected_partial`
  with granted scopes `pages_show_list`, `pages_read_engagement`, and
  `public_profile`. Its capability record marks identity, account listing, and
  posts true, and comments, metrics, upload, publish, and webhooks false.
  `MetaGraphTransport.probe_posts` reads `/{page_id}/posts` with `fields=id`
  and `limit=1` before the posts capability is set; the configured Graph API
  version was `v26.0`. No Page token or post content was copied into evidence.
- A later Meta callback returned `provider_malformed` because its token response
  did not satisfy Falkrona's prior positive-integer `expires_in` requirement.
  The exact provider payload was not logged, so the response shape is unverified.
  The transport now accepts omitted/zero lifetimes with a 24-hour local bound,
  accepts decimal-string lifetimes, and caps positive lifetimes at 60 days.
  Selecting the same verified Page now rotates credentials while retaining its
  connection and imported history. The owner confirmed that reconnect works.
- The first one-shot post-sync attempt could not reach Meta from the restricted
  local tool sandbox; the job stayed queued for retry. Two permitted worker passes
  then completed both queued jobs against the authorized TepeS Page. The first
  imported two posts; the second kept the count at two. Each completed after one
  page, and the connection's last-sync time was updated. No Page token or post
  content is included in the evidence.

## Gate decision

The recorded gate passed for the three live Facebook Page read capabilities:
identity, managed Page listing, and posts. Comments, analytics, upload, publishing,
and webhooks are not verified or enabled. Phase 5 remains open until the Instagram
connector is implemented and verified. Other platform adapters are deferred; manual
CSV import/export remains available. Future live sync jobs require a continuously
running worker scoped by `BRANDPILOT_WORKSPACE_ID`.
