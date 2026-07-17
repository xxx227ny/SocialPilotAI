# SocialPilot AI

SocialPilot AI 是面向跨境电商商家的 AI 社媒营销增长平台。项目围绕商品资料、营销分析、内容生产、投放分析与优化建议形成闭环，覆盖 AI 短视频批量生产、AI 社媒文案矩阵和 AI 投流策略优化三个方向。

当前稳定基线为 `C1 Baseline`。项目已完成模块化单体 Demo、Stage 9.4-A Presentation Flow 和零 AI 调用的预置 Demo Snapshot。Qwen Provider 已实现，但仓库内尚无可独立核验的真实成功调用证据；Wanx 尚未实现，仅有视频渲染任务与视觉 Provider 抽象占位；Performance-to-Prompt、内容二次生成和创意版本追踪尚未实现。完整状态见 [docs/version_status.md](docs/version_status.md)。

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

> 真实性边界：Demo Snapshot 使用预置 fixture，展示期间为 `0 AI Calls`；它不是实时 AI 生成结果。Qwen 的实现状态、Wanx 占位状态和增长闭环缺口以 `docs/version_status.md` 为准。

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
| `GET` | `/api/v1/dashboard/products/{id}` | 读取商品完整营销闭环，不调用 AI |
| `POST` | `/api/v1/video-projects/{id}/render-tasks` | 只创建本地 `CREATED` 视频渲染任务，不调用外部服务 |
| `GET` | `/api/v1/video-render-tasks/{id}` | 查询本地视频渲染任务状态 |

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

## Stage 8.1 VideoRenderTask 基础设施

`VideoProject` 可以创建多个按分镜追踪的 `VideoRenderTask`。创建接口只读取已经校验并保存的分镜，生成确定性的 `render_prompt`，再写入状态为 `CREATED` 的本地任务；同一个 `idempotency_key` 重复请求会返回原任务。

当前仅定义供应商无关的 `VisualGenerationProvider.submit()` 与 `fetch()` 契约，没有具体 Provider、视频 API、外部 SDK、视频文件或结果 URL，也不会产生外部调用和费用。未来接入视频模型时，由独立渲染执行器消费 `CREATED` 任务，不需要改变 Content Studio 的策划生成链路。

## 目录结构

```text
SocialPilotAI/
├── backend/
│   ├── app/
│   │   ├── api/v1/routes/    # v1 API 路由
│   │   ├── core/             # 配置与异常处理
│   │   ├── db/               # 数据库基类、引擎和会话
│   │   ├── models/           # SQLAlchemy 模型（预留）
│   │   ├── repositories/     # 数据访问层（预留）
│   │   ├── schemas/          # Pydantic 数据结构
│   │   ├── services/         # 业务服务层（预留）
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

C1 基线不提交 `.env`、`.env.*`、`*.key` 或 `*.secret`；本机已有环境模板也会被忽略。后续接入模型或外部平台时，密钥必须从环境变量或密钥管理服务读取，禁止写入源码。
