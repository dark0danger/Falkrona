# Social Application Setup Checklist

This checklist covers Facebook Pages and Instagram only. Other social integrations
are deferred future features. A successful login alone does not prove a capability.

Current live testing is Facebook-only. New login requests ask for
`pages_show_list` and `pages_read_engagement`; they do not request
`instagram_basic`. Instagram app configuration and live verification are deferred.

The UI provides separate Facebook and Instagram buttons. Instagram stays disabled
until its setup is verified. The Facebook-only consent button does not enable
publication by itself. **Allow publishing access** explicitly requests
`pages_manage_posts`. After generation, **Approve plan & schedule** binds the
reviewed whole plan to its Facebook Page, exact images/captions and future Cairo
times. A durable publishing worker uploads and posts at the approved times.
Permission names and Page tasks can be checked without writes:

`python scripts/check_meta_permissions.py --workspace-id <workspace UUID>`

This check uses the project's `.env` privately and prints no credentials. See
[the 2 October publishing review](evidence/publishing-permissions-2026-10-02.md).

- Create separate development applications and callback settings for Facebook and Instagram.
- Record the owner, app ID, API version, review status, and verification date.
- Store client secrets and refresh tokens only in server-side secret storage.
- Use unpredictable, expiring OAuth state and bind it to workspace and initiating user.
- Enumerate accounts/pages after authorization and require an explicit owner choice.
- Record each granted read, analytics, media, and publish capability separately.
- Verify pagination, revocation, refresh, rate-limit, and partial-permission behavior.
- Run external writes only against an authorized test account and approved exact asset.
- Keep upload/import/export and manual publication usable when approval is unavailable.
- Never add scraping to bypass denied official access.

## Facebook Pages read setup

For an already selected Page, use **Connect or reconnect Page** and select that
same Page after consent. Falkrona keeps the Page connection and imported posts,
replacing its encrypted credentials only after successful selection. If Meta omits
or reports zero for the user-token lifetime, Falkrona limits that authorization to
24 hours locally; reconnect when it expires.

Operator configuration uses BRANDPILOT_META_APP_ID,
BRANDPILOT_META_APP_SECRET, BRANDPILOT_META_GRAPH_VERSION, and
BRANDPILOT_META_CALLBACK_URL. The callback must end at
/api/v1/social/meta/callback and match the allowed redirect in the Meta app
exactly. It must use the same browser origin as the owner UI so the short-lived
callback cookie is sent; route /api through the reverse proxy to FastAPI. For
the local Vite setup, expose port 5173 (not FastAPI's port 8000) through an
HTTPS tunnel. The Meta dashboard rejects the HTTP loopback callback. For a
temporary development tunnel, install `cloudflared` and run
`cloudflared tunnel --url http://127.0.0.1:5173`. It prints a public HTTPS
origin such as `https://example.trycloudflare.com`. Configure this exact URL
in both the Meta app's Valid OAuth Redirect URIs and `.env`:

`BRANDPILOT_META_CALLBACK_URL=https://example.trycloudflare.com/api/v1/social/meta/callback`

Also fill the app ID, app secret, and reviewed Graph version in `.env`.
`offline_test` deliberately disables external social authorization; a live
Meta login needs a non-offline execution mode. The existing free-mode pair is
`BRANDPILOT_EXECUTION_MODE=gemini_free` and
`BRANDPILOT_MODEL_PROVIDER=gemini`; selecting it does not itself start an AI
run. Keep paid model calls disabled unless separately approved.

Set `BRANDPILOT_SESSION_COOKIE_SECURE=true` in `.env` and restart FastAPI.
In the PowerShell terminal used for Vite, run
`$env:__VITE_ADDITIONAL_SERVER_ALLOWED_HOSTS = "example.trycloudflare.com"`
(hostname only, no scheme/path), then restart Vite with
`npm run dev --workspace @falkrona/web`. Start FastAPI with
`powershell -ExecutionPolicy Bypass -File scripts/run_api.ps1` if it is not
already running.
Open the owner UI at the **tunnel's HTTPS origin**, sign in there, and use
Connect Meta. Starting from `http://127.0.0.1:5173` will not send the
host-bound OAuth callback cookie to the tunnel hostname. Keep the API and Vite
bound to loopback; do not set Vite's `allowedHosts` to `true`. A quick tunnel's
hostname changes on restart, so update both callback settings each time or
use a stable, named HTTPS tunnel. Quick tunnels are for development only and
do not support SSE; use a stable proxy/tunnel for broader app testing.

Keep the Meta secret outside the repository. The browser owner uses Connect
Meta; they do not enter developer credentials. Exposing the development UI
through a tunnel makes it reachable from the internet, so use a test workspace
and stop the tunnel when finished.
Run the workspace worker in its own VS Code terminal with the selected workspace
ID before testing Page post sync; leave it running for future jobs:

```powershell
$env:BRANDPILOT_WORKSPACE_ID = "<workspace UUID>"
powershell -ExecutionPolicy Bypass -File scripts/run_worker.ps1
```

Authorization and CSV import/export work through the API without a worker.

Record an authorized test Page, approved pages_show_list and
pages_read_engagement grants, selected Graph version, and a real Page post
read before marking the capability live. The current Page task values are
illustrated in [Meta's official Page token example](https://www.postman.com/meta/facebook/request/bqfxwbp/get-access-tokens-of-pages-you-manage).
Publishing and insights require separate approval and verification.

## Instagram scope

Instagram is the next active connector. Build and verify its professional-account
authorization and each permitted read capability separately. Keep CSV import/export
available while API permissions or account eligibility are pending. Do not treat a
Facebook Page connection as an Instagram connection, even when Meta links the two.
