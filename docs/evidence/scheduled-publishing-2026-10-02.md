# Scheduled Facebook publishing — 2 October 2026

The workflow is Draft a plan → automatically generate all designs → review
artwork/captions/Page/Cairo times → Approve plan & schedule. The approval API
requires owner publish permission, CSRF and the reviewed exact design IDs.
Approval, plan/item approval, immutable content snapshots, attempt records and
due-time jobs commit together. Failed validation rolls the entire operation back.

The Meta adapter uploads PNG bytes as an unpublished photo, checkpoints its ID,
then publishes it through the Page feed with the approved caption. Secrets stay
in Authorization headers. Fixed Graph-host calls reject redirects and malformed
IDs. Implementation references Meta's official generated SDK contracts for
[Page photo/feed methods](https://github.com/facebook/facebook-python-business-sdk/blob/main/facebook_business/adobjects/page.py)
and [photo page_story_id](https://github.com/facebook/facebook-python-business-sdk/blob/main/facebook_business/adobjects/photo.py).

The worker checks exact content hashes, current owner membership, grant and Page
content tasks before writes. It persists uploading/publishing states before
requests and persists remote IDs afterward. Restart after an uncertain upload
requires attention; uncertain publication reads the saved photo's Page story and
verifies Page and caption. An absent/unconfirmed story is never republished.
Lost job completion after a saved post checkpoint also does not resend.

Publications use their scheduled UTC instants derived from Cairo, with DST fold
validation. They cannot run early. Slots over 15 minutes late stop for review;
they are not silently sent after long downtime. One publishing-only worker can
run alongside the main model worker. The host/workers must remain available.
Cancelling a plan stops its unsent jobs; it never deletes or mislabels a sent post.

Validation (fake transport, no Facebook writes):

- 24 integration cases cover atomic whole-plan scheduling, idempotency, early
  claims, exact bytes/caption, failed-approval rollback, CSRF, owner/tenant checks,
  removal of access, past slots, cancellation, every crash checkpoint and uncertain
  remote response recovery.
- Approval renews insufficient token lifetime through Meta's exchange endpoint,
  re-encrypts the same authorized User/Page credential pair, and refuses to queue
  posts beyond the provider-confirmed lifetime. Unknown lifetime stays bounded
  to 24 hours. Tests verify successful renewal and full rollback when too short.
- Added transport cases verify multipart upload, published=false, UTF-8 Arabic,
  attachment IDs, token handling and exact Page/caption reconciliation.
- Relevant planning, generation, OAuth, existing publication, jobs and weekly
  result suites passed. Frontend production build passed; live API ready is 200.

Real drafting is being checked in the owner's Chrome session. The initial Gemini
plan succeeded, but helper connection to the current Falkrona origin needs owner
reconnection before the image test can continue. No live post was approved or sent.
First actual Facebook publication verification therefore remains pending the
owner's explicit plan approval.
