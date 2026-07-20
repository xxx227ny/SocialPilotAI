# SocialPilot AI Current Status

## Stable Baseline

Current Status: `Competition Demo Ready`

Baseline: `9e2312400c215f2cc130ad8c3a536dfe49bc2e42`

Date: 2026-07-19

本文件记录仓库当前可由代码、测试和构建结果支持的真实状态。它不把规划能力或未留存证据的外部调用描述为已验证能力。

## Completed

- Product Management
- Marketing Strategy 的结构化生成、校验与持久化链路
- Copy Matrix 三平台文案链路
- Video Project Planning 与分镜校验
- Campaign CSV 导入与 Metrics Calculation
- Growth Recommendation 链路
- Demo Snapshot
- Presentation Mode
- Presentation Flow Navigation
- Dashboard Showcase
- Copy Matrix Showcase
- AI Video Blueprint Showcase
- Growth Copilot Showcase
- VideoRenderTask 本地任务基础设施
- Qwen 真实结构化响应验证
- Wanx Provider 与真实视频生成验证
- Video Render Execution Pipeline
- VideoRenderArtifact 成功结果持久化与只读 API
- Verified Wanx Output 前端展示
- 默认关闭、幂等保护的 Live Render Facade

## AI Capability Status

### Qwen

状态：`Provider implemented / Real execution verified`

- Provider 实现和真实业务 API 入口存在。
- 真实 smoke 测试存在，且默认测试不会调用外部模型。
- `docs/qwen_verification.md` 记录了一次真实调用命令、成功结果和安全边界。

### Wanx

状态：`Provider implemented / Real video pipeline verified`

- `WanxProvider` 实现异步 submit/fetch 契约。
- `VideoRenderExecutionService` 完成一次提交、轮询、状态同步和 Artifact 创建。
- 真实 smoke 已验证 provider task、refresh 状态变化、成功视频 URL 和 Artifact。
- Verified Wanx Output 通过只读 API 展示已有成功 Artifact。
- Live Render Facade 默认关闭，固定参数、确定性幂等键且不自动重试。

## Growth Loop Status

已完成：

- Metrics calculation
- Growth recommendation
- 基于 Demo Snapshot 的 Performance Intelligence 展示
- Performance-driven Optimization 建议展示

未完成：

- Performance-to-Prompt
- Second version generation
- Creative version tracking
- Growth 建议自动写回 Copy 或 Video Prompt
- 自动预算调整或广告平台执行

## Demo Status

Demo Snapshot 状态：`Preset Fixture / No AI Calls / Stable Presentation Data`

Demo Snapshot 是用于稳定比赛展示的预置数据，不是页面访问时实时调用 AI 生成的结果，也不构成真实广告归因证据。Verified Wanx Output 读取独立的成功 Artifact；Live Wanx Demo 默认关闭。

## Next Planned Stages

- 提交材料与验证证据整理
- 长期稳定视频资产交付
- Performance-to-Prompt（尚未实现）
- 创意版本追踪与第二版内容生成
