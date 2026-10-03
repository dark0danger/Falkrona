# Account-based image workflow

Current status (3 October 2026): browser-helper development preview, version
0.1.5. The live three-post Arabic batch completed with automatic image return.
Gemini website automation remains unverified. See the [current setup guide](SETUP.md)
and [latest generation evidence](evidence/drafting-recovery-2026-10-03.md).
Later sections preserve dated implementation/verification history.
The owner's request replaces local product segmentation and composition as the
design-generation method. Existing drafts remain available.

## Owner experience

1. Complete Branding with the brand survey, transparent logo and optional design
   reference. Upload a product identity photo in Products.
2. Click Draft a plan in Content plan. Gemini drafts the weekly Facebook plan
   from confirmed business context and the selected Arabic/English language.
   The live draft flow starts distinct detailed prompts and image generation
   automatically; saved interrupted batches offer Continue creating designs.
3. Choose Gemini or ChatGPT. Review permission to send this prompt and these assets
   to the selected service. The user signs in directly to that service.
4. A browser helper starts a fresh conversation, attaches the images with explicit
   roles and submits the prepared generation request. It waits for a generated
   image and returns it to the matching Falkrona draft.
5. Every completed post appears in Calendar automatically, with a download for
   the whole week. Studio can open a finished result. Generation has no individual
   design approval gate and does not authorize publishing to social platforms.

The owner sees account connection, generation status and the resulting draft.
Technical geometry, masking and model parameters stay out of the owner flow.

## Prompt and asset contract

Weekly planning fixes a distinct visual concept for each post before product
vision: route, scene, camera, composition and visual hook. The campaign repeats
palette, typography, logo treatment and image character, while the actual scene
and spatial composition vary. Each direction knows the other posts' assignments.
Product vision records identity separately from source-scene elements to discard.
The browser prompt reinforces those exclusions and the assigned composition.
Changing only headline/CTA is rejected as a duplicate prompt. Validation cannot
guarantee the image app follows the prompt; actual artwork still needs visual QA.

- Logo: preserve the uploaded brand logo and its spelling; never borrow a logo
  from the optional reference.
- Product: identity evidence for shape, packaging, materials and label. Never use
  its original photograph as the final ad background or as styling inspiration.
- Reference: optional visual style/composition inspiration only. Do not copy its
  brand, claims, text or product.
- Request a fresh, complete Facebook/Instagram design in 4:5, with exact approved
  headline/CTA, correct audience language and truthful product details. The image
  app generates the composition; Falkrona does not reconstruct it locally.
- Bind the prompt and returned image to the current workspace, draft, confirmed
  facts and input asset hashes. Changed facts require a new direction.

## Browser helper boundary

A normal hosted webpage cannot operate a user's tabs on other domains. Automatic
upload/submission/return requires a browser extension or local companion running
on the user's device. The Codex browser tools in this development chat do not
automatically become capabilities of Falkrona.

Keep the user's sign-in session on their device. Do not collect passwords, copy
browser cookies into Falkrona or claim a connection works before verifying it.
Require explicit permission for the selected provider and attached brand assets.
Use a fresh conversation and act only on that generation request. Pause for
login, verification, account limits or ambiguous page state. Never repeat an
uncertain submission automatically. Provide a prompt/assets download and manual
image import when automatic generation cannot complete.

Website UI changes can break the helper, so this is a supervised integration.
Live verification with the selected signed-in account is required before claiming
that automatic attachments, submission and full-resolution image return work.

## Supported-service findings (1 October 2026)

Gemini Apps supports generating images from multiple uploaded images and
downloading the generated result. This establishes the interactive capability,
not an API for delegating the Gemini website to Falkrona:
https://support.google.com/gemini/answer/14286560?hl=en

ChatGPT supports image generation/editing with uploaded references:
https://learn.chatgpt.com/docs/image-generation

Sign in with ChatGPT supports eligible account-based Responses API requests, but
its current preview explicitly excludes image generation. It cannot supply the
image-generation connection requested here:
https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations

## First implementation choice

The browser-helper version automates the selected website after the user installs
and authorizes the helper. A no-install handoff version prepares the same prompt
and assets, opens the selected service, and lets the user upload the finished
image. Both preserve the input roles and skip local design generation.

## Implementation and current verification

The creative worker now performs one Gemini planning call (pipeline 4) and stops
at `awaiting_image_app`. It never calls local segmentation/composition. The browser
packet includes explicit role-named attachments, the complete prompt, selected
provider consent and a 30-minute, user/workspace/run-bound import nonce. Originals
stay in Falkrona; exported attachments strip metadata and are bounded to 2048px.

`apps/browser-helper` is a Chrome/Edge Manifest V3 extension. Load that folder with
Load unpacked for local testing, or download the ZIP through Studio. Connect from
the active Falkrona tab and sign in directly to the selected image app. Optional
host access is requested only for that Falkrona origin and the selected service.
No account credentials, cookie permission, image API, or publishing access.
Disconnect removes those grants and stops helper work. A changed tunnel URL needs
reconnection; marketplace distribution remains future work.

The normal path is Content plan Draft a plan → Gemini weekly plan → Gemini
prompts for all posts → helper attachment/submission → automatic import/download.
On interrupted/uncertain requests the helper
never automatically resends. A saved direction can be reopened without another
planning call. Manual recovery exposes the prompt, role-named files and image import.
An import validates raster type, size, single frame and 4:5 ratio; it normalizes
output to 1080x1350 without adding visible copy/logo layers. Replay is idempotent;
changed facts, a wrong workspace/provider/nonce or an expired handoff are rejected.

Adapters currently read the visible generated-image URL, which may be a preview
rather than the website's full-resolution download. The website must expose
recognized composer/attachment/response controls; otherwise the helper pauses.
The owner's signed-in ChatGPT account was exercised with three role-named images.
Both requests were submitted by the helper and generated images. The first image
returned automatically to Calendar and its 1080x1350 post package was downloaded.
Recovery of the second finished image is being verified after fixing upload
hydration, stale ChatGPT views and expired import-window reuse. Helper 0.1.2 can
observe a fresh view of the exact same conversation once, without sending again.
The weekly UI can recover an explicit CSRF rejection after another Falkrona tab
rotates the session token; other errors never trigger mutation retries.
Do not claim that installing the helper verifies an account by itself.

Validation: 149 backend tests including PostgreSQL, two web tests, five helper
tests, production build and dependency inventory passed. A pinned-Hermes fixture
verified one planning call with native image context and zero external calls.
Studio's create and refresh/recovery flows were checked through the actual React
component in an isolated sample-data browser preview. Evidence:
`evidence/generated/browser-image-workflow.json` and `browser-image-workflow.jpg`.
Explicit user resume can restart a known pre-submission login/upload pause. An
attempt marked submitted is never resent, including after interruption.

## ChatGPT send/recovery correction — 2026-10-01

Helper 0.1.1 tolerates rich-editor paragraph/NBSP spacing while requiring the full
prompt, clicks the unique enabled Send control inside the composer, and recognizes
the current ChatGPT message headings. It confirms all attachments before a send,
and accepts generated pixels only after the matching full request appears in the
transcript. Resume observes an already submitted request in its original tab.
If extension reload loses job tracking, resume pauses for manual import rather
than creating another request. Studio rejects the older helper before starting.

Setup, prompt/download instructions and manual recovery are collapsed in Studio.
Saved-request recovery can open the import controls without starting the helper.
To update, replace the files in the installed unpacked folder, Reload the helper
in Chrome/Edge Extensions, then refresh Falkrona. Website adapters remain a preview.

Verification for this correction: 13 helper tests, production build and the
targeted API import/ZIP regression passed. A signed-in ChatGPT DOM was inspected;
the owner's existing finished image was downloaded through its visible Download
control and matched to the saved prompt. This was not a live fixed-helper run.
Live automatic generation/return still requires reloading the installed helper.
Browser control blocks extension-settings pages, and its upload operation requires
file-URL access, so extension reload and import of that existing result were left
for the owner. The API restarted successfully; the public tunnel was preserved.
