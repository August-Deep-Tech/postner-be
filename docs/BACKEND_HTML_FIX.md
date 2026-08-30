# HTML pipeline — security fixes

**Status as of `afaff00` (2026-08-28).** The preview split has shipped: `compose_post`
fills HTML only, `render_post` does Playwright + upload, and `GET /posts/{id}/pages/{page_id}/html`
serves filled markup to the browser.

`git diff --stat b90dcc0..afaff00 -- app/templates/ app/render/` is **empty**. The template
filler and the screenshotter were not touched by that work, so the issues below are all
still live — and the new flow adds a browser sink to markup that was previously only ever
loaded by Playwright.

None of these are frontend fixes. The frontend's `sandbox=""` iframe and CSP headers are
defence in depth; they do nothing for the Playwright sink.

---

## Findings

| # | Finding | File | Severity |
|---|---|---|---|
| 1 | Placeholder substitution does no HTML escaping | `app/templates/engine.py:19` | **High** |
| 2 | Variant CSS values written raw into `:root{}` | `app/templates/engine.py:93` | **High** |
| 3 | New HTML endpoint serves `text/html` with no CSP | `app/posts/routes.py:188` | **High** (with the FE proxy) |
| 4 | Playwright renders untrusted markup with JS on, no egress limits | `app/render/screenshot.py:31` | **High** |
| 5 | `RewriteRequest.text` accepts arbitrary keys/values | `app/posts/routes.py:65` | Medium |
| 6 | `html_source` returned to clients; `html_content` on the list endpoint | `app/posts/preview.py:95`, `routes.py:140` | Medium |

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

- **LLM slide text derived from the scraped URL** (`generate_carousel` → `content.slides`
  → `fields`, `service.py:537`). Unauthenticated: anyone who controls a page a user drafts
  from can prompt-inject `<script>` into a slide title.
- **`RewriteRequest.caption` / `text`** — authenticated, arbitrary strings, straight into
  `content` and then into placeholders.
- **Brand `logo_url`** — lands inside `src="…"`, so `x" onerror="…` breaks the attribute.

### Fix

```python
import html as html_lib
from urllib.parse import urlsplit

_URL_KEYS = {"image_url", "logo_url", "cta_link"}
_SAFE_URL_SCHEMES = {"https", "data", "file"}  # file: only for the internal Playwright load


def _safe_url(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    scheme = urlsplit(raw).scheme.lower()
    if scheme not in _SAFE_URL_SCHEMES:
        return ""
    if scheme == "data" and not raw.lower().startswith("data:image/"):
        return ""
    return html_lib.escape(raw, quote=True)


def fill_placeholders(html: str, values: dict[str, str]) -> str:
    """Replace {{key}} tokens; unknown keys become empty string. Values are escaped."""

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

The `image_` / `_url` prefix and suffix checks cover the dynamic keys `packs.py:159-161`
generates (`image_2`, `image_url_2`, …).

**This one change closes both sinks** — the browser preview and the Playwright render —
because both consume the same filled string.

No visual regression: every text placeholder sits in element content, where `&amp;` renders
as `&`. The `white-space: pre-line` templates keep their newlines.

---

## 2. Validate variant CSS values

`apply_color_variant` (`engine.py:93-118`) writes values verbatim into a `:root{}` block, so
a value of `red; } </style><script>…</script><style>` escapes the style element. These
values are **LLM-generated** by `propose_and_save_variants` — the same prompt-injection
source as finding 1.

```python
_CSS_KEY_RE = re.compile(r"^--[a-z0-9-]{1,64}$", re.IGNORECASE)
_CSS_VALUE_RE = re.compile(r"^[#\w\s(),.%/+-]{1,120}$")
_CSS_FORBIDDEN = ("url(", "expression", "@import", "javascript:", "</", "{", "}", ";")


def _safe_css_value(value: str) -> str | None:
    v = str(value).strip().rstrip(";").strip()
    low = v.lower()
    if any(token in low for token in _CSS_FORBIDDEN):
        return None
    return v if _CSS_VALUE_RE.match(v) else None
```

Drop any pair failing `_CSS_KEY_RE` / `_safe_css_value` before it reaches
`existing[key] = value`. The value pattern allows `(` and `)` for `rgb()` / `hsl()`; `url(`
is caught by the forbidden-token list.

---

## 3. Send the new HTML endpoint out sandboxed

`GET /posts/{id}/pages/{page_id}/html` (`routes.py:188`) returns unescaped, partly
attacker-influenced markup as `text/html` with no security headers.

Direct navigation is mostly self-limiting — the route needs a Bearer token, which a browser
navigation will not carry. The real path is the frontend proxy: `/api/proxy/[...path]`
attaches the session token and **forwards the upstream content-type verbatim**, so this
response becomes `text/html` on the *app* origin, where the `httpOnly` session cookie lives
and `/api/proxy` is a credentialed gateway to the whole API. That is app-origin XSS, i.e.
full tenant read/write without ever stealing the token.

```python
_PREVIEW_CSP = (
    "sandbox; "
    "default-src 'none'; "
    "img-src data:; "
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

The bare `sandbox` directive makes the response behave as a sandboxed document — scripts
never execute, even on direct navigation, and even if finding 1 is not yet fixed.
`'unsafe-inline'` for styles is required by the templates' own `<style>` blocks.

Set `frame-ancestors` to the configured `CORS_ORIGINS` if the frontend ever frames this
endpoint by URL; keep `'none'` while it uses `html_content` + `srcdoc`, which is the plan.

---

## 4. Harden the Playwright render

`screenshot.py:31-35` is unchanged: full Chromium, **scripts enabled**, no request
interception, no timeout beyond `wait_until="networkidle"`, running inside the API
container. Injected script gets SSRF from inside the trust boundary — the cloud metadata
endpoint, the API on localhost, Postgres/Redis on the compose network — plus arbitrary
egress for exfiltration.

`afaff00` did not reduce this exposure; it moved the trigger. `POST /render` and
`add_feedback(decision="approved")` (`service.py:1133`) now both reach it.

```python
_ALLOWED_HOSTS = {"fonts.googleapis.com", "fonts.gstatic.com"}


async def _guard(route, request):
    url = request.url
    if url.startswith(("file:", "data:", "blob:")):
        await route.continue_()
        return
    host = urlsplit(url).hostname or ""
    if host in _ALLOWED_HOSTS:
        await route.continue_()
        return
    await route.abort()


context = await browser.new_context(
    viewport={"width": width, "height": height},
    device_scale_factor=1,
    java_script_enabled=False,
)
await context.route("**/*", _guard)
page = await context.new_page()
await page.goto(html_path.resolve().as_uri(), wait_until="networkidle", timeout=15_000)
```

**`java_script_enabled=False` is the clean kill for the whole SSRF class**, but it currently
breaks one template: `templates/lifestyle_day.html:221` runs JS to clean the caption and
split it across four staggered slots. Port that logic into the Python fill step. Two
payoffs: JS can then be disabled in both renderers, and the browser preview (which the
frontend will sandbox with no `allow-scripts`) stops diverging from the PNG for that
template. Until then, the route allowlist and the timeout are worth landing on their own.

Complementary, outside the code: deny the render container egress to `169.254.169.254` and
to internal service names.

---

## 5. Reject markup at the API boundary

`RewriteRequest.text: dict[str, Any]` (`routes.py:65`) merges unbounded, unvalidated keys
into `post.content`, which later reach placeholders. The API should accept **field values,
never markup**:

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

Reject unknown keys with 422 and any string value matching `_MARKUP_RE`. Same check on the
`slides` list items. This also keeps the door shut on a future WYSIWYG editor posting HTML
back — that would be stored XSS plus a server-side renderer that executes it.

---

## 6. Response hygiene (introduced by `afaff00`)

Not exploitable on their own, but worth fixing while this is open:

- **`html_source` is returned to clients.** `enrich_composed_with_html` (`preview.py:95`)
  copies each page dict and adds `html_content` without removing `html_source`, so responses
  carry two full copies of every page's markup — and `html_source` still holds
  `file:///app/runs/<tenant>/<post>/…` absolute paths, disclosing internal container layout.
  Strip `html_source` in the response mapper; keep it in the DB, where `render_post` and
  `animate_post` read it.
- **The list endpoint inlines every image.** `_post_response` (`routes.py:140`) calls
  `enrich_composed_with_html` for `GET /posts` too, so the queue fetch returns base64 data
  URIs for every page of every post. Gate enrichment to single-post reads, or put it behind
  an explicit `?include=html`.
- **Revisions now store markup.** `_add_revision` snapshots `composed`, which since
  `afaff00` contains `html_source`, so `post_revisions.payload` grows by a full document set
  per edit. Consider stripping `html_source` from the snapshot and letting the on-disk file
  be the revision's copy.

---

## Verification

```python
# 1 — escaping
def test_slide_title_is_escaped():
    html = fill_placeholders("<h1>{{title}}</h1>", {"title": "</h1><script>alert(1)</script>"})
    assert "<script>" not in html
    assert "&lt;script&gt;" in html

# 2 — variant breakout
def test_variant_css_breakout_rejected():
    out = apply_color_variant(":root{--bg:#fff;}", {"--bg": "red; } </style><script>x</script>"})
    assert "<script>" not in out

# 5 — markup rejected at the boundary
def test_rewrite_rejects_markup():
    r = client.post(f"/posts/{pid}/rewrite", json={"caption": "<script>x</script>"})
    assert r.status_code == 422
```

```bash
# 3 — headers on the preview endpoint
curl -sI -H "Authorization: Bearer $TOKEN" \
  "$API/posts/$POST_ID/pages/main/html" | grep -i "content-security-policy\|x-content-type"
```

---

## Cross-cutting, for the frontend

Tracked on the FE side, listed here so both halves are visible:

- Render preview HTML **only** in `<iframe srcDoc sandbox="">`. Never
  `dangerouslySetInnerHTML`, and never `allow-scripts` together with `allow-same-origin`.
- Add CSP headers in `next.config.ts` (currently the empty scaffold). `srcdoc` documents
  inherit the parent CSP, so `img-src` / `font-src` / `style-src` restrictions cover the
  payload.
- `/api/proxy/[...path]` should refuse to forward non-JSON content types, so an API response
  of `text/html` can never be served from the app origin.
