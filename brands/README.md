# Brands

File-based brand profiles (same idea as `variants/`). Shape is migration-friendly for a future DB.

## Layout

```
brands/
  <id>/
    brand.json
    logo.png     # optional
```

## `brand.json`

```json
{
  "id": "gradde",
  "name": "Gradde",
  "tagline": "AI for teachers",
  "description": "Helps teachers cut busywork while keeping the human touch in the classroom.",
  "logo": "logo.png"
}
```

| Field | Used for |
|---|---|
| `name` | Template `{{brand}}` on slides |
| `tagline` | Template `{{tagline}}` (when the layout includes it) |
| `description` | LLM voice / “what they do” only |
| `logo` | Filename next to `brand.json` → `{{logo_url}}` at render |

## API

- `GET /brands` — list
- `GET /brands/{id}` — one profile
- `POST /brands` — create/update JSON (`{ "id", "name", "tagline", "description", "logo" }`)

Put a logo file in the brand folder yourself (or set `logo` after copying the file). Multipart upload can come later.

## Generate

```json
{
  "url": "https://example.com/blog/post",
  "pack_id": "gentle_reminders",
  "brand_id": "gradde"
}
```

Optional one-off name override: `"brand": "Other Name"` (still uses profile tagline/description/logo when `brand_id` is set).
