# SocialPilot AI 能力矩阵

| Capability | Status | Evidence |
|---|---|---|
| AI Marketing Strategy | 已完成 | `backend/app/providers/qwen_provider.py`、`backend/app/services/marketing_strategy_service.py`、`backend/tests/test_strategy_service.py`、`docs/qwen_verification.md` |
| Copy Generation | 已完成 | `backend/app/services/copy_generation_service.py`、`backend/app/api/v1/routes/copies.py`、`backend/tests/test_copy_service.py`；一次Qwen调用支持TikTok、Instagram、Facebook、Pinterest完整矩阵 |
| Video Blueprint | 已完成 | `backend/app/services/content_studio_service.py`、`backend/app/schemas/video.py`、`frontend/src/pages/ContentStudioPage.tsx`、Content Studio测试 |
| Wanx Generation | 已完成 | `backend/app/providers/wanx_provider.py`、`backend/app/services/video_render_execution_service.py`、`backend/tests/smoke/test_wanx_real.py`、成功VideoRenderArtifact |
| Artifact Read & Verified Output | 已完成 | `GET /api/v1/video-projects/{id}/render-artifacts`、`frontend/src/components/video/VerifiedWanxOutput.tsx`、Artifact API测试 |
| Growth Analysis | 已完成 | `backend/app/services/metrics_service.py`、`backend/app/services/growth_analysis_service.py`、`frontend/src/pages/GrowthCopilotPage.tsx`、Growth测试 |
| Presentation Mode | 已完成 | `frontend/src/context/PresentationModeContext.tsx`、`frontend/src/components/showcase/PresentationFlowNav.tsx` |
| Live Wanx Facade | 部分完成 | Backend/Frontend与Mock测试已完成，默认关闭；当前Demo已有成功Artifact时会直接复用，不会再次submit |
| Performance-to-Prompt | 未完成 | GrowthRecommendation未注入Copy或Video生成Prompt，没有闭环Service或测试 |
| 自动第二版内容生成 | 未完成 | 没有第二版CopyMatrix/VideoProject自动编排，也没有创意父子版本关系 |

## 能力表述边界

- 可以表述为“支持真实Wanx视频生成流程，并保存生成结果用于展示”。
- 不应表述为“实时无限生成视频”或“批量自动生成视频”。
- 可以表述为“根据广告表现生成优化建议”。
- 不应表述为“已实现Performance-to-Prompt”或“自动生成第二版内容”。
- Demo Snapshot是预置fixture，Presentation Mode页面访问为`0 AI Calls`；真实Provider能力由独立验证链证明。
