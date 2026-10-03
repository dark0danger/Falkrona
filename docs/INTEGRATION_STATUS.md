# Integration Status

| Integration | Capability | Status | Evidence |
| --- | --- | --- | --- |
| Hermes | Source pin | passed | Exact upstream SHA resolved and checked out |
| Hermes | Durable creative-direction worker | passed_offline | Actual pinned AIAgent subprocess, isolated home, one loopback model request; creative worker contracts passed |
| Hermes | General agent job worker dispatch | unavailable | Existing gateway/plugin proof does not supply normal `agent.hermes` worker execution |
| Gemini | Creative direction and snapshot binding | passed_offline | Public/private admission, budgets, stale facts, structured output and local composition/export tests |
| Gemini | Live weekly planning | passed_live | Owner account: two Facebook posts drafted for Tepes, Calendar displays Planned by Gemini |
| Gemini | Weekly image prompts and batch import | passed_live_partial | Both prompts prepared; two helper-submitted ChatGPT images generated, first automatically imported; second recovery under verification |
| Browser helper | Reload/upload/image recovery | passed_offline | 22 regressions; exact-conversation observation, no duplicate Send, refreshed import window |
| Meta Pages | Engagement metrics | blocked_permission | Live snapshots permission_missing; reactions/comments denied, shares unknown; no invented zero counts |
| Weekly results | Owner-triggered report/next-plan cycle | passed_offline | Two cycles, duplicates, late sources, uncertainty, editable next plans and PostgreSQL RLS |
| Meta | Live publication/scheduler | blocked | No verified write adapter, media delivery or owner-approved remote publication |
| Hermes | Plugin discovery and tool loop | passed | Three real tool round trips, including restart |
| Hermes | Private authenticated API | passed | 401/401/200 auth matrix; completed run events and usage |
| Gemini | Contract policy | passed_offline | Unit contract tests |
| Gemini | Live model | configured | Live free-mode weekly planning verified; no paid image API used |
| OpenAI | Contract policy | passed_offline | Unit contract tests |
| OpenAI | Live model | blocked_cost_policy | Paid calls disabled by default |
| PostgreSQL | Compose configuration | passed | Docker Compose parse; loopback-only port |
| PostgreSQL | Running durable service | passed | Container healthy; Alembic head and concurrency tests passed |
| Application API | Health/status/jobs | passed | FastAPI integration tests and live readiness check |
| Application worker | Lease/restart recovery | passed | PostgreSQL claim, expiry, checkpoint, and dedupe tests |
| Local storage | Private artifact output | passed | Traversal/conflict/idempotency and degraded-health tests |
| Application security | Sessions and CSRF | passed | Argon2id, server sessions, secure cookies, expiry, revocation and rate-limit tests |
| Application security | Workspace authorization | passed | Cross-ID, role, revocation, scoped download and plugin-forgery tests |
| PostgreSQL | Workspace RLS | passed | Non-owner application role tested across one reused pooled connection |
| Credential storage | Encryption at rest | passed | AES-256-GCM workspace-bound round trip; plaintext absent from rows/API output |
| Web | Operations shell | passed | Vitest, production build, desktop/mobile inspection |
| Application API | Phase 3 assets/imports/onboarding | passed_offline | Security fixtures, API tests, private storage and migration tests |
| Website intake | Public URL policy | blocked_offline | Local/private/unsafe destinations rejected; external fetch disabled in offline mode |
| Social platforms | Active integration scope | scoped | Facebook Pages and Instagram only; active Studio formats also restricted |
| Meta Pages | OAuth and Page selection | passed_live | Real v26.0 callback, managed TepeS Page selected, identity and account list verified; tokens remain server-side |
| Meta Pages | Post read and paginated sync | passed_live | TepeS v26.0 read: two completed sync jobs, one page each, two distinct imported posts; checkpoint/retry/idempotency fixtures passed |
| Social platforms | Manual post CSV import/export | passed_offline | Arabic/English preview, private source, idempotent confirmation, scoped spreadsheet-safe CSV export |
| Instagram | OAuth and read capabilities | planned | Facebook Pages is verified; Instagram authorization and capability probes remain to be implemented |
| LinkedIn, TikTok, Pinterest, YouTube, X, WhatsApp | Live adapters | future | Deferred by the user-approved scope update |
