# Railway backend and Vercel frontend

This layout runs without your laptop hosting Falkrona. Image generation still uses the owner's Chrome/Edge helper and signed-in ChatGPT account. Keep that browser open while generating. Scheduled publishing and reports continue on Railway after approval.

## Services

- **Railway PostgreSQL:** persistent application database.
- **Railway backend:** the root `Dockerfile` builds the pinned Hermes runtime separately from Falkrona. `scripts/run_hosted.py` migrates the database and starts the API plus two workers per workspace. The publishing worker stays responsive while creative planning runs.
- **Railway volume:** mount at `/data`. The API and workers run in the same service so they share uploaded assets and generated artwork. Use **one replica**, with sleeping/serverless mode disabled. This setup targets a small showcase deployment. More replicas require shared object storage and a separate worker topology.
- **Vercel frontend:** the React app. `vercel.ts` forwards `/api/*` and `/health/*` to Railway, keeping session cookies on the frontend origin. Do not enable caching for authenticated API responses.

## 1. Railway

Create a project, add PostgreSQL, then add the Falkrona GitHub repository as a service. Use the **repository root**, the root Dockerfile and `railway.toml`. Attach a persistent volume at `/data` before uploading any assets. Generate a public HTTPS domain for the backend.

Set these **backend** variables in Railway:

| Variable | Value |
| --- | --- |
| `DATABASE_URL` | Reference PostgreSQL's connection URL using Railway's variable picker. The hosted launcher converts its scheme to the installed psycopg driver. |
| `BRANDPILOT_STORAGE_ROOT` | `/data/storage` |
| `BRANDPILOT_APP_SECRET_KEY` | A unique random secret of at least 32 characters. Keep it across redeployments. |
| `BRANDPILOT_CREDENTIAL_ENCRYPTION_KEY` | URL-safe base64 encoding of 32 random bytes. Keep it across redeployments. |
| `BRANDPILOT_OWNER_SETUP_TOKEN` | A unique secret of at least 20 characters. Use it only for owner account setup. |
| `BRANDPILOT_SESSION_COOKIE_SECURE` | `true` |
| `BRANDPILOT_EXECUTION_MODE` | `gemini_free` |
| `BRANDPILOT_MODEL_PROVIDER` | `gemini` |
| `BRANDPILOT_GEMINI_MODEL` | Your supported Gemini model ID. |
| `GEMINI_API_KEY` | Your Google AI Studio API key. |
| `BRANDPILOT_OPENAI_PAID_ENABLED` | `false` |
| `BRANDPILOT_IMAGE_API_ENABLED` | `false` |

Generate the three security values locally, then paste them into Railway variables (never commit them):

```powershell
.\.venv\Scripts\python.exe -c "import secrets,base64; print('APP_SECRET='+secrets.token_urlsafe(48)); print('ENCRYPTION_KEY='+base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()); print('SETUP_TOKEN='+secrets.token_urlsafe(32))"
```

Do not copy your Windows `BRANDPILOT_HERMES_PYTHON`, local storage path, database URL or workspace ID into Railway. The image prepares the Linux Hermes interpreter and the launcher discovers new workspaces automatically. The first container build downloads both application and Hermes dependencies and may take several minutes.

Open `https://YOUR-BACKEND.up.railway.app/health/ready` and require HTTP 200. Migration errors stop startup. A database role error means the PostgreSQL migration user needs permission to create/grant the `brandpilot_app` role. The application continues using that restricted role and tenant policies.

## 2. Vercel

Import the same repository. Leave **Root Directory at the repository root**, select Vite and use the settings in `vercel.ts`:

- Install: `npm ci`
- Build: `npm run build`
- Output: `apps/web/dist`
- Node: **24.x**
- Variable: `FALKRONA_BACKEND_URL=https://YOUR-BACKEND.up.railway.app`

The backend URL must be an HTTPS origin with no additional path. Vercel evaluates the TypeScript routing configuration during deployment. Set the variable for each deployment environment you use. Missing/invalid configuration fails rather than deploying an interface with a broken API.

No Gemini key, database credential or app secret belongs in Vercel or a `VITE_*` variable.

## 3. First visit

1. Open the Vercel address. Verify `/health/ready` and `/api/status` return backend JSON at this same address.
2. Use **First-time workspace setup**, create your owner account with your setup token and sign in.
3. The Railway launcher discovers the new workspace within about five seconds. You do not run a workspace selection command on the host.
4. Complete Branding and upload a product photo. Existing local data does not transfer automatically; it remains on your computer.
5. Install the helper from `apps/browser-helper`, open the **Vercel** Falkrona page and use **Allow and connect**. Reconnect whenever moving to a different frontend domain.
6. Draft one post first. Confirm its design returns to the plan. Review before approving any schedule.

## 4. Facebook

Add all four Meta variables to Railway together:

```dotenv
BRANDPILOT_META_APP_ID=YOUR_APP_ID
BRANDPILOT_META_APP_SECRET=YOUR_APP_SECRET
BRANDPILOT_META_GRAPH_VERSION=YOUR_SUPPORTED_GRAPH_VERSION
BRANDPILOT_META_CALLBACK_URL=https://YOUR-FRONTEND.vercel.app/api/v1/social/meta/callback
```

The callback uses the **Vercel frontend domain**, including the complete path above. Add that exact address to Meta's valid OAuth redirect URIs and configure the app domain. Redeploy the backend, connect Facebook from Falkrona, grant publishing permissions and choose your Page. Meta app review/access rules still apply to accounts outside accepted development roles. See [Meta setup](SETUP.md#10-facebook-and-meta-setup).

## Check before sharing

Verify account setup/login/logout, brand saving, logo/product uploads, Arabic or English planning, image return, regeneration, changed posting dates, one-plan approval, scheduled publication and report availability. Test a page refresh and an interrupted generation with **Continue creating designs**. Check that a deployment restart retains images and approved jobs. Keep the same signing/encryption secrets and retain both PostgreSQL and the volume.

Railway API/database resources consume usage. Check the limits and credits on your actual account before leaving services running. Direct image APIs and Instagram publishing remain future work.

Official guides: [Railway Dockerfiles](https://docs.railway.com/builds/dockerfiles), [volumes](https://docs.railway.com/volumes), [health checks](https://docs.railway.com/deployments/healthchecks), [Vercel programmatic configuration](https://vercel.com/docs/project-configuration), [external rewrites](https://vercel.com/docs/routing/rewrites).
