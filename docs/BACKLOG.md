# Executable Backlog

The technical plan remains the product contract, with the user-approved scope update
below taking priority for current implementation. Work proceeds in order; a phase is
complete only when its gate has evidence and affected earlier gates still pass.

## Current scope

- Build social integrations only for Facebook Pages and Instagram.
- Instagram is the next connector; Facebook Pages read and CSV import/export are
  already verified. Offline later-phase work can proceed while Instagram access
  remains pending, without claiming its live capabilities.
- LinkedIn, TikTok, Pinterest, YouTube, X, WhatsApp, and other connectors are future
  features. Do not implement or advertise them as live integrations in this scope.
- Keep local composition and uploaded assets as the finished-design path. Image
  generation APIs stay optional and disabled without a verified free allowance or
  explicit paid opt-in.

| Phase | Deliverable | Gate |
| --- | --- | --- |
| 0 | Pinned real Hermes spike, offline provider contracts, reproducible bootstrap | Real plugin tool round trip and authenticated private integration |
| 1 | API/web/worker foundation, migrations, durable jobs, storage | Restart and configuration recovery tests pass |
| 2 | Accounts, roles, encryption, workspace isolation | Adversarial cross-workspace matrix has no known read/write |
| 3 | Safe imports, assets, adaptive onboarding, editable brand profile | Manual-only onboarding produces a confirmed usable profile |
| 4 | Production Hermes bridge, skills, provider budgets and data filtering | Selected live provider completes a permitted real run |
| 5 | Facebook Pages and Instagram OAuth, read capabilities, sync, and manual imports/exports | Verify each advertised capability independently for both in-scope platforms |
| 6 | Deterministic analytics and sourced audit | Every displayed number traces to source data |
| 7 | Strategy and weekly calendar | Owner can approve an actionable, factual plan |
| 8 | Scene editor, renderer, variants and finished exports | Factual/logo/overflow checks pass and human rubric target is met |
| 9 | Scoped, versioned preference learning and rollback | Scope tests pass with no cross-workspace leakage |
| 10 | Exact-version approval, scheduling and publication reconciliation | Fault matrix produces no unapproved external write |
| 11 | Weekly results, experiments and continuing plan cycle | Second cycle works without repeating onboarding |
| 12 | Installation, recovery, accessibility, load and demo hardening | Advertised release checklist is supported by actual evidence |

## Phase 0 acceptance criteria

- [x] Upstream Hermes commit and license are recorded.
- [x] Host and runtime compatibility is documented.
- [x] Repository, offline contracts, PostgreSQL config, and test scripts exist.
- [x] A minimal Hermes plugin returns deterministic structured JSON.
- [x] Gemini/OpenAI contract behavior is testable without live calls.
- [x] Pinned Hermes runtime prepares successfully on the target host.
- [x] Real Hermes discovers and invokes the BrandPilot plugin.
- [x] Wrong API key is rejected and the service binds only to loopback.
- [x] Two isolated runtime homes retain only their own state.
- [x] Offline gate demonstrates no external model transport.
- [x] Live selected-provider status is recorded as passed or explicitly blocked.

## Phase 1 acceptance criteria

- [x] API, web, and worker bootstraps run with offline-safe defaults.
- [x] Clean and prior-fixture database migrations reach the current schema.
- [x] PostgreSQL jobs use transactional claims, leases, checkpoints, and bounded attempts.
- [x] Two workers cannot own the same job; expired leases recover.
- [x] Restart after a checkpoint creates no duplicate local output.
- [x] Job steps and outbox events have durable dedupe constraints.
- [x] Database and storage failures produce degraded health with usable details.
- [x] Local storage rejects traversal and conflicting duplicate writes.
- [x] Logs redact credential-shaped fields and values.
- [x] Offline application boot makes no external request.
- [x] Locked dependency/license inventory and repeatable test runners exist.
- [x] React production build and responsive operations shell pass verification.

## Phase 2 acceptance criteria

- [x] Local owner setup is protected by a one-time bootstrap boundary.
- [x] Passwords use Argon2id and sessions are opaque, server-side, expiring, and revocable.
- [x] Secure/HttpOnly/SameSite cookies and per-session CSRF tokens protect mutations.
- [x] Owner, editor, and analyst permissions are enforced from current membership rows.
- [x] Revoked membership loses access immediately without waiting for session expiry.
- [x] Workspace jobs, events, assets, and credentials reject cross-workspace identifiers.
- [x] Downloads require short-lived signatures bound to user, workspace, and asset.
- [x] Credentials use AES-256-GCM with workspace/provider AAD and a stored key version.
- [x] PostgreSQL connections assume a non-owner role and workspace RLS survives pool reuse.
- [x] Job steps use a compound workspace/job foreign key.
- [x] Run credentials reject forged plugin workspace/job/operation claims.
- [x] Two similar fixture businesses retain distinct assets and encrypted credentials.
- [x] The complete Phase 2 gate preserves the Phase 0/1 test and build results.

## Phase 3 acceptance criteria

- [x] Private workspace uploads support PNG/JPEG/WebP/SVG/PDF/DOCX with safe metadata and previews.
- [x] CSV/XLSX product imports provide Arabic/English mapping previews and idempotent confirmation.
- [x] Originals remain behind private storage and repeated uploads do not create duplicate assets.
- [x] SVG, OOXML, image, PDF, MIME, size, archive-ratio, and active-content checks fail closed.
- [x] Public URL intake rejects unsafe schemes, credentials, local/private destinations, and unsafe DNS results.
- [x] Offline mode preserves the URL source as an explicit blocked import without external transport.
- [x] Adaptive onboarding persists confirmed answers, avoids repeated questions, resumes after relogin, and records contradictions.
- [x] Manual profile proposals are versioned and owner-confirmable; richer imports remain optional.
- [x] The responsive UI exposes English/Arabic direction, keyboard-accessible controls, uploads, imports, onboarding, and profile confirmation.
- [x] The complete Phase 3 gate preserves Phase 0-2 tests and the production web build.
