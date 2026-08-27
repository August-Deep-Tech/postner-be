import json

STYLE_GUIDE = """
Brand / visual style for social posts:
- Warm, human, approachable — education-adjacent, never cold or corporate-sterile.
- No robotic / generic AI imagery (no glowing brains, circuit faces, stock-robot metaphors).
- Prefer scenes with people, everyday tools, or simple illustrative metaphors.
- Do not put marketing copy or long captions into the image itself.
- In-image text only if the post angle is explicitly a quote or stat card — and then keep it short.
- Palette should feel warm (creams, soft terracotta, sage, muted blues) unless the page content clearly needs otherwise.
""".strip()

POST_SYSTEM_PROMPT = f"""You are a social content writer for a product brand.
Given scraped page text, produce ONE ready-to-review social draft pack.

{STYLE_GUIDE}

Return ONLY valid JSON with these keys:
- post_type: short label for the angle (e.g. myth-busting, how-to, feature-spotlight, pricing-clarity)
- page_type: one of blog | feature | pricing | homepage (confirm or correct the hint)
- ig_fb_caption: full Instagram/Facebook caption ready to paste (include light CTA, no hashtag spam)
- tiktok_script: beat-by-beat spoken script for a short TikTok
- visual_prompt: short image-generation prompt for Recraft V3 matching the style guide (no long text in the image)
- overlay_text: very short line (max ~12 words) for the designed template overlay — NOT the full caption

Do not invent product claims that are not supported by the page text.
If a Brand profile is provided in the user message, write in that brand's voice and never invent a different brand or studio name.
""".strip()


def build_post_user_prompt(
    *,
    url: str,
    title: str,
    page_type_hint: str,
    text: str,
    brand_name: str = "",
    brand_tagline: str = "",
    brand_description: str = "",
) -> str:
    brand_block = ""
    if brand_name:
        brand_block = f"""
Brand profile (locked — use this identity):
- Name: {brand_name}
- Tagline: {brand_tagline or "(none)"}
- About: {brand_description or "(none)"}
"""
    return f"""Source URL: {url}
Page title: {title}
Page type hint: {page_type_hint}
{brand_block}
Page text:
---
{text}
---
""".strip()


VARIANT_SYSTEM_PROMPT = f"""You propose color/accent CSS variable sets for an existing social-post design.
The design may be a single-page template OR a multi-page pack (ordered page templates sharing one palette).
Layout and fonts are LOCKED — you must ONLY propose CSS custom properties (colors / accent shape colors).
Do not suggest fonts, spacing, or structural changes.

{STYLE_GUIDE}

Return ONLY valid JSON:
{{
  "variants": [
    {{
      "id": "snake_case_name",
      "label": "Human label",
      "css_vars": {{
        "--bg": "#hex",
        "--text": "#hex",
        "--accent": "#hex",
        "--accent-shape": "#hex"
      }}
    }}
  ]
}}

Use distinct but on-brand palettes. Keep contrast readable (text on bg).
You MUST include every --* color key listed in "Required CSS keys" (and any extras you see in the HTML), but never font-* properties.
""".strip()


def build_variant_user_prompt(
    *,
    design_html: str,
    count: int,
    design_label: str = "template",
    required_css_keys: list[str] | None = None,
    brand_name: str = "",
    brand_tagline: str = "",
    brand_description: str = "",
) -> str:
    snippet = design_html
    if len(snippet) > 12000:
        snippet = snippet[:12000] + "\n<!-- truncated -->"
    keys = required_css_keys or []
    keys_block = ", ".join(keys) if keys else "(infer from HTML :root)"
    brand_block = ""
    if brand_name:
        brand_block = f"""
Brand (bias palettes toward this voice; do not invent a different brand):
- Name: {brand_name}
- Tagline: {brand_tagline or "(none)"}
- About: {brand_description or "(none)"}
"""
    return f"""Propose exactly {count} color variants for this {design_label}.

Required CSS keys (include ALL of these in every variant.css_vars): {keys_block}
{brand_block}
Design HTML/CSS:
---
{snippet}
---
""".strip()


PACK_PROPOSE_SYSTEM_PROMPT = f"""You propose social carousel packs.
A pack is a multi-page template: an ordered sequence of page HTML layouts that share one css_vars palette.
You MUST only assemble packs from the provided page catalog (clone existing page templates by source id).
Do NOT invent new HTML layouts or source ids that are not in the catalog.

{STYLE_GUIDE}

Return ONLY valid JSON:
{{
  "packs": [
    {{
      "id": "snake_case_name",
      "label": "Human label",
      "description": "one sentence",
      "format": "ig_portrait",
      "css_vars": {{
        "--bg": "#hex",
        "--text": "#hex",
        "--accent": "#hex",
        "--accent-shape": "#hex",
        "--on-accent": "#hex"
      }},
      "pages": [
        {{
          "id": "cover",
          "source": "gentle_reminders/01_cover.html",
          "role": "cover",
          "tags": ["cover"],
          "images": 0,
          "fields": ["brand", "title", "subtitle"]
        }}
      ],
      "sequence": ["cover"]
    }}
  ]
}}

Rules:
- Each pages[].source MUST be a catalog source string.
- pages[].id must be unique within the pack; sequence lists those ids in order.
- Prefer 3–6 pages: one cover, one or more body, one close.
- Copy role/tags/images/fields from the catalog entry for that source (you may trim tags lightly).
- css_vars must include keys needed by the chosen pages (at least --bg, --text, --accent, --accent-shape; add --on-accent / --muted when catalog pages use them).
- Pack ids must be distinct snake_case names.
""".strip()


def build_pack_propose_user_prompt(
    *,
    catalog: list[dict],
    count: int,
    format_name: str,
    brief: str = "",
    brand_name: str = "",
    brand_tagline: str = "",
    brand_description: str = "",
) -> str:
    catalog_json = json.dumps(catalog, indent=2)
    if len(catalog_json) > 14000:
        catalog_json = catalog_json[:14000] + "\n/* truncated */"
    brand_block = ""
    if brand_name:
        brand_block = f"""
Brand profile:
- Name: {brand_name}
- Tagline: {brand_tagline or "(none)"}
- About: {brand_description or "(none)"}
"""
    brief_line = brief.strip() or "Editorial carousel suitable for the brand."
    return f"""Propose exactly {count} distinct packs for format={format_name}.

Brief: {brief_line}
{brand_block}
Page catalog (choose sources from here only):
{catalog_json}
""".strip()


CAROUSEL_SYSTEM_PROMPT = f"""You write multi-slide social carousels for a brand.
Given scraped page text AND a fixed pack page schema, fill EVERY sequenced slide.

{STYLE_GUIDE}

Rules:
- Follow the pack page list EXACTLY — one object per page_id in order.
- Only populate the fields listed for that page. Use empty string for unused optional fields.
- Put intentional newlines in title/subtitle/body where line breaks will look good on a poster (white-space: pre-line).
- Keep titles short enough to fit a 1080x1350 slide (roughly 3–6 short lines max for big serif titles). Prefer ALL CAPS for lifestyle tip titles when the pack style calls for it.
- Body copy: 1–3 short sentences. No hashtags in slide fields.
- brand: ALWAYS use the locked Brand profile name from the user message when provided. Never invent a studio or agency name.
- series: short ALL-CAPS category label shared across the carousel (e.g. HOMESCHOOL TIPS). Same value on every slide that has the field.
- script: short cursive lead-in for cover only (e.g. How to) — not the whole title.
- page_number: zero-padded index string without trailing period when required ("01", "02", "03").
- next: next slide number as zero-padded string for tip pills ("02", "03") — not "SWIPE".
- handle: social handle like @BrandName when the close slide needs it.
- ig_fb_caption: full caption for the carousel post (paste-ready).
- tiktok_script: optional short spoken script summarizing the carousel.
- visual_prompt: top-level fallback. ALSO set slide.visual_prompt for EVERY page with images > 0 — warm lifestyle photo, no text in image, distinct scene per slide.

Return ONLY valid JSON:
{{
  "post_type": "...",
  "page_type": "blog|feature|pricing|homepage",
  "brand": "...",
  "ig_fb_caption": "...",
  "tiktok_script": "...",
  "visual_prompt": "",
  "slides": [
    {{ "page_id": "cover", "series": "...", "script": "How to", "title": "...", "visual_prompt": "..." }}
  ]
}}
""".strip()


def build_carousel_user_prompt(
    *,
    url: str,
    title: str,
    page_type_hint: str,
    text: str,
    pack_id: str,
    pack_label: str,
    default_brand: str,
    page_schema: list,
    brand_name: str = "",
    brand_tagline: str = "",
    brand_description: str = "",
) -> str:
    schema_json = json.dumps(page_schema, indent=2)
    locked_name = brand_name or default_brand or ""
    brand_block = ""
    if brand_name or brand_description or brand_tagline:
        brand_block = f"""
Brand profile (locked — use this identity on every slide):
- Name: {brand_name or default_brand}
- Tagline: {brand_tagline or "(none)"}
- About: {brand_description or "(none)"}
Set JSON "brand" and every slide's brand field to exactly: {locked_name}
"""
    elif default_brand:
        brand_block = f"\nDefault brand name (use if no better fit): {default_brand}\n"
    return f"""Source URL: {url}
Page title: {title}
Page type hint: {page_type_hint}
Pack: {pack_id} ({pack_label})
{brand_block}
Pack page schema (fill every page_id, only listed fields):
{schema_json}

Page text:
---
{text}
---
""".strip()
