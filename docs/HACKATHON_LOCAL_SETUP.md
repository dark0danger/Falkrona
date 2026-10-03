# Local judging walkthrough

[← Falkrona README](../README.md) · [Complete setup](SETUP.md)

Falkrona is submitted as a runnable repository. There is no permanent hosted demo, and a judge’s local run does not need the submitter’s laptop online. The supported setup uses Windows/PowerShell, Python 3.13, Node 24/npm 11, PostgreSQL, a separate pinned Hermes runtime, and Chrome/Edge.

## Set up once

Follow [steps 1–7 of the complete guide](SETUP.md#1-prerequisites). The guide includes official download links and copyable commands. The included `scripts/local_setup.py` generates fresh local secrets, selects the prepared Hermes interpreter, and configures the new workspace without printing credentials.

For **real agent planning and design generation**, use your own Gemini API key/project and a signed-in ChatGPT account with [Browser Helper setup](SETUP.md#8-connect-the-browser-helper). Gemini website generation remains unverified. `offline_test` uses preview/fixture behavior; it is not evidence of live agent planning.

A fresh dependency/runtime installation can take longer than five minutes. After preparation, the following is a focused evaluation route, rather than a guaranteed total run-time limit; image generation depends on the external service.

## Evaluate the owner workflow

1. **Branding:** answer the short survey and upload a transparent logo. Optionally supply one style reference.
2. **Products:** upload a product identity photo and factual product details. The photo’s background is not a design reference.
3. **Content plan:** choose Arabic or English and one future post, consent to sharing the selected public brand inputs, then click **Draft a plan**.
4. **Agent work:** watch the weekly plan, per-post design direction, browser attachment/submission, and returned design. There is no per-design approval before generation.
5. **Control:** inspect the caption/artwork, regenerate an alternative, and change its future Cairo posting time. Try a small multi-post batch to inspect distinct ideas and consistent brand/CTA treatment.
6. **Approval:** the whole plan has one approval-and-schedule action for Facebook. Actual delivery requires [Meta configuration and granted Page publishing access](SETUP.md#10-facebook-and-meta-setup); drafting alone does not publish.
7. **Results:** inspect the weekly reporting flow. Real metrics require the authorized connection and sufficient platform data/time; missing history is not a measured performance improvement.

## Facebook publishing is a separate prerequisite

A judge may use an eligible Page they manage with a configured Meta app. With an unreviewed development app, ordinary external accounts may be unable to grant the required permissions until app-role/access requirements are met. Creating a permission request is not approval. The [Meta guide](SETUP.md#10-facebook-and-meta-setup) covers roles, consent, the exact HTTPS callback, and a read-only capability check.

Do not spend the first-run evaluation debugging Meta if you are reviewing the planning/creative agent. Complete that setup when testing the delivery capability, then explicitly approve a reviewed plan and keep the local delivery worker running.

## Inspect implementation evidence

- [Live Arabic draft and image recovery](evidence/drafting-recovery-2026-10-03.md)
- [Campaign variety and product-identity handling](evidence/creative-variety-2026-10-02.md)
- [Design deletion, regeneration, and CTA consistency](evidence/owner-design-controls-2026-10-03.md)
- [Posting-date controls](evidence/posting-date-editor-2026-10-03.md)
- [Durable scheduled publishing](evidence/scheduled-publishing-2026-10-02.md)

The submission makes no guaranteed five-minute clean-install claim, no permanent hosting claim, and no claim that unverified Instagram/Gemini-website integrations are ready.
