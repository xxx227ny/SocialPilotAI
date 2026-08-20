# SocialPilot AI 项目概览

## 项目定位

SocialPilot AI 是面向跨境电商商家的 AI 社媒增长助手，帮助中小卖家把商品信息转化为营销策略、多平台内容、视频方案和可执行的增长优化建议。

参赛方向：阿里云 AI 创新应用 / 跨境电商智能化。

## 背景与痛点

跨境卖家进入海外社交平台时，通常需要同时解决四类问题：

1. TikTok、Instagram、Facebook和Pinterest具有不同的内容语言，重复策划成本高。
2. 小团队缺少完整的商品策略、文案、视频和投放分析能力。
3. AI生成内容容易与真实商品卖点、目标市场和风险边界脱节。
4. 广告数据与下一轮内容之间缺少可解释、可追踪的连接。

## 产品方案

```text
Product
  ↓
Qwen Marketing Strategy
  ↓
TikTok / Instagram / Facebook / Pinterest Copy Matrix
  ↓
AI Video Blueprint
  ↓
Wanx Video Generation → VideoRenderArtifact
  ↓
Campaign Metrics → Growth Optimization Advice
```

Product、Strategy、Copy和VideoProject保留数据来源关系。视频策划与视频生成分离：Content Studio只产生经过校验的Blueprint，Wanx Pipeline使用独立RenderTask执行异步生成。Growth Copilot先由代码计算指标，再让AI解释结果并提出建议。

## 核心能力

### AI Marketing Strategy

基于商品名称、品类、描述、卖点和目标市场生成定位、受众洞察、营销角度、风险和依据。

### Copy Matrix

一次生成TikTok、Instagram、Facebook和Pinterest的Hook、Caption、Hashtags和CTA，体现短视频、社交展示、深度说明和搜索收藏场景的不同内容逻辑。

### AI Video Blueprint

生成主题、时长、画幅、Scene、镜头、动作、旁白和CTA，并校验Scene顺序与总时长。

### Wanx Video Generation

通过Wanx Provider提交异步视频任务，由Execution Service轮询状态，成功结果保存为VideoRenderArtifact。系统支持展示既有Verified Wanx Output，不宣称实时无限或批量生成。

### Growth Copilot

从广告数据计算CTR、CVR、CPA和ROAS，并生成预算、渠道和素材优化建议。

### Presentation Mode

比赛页面使用预置Demo Snapshot，按Overview、Copy Matrix、Video Blueprint、Growth Copilot顺序展示，页面访问为`0 AI Calls`。

## 核心价值

- 降低跨境社媒策略和内容生产门槛。
- 用同一商品策略协调多平台文案与视频方案。
- 用Provider抽象、Schema校验和任务幂等控制外部AI风险。
- 将广告指标转化为清晰的下一轮优化方向。
- 将稳定比赛Demo与真实AI验证分离，兼顾展示稳定性和技术真实性。

## 当前边界

项目尚未实现Performance-to-Prompt、Growth建议自动写回Prompt、自动生成第二版Copy/VideoProject、创意版本追踪、自动投放或长期视频对象存储。Growth建议用于人工决策，不代表自动执行或确定性增长承诺。
