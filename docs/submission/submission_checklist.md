# SocialPilot AI 初赛提交检查清单

> 本文件保留初赛检查记录。复赛最终状态与待办请查看
> `docs/submission/final-submission-guide.md` 第 7 节。

## 1. 核心文档

- [x] README存在
- [x] README已按当前HEAD在本地同步
- [x] Architecture文档存在
- [x] Architecture已补充Qwen、Wanx、Execution Pipeline和Artifact
- [x] Current Status文档已更新为Competition Demo Ready
- [x] Performance-to-Prompt未实现边界已明确
- [ ] S2文档变更尚未建立Git checkpoint

## 2. Demo Video

- [x] 已保存真实Wanx MP4：`demo_assets/verified_wanx_output.mp4`
- [x] 已验证H.264、3秒、720×1280、9:16、30fps
- [x] 已记录SHA-256
- [ ] `demo_assets/`和`*.mp4`当前没有Git ignore或明确提交策略
- [ ] 尚未完成人工视觉播放确认
- [ ] 当前Frontend仍读取Artifact临时URL，没有自动改用本地MP4

## 3. Screenshots

- [ ] Dashboard截图
- [ ] Copy Matrix截图
- [ ] AI Video Blueprint截图
- [ ] Verified Wanx Output截图
- [ ] Growth Copilot截图
- [ ] Presentation Mode全流程截图

当前仓库未发现正式比赛截图。

## 4. PPT / PDF

- [ ] 比赛演示PPT
- [ ] 技术方案PDF
- [ ] 架构图导出文件
- [ ] 提交附件ZIP

当前仓库未发现PPT、PDF或ZIP。

## 5. GitHub

- [ ] 尚未创建或配置GitHub remote
- [x] 当前产品代码基线：`9e2312400c215f2cc130ad8c3a536dfe49bc2e42`
- [x] `.env`、SQLite数据库、备份和`dist`已被忽略
- [ ] 未跟踪Raw API诊断脚本必须排除
- [ ] Demo MP4的仓库归档策略待确认
- [ ] 公开前确认Git作者邮箱隐私
- [ ] 禁止无筛选执行`git add .`

## 6. API Evidence

- [x] Qwen真实验证报告：`docs/qwen_verification.md`
- [x] Qwen真实smoke代码
- [x] Wanx真实smoke代码
- [x] 本地数据库存在Wanx成功Task和Artifact证据
- [ ] 独立Wanx验证Markdown报告
- [ ] 可提交的脱敏Wanx测试日志或结果摘要
- [ ] 当前默认pytest报告文件

## 7. Quality Gate

- [x] 最近S0默认pytest：84 passed，2 skipped，1 warning
- [x] 最近S0 Ruff：All checks passed
- [x] 最近S0 TypeScript与Vite production build：通过
- [x] 真实Qwen/Wanx smoke默认skip
- [ ] 最终提交前重新执行一次默认质量门禁

## 8. Limitations

- [x] Performance-to-Prompt未实现
- [x] 自动第二版Copy/VideoProject未实现
- [x] 创意版本追踪未实现
- [x] 长期视频对象存储未实现
- [x] 当前Artifact URL可能过期
- [x] Live Wanx Demo默认关闭且当前成功Artifact会触发复用
- [x] 不支持自动投放或自动预算调整
- [x] Demo Snapshot不代表实时AI结果或真实广告归因

## 9. 提交前阻塞项

1. 确定本地MP4的提交、附件或ignore策略。
2. 补齐比赛截图和PPT/PDF材料。
3. 创建脱敏Wanx验证报告。
4. 复核README、Architecture、Capability Matrix与表单表述一致。
5. 完成最终Git安全扫描和选择性checkpoint。
