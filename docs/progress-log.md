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

## 2026-07-23 — V2-C2.1A Strategy operation entry

- Status: ✅ Completed; checkpoint not yet created.
- Starting branch and HEAD: `competition-product-v2` at `b139d579c3f95de011d6da925349dd3c0b4b8fcc`.
- Scope: read-only strategy preflight and explicit future-cost acknowledgment only; no real generation, result persistence, copy generation, or video work.
- Existing-chain audit: the real endpoint remains `POST /api/v1/products/{product_id}/strategy`; it resolves `QwenProvider`, calls `provider.generate()`, validates JSON, and saves `MarketingStrategy`. The existing prompt currently consumes Product fields rather than MarketingBrief.
- Backend implementation: added `GET /api/v1/marketing-tasks/{task_id}/strategy-preflight`, a read-only service, structured response, and focused tests. Product input preparation is now a pure reusable step separated from Provider execution without changing the existing generation API contract.
- Preflight facts: validates task/Product association, Product content, immutable target-market snapshot, supported platforms, audience/language/tone/objective stage defaults, Qwen Provider type, model label, and a boolean configuration signal. No key, token, workspace ID, or secret value is returned.
- Frontend implementation: a saved MarketingBrief now exposes idle/checking/passed/blocked/error/retry states, task/Product/market/platform/default-field context, Provider/model/configuration facts, cost notice, and a session-only acknowledgment that defaults false and resets on Product or task change.
- Execution boundary: the real generation control is disabled and has no action handler. The prior Product Center generation action was neutralized; no workspace component imports or calls the existing real strategy function.
- Provider/AI calls and cost: 0. The preflight route does not resolve, instantiate, or call Qwen/Wanx/another Provider; no cost was incurred.
- Downstream data: isolated SQLite ended with 2 Products and 2 MarketingBriefs; MarketingStrategy, CopyMatrix, VideoProject, VideoRenderTask, and VideoRenderArtifact were all 0.
- Related backend tests: 25 passed, 0 failed, 1 known Starlette warning.
- Full default pytest: 99 passed, 2 real-provider smoke tests skipped, 0 failed, 1 known Starlette warning.
- Ruff: all checks passed.
- TypeScript: both frontend TypeScript project checks passed.
- Vite production build: passed with 122 modules transformed; output was written outside the repository and removed after verification.
- Isolated UI smoke: two Product/Brief contexts loaded; Alpha preflight passed with safe placeholder configuration; consent defaulted false; consent true still left execution disabled; switching to Beta reset consent and preflight state; Backend-down produced a retry action and recovery passed after restart.
- Concurrency/race protection: synchronous request lock, AbortController, request ID, active task/Product guard, response identity checks, and context-reset cleanup prevent duplicate or stale UI results.
- Presentation protection: `ProductCenterRoute` still redirects presentation mode to `/?mode=presentation`, and the existing DemoContextBar still owns `Demo Snapshot · 0 AI Calls`. A final new browser navigation assertion was blocked by browser security policy, so this item is supported by unchanged source plus successful TypeScript/build checks rather than a new browser pass.
- Temporary services/database/build output: stopped and permanently removed; no repository database, `.env`, log, screenshot, or build artifact was added.
- Known limitation: the current real strategy execution still accepts Product input only. Consuming MarketingBrief, obtaining separate authorization, calling Qwen, persisting/showing results, and failure/result-state execution remain exclusively V2-C2.1B.
- Commit/push/tag: none.
- Single recommended next stage: V2-C2.1B State, failure, and result UI, only after explicit approval for any real AI call and cost.

## 2026-07-24 — V2-C2.1B Strategy state, failure, and result UI

- Status: ✅ Completed; checkpoint not yet created.
- Starting branch and HEAD: `competition-product-v2` at `8eb4517def9d8a1e187f6405bf6988c7e4ed5530`.
- Preconditions: clean working tree; `master` and `competition-freeze-v1` both remained at `98772160208840eff2f00b97b78ae34809b1786f`.
- Scope: strategy operation states, safe failures, retry, Product-latest result read/recovery, default-off execution, and offline Fake Provider verification only. No real Qwen/Wanx call, CopyMatrix, video, migration, or history center.
- Association audit: `MarketingStrategy` has `product_id` but no `marketing_brief_id` or other direct MarketingBrief relationship. The UI and API do not invent task-to-strategy version ownership; recovered/uncertain records are labeled as the Product's latest strategy with an explicit boundary notice.
- Read API: added `GET /api/v1/products/{product_id}/strategies/latest`, returning the real persisted Strategy ID, Product ID, schema fields, and creation time. Missing Product and empty strategy both return clear 404s. Reads are Product-scoped, ordered by creation time/ID, Provider-free, and write-free.
- Existing execution compatibility: retained `POST /api/v1/products/{product_id}/strategy`; its response now additively includes persisted identity/time through `MarketingStrategyRead`. Product-only prompt behavior remains unchanged and documented as a limitation.
- Provider failure mapping: authentication, quota/rate-limit, network/unavailable, invalid output, Backend, missing record, and unknown failures map to fixed safe UI messages. Raw Provider responses, stack traces, keys, headers, workspace IDs, and signed URLs are never rendered.
- Feature flag: `VITE_ENABLE_STRATEGY_EXECUTION` is false when missing. The default production build and a separate browser pass kept the execution button disabled and displayed “当前构建未开放真实策略执行”. No enabling `.env` was created.
- State model: preflight uses idle/checking/ready/blocked/failed; execution uses idle/submitting/succeeded/failed/recovering/recovered. Product or Brief change resets consent and inapplicable state.
- Execution guards: preflight ready, `provider_configured`, session-only explicit cost consent, enabled build flag, matching task/Product identity, and no active submission must all pass both rendering and handler checks. No Effect, preflight success, Product switch, or reload automatically generates.
- Duplicate/race protection: synchronous execution lock, AbortController, context request ID, active Product/task guard, and response identity checks prevent double submits and stale UI overwrite. An uncertain failure reads Product latest before offering a user-controlled retry and never blindly repeats.
- Result UI: distinguishes “本次请求已保存” from “Backend 最近已保存记录” and shows Strategy ID, Product, creation time, positioning, audience insights, marketing angles, evidence/content pillars, risks, and source boundary. No nonexistent platform recommendation field is fabricated.
- Backend related tests: 42 passed, 0 failed, 1 known Starlette warning. Coverage includes latest read missing/empty/single/latest/Product isolation, Provider-free/read-only behavior, success, safe Provider failures, invalid output, one-strategy success, zero-strategy failure, and zero downstream generated objects.
- Full default pytest: 107 passed, 2 real-provider smoke tests skipped, 0 failed, 1 known Starlette warning.
- Ruff: all checks passed.
- TypeScript and Vite production build: passed; 123 modules transformed. Build output was written outside the repository and removed.
- Fake Provider isolation: a temporary FastAPI dependency override supplied deterministic JSON or deterministic authentication/quota/network/invalid-output failures. It ran from a temporary workspace with placeholder configuration and temporary SQLite; it contained no production debug route, made no network request, and was removed after the smoke.
- Offline browser smoke: 6 Products and 6 MarketingBriefs covered consent disabled/enabled, submitting, rapid double-click, direct success, reload/latest recovery, four safe failure categories, retry/re-preflight controls, and slow-result Product switching. The double-click success scenario logged exactly one Fake Provider call.
- Temporary database result: 2 Fake MarketingStrategies were intentionally created (one direct success and one completed slow-request race); CopyMatrix, VideoProject, VideoRenderTask, and VideoRenderArtifact counts were all 0. Failed Provider scenarios created no Strategy.
- Production-default regression: with the test flag removed, a ready preflight plus checked consent still left “调用 Qwen 生成策略” disabled and showed the default-off notice.
- Presentation regression: `/products?mode=presentation` redirected to `/?mode=presentation`; SocialPilot AI, 比赛演示模式, Demo Snapshot, `0 AI Calls`, and Overview/Copy Matrix/Video Blueprint/Growth Copilot were visible. Product Center, Preflight, execution state, and strategy result were absent; no strategy/AI request occurred and no page crash was observed.
- Provider/AI calls and cost: real Qwen 0, Wanx 0, external AI network requests 0, real credential use/output 0, AI cost 0. Fake Provider calls were local deterministic test calls only.
- Temporary cleanup: backend/frontend stopped; temporary SQLite, logs, Fake script, feature-flag process setting, and build output removed. Repository `.env`, databases, Demo Snapshot, and frozen evidence assets were not modified.
- Known limitations: strategies remain Product-owned rather than Brief-versioned; latest recovery cannot prove ownership by the current Brief and is labeled honestly; prompt input is still Product-only; full history and real Qwen/cost evidence remain future work; no large frontend test framework was added.
- Commit/push/tag: none.
- Single recommended next stage: V2-C2.2A Copy Matrix operation entry. Any real Qwen call still requires separate explicit authorization.

### V2-C2.1B-R1 correction

- Checkpoint review found that the list-item trim/blank validator had moved from `MarketingStrategySchema` to `MarketingStrategyRead`, while Provider output is validated through the base schema.
- Restored the validator to `MarketingStrategySchema`; `MarketingStrategyRead` now only adds persisted read fields and inherits the same content constraints.
- Added parameterized coverage for every generated `list[str]` field, including whitespace rejection, valid trimming, safe API errors, and zero Strategy/downstream writes for invalid Provider output.
- Result source labels now distinguish “本次生成策略” from “商品最新策略”, while retaining the explicit no-direct-MarketingBrief-version boundary.
- Real AI calls and cost: 0. No Qwen, Wanx, or external AI request was made.

## 2026-07-25 — V2-C2.1C MarketingBrief-aware Strategy Input and Execution Contract

- Status: ✅ Completed; checkpoint not yet created.
- Starting branch and HEAD: `competition-product-v2` at `e38c4903d6a9af06812d86ce08e2fc2b8601366b`; working tree and staged area were clean; protected `master` and `competition-freeze-v1` remained at `98772160208840eff2f00b97b78ae34809b1786f`.
- Chain audit: `MarketingBrief` persists `product_id`, `platforms`, `audience`, `language`, `tone`, `objective`, and `created_at`; its immutable target-market snapshot is encoded in the existing `audience` geographic prefix and projected by the service. `MarketingStrategy` still persists only `product_id`, with no Brief foreign key.
- Architecture correction: the workspace no longer executes the Product-only strategy route. It now uses `POST /api/v1/marketing-tasks/{task_id}/strategy`, which resolves the exact requested Brief, runs Preflight, builds one structured Prompt in the service layer, validates Provider output with the existing `MarketingStrategySchema`, saves through the existing repository, and returns source metadata.
- Prompt inputs: Product name, category, description, and selling points plus exact Brief ID, immutable market snapshot, platforms, audience, language, tone, and objective are present in the Fake Provider's received Prompt. Tests prove the requested older Brief is used rather than silently substituting the latest Brief.
- Execution response: `source_task_id`, `source_product_id`, `source_kind=marketing_brief`, persisted Strategy, `association_persisted=false`, and an explicit association notice describe only this response. No database Brief→Strategy relationship is claimed.
- Backend safety gate: `ENABLE_STRATEGY_EXECUTION` defaults false independently of `provider_configured`. Both the new task-bound route and compatible `POST /api/v1/products/{product_id}/strategy` stop before Provider resolution and before writes when disabled. No enabling `.env` was created.
- Preflight contract: separately reports `input_ready`, `provider_configured`, `execution_enabled`, and `ready_for_execution`; it returns booleans only and never returns configuration sources or secret values.
- Frontend contract: execution requires matching Product/task identity, input readiness, Provider configuration, Backend authorization, frontend feature flag, explicit cost consent, and the synchronous submission lock. Direct results show “本次生成策略” and the source MarketingBrief; reload recovery shows “商品最新策略” and states that current Brief ownership cannot be proven.
- Browser-discovered correction: Preflight and initial latest-result recovery previously shared one request sequence. Running Preflight before recovery completed could strand the UI in “正在核对结果”. Separate Preflight/context request sequences now preserve recovery completion while retaining stale-response protection.
- Backend verification: Strategy/MarketingBrief/Product/Qwen focused suite 80 passed, 0 failed; full default pytest 145 passed, 2 real-provider smoke tests skipped, 0 failed, 1 known Starlette warning; Ruff passed.
- Frontend verification: no-output TypeScript check passed; Vite production build passed with 123 modules transformed, and build output was removed.
- Offline browser/Fake Provider smoke: temporary SQLite plus FastAPI dependency override and safe placeholder configuration verified exact task-bound success, one Strategy after rapid double click, direct source metadata, reload recovery label/boundary, Product/task switching, deterministic network failure with retry UI, both default-off notices and disabled button, and Presentation redirect with four-stage navigation.
- Browser console and Presentation: 0 page errors and 0 warnings; `/products?mode=presentation` redirected to `/?mode=presentation`; Demo Snapshot and `0 AI Calls` were visible; Product/Strategy workspace content was absent.
- Temporary database result: 1 MarketingStrategy from the intended success scenario; CopyMatrix, VideoProject, VideoRenderTask, and VideoRenderArtifact all remained 0. The deterministic failed scenario wrote no additional Strategy.
- Provider/AI calls and cost: real Qwen 0, Wanx 0, external AI network requests 0, AI cost 0. Only local deterministic Fake Provider calls occurred.
- Cleanup and security: Backend/Frontend stopped; temporary SQLite, logs, build output, and process-only flags were removed. Repository `.env`, database, Demo Snapshot, frozen evidence, ORM, and migrations were not modified.
- Roadmap correction: Copy Matrix cannot start directly after Product-only prompting. Required order is V2-C2.1C checkpoint → separately authorized controlled real Qwen verification → real Strategy result acceptance → V2-C2.2A Copy Matrix operation entry.
- Commit/push/tag: none.
- Single recommended next stage: establish the V2-C2.1C checkpoint; after acceptance, prepare a separately authorized controlled real Qwen verification plan.

## 2026-07-26 — V2-C2.1D Controlled real Qwen verification evidence

- Status: ✅ Completed.
- Contract commit: `dc0b04eb45dc02f6350eee45d983becd37ff90b2`.
- Authorization: one separately authorized real Provider call, with a strict maximum of one call and no automatic retry.
- Execution: the task-bound `POST /api/v1/marketing-tasks/{task_id}/strategy` path made exactly one real `qwen-plus` Provider call against isolated temporary SQLite.
- Result: HTTP 200; the execution response contract and `MarketingStrategySchema` validation passed.
- Prompt evidence: boolean checks passed for Product name, category, description, and selling points, plus the exact Brief ID, Product ID, target-market snapshot, platforms, audience, language, tone, and objective. No Prompt text or raw Provider payload was recorded.
- Response evidence: source Task and Product identities were correct, `source_kind=marketing_brief`, `association_persisted=false`, and the association notice was present.
- Quality summary: positioning was non-empty; audience insights had 4 items, angles 3, risks 3, and evidence 5; trimming passed; US, TikTok, and portable-blender business context were present.
- Database result: 1 Product, 1 MarketingBrief, and 1 MarketingStrategy in the temporary database; CopyMatrix, VideoProject, VideoRenderTask, and VideoRenderArtifact remained 0.
- Cleanup: the temporary SQLite and directory were removed; no service or temporary file remained; the repository database, local environment file, and working tree were unchanged by execution.
- Security and cost: no secret, authentication header, Prompt, or raw Provider response was recorded. Exact token usage, Credits, and monetary cost were not recorded; the call may have consumed Alibaba Cloud Bailian Credits.
- Capability boundary: MarketingStrategy still persists only `product_id`. The Brief association exists only in the direct execution response; reload can recover only the Product's latest Strategy and cannot prove ownership by a specific MarketingBrief.
- Authorization state: the one-call authorization is exhausted. Any later real AI call requires new explicit user authorization and must never start automatically.
- Next stage: V2-C2.2A Copy Matrix operation entry remains pending and was not started.

## 2026-07-26 — V2-C2.2A Copy Matrix operation entry

- Status: ✅ Completed; checkpoint not yet created.
- Starting branch and HEAD: `competition-product-v2` at `813f4fbb683650daa4e7ffdda7be0e41ede2face`; working tree and staged area were clean, and protected `master`/`competition-freeze-v1` remained at `98772160208840eff2f00b97b78ae34809b1786f`.
- Existing-chain audit: `POST /api/v1/products/{product_id}/copy` injects Qwen, selects the Product's latest MarketingStrategy, builds a Product/Strategy Prompt, requires exactly TikTok, Instagram, and Facebook, and ignores MarketingBrief platforms. No ordinary-workspace Copy read API exists.
- Real association: CopyMatrix persists `product_id` and `marketing_strategy_id`, so a saved matrix can prove its exact Strategy. It has no MarketingBrief ID, and the Strategy itself still has no persisted Brief relationship; neither the preflight nor a reload can prove Brief-version ownership.
- Backend safety: added independent `ENABLE_COPY_EXECUTION`, default false. The old Copy route checks it before Provider resolution, and CopyGenerationService checks it again before reads, Provider calls, or writes. It is separate from Strategy execution and Provider configuration.
- Preflight API: added read-only `GET /api/v1/marketing-tasks/{task_id}/strategies/{strategy_id}/copy-preflight`. It resolves only the exact URL Brief and Strategy, validates both Product associations, Product and Strategy fields, the immutable market prefix, and supported Brief platforms. It does not resolve a Provider, construct a Provider request, select a latest record, or write CopyMatrix.
- Honest contract result: `contract_ready=false` and `ready_for_execution=false`. The missing requirement identifies the future Brief-aware, exact-Strategy Copy contract because the compatible old executor still chooses latest Strategy and forces all three platforms.
- Frontend safety: added independent `VITE_ENABLE_COPY_EXECUTION`, default false; no enabling environment file was added. The old Product Center Copy handler was removed. The new panel appears only with a Strategy, displays exact Product/Brief/Strategy/source/market/platform facts, runs only Preflight, resets consent on context changes, and uses AbortController, request IDs, active-context checks, and a synchronous lock.
- Cost and action boundary: consent defaults unchecked and is session-only. The “调用Qwen生成Copy Matrix” button remains natively disabled after consent and has no action handler; it states that V2-C2.2B must complete first and that generation is neither publishing nor social-account authorization.
- Backend verification: Copy/Strategy/Marketing/Product focused suite 89 passed; full default pytest 153 passed, 2 real-provider smoke tests skipped, 0 failed, 1 known Starlette warning; Ruff passed.
- Frontend verification: TypeScript passed; Vite production build passed with 124 modules transformed; the dedicated temporary output directory was removed.
- Offline smoke: isolated SQLite contained exactly 2 Products, 2 MarketingBriefs, and 2 deterministic MarketingStrategies. Exact preflights returned the requested IDs and Brief platforms; cross-Product pairing was rejected; rapid double-click produced one request for that context; switching Product reset consent and showed the second Brief/Strategy without stale data.
- Browser safety result: Backend Copy and Frontend Copy flags were false; the generated action remained disabled before and after consent. Access logs contained 2 intended Copy Preflight GETs and 0 Copy/Strategy execution POSTs. CopyMatrix, VideoProject, VideoRenderTask, and VideoRenderArtifact remained 0.
- Presentation regression: `/products?mode=presentation` redirected to `/?mode=presentation`; Demo Snapshot, `0 AI Calls`, four-stage navigation, and the read-only three-platform Copy Matrix were visible from a temporary database copy. The ordinary Copy Preflight, consent, and execution controls were absent; console finished with 0 errors and 0 warnings.
- Provider/AI calls and cost: real Qwen 0, Wanx 0, Fake Provider 0, external AI requests 0, AI cost 0.
- Cleanup and repository protection: temporary services, both temporary SQLite files, logs, and build output were removed. Repository `.env` and database metadata/hash remained unchanged; no ORM, table, migration, frozen evidence, or Demo Snapshot source was modified.
- Known limitations: no Brief-aware Copy Prompt/executor, no partial platform matrix, no Copy read/recovery UI, and no persisted MarketingBrief association. V2-C2.2B remains pending.
- Commit/push/tag: none.
- Single recommended next stage: V2-C2.2B Brief-aware exact-Strategy Copy execution, save, and recovery contract; any real AI call still requires separate explicit authorization.

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
