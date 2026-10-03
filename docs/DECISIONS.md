# Decisions

## ADR-0011: Bounded Gemini creative planning before local composition

Status: implemented on 2026-09-30 for the owner's continuation request.

Use the existing pinned Hermes AIAgent in an isolated, short-lived process for
creative direction. This bounded, no-tool turn uses Hermes's native Gemini adapter
and structured JSON output. The earlier general gateway/plugin proof remains a
separate proof; no production gateway is silently reused across businesses.
General `agent.hermes` worker dispatch remains outstanding.

Application admission, snapshots, conservative budget reservation, result validation,
revision creation, rendering and approval stay outside model authority. The model
receives necessary business context; the final renderer preserves real assets and
copy. Model calls use no paid-provider fallback or automatic retry. The generated
image prompt is saved/exported, but no image-generation API is enabled.

Source contracts checked against the pinned source and the official
[Hermes Python library guide](https://hermes-agent.nousresearch.com/docs/guides/python-library)
and [Gemini structured output documentation](https://ai.google.dev/gemini-api/docs/structured-output).

## ADR-0012: Owner-triggered weekly continuation before automated live sync

Status: implemented on 2026-09-30.

Completed Cairo weeks produce persistent reports from dated Facebook/Instagram
source posts and matching metric windows. Exported drafts are excluded. One report
and next plan are reused per period; explicit report refresh incorporates new
evidence without replacing owner-edited/approved plans. Follow-up syncing and
automatic weekly ticks remain unavailable until connector/runtime live gates pass.

## ADR-0001: Hermes runs out of process

Status: accepted on 2026-09-28

BrandPilot will call one private Hermes API-server process per isolated workspace
runtime home. The baseline integration is `/v1/runs` plus status/events. The API
server binds to loopback and requires a distinct bearer key.

Reason: Hermes owns the agent loop and its managed Python 3.14 environment, while
BrandPilot's application services can evolve independently. Process-level homes also
match the required workspace isolation boundary.

## ADR-0002: Hermes source is immutable and external to application code

Status: accepted on 2026-09-28

Hermes is pinned to commit `801a9022a742562a3c4578c0d8dd12cfd393fc47`.
The checkout lives under ignored `.dependencies/`; its PM-managed runtime lives under
ignored `.runtime/`. BrandPilot does not modify or vendor Hermes core.

## ADR-0003: Offline is the default and no fallback crosses a cost boundary

Status: accepted on 2026-09-28

`offline_test` selects no external model provider. Gemini free and paid operation are
explicit modes. OpenAI and image APIs require separate opt-ins. Provider errors never
trigger an automatic paid fallback.

## ADR-0004: Durable work is leased from PostgreSQL

Status: accepted on 2026-09-28

Workers claim one job in a transaction using `FOR UPDATE SKIP LOCKED`, record a
lease owner/expiry and bounded attempt count, and persist checkpoints before moving
to later steps. Expired leases are eligible for recovery. Job and outbox dedupe keys
are database constraints, not in-memory conventions.

Reason: process memory cannot preserve queued work or ownership across restarts, and
the database must arbitrate competing workers.

## ADR-0005: Local artifacts use deterministic private keys

Status: accepted on 2026-09-28

Phase 1 stores artifacts behind `LocalStorage` under a configured private root.
Writes use deterministic job keys and accept an existing object only when its bytes
match. Paths cannot be absolute or traverse above the root.

Reason: deterministic, content-idempotent writes let a recovered worker resume after
a checkpoint without duplicating or silently replacing output.

## ADR-0006: Authorization uses application checks plus PostgreSQL RLS

Status: accepted on 2026-09-28

The API resolves the current server-side session and membership for every workspace
request. Production API and worker engines assume the non-owner `brandpilot_app`
role. Each workspace transaction sets `app.workspace_id` transaction-locally, and
RLS policies enforce the same boundary for jobs, steps, outbox rows, credentials,
assets, and audit events. Workers require an explicit workspace ID.

Reason: request authorization provides useful role errors while RLS limits damage
from a missed workspace predicate and resets context when pooled connections return.

## ADR-0007: Secrets use versioned authenticated encryption

Status: accepted on 2026-09-28

Passwords use Argon2id. Provider credentials use AES-256-GCM with workspace and
provider identifiers as authenticated data; each row stores its key version. Session,
CSRF, download, and run credentials use independent opaque or signed values and are
never stored in plaintext where hashing is sufficient.

## ADR-0008: Phase 3 inputs are untrusted and recoverable

Status: accepted on 2026-09-28

Phase 3 parses uploaded images, SVG, PDF, DOCX, CSV, and XLSX as untrusted data.
Archive expansion, file count, size, MIME, active-content, and parser limits are
checked before storage. Original bytes remain private, while UI-facing metadata and
extracted text are normalized. Upload retries are content-idempotent per workspace.

Website intake validates the scheme, credentials, literal address, and resolved
addresses before queueing. Offline mode records a blocked source instead of making
an external request; a future fetcher must use bounded reads, no automatic redirects,
and repeat validation for every redirect target.

Reason: business files and copied website text can contain scripts, macros, prompt
injection, or network targets, so they must never become executable instructions or
an SSRF primitive.

## ADR-0009: Social integration scope is Facebook and Instagram

Status: accepted on 2026-09-29

Active social connector work is limited to Facebook Pages and Instagram. Facebook
Pages read access is verified; Instagram is the next connector to implement. LinkedIn,
TikTok, Pinterest, YouTube, X, WhatsApp, and other platforms are deferred future
features. Manual post import/export remains available where its provider mapping is
implemented.

Reason: shorten delivery time and verify a smaller set of useful integrations before
expanding the connector catalog.

## ADR-0010: Local composition is the no-image-API design baseline

Status: accepted on 2026-09-29

Finished design exports must work without a hosted image-generation API. The planned
studio uses confirmed brand data, uploaded product photos and logos, editable text,
shapes, patterns, and trusted local layout/rendering code. Image-generation adapters
remain optional and require a verified no-charge allowance or explicit paid opt-in.

Reason: image API access and free quotas are not guaranteed, while businesses still
need usable, editable graphics.
