# HTML pipeline — security fixes

**Verified against `c3d7bbd` (2026-08-30).**

Two commits reshaped this area since the review was written. `afaff00` split
`compose_post` (HTML fill) from `render_post` (Playwright + upload), and
`c3d7bbd` moved every runtime asset into object storage, deleting the `file://`
scheme from the codebase entirely.

Neither touched `fill_placeholders` or `apply_color_variant`. Findings 1, 2, 3
and 5 below are unchanged from the original review and confirmed still present
at the line numbers given. Findings 4 and 6 were partly overtaken by `c3d7bbd`
and have been rewritten; what remains of each is described in place.

None of these are frontend fixes. The frontend renders preview markup in a
`sandbox=""` iframe under a restrictive CSP, but that is defence in depth — it
does nothing for the Playwright sink, which runs inside this service.

---

## Findings

| # | Finding | File | Severity |
|---|---|---|---|
| 1 | Placeholder substitution does no HTML escaping | `app/templates/engine.py:17` | **High** |
| 2 | Variant CSS values written raw into `:root{}` | `app/templates/engine.py:102` | **High** |
| 3 | HTML endpoint serves `text/html` with no CSP | `app/posts/routes.py:207` | **High** (with the FE proxy) |
| 4 | Playwright renders untrusted markup with JS on, no egress limits | `app/render/screenshot.py:25` | Medium (was High) |
| 5 | `RewriteRequest.text` accepts arbitrary keys/values | `app/posts/routes.py:69` | Medium |
| 6 | `html_source` duplicated into every response, including the list | `app/posts/preview.py:14`, `routes.py:140` | Low (was Medium) |

---

## 1. Escape at substitution (root cause)

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
  attribute. Now stored as a public object URL up to 2048 chars (`006_brand_logo_url`),
  so there is more room for a payload than before, not less.

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

## 2. Validate variant CSS values

`apply_color_variant` (`engine.py:86-118`) writes values verbatim into a
`:root{}` block at line 102, so a value of
`red; } </style><script>…</script><style>` escapes the style element. These
values are **LLM-generated** by `propose_and_save_variants` — the same
prompt-injection source as finding 1.

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

## 3. Send the HTML endpoint out sandboxed

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
scripts never execute, even on direct navigation, and even if finding 1 is not
yet fixed. `'unsafe-inline'` for styles is required by the templates' own
`<style>` blocks.

`img-src` must name the storage origin rather than a blanket `https:`: the local
stack serves MinIO over plain **http** on `:9000`
(`STORAGE_PUBLIC_BASE_URL=http://localhost:9000/postner`), which `https:` alone
would block. The frontend hit exactly this and now reads the same setting to
build its own policy.

Set `frame-ancestors` to the configured `CORS_ORIGINS` if the frontend ever
frames this endpoint by URL; keep `'none'` while it uses `html_content` +
`srcdoc`, which is what it does today.

---

## 4. Harden the Playwright render

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

Note the allowlist must now include the storage host — page images are fetched
over the network rather than read off disk, so an over-tight allowlist produces
blank photos rather than an error.

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

## 5. Reject markup at the API boundary

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

## 6. Stop duplicating markup into every response

**Rewritten.** The original finding was that `html_source` leaked
`file:///app/runs/…` container paths. `c3d7bbd` removed the `file://` scheme
entirely, so that disclosure is gone.

What replaced it is waste rather than exposure. `page_preview_html`
(`preview.py:6-11`) now returns `html_source` unchanged, and
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

## Verification

```python
# 1 — escaping
def test_slide_title_is_escaped():
    html = fill_placeholders("<h1>{{title}}</h1>", {"title": "</h1><script>alert(1)</script>"})
    assert "<script>" not in html
    assert "&lt;script&gt;" in html

# 1 — url scheme allowlist
def test_non_http_image_url_dropped():
    html = fill_placeholders('<img src="{{image_url}}">', {"image_url": "javascript:alert(1)"})
    assert "javascript:" not in html

# 2 — variant breakout
def test_variant_css_breakout_rejected():
    out = apply_color_variant(":root{--bg:#fff;}", {"--bg": "red; } </style><script>x</script>"})
    assert "<script>" not in out

# 5 — markup rejected at the boundary
def test_rewrite_rejects_markup():
    r = client.post(f"/posts/{pid}/rewrite", json={"caption": "<script>x</script>"})
    assert r.status_code == 422

# 6 — markup returned once, and not on the list endpoint
def test_response_does_not_duplicate_markup():
    page = client.get(f"/posts/{pid}").json()["composed"]["pages"][0]
    assert "html_content" in page and "html_source" not in page
    assert "html_content" not in client.get("/posts").json()["posts"][0]["composed"]["pages"][0]
```

```bash
# 3 — headers on the preview endpoint
curl -sI -H "Authorization: Bearer $TOKEN" \
  "$API/posts/$POST_ID/pages/main/html" | grep -i "content-security-policy\|x-content-type"
```

---

## Cross-cutting, for the frontend

Already shipped on the FE side, listed so both halves are visible:

- Preview markup renders only in `<iframe srcDoc sandbox="">` — never
  `dangerouslySetInnerHTML`, never `allow-scripts` with `allow-same-origin`.
  Verified against a live page: an injected `<script>` and an `onerror` handler
  both fail to execute, and the parent cannot read into the frame.
- CSP and security headers are set, with `img-src` naming the storage origin
  from `STORAGE_PUBLIC_BASE_URL` for the reason given in finding 3.
- The BFF proxy refuses to forward non-JSON responses, so the endpoint in
  finding 3 cannot be served from the app origin.
