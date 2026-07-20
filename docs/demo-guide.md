# SocialPilot AI 比赛 Demo 指南

## 1. 推荐展示模式

比赛截图和录屏统一使用Presentation Mode：

```text
http://localhost:5173/?mode=presentation
```

进入后会隐藏Workspace Sidebar和普通Topbar，显示固定的Demo Journey导航。按`ESC`或点击“退出演示”可返回Workspace。

## 2. 启动前检查

### Backend

```powershell
cd D:\SocialPilotAI\backend
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

检查：

- `http://localhost:8000/api/v1/health`
- `http://localhost:8000/docs`
- `GET /api/v1/demo/snapshot`

必须从`backend`目录启动，以正确读取本地`.env`和SQLite数据库。不要在演示前执行真实smoke。

### Frontend

```powershell
cd D:\SocialPilotAI\frontend
npm run dev
```

默认访问`http://localhost:5173`。Backend CORS默认允许localhost和127.0.0.1的5173端口；不要临时改用未配置的端口。

## 3. Demo数据检查

- DemoScenario slug：`portable-blender-growth-loop`
- Demo source：`preset_fixture`
- Demo页面：`0 AI Calls`
- VideoProject ID：2
- 成功Wanx Artifact：存在
- 本地备用视频：`demo_assets/verified_wanx_output.mp4`

Presentation页面读取既有Snapshot，不现场生成Strategy、Copy、VideoProject或Growth分析。

## 4. 三分钟展示流程

### 0:00–0:30｜Overview

- 介绍SocialPilot AI和跨境电商内容痛点。
- 展示Portable Blender商品卖点、目标市场和Marketing Strategy。
- 指出`Demo Snapshot / 0 AI Calls`，说明现场数据稳定、真实Provider独立验证。

### 0:30–1:10｜Copy Matrix

- 依次展示TikTok、Instagram和Facebook。
- 对比Hook、Caption、Hashtags、CTA与平台适配逻辑。
- 强调同一Marketing Strategy是三平台内容的共同来源。

### 1:10–2:05｜Video Blueprint与Wanx

- 展示视频主题、画幅、时长和Storyboard。
- 说明Scene包含镜头、视觉描述、动作与旁白。
- 展示Verified Wanx Output或直接播放本地MP4。
- 说明真实链路为Task submit、polling、Artifact，不现场重新调用Wanx。

### 2:05–2:50｜Growth Copilot

- 展示CTR、CVR、CPA、ROAS。
- 展示高表现平台和优化建议。
- 明确当前只生成下一轮方向，不自动生成第二版内容。

### 2:50–3:00｜总结

总结商品理解、多平台内容、真实视频生成和增长建议的统一数据链，以及Provider隔离和稳定Demo设计。

## 5. 视频展示策略

优先使用本地`verified_wanx_output.mp4`进行录屏或现场播放。Frontend中的Artifact播放器仍依赖供应商URL，签名地址可能过期，因此只作为在线展示选项。

不要为解决播放问题临时开启Live Wanx，也不要现场执行submit或refresh。

## 6. 截图建议

- 使用1440×900或1600×900以上窗口，浏览器缩放100%。
- 每张截图保留顶部Demo Journey和当前步骤高亮。
- 建议准备Overview首屏、Copy三平台、Video Storyboard、Verified Output和Growth结果截图。
- 视频截图前确认首帧、播放控件和本地备用文件。

## 7. 降级顺序

1. 在线视频不可用：播放本地MP4。
2. Artifact API失败：保留Video Blueprint并单独播放MP4。
3. Backend暂时不可用：使用预先准备的截图与录屏。
4. 不通过真实AI调用补救现场问题。
