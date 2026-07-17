# SocialPilot AI 架构说明

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
  ├──────────────► Copy Matrix ───────► 多平台文案版本
  └──────────────► Content Studio ────► 短视频素材版本
                                      │
                                      ▼
                                投放结果数据
                                      │
                                      ▼
                               Growth Copilot
                                      │
                          预算 / 受众 / 素材优化建议
                                      │
                                      └──► 回流营销分析与内容再生成
```

产品、内容任务、素材版本、投放快照和优化建议将拥有独立的数据模型。模块之间通过应用服务调用与稳定的数据结构协作，避免前端直接拼接业务流程。

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

Stage 6 继续复用共享 TextGenerationProvider，不创建虚假的视频 Provider。Stage 8.1 已增加独立的 `VisualGenerationProvider` 抽象和 `VideoRenderTask` 本地任务基础设施，但没有具体 Wanx Provider 或外部调用；供应商任务 ID、轮询状态和结果地址不会混入当前策划模型。

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

## Stage 8.1 VideoRenderTask 基础设施

```text
VideoProject（已校验的生产方案）
        │ 1:N
        ▼
VideoRenderTask（本地 CREATED 任务）
        │ 未来由独立执行器消费
        ▼
VisualGenerationProvider（submit / fetch 抽象）
        │ 未来实现，当前不存在具体 Provider
        ▼
视频供应商
```

`VideoRenderService` 当前只负责确认 VideoProject 和分镜存在、再次校验正时长、构造确定性渲染提示词以及幂等创建本地任务。API 和 Service 都不注入 `VisualGenerationProvider`，因此创建与查询任务不会触发网络请求。

`VideoRenderTask` 保存来源项目、分镜序号、任务状态、供应商任务标识预留字段、渲染参数、幂等键和安全错误摘要。它不保存真实视频 URL。一个 VideoProject 可拆分为多个分镜任务，未来可由队列执行器按任务状态调用具体 Provider；Content Studio 继续只负责生成结构化 VideoProject，两条职责无需重构或相互耦合。

本阶段的 `VisualGenerationProvider` 只定义异步 `submit()` 与 `fetch()` 契约及供应商无关 DTO，没有 Wanx 实现、密钥配置或外部 SDK。未来接入时新增具体适配器和执行器即可，HTTP API、VideoProject 与任务持久化结构可以保持稳定。

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

## 后续模型接入位置（规划）

以下目录是目标架构示意，不代表当前仓库已存在这些实现。模型能力应通过统一的 provider 接口接入，而不是直接写进 API 路由：

```text
app/
├── services/
│   ├── content_studio/       # 视频任务编排
│   ├── copy_matrix/          # 文案任务编排
│   └── growth_copilot/       # 投流洞察编排
└── integrations/             # 后续新增
    └── ai/
        ├── router.py         # Model Router：按任务、成本与可用性选模型
        ├── qwen.py           # 通义千问：分析、脚本、文案与结构化输出
        ├── wanx.py           # 通义万相：图像/视频视觉素材
        └── tts.py            # TTS：多语言配音
```

- **通义千问**：当前已有 Qwen Provider、业务服务入口和默认跳过的真实 smoke 测试，但仓库内未保存可独立核验的真实成功调用证据。指标计算仍由可测试的确定性代码完成。
- **通义万相**：当前未实现。现有 `VisualGenerationProvider` 和 `VideoRenderTask` 仅为供应商无关的架构占位；未来实现才会提交和轮询外部异步任务。
- **TTS**：作为 Content Studio 的独立语音 provider，输入经过审查的脚本与语言/音色配置。
- **Model Router**：位于业务服务与具体模型 provider 之间，统一处理模型选择、超时、重试、限流、成本记录和降级。业务模块只依赖内部接口。

所有模型凭据都从环境变量或云端密钥服务读取；日志不得记录密钥、完整用户素材或敏感广告数据。模型返回内容需要经过 schema 校验后才能进入后续流程。

## 当前阶段边界

当前已具备商品资料、结构化营销策略、三平台文案、CSV 广告数据分析、短视频生产方案和零 AI 调用的一键比赛演示闭环。Demo Snapshot 是预置 fixture，不是实时 AI 结果。系统仍不包含 Performance-to-Prompt、内容二次生成、创意版本追踪、真实视频生成、通义万相、TTS、字幕、视频存储或发布、广告平台 API、自动投放、自动调预算、登录或支付。当前可验证状态以 `docs/version_status.md` 为准。
