# SocialPilot AI 项目概述

## 项目名称

SocialPilot AI

## 一句话介绍

SocialPilot AI 是面向跨境电商商家的 AI 社媒增长助手，将商品理解、营销策略、多平台文案、视频策划、真实视频生成验证和广告表现分析组织为一条可展示、可追踪的工作流。

## 用户痛点

- 跨境商家需要同时适配多个社媒平台，内容策划与改写成本高。
- 商品卖点、目标市场和平台表达经常脱节，内容缺乏一致的策略来源。
- 视频生产涉及策划、生成、异步任务和结果管理，流程复杂且容易失控。
- 广告数据可以计算，但中小团队难以把 CTR、CVR、CPA、ROAS 转换为清晰的优化方向。
- 比赛或销售演示需要稳定复现，不能依赖页面打开时持续调用外部 AI。

## 产品解决方案

SocialPilot AI 以 Product 为业务起点，使用 Qwen 生成结构化 Marketing Strategy，再生成 TikTok、Instagram 和 Facebook 的 Copy Matrix。Content Studio 将 Product、Strategy 和 Copy 组合为包含分镜、镜头、动作、旁白和 CTA 的 Video Blueprint。

真实视频链由独立的 Wanx Provider 和 Video Render Execution Pipeline 承担。系统通过幂等任务提交、状态轮询和 Artifact 持久化保存成功结果，并在 AI Video Blueprint 页面只读展示 Verified Wanx Output。Growth Copilot 使用确定性代码计算广告指标，再生成问题、预算和素材优化建议。

## AI 工作流程

```text
Product
  ↓
Qwen Marketing Strategy
  ↓
TikTok / Instagram / Facebook Copy Matrix
  ↓
AI Video Blueprint
  ↓
VideoRenderTask
  ↓
Wanx Provider submit / fetch
  ↓
VideoRenderArtifact
  ↓
广告指标计算与 Growth Optimization 建议
```

比赛 Presentation Mode 默认读取预置 Demo Snapshot，页面展示为 `0 AI Calls`。Qwen 与 Wanx 的真实能力通过独立 smoke 和既有成功 Artifact 验证，不在普通页面访问时重复调用。

## 核心价值

- **策略一致性**：Strategy、Copy 和 Video 均保留明确的数据来源关系。
- **多平台表达**：一次结构化 Copy 生成覆盖 TikTok、Instagram 和 Facebook。
- **真实视频链路**：不仅展示 Blueprint，也验证 Wanx 异步视频任务和成功 Artifact。
- **工程可控性**：Provider 抽象、Schema 校验、幂等提交和安全错误映射降低外部 AI 风险。
- **演示稳定性**：预置 Snapshot 与真实 Provider 验证分离，避免现场页面自动消耗额度。
- **数据驱动方向**：将广告指标转换为可读的 Performance-driven Optimization 建议。

## 当前能力边界

当前版本尚未实现 Performance-to-Prompt、Growth 建议自动写回 Prompt、第二版 Copy/VideoProject 自动生成或创意版本追踪。Growth Copilot 的建议用于下一轮人工决策，不代表自动投放或确定性增长承诺。VideoRenderArtifact 当前不等同于长期媒体存储；比赛使用的真实视频已另存为本地 Demo 资产。
