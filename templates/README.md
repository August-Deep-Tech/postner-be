# Template contract

Packs are **multi-page templates** (ordered HTML pages + shared `css_vars`).
Single-page files in this folder are one-page templates. Image generation
style (`realistic` / `illustration` / `graphics`) lives on the post, not
on the template — Recraft’s `style` param and the visual-prompt hint follow
`posts.image_style`.

| Route | Purpose |
|---|---|
| `POST /packs/propose` | New packs from existing page HTML in this catalog |

---

## Single-page templates

Drop HTML files in this folder (e.g. `basic.html`). The API loads them by
`template_id` (filename without `.html`).

### Required placeholders

| Placeholder | Purpose |
|---|---|
| `{{caption}}` | Short overlay text (`overlay_text` from generation) |
| `{{image_url}}` | Absolute http(s) URL to the Recraft image (object storage) |
| `{{cta_link}}` | Optional — source page URL |
| `{{brand}}` | Brand profile name (`brand_id`) |
| `{{tagline}}` | Brand tagline |
| `{{logo_url}}` | Brand logo http(s) URL (empty if none) |

### CSS variables

Define palette/accents on `:root` only. Example:

```css
:root {
  --bg: #fff8f0;
  --text: #1a1a1a;
  --accent: #e07a5f;
  --accent-shape: #81b29a;
}
```

Layout and `font-family` stay as authored in the HTML.

### Locked font

Include a Google Fonts `<link>` in the HTML, or omit it and the render engine
injects `LOCKED_FONT_*` from env.

### Canvas

Size `#canvas` to the social format. Playwright sets the viewport from the size
registry (`ig_feed` = 1080×1080, `ig_portrait` = 1080×1350, `ig_story` = 1080×1920,
`x_post` = 1600×900).

### Included single templates

| File | Best `format` | Notes |
|---|---|---|
| `basic.html` | `ig_feed` / `fb_post` | Brand card: headline + image + logo/name |
| `lifestyle_day.html` | `ig_story` / `tiktok` | Full-bleed photo; JS splits caption; site pin only |

---

## Template packs (multi-page templates)

A pack is the multi-page form of a template: shared palette + sequenced page HTML.

```
packs/<pack_id>/
  pack.json
  pages/
    01_cover.html
    ...
```

### `pack.json`

- `format` — default canvas size for every page
- `css_vars` — shared palette applied at render
- `pages[]` — each page: `id`, `file`, `role` (`cover` \| `body` \| `close`), `tags[]`, `images` (0 = text-only), `fields[]`
- `sequence` — ordered page ids for one carousel post

### Pack page placeholders

Vary by page; use `white-space: pre-line` so newlines in copy become line breaks.

| Placeholder | Typical pages |
|---|---|
| `{{brand}}` | all |
| `{{tagline}}` | optional (from brand profile) |
| `{{logo_url}}` | optional (from brand logo file) |
| `{{title}}` | cover, body, close |
| `{{subtitle}}` | cover |
| `{{body}}`, `{{body_2}}`, `{{body_emphasis}}` | body |
| `{{page_number}}` | numbered body slides |
| `{{cta}}` | close |
| `{{image_url}}` | only if `images` > 0 |

### Included packs

| Pack | Format | Pages | Images |
|---|---|---|---|
| `gentle_reminders` | `ig_portrait` (1080×1350) | 6 (cover → intro → split L → solid → split R → close) | 0 (text-only) |
| `lifestyle_tips` | `ig_portrait` (1080×1350) | 4 (cover peek → tip L → tip R → close handle) | 1 per page |

### Propose packs

```http
POST /packs/propose
{
  "brand_id": "gradde",
  "format": "ig_portrait",
  "count": 2,
  "brief": "calm wellness carousel"
}
```

Builds new packs by **cloning existing page templates** from the catalog (does not invent HTML).

### Generate / posts with a pack

```http
POST /posts
{ "url": "https://example.com/blog/post", "pack_id": "gentle_reminders", "brand_id": "<brand-id>", "image_style": "realistic" }
```

- Skips Recraft when all pages have `images: 0`
- `GET /packs` lists available packs (including proposed ones)
- `image_style` is `realistic` | `illustration` | `graphics` (omit/`null` picks one at random and stores it)
- Redesign with `{ "image_style": "illustration", "regenerate_images": true }` to switch Recraft style
