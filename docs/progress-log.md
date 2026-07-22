# SocialPilot AI Progress Log

This log records evidence-backed checkpoints. It does not convert plans into completed work or assign a result to a historical commit unless preserved or executed.

## Historical checkpoints

| Date | Checkpoint | Commit | Evidence and result | Known limitations |
|---:|---|---|---|---|
| 2026-07-17 | C0-C2 stable baseline | `61dd14e` | Initial modular backend, React frontend, product-to-growth chain, tests, README, and architecture. No earlier independent C0/C1/C2 commits or totals exist here. | Early stages share one baseline commit. |
| 2026-07-17 | Qwen verification | `57df1d1` | `docs/qwen_verification.md` records one successful `qwen-plus` smoke: 1 passed; output parsed and validated. | Historical paid/provider call; normal tests skip it. |
| 2026-07-17 | Artifact infrastructure | `9e3a740` | Model, repository, schema, service behavior, and tests added. | Provider URL is not long-term storage. |
| 2026-07-17 | Wanx adapter | `25f17d8` | Submit/fetch adapter, safe error mapping, configuration, and mock tests added. | External network, credentials, region, and provider behavior remain dependencies. |
| 2026-07-17 | Render execution pipeline | `027eccb` | Submit claim, refresh/status sync, Artifact creation, API and service tests added. | Polling must never silently resubmit. |
| 2026-07-19 | Wanx real verification | `5f0a5f9` | Opt-in real smoke and safety controls added; tracked docs state successful task-to-Artifact verification. | Real smoke is cost-bearing and disabled by default. |
| 2026-07-19 | Verified output/live facade | `9e23124` | Read-only Artifact display, default-off facade, frontend panel, and tests added. | Temporary provider URL may expire. |
| 2026-07-21 | Competition freeze | `9877216`; tag `competition-freeze-v1` | Docs, local verified MP4, submission docs, and presentation guidance added. Preserved gate: 84 passed, 2 skipped, 1 warning; Ruff and frontend build passed. | Performance-to-Prompt, second-version generation, and version tracking remain absent. |

## V2-C0 — Safe branch, project map, and development tree

- Status: ✅ Completed.
- Date: 2026-07-21.
- Starting point: `competition-freeze-v1` → `98772160208840eff2f00b97b78ae34809b1786f`.
- Branch: `competition-product-v2`, created directly from the freeze tag.
- Freeze verification: `master`, the tag, and the branch starting HEAD resolve to the same commit.
- Pre-check: clean tree, no pre-existing V2 branch, no untracked files.
- Product-code changes: none.
- Real AI calls: none.
- V2-C0 checkpoint: see this Git commit.
- Push: not performed as part of this checkpoint.
- Next stage: V2-C1.1A Product creation form and validation.

### Quality gate

| Gate | Scope | Result |
|---|---|---|
| Backend | Unit/mock suite with `qwen_smoke` and `wanx_smoke` excluded | 86 collected; 2 deselected; 84 passed; 0 failed; 1 known Starlette deprecation warning |
| Ruff | Backend check | All checks passed |
| TypeScript | `tsc -b` via frontend build | Passed |
| Production build | Vite | Passed; 118 modules transformed |

The first frontend build attempt ran from the backend directory and failed with `ENOENT` because no `package.json` exists there. It was rerun from the correct frontend directory and passed. This operational mistake did not modify product source.

### Document set

- `docs/development-roadmap.md`
- `docs/progress-log.md`
- `docs/v2-plan.md`

## 2026-07-22 — V2-C1.1A Product creation form and validation

- Status: ✅ Completed; checkpoint not yet created.
- Starting branch and HEAD: `competition-product-v2` at `50ab5a49e6da4a0e0c96293254c902aacd92f845`.
- Scope: real workspace product creation only; no market/platform selection and no generated strategy, copy, or video.
- Backend reuse: existing `POST /api/v1/products`, HTTP 201 response, Product repository/service, and SQLAlchemy persistence.
- Backend change: strengthened `ProductCreate` request validation without changing the Product ORM model, tables, or migrations.
- Frontend change: required Chinese-labeled form, field errors, dynamic 1–8 selling points, trimming/deduplication, loading lock, API error, success summary, and Presentation Mode route guard.
- Product tests: 13 passed, 0 failed, 1 known Starlette warning.
- Full default pytest: 91 collected; 89 passed; 2 real-provider smoke tests skipped; 0 failed; 1 known Starlette warning.
- Ruff: all checks passed.
- TypeScript and Vite production build: passed; 119 modules transformed.
- Isolated smoke: created `USB Portable Blender` as Product ID 1 in a temporary SQLite database; all four fields persisted correctly.
- Side-effect check: 1 Product; 0 MarketingStrategy, CopyMatrix, VideoProject, VideoRenderTask, and VideoRenderArtifact records.
- UI regression: empty validation, dynamic add/delete, disabled submit during request, success display, API failure feedback, and Presentation Mode protection passed.
- Demo protection: `/products?mode=presentation` redirected to `/?mode=presentation`; form absent and `0 AI Calls` present.
- Provider/AI calls and cost: none.
- Temporary services/database: stopped and removed; the repository database and Demo Snapshot were not modified.
- Commit/push: none.
- Single recommended next stage: V2-C1.1B Product list and detail.

## 2026-07-22 — V2-C1.1B Product list and detail

- Status: ✅ Completed; checkpoint not yet created.
- Starting branch and HEAD: `competition-product-v2` at `8ce1c73f598d6c548315f562d1b416a5f45e877e`.
- Scope: real workspace product list, independent product detail, create-to-refresh/select linkage, complete UI states, and Presentation Mode regression only.
- Preconditions: clean working tree; `master` and `competition-freeze-v1` both remained at `98772160208840eff2f00b97b78ae34809b1786f`.
- Backend audit: existing `GET /api/v1/products` returns creation-time-descending `ProductRead[]` with no query parameters; existing `GET /api/v1/products/{product_id}` returns complete `ProductRead`, including selling points, target markets, timestamps, and assets.
- Backend/database impact: none; Product model, schema, repository, service, routes, tables, migrations, and repository database were not modified.
- Frontend implementation: added the single-product API client call; implemented initial loading, bounded-scroll list, empty/error/retry/refresh states, selected and newly-created visual states, independent detail loading/error/retry/empty states, and complete field/asset display.
- Creation linkage: the existing `ProductCreateForm.onCreated(product)` callback immediately selects/highlights the returned product and triggers a real list refresh without replacing the form-owned success message.
- Race protection: every detail selection owns an `AbortController` and active-request guard, so cleanup aborts the prior request and ignores any late result.
- Product tests: 13 passed, 0 failed, 1 known Starlette warning.
- Full default pytest: 89 passed, 2 real-provider smoke tests skipped, 0 failed, 1 known Starlette warning.
- Ruff: all checks passed.
- TypeScript and Vite production build: passed; 119 modules transformed.
- Isolated smoke: empty state passed; created three different products; list showed all three API records; switching products loaded their independent details; the third create refreshed, selected, and highlighted the new product; detail failure and retry recovery passed.
- Smoke setup note: the first temporary frontend used port 4175 and correctly reached the list error state because that origin is not in the existing CORS allowlist; the services were restarted on the already-allowed port 5173, where all normal-path checks passed without changing CORS configuration.
- Isolated database side effects: 3 Products; 0 ProductAssets, MarketingStrategies, CopyMatrices, VideoProjects, VideoRenderTasks, and VideoRenderArtifacts.
- Presentation regression: `/products?mode=presentation` redirected to `/?mode=presentation`; Product Center was absent; Demo Snapshot and `0 AI Calls` remained visible.
- Provider/AI calls and cost: none; no Qwen or Wanx request was made and no cost was incurred.
- Temporary services/database: stopped; all stage-named temporary SQLite and log directories were removed permanently after verification.
- Security/privacy: no secret files were read; final source scan found no credential, workspace ID, signed URL, database, log, screenshot, or build artifact in the working tree.
- Known limitations: the existing list API has no limit/offset, so the UI loads the complete list into a bounded scroll area; no large frontend test framework was introduced.
- Commit/push/tag: none.
- Single recommended next stage: V2-C1.2A Target market and platform selection.

## 2026-07-22 — V2-C1.2A Target market and platform selection

- Status: ✅ Completed; checkpoint not yet created.
- Starting branch and HEAD: `competition-product-v2` at `723b1e2d51fe431a53322400ee57d8b57128604b`.
- Scope: target-market selection and persistence, per-product platform session drafts, readiness summary, state handling, and Presentation Mode regression only; no task start or AI generation.
- Preconditions: clean working tree; `master` and `competition-freeze-v1` both remained at `98772160208840eff2f00b97b78ae34809b1786f`.
- Existing-contract audit: `Product.target_markets` is `list[str]`; existing `PATCH /api/v1/products/{product_id}` returns `ProductRead` and already persists partial updates through ProductService/ProductRepository. MarketingBrief has `platforms`, Copy supports exactly TikTok/Instagram/Facebook, and VideoProject has a single platform, but none is a correct Product-level persistence field.
- Data ownership: markets are persisted on Product through the existing PATCH endpoint; platform selection is an in-memory `Record<product_id, Platform[]>` draft for the current frontend session and is explicitly described as not written to Backend until a future task-start contract.
- Backend/database impact: none; Product schema/model/repository/service/routes, ORM tables, migrations, and repository database were not modified.
- Market behavior: US, CA, UK, DE, FR, AU, JP, and SG options; 1–5 semantic selections; duplicate prevention; selected-count display; Backend refill; dirty/saving/success/error/retry states; disabled save when unchanged; selected Product/list synchronization; historical aliases and unknown values remain visible and are removed only by explicit user action followed by save.
- Platform behavior: TikTok, Instagram, and Facebook only; 1–3 selection validation; purpose descriptions; count display; per-product isolation; no publishing/OAuth claim; no Backend persistence claim.
- Readiness behavior: evaluates real Product identity/content, selling points, saved market state, and platform draft; the V2-C1.2B task-start control remains disabled and has no action handler.
- Concurrency safety: save lock prevents duplicate PATCH; request ID and active Product guards ignore stale save results; existing detail AbortController/active guard remains in force.
- Smoke correction: the first save successfully persisted US/CA but parent synchronization immediately replaced the success message with the generic synced state. The component was corrected to preserve the success feedback, rebuilt, and the following saves/retry visibly passed.
- Product tests: 13 passed, 0 failed, 1 known Starlette warning.
- Full default pytest: 89 passed, 2 real-provider smoke tests skipped, 0 failed, 1 known Starlette warning.
- Ruff: all checks passed.
- TypeScript and Vite production build: passed after the correction; 120 modules transformed.
- Isolated smoke: created Atlas Travel Bottle and Beacon Reading Light through the UI; saved A=US/CA and B=UK; product switching preserved independent market and platform states; full reload restored markets from Backend while intentionally clearing session-only platform drafts.
- Compatibility/error smoke: a third Product with `Legacy Export Zone` remained visible and unchanged; adding US retained the historical value; all three supported platforms were selectable; Backend-down save showed an error and retry succeeded after recovery.
- Idempotency evidence: exactly three successful Product PATCH requests for the three intended saves; rapid duplicate submission is blocked by the synchronous save lock and disabled control.
- Isolated database side effects: 3 Products; 0 ProductAssets, MarketingBriefs, MarketingStrategies, CopyMatrices, VideoProjects, VideoRenderTasks, and VideoRenderArtifacts.
- Presentation regression: `/products?mode=presentation` redirected to `/?mode=presentation`; Product configuration was absent and `0 AI Calls` remained visible. The clean test database intentionally had no seeded Demo Snapshot, so it honestly displayed the snapshot-not-ready state without reading workspace products.
- Provider/AI calls and cost: none; no Qwen or Wanx request was made and no cost was incurred.
- Temporary services/database: stopped; the stage-named temporary SQLite and logs were permanently removed after verification.
- Known limitations: platform drafts are intentionally lost on full reload because no approved task-draft persistence contract exists; the existing frontend has no large component-test framework.
- Commit/push/tag: none.
- Single recommended next stage: V2-C1.2B Task start entry.

## 2026-07-22 — V2-C1.2B Marketing task start entry

- Status: ✅ Completed; checkpoint not yet created.
- Starting branch and HEAD: `competition-product-v2` at `7e71d6091f8b483c516f93cf61272160abcbe79b`.
- Scope: save and restore a real MarketingBrief task input for a selected Product, saved target markets, and selected platforms only; no strategy, copy, video, render, artifact, publishing, authentication, or payment work.
- Preconditions: clean working tree; `master` and `competition-freeze-v1` both remained at `98772160208840eff2f00b97b78ae34809b1786f`.
- Existing-chain audit: MarketingBrief already owns `product_id`, `audience`, `language`, `platforms`, `tone`, `objective`, and `created_at`; existing `POST /api/v1/marketing-tasks` only saves through MarketingRepository/MarketingService. Qwen is injected only by the separate `POST /api/v1/products/{product_id}/strategy` route and its MarketingStrategyService. CopyMatrix and VideoProject depend on later generated objects and were not invoked.
- API decision: reused and hardened `POST /api/v1/marketing-tasks`; added `GET /api/v1/marketing-tasks/{task_id}` and `GET /api/v1/marketing-tasks/latest?product_id=...` on the same repository/service/data model. No second Product API, duplicate data layer, ORM field, table, or migration was added.
- Data ownership: `Product.target_markets` remains the validated creation source; TikTok, Instagram, and Facebook are canonicalized/deduplicated and persisted in `MarketingBrief.platforms`. The canonical markets are snapshotted inside the existing geographic `audience` semantics and projected as `target_markets` in read responses, so later Product market changes do not rewrite an earlier task input.
- Backend validation: Product existence; 1–5 supported semantic markets (US, CA, UK, DE, FR, AU, JP, SG and documented aliases); 1–3 supported platforms; empty/unsupported platforms rejected; duplicate platforms removed; correct Product association and HTTP 201/404/422 behavior.
- Frontend implementation: the former disabled V2-C1.2B area now shows the factual Product/market/platform/selling-point/description summary and an accurately named “创建营销任务输入” action. Success displays the Backend ID, Product, saved market snapshot, platforms, creation time, persistence confirmation, and “任务输入已保存，等待 V2-C2 AI 策略生成”.
- Recovery and empty/error states: selecting a Product loads its latest Brief with an AbortController and request/product guards; no history displays an explicit empty state; load/create errors retain user configuration and expose retry. An uncertain create response first queries the latest record and adopts only a newly observed ID instead of blindly creating again. Initial latest-read failure disables creation until history is known.
- Duplicate/race protection: a synchronous submit lock prevents rapid double-click duplication independently of button disabled state; request IDs, AbortController, and active Product checks discard stale cross-Product results. Market selection/save also maintains a synchronous latest-value ref so a fast save cannot read an older render.
- MarketingBrief tests: 7 passed, 0 failed, 1 known Starlette/httpx deprecation warning. Covered creation, missing Product, empty/unsupported platforms, platform deduplication, saved-market validation, single/latest reads, Product isolation, immutable market snapshot recovery, and zero downstream generated objects.
- Product tests: 13 passed, 0 failed, 1 known Starlette/httpx deprecation warning.
- Full default pytest: 94 passed, 2 real-provider smoke tests skipped, 0 failed, 1 known Starlette/httpx deprecation warning.
- Ruff: all checks passed.
- TypeScript and Vite production build: passed; 121 modules transformed.
- Isolated browser/API/SQLite smoke: final database started empty; created Atlas Travel Bottle and Beacon Reading Light; A saved CA/US with TikTok/Instagram and restored MarketingBrief #1 after reload; B first showed no task, then saved UK with Facebook as MarketingBrief #2; switching Products restored only the matching Brief. A double-click produced one record. Database totals were exactly 2 Products and 2 MarketingBriefs, one per Product.
- Error/recovery smoke: the first isolated Frontend port required a temporary local CORS override and then the visible list retry succeeded. With Backend stopped, task creation displayed a clear error and “重试创建”; after restoring the same SQLite, reload/read recovered Brief #2 without a blind duplicate.
- Browser-driven correction: accelerated market interaction exposed stale render timing; market selection/save was changed to track the latest values synchronously, then the final smoke advanced on observable 1/5 and 2/5 states before saving. Browser console finished with 0 warnings and 0 errors.
- Presentation regression: `/products?mode=presentation` redirected to `/?mode=presentation`; the task configuration was absent and `0 AI Calls` remained visible. Demo Snapshot did not read workspace MarketingBriefs.
- Provider/AI calls and cost: none. No Qwen, Wanx, text/visual Provider, strategy, copy, video, render, or artifact generation route was called; no AI cost was incurred.
- Isolated database side effects: 2 MarketingBriefs; 0 MarketingStrategies, CopyMatrices, VideoProjects, VideoRenderTasks, and VideoRenderArtifacts. Service logs contained no strategy/copy/video/Qwen/Wanx/Provider route match.
- Temporary services/database: stopped; all stage-named temporary SQLite databases and logs were permanently removed. Repository database files were not modified.
- Known limitations: the workspace restores only the latest Brief for a Product rather than a complete history center; audience/language/tone/objective are truthful stage defaults without editing UI; MarketingStrategy generation does not consume the Brief until V2-C2; no large frontend test framework was introduced.
- Commit/push/tag: none.
- Single recommended next stage: V2-C2 Operable Qwen content chain, beginning with V2-C2.1A Strategy operation entry and requiring separate real-AI approval before any paid call.

## V2 stage update template

```markdown
## YYYY-MM-DD — V2-Cx.y Stage name

- Status:
- Starting branch and HEAD:
- Scope authorized:
- Preconditions verified:
- Files changed (explicit allowlist):
- Database/schema impact:
- Provider/AI calls: none, or approved model/count/cost envelope
- Implementation summary:
- Tests executed and exact results:
- Warnings, skips, and failures:
- Security/privacy checks:
- git diff --stat:
- git diff --check:
- Commit: none until explicitly authorized
- Push: none until explicitly authorized
- Known issues:
- Rollback point:
- Single recommended next stage:
```

## Update rules

1. Record only commands actually run and results observed.
2. Never hide failed attempts, warnings, skips, or unavailable capabilities.
3. Do not start a second V2 stage in the same update.
4. Do not mark a stage complete before its gate passes.
5. Stage explicit files only; never use `git add .`.
6. Commit and push only after explicit approval.
7. Real Qwen/Wanx smoke requires a separate cost/risk report and approval.
