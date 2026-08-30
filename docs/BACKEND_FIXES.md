# Backend fixes — HTML preview and render pipeline

**Verified against `c3d7bbd` (2026-08-30).** Every line reference below was
checked against that tree.

Two commits reshaped this area recently. `afaff00` split `compose_post` (HTML
fill) from `render_post` (Playwright + upload), and `c3d7bbd` moved every
runtime asset into object storage, deleting the `file://` scheme from the
codebase. Findings that those commits changed or resolved are marked in place.

Two kinds of issue are collected here:

- **[A] Correctness** — downloaded PNGs come out with no photos. Reproducible
  today on the local stack.
- **[B] Security** — six findings in the template filler and the render path.
  Finding B1 is the root cause and one change closes it.

None of these are frontend fixes. The frontend renders preview markup in a
`sandbox=""` iframe under a restrictive CSP, but that is defence in depth — it
does nothing for the Playwright sink, which runs inside this service.

---

# Part A — Rendered PNGs are missing their photos

**Severity: High (broken output).** The preview shows the photos; the downloaded
file does not. Same markup, two renderers, one URL that means different things
in each.

## Cause

Image URLs are baked into the HTML from `STORAGE_PUBLIC_BASE_URL`, which is
`http://localhost:9000/postner` on the local stack (`docker-compose.yml:59`).
`S3CompatibleStorage.upload()` returns `f"{public_base_url}/{key}"`
(`s3.py:76,90`) and `compose_post` substitutes that into the markup.

`localhost:9000` then resolves differently depending on who loads the page:

| Renderer | `localhost:9000` resolves to | Result |
|---|---|---|
| The user's browser (preview iframe) | the host, where MinIO publishes 9000 | images load |
| Playwright, inside `backend-api-1` | the API container itself — no MinIO there | connection refused |

Measured from inside the running container:

```
http://localhost:9000/postner/   -> UNREACHABLE: [Errno 111] Connection refused
http://minio:9000/postner/       -> HTTP 200
```

`screenshot_html` then screenshots anyway. `wait_until="networkidle"` treats
failed requests as settled and nothing raises, so the PNG comes out with correct
text, colour and layout, and no photos.

This is local-stack specific: in production with a real CDN
(`https://cdn.example.com`) the container resolves that host fine and the bug
disappears — which is exactly why it can ship unnoticed.

## Fix

The renderer needs an **internal** URL where the browser needs a **public** one.
Options, best first:

1. **Rewrite storage URLs to the internal endpoint just before rendering** —
   swap `STORAGE_PUBLIC_BASE_URL`'s origin for `STORAGE_ENDPOINT_URL`'s
   (`http://minio:9000`) in `render_post` / `screenshot_html`. Keeps
   `html_source` browser-correct and touches only the render path.
2. **Inline each image as a `data:` URI before screenshotting** — no network at
   render time at all, and it composes well with disabling JS (see B4). Heavier,
   but the most robust.
3. A host alias so `localhost:9000` resolves inside the container. Fragile;
   aliasing `localhost` is a poor idea.

Whichever is chosen, **make it fail loudly**. A render that silently drops the
photos is worse than one that errors:

```python
failures: list[str] = []
page.on("requestfailed", lambda r: failures.append(r.url))
# ... after screenshot
if failures:
    raise RuntimeError(f"Assets failed to load during render: {failures}")
```

Or assert every `<img>` came back with a non-zero `naturalWidth` before writing
the PNG.

---

# Part B — Security

| # | Finding | File | Severity |
|---|---|---|---|
| B1 | Placeholder substitution does no HTML escaping | `app/templates/engine.py:17` | **High** |
| B2 | Variant CSS values written raw into `:root{}` | `app/templates/engine.py:102` | **High** |
| B3 | HTML endpoint serves `text/html` with no CSP | `app/posts/routes.py:207` | **High** (with the FE proxy) |
| B4 | Playwright renders untrusted markup with JS on, no egress limits | `app/render/screenshot.py:25` | Medium (was High) |
| B5 | `RewriteRequest.text` accepts arbitrary keys/values | `app/posts/routes.py:69` | Medium |
| B6 | `html_source` duplicated into every response, including the list | `app/posts/preview.py:14`, `routes.py:140` | Low (was Medium) |

---

## B1. Escape at substitution (root cause)

`fill_placeholders` is a raw regex `sub` into an HTML document:

```python
def fill_placeholders(html: str, values: dict[str, str]) -> str:
    def _repl(match): return values.get(match.group(1), "")
    return _PLACEHOLDER_RE.sub(_repl, html)
```

The sinks are element **and** attribute context:

```html
<h1 class="title">{{title}}</h1>          <!-- templates/packs/*/pages/*.html:54 -->
<img src="{{image_url}}" alt="" />        <!-- templates/basic.html:133 -->
<img class="logo-img" src="{{logo_url}}"  <!-- templates/basic.html:138 -->
```

Three taint sources reach it:

- **LLM slide text derived from the scraped URL** (`generate_carousel` →
  `content.slides` → `fields`). Unauthenticated: anyone who controls a page a
  user drafts from can prompt-inject `<script>` into a slide title.
- **`RewriteRequest.caption` / `text`** — authenticated, arbitrary strings,
  straight into `content` and then into placeholders.
- **Brand `logo_url`** — lands inside `src="…"`, so `x" onerror="…` breaks the
  attribute. Now stored as a public object URL up to 2048 chars
  (`006_brand_logo_url`), so there is more room for a payload than before.

### Fix

```python
import html as html_lib
from urllib.parse import urlsplit

_URL_KEYS = {"image_url", "logo_url", "cta_link"}
_SAFE_URL_SCHEMES = {"https", "http"}  # http for local MinIO; no file:, no data:


def _safe_url(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    if urlsplit(raw).scheme.lower() not in _SAFE_URL_SCHEMES:
        return ""
    return html_lib.escape(raw, quote=True)


def fill_placeholders(html: str, values: dict[str, str]) -> str:
    """Replace {{key}} tokens; unknown keys become empty string. Values escaped."""

    def _repl(match: re.Match[str]) -> str:
        key = match.group(1)
        raw = values.get(key)
        if raw is None:
            return ""
        text = str(raw)
        if key in _URL_KEYS or key.startswith("image_") or key.endswith("_url"):
            return _safe_url(text)
        return html_lib.escape(text, quote=True)

    return _PLACEHOLDER_RE.sub(_repl, html)
```

The `image_` / `_url` prefix and suffix checks cover the dynamic keys
`packs.py:157-160` generates (`image_2`, `image_url_2`, …).

Since `c3d7bbd` every asset reference is an http(s) object-storage URL, so the
scheme allowlist can be strict — `file:` and `data:` are no longer produced
anywhere and should be rejected.

**This one change closes both sinks** — the browser preview and the Playwright
render — because both consume the same filled string.

No visual regression: every text placeholder sits in element content, where
`&amp;` renders as `&`. The `white-space: pre-line` templates keep their newlines.

---

## B2. Validate variant CSS values

`apply_color_variant` (`engine.py:86-118`) writes values verbatim into a
`:root{}` block at line 102, so a value of
`red; } </style><script>…</script><style>` escapes the style element. These
values are **LLM-generated** by `propose_and_save_variants` — the same
prompt-injection source as B1.

```python
_CSS_KEY_RE = re.compile(r"^--[a-z0-9-]{1,64}$", re.IGNORECASE)
_CSS_VALUE_RE = re.compile(r"^[#\w\s(),.%/+-]{1,120}$")
_CSS_FORBIDDEN = ("url(", "expression", "@import", "javascript:", "</", "{", "}", ";")


def _safe_css_value(value: str) -> str | None:
    v = str(value).strip().rstrip(";").strip()
    if any(token in v.lower() for token in _CSS_FORBIDDEN):
        return None
    return v if _CSS_VALUE_RE.match(v) else None
```

Drop any pair failing `_CSS_KEY_RE` / `_safe_css_value` before it reaches
`existing[key] = value`. The value pattern allows `(` and `)` for `rgb()` /
`hsl()`; `url(` is caught by the forbidden-token list.

---

## B3. Send the HTML endpoint out sandboxed

`GET /posts/{id}/pages/{page_id}/html` (`routes.py:188-207`) returns unescaped,
partly attacker-influenced markup as `text/html` with no security headers.

Direct navigation is mostly self-limiting — the route needs a Bearer token,
which a browser navigation will not carry. The real path is the frontend proxy,
which attaches the session token; if it forwarded the upstream content-type,
this would become `text/html` on the *app* origin, where the httpOnly session
cookie lives and the proxy is a credentialed gateway to the whole API. That is
app-origin XSS: full tenant read/write without ever stealing the token.

The frontend has since blocked that specific route by refusing to forward
non-JSON responses, but this endpoint should not depend on one client's
discipline to be safe.

```python
_PREVIEW_CSP = (
    "sandbox; "
    "default-src 'none'; "
    f"img-src {settings.storage_public_base_url or 'https:'}; "
    "style-src 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src https://fonts.gstatic.com; "
    "frame-ancestors 'none'"
)

return HTMLResponse(
    content=html,
    media_type="text/html; charset=utf-8",
    headers={
        "Content-Security-Policy": _PREVIEW_CSP,
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        "Cache-Control": "no-store",
    },
)
```

The bare `sandbox` directive makes the response behave as a sandboxed document —
scripts never execute, even on direct navigation, and even if B1 is not yet
fixed. `'unsafe-inline'` for styles is required by the templates' own `<style>`
blocks.

`img-src` must name the storage origin rather than a blanket `https:`: the local
stack serves MinIO over plain **http** on `:9000`, which `https:` alone would
block. The frontend hit exactly this and now reads the same setting to build its
own policy — same root cause as Part A, in a different guise.

Set `frame-ancestors` to the configured `CORS_ORIGINS` if the frontend ever
frames this endpoint by URL; keep `'none'` while it uses `html_content` +
`srcdoc`, which is what it does today.

---

## B4. Harden the Playwright render

**Partly addressed by `c3d7bbd`.** `screenshot_html` now calls
`page.set_content(html)` rather than `page.goto(file://…)`, and writes no markup
to disk. The render is no longer on a `file://` origin, which removes the local
file-read surface and the temp-file trail. The original finding overstated what
remains; the severity drops accordingly.

What is still open, at `screenshot.py:25-30`: the context runs with **scripts
enabled**, no request interception, and no navigation timeout beyond
`wait_until="networkidle"`. Injected script still gets egress from inside the
trust boundary — the cloud metadata endpoint, the API on localhost, Postgres and
MinIO on the compose network — and an unbounded window to use it.

```python
_ALLOWED_HOSTS = {"fonts.googleapis.com", "fonts.gstatic.com"}
# plus the storage host, parsed from settings.storage_public_base_url


async def _guard(route, request):
    host = urlsplit(request.url).hostname or ""
    if host in _allowed_hosts(settings):
        await route.continue_()
    else:
        await route.abort()


context = await browser.new_context(
    viewport={"width": width, "height": height},
    device_scale_factor=1,
    java_script_enabled=False,
)
await context.route("**/*", _guard)
page = await context.new_page()
await page.set_content(html, wait_until="networkidle")
```

The allowlist must include the storage host — page images are fetched over the
network rather than read off disk, so an over-tight allowlist reproduces Part A.
Landing A and B4 together is sensible: both hinge on which host the renderer is
allowed to reach.

**`java_script_enabled=False` is the clean kill for the whole SSRF class**, but
it still breaks one template: `templates/lifestyle_day.html:221` runs JS to clean
the caption and split it across four staggered slots. Port that logic into the
Python fill step. Two payoffs: JS can then be disabled in both renderers, and the
browser preview (sandboxed with no `allow-scripts`) stops diverging from the PNG
for that template. Until then, the route allowlist and a timeout are worth
landing on their own.

Complementary, outside the code: deny the render container egress to
`169.254.169.254` and to internal service names.

---

## B5. Reject markup at the API boundary

`RewriteRequest.text: dict[str, Any]` (`routes.py:69`) merges unbounded,
unvalidated keys into `post.content`, which later reach placeholders. The API
should accept **field values, never markup**:

```python
_ALLOWED_TEXT_KEYS = {
    "ig_fb_caption", "tiktok_script", "visual_prompt", "overlay_text",
    "tagline", "brand", "slides",
}
_MARKUP_RE = re.compile(
    r"<\s*/?\s*(script|iframe|style|svg|object|embed|link|meta)\b|javascript:",
    re.IGNORECASE,
)
```

Reject unknown keys with 422 and any string value matching `_MARKUP_RE`. Same
check on the `slides` list items. This also keeps the door shut on a future
WYSIWYG editor posting HTML back — that would be stored XSS plus a server-side
renderer that executes it.

---

## B6. Stop duplicating markup into every response

**Rewritten since the original review.** The finding was that `html_source`
leaked `file:///app/runs/…` container paths. `c3d7bbd` removed the `file://`
scheme entirely, so that disclosure is gone.

What replaced it is waste rather than exposure. `page_preview_html`
(`preview.py:6-11`) returns `html_source` unchanged, and
`enrich_composed_with_html` (`preview.py:14`) adds it as `html_content` **without
removing `html_source`**. The two fields are byte-identical, so every response
carries each page's full markup twice.

`_post_response` (`routes.py:140`) applies that to **every** response including
`GET /posts`, so one review-queue load returns two copies of the markup for every
page of every post, up to the 50-post default limit.

- Strip `html_source` in the response mapper; keep it in the DB, where
  `render_post` and `animate_post` read it.
- Gate enrichment to single-post reads, or put it behind `?include=html`.
- `_add_revision` snapshots `composed` (`service.py:139`), which contains
  `html_source`, so `post_revisions.payload` grows by a full document set per
  edit. Consider excluding it from the snapshot.

---

# Verification

```python
# A — the render must not silently drop assets
async def test_render_fails_when_images_unreachable(monkeypatch):
    # point storage at an unroutable host, then render
    with pytest.raises(HTTPException):
        await render_post(db, post=post, settings=settings)

# B1 — escaping
def test_slide_title_is_escaped():
    html = fill_placeholders("<h1>{{title}}</h1>", {"title": "</h1><script>alert(1)</script>"})
    assert "<script>" not in html
    assert "&lt;script&gt;" in html

# B1 — url scheme allowlist
def test_non_http_image_url_dropped():
    html = fill_placeholders('<img src="{{image_url}}">', {"image_url": "javascript:alert(1)"})
    assert "javascript:" not in html

# B2 — variant breakout
def test_variant_css_breakout_rejected():
    out = apply_color_variant(":root{--bg:#fff;}", {"--bg": "red; } </style><script>x</script>"})
    assert "<script>" not in out

# B5 — markup rejected at the boundary
def test_rewrite_rejects_markup():
    r = client.post(f"/posts/{pid}/rewrite", json={"caption": "<script>x</script>"})
    assert r.status_code == 422

# B6 — markup returned once, and not on the list endpoint
def test_response_does_not_duplicate_markup():
    page = client.get(f"/posts/{pid}").json()["composed"]["pages"][0]
    assert "html_content" in page and "html_source" not in page
    assert "html_content" not in client.get("/posts").json()["posts"][0]["composed"]["pages"][0]
```

```bash
# A — what the container can actually reach
docker exec backend-api-1 python -c "
import urllib.request
for u in ['http://localhost:9000/postner/', 'http://minio:9000/postner/']:
    try: print(u, urllib.request.urlopen(u, timeout=5).status)
    except Exception as e: print(u, 'UNREACHABLE', e)"

# B3 — headers on the preview endpoint
curl -sI -H "Authorization: Bearer $TOKEN" \
  "$API/posts/$POST_ID/pages/main/html" | grep -i "content-security-policy\|x-content-type"
```

---

# Cross-cutting, for the frontend

Already shipped on the FE side, listed so both halves are visible:

- Preview markup renders only in `<iframe srcDoc sandbox="">` — never
  `dangerouslySetInnerHTML`, never `allow-scripts` with `allow-same-origin`.
  Verified against a live page: an injected `<script>` and an `onerror` handler
  both fail to execute, and the parent cannot read into the frame.
- CSP and security headers are set, with `img-src` naming the storage origin
  from `STORAGE_PUBLIC_BASE_URL` for the reason given in B3.
- The BFF proxy refuses to forward non-JSON responses, so the endpoint in B3
  cannot be served from the app origin.
