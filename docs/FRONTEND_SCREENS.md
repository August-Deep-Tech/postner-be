# Frontend screen field specs

Companion to [FRONTEND_ONBOARDING.md](./FRONTEND_ONBOARDING.md) (flow + routes).  
This file is the **per-screen field inventory**: UI component, content type, API binding, validation.

API base: `http://localhost:8001` · Auth: `Authorization: Bearer <access_token>` on `/brands` and `/posts`.

Formats used below: `ig_feed` | `ig_portrait` | `ig_story` | `tiktok` | `fb_post` | `x_post`.

---

## 1. Register / Login

**Purpose:** Create account or sign in; obtain JWT for tenant-scoped APIs.  
**Layout:** Centered form card. Mobile full-width padding; desktop max-width ~400px. Toggle Register ↔ Login tabs or links.

### Register

| ID | Label / content | Component | Type | API binding | Validation / notes |
|---|---|---|---|---|---|
| `reg_email` | Email | Text input | text (email) | `POST /auth/register` → `email` | Required, valid email |
| `reg_password` | Password | Text input (password) | text | `POST /auth/register` → `password` | Required, 8–128 chars |
| `reg_name` | Name | Text input | text | `POST /auth/register` → `name` | Optional; placeholder e.g. “Your name” |
| `reg_submit` | Create account | Button (primary) | button | `POST /auth/register` | On success store `access_token`, `tenant_id`, `user_id` |

### Login

| ID | Label / content | Component | Type | API binding | Validation / notes |
|---|---|---|---|---|---|
| `login_email` | Email | Text input | text (email) | `POST /auth/login` → `email` | Required |
| `login_password` | Password | Text input (password) | text | `POST /auth/login` → `password` | Required |
| `login_submit` | Sign in | Button (primary) | button | `POST /auth/login` | Same token storage as register |

### Actions

| Control | Route | Next |
|---|---|---|
| Submit register/login | `POST /auth/register` or `/auth/login` | Brand setup (or restore via `GET /auth/me`) |
| Session restore | `GET /auth/me` | If token present on app load |

---

## 2. Brand setup

**Purpose:** Create or edit the brand used on posts.  
**Layout:** Form stack. Mobile single column; desktop two-column optional (logo left, fields right). Empty state until the user creates a brand — **no system/demo brand**.

| ID | Label / content | Component | Type | API binding | Validation / notes |
|---|---|---|---|---|---|
| `brand_list` | Your brands | List / cards | list | `GET /brands` → `brands[]` | Empty until user creates one |
| `brand_name` | Brand name | Text input | text | `POST/PATCH /brands` → `name` | Required on create |
| `brand_tagline` | Tagline | Text input | text | `tagline` | Optional |
| `brand_description` | About | Textarea | text | `description` | Optional; voice for LLM |
| `brand_website` | Website | Text input | text (url) | `website` | Optional URL |
| `brand_logo` | Logo | File upload / URL input | image | `logo` | Optional URL or storage key for now |
| `brand_formats` | Enabled post formats | Multi-select chips | choice[] | `formats` | One or more of `ig_feed` \| `ig_portrait` \| `ig_story` \| `tiktok` \| `fb_post` \| `x_post`. Order matters: **first = default**. Default `["ig_feed"]` |
| `brand_slug` | ID (slug) | Text input | text | create `id` (optional) | Optional; auto from name if omitted |
| `brand_save` | Save brand | Button (primary) | button | `POST /brands` or `PATCH /brands/{id}` | Use returned `id` or `slug` as `brand_id` later |
| `brand_empty_cta` | Create your brand | Empty-state CTA | button | Opens create form | Required before New post |

### Actions

| Control | Route | Next |
|---|---|---|
| Save | `POST /brands` or `PATCH /brands/{id}` | New post |
| Empty list | — | Block New post until at least one brand exists |

---

## 3. New post

**Purpose:** Collect source URL + design target; kick off draft.  
**Layout:** Form. Mobile stacked; desktop form left / pack preview right.

| ID | Label / content | Component | Type | API binding | Validation / notes |
|---|---|---|---|---|---|
| `post_url` | Source URL | Text input | text (url) | `POST /posts` → `url` | Required, valid URL |
| `post_brand` | Brand | Select / picker | choice | `brand_id` | UUID or slug from brands; recommended |
| `post_mode` | Pack vs single template | Segmented control | choice | UI-only → sets XOR | Exactly one of pack / template |
| `post_pack` | Pack | Select cards | choice | `pack_id` | From `GET /packs`; XOR with template |
| `post_template` | Template | Select | choice | `template_id` | From `GET /templates`; default `basic` if neither |
| `post_format` | Format | Select chips | choice | `format` | Must be one of **brand.formats**. Default: first brand format. Options = brand’s enabled list only |
| `post_variant` | Color variant | Select (optional) | choice | `variant_id` | From `GET /variants?brand_id=`; nullable |
| `post_with_images` | Generate photos now | Toggle | boolean | `with_images` | Default **false** (cheaper draft). Still need compose for HTML preview |
| `post_submit` | Generate | Button (primary) | button | `POST /posts` | Then Generating screen |

### Format options (for `post_format`)

| Value | Size | Label suggestion |
|---|---|---|
| `ig_feed` | 1080×1080 | Instagram feed |
| `ig_portrait` | 1080×1350 | Instagram portrait |
| `ig_story` | 1080×1920 | Instagram story |
| `tiktok` | 1080×1920 | TikTok |
| `fb_post` | 1080×1080 | Facebook |
| `x_post` | 1600×900 | X / Twitter |

### Actions

| Control | Route | Next |
|---|---|---|
| Generate | `POST /posts` | Generating (pass `post_id`) |
| Prefetch catalogs | `GET /packs`, `GET /templates`, `GET /variants?brand_id=` | On screen mount (variants need brand) |

**Note:** `with_images: true` is **not** compose. Compose fills HTML for review; PNG render runs on approve or `POST /render`.

---

## 4. Generating

**Purpose:** Progress while draft → images → HTML compose. No editable fields.  
**Layout:** Centered progress. Same on mobile/desktop.

| ID | Label / content | Component | Type | API binding | Validation / notes |
|---|---|---|---|---|---|
| `gen_title` | Creating your post… | Heading | text | — | Static |
| `gen_step_draft` | Drafting copy | Progress step | status | `POST /posts` (already done or in flight) | Done when `post_id` returned |
| `gen_step_images` | Generating photos | Progress step | status | `POST /posts/{id}/images` | Skip if text-only pack |
| `gen_step_compose` | Building preview | Progress step | status | `POST /posts/{id}/compose` `{ "ensure_images": true }` | HTML fill → status `preview` |
| `gen_error` | Error message | Alert | text | HTTP error body | Retry / back |
| `gen_spinner` | Loading | Spinner | feedback | — | Until compose succeeds |

### Actions

| Step | Route | Body |
|---|---|---|
| Draft | `POST /posts` | From New post form |
| Images | `POST /posts/{id}/images` | `{ "regenerate": false }` (skip if no images needed) |
| Compose | `POST /posts/{id}/compose` | `{ "ensure_images": true }` |
| Done | `GET /posts/{id}` | Open **Review** with `html_content` |

---

## 5. Review

**Purpose:** Review HTML preview; reject / edit / approve (approve triggers PNG).  
**Reference:** [review-screen-reference.png](./review-screen-reference.png)  
**Layout:** Mobile — centered card, FAB row fixed bottom. Desktop — same card + FABs; widen column (~480–560px for X-style; larger for carousel).

| ID | Label / content | Component | Type | API binding | Validation / notes |
|---|---|---|---|---|---|
| `rev_logo` | `<postner/>` | Brand mark | text / logo | — | Header |
| `rev_avatar` | Profile image | Avatar | image | Brand `logo` or placeholder | Circular |
| `rev_display_name` | Display name | Text | text | Brand `name` | e.g. “Jaachiii” |
| `rev_verified` | Verified mark | Icon | icon | — | Decorative / brand badge |
| `rev_handle` | @handle | Text | text | Derive from brand slug/name | Secondary |
| `rev_body` | Post body / overlay | Text block | text | `content.ig_fb_caption` or slide fields | For packs: show current slide |
| `rev_preview` | HTML preview | iframe | html | `composed.pages[].html_content` (`srcdoc`) | Primary visual; not PNG until approve |
| `rev_slide_pager` | Slide dots / swipe | Pager | navigation | `content.slides[]` / composed pages | Packs only |
| `rev_meta_icons` | Comment / repost / like / stats | Icon row | icon | — | Decorative chrome (X-style) |
| `rev_schedule_line` | Schedule for … | Text | text | — | Placeholder v1; scheduling later |
| `rev_context_tip` | Context / tip strip | Info banner | text | Optional `meta` / scrape snippet | Green tip as in screenshot |
| `rev_fab_reject` | Reject | FAB (red X) | button | Opens Reject sheet | Left |
| `rev_fab_edit` | Edit | FAB (blue pencil) | button | Opens Edit sheet | Center |
| `rev_fab_approve` | Approve | FAB (green arrow) | button | Then Download | Right — **not** schedule yet |

### Actions

| Control | Behavior |
|---|---|
| Reject FAB | Open screen 6 |
| Edit FAB | Open screen 7 |
| Approve FAB | `POST /posts/{id}/feedback` `{ "decision": "approved" }` (awaits PNG render) → open screen 8 |
| Refresh state | `GET /posts/{id}` |

---

## 6. Reject sheet

**Purpose:** Capture rejection reasons before discarding or regenerating.  
**Layout:** Bottom sheet (mobile) / modal (desktop).

| ID | Label / content | Component | Type | API binding | Validation / notes |
|---|---|---|---|---|---|
| `rej_title` | Why reject? | Heading | text | — | |
| `rej_reasons` | Reason chips | Multi-select chips | choice[] | `POST /posts/{id}/feedback` → `reasons` | Suggested: `off_brand`, `weak_hook`, `bad_visual`, `wrong_tone` |
| `rej_note` | Notes | Textarea | text | `note` | Optional |
| `rej_page` | This slide only | Optional select | choice | `page_id` | Packs; null = whole post |
| `rej_cancel` | Cancel | Button (ghost) | button | — | Close sheet |
| `rej_submit` | Submit rejection | Button (destructive) | button | `decision: "rejected"` | Required: at least one reason **or** note (FE rule) |

### Actions

| Control | Route | Body |
|---|---|---|
| Submit | `POST /posts/{post_id}/feedback` | `{ "decision": "rejected", "reasons": [...], "note": "...", "page_id": null }` |
| After | — | Back to New post or list |

---

## 7. Edit sheet

**Purpose:** Change copy and/or look without leaving the review flow.  
**Layout:** Sheet/modal with two sections or tabs: **Copy** | **Look**.

### Tab: Copy (rewrite)

| ID | Label / content | Component | Type | API binding | Validation / notes |
|---|---|---|---|---|---|
| `edit_caption` | Caption | Textarea | text | `POST .../rewrite` → `caption` | Maps to IG/FB caption |
| `edit_title` | Title | Text input | text | `text.title` | Slide / overlay fields |
| `edit_subtitle` | Subtitle | Text input | text | `text.subtitle` | |
| `edit_body` | Body | Textarea | text | `text.body` | |
| `edit_body_2` | Body 2 | Textarea | text | `text.body_2` | Pack-dependent |
| `edit_cta` | CTA | Text input | text | `text.cta` | |
| `edit_suggest` | Suggest with AI | Toggle / button | boolean | `suggest` | If true, LLM fills empty/targets |
| `edit_recompose` | Update preview | Toggle | boolean | `recompose` | Default true; re-fills HTML only |
| `edit_copy_save` | Apply copy | Button (primary) | button | `POST /posts/{id}/rewrite` | Refresh Review preview |

### Tab: Look (redesign)

| ID | Label / content | Component | Type | API binding | Validation / notes |
|---|---|---|---|---|---|
| `edit_variant` | Color variant | Select | choice | `variant_id` | From `GET /variants?brand_id=` (post’s brand) |
| `edit_propose` | Propose new palette | Toggle / button | boolean | `propose: true` | Auto-proposes if no variant_id |
| `edit_regen_images` | New photos | Toggle | boolean | `regenerate_images` | Default false |
| `edit_look_recompose` | Update preview | Toggle | boolean | `recompose` | Default true |
| `edit_look_save` | Apply look | Button (primary) | button | `POST /posts/{id}/redesign` | |
| `edit_undo` | Undo last change | Button (ghost) | button | `POST /posts/{id}/undo` | Restores previous snapshot |
| `edit_history` | Version history | Optional list | status | `GET /posts/{id}/revisions` | `{ id, kind, version, created_at }` |

### Actions

| Control | Route |
|---|---|
| Apply copy | `POST /posts/{id}/rewrite` |
| Apply look | `POST /posts/{id}/redesign` |
| Undo | `POST /posts/{id}/undo` |
| Optional log | `POST /posts/{id}/feedback` `{ "decision": "needs_changes" }` |
| Close | Return to Review with refreshed `GET /posts/{id}` |

---

## 8. Download sheet

**Purpose:** After approve — pick size and download PNG(s).  
**Layout:** Sheet/modal. Mobile bottom sheet; desktop centered modal.

| ID | Label / content | Component | Type | API binding | Validation / notes |
|---|---|---|---|---|---|
| `dl_title` | Download | Heading | text | — | Shown after approve |
| `dl_preview` | Preview | Image | image | `composed.pages[].url` | PNG after approve/render |
| `dl_format` | Size / platform | Chip group / select | choice | `POST .../resize` → `format` | Options = **brand.formats** only (see format table) |
| `dl_apply_format` | Apply size | Button (secondary) | button | `resize` then `render` | Resize re-fills HTML; must re-render PNGs |
| `dl_pages` | Which slides | Multi-select | choice[] | `resize.pages` / compose pages | Packs; default all |
| `dl_download` | Download | Button (primary) | button | `composed.pages[].url` | Prefer public/storage URL |
| `dl_animate` | Also make video | Optional toggle + button | boolean | `POST .../animate` | Requires rendered PNGs |
| `dl_done` | Done | Button (ghost) | button | — | Exit to list / home |

### Actions

| Control | Route | Notes |
|---|---|---|
| Approve (from Review) | `POST /posts/{id}/feedback` `{ "decision": "approved" }` | Auto-renders PNG if missing; opens this sheet |
| Optional early PNG | `POST /posts/{id}/render` | Without approving |
| Apply size | `POST /posts/{id}/resize` then `POST /posts/{id}/render` | Resize clears PNG urls |
| Download | `composed.pages[].url` | Public when `STORAGE_BACKEND=s3`; local path when `local` |
| Optional MP4 | `POST /posts/{id}/animate` | `{ "motion_preset": "fade_kenburns" }` |

---

## Cross-screen type legend

| Type | Meaning |
|---|---|
| text | String content |
| text (email/url) | Constrained string |
| image | Raster / logo / composed PNG |
| button / FAB | Triggers action |
| choice / choice[] | Single or multi enum |
| boolean | Toggle |
| status / feedback | Progress or loading |
| icon | Decorative or action glyph |
| list | Collection UI |
| navigation | Pager / tabs |

---

## Related

- Flow & route narrative: [FRONTEND_ONBOARDING.md](./FRONTEND_ONBOARDING.md)  
- Review chrome: [review-screen-reference.png](./review-screen-reference.png)  
- Live OpenAPI: http://localhost:8001/docs
