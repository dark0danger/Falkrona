# Phase 03 Evidence

Commit: not committed

Mode: `offline_test`

## Implemented behavior

- Rebranded the project surface to Falkrona with the tagline `Your Brand's Pilot`.
- Added private upload/gallery handling for PNG, JPEG, WebP, SVG, PDF, and DOCX.
- Added bounded parser guards for file size, archive size, file count, expansion ratio,
  MIME/content mismatch, SVG scripts/entities/external references, and OOXML active
  content.
- Added Arabic/English CSV and XLSX product mapping previews with durable import jobs,
  private source storage, retry dedupe, and owner confirmation.
- Added URL intake that rejects unsafe schemes, credentials, local/private addresses,
  and DNS results resolving to non-public addresses. Offline mode records a blocked
  source and does not fetch it.
- Added persistent adaptive onboarding, contradiction records, versioned manual brand
  profiles, and responsive English/Arabic owner controls.

## Commands and results

- `uv lock` and `uv sync --group dev`: passed.
- `powershell -ExecutionPolicy Bypass -File scripts/migrate.ps1`: passed against local
  PostgreSQL after the Phase 3 policy upgrade fix.
- `uv run pytest -q`: 46 passed, 5 expected PostgreSQL skips without the test URL.
- `uv run python scripts/phase_gate.py --phase 3 --offline`: passed; 51 backend tests,
  5 real PostgreSQL tests, 2 web tests, production build, and dependency inventory.
- Dependency inventory: 45 Python, 138 Node, 0 undeclared licenses.
- `npm run build`: passed.

## Safety and recovery evidence

- Transparent PNG, EXIF-oriented JPEG, WebP, sanitized SVG, Arabic PDF/DOCX/CSV/XLSX
  fixtures all parsed successfully.
- Malformed images, oversized input, MIME spoofing, high-ratio archives, and unsafe
  SVG content failed closed.
- Repeated upload of the same bytes returned one gallery asset; import confirmation was
  idempotent; onboarding state was readable after a fresh request and contradictions
  were recorded instead of silently discarded.
- Manual profile proposal and confirmation succeeded without imported files.

Gate decision: passed. Phase 4 has not started.
