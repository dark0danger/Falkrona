# Your first campaign

[← README](../README.md) · [Complete setup](SETUP.md)

Falkrona turns your brand details and product photos into a weekly content plan with finished designs. This walkthrough covers the first campaign after installation.

## Set up Falkrona

Follow [steps 1–7 of the setup guide](SETUP.md#1-prerequisites) to install dependencies, configure Gemini and Hermes, create your account, and start the application and worker.

Live planning requires a Gemini API key. For image generation, sign in to ChatGPT and [connect the Browser Helper](SETUP.md#8-connect-the-browser-helper). The Gemini website adapter is included, but live account validation is pending.

## Add your brand and product

1. Open **Branding**, answer the short survey, and upload your logo with a transparent background. Add a design reference if you have one, then save.
2. Open **Products** and upload a clear product photo. Add factual product details where available.

The logo and brand survey define your identity. The product photo shows what the product looks like. An optional design reference helps with visual style. Falkrona keeps these asset roles separate.

## Create your plan

1. Open **Content plan** and choose a future week.
2. Select a product photo and choose Arabic or English for the designs.
3. Allow the selected services to use your brand inputs, then click **Draft a plan**.

Gemini creates the weekly plan and a detailed prompt for each post. The connected image app generates the designs and returns them to Falkrona. Keep its browser tab open during generation.

If a run pauses, use **Continue creating designs** to resume saved work. [Troubleshooting](SETUP.md#troubleshooting) covers connection, upload, and recovery issues.

## Review the finished work

Check the artwork, captions, and posting dates. Each post offers controls to regenerate a different idea, delete it, or change its future posting date. You can download the whole week before connecting Facebook.

## Approve and publish

Complete [Facebook and Meta setup](SETUP.md#10-facebook-and-meta-setup), grant Page publishing access, and choose the Page you manage. Then use **Approve plan & schedule** to approve the finished campaign.

Keep the database, API, and delivery worker running when posts are due. Falkrona publishes approved posts at the scheduled Cairo times.

## View results

Open **Weekly reports** to see engagement collected from the connected Page. Report data depends on the permissions granted and the history available for your posts.
