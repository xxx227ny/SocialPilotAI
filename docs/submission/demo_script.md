# SocialPilot AI 三分钟比赛 Demo 脚本

## 演示前准备

- 从`D:\SocialPilotAI\backend`启动后端，从`D:\SocialPilotAI\frontend`启动前端。
- 打开Presentation Mode，确认`/api/v1/health`和Demo Snapshot正常。
- Live Wanx Feature Flag保持关闭，整段演示使用预置Snapshot和既有Artifact。
- 预先确认Verified Wanx Output可播放，并准备本地`demo_assets/verified_wanx_output.mp4`作为主视频或断网备用。
- 不进入Product Center生成按钮，不执行任何真实AI调用。

## 0:00–0:20｜产品介绍

**画面**：Overview / Presentation Mode。

**讲解**：

“SocialPilot AI是一款面向跨境电商商家的AI社媒增长助手。它把商品理解、营销策略、多平台内容、视频生产和广告优化组织成一条可追踪的工作流。”

强调页面顶部的`Demo Snapshot`与`0 AI Calls`，说明现场展示读取稳定预置数据，真实Provider链路已经独立验证。

## 0:20–0:45｜商品输入与理解

**画面**：Overview中的Portable Blender商品信息。

**讲解**：

“系统从商品名称、品类、描述、核心卖点和目标市场出发。当前Demo商品是便携搅拌杯，重点卖点包括便携、USB充电和易清洁。”

说明本段展示已保存商品数据，不现场创建或修改商品。

## 0:45–1:10｜AI Marketing Strategy

**画面**：Overview中的定位、受众和营销主线。

**讲解**：

“Qwen把商品资料转换为结构化Marketing Strategy，包括市场定位、受众洞察、营销角度、风险和商品依据。模型负责理解，Schema负责验证，只有合法结构才能保存。”

## 1:10–1:35｜Copy Matrix

**画面**：Copy Matrix页面。

**讲解**：

“同一商品策略被Qwen一次适配为TikTok、Instagram、Facebook和Pinterest四种表达。TikTok强调Hook和UGC节奏，Instagram强调Lifestyle与视觉，Facebook强调功能价值和购买理由，Pinterest强调搜索关键词、实用灵感与收藏意图。”

指出每个平台均有Hook、Caption、Hashtags和CTA。

## 1:35–2:05｜AI Video Blueprint

**画面**：AI Video Blueprint页面的Hero与Storyboard。

**讲解**：

“Content Studio把Product、Strategy和Copy组合成结构化视频蓝图。每个Scene包含时长、镜头类型、视觉描述、动作和旁白，系统还校验Scene顺序和总时长。”

强调Blueprint与真实视频渲染解耦，策划失败不会创建外部视频任务。

## 2:05–2:30｜Verified Wanx Output

**画面**：优先播放本地`verified_wanx_output.mp4`；如线上Artifact仍有效，也可展示页面中的Verified Wanx Output。

**讲解**：

“这不是概念占位视频。系统已通过Wanx真实异步任务完成一次submit、状态轮询和Artifact创建。这里展示的是提前生成并验证的三秒、720×1280、9:16 H.264 MP4，现场不重新调用Wanx。”

不要点击Live生成按钮，不宣称无限实时生成。

## 2:30–2:55｜Growth Copilot

**画面**：Growth Copilot页面。

**讲解**：

“系统先用确定性代码计算CTR、CVR、CPA和ROAS，再结合营销策略生成问题、预算和素材优化建议。它把表现数据转化为下一轮内容方向，而不是让模型重新计算指标。”

明确当前版本尚未自动生成第二版Copy或VideoProject。

## 2:55–3:00｜收束

**讲解**：

“SocialPilot AI的价值，是让商品理解、内容生产、真实视频生成和增长反馈拥有统一、可验证的数据链，同时通过Provider隔离和稳定Snapshot控制现场风险。”

## 现场降级顺序

1. 线上视频不可用：直接播放本地MP4。
2. Artifact API失败：继续展示Video Blueprint与本地MP4。
3. 后端暂时不可用：使用已准备的截图或演示材料；当前仓库尚未完成截图材料，应在后续阶段补齐。
4. 不通过开启Live生成功能解决现场故障，避免额外费用和等待风险。
