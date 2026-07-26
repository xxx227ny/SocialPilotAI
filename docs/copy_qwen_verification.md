# Controlled Real Copy Qwen Verification Evidence

## V2-C2.2C verification record

- Verification date: 2026-07-27
- Contract commit: `88429d781b37c3bfa28a213c4969fc82dcfab6e6`
- Execution endpoint: `POST /api/v1/marketing-tasks/{task_id}/strategies/{strategy_id}/copy`
- Provider: Alibaba Cloud Bailian / DashScope Qwen
- Model: `qwen-plus`

## Controlled execution result

| Check | Result |
|---|---|
| User-authorized maximum | 1 real Qwen call |
| Real Qwen Provider calls | 1 |
| Task-bound Copy POSTs | 1 |
| SDK automatic retries | 0 |
| Outer retries | 0 |
| HTTP result | 200 |
| Verification result | Success |
| Legacy Product-only Copy POSTs | 0 |
| Strategy generation calls | 0 |
| Wanx calls | 0 |
| Video generation calls | 0 |

## Prompt input evidence

Only boolean checks were retained. The complete Prompt, raw request, and raw
Provider response were not recorded.

- Product fields: passed
- MarketingBrief fields: passed
- MarketingStrategy fields: passed
- Exact US target-market snapshot: passed
- Exact TikTok platform snapshot: passed

## Response contract and Copy quality

- `source_task_id`: correct
- `source_strategy_id`: correct
- `source_product_id`: correct
- `source_kind=marketing_brief_and_strategy`
- `requested_platforms`: TikTok only
- `strategy_association_persisted=true`
- `brief_association_persisted=false`
- `association_notice`: present and accurate
- Output platforms: exactly TikTok
- Instagram, Facebook, or additional platforms: none
- Text fields: non-empty and trimmed
- Hashtags: non-empty, with no whitespace-only items
- CopyMatrix association: exact Product and exact MarketingStrategy

## Temporary database evidence

| Record type | Before | After |
|---|---:|---:|
| Product | 1 | 1 |
| MarketingBrief | 1 | 1 |
| MarketingStrategy | 1 | 1 |
| CopyMatrix | 0 | 1 |
| VideoProject | 0 | 0 |
| VideoRenderTask | 0 | 0 |
| VideoRenderArtifact | 0 | 0 |

The MarketingStrategy was deterministic local preparation data created only in
the isolated temporary database. Qwen was not called to create it, and this
verification assessed the Copy execution contract rather than Strategy
generation quality.

## Persistence and recovery boundary

- CopyMatrix persists `product_id`.
- CopyMatrix persists `marketing_strategy_id`.
- CopyMatrix has no MarketingBrief foreign key.
- The execution response therefore reports
  `brief_association_persisted=false`.
- Reload can prove that a CopyMatrix belongs to the specified Strategy.
- Reload cannot prove a persisted association with the specified
  MarketingBrief.

## Security, cleanup, cost, and authorization

- No API key or Authorization Header value was recorded.
- The complete Prompt was not recorded.
- The raw Provider response was not recorded.
- The temporary SQLite database and temporary directory were deleted.
- Ports 8000 and 5173 had no residual listener.
- The repository `.env` and database were not modified.
- The Git working tree remained clean after execution.
- The call may have consumed Alibaba Cloud Bailian Credits.
- Exact Token usage, Credits, and monetary cost were not queried or invented.
- The one-call authorization is exhausted.
- No further real AI call is currently authorized.
- Any later Qwen or Wanx call requires new explicit user authorization.

Related records: [Development Roadmap](development-roadmap.md) and
[Progress Log](progress-log.md).
