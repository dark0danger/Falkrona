# Falkrona Browser Helper · 0.1.5

[Full setup guide](../../docs/SETUP.md#8-connect-the-browser-helper) · [Image workflow](../../docs/BROWSER_IMAGE_WORKFLOW.md)

A Chrome/Edge Manifest V3 extension that sends the authorized Falkrona prompt and role-named assets to ChatGPT or Gemini, then returns the generated design to its matching post. ChatGPT was exercised in the owner flow; the Gemini website adapter is pending end-to-end verification. This is a development preview, not a marketplace release.

## Install from this repository

1. Open `chrome://extensions` or `edge://extensions` in the browser you use for Falkrona.
2. Enable **Developer mode** and choose **Load unpacked**.
3. Select this exact folder: `apps/browser-helper`. It directly contains `manifest.json`. You do not need a separate ZIP.
4. Open the active Falkrona page in that browser, click **Falkrona Browser Helper**, select **ChatGPT** or **Gemini**, then click **Allow and connect**.
5. Allow the selected Falkrona/image-app site grants and sign in directly to the selected image app.
6. Return to Falkrona, complete Branding/Products, and click **Draft a plan** in Content plan. The live workflow starts image generation automatically; saved interrupted batches offer **Continue creating designs**.

You do not normally press Send yourself. The helper confirms attachments and submits the saved prompt, waits for a completed stable image, and imports it. Generation is separate from the owner’s later whole-plan publishing approval.

## Update or change origin

After updating files, click **Reload** on the extension’s card, then refresh Falkrona. The loaded folder must be the one you updated. The manifest currently reports **0.1.5**.

Reconnect with **Allow and connect** after switching the Falkrona origin, tunnel URL, or selected image service. Keep the generation browser open. Disconnect in the popup to remove the selected grants and stop helper work.

## Recovery and limits

The helper pauses for login, verification, account limits, unconfirmed uploads, changed controls, or ambiguous outputs. An already-submitted request is observed in its original conversation; it is not automatically sent again. Submission tracking survives an extension reload, but prompts/image bytes are not persisted in extension storage.

Use Falkrona’s saved recovery action to continue the same request. When automation cannot finish, Studio retains the prompt and role-named assets and provides manual finished-image import. Automatic return reads the visible generated-image URL, which may be a preview; the image app’s own Download control may provide higher-resolution output.

The extension requests access only to the selected Falkrona origin and image service. It does not request cookies permission or collect passwords. No paid image API or social publishing permission is granted by installing it. Account quotas and website controls can change, so inspect the artwork before approving a plan.
