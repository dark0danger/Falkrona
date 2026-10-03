# Dependencies

## Phase 11 continuation

No new runtime packages or subscriptions added. Creative planning reuses pinned
Hermes AIAgent/Gemini transport, Pydantic, SQLAlchemy and the standard library.
The 2026-09-30 inventory recorded 45 Python and 138 Node packages with no undeclared
license metadata. Application Python and Hermes Python remain separate.

## Locked in Phase 0

| Component | Pin | License | Status |
| --- | --- | --- | --- |
| Hermes Agent | `801a9022a742562a3c4578c0d8dd12cfd393fc47` | MIT | Source and real runtime gate passed |
| PostgreSQL image | `postgres:17.6-alpine` | PostgreSQL License | Compose configuration validated |
| BrandPilot Python | `>=3.13,<3.14` | Python license | Host has 3.13.12 |
| setuptools | `80.9.0` | MIT | Build dependency pinned in `uv.lock` |
| Hermes Python | PM-managed 3.14.7 | Python license | Separate runtime passed |
| Node.js | `>=24,<25` | MIT | Host has 24.13.1 |
| npm | `>=11,<12` | Artistic-2.0 | Host has 11.8.0 |

Falkrona's exact root graphs are recorded in `uv.lock` and `package-lock.json`.
Hermes owns its complete hash-verified dependency graph in upstream `uv.lock` and
`pm/lock.json` at the pinned commit; upstream license and notice files remain in that
immutable checkout. BrandPilot Phase 0 has no third-party application runtime
dependencies.

## Added in Phase 1

| Component | Locked version | License source |
| --- | --- | --- |
| Alembic | `1.20.0` | Package metadata inventory |
| FastAPI | `0.137.2` | Package metadata inventory |
| psycopg / binary | `3.3.6` | Package metadata inventory |
| Pydantic | `2.13.5` | Package metadata inventory |
| SQLAlchemy | `2.0.54` | Package metadata inventory |
| Uvicorn | `0.49.0` | Package metadata inventory |
| React / React DOM | `19.1.1` | npm lock metadata |
| Vite | `7.3.6` | npm lock metadata |
| Vitest | `5.0.2` | npm lock metadata |

The generated full inventory is `docs/DEPENDENCY_LICENSES.md`: 31 Python packages
and 138 Node packages, with no missing declared-license metadata. `npm audit` reported
zero known vulnerabilities after the Vitest 5 upgrade on 2026-09-28.

## Added in Phase 2

| Component | Locked version | Purpose | License source |
| --- | --- | --- | --- |
| argon2-cffi | `25.1.0` | Argon2id password hashing | Package metadata inventory |
| cryptography | `46.0.7` | AES-256-GCM credential encryption | Package metadata inventory |

The Phase 2 inventory contained 36 Python and 138 Node packages, with no
missing declared-license metadata.

## Added in Phase 3

| Component | Locked version | Purpose | License source |
| --- | --- | --- | --- |
| Pillow | `11.3.0` | Bounded image verification and metadata extraction | Package metadata inventory |
| defusedxml | `0.7.1` | Safe SVG/XML parsing | Package metadata inventory |
| pypdf | `6.19.0` | Bounded PDF text extraction | Package metadata inventory |
| python-docx | `1.2.0` | DOCX text extraction after ZIP checks | Package metadata inventory |
| openpyxl | `3.1.5` | XLSX read-only product mapping | Package metadata inventory |
| python-multipart | `0.0.32` | FastAPI multipart uploads | Package metadata inventory |

The generated Phase 3 inventory records 45 Python and 138 Node packages with no
undeclared licenses.
