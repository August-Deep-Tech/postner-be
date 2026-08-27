# Postner BE

Multi-tenant FastAPI backend: register → brands → draft post → Recraft images → compose PNG → polish.

## Stack

- **Auth:** email/password + JWT
- **DB:** Postgres (Docker) — tenants, brands, **brand variants**, posts, revisions
- **Assets:** Docker volume `/app/output`; composed PNG/MP4 → object storage when `STORAGE_BACKEND=s3`
- **Packs/templates:** on disk (shared catalog). Starter variant JSON under `variants/` is **seeded into each brand** on create.

## Quick start (Docker)

```bash
cp .env.example .env
# set ANTHROPIC_API_KEY and/or OPENAI_API_KEY, FAL_KEY, JWT_SECRET

docker compose up --build
```

API: http://localhost:8001/docs

Compose brings up **api** + **db** (Postgres on host port **5434** → container 5432, to avoid clashing with other local Postgres). Named volumes: `pgdata`, `output`.

## Local (without Docker API)

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium

# Start Postgres (e.g. via compose)
docker compose up db -d

cp .env.example .env
# DATABASE_URL=postgresql+psycopg://postner:postner@localhost:5434/postner

alembic upgrade head
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Product flow

1. `POST /auth/register` `{ "email", "password", "name?" }` → JWT
2. `GET/POST/PATCH /brands` (Bearer token; user creates brands — no demo seed)
3. `POST /posts` — scrape + LLM draft (`with_images` optional)
4. `POST /posts/{id}/images` — Recraft source photos (reuse unless `regenerate`)
5. `POST /posts/{id}/compose` — **final rendered PNG(s)** (`ensure_images` gap-fills)
6. Optional: `animate` | `resize` | `redesign` | `rewrite` | `undo` | `feedback`

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
| GET | `/posts/{id}` | Full state (tenant-scoped) |
| POST | `/posts/{id}/images` | Recraft (`pages?`, `regenerate`) |
| POST | `/posts/{id}/compose` | Final PNG (`pages?`, `ensure_images`) |
| POST | `/posts/{id}/animate` | MP4 (`motion_preset`) |
| POST | `/posts/{id}/resize` | Recompose at `format` |
| POST | `/posts/{id}/redesign` | `variant_id` and/or `propose: true` (auto color skin), then recompose |
| POST | `/posts/{id}/rewrite` | Caption/text or `suggest` re-LLM |
| POST | `/posts/{id}/undo` | Restore previous revision snapshot |
| GET | `/posts/{id}/revisions` | List `{ id, kind, version, created_at }` |
| POST | `/posts/{id}/feedback` | `decision`, `reasons[]`, `note` |

`format`: `ig_feed` | `ig_portrait` | `ig_story` | `tiktok` | `fb_post` | **`x_post`** (1600×900)

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

### Still on local disk

| Path | What |
|---|---|
| `templates/` | HTML templates + packs (shared catalog; proposed packs also write here) |
| `variants/` | Starter JSON only (seed source for new brands) |
| `brands/<slug>/` | Optional logo files referenced by DB brands |
| `output/<run>/` | Recraft images, filled HTML, local PNG/MP4 workspace (`Post.asset_dir`) |

Composed finals upload via `ObjectStorage` when `STORAGE_BACKEND=s3`; otherwise URLs stay local paths.

## Env

| Var | Purpose |
|---|---|
| `DATABASE_URL` | SQLAlchemy URL (`postgresql+psycopg://…`) |
| `JWT_SECRET` | Sign access tokens |
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` | LLM |
| `FAL_KEY` | Recraft |
