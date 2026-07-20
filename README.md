# SocialPilot AI

## 项目简介

SocialPilot AI 是面向跨境电商商家的 AI 社媒营销增长平台。项目围绕商品资料、营销分析、内容生产、投放分析与优化建议形成演示链，覆盖 AI 社媒文案矩阵、结构化视频 Blueprint、真实 Wanx 视频生成验证和投流优化建议。

当前比赛基线为 `9e2312400c215f2cc130ad8c3a536dfe49bc2e42`。项目已完成模块化单体 Demo、Presentation Flow、零 AI 调用的预置 Demo Snapshot，以及 Qwen 和 Wanx 的真实 Provider 验证链路。系统支持从结构化 `VideoProject` 创建渲染任务，通过 Wanx 提交和轮询真实视频任务，并把成功结果保存为 `VideoRenderArtifact` 供前端只读展示。Performance-to-Prompt、内容二次生成和创意版本追踪仍未实现。完整状态见 [docs/version_status.md](docs/version_status.md)。

## 背景痛点

- **平台差异大**：TikTok、Instagram 和 Facebook 的内容节奏、视觉偏好与购买决策逻辑不同，重复改写成本高。
- **营销能力门槛高**：中小卖家通常缺少完整的策略、文案、视频和投放分析团队。
- **内容与商品脱节**：生成内容容易忽略真实卖点、目标市场和风险边界。
- **视频链路复杂**：视频策划、异步任务、状态查询和结果管理需要稳定的工程编排。
- **数据难以行动化**：CTR、CVR、CPA、ROAS 可以计算，但不容易转化为清晰的下一轮优化方向。

## 解决方案

SocialPilot AI 从结构化商品信息出发，让 Qwen 生成 Marketing Strategy、多平台 Copy Matrix 和 Video Blueprint；真实视频由独立的 Wanx Provider 与执行服务异步生成并保存为 Artifact。投放数据由确定性 Metrics Engine 计算，再由 Growth Copilot解释指标并给出优化建议。

```text
商品信息
  ↓
Qwen 商品理解与 Marketing Strategy
  ↓
TikTok / Instagram / Facebook Copy Matrix
  ↓
AI Video Blueprint
  ↓
Wanx VideoRenderTask → Polling → VideoRenderArtifact
  ↓
CTR / CVR / CPA / ROAS
  ↓
Performance-driven Optimization 建议
```

当前版本不会把Growth建议自动写回Prompt，也不会自动生成第二版Copy或VideoProject。

## 核心功能

### AI Marketing Strategy

Qwen基于商品名称、品类、描述、卖点和目标市场生成结构化定位、受众洞察、营销角度、风险和商品依据。模型输出必须经过JSON解析与Pydantic校验后才能保存。

### Copy Matrix

一次生成TikTok、Instagram和Facebook三套差异化内容，每个平台包含Hook、Caption、Hashtags和CTA，并保留Marketing Strategy来源关系。

### AI Video Blueprint

将Product、Strategy和Copy转换为结构化短视频方案，包括主题、总时长、画幅、Scene顺序、镜头类型、视觉描述、动作、旁白和CTA。Blueprint与真实视频渲染相互解耦。

### Verified Wanx Output

系统已验证真实Wanx异步视频生成链。`VideoRenderExecutionService`只提交一次任务，后续通过fetch轮询状态，成功后保存`VideoRenderArtifact`。Frontend只读展示已有结果；没有Artifact时仍保留Blueprint。

### Growth Copilot

系统使用确定性代码聚合广告数据并计算CTR、CVR、CPA和ROAS，再结合既有Marketing Strategy生成问题、预算和素材优化建议。当前建议用于人工决策，不自动投放或二次生成内容。

### Presentation Mode

比赛模式按Overview → Copy Matrix → Video Blueprint → Growth Copilot展示统一Demo Snapshot。页面明确标记`preset_fixture`和`0 AI Calls`，避免现场页面访问自动消耗AI额度。

## 技术架构

```text
React + TypeScript + Vite
          │
          ▼
FastAPI API / Pydantic Schemas
          │
          ├── Business Services ── SQLAlchemy ── SQLite
          │
          ├── TextGenerationProvider ── QwenProvider
          │
          └── VisualGenerationProvider ── WanxProvider
                                          │
                                  VideoRenderExecutionService
                                          │
                                  VideoRenderTask / Artifact
```

系统采用模块化单体架构，按API、Service、Repository、Model、Schema和Provider分层。外部AI适配与业务编排分离，便于使用Mock测试核心流程，并通过Provider专属marker隔离真实smoke。

## AI能力说明

- **Qwen**：用于Marketing Strategy、Copy Matrix、Video Blueprint和Growth Recommendation的结构化文本生成；仓库包含真实验证报告。
- **Wanx**：用于异步视频任务submit/fetch；已验证Task状态轮询和Artifact创建。
- **Metrics Engine**：CTR、CVR、CPA、ROAS由代码计算，不交给模型计算。
- **安全边界**：真实smoke默认跳过，API Key只从后端环境读取，错误响应不暴露凭据或完整供应商响应。
- **未实现能力**：Performance-to-Prompt、自动第二版内容生成、创意版本追踪和长期视频对象存储。

## 当前已完成

- FastAPI 应用、`/api/v1` 统一路由和 health 接口
- Pydantic v2 环境配置、开发 CORS、全局异常处理骨架
- SQLAlchemy 2.x、SQLite 连接、会话结构与当前业务数据模型
- health 接口 pytest 测试与 Ruff 规则
- React + TypeScript + Vite 管理界面
- 总览、商品中心、文案矩阵、视频工厂、投流优化五个路由
- 前端后端服务状态检测
- 三个核心业务模块的架构边界和后续模型接入设计
- Product、ProductAsset、MarketingBrief 三个业务数据模型
- 商品创建、查询、修改、素材信息登记与营销任务创建 API
- 幂等数据库初始化和仅开发环境生效的 Portable Blender Demo 数据
- 商品中心列表和创建商品表单
- Provider 中立的文本生成接口和 Qwen Provider
- 商品资料到结构化 MarketingStrategy 的生成、校验与持久化链路
- 商品中心营销分析按钮与结果展示
- 基于最新 MarketingStrategy 的 Copy Matrix 单次生成链路
- TikTok、Instagram、Facebook 三平台文案卡片
- CSV 广告数据整批校验与原子导入
- 基于总量聚合的 CTR、CVR、CPA、ROAS 确定性计算
- 复用共享 Provider 的 Growth Copilot 分析与前端建议展示
- 基于 Product、MarketingStrategy 和 CopyMatrix 的短视频生产方案生成
- VideoProject 来源追踪、分镜时间线校验和 Content Studio 页面
- 零 AI 调用的一键 Portable Blender Demo Snapshot
- 聚合 Product、Strategy、Copy、Video 与 Growth 的比赛展示 Dashboard
- 对缺失业务数据安全降级的 Dashboard 查询接口
- Presentation Mode、比赛演示流程导航及 Dashboard / Copy Matrix / AI Video Blueprint / Growth Copilot 展示页
- Qwen Provider 真实结构化响应 smoke 验证
- Wanx Provider、异步任务提交与查询适配
- `VideoRenderExecutionService` 提交、轮询和状态同步链路
- `VideoRenderArtifact` 成功结果持久化与只读查询 API
- AI Video Blueprint 页面中的 Verified Wanx Output 只读播放器
- 默认关闭、固定参数、幂等保护的 Live Render Facade 和可选前端面板

> 真实性边界：Demo Snapshot 使用预置 fixture，展示期间为 `0 AI Calls`；它不是页面访问时实时生成的结果。Qwen 与 Wanx 的真实链路通过独立 smoke 和既有 Artifact 验证。Live Wanx Demo 默认关闭，仅在前后端显式启用并由用户确认后才允许进入安全 Facade。当前 Growth Copilot 只生成 Performance-driven Optimization 建议，不会自动生成第二版 Copy 或 VideoProject。

## Stage 2 API

| 方法 | 地址 | 说明 |
| --- | --- | --- |
| `POST` | `/api/v1/products` | 创建商品 |
| `GET` | `/api/v1/products` | 获取商品列表 |
| `GET` | `/api/v1/products/{id}` | 获取商品详情 |
| `PATCH` | `/api/v1/products/{id}` | 修改商品 |
| `POST` | `/api/v1/products/{id}/assets` | 登记 jpg/jpeg/png/webp 素材信息 |
| `POST` | `/api/v1/marketing-tasks` | 创建营销任务资料 |
| `POST` | `/api/v1/products/{id}/strategy` | 调用 Qwen 生成并保存结构化营销分析 |
| `POST` | `/api/v1/products/{id}/copy` | 单次调用生成并保存三平台社媒文案 |
| `POST` | `/api/v1/products/{id}/campaigns/upload` | 校验并导入广告 CSV |
| `POST` | `/api/v1/products/{id}/growth-analysis` | 返回聚合指标与 AI 优化建议 |
| `POST` | `/api/v1/products/{id}/video-projects` | 生成并保存结构化短视频生产方案 |
| `POST` | `/api/v1/demo/prepare` | 幂等准备预置演示快照，不调用 AI |
| `GET` | `/api/v1/demo/snapshot` | 只读获取预置 Demo Snapshot，不调用 AI |
| `GET` | `/api/v1/dashboard/products/{id}` | 读取商品完整营销闭环，不调用 AI |
| `POST` | `/api/v1/video-projects/{id}/render-tasks` | 只创建本地 `CREATED` 视频渲染任务，不调用外部服务 |
| `GET` | `/api/v1/video-render-tasks/{id}` | 查询本地视频渲染任务状态 |
| `POST` | `/api/v1/video-render-tasks/{id}/submit` | 通过执行服务向 Wanx 提交一次渲染任务 |
| `POST` | `/api/v1/video-render-tasks/{id}/refresh` | 查询供应商任务并同步状态与成功 Artifact |
| `GET` | `/api/v1/video-projects/{id}/render-artifacts` | 只读查询已有成功视频 Artifact，不调用 Provider |
| `POST` | `/api/v1/video-projects/{id}/live-render` | Feature Flag 保护的固定参数 Live Render Facade |

应用启动时会通过 SQLAlchemy `create_all` 创建缺失表，重复启动不会报错。在 `APP_ENVIRONMENT=development` 时会幂等写入 Portable Blender 演示商品；生产环境应设置为 `production`，不会写入 Demo 数据。

## Stage 3 百炼配置

Qwen Provider 使用阿里云百炼官方 OpenAI 兼容 Chat Completions 接口。实际 Key 只能写入后端 `.env`，不能写入 `.env.example` 或前端环境变量：

```dotenv
DASHSCOPE_API_KEY=
QWEN_MODEL=qwen-plus
QWEN_TIMEOUT=30
```

Provider 开启 JSON Mode，模型文本经过 JSON 解析和 Pydantic 校验后才能保存。普通测试全部使用 Mock，不访问外部 API。

真实 smoke 测试必须显式执行：

```powershell
cd D:\SocialPilotAI\backend
.\.venv\Scripts\Activate.ps1
pytest --run-qwen-smoke tests\smoke\test_qwen_real.py
```

缺少 `DASHSCOPE_API_KEY` 时测试仍会跳过。该命令会产生一次真实模型调用和相应费用。

## Stage 4 Copy Matrix

商品中心的“生成社媒文案”操作依赖已经保存的 MarketingStrategy。后端一次调用 Qwen，同时生成 TikTok、Instagram 和 Facebook 三个平台内容；不会按平台分别调用模型。

模型返回结果必须满足固定平台集合以及 hook、caption、hashtags、CTA 校验，才能写入 `copy_matrices` 表。普通 pytest 使用 Mock Provider，不会调用百炼。

## Stage 5 Growth Copilot

广告 CSV 必须使用 UTF-8 编码，并包含以下表头：

```csv
platform,campaign_name,date,impressions,clicks,conversions,spend,revenue
TikTok,Launch,2026-07-01,1000,60,6,120.00,360.00
```

系统会先校验完整文件，再一次性写入数据库；任意一行非法时不会写入任何行。指标基于全部数据的总量计算：`CTR = 总点击 / 总曝光`、`CVR = 总转化 / 总点击`、`CPA = 总花费 / 总转化`、`ROAS = 总收入 / 总花费`，不平均单条比例。分母为零时 CTR/CVR 为 0，CPA/ROAS 为 `null`。

Growth Analysis 只把已经计算好的指标和最新 MarketingStrategy 交给共享文本 Provider，用于解释问题和给出建议，不让模型计算指标，也不会自动修改预算。普通 pytest 全部使用 Mock Provider。

## Stage 6 Content Studio

Content Studio 使用 Product、最新 MarketingStrategy 和最新 CopyMatrix 作为来源，一次调用共享 `TextGenerationProvider`，生成标题、创意、分镜、旁白文本和 CTA。结果保存为 `VideoProject`，状态固定为 `planned`。

```json
{
  "platform": "TikTok",
  "duration_seconds": 30,
  "aspect_ratio": "9:16"
}
```

平台字段是可扩展字符串，当前界面默认 TikTok。每个 scene 的 sequence 必须唯一、duration_seconds 必须大于零，全部 scene 时长之和必须等于项目总时长。该阶段不会生成视频文件、URL、音频、字幕、存储记录或万相任务；普通 pytest 使用 Mock Provider。

## Stage 7 Demo Dashboard

首页提供“一键载入 Portable Blender Demo”。Demo 使用 `DemoScenario.slug` 明确标识预置数据来源，不根据商品名称判断，并在一次事务中准备 Product、MarketingStrategy、CopyMatrix、VideoProject、广告 Campaign 和 Growth Recommendation 快照。

Demo 页面会明确显示 `Demo Snapshot`、`0 AI Calls` 和“使用预置演示数据”。Demo 与 Dashboard API 均不依赖 TextGenerationProvider，也不会调用 Strategy、Copy、Video 或 Growth 生成接口。广告指标仍通过 MetricsService 从预置 Campaign 总量计算。

`/demo/prepare` 仅在 `APP_ENVIRONMENT=development` 时可用，重复调用保持幂等。Dashboard 也支持读取普通存量商品；缺少 Strategy、Copy、Video 或 Growth 时会返回 `missing`/`partial` 状态，不会自动调用 AI。

## Stage 8 / C3 Video Render Execution

`VideoProject` 可以创建多个按分镜追踪的 `VideoRenderTask`。创建接口只读取已经校验并保存的分镜，生成确定性的 `render_prompt`，再写入状态为 `CREATED` 的本地任务；同一个 `idempotency_key` 重复请求会返回原任务。

供应商无关的 `VisualGenerationProvider.submit()` 与 `fetch()` 契约由 `WanxProvider` 实现。`VideoRenderExecutionService` 负责一次提交、后续只查询不重复提交、状态转换、安全错误映射，以及成功后创建或更新 `VideoRenderArtifact`。真实 Wanx smoke 必须通过独立 `--run-wanx-smoke` 开关执行，普通 pytest 不会触发外部服务。

前端 AI Video Blueprint 页面通过只读 Artifact API 展示 Verified Wanx Output；没有 Artifact 或读取失败时仍保留原有 Blueprint。Live Render Facade 默认关闭，固定 Scene 1、720P 和服务端幂等键；已有成功 Artifact 或运行中任务时直接返回现有结果，不创建第二个任务，也不自动重试。

## 目录结构

```text
SocialPilotAI/
├── backend/
│   ├── app/
│   │   ├── api/v1/routes/    # v1 API 路由
│   │   ├── core/             # 配置与异常处理
│   │   ├── db/               # 数据库基类、引擎和会话
│   │   ├── models/           # SQLAlchemy 业务与视频渲染模型
│   │   ├── providers/        # Qwen / Wanx Provider 适配层
│   │   ├── repositories/     # 数据访问层
│   │   ├── schemas/          # Pydantic 数据结构
│   │   ├── services/         # 业务、渲染执行与 Live Facade 服务
│   │   └── main.py           # FastAPI 入口
│   ├── tests/
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── api/              # Axios 客户端
│   │   ├── components/       # 通用组件
│   │   ├── layouts/          # 应用布局
│   │   ├── pages/            # 路由页面
│   │   ├── types/            # TypeScript 类型
│   │   ├── App.tsx
│   │   └── styles.css
│   └── package.json
├── docs/architecture.md
├── .gitignore
└── README.md
```

## Windows 启动后端

以下命令在 PowerShell 中执行，要求 Python 3.11 或更高版本：

```powershell
cd D:\SocialPilotAI\backend
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
# 按“Stage 3 百炼配置”一节在本地创建 .env；不要写入真实 Key 到仓库
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

如果 PowerShell 禁止激活脚本，可只为当前窗口临时放开：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

## Windows 启动前端

要求 Node.js 20 或更高版本。新开一个 PowerShell 窗口：

```powershell
cd D:\SocialPilotAI\frontend
npm install
# 如需覆盖 API 地址，在本地创建 .env 并设置 VITE_API_BASE_URL
npm run dev
```

## 运行检查

后端测试与代码检查：

```powershell
cd D:\SocialPilotAI\backend
.\.venv\Scripts\Activate.ps1
pytest
ruff check .
```

前端生产构建：

```powershell
cd D:\SocialPilotAI\frontend
npm run build
```

## 默认地址

- 前端页面：http://localhost:5173
- 后端 API：http://localhost:8000
- health：http://localhost:8000/api/v1/health
- API 文档：http://localhost:8000/docs

前后端需要同时运行，首页才会显示“后端服务正常”。

## Demo展示流程

使用 `http://localhost:5173/?mode=presentation` 进入比赛展示模式：

1. **Overview**：项目定位、Portable Blender商品理解、Marketing Strategy和增长闭环总览。
2. **Copy Matrix**：展示TikTok、Instagram、Facebook三平台差异化内容。
3. **Video Blueprint**：展示结构化Storyboard和既有Verified Wanx Output。
4. **Growth Copilot**：展示CTR、CVR、CPA、ROAS及Performance-driven Optimization建议。

比赛现场推荐保持Live Wanx Feature Flag关闭，使用预生成Artifact或本地`demo_assets/verified_wanx_output.mp4`，不现场重新调用Qwen或Wanx。

## 常见问题排查

### 页面显示“后端服务未连接”

确认后端窗口没有报错，并直接访问 `http://localhost:8000/api/v1/health`。若修改了后端端口，同时更新前端 `.env` 中的 `VITE_API_BASE_URL`，然后重启 Vite。

### 浏览器出现 CORS 错误

默认只允许 `localhost:5173` 和 `127.0.0.1:5173`。如果前端使用其他端口，在后端 `.env` 的 `CORS_ORIGINS` 中添加完整来源并重启后端，例如：

```dotenv
CORS_ORIGINS=http://localhost:5173,http://localhost:5174
```

### 找不到 Python 或版本不正确

运行 `py --list` 查看已安装版本。也可以将文档中的 `py -3.11` 替换为本机可用的 3.11+ 版本。

### 无法激活虚拟环境

执行上文的 `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`，或不激活，直接使用 `.\.venv\Scripts\python.exe` 和 `.\.venv\Scripts\uvicorn.exe`。

### npm 安装或构建失败

先运行 `node --version` 与 `npm --version`；建议 Node.js 20+。删除由失败安装产生的 `node_modules` 后重新运行 `npm install`，并确认当前网络可访问 npm registry。

### 端口被占用

后端可改用 `--port 8001`，同时更新前端 API 地址；前端可运行 `npm run dev -- --port 5174`，同时将新来源加入后端 CORS 配置。

## 安全说明

当前比赛基线不提交 `.env`、`.env.*`、`*.key`、`*.secret`、SQLite 数据库、数据库备份或临时签名 URL。Qwen 与 Wanx 密钥只从后端环境变量或本地 `.env` 读取，禁止写入源码、前端变量或日志。真实 smoke 默认跳过，只有显式 Provider 开关才允许执行。
