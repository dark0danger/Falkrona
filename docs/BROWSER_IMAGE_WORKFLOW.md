# Browser image generation

Falkrona uses Hermes and Gemini to prepare a creative brief. The Chrome or Edge helper sends it to the selected image website and returns the finished design to the matching draft. Browser Helper **0.1.7** supports the ChatGPT workflow. The Gemini website adapter is included and awaits live account validation.

## Connect and create

1. Complete **Brand** and upload a product photo in **Products**.
2. In Chrome or Edge, load the folder containing the helper's `manifest.json`. Open Falkrona in the same browser, choose **Allow and connect** in the helper, and sign in to the selected image app. See [installation and updates](SETUP.md#8-connect-the-browser-helper).
3. In Falkrona, open **Accounts → Image creation → Check connection**. Reconnect after changing the Falkrona address or image app.
4. In **Content plan**, choose a future week and design language, give consent for the selected services, and click **Create my week**. Keep the browser open while the design is generated.
5. Review the returned design, caption, and posting time. Publication requires a separate approval for the plan.

## How assets are used

- **Logo** provides the brand identity and correct spelling.
- **Product photo** provides the product's shape, packaging, label, and material. Falkrona asks the image app to create a fresh composition and omit the photo's original setting.
- **Optional design reference** supplies style cues such as color and typography. Falkrona asks the image app to avoid borrowing the reference's brand, product, copy, or claims.

Each post gets a distinct concept and composition within the campaign's shared style. Inspect the returned artwork for product fidelity, correct language, and truthful copy before approving it.

## Recovery and access

- If login, quota, or upload controls interrupt a run, **Open image request** opens the saved conversation. **Continue creating designs** resumes the saved work. A submitted request is observed without sending it again.
- If automatic return fails, use Studio's recovery options to copy the prompt, download the reference files, or import the finished image. Import accepts PNG, JPEG, or WebP and checks the 4:5 ratio.
- The helper needs permission for the connected Falkrona address and selected image website. Sign-in stays in your browser. Use **Disconnect** in the helper menu to revoke the connection.
- The connection check verifies browser access. Generation still depends on the provider's website, account login, and image allowance.

See [Gemini setup](GEMINI_CREATIVE_SETUP.md) for model configuration and [hosting](DEPLOYMENT.md) for connecting the helper to a deployed Falkrona site.
