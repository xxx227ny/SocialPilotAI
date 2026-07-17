# SocialPilot AI Current Status

## Stable Baseline

Version: `C1 Baseline`

Date: 2026-07-17

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

## AI Capability Status

### Qwen

状态：`Provider implemented / Real execution not verified`

- Provider 实现和真实业务 API 入口存在。
- 真实 smoke 测试存在，且默认测试不会调用外部模型。
- 当前仓库没有保存可独立核验的成功调用日志、响应记录或测试报告，因此 C1 不声明真实调用已经验证。

### Wanx

状态：`Not implemented / Architecture placeholder only`

- `VideoRenderTask` 与供应商无关的 `VisualGenerationProvider` 抽象存在。
- 当前没有 Wanx Provider、外部 SDK、提交/轮询执行器或真实视频结果。

## Growth Loop Status

已完成：

- Metrics calculation
- Growth recommendation
- 基于 Demo Snapshot 的 Performance Intelligence 展示

未完成：

- Performance-to-Prompt
- Second version generation
- Creative version tracking
- 自动预算调整或广告平台执行

## Demo Status

Demo Snapshot 状态：`Preset Fixture / No AI Calls / Stable Presentation Data`

Demo Snapshot 是用于稳定比赛展示的预置数据，不是页面访问时实时调用 AI 生成的结果，也不构成真实广告归因证据。

## Next Planned Stages

- C2 Real Qwen Verification
- C3 Wanx Video Pipeline
- C4 Performance-to-Prompt
- C5 Final Demo Polish
