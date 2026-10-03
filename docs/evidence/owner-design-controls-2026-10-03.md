# Asset purposes, deletion and single-post regeneration

Uploads retain a purpose in existing asset metadata. Product and Branding uploads
deduplicate within their purpose, so the same bytes uploaded as a reference cannot
silently become a product. Historic logo verification, Branding choices and agent
attachment roles classify earlier uploads. Owner workspace gallery review also
identified four complete ENEA/GlobalView ads uploaded through the old product box;
these were moved to references with metadata backed up in `.runtime`.

The gallery groups product photos, logos, design references and documents. All
three product pickers require the product purpose. In the live owner workspace,
only `pngwing.com.png` and `product.png` appear in the product picker; five
references and one logo are separated.

Delete plan and Delete design archive the selected plan/post, keeping source
assets and artwork revisions available for Undo. The latest deleted plan does not
expose an older revision as the active plan. Recovery remains visible after a
refresh. Removed posts do not appear in the studio or downloadable week; the
remaining complete designs can be reviewed and approved. Empty plans cannot be
published. Deleting a plan cancels queued creative briefs and rejects late image
handoffs. Scheduled/approved content cannot be edited through these controls.

Regenerate reserves a new revision of one post, assigns a route unused by the
current week before product vision, changes camera/composition, and lets Gemini
write a new design direction. Previous concepts and prompts are supplied only as
ideas to avoid. Repeated prompts are rejected before image handoff. Other saved
posts and earlier artwork revisions are preserved. An expected revision protects
against duplicate clicks; a reserved request can be resumed after interruption.

A CTA treatment is saved with the shared brand identity and reused across weeks:
bottom-center rounded rectangle, fixed 1080x1350 box, solid brand fill, contrasting
text, campaign font/Arabic companion, 32px bold centered lettering. Both Gemini
direction and image-app handoff repeat the exact contract. Scene/copy variation
cannot override it. Hermes's creative skill was updated and installed in the
project runtime. Existing pixels are not retrospectively redrawn; this treatment
applies to newly generated and regenerated artwork. Actual rendering remains the
image app's responsibility; no new external image was generated during this task.

Validation: final complete suite **241 tests and 96 subtests passed**, using the
separate `brandpilot_phase_gate` PostgreSQL database; **8 UI tests passed** and
production UI build succeeded. New integration scenarios cover role history,
same-file/different-purpose uploads, reference rejection, removal/package/Undo,
empty-plan blocking, cancelled briefs, studio visibility, restoration order,
single-post regeneration, rejected-idea repetition, CTA/language preservation,
duplicate clicks, approved-plan protection, CSRF and workspace scoping.

Live browser review confirmed two product choices, separate reference/logo groups,
three enabled Regenerate/Delete action pairs and Delete plan. No console warnings
or errors were observed. No owner design was regenerated/deleted or published in
the live workspace during validation. API and creative worker are running on the
same public tunnel address; helper files/version did not require another reload.
