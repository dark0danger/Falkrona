# Phase 08 Evidence

Status: technical implementation in progress; human design gate pending.
Mode: `offline_test`. No external image/model request or social publishing call was made.

## Implemented

- Versioned workspace-scoped scenes with PostgreSQL RLS, compound plan/artifact
  ownership, source brief references, and recoverable stale-edit conflicts.
- A Calendar-to-Studio path with text, caption, geometry, color, layout, asset,
  carousel-order, revision history, and local undo controls.
- Browser-shaped SVG preview and exact-pixel PNG export, including Arabic and
  bilingual text. Private logo/product images are referenced by original asset hash
  and embedded locally at export; no image-generation API is required.
- Six size presets, reference palette analysis without source copy or logo transfer,
  text-fit blocking, contrast checks, and a ZIP containing ordered PNG/JPEG slides,
  editable scene JSON, caption, alt-text draft, and a hash manifest.

## Verification

- `uv run python scripts/phase_gate.py --phase 8 --offline`: automated steps passed.
- 104 backend tests passed, including 10 real PostgreSQL checks; 2 web tests and
  the production Vite build passed. Migration `0010_phase8_creative_studio` was
  applied to the local application database.
- The isolated browser fixture page rendered 30 actual PNG blobs: 5 text cases
  (English, Arabic, bilingual, long copy, Arabic/English numbers) across all 6
  presets, using 3 fixture logos. Each result had the expected dimensions and a
  SHA-256 digest, and the browser text-fit check found no overflow. This was a
  browser smoke run, separate from the automated gate.
- An isolated owner workflow created a brief-linked scene, saved a bilingual edit,
  and exported a real 1080x1350 PNG. Visual inspection confirmed connected Arabic
  glyphs and separated Arabic/English lines. Representative originals:
  [English PNG](generated/phase-08-english.png),
  [bilingual PNG](generated/phase-08-bilingual.png).
- API tests proved immutable revision/restore, CSRF, stale revision rejection,
  wrong dimensions and forged asset hash rejection, cross-workspace denial,
  package caption/scene correspondence, and ordered PNG/JPEG filenames.
- [Generated gate report](generated/phase-08.json) records the automated results.

## Open Gate Items

- The owner rejected the representative exports as inadequate social designs.
  The current `starter_scene` uses fixed colors and prints brief instructions as
  artwork copy; it does not invoke Hermes. The new
  [social design skill](../../infra/hermes/skills/social-media-graphic-design/SKILL.md)
  captures the owner's strict design rules, including 1080x1350-only final artwork.
  The Studio's new regenerate action reads the skill's shared design policy,
  extracts colors from the selected workspace logo, requires a workspace photo,
  uses short audience-language copy, and creates a new 4:5 scene revision.
  The first-create UI immediately applies this guided revision. The earlier
  fixed-layout draft remains in history for compatibility.
  On 2026-09-29, the pinned Hermes interpreter successfully discovered the skill
  and loaded its complete content through `skill_view` in the Phase 4 runtime
  home. Installation copies were hash-checked; no model/provider call was made.
- New Nile Coffee fixture [English](generated/phase-08-nile-coffee-review-v2.png)
  and [Arabic](generated/phase-08-nile-coffee-review-v2-ar.png) PNGs were exported
  at 1080x1350 and visually inspected, including connected Arabic glyphs and
  right-side logo anchoring. They use an assistant-generated
  sample photograph and a fictional sample logo; neither represents an owner's
  real product or approved brand assets. The review page is available locally at
  `/studio-review.html` on the Vite dev server. This artifact is for feedback,
  not publication.
- The focused Studio tests passed (6 tests plus 30 subtests), including a real
  regenerate API path with CSRF, immutable history, logo colors, RTL anchoring,
  and workspace image hashes. The web production build passed. The full Phase 8
  automated gate passed again on 2026-09-29; human design sign-off remains open.
- Hermes currently supplies the skill and shared policy, but no live creative
  model composed this PNG. The local Studio renderer made it from the scene and
  sample assets. A real workspace design requires its own uploaded logo and photo.
- David has not scored the 30 designs against composition, hierarchy, typography,
  brand fit, and product truthfulness. The required 80% at 4/5 per dimension is
  therefore **not passed**. The two original exports and two guided fixture
  exports were visually inspected.
- The renderer uses locally available Arial rather than a bundled redistributable
  font. Font availability and Arabic shaping need review on each target machine.
- The server validates PNG format, dimensions, and hashes, but currently accepts
  browser-submitted pixels without independently verifying that they match the
  stored scene. Exports are drafts, not approved/publishable artifacts.
- Crop/masking, line/group scene layers, and optional paid image adapters remain
  outside this implementation. Logo/product layers use `contain` only, keeping
  originals intact. Factual copy edits are flagged for owner review.

Gate decision: automated checks passed; Phase 8 remains open for renderer hardening
and human review. Phase 9 has not started.

## TepeS review retry (2026-09-29)

- The owner rejected the Nile Coffee fixture as unrelated to the connected TepeS
  Facebook Page and supplied a product-ad reference. The TepeS Page profile image
  was fetched by its recorded Page ID and used as the real logo source. It is only
  200x200 pixels; the TepeS workspace has no uploaded image assets or confirmed
  brand profile yet.
- The owner specified an unbranded juice bottle. An illustrative bottle photograph
  was generated for this review only. It is not a verified TepeS product or
  packaging and was not added to the owner's workspace.
- The [TepeS review PNG](generated/phase-08-tepes-review-v3-ar.png) uses that bottle,
  the Page profile image, Arabic copy on the photograph, an upper-left logo per
  the supplied reference, and a 1080x1350 canvas. The file was inspected after a
  headless browser capture; the logo, text, and product are present in the pixels.
- Updated the Hermes skill with brand/account identity checks, product-image
  questions and generation rules, reference-based alignment, and a requirement to
  keep illustrative packaging in draft. Updated its local install and verified
  file hashes. The Studio now asks owners to confirm the selected product image
  and whether the logo already includes the brand name; the API enforces the
  product confirmation and a current confirmed brand profile.
- The real Page JPEG initially failed logo color extraction. Quantized palette
  analysis now resolves dark teal, white, and green from it. The guided scene uses
  a full-bleed product image with the text above the product rather than a
  detached bottom band.
- `scripts/phase_gate.py --phase 8 --offline` passed again: 106 backend tests,
  2 web tests, and the production build. Human design approval remains pending.
  The app has no automatic image-generation provider; without an approved product
  image it keeps a draft and asks for a description/upload. Hermes itself did not
  generate this PNG; the built-in image tool made the illustrative bottle and the
  local renderer placed the exact Page logo and copy.
