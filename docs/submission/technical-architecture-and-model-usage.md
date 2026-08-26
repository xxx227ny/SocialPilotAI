# SocialPilot AI 技术架构与模型调用说明

**复赛提交版｜2026 年 8 月**

本文说明 SocialPilot AI 的系统架构、三个核心目标的数据流、阿里云千问与万象模型的调用方式，以及模型调用的费用、安全和可恢复性设计。

> 设计原则：AI 负责理解与生成，确定性代码负责身份、状态、指标、约束、幂等、存储和执行边界。模型输出必须通过结构校验后才能进入业务流程。

## 1. 总体架构

SocialPilot AI 采用模块化单体架构，前端与后端分离，后台任务和媒体处理独立运行。

```text
React + TypeScript + Vite 网页
                ↓ REST / Cookie Session
FastAPI API + Pydantic Schema
                ↓
业务服务 / Preflight / 状态机 / 幂等控制
                ↓
ExecutionJob + ExecutionAttempt + Worker
       ↙                 ↓                 ↘
SQLAlchemy + SQLite   阿里云模型 Provider   FFmpeg / Artifact Storage
```

核心组件：

- **前端**：React、TypeScript、Vite、React Router、Axios。
- **API 层**：FastAPI 路由与 Pydantic 请求/响应模型。
- **业务层**：前置检查、费用确认、状态机、版本与来源冻结、恢复逻辑。
- **执行层**：`ExecutionJob`、`ExecutionAttempt`、Worker 和 Job Type Registry。
- **数据层**：SQLAlchemy、SQLite、Alembic；当前生产迁移头为 `0021_product_video_production_batches`。
- **模型层**：千问文本、万象图片、HappyHorse 商品动态视频、千问云配音，以及 `wan2.7-t2v` 备用视频链。
- **媒体层**：FFmpeg/FFprobe、本地 Artifact 存储、HTTP Range/HEAD/下载接口。
- **访问控制**：管理员配置的复赛测试账号、PBKDF2-SHA256 密码哈希和签名会话 Cookie。

## 2. 分层职责

| 层级 | 主要职责 | 不承担的职责 |
| --- | --- | --- |
| 网页 | 收集输入、展示前置检查、费用确认、进度、结果和安全错误 | 不保存 API Key，不直接调用模型 |
| API / Schema | 参数校验、身份校验、统一安全响应 | 不把供应商原始响应暴露给浏览器 |
| Service | 构造冻结输入、业务约束、状态转换、幂等和结果关联 | 不依赖模糊“最新记录” |
| Worker / Handler | 领取任务、调用一次 Provider、写入成功或失败事实 | 不在不确定提交后自动重试 |
| Provider | 适配端点、认证、请求体和供应商状态 | 不决定业务对象关系 |
| 数据与媒体 | 保存业务记录、版本、Artifact 和内容指纹 | 不把密钥或临时签名地址写入 Git |

## 3. 模型与组件使用说明

| 业务能力 | 模型或组件 | 主要输入 | 主要输出 | 调用边界 |
| --- | --- | --- | --- | --- |
| 商品理解、营销策略、视频脚本、文案矩阵、投流建议 | 千问文本模型；比赛配置推荐 `qwen3.7-plus` | 商品、品牌规范、平台、指标和冻结来源 | 结构化 JSON | OpenAI 兼容 `/chat/completions`；Schema 校验后保存 |
| 商品广告画面 | 万象图片 `wan2.7-image-pro` | 商品参考图、分镜描述、视觉约束 | 分镜商品图 | 每个分镜独立 Job；成功后保存为 ProductAsset |
| 商品动态视频 | `happyhorse-1.1-r2v` | 多张商品参考图、商品动作与镜头说明 | 动态商品视频 | 异步提交与查询分离；不确定提交不重复 |
| 通用视频备用链 | 万象 `wan2.7-t2v` | 结构化视频项目与 Prompt | 视频任务与 Artifact | 用于通用文生视频，不是三平台批量链的默认动态商品路径 |
| 云配音 | `qwen-audio-3.0-tts-plus` | 旁白、声音、语言和目标时长 | WAV 音频 | 旁白冻结到时间线；失败按明确/限流/不确定分类 |
| 合成与质量检查 | FFmpeg / FFprobe | 画面、旁白、音乐、字幕 | 竖屏 MP4、WebVTT、媒体 QA | 本地执行，不产生云模型费用 |
| 广告指标与预算分配 | 确定性 Python 代码 | Campaign CSV、策略参数 | CTR/CVR/CPA/ROAS、预算与竞价动作 | 不让大模型重新计算基础指标 |

### 3.1 千问文本调用

后端通过内部 `TextGenerationProvider` 契约调用千问。业务服务构造包含商品、平台、品牌规范和来源编号的 Prompt；Provider 返回文本后，系统执行 JSON 解析、字段清理和 Pydantic Schema 校验。平台缺失、重复、额外字段或非法结构会失败且不写入业务结果。

文案矩阵的一次 Provider 调用返回 TikTok、Instagram、Facebook、Pinterest 四个平台的完整结构，不按平台重复调用。视频批量链则按三个视频平台分别生成脚本，以便每个平台拥有独立节奏和卖点表达。

### 3.2 万象图片调用

每个脚本分镜使用冻结的商品参考图和分镜描述生成商品广告画面。任务成功后，系统下载并验证媒体，将结果保存为带 SHA-256 和存储身份的 `ProductAsset`。后续视频阶段只使用这些明确素材编号。

### 3.3 HappyHorse 商品动态视频

三平台批量链默认使用 `happyhorse-1.1-r2v`，将多张参考画面生成具有真实动作和镜头变化的商品视频，避免仅用静态照片轮播冒充动态展示。Provider 提交和状态查询是两个独立操作；查询只读取原任务，不会再次提交。

### 3.4 千问云配音

脚本旁白交给 `qwen-audio-3.0-tts-plus`。系统保存旁白摘要、语音配置和目标时长，并根据实际音频生成字幕时间线。旁白过长会安全停止，不会直接裁断；限流失败可只恢复失败平台；可能已提交但结果未知时必须由用户确认后才能创建替代任务。

### 3.5 运行时密钥配置

系统支持 `token-plan` 与 `legacy` 两个 Provider 配置档。比赛 Token Plan 使用专属 Key 和专属基地址；旧百炼 Key 可作为故障诊断或兼容档。切换通过仓库外环境配置和启动参数完成，不需要修改业务代码。

所有密钥只从后端进程环境、被忽略的本机环境文件或安全密钥文件读取。前端、数据库、日志、截图、提交文档和 Git 均不保存明文 Key。

## 4. 目标一技术链路：三平台视频批量生产

```text
Product + BrandKitVersion + ProductAsset
        ↓
BatchVideoJob → TikTok / YouTube Shorts / Instagram Reels Variants
        ↓
Qwen Script Jobs → Immutable VideoScriptVersion / SceneVersion
        ↓
Wanx Image Jobs → Scene ProductAssets
        ↓
HappyHorse Reference-to-Video Task
        ↓
VideoProject → Composition
        ↓
Qwen TTS → Voiceover
        ↓
Subtitle Timeline + Music + Ducking + FFmpeg Enhancement
        ↓
MP4 Artifact + WebVTT Artifact + Batch ZIP
```

关键设计：

- Variant、ScriptVersion、Scene、ProductAsset、VideoProject、Artifact 均按明确编号关联。
- 脚本版本不可变；重新生成会创建新版本，不覆盖历史。
- 每个平台拥有独立生产 Item 和状态，支持部分成功与精确恢复。
- 批次前置检查冻结调用次数、费用区间、商品图摘要和脚本来源。
- 成片通过后端内容接口提供 GET、HEAD、Range 和下载，浏览器不直接读取供应商临时地址。
- 批量下载 ZIP 包含成功 MP4、WebVTT 和结果清单；部分成功时也能交付已有结果。

## 5. 目标二技术链路：四平台文案矩阵

```text
Product + BrandKitVersion
        ↓
MarketingBrief
        ↓
Qwen MarketingStrategy Job
        ↓
Copy Preflight + Cost Confirmation
        ↓
Qwen CopyMatrix Job
        ↓
TikTok / Instagram / Facebook / Pinterest
        ↓
Copy / Export JSON / Export CSV / Regenerate
```

关键设计：

- 商品、营销任务和策略身份在 Preflight 与执行之间再次校验。
- 文案结果只接受四个平台的完整且唯一结构。
- `max_attempts=1`，同一幂等输入只能创建一个执行任务。
- 重新生成使用新的 regeneration key，保留旧矩阵和来源关系。
- 浏览器导出使用安全 Blob URL，完成后主动释放，不暴露本机文件路径。

## 6. 目标三技术链路：ROAS 优化沙箱

```text
Campaign CSV
     ↓
Validation + Metrics Engine
     ↓
FeedbackContext Digest
     ↓
Qwen Growth Recommendation
     ↓
Deterministic Budget Optimizer
     ↓
Active GrowthOptimizationRun
     ↓
Sandbox Execution / Monitor / Emergency Stop / Rollback
```

指标公式：

- `CTR = 点击 ÷ 曝光`
- `CVR = 转化 ÷ 点击`
- `CPA = 花费 ÷ 转化`
- `ROAS = 收入 ÷ 花费`

Metrics Engine 先汇总分子和分母再计算比例，不对各行比例做简单平均。千问只解释已计算指标并给出建议；预算守恒、最低平台份额、目标 ROAS 和最大竞价调整幅度由确定性优化器执行。

沙箱执行记录固定为 `execution_mode=SANDBOX`、`provider_name=sandbox_ad_adapter`、`external_mutation_performed=false`。因此它能证明方案生成、约束、监控和回滚流程，但不会修改真实广告账户。

## 7. 状态机、幂等与费用控制

### 7.1 前置检查

真实调用前，Preflight 检查功能开关、Provider 配置、业务对象身份、素材摘要、配额、预计调用次数和费用。Preflight 不调用模型，也不创建最终业务结果。

### 7.2 用户确认

付费调用需要用户显式勾选确认。确认值与冻结 Preflight 不一致、已过期或业务输入变化时，执行请求会被拒绝。

### 7.3 执行事实

`ExecutionJob` 保存 Job Type、输入摘要、来源、幂等键、状态、结果实体编号和 Provider 身份；`ExecutionAttempt` 保存单次尝试、Provider 调用次数和提交状态。

常见提交状态包括：

- `NOT_SUBMITTED`：明确未提交；允许在新 Preflight 下安全处理。
- `RESPONSE_RECEIVED`：已收到 Provider 响应，可按响应结果收敛。
- `EXPLICIT_FAILURE`：Provider 明确拒绝或失败。
- `SUBMIT_UNKNOWN`：请求可能已被供应商接收，但本地未得到确定结果；禁止自动重试。

### 7.4 精确恢复

页面刷新只读取已有 Job、Batch、Variant 和 Artifact。相同幂等键与相同输入会恢复原对象；相同键但不同输入返回冲突。系统不通过“最近一条记录”猜测结果。

## 8. 数据与媒体安全

- 数据库迁移由 Alembic 管理；生产启动前检查 Schema 状态和指纹。
- 商品素材和视频 Artifact 使用受控存储根、相对存储身份、大小和 SHA-256。
- 媒体读取拒绝路径穿越、目录、越界符号链接、不支持类型和身份不一致。
- MP4/WebVTT 内容接口支持浏览器播放所需的 Range、HEAD、Content-Length 和 MIME 类型。
- API Key、Authorization Header、完整供应商请求/响应和临时签名 URL 不进入前端或 Git。
- Provider 错误被映射为安全类别；页面显示可操作原因，不回显密钥或原始响应。

## 9. 登录与会话安全

- 测试账号由管理员在仓库外配置。
- 密码以 PBKDF2-SHA256 哈希保存，不在配置中保存明文。
- 登录成功后使用签名、`HttpOnly`、`SameSite=strict` Cookie。
- 除健康检查和登录会话接口外，业务 API 均受认证保护。
- HTTPS 部署时启用 Secure Cookie；本机 HTTP 验收使用开发配置。

## 10. 部署结构

本机 Demo 使用前后端独立进程：Vite 提供网页，Uvicorn 运行 FastAPI，SQLite 和 Artifact 位于仓库外 Runtime 目录。公网部署建议采用：

```text
HTTPS 域名 / 反向代理
        ↓
Frontend 静态资源 + FastAPI
        ↓
Worker + SQLite（演示）或托管数据库（扩展）
        ↓
持久化 Artifact 目录或对象存储
```

公网部署必须补充 HTTPS、Secure Cookie、域名白名单、持久化卷、进程守护、备份和密钥托管。当前本机验收地址不等同于公网体验地址。

## 11. 质量验证与证据

项目采用分层测试：

- Backend 单元、API、迁移、并发、幂等、Worker 和媒体测试。
- Frontend 产品状态行为测试、静态安全断言、TypeScript 和 Vite 构建。
- Provider-free 隔离 Smoke 验证业务链，不消耗真实额度。
- 真实 Provider Smoke 在明确授权、单次调用和独立证据目录下运行。
- 浏览器实操验收检查登录、中文页面、文案复制/导出、视频播放/下载和 ROAS 沙箱。

当前三个核心闭环均具备网页入口与可运行实现；目标一已完成三平台本地成片验收，目标二网页闭环已完成，目标三完成 ROAS 沙箱闭环。

## 12. 当前边界与后续扩展

- 广告优化执行目前是安全沙箱，未接入真实广告平台预算与竞价 API。
- 正式公网体验地址尚待部署。
- 第三方模型可能受额度、限流、内容审核和任务排队影响；系统只保证安全保存与恢复本地事实，不承诺供应商永远可用。
- 规模扩大后，可将 SQLite、后台任务和媒体分别迁移至托管数据库、独立队列和对象存储；现有边界可复用。
