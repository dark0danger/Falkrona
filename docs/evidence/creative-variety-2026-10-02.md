# Distinct concepts with consistent branding — 2 October 2026

The owner identified that two Tepes ads repeated the product photograph's bottle,
fruit arrangement, wooden surface and leafy background while changing the copy.
The ENEA examples illustrate the desired principle: consistent palette/type and
visual character with different scenes, focal subjects and compositions.

The previous per-post requests did not share a campaign visual plan. The skill
also repeated literal reference alignment and layout conventions too rigidly.

Implemented:

- Gemini chooses a shared campaign typography/art direction and each post's
  distinct visual route, scene, camera, composition and visual hook during weekly
  planning, before product vision. The brand treatment carries into later weeks
  under the same confirmed profile.
- Each direction sees the selected concept and the other posts' assignments.
  Product observations separate physical packaging/label identity from an explicit
  source-scene exclusion list. Reference character is separate from literal layout.
- The image-app request includes the shared brand treatment, assigned composition,
  source-scene exclusions and the other compositions to avoid. It forbids using
  the original photograph with changed text.
- Validation rejects repeated visual routes, insufficient camera/composition
  variation, near-identical scenes, copy-only prompt variation and absent product
  observations. These checks do not substitute for reviewing actual output pixels.
- Weekly planning receives the exact logo-derived palette and validates the
  campaign palette and every designed backdrop color. Transparent logos may add
  neutral white/black for contrast; they no longer acquire Falkrona's default ink.
- Old plans require a fresh visual plan; prior successful artwork remains saved.
  The owner still uses Draft week and one Generate action, with no additional
  creative controls or individual approval gates.
- Hermes skill and policy updated and installed. Direction pipeline is version 5;
  historic output remains readable. No local renderer or image API was introduced.

Verification: 28 targeted backend tests (plus 20 subtests) passed, including batch import/replay/ZIP,
product-only observation, prompt-variety rejection, later-week identity inheritance,
old-plan handling, exact palette enforcement, transparent-logo color fidelity,
source staleness, workspace boundaries and no local rendering.
TypeScript/Vite production build passed. API/worker restarted healthy.

The final live plan and both product-only directions completed with the actual
Tepes palette (#004c58, #ffffff, #258f45) and shared Montserrat typography.
The first image-app attempt stopped before Send because ChatGPT's new three-input
composer placed a video picker before the ordinary file attachment input.
Helper 0.1.3 selects the explicitly named Attach files/Attach photos input instead
of document order. A second live fresh-tab attempt exposed an input that stayed
mounted but silently reset its files before hydration accepted the upload. Its
single bounded retry now also covers that confirmed empty, unsent case; partial
uploads, changed composers and submitted requests cannot trigger it.
All 25 helper tests passed, including the three-input, reset-input and partial-upload
regressions and existing no-duplicate-submission/reload checks. The updated helper
is copied to the owner's installed folder and the downloadable zip; activation
requires the owner to reload the extension. The focused image-packet test also
passed after adding prominent packaged-product identity to human-moment concepts.
Calendar and Studio accept compatible 0.1.x patch releases from 0.1.3 onward rather
than rejecting every version except 0.1.2. The production build passed again.
The first finished image automatically imported as an external-generation asset
at 1080x1350. Pixel review confirmed a new white overhead fruit/bottle arrangement,
teal type and Tepes logo, with no source wooden table or leafy backdrop.
The second finished image also automatically imported at 1080x1350. It uses a
human enjoying juice, the actual packaged bottle prominently in the foreground,
and a teal background with white bold typography. The two actual scenes differ
while retaining shared palette/type character. Both bound ChatGPT conversations
contained one submitted request; interrupted pre-upload attempts were never sent.

The first caption invented organic farming/sourcing-standard claims beyond the
owner's supplied facts. It was corrected through Studio's normal Save changes
flow. This revealed that the weekly ZIP previously read the initial import's
caption rather than its saved revision. The package now uses the latest saved
revision only when its generated-image ID matches that package entry. The added
integration regression passed, retaining the other post's caption and all five
ZIP entries. The API was restarted with this fix after image generation finished.

The owner's actual Download all posts action saved
`C:\Users\Admin\Downloads\Falkrona-week.zip`. Inspection confirmed two 1080x1350
PNGs, two captions, a two-post schedule, and the corrected first caption.
Calendar shows both posts Ready and the weekly Download all posts action.
Proof: `.runtime/tepes-distinct-week-ready.jpg`; actual artwork copies:
`.runtime/tepes-distinct-design-1.png` and `.runtime/tepes-distinct-design-2.png`.

Live verification completed. The old Cloudflare tunnel expired with
“Unauthorized: Tunnel not found”. A replacement tunnel to the same frontend is
reachable at https://approach-william-whose-girlfriend.trycloudflare.com/.
The Meta callback was updated to that origin and the owner saved its exact
callback in Meta. The new preview is signed in; image-helper connection and
actual output comparison passed. A live Gemini smoke confirmed
distinct human-moment and overhead concepts, then exposed palette drift; the final
palette-enforced live owner-flow test produced and imported both distinct images.
No Facebook post was published, and Instagram remains deferred.
