# SocialPilot AI AI能力说明

## 1. 能力总览

SocialPilot AI将阿里云AI能力放在明确的Provider边界后：Qwen负责结构化文本理解与生成，Wanx负责异步视频生成。确定性指标计算、任务状态、数据校验和持久化由应用代码负责。

```text
Business Service
  ├── TextGenerationProvider → QwenProvider
  └── VisualGenerationProvider → WanxProvider
```

## 2. Qwen应用

### Marketing Strategy

输入商品名称、品类、描述、卖点和目标市场，输出：

- Positioning
- Audience insights
- Marketing angles
- Risks
- Evidence

### Copy Matrix

基于Marketing Strategy生成TikTok、Instagram、Facebook和Pinterest的Hook、Caption、Hashtags和CTA。一次Qwen Provider调用返回完整四平台矩阵，不按平台重复调用。

### Video Blueprint

基于Product、Strategy和Copy生成标题、创意、Scene、镜头、动作、旁白与CTA。Provider只返回结构化策划，不创建视频文件或供应商任务。

### Growth Recommendation

Qwen接收代码已经计算好的指标和Marketing Strategy，负责解释问题并生成建议，不重新计算CTR、CVR、CPA和ROAS。

### 验证与安全

- 真实smoke使用`qwen_smoke` marker和`--run-qwen-smoke`。
- 普通pytest默认skip真实调用。
- 输出经过JSON解析与Pydantic校验。
- 仓库包含`docs/qwen_verification.md`验证记录。
- API Key只从后端环境读取，不返回Frontend。

## 3. Wanx应用

### Provider契约

`WanxProvider`实现：

- `submit(request)`：创建一个异步视频任务。
- `fetch(provider_task_id)`：查询既有任务状态。

submit与fetch使用相同认证来源，但异步submit专用Header不会发送到fetch。供应商响应被转换为内部Submission或Snapshot，不把完整响应暴露给业务层。

### Video Render Execution Pipeline

```text
VideoProject
  ↓
VideoRenderTask (CREATED)
  ↓
atomic submit claim
  ↓
Wanx task
  ↓
refresh / fetch polling
  ↓
VideoRenderArtifact
```

Execution Service保证同一Task只提交一次；refresh只查询状态，不自动重新submit。成功时要求存在输出URL并创建或更新Artifact。

### 真实验证与费用保护

- 真实smoke使用`wanx_smoke` marker和`--run-wanx-smoke`。
- 单次submit，禁止自动重试。
- 15秒轮询，最长5分钟。
- 不批量生成，不在smoke中下载视频。
- 已验证provider task、状态变化、成功URL和Artifact创建。

## 4. Artifact与展示

Artifact Read API只返回已成功结果，不触发Provider。Frontend仅在Artifact存在有效URL时显示Verified Wanx Output；读取失败或没有Artifact时仍显示Video Blueprint。

当前Artifact可能引用临时签名URL，长期对象存储尚未实现。比赛视频已保存为本地MP4资产，但当前Frontend不会自动切换到该文件。

## 5. Growth指标边界

CTR、CVR、CPA和ROAS由`MetricsService`根据聚合总量计算。AI不计算基础指标，也不自动修改预算、创建广告或执行投放。

当前能力为Performance-driven Optimization：系统生成优化建议，为下一轮内容策略提供方向。

## 6. 未实现能力

- Performance-to-Prompt
- Growth建议自动写回Copy或Video Prompt
- 自动生成第二版CopyMatrix或VideoProject
- 创意版本追踪
- 自动广告投放和预算调整
- TTS、字幕和长期视频对象存储

上述能力只能作为后续规划，不应作为当前比赛完成能力陈述。
