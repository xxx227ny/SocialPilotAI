# Demo Assets

该目录用于保存 SocialPilot AI 初赛演示所需的稳定展示资产。目录中的媒体文件用于比赛录屏、现场演示或在线 Artifact 无法访问时的本地降级，不属于应用运行依赖。

## verified_wanx_output.mp4

`verified_wanx_output.mp4` 是 SocialPilot AI 真实 Wanx 视频生成链路产生并下载保存的验证视频，用于展示 AI Video Blueprint 对应的 Verified Wanx Output。

已核验的视频参数：

- 容器格式：MP4
- 视频编码：H.264
- 时长：3 秒
- 分辨率：720 × 1280
- 画幅比例：9:16
- 帧率：30 fps
- 文件大小：1,947,573 bytes

该文件是预生成的比赛展示资产，不会在应用启动、页面访问或默认测试过程中触发 Qwen、Wanx、RenderTask、submit 或 refresh。删除该文件不会影响 Backend API、Frontend 构建或核心业务流程，但会失去比赛现场的本地视频降级选项。

本目录不得保存 API Key、Token、Authorization Header、Workspace 敏感信息、供应商完整响应或临时签名 URL。
