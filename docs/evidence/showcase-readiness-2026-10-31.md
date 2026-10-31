# Reliability and deployment checks, 31 October 2026

## Changes

- Browser Helper 0.1.6 opens a foreground image tab and injects its adapter as soon as the document accepts commands, rather than waiting for all page resources. The adapter still waits for hydrated upload controls. Interrupted requests retain the existing submission checks. No measured live latency improvement is claimed.
- Concurrent CSRF rejections share a token refresh within the frontend so retries do not immediately invalidate one another.
- Generic managed PostgreSQL URLs select the installed psycopg driver.
- Hermes execution discovers both normal bootstrap and older spike-bootstrap runtime facts.
- Railway container includes the separate pinned Hermes runtime and a supervisor for the API, workspace generation workers and dedicated publishing workers. Vercel routes API traffic through the frontend origin.

## Verification

- The initial pytest run passed **244 tests**, with **14 PostgreSQL-only tests skipped**, and 104 subtests. This was followed by the PostgreSQL phase gate below.
- The final offline phase 11 gate passed every step, including **178 unittest cases** with PostgreSQL migrations, workspace isolation and durable job tests enabled, frontend tests, production build and dependency inventory.
- Frontend: **12 tests passed**, including concurrent CSRF recovery. Production TypeScript/Vite build passed.
- Browser Helper: **31 tests passed**, including early injection into a still-loading page, one-send behavior, interrupted uploads, paused/reloaded requests, image selection and return binding.
- Linux Docker build passed with the pinned Hermes runtime. The build exposed a missing `libatomic1` library, which is now included. The build downloads the full pinned runtime and can take substantially longer than a cached deployment.
- A container smoke test used a disposable PostgreSQL database and fresh random test credentials. API readiness returned HTTP 200, owner creation succeeded, and two workers started automatically for the new workspace.
- A test asset on a mounted volume survived stopping/removing the backend container and starting a replacement. The replacement API became ready. No real Gemini, ChatGPT or Meta requests were made by this smoke test.
- Vercel configuration loaded with a sample HTTPS backend origin and produced the expected API rewrite.

## Remaining live checks

Live ChatGPT generation was not verified in this session. The Windows browser-control tool stopped because it could not determine the current browser URL confidently. The owner confirmed the helper and ChatGPT account were available, but had not yet tried the updated generation flow.

The installed helper folder was updated to 0.1.6. Reload it in Chrome Extensions and reconnect to the local or hosted frontend origin before testing. Verify one generated post returns to the plan, then verify a selected plan through approval and scheduled delivery on the final hosted domain. Existing Meta permission/app-review requirements continue to apply.

Railway and Vercel deployment configuration is prepared and the Linux container is tested locally. No actual Railway or Vercel project was deployed or remote domain verified in this session. Follow [the deployment guide](../DEPLOYMENT.md).
