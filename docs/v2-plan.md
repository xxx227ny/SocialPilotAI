# Competition Product V2 Plan

## Purpose

Competition Product V2 upgrades the stable demo into an operable product path while preserving Presentation Mode as a deterministic fallback. Users should eventually enter a real product, select markets/platforms, start generation, observe task state, save results, import performance data, receive recommendations, generate second-version content, and compare V1 with V2.

V2 is not the final commercial product. Work proceeds through one reviewed stage at a time.

## Goals

1. Operable product creation, editing, list, and detail flows.
2. Explicit target-market and platform selection.
3. User-triggered Strategy and Copy Matrix generation with durable results and honest states.
4. Operable VideoProject-to-RenderTask flow with status, recovery, and stable assets.
5. Deterministic performance metrics plus structured optimization feedback.
6. Performance-to-Prompt generation of V2 Copy and VideoProject.
7. Parent-child creative versions, iteration metadata, history, and comparison.
8. Error, empty, loading, timeout, retry, and fallback states for critical paths.
9. Presentation Mode regression safety with no required live AI calls.

## Non-goals

- Authentication, billing, subscriptions, or multi-tenancy.
- Social publishing, ad-account OAuth, automatic ad execution, or automatic budget changes.
- Unlimited generation remains out of scope. Stage 3C permits bounded,
  Provider-free batch orchestration only; it does not generate media.
- A general media suite remains out of scope. Existing approved subtitle and
  audio-composition stages do not imply downstream batch production is complete.

## Stage 3C boundary

Stage 3C adds bounded BatchVideoJob orchestration and stable per-variant identities.
It performs no AI, TTS, FFmpeg, rendering, review, publishing, or external writes.
Scripts, visual assets, voice, final rendering, human review, bundles, and batch
delivery remain incomplete downstream stages with separate Provider and cost approval.
- Complex cloud storage before cost, privacy, retention, and download authorization review.
- Replacing the modular monolith with microservices.
- Modifying the freeze tag/history, public release copy, or private submission materials.

## Mandatory stage order

Only the next accepted substage may begin.

1. **✅ V2-C0 — Safe branch, project map, and development tree**
2. **V2-C1 — Operable workspace**
   - V2-C1.1A Product creation form and validation
   - V2-C1.1B Product list and detail
   - V2-C1.2A Target market and platform selection
   - V2-C1.2B Task start entry
3. **V2-C2 — Operable Qwen content chain**
   - V2-C2.1A Strategy operation entry
   - V2-C2.1B Generation state, failure feedback, and result display
   - V2-C2.2A Copy Matrix operation entry
   - V2-C2.2B Multi-platform result persistence and history
4. **V2-C3 — Wanx task hardening**
   - V2-C3.1A VideoProject-to-RenderTask operation entry
   - V2-C3.1B Task status and polling UI
   - V2-C3.2A Stable video asset display and download
   - V2-C3.2B Failure recovery and fallback
5. **V2-C4 — Performance-to-Prompt**
   - V2-C4.1A Structured `FeedbackContext`
   - V2-C4.1B Recommendation-to-generation constraints
   - V2-C4.2A Automatic V2 Copy generation
   - V2-C4.2B Automatic V2 VideoProject generation
   - V2-C4.3A V1/V2 parent-child relationship
   - V2-C4.3B Version comparison page
6. **V2-C5 — Project and history management**
   - V2-C5.1A Generation-task history
   - V2-C5.1B Result replay
   - V2-C5.2A Error and retry records
7. **V2-C6 — Deployment and competition stability**
   - V2-C6.1A Environment configuration and deployment checks
   - V2-C6.1B Security and rate limits
   - V2-C6.2A Minimal approved real-model smoke
   - V2-C6.2B Presentation Mode regression

## Acceptance gates

Every stage must pass all applicable gates:

1. **Pre-check:** expected branch/HEAD, understood tree, unchanged freeze tag, explicit file allowlist.
2. **Behavior:** acceptance cases plus invalid, empty, loading, provider-failure, timeout, and retry behavior.
3. **Backend:** relevant tests and default unit/mock suite; real smoke excluded unless separately approved.
4. **Static quality:** Ruff passes without convenience exclusions.
5. **Frontend:** TypeScript and Vite production build pass; UI tests when a suitable harness exists.
6. **Data:** compatibility, idempotency, and rollback notes; no destructive migration without approval.
7. **Security/privacy:** no secrets, authorization data, signed URLs, private workspace IDs, or unnecessary user material in source, logs, fixtures, or docs.
8. **Evidence:** exact pass/fail/skip/warning counts, `git diff --stat`, `git diff --check`, and limitations.
9. **Scope:** no next-stage feature and no unrelated cleanup.
10. **Approval:** stop after reporting; commit/push require explicit authorization.

### V2-C0 acceptance

- Status: ✅ Completed on 2026-07-21.
- Start: `competition-freeze-v1` at `98772160208840eff2f00b97b78ae34809b1786f`.
- V2-C0 checkpoint: see this Git commit.
- Gate result: Backend 84 passed, 2 deselected, 0 failed; Ruff passed; TypeScript passed; Vite production build passed.
- Next stage: V2-C1.1A Product creation form and validation.
- Branch starts from `competition-freeze-v1` without moving `master` or the tag.
- Starting gates run without real AI.
- Only the three V2 baseline documents are added.
- Historical nodes distinguish evidence from missing checkpoints.
- Mermaid, links, UTF-8, sensitive-information scan, and `git diff --check` pass.

### V2-C1.1A acceptance preview

This is the only recommended stage after V2-C0 approval. It is limited to the real product-creation form and validation, reuses existing contracts where possible, covers invalid/empty/loading/error behavior, and does not start generation or later workspace features.

## AI cost discipline

Default-allowed work is limited to unit tests, mock providers, fixtures, local databases, and the existing verified local video asset.

Before any real Qwen/Wanx action, report and obtain approval for:

- Purpose and why mocks are insufficient.
- Exact model/provider and environment.
- Maximum request count and polling behavior.
- Estimated cost or stated inability to determine it.
- Timeout, retry, and failure policy.
- Any non-reversible charge or external artifact.

Without approval, do not run real smoke, submit paid tasks, poll provider APIs, add charge-producing automatic retries, or expose credentials.

## Rollback strategy

- Immutable anchor: `competition-freeze-v1` at `98772160208840eff2f00b97b78ae34809b1786f`.
- Never move/delete the tag, rewrite `master`, force-push, or use destructive reset for recovery.
- Keep each accepted stage small and reviewable on `competition-product-v2`.
- Before commit, reverse only the explicit stage allowlist after review; preserve user/unrelated changes.
- After an authorized commit, use a corrective commit rather than history rewriting.
- Database changes require compatibility and data-preservation plans.
- External tasks/charges may be irreversible; prevention, idempotency, and approval are the rollback strategy.

## Freeze protection

- Do not modify the freeze tag or target.
- Do not develop V2 in the public-release copy or include private submission materials.
- Do not modify unrelated projects or automatically push.
- Do not commit `.env`, credentials, databases, logs, raw provider responses, signed URLs, or private artifacts.
- Keep Presentation Mode as a stable fallback independent of live Qwen/Wanx.

## Stage reporting

Use [Progress Log](progress-log.md) for exact execution evidence and update [Development Roadmap](development-roadmap.md) only after verified work. The next-stage recommendation must name exactly one substage.
### Stage 3D：Provider-free版本化脚本与分镜

Stage 3D为`BatchVideoVariant`增加不可变、可编辑和可激活的脚本/分镜版本历史。它只覆盖人工创建与精确`VideoProject`导入，所有版本均为`UNREVIEWED`，不表示内容已审核或可发布。Qwen脚本生成、视觉素材、TTS、渲染、批量审核和平台交付仍是后续能力；本阶段不会调用Provider或生成媒体。
