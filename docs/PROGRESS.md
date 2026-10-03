# Progress

## Posting date editor — 2026-10-03

Added Change posting date beside finished designs, with a compact Cairo date/time
editor before plan approval. Schedule validation protects the plan's week,
future times, conflicts and Cairo clock changes. Artwork and other posts remain
unchanged. Passed 22 targeted integration tests, 11 UI tests, production build,
and isolated browser Save/Cancel/refresh verification. See
evidence/posting-date-editor-2026-10-03.md.

## Asset purpose groups and owner design controls — 2026-10-03

Grouped uploads by their saved purpose and restricted product pickers to product
photos, including cleanup of four older complete ads uploaded through the product
box. Added recoverable plan/post deletion and one-post regeneration with a new
visual idea, preserving other posts and revision history. Brand CTA geometry and
styling now travel in every new Gemini/image-app prompt and across future weeks;
Hermes creative instructions are updated. Final suite: 241 tests, 96 subtests and
8 UI tests passed; build and live UI review passed. See
evidence/owner-design-controls-2026-10-03.md.

## Request-specific drafting constraints and preview recovery — 2026-10-03

Fixed the owner’s three-post Arabic sales draft by constraining Gemini's schema
to actual facts, available purposes, requested platform/count, colors and future
posting days. Selected language now reaches the planner as well as image prompts;
invalid drafts preserve previous plans and retain plain failure explanations.
The exact live retry returned all three Arabic posts successfully.

Live image testing also exposed an overlong Arabic CTA and transient overlapping
ChatGPT previews. Added schema word limits and helper 0.1.5 candidate stabilization
with source deduplication. Same-request recovery and genuine multiple-image
selection remain protected. See evidence/drafting-recovery-2026-10-03.md.

## ChatGPT upload readiness and saved-request recovery — 2026-10-03

Reproduced the owner-visible attachment confirmation pause: the two fresh
ChatGPT tabs contained empty composers and no accepted attachment previews.
Resumed the existing saved request once on its now-ready tab. The helper attached
all three authorized images, submitted once, retrieved the finished artwork and
imported it into the plan. The live plan displays Ready to review, the image,
caption and scheduled Cairo time. No publishing approval was clicked.

Helper 0.1.4 now verifies ChatGPT's upload menu responds before setting files;
the visible server-rendered file inputs alone do not prove upload readiness.
It pauses without attaching or sending if the controls never initialize. Existing
partial-upload and uncertain-submission protections remain in place. All 27 helper
regressions pass, including delayed hydration and unavailable upload controls.
Updated the exact installed Falkrona-Browser-Helper folder; Chrome Reload is
required to activate the new files. Live evidence: .runtime/generation-resumed-review.png.

## Whole-plan approval and automatic Facebook publishing — 2026-10-02

One Draft a plan action now chains Gemini planning into browser-helper image
generation. The owner reviews complete artwork, current saved captions, Page and
Cairo posting times, then approves the whole plan once. Approval atomically binds
exact design revisions and hashes to durable due-time jobs. An owner can cancel
unpublished posts. Changed facts, artwork, captions, revoked ownership, expired
credentials and removed Page rights prevent a write.

Implemented fixed-host multipart unpublished-photo upload, attached-media feed
publication and photo/story reconciliation. Before-request states and remote IDs
are checkpointed; uncertain writes never blindly retry. Confirmed remote post IDs
enter social history for daily engagement and weekly reporting. A dedicated
publishing-only worker keeps model work off the delivery queue. API and both
workers are running; all existing RLS tables are reused without schema changes.

Publishing, OAuth, generation, planning, transport, jobs and report regressions
passed. Production UI build passed. Live drafting is being checked; initial image
generation paused because the helper was not connected to the current origin.
No live publication is claimed or performed until the owner approves exact posts.
See evidence/scheduled-publishing-2026-10-02.md.

## Fresh owner test and publishing reconnect — 2026-10-02

Added an owner-only, explicit Facebook publishing-permission reconnect action.
Ordinary Connect Facebook still requests read scopes; Allow publishing access
adds pages_manage_posts with rerequest consent. Instagram scopes remain absent.
The API retains workspace authorization, CSRF and browser-bound OAuth state.
Granting permission does not enable the unimplemented live publisher.

The owner requested a fresh test. Backed up and cleared this workspace's nine
weekly plans, 20 design versions, one render record and five generated image
asset records. Brand/profile/survey data, logo, design reference, four uploaded
materials, Facebook connection, imported social history and usage accounting
were preserved. Scoped RLS transactions verified their unchanged fingerprints.
Old creative dedupe keys were archived so an identical new draft can run again.
Original image files remain in storage; row backups are in .runtime.

OAuth/transport validation: 21 tests and 12 subtests passed. Frontend build passed,
API restarted healthy, and the updated owner UI was checked in Chrome. The
owner completed Allow publishing access and selected TepeS again. A read-only
Meta check at 18:36 UTC verified pages_manage_posts in both saved and current
grants and the Page CREATE_CONTENT task. Post reading passed; engagement still
returns permission_missing. Live delivery remains disabled and unimplemented.

## Separate social buttons and publishing review — 2026-10-02

Facebook and Instagram have separate connection buttons in their respective
cards. Facebook retains read-only consent; Instagram is marked setup pending and
does not reuse the Facebook button. Page selection labels/filtering are explicit,
and connected accounts state that tracking is available while publishing is not.

Live Meta v26.0 checks confirmed TepeS post reads and Page content tasks. The
current token grants only public_profile, pages_show_list and pages_read_engagement;
pages_manage_posts is absent. Engagement counts still return permission_missing.
Phase 10 remains manual export only, with no live adapter or scheduler. No new
scopes, remote uploads or publications were requested. Publishing/Meta regressions
and frontend build passed; see `evidence/publishing-permissions-2026-10-02.md`.

## Owner UI spacing and responsive polish — 2026-10-02

Polished the existing five-section UI with consistent 44px controls, readable
secondary text, smaller saved-post thumbnails, a balanced Studio preview/caption
layout and tighter brand-form spacing. The single-image slide selector is hidden.
Phone navigation now wraps so every section remains visible. Fixed horizontal
overflow and excess vertical space caused by intrinsic mobile grid sizing.

Signed-in Chrome checks covered Dashboard, Brand, Product photos, Social accounts,
Content plan, saved Studio artwork and Weekly reports, with desktop, 900px tablet
and 390px phone checks. The checked responsive pages had no horizontal overflow.
Production build passed. No design generation, brand save or social publication
was submitted. The saved Facebook Page currently requests reconnection; the Meta
allowlist callback remains:
https://thereby-examines-reggae-tiles.trycloudflare.com/api/v1/social/meta/callback

## Simple owner UI and restored preview — 2026-10-02

Rebuilt the UI around the owner's light dashboard reference: pale navigation,
coral actions, a brand toolbar, bordered cards and actual saved-post previews.
Five main sections remain. Product photos sit under Brand; catalog imports,
social-history imports, plan preferences and image preferences are collapsed.
The main plan actions remain Draft week and Generate, with the Arabic/English
design choice retained. Weekly reports are reached from the dashboard and the
sidebar check-in. No sample metrics, people or comments were added to live data.

The dashboard reads the current Cairo week and renders the latest report's
measured reaction snapshots without summing repeated lifetime measurements.
Missing measurements remain unavailable. Image previews and data requests stay
scoped to the selected workspace; switching workspaces clears previous brand
materials before loading the next workspace.

Validation: production build and eight frontend checks passed. The restored
public site and API health returned 200; desktop and 390px sign-in layouts were
inspected. Signed-in checks were subsequently completed in the owner's reconnected
Chrome browser during the spacing and responsive polish described above.
No image generation or publication was submitted during the UI work.

Cloudflare retired the previous quick tunnel. New preview:
https://thereby-examines-reggae-tiles.trycloudflare.com/ . The Vite allowlist and
local Meta callback setting now use this address, and the API was restarted.
Meta's allowlist still needs the new callback before a new Facebook connection.

## Arabic/English design choice — 2026-10-02

Calendar now offers one Design language choice for the week's images, and Studio
offers the same English/Arabic choice for a new design version. The selected
language is saved with generation inputs and reaches every Gemini direction and
image-app prompt, covering headline, CTA and caption. Arabic prompts request
joined letters, right-to-left order and a compatible brand font; logo and package
lettering retain their original identity. The worker rejects a mismatched language
or copy without letters in the selected script. Older automatically planned
requests remain resumable without changing their saved inputs.

Both new language integrations passed, alongside the English batch/package and
helper-download regressions. The other 21 weekly/direction checks passed before
the final focused rerun; the production build passed. API and worker restarted.
Live Studio selection verified both options and Arabic selection; screenshot:
`.runtime/design-language-choice.jpg`. No additional image request was sent.

## Distinct campaign scenes with consistent branding — 2026-10-02

Gemini now chooses the shared brand treatment and distinct weekly scenes before
product-image inspection. Per-post prompts receive all assigned concepts and
explicit product-identity/source-scene separation. The browser request reinforces
the assigned composition and scenery exclusions. Duplicate scene systems and
copy-only prompt changes are rejected before image handoff. Branding treatment
persists across later weeks under the same confirmed profile. Owner controls stay
Draft week and Generate; existing plans require a new visual plan.

The Hermes skill is updated and installed. 28 focused backend regressions and the
production build passed. Exact logo palette is supplied during weekly planning;
designed backdrop colors are validated. Transparent logos add neutral contrast
without substituting Falkrona's default ink. The live Gemini plan and both ChatGPT
images completed and imported automatically: one white overhead ingredient scene,
one human enjoying the juice with the product bottle visible. Both are 1080x1350.
Helper 0.1.3 fixes current ChatGPT upload-input selection and empty hydration
recovery; 25 helper tests pass. The frontend accepts compatible patch updates.
The weekly package now retains saved caption edits paired with the correct image;
its regression passed and the downloaded ZIP contains both images/captions and
the two-post schedule. See [evidence](evidence/creative-variety-2026-10-02.md).

## Gemini weekly drafting and batch images — 2026-10-01

Draft week now queues one Gemini request for the whole plan. Generate prepares
distinct Gemini prompts for all posts, sends them through the connected image app
and saves each returned image independently. Calendar provides one weekly download;
there is no individual design approval gate. Explicit retries preserve successful
work. Hermes's design skill documents this owner flow and image-role separation.

The live Gemini test drafted two Facebook posts for Tepes and prepared both image
prompts. The helper attached the logo/product/reference and submitted both actual
ChatGPT requests. The first generated image returned automatically; recovery of
the second finished image is being verified. Fixed bridge reload, rich text, upload
hydration, stale image views, expired import-window reuse and long-job CSRF recovery.
Six weekly integration, sixteen related direction/planning, seven job/API,
22 helper and five web tests passed, along with the production build.
Facebook post sync passed live; engagement snapshots record permission_missing
because current Meta access rejects reactions/comments. Instagram testing deferred.
See [current evidence](evidence/weekly-gemini-generation.md).

## Studio and ChatGPT helper correction — 2026-10-01

Browser helper 0.1.1 fixes rich-text whitespace verification, scoped Send detection
and the current ChatGPT response layout. Resume watches a matching submitted
request without resending. Missing tracking after extension reload pauses for
manual import; Studio refuses older helpers before starting a request. Setup and
manual recovery are collapsed, and saved-request import can open without starting
the helper. Thirteen helper regressions, the production build and the targeted
API image-import/ZIP test passed. API restarted; public URL retained.

Signed-in ChatGPT controls were inspected. The existing finished ad was downloaded
and matched to its original Studio prompt. Import was blocked by browser-control
file-upload permissions. Reload of the installed extension and a live automatic
send/return test remain pending; no new image request was sent during this repair.

## Browser image-app continuation — 2026-10-01

The owner-approved browser-helper workflow replaces local rendering for new ads.
Gemini/Hermes plans a complete ad from Branding, the brief, factual products, the
actual logo/product pixels and optional style reference. Product photos remain
identity inputs, never design references or finished backgrounds. The worker stops
after its single planning call. Studio and the Chrome/Edge helper handle the
consented external image-app request and import its complete pixels into a new,
unapproved, context-bound revision without duplicate text/logo overlays.

The consolidated gate passed: 149 backend tests (including PostgreSQL), two web
tests, production build and dependency inventory. Five browser-helper tests verify
origin/tab binding, single-send recovery, explicit pre-send resume and image-role
validation. The real Studio component was exercised in an isolated sample-data
browser preview, including saved-direction recovery after refresh. API and worker
restarted; the original public tunnel/Meta callback is preserved.

Hermes's design skill is updated and installed. A pinned real-Hermes loopback
fixture passes with one native-vision call and zero external calls. Website-account
verification is pending: inspected Gemini/ChatGPT sessions were signed out. The
helper is a development preview; full-resolution automatic download and live DOM
adapters need the owner's signed-in test. See [setup and limitations](BROWSER_IMAGE_WORKFLOW.md).

## Previous owner-flow continuation — 2026-10-01

The owner flow now starts with **Branding**: four Gemini-generated questions with
examples, a required verified transparent logo, and one optional uploaded design
reference. Studio enforces this setup on the server and uses the saved logo. Social
asset/website reference intake options and technical design controls were removed
from the owner UI. Gemini receives small metadata-free previews of logo, product
and reference images along with the confirmed business context.

The workspace worker collects dated engagement daily and generates reports on
Mondays at 00:05 Cairo time, with durable deduplication/restart catch-up and an
in-app Results badge. Linked professional Instagram read/like/comment collection
is implemented and fixture-tested alongside Facebook. Missing counts remain
unavailable; lifetime counts are distinguished from reporting-week performance.
Migration 0015 applied to local PostgreSQL without resetting existing data.

Live Gemini and live Meta OAuth/measurements/publication still need real-account
verification. See [the revised owner flow and validation](BRANDING_AND_WEEKLY_REPORTS.md).

## Previous continuation — 2026-09-30

Phase 11 local foundation and Gemini creative planning implemented and verified.
The consolidated offline gate passed: 129 backend tests including real PostgreSQL
checks, two web tests, production build and dependency inventory. The real pinned
Hermes creative runner passed a single-request loopback fixture. Additive migrations
0013/0014 applied to local application PostgreSQL.

Studio can ask Gemini to organize the design idea/prompt using current brand,
brief, referenced products, accepted preferences, asset metadata, logo colors and
language before local composition. Facts/asset/input changes invalidate the prepared
direction. The final design keeps its source images and exact copy; image API calls
remain disabled. Active output sizes are for Facebook/Instagram only.

Results now prepares dated weekly reports and editable next plans without repeated
onboarding. Duplicate cycles reuse the same report/plan; explicit refresh handles
late evidence. Reports exclude unpublished designs/exports and preserve uncertainty.

Phase 10 live publishing, Instagram access, live Gemini verification, automatic
weekly sync, complete product-change draft invalidation, and Phase 12 hardening
remain open. Historical phase sections below describe their original verification.

See [review](REVIEW_2026-09-30.md), [setup](GEMINI_CREATIVE_SETUP.md), and
[continuation evidence](evidence/phase-11.md).

## Phase 10 - Approved publishing and scheduling

Status: in progress (offline export workflow verified; live publishing blocked)

- Added exact-design owner approval, content/fact/render hashing, destination and
  Cairo-time binding, idempotent local attempts, cancellation, and manual packages
  containing an approval receipt. Export does not claim a published post.
- Added internal uncertain-outcome recovery rules for future connectors, but no
  live scheduler, public-media delivery, or Meta publish adapter is enabled.
- Phase 10 offline checks passed on 2026-09-30: 120 backend tests including real
  PostgreSQL checks, 2 web tests, and production build. Migration
  `0012_phase10_publication` applied locally.
- The full gate remains blocked by unapproved TepeS artwork, unverified Meta write
  permission, and the absence of an owner-verified live publish. Phase 11 has not
  started.

Evidence: [phase-10.md](evidence/phase-10.md) and generated
[phase-10.json](evidence/generated/phase-10.json).

## Phase 9 - Feedback and persistent learning

Status: complete for offline scoped feedback and owner-approved preference retrieval

- Design-revision feedback retains the original note, interpreted correction,
  category, actor, timestamp, and server-derived post/campaign/platform/future scope.
- Owner approval, explicit conflicting-rule replacement, version history, rejection,
  and rollback are available in Studio. Facts and performance hypotheses do not
  silently become preferences or global claims.
- New Calendar briefs show applicable approved rules. The reviewed Hermes brand
  context reads active workspace-wide rules fresh outside `gemini_free` mode;
  rollback removes them from future retrieval. RLS and compound ownership protect
  both new tables.
- Phase 9 offline gate passed on 2026-09-30: 111 backend tests, including 11 real
  PostgreSQL checks; 2 web tests and production build passed. Twenty distinct
  corrections and 20 scope-context cases were checked. Migration
  `0011_phase9_feedback_learning` applied to local PostgreSQL.

Phase 8 human design approval and Phase 5 Instagram authorization remain open.
Preferences do not automatically improve rendered artwork; Gemini-assisted design
work is deferred. Phase 10 offline approval/export work has since started.

Evidence: [phase-09.md](evidence/phase-09.md) and generated
[phase-09.json](evidence/generated/phase-09.json).

## Phase 8 - Creative studio and finished exports

Status: in progress (automated checks passed; human design gate pending)

Implemented:

- Workspace-scoped immutable design revisions and private render artifacts with RLS.
- Calendar-linked local studio, browser-shaped Arabic/bilingual preview, undo,
  asset-preserving image layers, destination presets, and ordered PNG/JPEG ZIP export.
- Offline reference traits, scene validation, text-fit and contrast checks.
- TepeS review retry with its actual Page profile image, an illustrative
  owner-described unbranded bottle, on-image Arabic copy, and product-image
  confirmation before guided regeneration.

Verified on 2026-09-29:

- Phase 8 automated gate passed: 104 backend tests including 10 PostgreSQL checks,
  2 web tests, and production build.
- Browser smoke rendered 30 PNG fixture variants at all six sizes; an isolated owner
  workflow saved and exported English and bilingual designs.
- Local application database migrated to `0010_phase8_creative_studio`.
- Updated offline gate passed with 106 backend tests, 2 web tests, and production
  build. The TepeS review PNG was inspected at 1080x1350.

Gate decision: pending David's design rubric and further renderer hardening. No
image API cost or social publishing. Phase 9 offline work has proceeded separately.

Evidence: [phase-08.md](evidence/phase-08.md) and generated
[phase-08.json](evidence/generated/phase-08.json).

## Phase 7 - Marketing direction and weekly calendar

Status: complete for the offline, owner-approvable calendar

- Added goal selection, source-linked starter strategies, adaptive cadence,
  content mix, Facebook/Instagram briefs, and Cairo-local calendar editing.
- Confirmed facts are referenced per brief; unsafe/expired promotions and
  unavailable products are omitted from automatic drafts.
- Plans are versioned; replanning preserves approved or locked briefs and flags
  stale facts, removed platforms, and schedule conflicts. Last approved plans remain
  available while a later revision is in draft.
- Phase 7 gate passed with 98 backend tests (9 real PostgreSQL checks), 2 web tests,
  and a production build. Migration `0009_phase7_weekly_plans` applied locally.

Evidence: [phase-07.md](evidence/phase-07.md) and generated
[phase-07.json](evidence/generated/phase-07.json).

Instagram authorization remains open in Phase 5. Phase 8 rendering and automatic
publishing have not started.

## Phase 6 - Deterministic analytics and sourced audit

Status: complete for the offline, source-linked audit; live metric reads unavailable

- Added workspace-isolated metric and redacted-comment observations, evidence IDs,
  source freshness, UTC windows, traffic scope, and evidence invalidation.
- The audit distinguishes measured zero, missing, and suppressed values; it never
  sums unique reach snapshots or reports a partial metric total as complete.
- Added an Insights view for Facebook Pages and Instagram, including honest
  cold-start and unavailable-capability states.
- Phase 6 gate passed with 90 backend tests, 2 web tests, a production build, and
  migration `0008_phase6_sourced_audit` applied to local PostgreSQL.

Evidence: [phase-06.md](evidence/phase-06.md) and generated
[phase-06.json](evidence/generated/phase-06.json).

Instagram authorization remains open in Phase 5. No live metrics/comments access
or Phase 7 work is claimed.

## Phase 5 - Social connections and reliable imports

Status: Facebook Pages read scope passed; Instagram remains in Phase 5 scope

Implemented so far:

- Added a Social workspace view for Facebook Pages and Instagram with account-level
  status and manual fallback routes. Other connectors were deferred by scope update.
- Added a Meta Pages read flow with one-use workspace/user/session/browser-bound OAuth
  state, encrypted server-side tokens, owner-verified Page selection, per-capability
  read probes, disconnect, and a clear expired/revoked permission state.
- Added queued, checkpointed Page post synchronization with cursor pagination,
  idempotent source-ID upserts, rate-limit retry, and no publishing capability.
- Added Arabic/English social CSV preview and confirmation, private source storage,
  owner-imported provenance, repeat-import deduplication, and a scoped CSV export.
- Added same-Page reconnect with credential rotation and retained post history.
- Isolated phase-gate PostgreSQL tests from the application database and added a
  read-only live Meta evidence check.
- Added migration 0007_phase5_social_connections with PostgreSQL RLS for OAuth
  transactions, connections, and imported posts.

Verified so far:

- The migration applied to local PostgreSQL.
- Focused API tests covered callback browser binding, replay, expiry, cancellation,
  Page management checks, partial permissions, encrypted credential deletion,
  cross-workspace access, Arabic import deduplication, paginated sync, checkpoint
  retry, and revoked-token handling.
- The consolidated gate passed with 83 backend tests, including 7 PostgreSQL
  checks, 2 web tests, a production build, and dependency inventory. See
  [phase-05.md](evidence/phase-05.md).
- On 2026-09-29, the Meta development app completed its HTTPS callback and
  the owner selected the managed TepeS Page. The real `v26.0` connection is
  `connected_partial`: identity, account listing, and the post read probe
  succeeded with `pages_show_list` and `pages_read_engagement`. Two live sync
  jobs completed and imported two distinct posts without duplication. Comments,
  metrics, upload, publishing, and webhooks remain unavailable.

Gate decision: passed for the advertised Meta read capabilities only. Other
platform adapters remain unavailable with manual import/export. Under the updated
scope, Phase 5 stays open until Instagram's authorized capabilities are implemented
and verified. A workspace-scoped worker must stay running for future syncs.

## Phase 4 - Production Hermes bridge and provider controls

Status: complete (offline gate passed; live providers explicitly unverified)

Implemented so far:

- Durable, RLS-protected agent runs, tool-call audit records, usage ledger entries,
  and atomic per-run budget reservations.
- Explicit model configuration, selected-provider admission, public Gemini and paid
  OpenAI contract paths, redaction/classification before external-model admission,
  and image capability fail-closed behavior.
- Owner agent-run start/read/cancel endpoints plus short-lived, run-scoped Hermes
  credentials for exactly two reviewed app tools: read confirmed brand context and
  store a plain-text artifact.
- A Falkrona Hermes plugin with no terminal, arbitrary filesystem, browser,
  install, or general network capability; its only HTTP calls target the local
  signed app-tool endpoints.
- Hermes client support for the pinned `/v1/runs/{id}/stop` endpoint and a Phase 4
  gate entry that requires the real local Hermes proof.

Verified on 2026-09-28:

- Consolidated Phase 4 gate passed in `offline_test` mode: 62 backend tests,
  including 6 real PostgreSQL tests, 2 web tests, production build, and dependency
  inventory all passed.
- The Phase 4 focused contracts passed: pre-transport redaction, private Gemini
  rejection, Gemini/OpenAI public-task admission fixtures, one-provider selection,
  quota exhaustion, cancellation, reviewed app-tool artifact storage, and forged
  workspace rejection.
- Migration `0006_phase4_hermes_runs` applied to local PostgreSQL successfully.
  Six real PostgreSQL tests passed, including RLS visibility for `agent_runs`.
- The pinned Hermes gateway on `127.0.0.1:8642` accepted a real `/v1/runs` request,
  reached `completed`, made 4 fixture-provider turns, invoked both reviewed Falkrona
  tools, persisted an artifact through the app endpoint, and stopped cleanly.

Gate decision: passed. No live Gemini/OpenAI call has been made and Phase 5 has not
started at the time of this Phase 4 gate.

Evidence: [phase-04.md](evidence/phase-04.md) and generated
[phase-04.json](evidence/generated/phase-04.json).

## Phase 3 - Assets, imports, and adaptive onboarding

Status: complete

Implemented:

- Falkrona identity in the owner UI, browser title, repository metadata, and web
  workspace package; the internal `brandpilot` Python import namespace remains stable.
- Private, content-idempotent uploads for PNG/JPEG/WebP/SVG/PDF/DOCX with image
  metadata, safe SVG normalization, bounded archives, and extracted document text.
- Arabic/English CSV/XLSX product mapping previews, durable import jobs, private
  source storage, and idempotent product confirmation.
- Public URL intake with scheme, credential, literal-IP, hostname, and DNS checks;
  offline mode records an explicit blocked import and performs no external fetch.
- Persistent adaptive onboarding with confirmed-answer skipping, relogin resume, and
  contradiction records; versioned manual brand profiles remain owner-confirmable.
- Responsive owner controls for English/Arabic direction, keyboard-accessible upload,
  import, onboarding, profile, gallery, and URL-intake workflows.

Verified on 2026-09-28:

- Phase 3 Alembic migration applied successfully to local PostgreSQL after an
  upgrade-safe RLS policy replacement for the existing asset policy.
- Consolidated Phase 3 gate passed in `offline_test` mode.
- 51 backend tests passed, including 5 real PostgreSQL tests; no earlier phase
  failures were observed.
- Phase 3 security/API/migration coverage passed: 9 focused tests and 4 URL-policy
  subtests, with PNG transparency, rotated JPEG, WebP, sanitized SVG, Arabic
  document/spreadsheet mapping, malformed/oversized/archive/MIME rejection,
  content-idempotent uploads, onboarding contradictions, and URL blocking.
- 2 web tests passed and the production TypeScript/Vite build passed.
- Dependency inventory recorded 45 Python and 138 Node packages with no undeclared
  licenses.

Gate decision: passed. Manual profile confirmation works without imports, and richer
inputs remain optional. Phase 4 had not started when this Phase 3 gate was recorded.

Evidence: [phase-03.md](evidence/phase-03.md) and generated [phase-03.json](evidence/generated/phase-03.json).

## Phase 2 - Accounts, authorization, and workspace isolation

Status: complete

Implemented:

- Protected local owner setup, Argon2id passwords, opaque server-side sessions,
  secure cookies, CSRF, expiry, revocation, and login throttling.
- Workspace memberships and owner/editor/analyst role enforcement with immediate
  revocation.
- Workspace-scoped jobs, SSE status, signed downloads, encrypted credentials, audit
  events, and forged plugin-call rejection.
- Browser owner setup/sign-in, session restoration, workspace display, and sign-out.
- Non-owner PostgreSQL application role with transaction-local context, RLS policies,
  pooled-connection isolation, and compound workspace/job integrity.
- Two similar fixture businesses with distinct assets and encrypted credential values.

Verified on 2026-09-28:

- Consolidated Phase 2 gate passed against `postgres:17.6-alpine`.
- 44 backend tests passed, including 5 real PostgreSQL tests.
- The adversarial matrix found no cross-workspace API, file, SSE, job, database, or
  plugin-tool read/write path.
- Session/CSRF/expiry/revocation/rate-limit, role, signed-download, encryption, and
  token-forgery tests passed.
- 2 web tests and the production TypeScript/Vite build remained green.
- Desktop and 390x844 login/setup views passed visual inspection.
- Dependency inventory recorded 36 Python and 138 Node packages with no undeclared
  licenses.

Next: Phase 3 - assets, imports, and adaptive onboarding.

## Phase 1 - Durable application foundation

Status: complete

Implemented:

- FastAPI bootstrap with live/ready health, runtime status, job submission, and
  usable typed HTTP errors.
- Restartable worker with PostgreSQL leases, bounded attempts, checkpoints,
  heartbeat support, expired-lease recovery, and deterministic local outputs.
- `jobs`, `job_steps`, and `outbox_events` persistence with dedupe constraints.
- Two-step Alembic history covering clean install and upgrade from the Phase 0
  fixture schema.
- Private local storage abstraction with traversal, conflict, and duplicate guards.
- Structured JSON logging with secret redaction.
- React/Vite operations shell with desktop/mobile layouts and visible offline sample
  state.
- Offline fixtures, strict startup configuration, locked dependencies, and generated
  license inventory.

Verified on 2026-09-28:

- Consolidated Phase 1 gate passed against `postgres:17.6-alpine`.
- 34 backend tests passed, including 3 real PostgreSQL tests.
- Two independent workers claimed one PostgreSQL job once; an expired lease was
  reclaimed on attempt 2.
- A worker restart after its durable checkpoint completed with one local output.
- Clean migration and prior-schema upgrade both preserved expected state.
- Healthy and degraded API/database/storage states returned actionable responses.
- Offline boot made no external connection and paid/provider calls remained disabled.
- 2 web tests and the production TypeScript/Vite build passed.
- Dependency inventory recorded 31 Python and 138 Node packages with no undeclared
  licenses; npm audit reported zero vulnerabilities after upgrading Vitest.
- Desktop and 390x844 mobile views were inspected with no overlap; sample/offline
  disclosure remained visible.

Current external status remains unchanged:

- Gemini live smoke: `blocked_no_key`
- OpenAI live smoke: `blocked_cost_policy`
- Social providers: not started

Next: Phase 2 - accounts, authorization, and workspace isolation.

## Phase 0 - Feasibility, dependency lock, and real Hermes spike

Status: complete (offline gate passed; live providers explicitly blocked)

Implemented:

- Repository bootstrap and offline-first runtime contract.
- Hermes source pin and isolated dependency/runtime paths.
- Minimal `brandpilot_phase0_probe` Hermes plugin.
- Application-side `/v1/runs` client with loopback and bearer-key requirements.
- Typed missing-key, authorization, quota, transport, and malformed-output outcomes.
- Fail-closed Gemini/OpenAI cost and data admission policy.
- Local PostgreSQL container definition.
- Environment, unit, phase-gate, and real-Hermes spike scripts.
- Root Python and Node lockfiles plus Hermes's upstream hash-verified locks.

Verified on 2026-09-28:

- Pinned Hermes runtime prepared with PM-managed Python 3.14.7.
- Real plugin discovery and tool invocation passed through Hermes core.
- Two runtime homes kept distinct histories; Workspace A retained 6 messages and
  grew to 12 after restart without receiving Workspace B's marker.
- The private gateway bound to `127.0.0.1`; missing/wrong keys returned 401 and
  the correct key returned 200.
- A real `/v1/runs` request completed and exposed tool lifecycle events plus
  structured usage of 300 input and 40 output fixture tokens.
- `offline_test` used only a loopback fixture and made zero external provider calls.
- PostgreSQL Compose configuration parsed successfully with its port bound to
  `127.0.0.1`. Starting the durable service belongs to Phase 1.
- All 16 unit contracts and the combined Phase 0 gate passed.

Current external status:

- Gemini live smoke: `blocked_no_key`
- OpenAI live smoke: `blocked_cost_policy`
- Social providers: not started

Gate completed before Phase 1 work began.
