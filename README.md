# Postner BE

Multi-tenant FastAPI backend: register → brands → draft post → Recraft images → compose PNG → polish.

## Stack

- **Auth:** email/password + JWT (`AUTH_DISABLED=1` for local smoke)
- **DB:** Postgres (Docker)
- **Assets:** Docker volume `/app/output`
- **Packs/templates/variants:** on disk (shared catalog)

## Quick start (Docker)

```bash
cp .env.example .env
# set ANTHROPIC_API_KEY and/or OPENAI_API_KEY, FAL_KEY, JWT_SECRET
# optional: AUTH_DISABLED=1 for legacy /generate without login

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
6. Optional: `animate` | `resize` | `redesign` | `rewrite` | `feedback`

### Auth

| Method | Path | Notes |
|---|---|---|
| POST | `/auth/register` | Creates user + personal tenant |
| POST | `/auth/login` | Returns access JWT |
| GET | `/auth/me` | User + active tenant |

JWT claims: `sub` (user_id), `tenant_id`. Set `Authorization: Bearer <token>` on brands/posts.

`AUTH_DISABLED=1` bypasses auth with a fixed local tenant (also used for legacy smoke).

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
| POST | `/posts/{id}/feedback` | `decision`, `reasons[]`, `note` |

`format`: `ig_feed` | `ig_portrait` | `ig_story` | `tiktok` | `fb_post` | **`x_post`** (1600×900)

### Packs + variants (design propose)

Packs are multi-page templates; variants are shared CSS color skins for a template **or** pack.

| Method | Path | Role |
|---|---|---|
| GET | `/packs` | List packs |
| POST | `/packs/propose` | Assemble new packs from page catalog; `with_variants` pairs color skins |
| GET | `/variants` | List variant ids |
| POST | `/variants/propose` | Palettes for `pack_id` **or** `template_id` (XOR); optional `brand_id` |

See [`templates/README.md`](templates/README.md).

### Legacy

`POST /generate` — one-shot scrape → image → compose (file brands). Intended for local/dev, especially with `AUTH_DISABLED=1`.

## Env

| Var | Purpose |
|---|---|
| `DATABASE_URL` | SQLAlchemy URL (`postgresql+psycopg://…`) |
| `JWT_SECRET` | Sign access tokens |
| `AUTH_DISABLED` | `1` = skip Bearer auth |
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` | LLM |
| `FAL_KEY` | Recraft |
