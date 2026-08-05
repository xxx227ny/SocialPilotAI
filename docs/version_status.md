# SocialPilot AI 版本与验收状态

## 当前状态

状态：`V2-L2A Competition Checkpoint Ready`

| Checkpoint | Commit | 说明 |
| --- | --- | --- |
| V2-L1 | `ec34d1d3e1004d6cfc259ac720618f230a3ff4c9` | Qwen与Wanx真实主链基线。 |
| V2-L2A | `cf53573d4890c6809cb84f487fba01c6d40b6fb5` | YouTube账号绑定与Private发布Checkpoint。 |
| 本次文档更新前基线 | `09f7553e4bdcba79ae4393d006ae76416004cc10` | 增加本地数据库、媒体、Artifact与构建产物忽略保护。 |

本文只记录已有代码、测试或受监督真实验收支持的状态，不把计划能力描述为已完成。

## 已完成闭环

```text
Product → Feedback → Qwen → Copy → Wanx → Artifact
        → YouTube OAuth → Private Upload
```

### Product、Feedback与Qwen

- Product、MarketingBrief、MarketingStrategy和CopyMatrix均有持久化来源关系。
- Campaign CSV先完整校验再写入；CTR、CVR、CPA、ROAS由确定性代码计算。
- Qwen真实结构化执行已验证；Strategy、Copy、Video Blueprint和Recommendation输出需通过Schema校验。

### Wanx与Artifact

- Wanx Provider实现异步提交和状态查询。
- RenderTask有幂等保护、明确状态机和精确VideoProject关系。
- 成功输出保存为Artifact，并通过统一元数据/内容API和安全路径解析器读取。
- 比赛上传验收使用独立受控、哈希验证的 Wanx Artifact；V2-L1 Live 主链验收记录独立保留，二者不混同。

### YouTube OAuth

状态：`Real OAuth verified`

- 真实Google OAuth账号绑定已完成。
- 使用PKCE、state摘要、浏览器会话摘要、过期时间和一次性OAuthSession。
- OAuth state不以明文持久化，已消费会话不能重放。
- access token与refresh token使用Fernet加密后保存；凭据不进入前端、文档或日志。
- 同一Product和频道的重新授权更新既有SocialAccount，不创建重复账号。

### YouTube Private Upload

状态：`Real private upload verified`

- 真实YouTube Private上传已完成。
- 发布前执行Provider-free Preflight；检查精确SocialAccount、Artifact、文件和元数据。
- privacy固定为Private；made-for-kids由用户明确选择；AI合成内容披露开启；不通知订阅者。
- 固定幂等键防止双击产生重复PublishTask或逻辑上传。
- 上传前授权失败进入确定性`FAILED`；媒体可能已发送但结果未知时进入`SUBMIT_UNKNOWN`。
- `FAILED`和`SUBMIT_UNKNOWN`不会自动重传，历史任务可从本地只读恢复。

### Presentation Mode

状态：`Preset Snapshot / 0 AI Calls`

- 使用DemoScenario引用的精确Product、Strategy、Copy、VideoProject、RenderTask和Artifact。
- Presentation只读加载既有Artifact并播放，不触发AI或Provider。
- 社交发布区域、生成、任务刷新和上传操作全部隐藏。
- 页面访问与刷新不写数据库。

## 质量门禁

| 检查 | 结果 |
| --- | --- |
| V2-L2A定向pytest | 32 passed |
| 完整pytest | 515 passed, 3 skipped |
| Ruff | passed |
| TypeScript | passed |
| Frontend Social | 20 checks passed |
| Live Wanx frontend | 5 scenarios passed |
| Presentation Artifact | passed |
| Vite production build | passed |
| `git diff --check` | passed |
| 变更文件UTF-8 strict | passed |
| 新增行敏感信息扫描 | 0 findings |

普通pytest与前端门禁不调用真实Google、YouTube、Qwen或Wanx。真实Provider验收通过独立、受监督流程执行。

## 安全状态

- Token采用Fernet加密，密钥仅从后端本机环境读取。
- OAuth使用PKCE、摘要state和一次性会话，防止重放。
- Backend Feature Gate是账号绑定和发布的最终安全边界。
- Preflight不调用Provider、不创建PublishTask、不写业务数据。
- 上传使用幂等键和不确定状态保护，不自动发布或自动重试。
- Presentation保持0 AI Calls且隐藏社交发布区域。
- 本机环境文件、数据库、普通媒体、Artifact、日志、构建和临时文件均受Git忽略规则保护。

## 尚未实现

- Instagram真实账号绑定与发布。
- TikTok真实账号绑定与发布。
- 自动广告投放、自动预算调整和广告平台写操作。
- 根据Growth Recommendation自动生成第二版Copy或VideoProject。
- 不经用户确认的自动发布或自动上传重试。

## 演示真实性边界

- Presentation Snapshot是为稳定演示准备的只读证据，不宣称页面加载时实时调用AI。
- 真实Qwen、Wanx、Google OAuth和YouTube上传分别经过受监督验收。
- 比赛上传验收使用独立受控、哈希验证的 Wanx Artifact；V2-L1 Live 主链验收记录独立保留，二者不混同。
- 文档不记录任何Token、密钥、Provider视频身份、数据库位置或本机临时路径。
