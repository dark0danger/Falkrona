# Gemini creative planning setup

[Complete installation and troubleshooting](SETUP.md#4-enable-gemini-planning) · [Browser image workflow](BROWSER_IMAGE_WORKFLOW.md)

## Configure the provider

1. Create your own key in [Google AI Studio](https://aistudio.google.com/apikey). Check [Google’s key guide](https://ai.google.dev/gemini-api/docs/api-key), [model catalog](https://ai.google.dev/gemini-api/docs/models), and [pricing](https://ai.google.dev/gemini-api/docs/pricing).
2. Put `GEMINI_API_KEY`, `BRANDPILOT_MODEL_PROVIDER=gemini`, and an explicit supported `BRANDPILOT_GEMINI_MODEL` in the local ignored `.env`. Choose a model with native image input and structured JSON output.
3. Use `BRANDPILOT_EXECUTION_MODE=gemini_free` only with an eligible free-tier project/model and public brand context. That policy does not disable billing in Google’s project. Intentionally billed operation uses the separately selected `paid_opt_in` mode. Keep `BRANDPILOT_IMAGE_API_ENABLED=false` and `BRANDPILOT_OPENAI_PAID_ENABLED=false` for the browser image path.
4. Prepare Hermes with `scripts/prepare_hermes.ps1`, then run `.\.venv\Scripts\python.exe scripts/local_setup.py hermes` to configure its separate interpreter. Do not install Hermes into Falkrona’s `.venv`.
5. Create the owner account, select the workspace with `local_setup.py workspace`, and start the API and regular worker. Restart these processes after changing their configuration.
6. Install/connect the Browser Helper in Chrome/Edge and sign in directly to the selected image app. The [complete guide](SETUP.md#8-connect-the-browser-helper) names the exact folder to load.

## Owner flow

Complete **Branding** with the brand survey, transparent logo, and optional design reference. Upload the real product photo in **Products** and provide truthful details. In **Content plan**, choose a future week, product photo, Arabic/English, and sharing consent. **Draft a plan** starts the live Gemini weekly plan and detailed per-post prompts, then the connected image app creates complete ads. Review the completed designs, captions, and posting times; whole-plan publishing approval is a later step.

## Prompt contract

Gemini receives confirmed brand context, campaign goal, selected language, product facts, and appropriately scoped preferences. Uploaded logo, product, and optional reference previews provide native vision context. Keys, OAuth tokens, raw customer comments, and private customer records are excluded.

- **Logo:** preserve the owner-uploaded brand asset and palette.
- **Product:** identity evidence only. Preserve the actual item/packaging/label, while discarding the original photograph’s background, props, and composition.
- **Optional reference:** style inspiration only. Do not copy its brand, literal scene, claims, or wording.
- **Campaign:** distinct ideas, camera/scene/composition per post; shared brand typography, palette, logo treatment, and CTA style/position.

Gemini supplies structured planning/direction and a detailed complete-ad prompt. ChatGPT or Gemini’s website creates the image through the authorized helper; Falkrona does not add local text/logo overlays to that output. Original SAM weights/local segmentation are not required for this live flow.

Website image generation depends on the selected account and adapter. Login, quota, unconfirmed attachments, changed controls, or ambiguous output pauses the run and preserves recovery inputs. An uncertain submitted request is not automatically resent. Inspect the returned logo, product identity, label spelling, language, and claims before approving publication.
