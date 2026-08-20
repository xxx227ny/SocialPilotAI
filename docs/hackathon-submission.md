# SocialPilot AI 阿里云AI黑客松初赛说明

## 一、项目基本信息

- **项目名称**：SocialPilot AI
- **项目定位**：AI驱动的跨境电商社媒增长助手
- **参赛方向**：阿里云AI创新应用 / 跨境电商智能化
- **当前基线**：`9e2312400c215f2cc130ad8c3a536dfe49bc2e42`

## 二、项目简介

SocialPilot AI面向缺少专业营销团队的跨境电商卖家，通过Qwen完成商品理解、营销策略、多平台文案和视频策划，通过Wanx完成真实视频生成验证，再结合广告数据计算与Growth Copilot建议，形成可展示、可追踪的社媒营销工作流。

## 三、解决的核心问题

1. 海外平台内容逻辑不同，商家需要重复策划和改写。
2. 商品卖点、营销策略、文案和视频之间缺少统一来源。
3. 视频生成涉及异步任务、费用和失败状态，缺少安全编排。
4. 广告指标难以转化为清晰的内容优化建议。
5. 现场演示依赖实时AI时容易受到网络、费用和等待影响。

## 四、解决方案

```text
商品输入
  ↓
Qwen Marketing Strategy
  ↓
TikTok / Instagram / Facebook / Pinterest Copy Matrix
  ↓
AI Video Blueprint
  ↓
Wanx Video Generation Pipeline
  ↓
Verified VideoRenderArtifact
  ↓
Campaign Metrics + Growth Optimization Advice
```

系统使用明确的数据模型记录Product、Strategy、Copy、VideoProject、RenderTask和Artifact关系。Presentation Mode使用稳定的预置Snapshot，真实AI链路由独立smoke与成功Artifact证明。

## 五、阿里云AI应用

### Qwen

- 商品理解与Marketing Strategy
- TikTok、Instagram、Facebook、Pinterest Copy Matrix
- 结构化Video Blueprint
- Growth Recommendation

Qwen输出经过JSON解析和Pydantic校验，指标计算不交给模型。

### Wanx

- 异步视频任务submit
- provider task状态fetch
- 本地任务状态同步
- 成功VideoRenderArtifact创建
- Verified Wanx Output展示

真实Wanx链路已验证一次submit、轮询和Artifact创建；普通测试与Presentation页面不会自动调用Wanx。

## 六、技术架构

- **Backend**：Python、FastAPI、SQLAlchemy、Pydantic、Pytest
- **Frontend**：React、TypeScript、Vite
- **Text AI**：QwenProvider / TextGenerationProvider
- **Video AI**：WanxProvider / VisualGenerationProvider
- **Persistence**：SQLite、Repository和SQLAlchemy Model
- **Quality**：Mock Provider单元测试、真实smoke隔离、Ruff、TypeScript build

核心工程设计包括Provider抽象、Schema校验、确定性idempotency key、原子submit claim、refresh-only polling、安全错误映射和只读Artifact API。

## 七、当前完成能力

- Product商品数据与营销任务
- Qwen Marketing Strategy真实验证
- 四平台Copy Matrix
- AI Video Blueprint
- Wanx真实视频生成Pipeline
- VideoRenderArtifact与Verified Output
- Campaign CSV与CTR/CVR/CPA/ROAS计算
- Growth Copilot建议
- Demo Snapshot与Presentation Mode
- 默认关闭、幂等保护的Live Render Facade

## 八、创新点

### 1. 商品到内容的数据来源链

Strategy、Copy和Video不是相互独立的生成结果，而是保留Product及上游记录关系，便于追踪内容依据。

### 2. 策划与真实视频生成解耦

Video Blueprint负责结构化创意，RenderTask与Wanx Pipeline负责外部异步执行，避免供应商状态污染策划模型。

### 3. AI与确定性计算分工

广告指标由代码计算，AI负责解释和建议；模型不重新计算业务指标。

### 4. 真实能力与稳定Demo分离

真实Qwen/Wanx通过独立验证链证明，比赛页面读取`0 AI Calls`的稳定Snapshot，降低现场失败和额度风险。

## 九、Demo流程

1. **Overview**：商品理解、Marketing Strategy和项目价值。
2. **Copy Matrix**：四平台差异化内容。
3. **Video Blueprint**：Storyboard与Verified Wanx Output。
4. **Growth Copilot**：广告指标、平台比较和优化建议。

推荐使用Presentation Mode和本地Wanx MP4，现场不执行真实生成。

## 十、真实性边界与限制

- Demo Snapshot是预置fixture，不代表页面访问时实时调用AI。
- 当前未实现Performance-to-Prompt。
- 当前不自动生成第二版Copy或VideoProject。
- 当前没有创意版本追踪、自动投放或自动预算调整。
- VideoRenderArtifact不等同于长期对象存储，供应商URL可能过期。
- Live Wanx Demo默认关闭，已有成功Artifact时会直接复用。

## 十一、商业化方向

目标用户包括Amazon卖家、Shopify商家、独立站卖家和小型跨境团队。未来可以按商品分析、内容生成、视频额度、广告分析、团队协作和多账号能力设计SaaS订阅层级，但当前项目仍处于黑客松Demo验证阶段。

## 十二、总结

SocialPilot AI展示了阿里云Qwen与Wanx在跨境电商营销场景中的组合应用：Qwen负责理解和结构化内容，Wanx负责真实视频生成，应用层负责数据校验、任务控制、指标计算和稳定展示。项目目标不是替代完整营销团队，而是让小型卖家以更低门槛获得一致、可解释、可验证的社媒增长工作流。
