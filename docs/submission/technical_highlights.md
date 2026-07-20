# SocialPilot AI 技术亮点

## 1. Qwen Provider

`QwenProvider` 实现内部 `TextGenerationProvider.generate(prompt) -> str` 契约，业务服务不直接依赖供应商 SDK。Marketing Strategy、Copy Matrix、Video Blueprint 和 Growth Recommendation 都先接收模型文本，再经过 JSON 解析与 Pydantic Schema 校验，只有结构合法时才进入业务结果或持久化流程。

真实 Qwen smoke 使用独立 `qwen_smoke` marker 和 `--run-qwen-smoke` 开关。普通 pytest 默认跳过外部调用，认证、连接、超时和模型错误会转换为不包含 Key 或完整供应商响应的安全错误。

## 2. Wanx Provider

`WanxProvider` 实现 `VisualGenerationProvider` 的异步 `submit()` 与 `fetch()` 契约。submit使用Wanx异步任务接口，fetch只查询既有provider task，不重新提交任务。Provider负责模型参数和供应商状态归一化，执行服务负责本地业务状态。

真实Wanx smoke具备单次submit保护、15秒轮询、5分钟上限、不自动重试和不下载视频等费用控制。普通pytest必须显式传入 `--run-wanx-smoke` 才会放行真实测试。

## 3. Provider Abstraction

系统将文本生成与视觉生成分为两套稳定契约：

```text
TextGenerationProvider → QwenProvider
VisualGenerationProvider → WanxProvider
```

API和业务服务面向内部接口工作，Provider适配端点、Header、请求体和供应商响应。这样可以独立测试业务编排、错误处理和数据校验，也避免将凭据、供应商task字段或HTTP细节扩散到前端。

## 4. Video Render Execution Pipeline

```text
VideoProject
  ↓
VideoRenderTask (CREATED)
  ↓
VideoRenderExecutionService.submit()
  ↓
Wanx provider task
  ↓
VideoRenderExecutionService.refresh()
  ↓
SUCCEEDED / FAILED / CANCELED
```

任务使用确定性 `idempotency_key`。提交前通过数据库条件更新原子认领 `CREATED` 任务，避免同一任务被重复submit。refresh要求已有provider task id，只调用fetch并同步状态，不包含自动重试或隐式重新生成。

## 5. Artifact Management

当供应商任务成功且返回视频地址时，执行服务创建或更新 `VideoRenderArtifact`。Artifact与`VideoRenderTask`一对一关联，保存provider output URL、可选storage path、metadata和可选expires_at。

`GET /api/v1/video-projects/{video_project_id}/render-artifacts`只返回已有成功Artifact，不调用Provider。Frontend在存在可播放URL时显示Verified Wanx Output；无Artifact或API失败时保留原有Video Blueprint，不使页面崩溃。

当前Artifact仍可能引用供应商临时签名URL，尚未实现长期对象存储。比赛真实视频已另存为本地MP4资产，但当前Frontend没有自动改用该本地文件。

## 6. Growth Copilot

广告CSV先经过完整校验和原子导入。`MetricsService`以聚合总量计算CTR、CVR、CPA和ROAS，避免把各行比例简单平均。Growth AI只接收已计算指标和已保存的Marketing Strategy，负责解释问题并生成预算、渠道和素材建议，不重新计算指标。

当前能力属于Performance-driven Optimization：完成数据分析与优化建议展示，但未实现Performance-to-Prompt、自动生成第二版Copy或VideoProject，也不自动调整广告预算。

## 7. Demo Safety

- Presentation Mode读取`preset_fixture`，标记`0 AI Calls`。
- Artifact展示为只读，不触发submit或refresh。
- Live Render Facade默认关闭，固定Scene 1、720P和服务端幂等键。
- 已有成功Artifact或已有任务时，Live Facade返回现有结果，不创建第二个任务。
- API Key只存在后端环境配置，不进入Frontend或仓库文档。
