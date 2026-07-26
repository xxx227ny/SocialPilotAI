# Qwen Verification Result

## Verification Context

- Baseline commit: `61dd14ed75a36d7bb0ed8eb8996d9fcf847e7bbe`
- Started: `2026-07-17T17:17:38.6286055+08:00`
- Finished: `2026-07-17T17:17:55.3031516+08:00`
- Verification scope: existing Qwen Provider smoke test only

## Provider

- Provider: `QwenProvider`
- Contract: `TextGenerationProvider.generate(prompt: str) -> str`
- Model: `qwen-plus`
- Endpoint: `https://dashscope.aliyuncs.com/compatible-mode/v1`
- API style: OpenAI-compatible Chat Completions
- Credentials source: backend environment / local `.env`

## Execution

```powershell
cd D:\SocialPilotAI\backend
.\.venv\Scripts\pytest.exe --run-qwen-smoke tests\smoke\test_qwen_real.py -v
```

Result: `SUCCESS`

- Tests: `1 passed`
- Provider returned non-empty structured text.
- The response was successfully parsed and validated by `MarketingStrategySchema`.
- No full model response or credential value was saved.
- No retry, batch generation, database write, or downstream business workflow was executed.

## Conclusion

The existing Qwen Provider successfully completed one real DashScope request and returned the structured result required by the current smoke test.

## V2 Controlled MarketingBrief-aware Verification — 2026-07-26

### Verification contract

- Date: `2026-07-26`
- Branch: `competition-product-v2`
- Contract commit: `dc0b04eb45dc02f6350eee45d983becd37ff90b2`
- Provider: Alibaba Cloud Bailian / DashScope Qwen
- Model: `qwen-plus`
- Endpoint host: `dashscope.aliyuncs.com`
- API: `POST /api/v1/marketing-tasks/{task_id}/strategy`
- Database: isolated temporary SQLite
- Authorized maximum Provider calls: 1
- Actual Provider calls: 1
- Automatic retries: 0
- HTTP result: 200
- Result: success
- Strategy schema validation: passed
- Strategy records created: 1
- CopyMatrix records: 0
- VideoProject records: 0
- VideoRenderTask records: 0
- VideoRenderArtifact records: 0
- Secret leakage: none
- Temporary environment cleanup: passed
- Repository database modified: no
- Working tree modified by execution: no

### Prompt input evidence

Boolean checks confirmed that the real Prompt contained all contracted inputs. The
Product fields were `name`, `category`, `description`, and `selling_points`. The
MarketingBrief fields were the exact Brief ID, `product_id`, target-market
snapshot, `platforms`, `audience`, `language`, `tone`, and `objective`.

The Prompt text, Provider request and response, authentication headers,
credentials, workspace identifiers, and local environment contents were not
recorded.

### Response and quality summary

- `source_task_id` matched the requested Brief.
- `source_product_id` matched the Brief's Product.
- `source_kind` was `marketing_brief`.
- `association_persisted` was `false`.
- `association_notice` was present.
- Positioning was non-empty.
- `audience_insights` contained 4 items.
- `angles` contained 3 items.
- `risks` contained 3 items.
- `evidence` contained 5 items.
- Trimming validation passed for all Strategy fields.
- The validated output contained US, TikTok, and portable-blender business context.

### Capability and cost boundary

- MarketingStrategy still persists only `product_id`.
- The MarketingBrief association exists only in the execution response.
- A page reload can recover only the Product's latest Strategy and cannot prove
  that the recovered record belongs to a specific MarketingBrief.
- Exact token usage, Credits, and monetary cost were not recorded.
- This call may have consumed Alibaba Cloud Bailian Credits.
- The single-call authorization is exhausted.
- Any later real Provider call requires new explicit user authorization.
