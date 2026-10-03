# Branding and weekly reports — 1 October 2026

The owner's revised request supersedes the older BrandPilot plan. The product is
Falkrona, for Facebook and Instagram only. Branding assets come from the owner;
social connections read posts and permitted engagement, not logos or references.

## Owner flow

1. Open **Branding**. Gemini prepares four friendly questions in a single Hermes
   turn: name, what the business sells/stands for, audience, and preferred style.
   Each question includes examples. Style cards illustrate simple, playful and
   elegant approaches. Offline mode clearly labels its starter questions.
2. Upload a transparent PNG/WebP logo. The server verifies decoded transparency
   and visible artwork; an opaque or entirely invisible image is rejected.
   Optionally upload one PNG/JPG/WebP design reference. Save the four answers and
   logo together. Saving unchanged answers does not create extra profile versions.
3. Upload a real product photo in Products. In Calendar, choose the week, goal,
   platforms and post count, allow public details to go to Gemini, then click
   **Draft week**. Gemini drafts the whole plan from the confirmed business details,
   available product catalog, public post history and accepted preferences.
4. Choose the connected ChatGPT/Gemini image app and click **Generate** once.
   Gemini prepares a distinct detailed prompt for every post, receiving confirmed
   brand facts, style, ad brief, relevant product facts,
   accepted preferences and small logo/product/reference image previews before
   composition. Image metadata is stripped, previews are at most 512×512, and
   keys, social tokens and internal asset IDs are excluded. The reference guides
   composition and mood; its text and logo must not be copied. The browser helper
   attaches the role-named logo, product and optional reference, sends each prompt,
   waits for the generated image and imports it automatically. No individual draft
   review or approval is required. Finished posts and a weekly download appear in
   Calendar; Studio opens a saved result after generation.

Product photos provide product identity only, never the ad layout or background.
The selected image app creates a fresh complete composition; Falkrona imports its
pixels without adding text/logo overlays locally. The optional uploaded reference
provides style inspiration only. Completed posts survive another post's failure.
An explicit Continue generation retries a failed Gemini prompt or resumes the
original image request; a recorded submission is never automatically sent twice.
Generation does not authorize social publishing. See
[browser setup and limits](BROWSER_IMAGE_WORKFLOW.md).

Design creation, regeneration, revisions and direction requests enforce Branding
on the server. Another workspace's assets or an arbitrary old profile cannot
bypass the requirement. Brand/product/reference changes invalidate prepared
Gemini directions. Existing data is preserved; older workspaces need to finish
the new Branding setup to create further designs.

## Engagement and reports

Run the application API and one workspace worker as described in the README.
The worker ticks every minute, queues one daily post sync/engagement collection,
and prepares a report each Monday at 00:05 Cairo time, starting with the week
Branding was completed. Durable period keys and report uniqueness prevent
duplicates; completed weeks are caught up after a restart. Reports and editable
next plans appear in **Results**, with an in-app new-report badge. This is in-app
delivery, not email or social messaging. The computer/server must remain running.

Facebook Page reactions/comments and supplied shares are read with the account's
granted access. Professional Instagram accounts linked to a managed Facebook
Page can be selected through the same authorization flow (`instagram_basic` plus
the existing Page read permissions); permitted media likes/comments are recorded.
Missing shares, saves or counts are unavailable, never inferred as zero. Saved
counts are cumulative since publication and carry individual observation dates;
the report does not call them engagement earned only during the reporting week.
Older valid evidence survives a later collection failure. Rate limits and network
failures back off; disconnected accounts do not accept late writes.

An owner-supplied CSV can also include optional `likes` (or `reactions`),
`comments`, `shares`, and `saves` alongside `post_id`, `caption`, `published_at`.
Blank counts remain unavailable. Export data is labeled as owner supplied.
Automatic read collection never publishes a post or changes brand assets.

## Validation and live limits

Migration `0015_branding_setup` adds isolated branding and engagement tables with
PostgreSQL RLS and workspace-bound asset/post foreign keys. API/worker tests cover
required setup, opaque/invisible logos, cross-workspace assets, survey validation,
single-call budgets, visual context and stale references, daily counts, duplicate
ticks/restarts, CSV evidence, unavailable data, and linked Instagram read fixtures.

The offline gate passed 137 backend tests with no skips, two web tests, production
build, environment checks and dependency inventory. The real pinned Hermes loopback survey and
image-context checks are recorded in `docs/evidence/generated`. The loopback
checks make one request apiece and no external calls. Screenshots use an isolated
fixture workspace; Chrome's extension file-access setting blocked the native
upload chooser test, while the upload APIs and rendered logo were verified.

Live Gemini and Meta access still require configured credentials, granted scopes
and real-account verification. Meta documentation was unavailable to the browser
research tool during this change, so the new Instagram adapter must receive a
real-account smoke check before being described as live-verified. Live publishing,
general Hermes dispatch and Phase 12 release hardening remain separate work.
