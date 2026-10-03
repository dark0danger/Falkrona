# Drafting and image recovery checks — 2026-10-03

The owner reported `Gemini could not draft the week: invalid_plan` for Arabic,
three posts, sales, Facebook, week starting 28 September. Both failed runs had
only confirmed brand facts, no product catalog entries and no confirmed offer.
The exact rejected rule was not persisted by the old worker, so it cannot be
retroactively attributed to one specific invalid-plan branch.

## Changes

- Gemini receives a per-request response schema with exact post count, requested
  platforms, confirmed fact keys, available post purposes and brand colors.
- Sales without catalog/offer data uses truthful brand education or conversation
  with an enquiry CTA; product/offer purposes remain unavailable without their
  source facts. Uploaded photos are not treated as catalog facts.
- The planner receives the selected Arabic/English language. The saved plan
  records it and validates actual audience-facing text against that choice.
- Remaining day/hour pairs are supplied explicitly, allowing different hours on
  the same day. A finished week is rejected before a model request.
- Invalid post counts, platforms, duplicated slots, unconfirmed facts, missing
  product/offer facts and expired offers have distinct error codes. Safe, plain
  failure explanations survive in the workspace-scoped run output.
- The existing saved plan remains intact if a new draft is rejected.
- Design-direction response schemas encode the headline/CTA word limits used by
  validation. A live Arabic CTA had exceeded the five-word limit.
- Helper 0.1.5 waits for generation to stop and image candidates to remain stable
  for six seconds. Identical source previews count as one result; genuinely
  distinct finished images still require owner selection. Recovery observes the
  same submitted conversation and never sends that request again.
- The plan refreshes each prompt's state before starting the image app, avoiding
  stale “Waiting for Gemini” cards while an image is already generating.

## Verification

The corrected live draft returned three distinct Arabic posts for the owner's
exact sales/Facebook choices. The first fresh ChatGPT request accepted all three
attachments automatically with helper 0.1.4. It produced an image; a transient
multiple-preview pause exposed the additional helper issue addressed in 0.1.5.
The installed helper folder was updated; Chrome Reload is required to activate
0.1.5 before resuming that same saved conversation.

After the owner reloaded 0.1.5, the same first conversation was observed and its
image imported without another submission. Only the failed second direction run
was replaced; it passed the schema's CTA limit. The first and third direction run
IDs were preserved.

The live three-post batch then completed. All three images, Arabic captions and
future Cairo posting times appear in Content plan, with one Approve plan & schedule
action. The owner-UI Download all posts action returned `Falkrona-week.zip`.

Automated coverage includes both languages, counts 1–5, missing catalog/offer
data, late/finished weeks, same-day slots, malformed output, unsupported platform,
wrong count, invented facts, duplicate slots, missing product/offer references,
palette changes, repeated visuals, language mismatch, CSRF/consent, owner retries,
asset isolation, completed-image replay, import binding, package export, publishing
permission revocation and durable-job recovery. The PostgreSQL checks use the
separate `brandpilot_phase_gate` database, never the application database.

No plan approval or Facebook publication was performed during these checks.

Final automated results: **228 backend tests and 96 subtests passed**, with the
isolated PostgreSQL checks enabled; **30 helper tests and 8 UI tests passed**.
Production UI build passed. The combined run also exposed and fixed test setup
that allowed the PostgreSQL environment to override SQLite migration fixtures.
Full output: `.runtime/drafting-final-all-tests.log`.
