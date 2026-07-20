# SocialPilot AI 架构说明

## 黑客松展示架构速览

```text
Product
  ↓
QwenProvider → Marketing Strategy → Copy Matrix → Video Blueprint
                                                    ↓
                                            VideoRenderTask
                                                    ↓
                                              WanxProvider
                                                    ↓
                                      VideoRenderArtifact → Frontend

Campaign Data → Metrics Engine → Growth Copilot → Optimization Advice
```

Presentation Mode读取预置Demo Snapshot并保持`0 AI Calls`；Qwen与Wanx真实能力通过独立验证链证明。Growth Copilot当前输出Performance-driven Optimization建议，不会自动生成第二版内容。

## 业务模块

### Content Studio：短视频生产

负责将商品资料、目标市场、营销策略和平台文案转化为结构化短视频生产方案。Stage 6 生成并保存经过校验的分镜计划，不生成视频文件、音频、字幕、URL 或外部渲染任务。

### Copy Matrix：多平台文案

负责按平台、国家/地区、语言、受众和营销目标生成并保存文案矩阵。当前实现 TikTok、Instagram 和 Facebook 三平台结构化结果；本地化表达、A/B 变体和创意版本追踪仍属后续能力。

### Growth Copilot：投流分析与优化

负责汇总广告表现，围绕预算、受众、渠道和素材输出优化建议，并把结果反馈给内容模块。Stage 5 只接收用户上传的 CSV，不连接广告账户，也不自动执行预算或投放操作。

## 数据流

```text
商品中心
  │ 商品属性、卖点、素材、目标市场
  ▼
营销分析
  │ 内容策略与受众假设
  ├──────────────► Copy Matrix ───────► 多平台文案矩阵
  └──────────────► Content Studio ────► 结构化 Video Blueprint
                                      │
                                      ▼
                                投放结果数据
                                      │
                                      ▼
                               Growth Copilot
                                      │
                          预算 / 受众 / 素材优化建议
                                      │
                                      └──► 为下一轮内容策略提供人工参考
```

产品、内容任务、投放快照和优化建议使用独立的数据模型。模块之间通过应用服务调用与稳定的数据结构协作，避免前端直接拼接业务流程。

当前版本将广告表现转换为 Performance-driven Optimization 建议，供下一轮内容策略参考；尚未实现把建议自动写回 Prompt、自动生成第二版 Copy 或第二版 VideoProject，也没有创意版本追踪。

## AI Provider Layer

```text
TextGenerationProvider                 VisualGenerationProvider
          │                                       │
          ▼                                       ▼
    QwenProvider                              WanxProvider
          │                                       │
 Strategy / Copy / Video Plan          Video submit / task fetch
```

业务服务只依赖 Provider 契约。`QwenProvider` 负责结构化文本生成，`WanxProvider` 负责异步视频任务提交与查询；认证、连接、超时和供应商错误会映射为安全的内部异常，不向客户端暴露密钥、Authorization Header 或完整供应商响应。

## Stage 2 商品数据基础

当前商品中心引入三个关系模型：

- `Product`：保存名称、类别、描述、JSON 卖点列表、JSON 目标市场列表及时间戳。
- `ProductAsset`：通过 `product_id` 关联商品，只登记本地文件名、路径和受支持的图片类型，不执行文件上传。
- `MarketingBrief`：通过 `product_id` 关联商品，保存受众、语言、去重的平台列表、语调和目标。它是用户输入的数据记录，不包含自动生成的营销策略。

```text
Product 1 ────── * ProductAsset
   │
   └──────────── * MarketingBrief
```

请求首先由 Pydantic v2 schema 完成非空列表、空白文本、素材类型和平台去重校验；应用服务负责商品存在性等用例规则；仓储层统一提交 SQLAlchemy 会话。API 不直接返回 ORM model，而是通过响应 schema 映射。

开发阶段采用 `Base.metadata.create_all()` 创建缺失表，该操作幂等且不会删除已有表。开发 Demo seed 通过商品名称判断是否已存在，并受 `APP_ENVIRONMENT=development` 限制。此方案适合比赛阶段新增表；进入多人协作或生产数据库演进后仍应引入正式迁移工具。

## Stage 3 Qwen 营销分析链路

```text
Product
  │ 商品名称、类别、描述、卖点、目标市场
  ▼
MarketingStrategyService
  │ 构造只允许基于商品资料的 JSON Prompt
  ▼
TextGenerationProvider
  │ 当前实现：QwenProvider
  ▼
百炼 OpenAI 兼容 Chat Completions（JSON Mode）
  │ 模型原始文本
  ▼
JSON 解析 → MarketingStrategySchema 校验
  │ 仅校验成功才继续
  ▼
MarketingStrategy 持久化
```

`TextGenerationProvider` 只定义 `generate(prompt) -> str`，业务服务不依赖阿里云 SDK。Qwen Provider 使用北京地域兼容端点、配置模型和 timeout，并将认证、连接/超时、模型状态错误转换为安全的内部异常。异常信息不包含 Key 或完整供应商响应。

MarketingStrategy 保存定位、目标用户洞察、营销角度、风险和依据。其中数组使用 JSON 列；Schema 和 ORM 都拒绝空核心字段。模型负责理解和生成，代码负责 JSON 解析、结构校验、商品存在性检查和持久化。

Stage 3 只完成商品营销分析，不向 Copy Matrix、Content Studio 或 Growth Copilot 触发任何下游任务。

## Stage 4 Copy Matrix

```text
Product + 最新 MarketingStrategy
              │
              ▼
      CopyGenerationService
              │ 单个 Prompt / 单次 Provider.generate
              ▼
          Qwen Provider
              │ 一个 JSON 对象
              ▼
  CopyMatrixSchema 严格校验三个平台
              │
              ▼
       CopyMatrix 持久化
```

CopyMatrix 通过 `product_id` 和 `marketing_strategy_id` 保留数据来源，`copies` JSON 列一次保存 TikTok、Instagram、Facebook 三个 `PlatformCopySchema`。每个平台包含 hook、caption、hashtags 和 CTA。

Prompt 在一个请求中定义三种平台逻辑：TikTok 强调强 Hook、UGC、短句和情绪；Instagram 强调 Lifestyle、品牌感和视觉描述；Facebook 强调功能价值、理性购买理由和产品优势。同时禁止医疗承诺、减肥保证、虚假认证和无商品依据的宣称。

Provider 工厂位于共享 API dependency，Strategy API 和 Copy API 彼此独立，不存在路由间依赖。若商品没有 MarketingStrategy，Copy API 返回 409，且不会调用模型。

## Stage 5 Growth Copilot

```text
广告 CSV ──完整校验──► AdCampaign 批量写入
                             │
                             ▼
                    MetricsService（纯计算）
                    总曝光 / 点击 / 转化 / 花费 / 收入
                             │
                             ▼
                     CTR / CVR / CPA / ROAS
                             │
                 + 最新 MarketingStrategy
                             ▼
                   GrowthAnalysisService
                             │
                    共享 Text Provider
                             ▼
                 GrowthRecommendation（建议）
```

CSV 解析服务先完成文件类型、编码、表头和所有数据行校验，之后才调用仓储层单次提交，避免部分导入。`MetricsService` 不持有 Provider，也不调用 LLM；它先聚合所有 Campaign 总量，再计算比率，从而避免简单平均各行比率造成权重失真。除零时 CTR/CVR 返回 0，无法定义的 CPA/ROAS 返回空值。

GrowthAnalysisService 只接收 MetricsService 的计算结果和已保存的 MarketingStrategy。模型负责解释指标、提出预算与素材建议，不能重新计算指标；输出必须通过 Pydantic v2 校验。本阶段建议仅供人工决策，不会自动投放或调整预算。

## Stage 6 Content Studio

```text
Product + 最新 MarketingStrategy + 最新 CopyMatrix
                         │
                         ▼
              ContentStudioService
                         │ 单个 Prompt / 单次调用
                         ▼
             TextGenerationProvider
                         │
                         ▼
                VideoPlanSchema
        唯一 sequence / 正时长 / 总时长一致
                         │
                         ▼
       VideoProject（status = planned）
```

VideoProject 通过三个外键记录商品、营销策略和文案矩阵来源，保存平台、画幅、总时长、标题、创意、分镜 JSON、CTA 和状态。平台是可扩展文本字段，当前请求默认 TikTok，并未在模型层限制未来平台集合。

当前分镜包含镜头类型、视觉描述、动作和旁白文本；旁白只是制作脚本，不会触发 TTS。Schema 在数据库写入前验证分镜序号不重复、每段时长大于零，以及所有分镜时长之和等于项目总时长。Provider 返回不合规时不会持久化。

Stage 6 继续复用共享 `TextGenerationProvider`，只生成结构化 Blueprint。真实视频生成由独立的 `VisualGenerationProvider`、`WanxProvider`、`VideoRenderTask` 和执行服务负责；供应商任务 ID、轮询状态和结果地址不会混入策划模型。

## Stage 7 Demo Dashboard

```text
POST /demo/prepare
        │ 开发环境 / 幂等 / 单事务 / 无 Provider
        ▼
DemoScenario（preset_fixture）
        │ 精确引用 Product / Strategy / Copy / Video / Campaign
        ▼
DashboardService ──► MetricsService
        │                 │ 只做总量指标计算
        └─────────────────┘
        ▼
DashboardSnapshot
Product → Strategy → Copy → Video → Growth
```

DemoScenario 使用唯一 slug 和明确的 `preset_fixture` 来源标识，不以商品名称推断演示数据。它保存完整演示链路的记录 ID、Campaign ID 列表和预置 Growth Recommendation 快照，保证重复准备不会增加重复记录。

DemoService、DashboardService 及对应路由都不导入、不注入 TextGenerationProvider，也不调用任何生成 Service。DashboardService 对普通存量商品使用最新已保存记录；缺失 Strategy、Copy、Video 或 Growth 时返回 `missing`，只有指标或建议时返回 `partial`。查询不会为了补齐数据触发 AI。

Demo Snapshot 明确标记 `0 AI Calls` 和“使用预置演示数据”。该通道用于比赛现场稳定展示，不冒充实时生成结果；真实 AI 工作流仍通过各自独立的生成 API 运行。

## Stage 8 / C3 Video Generation Pipeline

```text
Product
  │
  ▼
VideoProject（已校验的生产方案）
  │ 1:N
  ▼
VideoRenderTask（幂等本地任务）
  │
  ▼
VideoRenderExecutionService
  │ submit once
  ▼
WanxProvider
  │ asynchronous task polling
  ▼
VideoRenderArtifact
  │ read-only API
  ▼
Frontend Verified Wanx Output
```

`VideoRenderService` 负责确认 VideoProject 和分镜存在、校验正时长、构造确定性渲染提示词以及幂等创建本地任务。创建任务本身不注入 Provider，因此不会触发网络请求。

`VideoRenderExecutionService` 对 `CREATED` 任务执行原子提交认领，保证同一任务只提交一次；后续 refresh 只调用 `fetch()`，同步 `SUBMITTED`、`PENDING`、`RUNNING`、`SUCCEEDED`、`FAILED` 或 `CANCELED` 状态。成功结果保存为独立 `VideoRenderArtifact`，Task 继续保存来源、供应商任务标识、渲染参数、幂等键和安全错误摘要。

`WanxProvider` 已实现异步 submit/fetch HTTP 契约，并通过独立真实 smoke 验证完整任务链。Artifact Read API 只查询已有成功结果，不触发 submit、refresh 或 Provider。Live Render Facade 默认关闭，固定参数并复用服务端幂等键；已有成功 Artifact 或已有任务时不会新建第二个任务。

## 为什么采用模块化单体

黑客松和产品早期阶段需要快速迭代、低部署成本与清晰的业务边界。模块化单体把 API、服务、仓储和数据模型放在同一后端进程中，便于本地开发、事务管理、测试和部署；同时按业务能力组织代码，避免演变成相互耦合的“大泥球”。

当单个模块出现明确的独立扩展需求（例如视频渲染需要 GPU 队列）时，可以沿现有服务边界拆分为独立服务，而无需在第一阶段承担微服务的网络、观测和分布式一致性成本。

## 分层约定

- `api/v1`：HTTP 路由、参数校验和响应映射，不承载核心业务逻辑。
- `schemas`：API 与模块间使用的 Pydantic v2 数据契约。
- `services`：编排业务用例与模块协作，是未来 AI 能力的主要调用入口。
- `repositories`：封装数据库读写，避免服务层依赖 SQL 细节。
- `models`：SQLAlchemy 2.x 持久化模型。
- `core`：环境配置、异常处理、日志和后续安全能力。
- `db`：数据库引擎、会话和声明式基类。

## Provider 扩展位置

当前 Qwen 与 Wanx 均通过统一 Provider 接口接入，模型能力不直接写进 API 路由：

```text
app/
├── providers/
│   ├── qwen_provider.py      # 通义千问结构化文本适配
│   ├── wanx_provider.py      # 通义万相异步视频适配
│   ├── base.py               # 文本 Provider 契约与安全异常
│   └── visual_base.py        # 视频 Provider 契约与 DTO
└── services/
    ├── content_studio_service.py
    ├── video_render_execution_service.py
    └── live_video_render_service.py
```

- **通义千问**：已有 Qwen Provider、业务服务入口、默认跳过的真实 smoke，以及仓库内验证报告。指标计算仍由可测试的确定性代码完成。
- **通义万相**：已有 Wanx Provider、提交/查询适配、执行服务、Artifact 持久化、真实 smoke 与前端只读展示。
- **TTS**：作为 Content Studio 的独立语音 provider，输入经过审查的脚本与语言/音色配置。
- **Model Router**：位于业务服务与具体模型 provider 之间，统一处理模型选择、超时、重试、限流、成本记录和降级。业务模块只依赖内部接口。

所有模型凭据都从环境变量或云端密钥服务读取；日志不得记录密钥、完整用户素材或敏感广告数据。模型返回内容需要经过 schema 校验后才能进入后续流程。

## 当前阶段边界

当前已具备商品资料、结构化营销策略、三平台文案、CSV 广告数据分析、短视频生产方案、Wanx 真实视频生成、Artifact 展示和零 AI 调用的一键比赛演示链。Demo Snapshot 是预置 fixture，不是页面访问时实时 AI 生成的结果；Verified Wanx Output 读取已成功生成的独立 Artifact。系统仍不包含 Performance-to-Prompt、自动内容二次生成、创意版本追踪、TTS、字幕、长期视频存储或发布、广告平台 API、自动投放、自动调预算、登录或支付。当前可验证状态以 `docs/version_status.md` 为准。
