# Gemini weekly generation — 1 October 2026

The revised owner flow is Calendar Draft week → Gemini weekly plan → Generate
once → Gemini prompt for each post → selected image-app browser helper → automatic
image import and weekly download. No individual draft-design approval is required.
Generation does not authorize social publication. Existing branding, product
identity/reference separation and weekly engagement reporting are preserved.

Implemented durable `planning.week` jobs, strict structured plan validation,
workspace/context-bound batch generation and independently saved outputs. Explicit
owner retries create a new Gemini request only for failed/cancelled work; pending
requests and completed posts are reused. Live planning has no template fallback.
Offline-test planning remains deterministic for existing fixture suites.

Helper 0.1.2 preserves submission metadata across extension reload without storing
prompts or image bytes persistently. It resumes the exact bound conversation when
available and pauses if a closed submitted tab cannot be identified. It does not
repeat an uncertain Send. Both project helper copies and the downloadable ZIP were
updated; the running Chrome copy must be loaded from the updated folder.

Verification:

- Six isolated weekly integration tests passed: Gemini/free-mode planning, source
  validation, stale context, whole-week generation/import/replay/package, foreign
  photo rejection and explicit retry behavior.
- Sixteen related Gemini direction/planning tests passed.
- Seven durable job and agent API tests passed.
- Twenty-two helper DOM/background tests passed, including bridge restoration
  using existing permissions, reload/closed-tab recovery, hydrated upload controls,
  one fresh observer of a stale ChatGPT conversation, full prompt/attachment binding,
  renewed import windows and single submission.
- Five web tests passed, including CSRF recovery that retries only an explicit
  rejection before API execution, preserving the same image payload.
- TypeScript/Vite production build passed. API and worker restarted; readiness
  reports database and storage healthy. No application data reset or migration.

Live account test: Gemini drafted two Facebook posts for Tepes and Calendar
displayed “Planned by Gemini”. Both detailed Gemini prompts completed. The helper
attached all three role-named images and submitted each to signed-in ChatGPT.
The first generated image returned automatically and its post ZIP was downloaded
and verified at 1080x1350. The second generated image is finished in ChatGPT;
automatic recovery/import is pending activation of the final recovery fixes.

Initial live issues reproduced and corrected: wrong unpacked helper folder, bridge
registration lost on reload, rich-text matching, first-upload hydration replacement,
overlong Gemini CTA, ChatGPT's stale 99% response, expired import-window reuse and
CSRF invalidation by a second Falkrona tab. The actual installed sibling folder
`C:\Users\Admin\Downloads\Projects\Falkrona-Browser-Helper`, runtime extracted copy
and downloadable ZIP contain the tested 0.1.2 code. Updated adapter code requires
Chrome's Reload control to activate.

Facebook “Check posts now” completed successfully. Engagement snapshots on
1 October record permission_missing: current Page access rejects reactions and
comments, while shares remain unknown. Null metrics are not recorded as zero.
No social post was published. Instagram account testing is deferred by the owner.

Screenshot: `.runtime/weekly-helper-check.jpg` (local ignored runtime evidence).
First returned image: `.runtime/weekly-first-image.jpg`.
Test logs: `.runtime/weekly-tests.log`, `.runtime/weekly-related-tests.log`,
`.runtime/weekly-worker-tests.log`.
