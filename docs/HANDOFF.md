# Handoff: deferred backend work + frontend tasks

Companions: [FRONTEND_ONBOARDING.md](./FRONTEND_ONBOARDING.md) (flow + routes) · [FRONTEND_SCREENS.md](./FRONTEND_SCREENS.md) (per-screen fields).

The working backlog out of the posts-service review: one backend item that was deliberately deferred, one that is landing, and three frontend items for **Jaachi**. Frontend line references below were re-verified; backend references are deliberately by function name rather than line number, because that tree has been moving.

---

## Backend

### 1. Revision snapshot slimming — deferred on purpose

`_add_revision` / `_post_snapshot` in `app/posts/service.py` write a full deep copy of `content` + `images` + `composed` into `post_revisions.payload` on every mutation. `composed` holds the fully filled HTML for every page of a carousel, so revision rows are large, and nothing prunes them. Shrinking them is worth doing eventually.

The obvious optimisation is to keep `composed` only for the revision kinds that changed it and strip it everywhere else. **That does not work**, and the reason is the valuable part of this entry — it was tried, it was unsafe, and it was pulled back out. Do not re-derive it from scratch.

The problem is that more kinds change `composed` than it looks:

- `rewrite_post` calls `compose_post` whenever `recompose=True`, and only then records its `rewrite` revision. The edit sheet always sends `recompose: true` (`postner_fe/src/components/review/edit-sheet.tsx:90`), so in the product every rewrite rewrites the markup.
- `undo_post` calls `_apply_snapshot`, which assigns `post.composed`, before recording its own `undo` revision. So `undo` changes the markup too.
- `_apply_snapshot` only assigns a key that is actually present in the snapshot. A snapshot with no `composed` therefore leaves whatever markup is currently on the post.

Put together, stripping `composed` from a kind that did change it desyncs the preview on restore. Two consecutive rewrites followed by an undo is enough: the undo restores the older copy while the newer markup stays in place, so the post holds one thing in `content` and renders another in the review iframe. Nothing surfaces the mismatch, because the restored snapshot also restores a reviewable status.

That leaves `images` as the only kind that can safely lose its composed snapshot — `draft` snapshots have an empty `composed` anyway — which makes the naive version nearly worthless. Hence the deferral.

Two designs worth revisiting when someone picks this up:

- **(a) Strip `draft` and `images` only.** Correct and simple, but a modest saving for the reasons above. Worth it only as a cheap side-effect of touching this code for another reason.
- **(b) Keep the `composed` structure on every kind, but strip `pages[].html_source`.** Much bigger saving, since `html_source` is an entire filled document per page. Undo would then recompose server-side to rebuild the markup. The costs are real: undo gets slower, it pulls the render path into what is currently pure database work, and it can start failing for the reasons compose fails (missing images, missing pack file) — which the undo endpoint has no way to signal today.

### 2. Per-page placeholder fields on the post payload — landing

`create_draft_post` now also stores `content["pack_pages"]`, alongside the existing `content["pack_page_ids"]`, which is staying. The value comes from `pack_field_schema()` in `app/templates/packs.py`, which turns a pack into one entry per sequenced page:

```json
{ "page_id": "cover", "index": 1, "role": "cover", "tags": ["cover", "script"], "images": 1, "fields": ["script", "title"] }
```

Snapshotting the schema at draft time (rather than having clients fetch the pack) means an edited pack cannot retroactively change the shape of an existing post. This is what unblocks frontend task 1.

Still open, and optional: a `GET /packs/{pack_id}` detail endpoint over the same function, so the pack picker can preview what each page holds before a post exists.

---

## Frontend (Jaachi)

### Task 1 — drive the edit sheet's fields off the pack schema

**Ready to start.** The backend side is landing; see backend item 2 for the shape.

`postner_fe/src/components/review/edit-sheet.tsx:124-155` renders a fixed list of inputs for whichever slide is selected:

```tsx
// postner_fe/src/components/review/edit-sheet.tsx:125-131
[
  ["title", "Title", "input"],
  ["subtitle", "Subtitle", "input"],
  ["body", "Body", "textarea"],
  ["body_2", "Body 2", "textarea"],
  ["cta", "Call to action", "input"],
] as const
```

The guard on line 133 is `key in slide || kind === "input"`, which never actually filters anything: the inputs are unconditional, and `CarouselSlide` (`app/models/schemas.py`) defaults every field to `""`, so `model_dump()` puts all of them in every slide dict. Neither branch consults the template. On `lifestyle_tips` that means the cover page offers Subtitle, Body 2 and Call to action — none of which its HTML has a placeholder for, so typing in them changes `content` and changes nothing visible — while `script`, `next`, `handle` and `page_number`, which those pages do use, are not editable at all.

Drive the visible inputs for the active slide from that page's `fields` instead. Two things to get right:

- **Treat `content.pack_pages` as optional.** Posts drafted before this change will not have it, and single-mode (non-pack) posts never will. Fall back to the current hardcoded list when it is missing, rather than rendering an empty form.
- **Match on `page_id`, not index.** The entries are built from the same `pack.sequenced_pages()` as `content.slides`, so they line up positionally today — but looking up the entry whose `page_id` equals the selected slide's `page_id` costs nothing and survives any future divergence between the two lists.

Keep the input-versus-textarea decision as a lookup keyed on field name, so an unfamiliar field from a new pack still renders as something sensible.

You will also need to add `pack_pages` to `PostContent` in `postner_fe/src/lib/api/types.ts:38-53`, next to `pack_page_ids` on line 51. That interface hand-mirrors the backend `content` dict — the file says so at lines 15-20 — because FastAPI types `content` as an open `dict[str, Any]`, so `npm run gen:api` will not produce it for you.

### Task 2 — regenerate the API types

`asset_dir` is being removed from the backend outright, not just hidden from the response: the column is dropped by migration, the mapping is off the `Post` model, and it is out of both `create_draft_post` and the `make_post` test fixture. Only the historical migrations still name it, which is as it should be.

`postner_fe/src/lib/api/schema.d.ts:688` still declares `asset_dir: string` as required on `PostResponse`, and `Post` derives from `S["PostResponse"]` (`postner_fe/src/lib/api/types.ts:100`), so the frontend type currently promises a field that is on its way out of the API entirely.

Run `npm run gen:api` against a backend that is migrated to head — if `asset_dir` is still in the regenerated schema, that environment has not picked the change up yet and it is worth checking before committing the result. Nothing under `postner_fe/src` reads `post.asset_dir`; the declaration in `schema.d.ts` is its only appearance in the frontend. So this should be a pure type regeneration with no call-site fallout.

### Task 3 — stop the preview depending on `html_content` alone

**Worth doing proactively.** It is cheap, and it removes a whole class of confusing failure.

Two things in the frontend make the review preview fragile:

- `pagePreviewHtml` reads `html_content` and nothing else (`postner_fe/src/lib/api/types.ts:159-162`).
- `usePostMutation` writes the mutation response straight over the cached post with `queryClient.setQueryData` (`postner_fe/src/features/posts/hooks.ts:62-76`). It invalidates the list and revisions queries, but the post detail entry is replaced, not merged or refetched.

So any post response that arrives without `html_content` blanks the preview in the cache. `previewPages` then filters those pages out, `hasPreview` goes false, and `isReviewable` still returns true — the post silently drops out of the review queue while claiming to belong in it, and it looks like a frontend bug.

This matters because `html_content` is a response-only convenience: the API copies it out of the stored `html_source` when it serialises a post. Endpoints that cannot change the composed HTML — `POST /posts/{id}/images` and `POST /posts/{id}/animate` are the obvious two — are natural candidates for skipping that copy, since it duplicates an entire filled document per page into the response for no benefit. A change doing exactly that has been in and out of the backend tree today, so check whether it is currently live before testing against either behaviour. The frontend should not care either way, and right now it does.

Nothing is broken today regardless: `useGenerateImages` has exactly one caller, in `postner_fe/src/features/posts/use-pipeline.ts:42-45`, where it runs before compose and only when the post has no images yet, and there is no `/animate` caller at all — no hook, no component. The failure arrives the day someone adds a "regenerate photos" button to the review or edit screen.

Two ways to close it:

- **Fall back to `html_source` in `pagePreviewHtml`.** Cheap and local. The doc comment above that function argues only `html_content` is safe because `html_source` "still points at `file://` assets" — that is stale: `page_preview_html` in `app/posts/preview.py` returns `html_source` verbatim as `html_content`, so for any post composed since the move to object storage the two strings are identical. Legacy rows do carry `file://`, but they carry it in `html_content` too, and `needsRecompose` (`types.ts:176-180`) already catches that. If you add the fallback, point `needsRecompose` at `pagePreviewHtml(page)` rather than at `page.html_content` directly, or a post previewed via the fallback will skip the recompose warning.
- **Merge rather than replace in `usePostMutation`.** Fixes the whole class of problem, including any field the API trims from a response later. But merging posts is ambiguous in the wrong direction: a shallow merge would preserve a stale `composed` after a mutation that legitimately replaced it — resize clears the PNG urls, render adds them — so you would trade a blank preview for a wrong one. Switching to `invalidateQueries` on the post key instead costs a round trip per mutation and gives up the instant update.

Recommendation: take the `html_source` fallback and leave the cache write as replace-on-success. It fixes the failure without changing cache semantics for every mutation, and it makes the review screen robust to whatever the API decides to leave out of a response next.
