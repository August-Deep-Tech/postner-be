# Postner BE

Multi-tenant FastAPI backend: register → brands → draft post → Recraft images → HTML preview → approve/render PNG → polish.

## Stack

- **Auth:** email/password + JWT
- **DB:** Postgres (Docker) — tenants, brands, **brand variants**, posts, revisions
- **Assets:** **object storage only** (S3-compatible; R2 in dev/prod). Filled HTML in `posts.composed`; Recraft / logos / PNG / MP4 as public URLs.
- **Packs/templates:** on disk (shared catalog). Starter variant JSON under `variants/` is **seeded into each brand** on create.

## Quick start (Docker)

```bash
cp .env.example .env
# set ANTHROPIC_API_KEY and/or OPENAI_API_KEY, FAL_KEY, JWT_SECRET

docker compose up --build
```

API: http://localhost:8001/docs

Compose brings up **api** + **db** (Postgres host port **5434**). Named volume: `pgdata`. Object storage is remote S3/R2 — set `STORAGE_*` in `.env`/`.env.local` before starting.

## Local (without Docker API)

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium

# Start Postgres
docker compose up db -d

cp .env.example .env
# DATABASE_URL=postgresql+psycopg://postner:postner@localhost:5434/postner
# Point STORAGE_* at your S3-compatible bucket (see .env.example)

alembic upgrade head
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Product flow

1. `POST /auth/register` `{ "email", "password", "name?" }` → JWT
2. `GET/POST/PATCH /brands` (Bearer token; user creates brands — no demo seed)
3. `POST /posts` — scrape + LLM draft (`with_images` optional)
4. `POST /posts/{id}/images` — Recraft source photos (reuse unless `regenerate`)
5. `POST /posts/{id}/compose` — **fill HTML only** → status `preview` (`ensure_images` gap-fills photos). FE reviews via `composed.pages[].html_content`
6. `POST /posts/{id}/feedback` `{ "decision": "approved" }` — auto-renders PNG if missing → `approved`; **or** `POST /posts/{id}/render` for PNGs without approving
7. Optional: `animate` | `resize` | `redesign` | `rewrite` | `undo`

### Auth

| Method | Path | Notes |
|---|---|---|
| POST | `/auth/register` | Creates user + personal tenant |
| POST | `/auth/login` | Returns access JWT |
| GET | `/auth/me` | User + active tenant |

JWT claims: `sub` (user_id), `tenant_id`. Set `Authorization: Bearer <token>` on brands/posts.

### Posts

| Method | Path | Role |
|---|---|---|
| POST | `/posts` | Draft (`url`, `brand_id`, `pack_id`\|`template_id`, `format`, `variant_id`, `with_images`) |
| GET | `/posts/{id}` | Full state (tenant-scoped); `composed` enriched with `html_content` |
| GET | `/posts/{id}/pages/{page_id}/html` | Browser-ready filled HTML for one page |
| POST | `/posts/{id}/images` | Recraft (`pages?`, `regenerate`) |
| POST | `/posts/{id}/compose` | Fill HTML preview (`pages?`, `ensure_images`) — no Playwright |
| POST | `/posts/{id}/render` | Playwright PNG + upload (`pages?`) → status `rendered` |
| POST | `/posts/{id}/animate` | MP4 (`motion_preset`); requires rendered PNGs |
| POST | `/posts/{id}/resize` | Re-fill HTML at `format` (clears PNG urls; call `/render` after) |
| POST | `/posts/{id}/redesign` | `variant_id` and/or `propose: true`, then re-fill HTML if `recompose` |
| POST | `/posts/{id}/rewrite` | Caption/text or `suggest` re-LLM; `recompose` re-fills HTML |
| POST | `/posts/{id}/undo` | Restore previous revision snapshot |
| GET | `/posts/{id}/revisions` | List `{ id, kind, version, created_at }` |
| POST | `/posts/{id}/feedback` | `decision`, `reasons[]`, `note`; **approved** auto-renders if no PNGs |

`format`: `ig_feed` | `ig_portrait` | `ig_story` | `tiktok` | `fb_post` | **`x_post`** (1600×900)

**Statuses:** `drafted` → `preview` (HTML) → `rendered` (PNG) → `approved` / `rejected`.
### Packs + variants (design propose)

Packs are multi-page templates on disk. **Variants are per-brand color palettes in Postgres** (`brand_variants`). Creating a brand seeds starter palettes from `variants/*.json`.

| Method | Path | Role |
|---|---|---|
| GET | `/packs` | List packs |
| POST | `/packs/propose` | Assemble new packs; `with_variants` requires `brand_id` and saves skins on that brand |
| GET | `/variants?brand_id=` | List that brand’s variants (`id`, `slug`, `label`, `css_vars`) |
| POST | `/variants/propose` | **Requires `brand_id`**; palettes for `pack_id` **or** `template_id` (XOR), saved on the brand |

Variant generation is biased by: pack/template HTML + required CSS keys + brand name/tagline/description.

See [`templates/README.md`](templates/README.md).

### Catalog on disk (not runtime media)

| Path | What |
|---|---|
| `templates/` | HTML templates + packs (shared catalog) |
| `variants/` | Starter JSON only (seed source for new brands) |
| `brands/<slug>/` | Optional seed logo files — uploaded to object storage on brand create |

Runtime media (Recraft, logos, composed PNG/MP4) is **only** in object storage. `STORAGE_BACKEND=local` is removed.

## Env

| Var | Purpose |
|---|---|
| `DATABASE_URL` | SQLAlchemy URL (`postgresql+psycopg://…`) |
| `JWT_SECRET` | Sign access tokens |
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` | LLM |
| `FAL_KEY` | Recraft |
| `STORAGE_BACKEND` | Must be `s3` |
| `STORAGE_BUCKET` / keys / `STORAGE_ENDPOINT_URL` | S3-compatible store (e.g. Cloudflare R2) |
| `STORAGE_PUBLIC_BASE_URL` | Browser-reachable base URL for the bucket |
| `STORAGE_ADDRESSING_STYLE` | `auto` for AWS/R2 |
