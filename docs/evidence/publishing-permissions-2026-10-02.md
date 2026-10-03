# Facebook publishing and permission check — 2 October 2026

## Follow-up after Meta dashboard permission change

A read-only recheck at 18:15 UTC still showed only public_profile,
pages_show_list and pages_read_engagement on the existing token. The app now
offers explicit Allow publishing access consent for pages_manage_posts;
standard Facebook tracking consent stays read-only. No new scope is silently
requested. The owner completed consent and Page selection. The 18:36 UTC
read-only check verified pages_manage_posts in both saved/current grants, managed
TepeS Page access, CREATE_CONTENT/MANAGE tasks and working post reads. Engagement
still returns permission_missing. Evidence is saved in
.runtime/meta-permissions-after-consent-2026-10-02.json. No Page post was sent.

The requested fresh-workspace reset removed nine plans, 20 design versions,
one render record and five generated image asset records. Original uploaded
assets, brand tables and social data passed unchanged fingerprint verification.
Usage histories remain; creative dedupe keys were archived. Physical image files
were retained. Recoverable pre-change row snapshots are:

- .runtime/creative-reset-backup-5c8dbc12-42c1-4343-9257-9d1925d93d51.json
- .runtime/creative-reset-backup-1e660d1b-66df-495a-a7b8-15ef9bcb55d4.json

The first snapshot contains removed plans/designs/external image records;
the second contains the two old local-composition assets. To restore, use an
application-role transaction scoped to this workspace, restoring dependent
rows in foreign-key order and resolving dedupe keys against any new runs.
Do not overwrite newly created plans or current OAuth connections.

21 OAuth/transport tests and 12 subtests passed, and the frontend build passed.
The restarted API readiness endpoint returned 200. Live publishing remains
unimplemented and disabled independently of a future granted write scope.

The owner reconnected TepeS and requested a publishing/permission review and
separate Facebook and Instagram connection buttons. Instagram live setup/testing
remains deferred. No new scopes were requested and no remote writes were made.

## Live evidence

`scripts/check_meta_permissions.py` checked the existing encrypted server-side
credentials against Meta Graph v26.0 using GET requests. It used the application
database role, an exact workspace filter/RLS context and a read-only transaction.
Output includes no tokens or secrets. Evidence is saved locally at
`.runtime/meta-permissions-check-2026-10-02.json`.

- Current grants match the saved grants: `public_profile`, `pages_show_list`,
  `pages_read_engagement`.
- The selected TepeS Page remains managed, with `CREATE_CONTENT` and `MANAGE`
  among its task grants. Page post reading passed.
- `pages_manage_posts` is absent. Permission to manage the Page is distinct from
  the app token's authority to write posts.
- Reading engagement for an existing imported post returned `permission_missing`.
  No zero counts were substituted and no new measurement was saved.
- Falkrona's `upload` and `publish` capabilities remain disabled.

## Phase 10 review

PublicationService still creates `delivery_mode: manual` and `manual_ready`
attempts. The worker has no publication dispatch and MetaGraphTransport has no
photo/post publishing method. Weekly Gemini plans explicitly select `manual_only`.
The remote transition/reconciliation helpers are contracts, not a live connector.
The latest generated images were accepted by the owner, but live scheduling and
publication are not complete. Manual packages do not claim a published post.

Live publication requires a Page write grant, a verified publishing adapter,
scheduled delivery and recovery/reconciliation of uncertain remote outcomes. An
actual publication test must specify the exact design/caption and destination.

## UI and validation

Each platform now has its own connection button and card. Facebook opens the
existing Facebook-only consent flow. Instagram's button is disabled with a short
setup-pending message; it cannot launch a misleading Facebook-only consent flow.
Facebook account choices exclude linked Instagram choices. Connected accounts
show a short, accurate tracking/publishing status.

Existing publishing, schedule, Meta authorization and transport checks passed:
27 tests plus 21 subtests. A further targeted test verifies that even an existing
write grant cannot turn the unimplemented upload/publisher into an available
capability. The frontend production build passed. Desktop/mobile UI proof is
saved at `.runtime/falkrona-separate-social-buttons.jpg`.
