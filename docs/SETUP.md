# Complete setup guide

[← README](../README.md) · [First campaign](QUICKSTART.md) · [Troubleshooting](#troubleshooting)

This guide runs Falkrona on a Windows computer using PowerShell. It starts the actual API, frontend, PostgreSQL database, and workspace worker. Docker Compose currently supplies **PostgreSQL only**, not the entire app. Run every command below from the repository root unless a step says otherwise.

Choose the features you want to use:

| Path | Needed | Result |
| --- | --- | --- |
| Local offline preview | Steps 1–3 and 6–7 | Local account and interface; deterministic fixtures where supported. No live Gemini or social calls. |
| Real planning and designs | Steps 1–9 | Gemini planning + browser image generation. Facebook login is not necessary to create a plan and designs. |
| Facebook delivery | Add step 10 and the delivery worker | Approved posts delivered to a permitted Facebook Page. |

The first installation downloads application dependencies and the Hermes runtime. You will also configure your own provider and image-app accounts.

## 1. Prerequisites

Install the following and open a **new PowerShell terminal** afterward so PATH changes are available.

| Tool | Required version / purpose | Official link |
| --- | --- | --- |
| Git | Clone Falkrona and the pinned Hermes source | [Download Git](https://git-scm.com/downloads) |
| uv | Locked Python dependency installation | [Install uv](https://docs.astral.sh/uv/getting-started/installation/) |
| Python | 3.13 for Falkrona; uv can install it in step 2 | [uv Python guide](https://docs.astral.sh/uv/guides/install-python/) |
| Node.js + npm | Node 24 and npm 11 | [Download Node.js](https://nodejs.org/en/download) |
| Docker Desktop | PostgreSQL container; start Docker Desktop with Linux containers | [Windows installation](https://docs.docker.com/desktop/setup/install/windows-install/) |
| Chrome or Edge | Browser Helper; Chrome 120+ or a current compatible Edge | [Chrome](https://www.google.com/chrome/) · [Edge](https://www.microsoft.com/edge) |

The Docker guide covers supported Windows versions, WSL, and virtualization prerequisites. Check that the engine is running, not just that the CLI is installed:

```powershell
git --version
uv --version
node --version
npm --version
docker compose version
docker info
```

For uv, the official Windows package-manager command is:

```powershell
winget install --id=astral-sh.uv -e
```

Use Node **24.x** even if the download page also offers a newer major version. The repository declares Node 24 and npm 11 in `package.json`.

## 2. Clone and install application dependencies

```powershell
git clone https://github.com/dark0danger/Falkrona.git
cd Falkrona
uv python install 3.13
uv sync --locked --python 3.13
npm ci
```

The Python environment is created at `.venv`. No activation is necessary: subsequent commands name its interpreter directly. `uv.lock` and `package-lock.json` provide the locked dependencies; do not replace them just to get past a setup error.

Hermes is installed separately in step 5. Its independently managed Python runtime is not Falkrona’s Python 3.13 environment.

## 3. Create local configuration and PostgreSQL

### Create `.env` safely

```powershell
.\.venv\Scripts\python.exe scripts/local_setup.py init
notepad .env
```

This creates `.env` from `.env.example` with unique application/session, credential-encryption, owner-bootstrap, and Hermes service values. It keeps provider keys blank and external execution disabled. It refuses to overwrite an existing `.env` or rotate its keys.

For HTTP at `http://127.0.0.1:5173`, the utility writes `BRANDPILOT_SESSION_COOKIE_SECURE=false`. If your **initial** setup will use HTTPS instead, use `init --https`. For an existing file, change that setting manually when switching to HTTPS; do not recreate your encryption key.

Do not wrap values in quotation marks: the PowerShell launch scripts read literal `NAME=value` lines. Keep `.env` local; `.gitignore` excludes it.

### Start the database and migrate

Open Docker Desktop, then:

```powershell
docker compose -f infra/postgres/compose.yaml up -d --wait postgres
powershell -ExecutionPolicy Bypass -File scripts/migrate.ps1
```

The local Compose file uses development-only `brandpilot` database credentials and exposes PostgreSQL on loopback port **5432**. The matching `.env.example` URL is:

```dotenv
BRANDPILOT_DATABASE_URL=postgresql+psycopg://brandpilot:brandpilot@127.0.0.1:5432/brandpilot
BRANDPILOT_STORAGE_ROOT=.runtime/storage
```

The Docker volume retains database state across normal container shutdowns. Uploaded and generated files live in `.runtime/storage`; preserve both if you need to retain a workspace.

## 4. Enable Gemini planning

A Gemini API key is needed for the brand survey, weekly plan, and detailed design prompts. It is separate from signing in to the Gemini website or ChatGPT.

1. Open [Google AI Studio API keys](https://aistudio.google.com/apikey) and create a key for your project. See [Google’s key guide](https://ai.google.dev/gemini-api/docs/api-key).
2. Choose an available Gemini model with **image input and structured JSON output**. Check the [current model catalog](https://ai.google.dev/gemini-api/docs/models) and [structured-output documentation](https://ai.google.dev/gemini-api/docs/structured-output).
3. Check [pricing](https://ai.google.dev/gemini-api/docs/pricing) and [rate limits](https://ai.google.dev/gemini-api/docs/rate-limits) for the selected project/model. Use an eligible free-tier project if you need zero model spending.
4. Edit these settings in `.env`, replacing both placeholders:

```dotenv
BRANDPILOT_EXECUTION_MODE=gemini_free
BRANDPILOT_MODEL_PROVIDER=gemini
BRANDPILOT_GEMINI_MODEL=YOUR_SUPPORTED_GEMINI_MODEL_ID
GEMINI_API_KEY=YOUR_GEMINI_API_KEY
BRANDPILOT_OPENAI_PAID_ENABLED=false
BRANDPILOT_IMAGE_API_ENABLED=false
```

Model IDs are explicit configuration. A newly released model is not automatically tested by Falkrona. Choose one supported by your account and the pinned Hermes Gemini integration, then verify it with a small one-post plan.

`gemini_free` selects Falkrona’s provider/cost policy; it does not turn off billing on your Google project. Public brand-context consent is required in this mode. Do not enter customer records or private business data into that flow.

For an intentionally billed Gemini project, the separate `paid_opt_in` execution mode exists. It is not selected by these instructions. Keep OpenAI paid calls and image API calls disabled for the browser image workflow.

**No OpenAI API key is needed** when ChatGPT creates images through the Browser Helper. You sign in to ChatGPT directly in the browser; Falkrona does not collect its password or session cookies.

To remain entirely offline, keep `BRANDPILOT_EXECUTION_MODE=offline_test`, `BRANDPILOT_MODEL_PROVIDER=none`, and both paid/image flags `false`. Offline preview is not real agent planning or real publishing.

## 5. Prepare the pinned Hermes runtime

```powershell
powershell -ExecutionPolicy Bypass -File scripts/prepare_hermes.ps1
.\.venv\Scripts\python.exe scripts/local_setup.py hermes
```

The first command clones Hermes into `.dependencies/hermes-agent`, checks out the revision from [`infra/hermes/pin.json`](../infra/hermes/pin.json), prepares its managed runtime, and installs Falkrona’s graphic-design skill. It can download substantial dependencies on the first run.

The second command finds the interpreter recorded by that preparation and sets `BRANDPILOT_HERMES_PYTHON` in your local `.env`. This avoids depending on a previously created developer fixture home. It does not change your provider keys.

Do not point `BRANDPILOT_HERMES_PYTHON` at Falkrona’s `.venv`. Do not use an arbitrary newer Hermes checkout: Falkrona checks the pinned source revision. Upstream project: [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent).

## 6. Start the API and frontend

Keep these in **two separate terminals**, opened in the repository root:

```powershell
# Terminal 1 — API
powershell -ExecutionPolicy Bypass -File scripts/run_api.ps1
```

```powershell
# Terminal 2 — web interface
npm run dev --workspace @falkrona/web
```

| Service | Address |
| --- | --- |
| Owner interface | [http://127.0.0.1:5173](http://127.0.0.1:5173) |
| API documentation | [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) |
| Health | [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health) |
| Execution/provider status | [http://127.0.0.1:5173/api/status](http://127.0.0.1:5173/api/status) |

The Vite frontend proxies API and health requests to FastAPI. Open the owner interface, not the API address, for the normal workflow.

### Create the first owner

On the sign-in page, expand **First-time workspace setup**, choose **Set up the owner**, enter your email, password, and workspace name, and paste `BRANDPILOT_OWNER_SETUP_TOKEN` from your own `.env` into **Local setup token**. Click **Create owner**.

That token is a local bootstrap secret. Normal sign-in uses the account email and password after setup. An already initialized database does not become a fresh owner setup by restarting the server.

## 7. Select the workspace and start workers

After creating the owner, open a third terminal:

```powershell
.\.venv\Scripts\python.exe scripts/local_setup.py workspace
powershell -ExecutionPolicy Bypass -File scripts/run_worker.ps1
```

The utility reads workspace IDs from the configured database and sets `BRANDPILOT_WORKSPACE_ID` in `.env`. A fresh database has one workspace. It refuses to guess if zero or multiple workspaces exist. For an existing multi-workspace setup, choose a known workspace explicitly:

```powershell
.\.venv\Scripts\python.exe scripts/local_setup.py workspace --workspace-id YOUR_WORKSPACE_UUID
```

If you need to look up local IDs:

```powershell
docker compose -f infra/postgres/compose.yaml exec postgres psql -U brandpilot -d brandpilot -c "SELECT id, name FROM workspaces;"
```

Run one worker configuration per workspace. The current launch scripts read one `.env`, so a broader multi-workspace deployment needs separate process environments/configuration. Do not silently change a running worker’s scope to another workspace.

For scheduled publishing, also open a **fourth terminal**:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_worker.ps1 --publishing-only
```

The regular worker handles planning, sync, measurement, reporting, and jobs. The dedicated delivery worker prevents slow model work from delaying approved posts. Keep the API, database, and relevant workers running when work is due. A post over 15 minutes late stops for attention rather than silently publishing far outside its approved slot.

## 8. Connect the Browser Helper

The extension is included in the repository at `apps/browser-helper`. You do not need to find a separate ZIP or a store listing.

1. Open **Chrome** or **Edge**, using the same browser for Falkrona and the image service.
2. Open `chrome://extensions` or `edge://extensions`.
3. Enable **Developer mode** → **Load unpacked**.
4. Select the actual **`apps/browser-helper` folder inside your cloned repository**. It must directly contain `manifest.json`; do not select the repository root or a parent folder.
5. Open the active Falkrona page in that browser. Click the **Falkrona Browser Helper** extension, choose **ChatGPT** or **Gemini**, and click **Allow and connect**.
6. Allow the requested access for that Falkrona origin and selected image service. Sign in directly at [ChatGPT](https://chatgpt.com/) or [Gemini](https://gemini.google.com/).
7. Return to Falkrona. The connection should be reported before you draft a live generation batch.

The included manifest is version **0.1.5**. After updating extension files, click **Reload** on its Extensions card and refresh Falkrona. Extracting a ZIP by itself does not activate a new extension version.

ChatGPT attachment, send, and return were exercised in the owner’s account. The Gemini website adapter remains pending end-to-end verification. Availability and image quotas depend on the selected account; signing in does not guarantee unlimited generation.

The helper automates the approved prompt/images and returns the generated result. You do not normally press Send or manually import every image. Keep its generation tab open. It pauses if login, verification, limits, attachment confirmation, or changed website controls require attention.

If you switch origin, including a new HTTPS tunnel address, open that Falkrona page and **Allow and connect again**. Disconnect in the helper popup to revoke the selected access. See [helper instructions](../apps/browser-helper/README.md) and [the integration boundary](BROWSER_IMAGE_WORKFLOW.md).

## 9. Create your first real plan

1. Open **Branding**. Complete the survey for name, business/category, audience, and preferred style. Upload a logo with a transparent background, optionally upload a design reference, and save.
2. Open **Products**. Upload a real product image and add factual details. Product photos supply product identity; they must not dictate the ad’s background or composition.
3. Open **Content plan**. Select a current/future week with enough future slots, choose a product photo, select **Arabic** or **English**, and authorize sharing the displayed brand inputs with Gemini and the selected image service.
4. For the first test, use **one post**. Click **Draft a plan**. The live workflow drafts the weekly strategy and automatically starts detailed prompts and image generation through the connected helper.
5. Inspect the finished image, caption, and future Cairo time. Use **Regenerate**, **Delete**, or **Change posting date** while the plan is still an unscheduled draft.
6. Try a small multi-post batch to see different ideas with shared brand styling and CTA treatment. Do not confuse consistency with repeating the uploaded product photograph.

Drafting/generating does not publish anything to Facebook. You may download designs without connecting Meta. Whole-plan scheduling requires the separate Facebook setup below and an explicit approval.

## 10. Facebook and Meta setup

### What needs configuring, and by whom?

The **app operator** configures one Meta app, its ID/secret/version, callback, and permissions. A brand owner normally just connects Facebook, grants consent, and selects a Page. Creating a separate Meta app for every brand owner is not the intended product workflow.

A Meta app in development may limit access to accepted app-role users with the required Page access. Connecting other users requires the relevant Meta review and permission approvals. Permissions listed in a review request remain pending until Meta approves them.

Official references: [Meta app dashboard](https://developers.facebook.com/apps/) · [Pages API](https://developers.facebook.com/docs/pages-api/) · [Permissions](https://developers.facebook.com/docs/permissions/) · [App roles](https://developers.facebook.com/docs/development/build-and-test/app-roles/) · [App Review](https://developers.facebook.com/docs/app-review/) · [Facebook Login for Business](https://developers.facebook.com/docs/facebook-login/facebook-login-for-business/).

### Configure a local HTTPS callback

For local testing, use HTTPS on the same origin as the Falkrona UI. A development tunnel gives Meta a reachable HTTPS callback while Falkrona runs locally.

1. Install [cloudflared](https://developers.cloudflare.com/tunnel/downloads/) and start a development tunnel to the **frontend port 5173**:

```powershell
cloudflared tunnel --url http://127.0.0.1:5173
```

2. Copy the actual HTTPS origin printed by cloudflared. The URL below is a placeholder, not a Falkrona deployment:

```text
https://YOUR-TUNNEL.trycloudflare.com
```

3. In the Meta app’s **Facebook Login for Business → Settings**, enable Client OAuth Login and Web OAuth Login as appropriate for your app, then add this **complete** URL to **Valid OAuth Redirect URIs**:

```text
https://YOUR-TUNNEL.trycloudflare.com/api/v1/social/meta/callback
```

The homepage alone is not the callback. It must match exactly, including path, host, and scheme.

Common Arabic dashboard labels (wording depends on the configured app/use case):

| English | Arabic |
| --- | --- |
| Facebook Login for Business | تسجيل دخول فيسبوك للأعمال |
| Settings | الإعدادات |
| Client OAuth Login | تسجيل دخول العميل عبر OAuth |
| Web OAuth Login | تسجيل دخول OAuth للويب |
| Valid OAuth Redirect URIs | محددات URI لإعادة توجيه OAuth الصالحة |
| App settings → Basic | إعدادات التطبيق → أساسي |
| App domains | نطاقات التطبيق |
| App roles | الأدوار بالتطبيق |
| App Review | مراجعة التطبيق |

4. Configure all four Meta values together in `.env`, using the app’s actual values and a supported Graph version from your Meta dashboard/docs:

```dotenv
BRANDPILOT_META_APP_ID=YOUR_META_APP_ID
BRANDPILOT_META_APP_SECRET=YOUR_META_APP_SECRET
BRANDPILOT_META_GRAPH_VERSION=vYOUR_SUPPORTED_VERSION.0
BRANDPILOT_META_CALLBACK_URL=https://YOUR-TUNNEL.trycloudflare.com/api/v1/social/meta/callback
BRANDPILOT_SESSION_COOKIE_SECURE=true
```

Replace the version placeholder, for example with the exact `vNN.0` shown for your app. A partial Meta configuration causes startup validation to fail. Keep the app secret server-side.

5. Stop/restart the API and workers to load `.env`. Stop Vite and restart it with the tunnel hostname allowed. In its terminal:

```powershell
$env:__VITE_ADDITIONAL_SERVER_ALLOWED_HOSTS = "YOUR-TUNNEL.trycloudflare.com"
npm run dev --workspace @falkrona/web
```

Use hostname only, without `https://` or the callback path. Keep API and Vite bound to loopback; do not allow every hostname.

6. Open the **HTTPS tunnel homepage**, sign in there, and reconnect the Browser Helper to that origin if generating images there. Starting Facebook login from the old localhost page can prevent the callback session from matching.

A quick-tunnel address changes after restart. Update both Meta and `.env`, restart affected processes, and reconnect the helper. [Quick tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/) are development tools with no uptime guarantee; a persistent deployment needs a stable HTTPS origin.

### Required Facebook permissions and Page selection

| Permission | Falkrona requests it for |
| --- | --- |
| `pages_show_list` | List Pages the owner can choose. |
| `pages_read_engagement` | Read permitted Page content/engagement. |
| `pages_manage_posts` | Create approved Page posts; requested by **Allow publishing access**. |

Do not add Instagram scopes to the Facebook-only test. Current Facebook login does not request `instagram_basic`. Extra Meta permissions are not automatically used just because the developer dashboard lists them.

1. Use **Social accounts → Facebook** and complete the consent flow.
2. Select the Page you actually manage. Page access/tasks and the granted scopes determine the capabilities; a successful Facebook login alone does not prove publishing access.
3. Click **Allow publishing access**, finish consent, and select the same Page again if read-only access was already connected.
4. Check the grant without posting:

```powershell
.\.venv\Scripts\python.exe scripts/check_meta_permissions.py --workspace-id YOUR_WORKSPACE_UUID
```

The check reports capabilities without printing tokens. If publishing remains unavailable, inspect the actual grant, Page access, and app review/role eligibility. Restarting Falkrona cannot create a permission Meta did not grant.

### Approve and publish

Once the plan’s designs are complete, review the artwork, factual claims, captions, and future **Cairo** times. Click **Approve plan & schedule** for the chosen Page. The plan is bound to those approved assets/captions/times. No separate approval for every post is needed.

Keep the database, API, regular worker, and dedicated publishing worker running on the computer executing the schedule. Watch post status in Content plan. **View published post** appears when a remote publication ID is recorded. Uncertain submissions are reconciled rather than blindly resent; **Needs attention** requires review. **Cancel unpublished posts** stops remaining unsent schedule entries.

Instagram remains deferred and uses its own disabled control until its connection and delivery have been verified. A Facebook connection is not an Instagram connection.

## 11. Weekly reports

The regular workspace worker schedules daily authorized post/engagement collection and reports for completed weeks, beginning Monday just after midnight in **Africa/Cairo**. Reports appear in **Results**; this is an in-app report, not an email delivery promise. The scheduler can catch up after restarts.

Keep the worker running and the social connection authorized. Metrics depend on available platform data and granted capabilities. Missing data should not be interpreted as real zero engagement or a measured growth claim.

## Restart, shutdown, and updates

- Stop frontend/API/workers with **Ctrl+C** in their own terminals.
- Stop PostgreSQL without deleting its volume:

```powershell
docker compose -f infra/postgres/compose.yaml stop
```

- Restart PostgreSQL with the `up -d --wait postgres` command and rerun the normal launch commands. Saved data/jobs are durable; uncertain image/post requests are not automatically resent.
- After changing `.env`, restart the processes that read it. Refreshing the browser alone does not reload server configuration.
- After updating source, run `uv sync --locked --python 3.13`, `npm ci`, and migrations, then restart the app. Reload an updated Browser Helper in Extensions.
- Do not delete the PostgreSQL volume, storage directory, or encryption key as a normal troubleshooting step. They are needed to retain work and encrypted connections.

## Configuration reference

See [`.env.example`](../.env.example) for every variable. The settings below cover the normal owner/demo flow:

| Setting | Purpose |
| --- | --- |
| `BRANDPILOT_EXECUTION_MODE` | `offline_test`, `gemini_free`, or explicitly billed `paid_opt_in`. |
| `BRANDPILOT_MODEL_PROVIDER` | `none` offline; `gemini` for the documented live workflow. |
| `GEMINI_API_KEY` | Server-side Gemini credential; `GOOGLE_API_KEY` is a fallback. |
| `BRANDPILOT_GEMINI_MODEL` | Explicit supported model ID. |
| `BRANDPILOT_HERMES_PYTHON` | Prepared separate Hermes interpreter; set by the utility. |
| `BRANDPILOT_DATABASE_URL` | PostgreSQL application database and credentials. |
| `BRANDPILOT_STORAGE_ROOT` | Durable local asset directory. |
| `BRANDPILOT_WORKSPACE_ID` | Workspace scope for the worker. |
| `BRANDPILOT_APP_SECRET_KEY` | Generated session/application signing value. |
| `BRANDPILOT_CREDENTIAL_ENCRYPTION_KEY` | Generated base64 encoding of exactly 32 bytes. Preserve it with existing connections. |
| `BRANDPILOT_OWNER_SETUP_TOKEN` | Generated bootstrap token for the first owner form. |
| `BRANDPILOT_SESSION_COOKIE_SECURE` | `false` only for local HTTP; `true` for HTTPS. |
| `BRANDPILOT_META_APP_ID`, `...APP_SECRET`, `...GRAPH_VERSION`, `...CALLBACK_URL` | All four required together for the Meta connector. |
| `BRANDPILOT_AGENT_MAX_MODEL_CALLS`, `...MAX_INPUT_TOKENS`, `...MAX_OUTPUT_TOKENS` | Existing run admission limits. |
| `BRANDPILOT_OPENAI_PAID_ENABLED`, `BRANDPILOT_IMAGE_API_ENABLED` | Keep `false` for this setup. |
| `FALKRONA_DEV_API_URL` | Set in the Vite terminal if the API uses another local port. |
| `__VITE_ADDITIONAL_SERVER_ALLOWED_HOSTS` | Set in the Vite terminal to permit the current HTTPS tunnel hostname. |

The utility only creates fresh security values during `init`. `hermes` changes the interpreter setting; `workspace` changes the worker scope. It does not activate paid calls, perform OAuth, create users, or publish posts. For advanced use, `--env-file PATH` chooses another local configuration file; the existing API/worker launch scripts still load the root `.env`.

## Troubleshooting

| Symptom | Check / fix |
| --- | --- |
| `uv`, `node`, `npm`, `git`, or `docker` is not recognized | Install the prerequisite and reopen PowerShell. |
| `npm.ps1 cannot be loaded` | Use `npm.cmd ci` / `npm.cmd run dev --workspace @falkrona/web`, or your organization’s permitted PowerShell policy. |
| Docker cannot connect to its engine | Open Docker Desktop; verify Linux-container/WSL setup and run `docker info`. |
| Port 5432 is already in use | Reuse a compatible local PostgreSQL instance and set the correct URL, or explicitly change both Compose’s host port and `.env`. Do not remove an unrelated database. |
| Python or Node version mismatch | Install Python 3.13 with uv and use Node 24/npm 11. |
| Setup says `.env` exists | It preserved your file. Edit it instead of rerunning `init`; do not overwrite existing keys. |
| Missing application/credential/setup secret | For a fresh install, run `local_setup.py init`. For an existing workspace, restore its original secrets. |
| Sign-in appears successful then returns to login | Ensure local HTTP uses secure-cookie `false`, HTTPS uses `true`, and you are using one consistent UI origin. Restart API after changing it. |
| `runtime_unavailable` or Hermes cannot complete planning | Run `prepare_hermes.ps1`, then `local_setup.py hermes`; check model/key availability; restart the worker. |
| Worker says workspace ID is required | Create the owner, run `local_setup.py workspace`, then start the worker. |
| Plan remains queued | Verify the regular worker is running for this workspace. |
| Gemini refuses or cannot draft a week | Check key/model/quota, brand completeness, selected language, public-context consent, and enough future slots. Inspect the saved plain error before retrying. |
| Helper is disconnected | Use Chrome/Edge, load the folder containing `manifest.json`, open the current Falkrona origin, then **Allow and connect**. |
| Helper loaded from the wrong folder or uses an old version | The installed folder should be this clone’s `apps/browser-helper`; reload it in Extensions and refresh Falkrona. |
| Image app did not confirm all attachments | Keep the existing generation tab open. Review login/loading/upload state and use the saved recovery action. Do not manually send a duplicate request. |
| Image app pauses after submission | Resume observes the same conversation. If necessary, use Studio’s manual recovery prompt/assets and import the finished image. |
| Text is Arabic when you expected English, or vice versa | Set the design language before drafting. Regenerate a new draft if its saved language is wrong. |
| Facebook reports a blocked redirect URL | Whitelist the complete callback path and make `.env` match exactly; start login from that HTTPS UI origin. |
| `Invalid Scopes: instagram_basic` | Use the current Facebook-only flow; do not manually add that Instagram permission. |
| Facebook works for the developer but not another account | Check accepted app roles, permission access/review, and Page access. An unreviewed permission request is not a public grant. |
| Facebook login succeeds but scheduling is disabled | Obtain `pages_manage_posts` through **Allow publishing access**, select the Page, and check actual capabilities. |
| Approved posts do not arrive | Verify the delivery worker, authorization expiry, future Cairo times, and the recorded publishing status. Late/uncertain jobs need attention. |
| Tunnel stopped / site cannot be reached | Restart the local services and tunnel while testing; a random quick-tunnel URL is not a permanent hosted demo. |

## Verification and development

These checks do not require a live model key unless you explicitly exercise live providers:

```powershell
.\.venv\Scripts\python.exe scripts/check_environment.py
.\.venv\Scripts\python.exe scripts/phase_gate.py --phase 11 --offline
npm test
npm run build
node --test apps/browser-helper/background.test.cjs apps/browser-helper/provider.test.cjs apps/browser-helper/provider-dom.test.cjs
```

The environment report also expects historical Hermes lock/runtime preparation; a missing fixture capability is not proof that your explicit live interpreter is unusable. Phase-gate PostgreSQL tests use an isolated database ending in `_phase_gate`, not the application database.

Optional real-Hermes offline probe:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_hermes_spike.ps1
```

That probe exercises the pinned runtime through a loopback fixture provider; it is a test, not a live creative request. Use [recorded evidence](evidence/drafting-recovery-2026-10-03.md) to understand historical validation and [PROGRESS](PROGRESS.md) for implementation history.

## Hosting later

A hosted deployment needs the frontend, FastAPI service, persistent PostgreSQL, asset storage, and always-running workers with a stable HTTPS origin. The Browser Helper runs in each connected owner’s browser. Static frontend hosting alone does not execute planning or scheduled publishing. Streamlit is not a drop-in host for the current React/FastAPI architecture.
