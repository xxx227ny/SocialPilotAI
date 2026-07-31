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

## 2026-07-27 — V2-C2.2B Brief-aware Exact-Strategy Copy Execution, Save and Recovery Contract

- Status: ✅ Completed; checkpoint not yet created.
- Starting branch and HEAD: `competition-product-v2` at `5292f96607b3cc208e8a4c4816bb1de88818af84`; working tree and staged area were clean, and protected `master`/`competition-freeze-v1` remained at `98772160208840eff2f00b97b78ae34809b1786f`.
- Existing contract audit: CopyMatrix persists `product_id`, `marketing_strategy_id`, `copies`, and `created_at`; it has no MarketingBrief foreign key. The compatible `POST /api/v1/products/{product_id}/copy` continues to select the Product's latest Strategy and require TikTok, Instagram, and Facebook together.
- Task-bound execution: added `POST /api/v1/marketing-tasks/{task_id}/strategies/{strategy_id}/copy`. The route gate runs before Provider resolution; the service repeats the gate, resolves only the exact URL Brief and Strategy, validates their shared Product through Preflight, builds the structured Prompt, calls the injected Provider, validates the output, and saves through CopyMatrixRepository.
- Prompt boundary: the pure builder includes Product ID/name/category/description/selling points; exact Brief ID/product ID/immutable target-market snapshot/platforms/audience/language/tone/objective; and exact Strategy ID/product ID/positioning/audience insights/angles/risks/evidence. User fields are marked untrusted data. Prompt text is not returned to the UI or logged.
- Platform contract: only the normalized unique 1–3 platforms saved on the Brief may be returned. Missing, extra, duplicate, unsupported, or whitespace-only platform content is rejected before persistence. Valid hook, caption, hashtags, and CTA values are trimmed. The legacy three-platform Schema and Product-only Prompt remain compatible.
- Persistence without schema change: the task-bound repository method writes the already validated dynamic platform JSON directly to the existing table, preserving the unchanged legacy ORM validator and old three-platform path. No ORM, table, or migration was modified.
- Execution response: returns exact source task, Strategy, and Product IDs; `source_kind=marketing_brief_and_strategy`; requested platforms; the saved matrix; `strategy_association_persisted=true`; `brief_association_persisted=false`; and an explicit association notice.
- Recovery: added read-only `GET /api/v1/strategies/{strategy_id}/copy/latest`. It verifies the Strategy, returns only that Strategy's latest persisted CopyMatrix, resolves no Provider, and performs no write. The UI labels recovered data “该策略最新Copy Matrix”, never as the current Brief's result.
- Preflight upgrade: the exact Brief/Strategy execution contract is implemented, so `contract_ready=true` independently of runtime authorization. Default Backend execution remains false, therefore default `ready_for_execution=false`; the old missing contract requirement was removed.
- Frontend state and safety: CopyPreflightPanel now supports idle/checking/ready/blocked/submitting/succeeded/failed/recovering/recovered, direct and recovery labels, exact source facts, platform-only result cards, safe failure categories, AbortControllers, request IDs, active-context guards, and a synchronous submission lock. Uncertain responses query exact-Strategy recovery before offering retry. No Effect automatically executes generation.
- Backend verification: Copy-focused tests 34 passed; Copy/Strategy/MarketingTask/Product regression 109 passed; full default pytest 173 passed, 2 real-provider tests skipped, 0 failed, 1 known Starlette warning; Ruff passed.
- Frontend verification: TypeScript passed; Vite production build passed with 124 modules transformed. The default build left `VITE_ENABLE_COPY_EXECUTION` false.
- Offline Fake Provider browser smoke: process-only Backend and Frontend Copy flags enabled against isolated SQLite. Rapid double-click produced one POST. The single-platform case saved only TikTok; the multi-platform case saved exactly TikTok and Instagram; page reload/reselection recovered by exact Strategy. Invalid-output and simulated network-uncertainty cases showed safe retry states and wrote no matrix.
- Temporary database result: 4 Products, 4 MarketingBriefs, 4 MarketingStrategies, 2 valid CopyMatrices, and 0 VideoProject, VideoRenderTask, or VideoRenderArtifact records. The 4 deterministic Fake Provider calls were one each for single-platform success, multi-platform success, invalid output, and uncertainty simulation. Old Copy POST and Strategy execution POST counts were 0.
- Default-off verification: with the Frontend Copy flag unset, the execution button remained disabled after Preflight and fee acknowledgement even while the isolated Backend gate was enabled. Backend gate tests separately proved Provider resolution 0 and CopyMatrix writes 0 when disabled.
- Presentation regression: `/products?mode=presentation` redirected to `/?mode=presentation`; Demo Snapshot, `0 AI Calls`, four-stage navigation, and the read-only three-platform Copy Matrix were visible from a temporary repository-database copy. Ordinary Copy execution/status/result UI was absent; console finished with 0 errors and 0 warnings; Provider and execution requests were 0.
- Provider/AI calls and cost: real Qwen 0, Wanx 0, other external AI requests 0, AI cost 0. Only the deterministic offline Fake Provider was invoked.
- Cleanup and repository protection: temporary services, SQLite databases, Provider telemetry, logs, launcher, and build output were removed; ports 8000/5173 were released. Repository `.env` remained 417 bytes with its prior timestamp, and repository database SHA-256 remained `BA74D9DF99A9595DB189B9032B2EFA8E07F540752A61B3D5E88231B6AEE13C63`.
- Commit/push/tag: none.
- Known limitation: CopyMatrix proves its exact Strategy through `marketing_strategy_id`, but cannot persist or recover a MarketingBrief association. No publishing, platform-account authorization, VideoProject, Wanx call, or real Copy Provider verification was added.
- Single recommended next stage: V2-C3.1A VideoProject to RenderTask operation entry, beginning with a read-only contract and Fake-only verification; any real Qwen or Wanx call still requires separate explicit authorization.

## 2026-07-27 — V2-C2.2C Real Copy Qwen Verification Evidence

- Status: ✅ Completed.
- Contract commit: `88429d781b37c3bfa28a213c4969fc82dcfab6e6`.
- Controlled execution: one separately authorized task-bound, Brief-aware, exact-Strategy Copy POST made exactly one real `qwen-plus` Provider call, with zero SDK retries and zero outer retries.
- Result: HTTP 200. Boolean checks passed for the Product, MarketingBrief, and MarketingStrategy Prompt field groups, the exact US target-market snapshot, and the exact TikTok platform snapshot. The complete Prompt, raw request, and raw Provider response were not recorded.
- Platform and response contract: output contained TikTok only, with no Instagram, Facebook, duplicate, or additional platform. Source Task, Strategy, and Product IDs were correct; `source_kind=marketing_brief_and_strategy`; `strategy_association_persisted=true`; `brief_association_persisted=false`; and the association notice was present.
- Copy quality: hook, caption, and CTA were non-empty and trimmed; hashtags were non-empty with no whitespace-only item; the saved CopyMatrix referenced the exact Product and Strategy.
- Temporary database: before execution there were 1 Product, 1 MarketingBrief, 1 deterministic local MarketingStrategy, 0 CopyMatrix, and 0 VideoProject/VideoRenderTask/VideoRenderArtifact records. After execution only CopyMatrix increased, from 0 to 1.
- Strategy source boundary: the Strategy was deterministic local preparation data in temporary SQLite. No Qwen Strategy generation occurred, and this verification assessed the Copy execution contract rather than Strategy quality.
- Persistence boundary: CopyMatrix persists `product_id` and `marketing_strategy_id` but has no MarketingBrief foreign key. Reload can prove the exact Strategy association, not a persisted association with the selected Brief.
- Unused generation paths: legacy Product-only Copy POST 0, Strategy generation 0, Wanx 0, and Video generation 0.
- Cleanup and repository protection: the temporary SQLite and directory were deleted; ports 8000/5173 had no residual listeners; the repository database, `.env`, and Git working tree remained unchanged.
- Security and cost: no Key value, authentication header value, complete Prompt, or raw Provider response was recorded. The call may have consumed Alibaba Cloud Bailian Credits; exact Token usage, Credits, and monetary cost were not queried or invented.
- Authorization state: the single-call authorization is exhausted. Any later Qwen or Wanx call requires new explicit user authorization.
- Single recommended next stage: V2-C3.1A VideoProject to RenderTask Operation Entry, beginning default-off and Fake-only with no real Wanx call.

## 2026-07-27 — V2-C3.1A VideoProject to RenderTask Operation Entry

- Status: ✅ Completed; checkpoint not yet created.
- Starting branch and HEAD: `competition-product-v2` at `6d36f5182453427b85763ff7deb4acf656f24dca`; working tree and staged area were clean, and protected `master`/`competition-freeze-v1` remained at `98772160208840eff2f00b97b78ae34809b1786f`.
- Existing association audit: VideoProject persists `product_id`, `marketing_strategy_id`, and `copy_matrix_id`; it has no MarketingBrief foreign key. VideoRenderTask persists its VideoProject, scene, status, Provider task identity, server-owned render Prompt, render parameters, unique idempotency key, safe errors, and timestamps. VideoRenderArtifact is unique per RenderTask and can hold a Provider URL or storage path.
- Existing execution audit: local RenderTask creation is idempotent by key; submit uses an atomic CREATED-state claim; refresh never submits; succeeded artifact writes update the unique task artifact. However, ordinary submit/refresh previously had no independent default-off Gate, uncertain submit recovery is incomplete, and the current Provider URL is not proven durable storage.
- Read APIs: added exact `GET /api/v1/video-projects/{video_project_id}` and deterministic Product-scoped `GET /api/v1/products/{product_id}/video-projects/latest`; both are read-only, resolve no Provider, and return safe 404s.
- Preflight API: added `GET /api/v1/video-projects/{video_project_id}/render-preflight`. It validates the exact Product and persisted Strategy/Copy associations, required VideoProject fields, non-empty scenes, trimmed scene schema, and timeline. It returns only safe Provider/execution booleans, project summaries, non-exact cost notice, and the honest association boundary; it returns no Key, Workspace ID, Prompt, signed URL, or Provider payload.
- Execution gates: added independent Backend `ENABLE_VIDEO_RENDER_EXECUTION` and frontend `VITE_ENABLE_VIDEO_RENDER_EXECUTION`, both strict false when absent. Ordinary submit/refresh routes stop before Provider resolution, and VideoRenderExecutionService repeats the Gate before reads or external calls. The existing fixed presentation live-demo route retains its separate `ENABLE_LIVE_WANX_DEMO` boundary.
- Honest readiness: `input_ready=true` for valid projects, but `contract_ready=false` and `ready_for_execution=false`. Missing contracts are `exact_video_project_render_task_execution_contract`, `uncertain_submit_recovery_contract`, and `durable_video_artifact_storage_contract`.
- Workspace UI: Product Center now restores the selected Product's latest VideoProject and runs exact Preflight with AbortController, request IDs, active Product/VideoProject guards, synchronous retry lock, safe loading/empty/failure/blocked/retry states, and explicit Product/Strategy/Copy versus absent Brief association text. The future “创建RenderTask · V2-C3.1B经授权后开放” button is natively disabled and has no handler.
- Backend verification: Video/Render/Wanx local tests 51 passed; Product/Marketing/Strategy/Copy/Video regression 160 passed; full default pytest 184 passed, 2 real-provider smoke tests skipped, 0 failed, and 1 known Starlette deprecation warning; Ruff passed.
- Frontend verification: TypeScript passed; Vite production build passed with 125 modules transformed. Build output was written outside the repository and removed.
- Browser smoke: isolated SQLite contained 2 deterministic local Products and 2 VideoProjects. Product A/B restored only their own exact projects; valid field and Preflight summaries displayed; Backend and frontend execution flags remained false; the RenderTask button stayed disabled. Backend-down showed a safe error, recovery succeeded, and rapid double-click produced one latest-project GET and one Preflight GET.
- Browser request and database counts: final recovery access log contained latest-project GET 1, Preflight GET 1, submit 0, refresh 0, live-render 0, and Video/Render POST 0. The temporary database ended with 2 Products, 2 VideoProjects, 0 VideoRenderTasks, and 0 VideoRenderArtifacts. The new Preflight path resolved and called no Provider.
- Presentation regression: `/products?mode=presentation` redirected to `/?mode=presentation`; SocialPilot AI, competition mode, Demo Snapshot, `0 AI Calls`, and Overview/Copy Matrix/Video Blueprint/Growth Copilot navigation were visible. Product Center, Video Render Preflight, and the RenderTask button were absent; console finished with 0 errors and 0 warnings.
- Non-functional observations: the first Vite build attempt was blocked before build by sandbox denial of Vite's temporary config cache and then passed with approved local cache access. The first Smoke launcher used an unavailable conventional Node path; Backend data preparation succeeded, services were stopped or reused safely, and the actual local Node path was then used. The first browser navigation wait timed out even though the page had loaded; direct URL/DOM inspection confirmed the page and subsequent browser checks passed.
- Provider/AI calls and cost: real Qwen 0, real Wanx 0, other external Provider calls 0, AI cost 0. Existing regression tests use only deterministic local Mock/Fake visual Providers; the V2-C3.1A Preflight and browser Smoke made 0 submit and 0 refresh calls.
- Cleanup and repository protection: temporary services, SQLite, logs, and build output were removed; ports 8000/5173 were released. Repository `.env`, database, verified Wanx video, frozen Demo Snapshot, ORM, tables, and migrations were not modified.
- Known limitations: no one-action exact VideoProject RenderTask execution contract, no execution UI, no polling/state recovery UI, no safe uncertain-submit reconciliation, and no proven durable artifact storage. The legacy local RenderTask-create API remains separate from the new disabled workspace entry.
- Commit/push/tag: none.
- Single recommended next stage: V2-C3.1B Exact VideoProject RenderTask Execution, State and Recovery Contract. Any real Wanx call still requires new independent explicit user authorization.

## 2026-07-27 — V2-C3.1B Exact VideoProject RenderTask Execution, State and Recovery Contract

- Status: completed; checkpoint pending.
- Starting branch and HEAD: `competition-product-v2` at `6949cf60814f8848439ffea5aecd63f096078ff8`; `master` and `competition-freeze-v1` remained at `98772160208840eff2f00b97b78ae34809b1786f`.
- Scope authorized: exact ordinary-workspace VideoProject execution, RenderTask state/recovery, explicit refresh, durable Artifact persistence and stable reading, using only temporary SQLite and deterministic Fake Wanx.
- Existing-chain decision: retained the single-Scene RenderTask model, repositories, legacy create/submit/read/refresh routes, existing idempotency column/unique constraint, and Artifact model. Added one minimal orchestration service/route and safe read/storage abstractions instead of a second model or repository stack.
- Final APIs: exact execution `POST /api/v1/video-projects/{video_project_id}/render-execution`; deterministic latest recovery `GET /api/v1/video-projects/{video_project_id}/render-tasks/latest`; exact safe recovery `GET /api/v1/video-render-tasks/{task_id}/recovery`; stable Artifact metadata/content `GET /api/v1/video-render-artifacts/{artifact_id}` and `/content`. Existing refresh remains explicit and never submits.
- RenderTask and idempotency: one task represents server-selected Scene 1, not an entire multi-scene composite. The SHA-256 idempotency key covers the exact VideoProject, Scene identity/content, provider, model, duration, aspect ratio, resolution, and contract version. Duplicate execution returns the same task; terminal and uncertain tasks never resubmit.
- State and uncertainty contract: added `SUBMITTING`, `SUBMIT_UNKNOWN`, `REFRESHING`, and `ARTIFACT_PERSIST_FAILED` without changing ORM or tables. A network/timeout acknowledgement gap becomes `SUBMIT_UNKNOWN`; repeated execution only restores that task because the Provider has no client-idempotency lookup. No provider task ID is fabricated and no automatic submit retry occurs.
- Artifact contract: Fake output bytes are content-type and size checked, stored under a configurable repository-external root using a server-generated task/hash filename, temporary file, `fsync`, and atomic replace. Only a relative storage path is persisted. Success finalization and the single Artifact record are committed together; storage failure cannot appear as success. Metadata/content reads enforce root containment and expose neither local absolute paths nor Provider URLs.
- Preflight and gates: implemented contract requirements now compute `contract_ready=true`; storage configuration is checked separately. Backend and frontend execution flags both remain default false, so the default environment reports `execution_enabled=false` and `ready_for_execution=false`. Route gate precedes Provider resolution, the service repeats the gate, and the UI/handler also require every Preflight condition, exact identities, fee confirmation, and synchronous locks.
- Frontend: added idle/loading/checking/ready/blocked/creating/submitting/submitted/processing/refreshing/succeeded/failed/submit-unknown/artifact-persist-failed/recovering/recovered states, safe error categories, explicit refresh, stable Artifact playback, reload recovery, AbortController/request IDs, active Product/Project/Task guards, and synchronous submit/refresh locks. There is no automatic polling or execution Effect.
- Backend tests: existing Video subset 39 passed; new contract suite 36 passed; complete Video/Render/Artifact/Wanx/live selection 66 passed with 1 known warning; Product/Marketing/Strategy/Copy/Video regression 176 passed, 1 skipped, 25 deselected, 1 warning; full default pytest 200 passed, 2 real-provider tests skipped, 1 known Starlette warning.
- Static/build gates: Ruff passed; TypeScript passed from the frontend workspace; Vite production build passed with 125 modules transformed. Build output was written outside the repository and removed.
- Browser Fake Wanx Smoke: isolated SQLite seeded four exact Product/VideoProject contexts. Success produced task 1, explicit `PENDING → RUNNING → SUCCEEDED`, one stable MP4 Artifact, and reload recovery. Uncertain submit produced `SUBMIT_UNKNOWN`; authentication produced safe `FAILED`; storage failure produced `ARTIFACT_PERSIST_FAILED` with no Artifact. Rapid double-click produced one execution POST and one refresh per action; context switching did not leak stale state.
- Fake call and write counts: 4 Fake submit calls across four intentionally distinct scenarios; 3 Fake refresh calls; 2 local Fake output-fetch calls; no external network. Final enabled Smoke database contained 4 RenderTasks (`SUCCEEDED`, `SUBMIT_UNKNOWN`, `FAILED`, `ARTIFACT_PERSIST_FAILED`) and exactly 1 Artifact. The separate default-off Smoke contained 0 RenderTasks and 0 Artifacts with submit/refresh/output-fetch all 0.
- Backend-down and Presentation regression: Backend-down showed a safe list error and retry entry with no execution request. `/products?mode=presentation` redirected to `/?mode=presentation`; Demo Snapshot, `0 AI Calls`, and all four presentation stages were visible, while Product Center/RenderTask/Artifact UI and workspace requests were absent. Console ended with 0 errors and 0 warnings.
- Non-functional observations: initial pytest temporary-directory creation was blocked by the environment and passed with explicit repository-external `--basetemp` paths. The first TypeScript command was run from the repository root and printed help; the frontend-workspace rerun passed. The first browser launcher used an invalid one-platform CopyMatrix seed and was corrected in the repository-external launcher before a clean database restart. A combined service startup attempt timed out, and the first default-off restart used the wrong working directory/npm path; all temporary processes were stopped or verified absent before corrected clean restarts.
- Provider/AI calls and cost: real Wanx 0, real Qwen 0, other external AI 0, AI cost 0. Only dependency-overridden deterministic Fake Wanx and local frozen MP4 bytes were used.
- Repository protection and cleanup: no ORM/table/migration, `.env`, repository database, frozen Demo Snapshot, or verified Wanx MP4 change. Temporary services, SQLite databases, Artifact directories, logs, launchers, pytest directories, and build output were removed; ports 8000/5173 were released.
- Known limitations: Scene 1 only; no whole-project composite rendering; no Provider-side lookup for automatic uncertain-submit reconciliation; explicit refresh only; local filesystem storage only; no claim of byte-range support; no MarketingBrief foreign key.
- Commit/stage/push/tag: none.
- Single recommended next stage: Controlled Real Wanx Render Verification Readiness. Readiness itself is read-only; any real Wanx call requires a later, separate, explicit user authorization.

## 2026-07-27 — V2-C3.1C Controlled Real Wanx Render Verification Evidence

- Contract Commit: `7257c189f0ebdec6a53b800e988a3012d129afd6`.
- Provider and model: Alibaba Cloud Bailian / Wanx, `wan2.7-t2v`, Region `cn-beijing`, Text-to-Video.
- Authorization and calls: maximum Submit 1 / actual 1; maximum Refresh 19 / actual 3 with a minimum 15-second interval; maximum output download 1 / actual 1; automatic and outer retries 0; Qwen 0; Live Demo 0.
- HTTP and state result: one `render-execution` POST returned HTTP 200; all three Refresh requests returned HTTP 200; state changed `PENDING → RUNNING → RUNNING → SUCCEEDED`; total elapsed time was 49.3 seconds. There was no second Submit, `SUBMIT_UNKNOWN`, or Artifact storage failure.
- Redacted input: exact Scene 1, requested 2 seconds, `9:16`, and `720P`, with a short non-sensitive portable-blender product scene. The complete Prompt was not recorded.
- Isolated object counts: Product 1, MarketingStrategy 1, CopyMatrix 1, VideoProject 1, VideoRenderTask 1, and VideoRenderArtifact 1. Preparation data was deterministic and local; Qwen was not used. Task/VideoProject and Product/Strategy/CopyMatrix associations were correct; VideoProject still has no MarketingBrief foreign key.
- Artifact evidence: `video/mp4`, 825,844 bytes, SHA-256 `e30bbdb2904b28b73b227f652593c4da4517e293d1680fc9aec3c97a5bfc33ce`; a controlled relative `storage_path`; no persisted Provider playback URL; size/hash metadata matched; stable content API reading passed; second download 0.
- Media and visual boundary: no `ffprobe`, media player, or decoder independently parsed the generated MP4. Requested `720P`, `9:16`, and 2 seconds are not asserted as decoded output properties. Codec, actual resolution/duration, frame rate, audio track, and visual quality were not independently accepted.
- Product boundary: Scene 1 only, not a multi-scene composite; explicit Refresh rather than automatic polling; `SUBMIT_UNKNOWN` requires manual reconciliation; local filesystem Artifact storage only; no object storage or dedicated Range-support claim.
- Security and cleanup: no Key, Workspace ID, Authorization Header, Provider Task ID value, complete Prompt, raw Provider request/response, signed URL, or private path was recorded. Temporary SQLite, Artifact/video, script, logs, progress, and result files were deleted; ports 8000/5173 were released; repository `.env`, database, frozen MP4, and Git working tree remained unchanged.
- Retention and cost: the generated video was deleted and is not a permanent evidence asset. The real Submit may have consumed Alibaba Cloud Bailian Credits; exact Credits, amount, and remaining balance were not queried or invented.
- Authorization state: Submit, Refresh, and download authorization is exhausted. No further Wanx call or Provider-output access is permitted without new independent user authorization.
- Next pending roadmap node: V2-C3.2A Stable asset display and download; it was not started in this stage.

## 2026-07-27 — V2-C3.2A Stable Asset Display and Download

- Status: completed; checkpoint pending.
- Starting branch and HEAD: `competition-product-v2` at `9385047f2f4b7c4151c6208a5779f0eb011e846b`; staged was empty, the worktree was clean, and protected `master`/`competition-freeze-v1` remained at `98772160208840eff2f00b97b78ae34809b1786f`.
- Existing capability audit: VideoRenderArtifact is one-to-one with VideoRenderTask and stores Provider output URL, controlled storage path, JSON metadata, expiry, and timestamps. The metadata and content routes existed, but content relied on generic file delivery, had no project-owned Range/416/HEAD/download contract, and the workspace player did not refetch verified metadata or expose explicit playback/download states.
- Safe metadata: `GET /api/v1/video-render-artifacts/{artifact_id}` now resolves the same controlled file used by content/download and returns only Artifact/Task IDs, safe provider name, content availability, content/download URLs, type, size, persisted SHA-256, local storage kind, and timestamps. It returns no storage path, absolute path, Provider output URL, Provider Task ID, signed URL, Workspace ID, Key, Token, or Header.
- Content and download: stable content streams complete GET with 200 and supports one byte range in `start-end`, `start-`, or `-suffix` form with 206 and exact headers. Invalid, reversed, out-of-range, empty, unsupported-unit, and multipart ranges return 416 with `Content-Range: bytes */total`. HEAD returns the full safe headers and no body. Download streams a 200 attachment with a server-generated Artifact/Task filename and performs no redirect or external fetch.
- Integrity and path safety: metadata, playback, and download share one resolver. It rejects absolute and multi-part/traversal paths, resolved paths outside the storage root, symlink escapes, directories, missing files, unsupported suffix/type, absent or non-SUCCEEDED tasks, size/type mismatches, and malformed persisted SHA-256. SHA-256 is not recalculated for every playback/download request; the read contract relies on the digest computed and persisted when the Artifact was stored, plus current path/type/size checks.
- Workspace UI: added a dedicated stable-Artifact panel with `artifact_idle/loading/ready/missing/invalid`, `playback_loading/ready/failed`, and `download_ready/failed` states; Product/Project/Task/Artifact guards; AbortController and request IDs; safe retry; 9:16 `object-fit: contain` playback; human-readable size and shortened hash; local-storage/single-Scene boundary text; and a locked download action that cannot submit or refresh rendering.
- Backend verification: Artifact/Range/Download suite 26 passed with 1 safe Windows symlink-capability skip; combined Video/Render regression 64 passed with 1 skip; Product/Strategy/Copy regression 88 passed; full default pytest 226 passed, 3 real-provider smoke tests skipped, 0 failed, and 1 known Starlette deprecation warning. Ruff passed.
- Frontend verification: TypeScript passed. Vite production build passed with 126 modules transformed; output was written outside the repository and removed.
- Browser smoke: temporary SQLite and a repository-external Artifact directory used a read-only copy of `demo_assets/verified_wanx_output.mp4`. The exact Product/VideoProject/RenderTask/Artifact recovered; the browser used the stable Backend content URL, reached media `readyState=4`, decoded 720×1280 without error, remained paused with autoplay false, and used a 9:16 container with `object-fit: contain`.
- Range/download evidence: browser media requests returned 206. An explicit `bytes=0-99` check returned 100 bytes and `Content-Range: bytes 0-99/1947573`. Download returned 1,947,573 bytes and SHA-256 `8e6da684f207a6c193888e93b8c5e9d9825d9882dd005a347dd8de589ff6711f`, exactly matching the frozen source copy.
- Recovery and isolation: page reload recovered the exact Task/Artifact; Product switching removed the old player; a missing local file produced a safe Artifact-missing state and local-only retry; Backend-down produced a safe list error and recovered after retry. Presentation redirected to `/?mode=presentation`, retained Demo Snapshot, `0 AI Calls`, and all four stages, and showed no workspace player or download action. Final console result was 0 errors and 0 warnings.
- Side effects: Render Submit 0, Render Refresh 0, render-execution 0, Provider calls 0, external AI calls 0, and temporary database writes after the smoke baseline 0. No new AI video was generated or downloaded from a Provider.
- Cleanup and protection: temporary SQLite, copied MP4, downloaded verification file, range bytes/headers, logs, scripts, build output, and services were removed; ports 8000/5173 were released. Repository `.env`, database, frozen verified MP4, Presentation data, ORM, tables, and migrations were unchanged.
- Known limitations: local filesystem only; single Scene 1 Artifact only; no authentication/authorization, object storage, transcoding, multi-scene composition, per-request full-file hash verification, or Provider-side uncertain-submit reconciliation.
- Git boundary: no stage, commit, push, or Tag; no real Qwen/Wanx call and AI cost 0.
- Single next pending roadmap node: V2-C3.2B Recovery and fallback.

## 2026-07-28 — V2-C3.2B Failure Recovery and Fallback

- Status: completed; checkpoint pending.
- Starting branch and HEAD: `competition-product-v2` at `3ac62c6e6aaba6d5cda107aca1be659edb606b5b`; staged was empty, the worktree was clean, and protected `master`/`competition-freeze-v1` remained at `98772160208840eff2f00b97b78ae34809b1786f`.
- Existing-capability audit: retained `VideoRenderRecoveryService`, latest/exact recovery routes, `VideoRenderOperationRead`, the existing Task/Artifact repositories and state machine, idempotent exact-project execution, explicit Refresh contract, stable Artifact resolver/player, double execution gates, and Presentation routing. No second Recovery API, Task/Artifact data layer, ORM field, table, or migration was added.
- Backend recovery decision: every operation response now carries a typed category, local Artifact state, read-only retry permission, same-original-`CREATED` continuation permission, explicit Refresh permission, resubmit prohibition, Presentation fallback availability, safe user guidance, and the literal `automatic_action_allowed=false`. Latest and exact Recovery GET compute Artifact availability through the existing controlled local-storage resolver and metadata/path/type/size rules.
- State matrix: `CREATED` may continue only the same idempotent task; `SUBMITTING`/`SUBMIT_UNKNOWN` prohibit submit and refresh; `SUBMITTED`/`PENDING`/`RUNNING` permit only user-explicit Refresh; `REFRESHING` prohibits a second Refresh; `FAILED`/`CANCELED` are terminal; `ARTIFACT_PERSIST_FAILED` explains that Provider output may exist but is not accessed or redownloaded; `SUCCEEDED` distinguishes a verified stable Artifact from missing/invalid local media.
- Read-only and privacy boundary: Recovery GET resolves no Provider dependency, performs no Submit/Refresh/output download/database write, leaves row counts and timestamps unchanged, and returns no Provider Task ID, Provider output URL, storage path, absolute path, signed URL, raw Provider response, Key, Token, Workspace ID, or Header.
- Workspace interaction: the UI consumes Backend action permissions, shows the authoritative recovery category and Artifact state, and separates “重新读取当前Task状态”, “继续原始任务提交”, “显式刷新Provider状态”, and “查看 Presentation Demo Snapshot”. It has no polling or automatic retry/submit/refresh Effect. The Presentation URL is always `/?mode=presentation` with no workspace identity parameters.
- Identity and race protection: Product, VideoProject, RenderTask, Artifact, request ID, AbortController, and synchronous action locks guard recovery, continuation, Refresh, Artifact metadata, and download. Uncertain action recovery reads the exact Task when its ID is known. Product/Artifact switches abort old requests and prevent old results or downloads from entering the new context.
- Frontend corrections found by browser verification: duplicate Presentation fallback links in the missing-Artifact state were reduced to one. Presentation Video Blueprint no longer calls the ordinary `video-projects/{id}/render-artifacts` API; it uses only the read-only Demo Snapshot path in Presentation mode.
- Backend focused verification: new recovery suite 27 passed; combined Recovery/Artifact/Render suite 68 passed, 1 Windows symlink-capability skip, and 1 known Starlette warning. Ruff passed.
- Full Backend verification: the first full run reached 181 passed and 2 skipped before 73 fixture setup errors caused solely by access denial to the environment's global pytest temp root. The clean rerun with an explicit repository-external basetemp passed: 253 passed, 3 real-provider skips, 0 failed, 1 known Starlette deprecation warning.
- Frontend verification: TypeScript passed. Vite production build passed with 126 modules transformed and output written outside the repository; temporary build output was removed after verification.
- Offline Fake browser smoke: isolated SQLite, repository-external Artifact storage, a read-only frozen-MP4 copy, and dependency-overridden Fake Wanx covered stable success, `CREATED`, `SUBMIT_UNKNOWN`, `FAILED`, `CANCELED`, `ARTIFACT_PERSIST_FAILED`, missing local media, and active `PENDING`. Backend disconnect displayed an exact read-only retry and Presentation entry; after restart the same Product/Project/Task context recovered. Rapid A/B switching ended on the exact second Task with no stale Artifact.
- Browser action counts: rapid double-click on `CREATED` produced exactly 1 execution POST and 1 Fake Submit, reused the same Task, and created no second Task. Rapid double-click on active Refresh produced exactly 1 Refresh POST and 1 Fake Provider fetch. Provider-output fetch/download was 0. Stable Content API reads used only the copied local Artifact. Task rows remained 8 and Artifact rows remained 2; post-baseline Task/Artifact row creation was 0.
- Presentation regression: fallback navigation occurred only after the explicit link click. `/products?mode=presentation` redirected to `/?mode=presentation`; SocialPilot AI, competition mode, Demo Snapshot, `0 AI Calls`, Overview, Copy Matrix, Video Blueprint, and Growth Copilot were available. Product Center and recovery UI were absent. The clean Presentation access log contained only Demo Snapshot GETs and no ordinary workspace, execution, Submit, Refresh, Qwen, or Wanx request. Console ended with 0 errors and 0 warnings.
- Provider/AI calls and cost: real Qwen 0, real Wanx 0, real Submit 0, real Refresh 0, Provider-output access/download 0, automatic retry 0, background polling 0, and AI cost 0. The only generation-related calls were the two explicitly tested offline Fake actions described above.
- Cleanup and protection: temporary Backend/Frontend services, SQLite, Artifact directory, frozen-MP4 copy, logs, test launcher, pytest basetemp, and external build output were removed; ports 8000/5173 were released. Repository `.env`, SQLite, frozen MP4, Presentation source data, ORM, tables, and migrations remained unchanged.
- Known limitations: no Provider-side `SUBMIT_UNKNOWN` reconciliation, automatic compensation, replacement-task history, background polling, multi-scene composition, object storage, transcoding, authentication/authorization, or tenant isolation. A terminal or persist-failed task cannot start a replacement attempt in this stage.
- Git boundary: no stage, commit, push, or Tag; the stage ends with source/docs changes only.
- Single recommended next stage: V2-C4.1A FeedbackContext. It was not started, and any future real Qwen or Wanx call still requires separate explicit authorization.

## 2026-07-28 — V2-C3.2B Recovery Decision Consistency Correction

- Root cause: the reused-task `render-execution` response inferred Artifact availability from a `SUCCEEDED` Task plus an Artifact database row, while latest/exact Recovery GET used the controlled local-file verifier. A missing file could therefore be reported as both available and missing.
- Unified decision: repeated `render-execution`, local recovery after a concurrent 409, normal operation responses, latest Recovery GET, and exact Task Recovery GET now use `VideoRenderRecoveryService.build_operation`. The shared Artifact check retains controlled-root, traversal/symlink, regular-file, supported type, persisted size, and SHA-256 format validation. It never accesses a Provider URL or redownloads output.
- Fail-closed actions: `CREATED` continues the original Submit only when no Provider Task ID exists. A contradictory `CREATED` identity is `submit_uncertain`. `SUBMITTED`/`PENDING`/`RUNNING` permit explicit Refresh only with a valid Provider Task ID; missing identity is `refresh_uncertain`. Public responses still omit Provider Task IDs.
- Three-interface evidence: a valid Artifact returned `succeeded / available` from repeated execution, latest Recovery, and exact Recovery. A missing file returned `succeeded_artifact_unavailable / missing` from all three. Invalid size, type, SHA metadata, and unsafe path cases produced the same safe unavailable classification across all three without leaking paths or integrity details.
- Backend verification: the focused consistency suite passed 37 tests; combined Recovery/Artifact/Render tests passed 78 tests with 1 safe Windows symlink-capability skip; full default pytest passed 263 tests with 3 real-provider skips and 1 known Starlette deprecation warning. Ruff passed.
- Frontend verification: TypeScript passed. Vite production build passed with 126 modules and repository-external output.
- Browser Smoke: isolated temporary SQLite, repository-external Artifact storage, a read-only frozen-MP4 copy, and dependency-overridden Fake Provider verified missing-Artifact recovery and normal `CREATED` continuation. Fee confirmation enabled the same-task continuation control, but Submit and Refresh were not clicked. Repeated execution/latest/exact responses were all `succeeded_artifact_unavailable / missing`; Provider submit/fetch/output-fetch remained 0 and Task/Artifact row counts stayed 2/1.
- Presentation regression: `/products?mode=presentation` redirected to `/?mode=presentation`; Demo Snapshot, `0 AI Calls`, all four navigation stages, and the Video Blueprint were visible. Product/recovery workspace content was absent; console ended with 0 errors and 0 warnings.
- Provider, writes, and cost: browser Provider Submit 0, Provider Fetch 0, Provider-output fetch 0, real Qwen/Wanx 0, post-baseline Task/Artifact writes 0, and AI cost 0.
- Git boundary: no stage, commit, push, or Tag. V2-C4.1A was not started. C3.2B remains checkpoint-pending until explicit checkpoint authorization.

## 2026-07-29 — V2-C4.1A Structured FeedbackContext

- Status: completed; checkpoint pending.
- Starting baseline: `competition-product-v2` at `2cee1958ba44d0de18bf0c0d65c56338fbb4f636`; clean worktree and stage; protected `master` and `competition-freeze-v1` both at `98772160208840eff2f00b97b78ae34809b1786f`.
- Existing capability audit: AdCampaign persists only `product_id`; it has no CopyMatrix, VideoProject, RenderTask, Artifact, or MarketingBrief attribution. The existing MetricsService correctly aggregates totals before calculating ratios. MarketingStrategy, CopyMatrix, and VideoProject can form an exact chain through VideoProject foreign keys. The old Growth Qwen route had no independent execution gate.
- Read-only API: added `GET /api/v1/products/{product_id}/feedback-context`. Missing Product is 404; a Product without Campaign rows returns a serializable HTTP 200 empty Context. GET performs no Provider resolution, generation, persistence, count change, or timestamp change.
- Deterministic contract: `version=v1`, `data_source=stored_campaigns`, Product identity, sorted Campaign IDs/platforms, count/date range, overall and per-platform metrics, exact content-chain IDs, readiness, missing requirements, Product-only attribution flags, `provider_calls=0`, and an SHA-256 lowercase digest. Digest input uses stable JSON ordering and includes Campaign ID/date/platform/numeric totals plus exact content-chain references; it excludes time, randomness, names, CSV text, and local paths.
- Metrics and chain: all CTR/CVR/CPA/ROAS values reuse MetricsService, including its six-decimal ratio rounding and null CPA/ROAS divide-by-zero semantics. The chain starts only from the latest Product VideoProject and verifies its exact Strategy and CopyMatrix Product IDs plus CopyMatrix/VideoProject Strategy identity. It never combines unrelated latest records.
- Attribution boundary: Campaign performance is attributable only to Product. The selected chain is a later-stage reference, not evidence that its CopyMatrix, VideoProject, RenderTask, Artifact, or MarketingBrief produced the Campaign results. VideoProject still has no MarketingBrief foreign key.
- Growth execution safety: added independent `ENABLE_GROWTH_EXECUTION=false`. The route gate executes before Qwen Provider resolution and the Service repeats the same gate. Default-off tests observed Provider resolutions 0 and database writes 0; explicit test Settings keep the legacy Fake Provider success path compatible.
- Workspace UI: Product changes read the matching Context with AbortController, request IDs, Product identity checks, and stale-response guards. It implements loading, empty, ready, incomplete, error, manual read-only retry, upload refresh, synchronous upload/read locks, metrics, exact chain IDs, digest summary, missing requirements, and attribution warning. AI optimization is a disabled control with no action handler.
- CSV boundary: import is explicit and writes Campaign rows but calls no AI. The UI states that repeated imports append records and are not deduplicated or replaced. A full Product Center reload retains Backend Context data and the same digest; the existing page-level Product selection must be reselected before the panel is displayed.
- Test note: the first focused run was 9 passed / 2 failed because two new assertions ignored existing six-decimal MetricsService rounding and SQLite timezone-marker loss. Assertions were corrected to the established contracts without weakening validation; the rerun passed 11 tests.
- Automated verification: focused FeedbackContext/Growth 11 passed; Campaign/Metrics/Dashboard/Demo combined regression 24 passed; full default pytest 273 passed, 3 real-provider tests skipped, 0 failed, and 1 known Starlette/TestClient deprecation warning. Ruff passed. TypeScript passed. Vite production build passed with 126 modules and repository-external output.
- Browser Smoke: temporary SQLite contained a ready Product with an exact chain, an incomplete Product with Campaign data, and an empty Product. One rapid double-click on CSV import produced exactly one upload POST and two Campaign rows. The resulting overall metrics were CTR 5.00%, CVR 20.00%, CPA $10.00, and ROAS 3.00x; platform order was Instagram then TikTok. Reload plus exact Product re-selection restored the same full digest `83aa4bd71f100180db185ec702fa23a017837ffe75fd5fb1a16cc0abb09a8288`. Rapid A/B switching ended on Product B with one Campaign and INCOMPLETE state, with no stale Product A Context.
- Failure and Presentation regression: stopping Backend produced a safe FeedbackContext error and preserved a read-only retry; restarting against the same temporary SQLite recovered Product B. `/products?mode=presentation` redirected to `/?mode=presentation`; Demo Snapshot, `0 AI Calls`, all four stages, and Presentation Growth Copilot remained available. The ordinary FeedbackContext region was absent, Presentation added no feedback/upload/growth request, and console ended with 0 errors and 0 warnings.
- Exact Browser side effects: one explicit upload POST; two temporary Campaign rows written for Product 1; growth-analysis POST 0; Provider resolutions 0; real Qwen 0; real Wanx 0; Submit 0; Refresh 0; Provider-output access 0; automatic retry/background jobs 0; AI cost 0.
- Scope boundary: no FeedbackContext ORM/table/migration, Recommendation generation/constraint, Performance-to-Prompt, V2 Copy, V2 VideoProject, parent-child version, budget action, ad-account integration, authentication, or tenant feature was added.
- Git boundary: staged empty; no commit, push, or Tag. V2-C4.1B was not started.
- Single recommended next stage: V2-C4.1B Recommendation constraints.

## 2026-07-29 — V2-C4.1A Product isolation and fail-closed correction

- Checkpoint review found that an invalid latest VideoProject chain was marked not ready but still exposed candidate VideoProject and CopyMatrix IDs. The existing cross-Product test incorrectly required that disclosure, and the workspace rendered the IDs even when `content_chain_ready=false`.
- The public contract now exposes Strategy, CopyMatrix, and VideoProject IDs only as one validated atomic chain. Missing records, cross-Product ownership, or CopyMatrix/VideoProject Strategy mismatch return all three IDs as `null`, set both chain and Context readiness false, and retain only safe structured missing requirements.
- Candidate references and validation facts remain private digest inputs so repeated invalid input is stable and candidate-reference or validity changes alter the digest. FeedbackContext remains read-only, Provider-free, and non-persistent.
- The workspace now renders chain IDs only when `content_chain_ready=true`; otherwise it shows `精确内容链未就绪` and the existing safe missing-requirement list.
- Automated correction gates: focused FeedbackContext/Growth Gate 15 passed; Campaign/Metrics/Dashboard/Demo combined regression 28 passed; full default pytest 277 passed, 3 real-provider tests skipped, 0 failed, and 1 known Starlette/TestClient deprecation warning. Ruff, TypeScript, and repository-external Vite production build passed.
- Isolated browser verification covered a valid chain, cross-Product CopyMatrix, same-Product Strategy reference mismatch, empty and missing-chain contexts, Backend error/recovery, and rapid Product switching. Invalid contexts showed no chain IDs even when the temporary database contained candidate references. Presentation Demo Snapshot and all four stages remained isolated; console finished with 0 errors and 0 warnings.
- Browser requests included 8 FeedbackContext GETs and 0 API POSTs. Browser database writes, growth-analysis requests, Provider resolutions, real Qwen/Wanx calls, Submit, Refresh, and AI cost were all 0. No real AI or Provider was called, and V2-C4.1B was not started.

## 2026-07-29 — V2-C4.1B Recommendation-to-Generation Constraints

- Status: completed; checkpoint pending. Starting branch `competition-product-v2`, HEAD `c34a5611bfae8e666dbb1a055aa0b7fcded3317e`; staged remained empty and no commit, push, or Tag was created.
- Audit result: Recommendation has no ORM or persistence layer. Campaign remains Product-only and cannot prove that any CopyMatrix, VideoProject, RenderTask, Artifact, or MarketingBrief caused a metric. C4.1A FeedbackContext and its atomic latest-VideoProject exact chain remain the sole content identity source; no second Metrics or latest-record selector was added.
- Backend contract: added read-only, Provider-free Growth Preflight; retained the sole `POST /products/{product_id}/growth-analysis`; preserved route Gate before Provider resolution and Service Gate. Execution rebuilds Context, requires an exact current digest and chain, validates stored Copy/Video platforms before Provider use, calls the injected text Provider at most once, strictly validates a bounded `extra="forbid"` Recommendation, and returns Backend-owned source/safety fields.
- Output boundary: observations, Copy constraints, Video constraint, and budget guidance are test hypotheses only. Platform scope is normalized and constrained to stored Campaign/Copy/Video references. Prompt uses Backend-calculated metrics and validated content while excluding Campaign names, CSV source text, IDs, digests, secrets, paths, Artifact internals, and execution permissions.
- Frontend contract: added idle/checking/ready/blocked/failed Preflight states and idle/submitting/succeeded/failed/uncertain execution states. The default-off Frontend Gate, Backend readiness, exact identity, explicit session fee confirmation, AbortController/request IDs, Product identity guard, and synchronous lock all participate in enablement. Product/Context/digest changes clear Preflight, confirmation, and result. C4.2A/C4.2B remain disabled placeholders without handlers.
- Automated verification: Recommendation/Feedback/Growth focused suite 44 passed; Campaign/Metrics/Dashboard/Demo regression 13 passed; full default pytest 306 passed, 3 real-provider tests skipped, 0 failed, and 1 known Starlette/TestClient deprecation warning. Ruff and TypeScript passed. Vite production build passed with 126 modules and repository-external output.
- Isolated browser verification used temporary SQLite and a dependency-overridden Fake Provider only. Default dual gates produced 0 Provider resolutions and 0 POSTs. Enabled coverage produced 5 deliberate Fake resolutions and 5 calls total: 3 valid, 1 strict-invalid, and 1 connection-uncertain. The rapid double-click generated exactly 1 POST/1 Fake call; invalid and uncertain cases performed no automatic retry. Recommendation executions created or updated 0 database rows and generated 0 CopyMatrix, VideoProject, RenderTask, or Artifact records.
- Browser regression also covered blocked Context, fee-confirmation disablement, one explicit temporary CSV import, digest change from `b96c23c340c0…` to `337824ef9341…` clearing the old result/confirmation/Preflight, rapid A/B Product switching, Backend disconnect/recovery, and disabled C4.2 placeholders. The explicit CSV import added one temporary Campaign row and triggered 0 AI calls.
- Presentation regression: `/products?mode=presentation` redirected to `/?mode=presentation`; Demo Snapshot, `0 AI Calls`, and Overview/Copy Matrix/Video Blueprint/Growth Copilot were present on all four stages. Product Center and ordinary Recommendation UI were absent. Console ended with 0 errors and 0 warnings.
- Safety and scope: no ORM, migration, real `.env`, repository database, frozen MP4, Presentation fixture, Provider debug endpoint, or production Fake Provider was changed. Real Qwen, Wanx, Submit, Refresh, external AI calls, and AI cost were all 0.
- Known limitation: Recommendation is session-only and is lost on reload. No causal creative attribution or Recommendation-to-child persistence/version relation exists. Any later generation must rebuild and revalidate Product, digest, and exact content-chain identity.
- Single recommended next stage: V2-C4.2A Automatic V2 Copy generation. It was not started, and it must not inherit execution authority from this Recommendation response.

## 2026-07-29 — V2-C4.1B Campaign platform and single-use cost-consent correction

- Root cause: execution normalized every Campaign platform after the Provider call, so an unsupported Product-only channel such as Google Ads could turn an otherwise valid Recommendation into a post-paid 502. On the workspace, a successful result retained the ready Preflight and checked fee confirmation, allowing another deliberate click without fresh authorization.
- Backend correction: Campaign platforms are now filtered into a stable unique TikTok/Instagram/Facebook observation allowlist before Provider use. Unsupported Campaign-only channels remain in Backend-calculated overall totals and the deterministic Context digest, but are excluded from controlled platform observations and Prompt platform metrics. Exact Copy and Video platform constraints retain their existing strict validation. Mixed TikTok/Google Ads input can produce only legal TikTok observations; Google Ads-only input can produce an overall-only Recommendation; Provider output that names Google Ads fails safely without a write or sensitive detail.
- Frontend correction: fee confirmation is single-use and is consumed synchronously before the POST. Upload, Context reread, Preflight, and execution controls are disabled while submitting. Success preserves the visible result but clears Preflight and confirmation; failed and uncertain attempts also require a new successful Preflight and a new confirmation. Product or digest changes continue to clear old identity, authorization, and result.
- Automated correction gates: focused constraint suite 32 passed; Recommendation/Feedback/Growth combined suite 47 passed; Campaign/Metrics/Dashboard/Demo regression 13 passed; full default pytest 309 passed, 3 real-provider tests skipped, 0 failed, and 1 known Starlette/TestClient deprecation warning. Ruff, TypeScript, and repository-external Vite production build passed with 126 modules.
- Isolated browser verification used temporary SQLite and a dependency-overridden Fake Provider. Five deliberate authorizations produced exactly five Provider resolutions/calls: 3 valid, 1 strict-invalid, and 1 connection-uncertain. The initial rapid double-click produced one call. A second valid call required an explicit new Preflight and new fee confirmation. Invalid and uncertain outcomes performed no automatic retry and left execution disabled until reauthorization.
- Digest and Product isolation: one explicit temporary CSV import changed Product A Context digest from `69b433e7b050…` to `b069ce3671c1…`; manual Context reread removed the old result, cleared Preflight, and disabled fee confirmation. Rapid A/B/C switching ended on Product C without stale result or authorization.
- Presentation regression: `/products?mode=presentation` redirected to `/?mode=presentation`; Demo Snapshot, `0 AI Calls`, and Overview/Copy Matrix/Video Blueprint/Growth Copilot were present on all four stages. Product Center and ordinary Recommendation UI were absent. Console ended with 0 errors and 0 warnings.
- Safety and scope: temporary executions wrote only disposable Campaign/test records in isolated SQLite. Recommendation persistence, CopyMatrix, VideoProject, RenderTask, and Artifact writes were 0. Real Qwen, Wanx, Submit, Refresh, external AI calls, and AI cost were all 0. No ORM, migration, production Fake/debug entry, execution-enabled `.env`, repository database, frozen MP4, or Presentation fixture was changed.
- Git boundary: HEAD remained `c34a5611bfae8e666dbb1a055aa0b7fcded3317e`; staged remained empty; no commit, push, or Tag was created. V2-C4.2A was not started.

## 2026-07-29 — V2-C4.2A Recommendation-Bound V2 Copy Generation

- Status: completed; checkpoint pending. Starting branch `competition-product-v2`, HEAD `e3c63439c04a83f4da592e8aeb04405db6c39d0e`; staged remained empty and no commit, push, or Tag was created.
- Backend contract: added Provider-free V2 Copy Preflight and a separately gated V2 Copy execution route. Backend owns the deterministic Recommendation digest, rebuilds the authoritative FeedbackContext, verifies the current Product, Context digest, exact Strategy/CopyMatrix/VideoProject identity, Recommendation contents, and ordered target platforms, then builds a structured Prompt from trusted Product, exact source content, Recommendation constraints, and Backend-calculated metrics.
- Output and persistence: strict Provider output rejects unknown fields, blank or oversized text, duplicate hashtags, unsupported, missing, duplicate, extra, or reordered platforms. Valid output creates exactly one CopyMatrix through the existing repository and preserves the source CopyMatrix. The response labels the candidate source identities and honestly states that Recommendation, Context, and source-Copy parentage are not persisted.
- Dual-gate and authorization boundary: the existing Copy gate and the new V2 Copy gate both default false in Backend and Frontend. Route gating occurs before Provider dependency resolution and Service gating repeats before data reads. V2 authorization is separate from Recommendation authorization, single-use, session-only, and synchronously consumed. Product, Context digest, Recommendation, failure, or uncertain response clears or blocks reuse; no automatic retry, Effect-triggered execution, or latest-Copy recovery claim exists.
- Automated verification: V2 targeted suite 33 passed; V2 plus Copy API/service/preflight/task-bound regression 67 passed; Recommendation/Feedback/Growth regression 47 passed; Product/Strategy/Video regression 95 passed; Campaign/Metrics/Dashboard/Demo regression 13 passed; full default pytest 342 passed, 3 real-provider tests skipped, 0 failed, and 1 known Starlette/TestClient deprecation warning. Ruff and TypeScript passed. Vite production build passed with 126 modules and repository-external output.
- Isolated browser verification used temporary SQLite and dependency-overridden Fake Providers only. Across deliberate default-off, valid, strict-invalid, safe-failure, and response-loss scenarios there were 8 Recommendation POSTs, 8 V2 Preflight POSTs, 5 V2 execution POSTs, 8 Fake Recommendation calls, and 5 Fake V2 Copy calls, with zero automatic retries. Only the valid V2 authorization created one additional CopyMatrix; invalid, failed, and uncertain attempts wrote none. Rapid double-click produced one V2 call. A new Recommendation reset the V2 Preflight and fee authorization.
- Identity and recovery checks: Product A/B/C rapid switching ended on the final Product without stale result. A deliberate Campaign import changed Product A's Context digest from `b96c23c340c0…` to `2a03b530c970…`, and the reread cleared the old Recommendation, V2 Preflight, fee confirmation, and result. Backend disconnect produced a safe Context error; restart recovered the current Product. A response-loss uncertainty prohibited resubmission of the current Recommendation.
- Presentation regression: `/products?mode=presentation` redirected to `/?mode=presentation`; Demo Snapshot, `0 AI Calls`, and Overview/Copy Matrix/Video Blueprint/Growth Copilot were present across all four stages. Product Center and V2 Copy controls were absent. Console ended with 0 errors and 0 warnings.
- Safety and scope: no ORM, migration, real `.env`, repository database, frozen MP4, Presentation fixture, production Fake/debug endpoint, Strategy, VideoProject, RenderTask, Artifact, budget action, or C4.2B/C4.3A implementation was added. Real Qwen, Wanx, Submit, Refresh, external AI calls, and AI cost were all 0.
- Known limitation: Recommendation and candidate-parent relations remain non-persistent. Reload can recover neither Recommendation ownership nor a parent-child version graph, and an uncertain execution cannot use a latest CopyMatrix lookup as proof of outcome.
- Git boundary: no stage, commit, push, or Tag. The single recommended next stage is V2-C4.2B Recommendation-Bound V2 VideoProject; it was not started.

## 2026-07-30 — V2-C4.2A Product Input Fail-Closed Correction

- Root cause: `_product_ready()` called `.strip()` directly on nullable `Product.category` and assumed every selling-point item was a string. Legacy or directly persisted incomplete Product values could therefore raise an internal `AttributeError` or `TypeError` instead of producing the contracted blocked Preflight.
- Correction: Product readiness now uses one type-safe trimmed-text predicate for name, category, description, and every selling-point item. Selling points must be a non-empty list whose complete contents are non-empty strings. `None`, empty, whitespace-only, or non-string values fail closed without changing ORM, schema, migration, or frontend behavior.
- API evidence: an exact otherwise-ready Product with `category=None` and all tested blank/invalid variants returned HTTP 200 Preflight with `input_ready=false`, `ready_for_execution=false`, and `product_input`. Preflight resolved no Provider and changed no model counts. V2 execution against the incomplete Product returned safe HTTP 409 before Provider generation and preserved CopyMatrix, Strategy, VideoProject, RenderTask, and Artifact counts.
- Success regression: a complete Product retained the prior behavior—one deliberate Fake V2 call created exactly one additional CopyMatrix, left the source CopyMatrix unchanged, and created no other model.
- Automated verification used fresh writable `D:\提示词` basetemp paths rather than `D:\codx\_temp`: V2 targeted 58 passed; V2 and existing Copy contracts 92 passed; Recommendation/Feedback/Growth 47 passed; Product/Strategy/Video 74 passed; Campaign/Metrics/Dashboard/Demo 13 passed; full default pytest 367 passed, 3 real-provider tests skipped, 0 failed, and 1 known Starlette/TestClient deprecation warning. Ruff and `npx tsc --noEmit` passed. Repository-external Vite production build passed with 126 modules.
- Browser Smoke: isolated temporary SQLite and a dependency-overridden Fake Provider verified the incomplete Product UI as `BLOCKED` with `商品生成资料不完整`, disabled fee/execution controls, and no V2 Provider call. A valid Product completed one Recommendation and one V2 Copy Candidate and displayed its saved CopyMatrix. Presentation redirected correctly, retained Demo Snapshot/`0 AI Calls` and all four stages, hid the ordinary workspace, and ended with 0 console errors and 0 warnings.
- Provider and persistence boundary: incomplete-Product Provider generation 0 and database writes 0; real Qwen/Wanx/external Provider calls 0; Submit/Refresh 0; AI cost 0. No C4.2B work was started.
- Environment cleanup exception: `D:\codx\_temp\socialpilot-c42a-chain2` and `D:\codx\_temp\socialpilot-c42a-full` are pre-existing repository-external ordinary pytest directories, not links, Junctions, or Reparse Points. Exact-path deletion was denied by Windows ACL. The parent directory was not modified, the paths were not reused, and cleanup is deferred to a local administrator. All new correction basetemps, browser SQLite/logs/helper, and build output are separately cleaned after verification.
- Git boundary: the worktree remains the original 19-file C4.2A allowlist; staged remains empty; no commit, push, or Tag. C4.2A remains checkpoint-pending.

## 2026-07-30 — V2-C4.2B Recommendation-Bound V2 VideoProject

- Status: development and verification completed; independent audit and checkpoint authorization pending. Starting branch `competition-product-v2`, HEAD `da033167f91068b4c3d8c94cb8575bf3b3dbd01a`; protected `master` and `competition-freeze-v1` both remained `98772160208840eff2f00b97b78ae34809b1786f`.
- Scope: the authorized 14-file draft was preserved and completed; only `docs/development-roadmap.md` and `docs/progress-log.md` were added to the final 16-file allowlist. No ORM, migration, Recommendation/FeedbackContext persistence layer, second CopyMatrix/VideoProject model, Metrics layer, or C4.3A version graph was introduced.
- Backend contract: added Provider-free, read-only V2 VideoProject Preflight plus a separately gated execution route. Preflight and execution rebuild current FeedbackContext, recompute Recommendation identity, revalidate the atomic source Strategy/CopyMatrix/VideoProject chain, load the candidate CopyMatrix by exact ID, reject cross-Product/wrong-Strategy/source-equal candidates, require one strict target-platform candidate copy, and bind normalized full candidate content and association identity into a deterministic Preflight digest.
- Provider and persistence: Qwen may return only bounded `title`, `concept`, `scenes`, and `cta`. Unknown fields, blank/oversized text, invalid or duplicate sequence, gaps, non-positive durations, or a duration sum different from the source VideoProject fail before persistence. Backend fixes platform, duration, aspect ratio, Product, source Strategy, candidate CopyMatrix, and `planned` status. Success writes exactly one VideoProject; RenderTask, Artifact, Wanx, Submit, Refresh, polling, and automatic render remain absent.
- Frontend contract: the ordinary Growth workspace exposes C4.2B only after a valid C4.2A candidate exists. It implements idle/checking/ready/blocked/failed Preflight states; idle/submitting/succeeded/failed/uncertain execution states; independent default-off gate and fee confirmation; synchronous authorization consumption; AbortController, request IDs, Product/Recommendation/candidate/Preflight identity guards; and no retry or latest-VideoProject recovery. Success remains in the workspace and does not enter the Render flow.
- Automated verification: C4.2B focused 26 passed; Recommendation/V2 Copy/FeedbackContext regression 105 passed; Video/Render/Artifact regression 119 passed with 1 safe skip; Product/Strategy/Copy regression 113 passed; Campaign/Metrics/Dashboard/Demo regression 13 passed; full default pytest 393 passed, 3 real-provider tests skipped, 0 failed, and 1 known Starlette/TestClient deprecation warning. Ruff and `npx tsc --noEmit` passed. Repository-external Vite production build passed with 126 modules.
- Browser Smoke used temporary SQLite and dependency-overridden Fake Qwen only. Three deliberate Recommendation calls, three V2 Copy calls, and four V2 VideoProject calls covered valid success, strict-invalid output, safe connection failure, and deliberate response loss. The rapid double-click produced one V2 VideoProject POST/call. Only the valid V2 VideoProject authorization added one VideoProject; invalid, failed, and uncertain attempts added none. Three deliberate V2 Copy authorizations added three candidate CopyMatrix rows. RenderTask and Artifact stayed 0; Wanx, Submit, Refresh, automatic retry, real Provider calls, and AI cost were 0.
- Browser identity/recovery evidence: a lost response entered `uncertain` and displayed no latest-project recovery; Backend restart recovered the workspace; rapid Product B→A switching ended only on A; a temporary Campaign metric change changed Context digest and cleared Recommendation, candidate CopyMatrix UI, C4.2B Preflight, fee confirmation, and result. The UI displayed the exact candidate CopyMatrix, platform, 10-second duration, 9:16 ratio, scenes, `Wanx Calls = 0`, `RenderTask = 0`, `Artifact = 0`, and `尚未渲染`.
- Presentation regression: `/products?mode=presentation` redirected to `/?mode=presentation`. Overview, Copy Matrix, Video Blueprint, and Growth Copilot each loaded the protected Demo Snapshot and `0 AI Calls`. Access logs recorded four `GET /api/v1/demo/snapshot` requests and zero V2 VideoProject requests; Product Center and the ordinary C4.2B workspace were absent. Final Presentation console capture was 0 errors and 0 warnings.
- Honest validation notes: an initial grouped pytest command used a nonexistent test filename and collected no tests; corrected explicit test groups passed. The first Ruff and Vite attempts were denied when their tools tried to write cache/config temporaries inside the read-protected repository; repository-external cache/output plus the approved Vite temporary write succeeded. One temporary Presentation access-log start initially collided with an existing local port and was rerun after the port was released. A deliberate Backend drop produced the expected browser connection interruption and `uncertain` state.
- Authenticity boundary: Recommendation is a deterministic integrity object, not a signature, authorization proof, or Provider provenance record. Recommendation, FeedbackContext, candidate-Copy parentage, and VideoProject parentage are not persisted. The new VideoProject's Product/Strategy/candidate-Copy foreign keys are durable; no causal performance attribution is claimed.
- Safety boundary: real Qwen, Wanx, external Provider, Submit, Refresh, automatic retry, polling, and AI cost were all 0. `.env`, repository SQLite, frozen MP4, Presentation code/data, protected refs, and history were not modified. No stage, commit, push, Tag, amend, rebase, or squash was performed.
- Known limitation: page reload cannot reconstruct Recommendation ownership or either parent-child version relation. A response-loss uncertainty cannot be reconciled from latest VideoProject. C4.3A remains unstarted.
- Next: independent audit. Create the V2-C4.2B checkpoint only after explicit user approval.

## 2026-07-30 — V2-C4.2B Source VideoProject Fail-Closed and Association Truth Correction

- Status: targeted correction completed; independent re-audit required and checkpoint remains explicitly unauthorized. Branch and protected HEAD remain `competition-product-v2` at `da033167f91068b4c3d8c94cb8575bf3b3dbd01a`; staged remains empty.
- Source fail-closed contract: Preflight now validates the complete source VideoProject through the existing `VideoPlanSchema` using title, concept, platform, duration, aspect ratio, scenes, and CTA, then separately enforces scene sequences exactly `1..N`. Invalid legacy or direct-write values produce HTTP 200 with `input_ready=false`, `ready_for_execution=false`, and safe `source_video_project_schema`; published platform/aspect values are empty and duration is 0 instead of echoing invalid input or leaking internal validation details.
- Execution-time protection: the same source validation is rerun while rebuilding the authoritative Preflight. A post-Preflight source-duration mutation changes the digest/readiness and execution returns safe HTTP 409 before Provider generation. Invalid-source Provider resolution/generation and all model writes remain 0.
- Association truth: the success schema and UI now expose `candidate_copy_matrix_association_persisted=true`, matching the new VideoProject's real `copy_matrix_id`. They separately expose `candidate_copy_source_parent_relation_persisted=false`, `source_video_parent_relation_persisted=false`, and `recommendation_persisted=false`; the prior ambiguous Copy-parent and Video-parent field names were removed from the C4.2B response contract.
- Regression coverage: 13 invalid-source variants cover duration 0 and over 180, empty/blank platform and aspect ratio, empty scenes, malformed scene structure, invalid sequence, duration-total mismatch, and blank title/concept/CTA. The focused suite passed 40 tests; Recommendation/V2 Copy/FeedbackContext passed 105; Video/Render/Artifact passed 119 with 1 safe skip; Product/Strategy/Copy passed 113; Campaign/Metrics/Dashboard/Demo passed 13; full default pytest passed 407 with 3 real-provider skips and 1 known Starlette/TestClient warning. Ruff, `npx tsc --noEmit`, and repository-external Vite production build passed with 126 modules.
- Browser Smoke: an invalid source displayed `BLOCKED` and `源VideoProject生产Schema无效`; its fee confirmation and execution button remained disabled; C4.2B execution POST, Fake Qwen video call, and database writes were 0. A valid source completed one C4.2B execution, added exactly one VideoProject linked to the exact candidate CopyMatrix, displayed the four truthful persistence relations, and left RenderTask/Artifact/Wanx at 0. The browser console ended with 0 errors and 0 warnings.
- Presentation regression: `/products?mode=presentation` redirected to `/?mode=presentation`; Overview, Copy Matrix, Video Blueprint, and Growth Copilot each retained the protected presentation shell and excluded the ordinary C4.2B workspace. Presentation console ended with 0 errors and 0 warnings.
- Safety and scope: no ORM, migration, database structure, C4.3A relation, `.env`, repository database, frozen MP4, Presentation code/data, protected ref, or history was changed. Real Qwen, Wanx, external Provider, Submit, Refresh, automatic retry, and AI cost remained 0. Worktree scope remains the original 16 C4.2B files; no stage, commit, push, Tag, amend, rebase, or checkpoint was created.
- Next: stop and wait for independent re-audit. A C4.2B checkpoint requires a later explicit authorization.

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
