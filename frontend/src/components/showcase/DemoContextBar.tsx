export function DemoContextBar() {
  return (
    <aside className="demo-context-bar" aria-label="演示数据说明">
      <div><strong>Demo Snapshot</strong><span>0 AI Calls</span><span>Preset Scenario</span></div>
      <p>Based on Portable Blender Growth Loop</p>
      <ol aria-label="SocialPilot AI 增长叙事">
        <li><small>Understand</small><strong>商品理解</strong></li>
        <li aria-hidden="true">→</li>
        <li><small>Create</small><strong>内容生产</strong></li>
        <li aria-hidden="true">→</li>
        <li><small>Optimize</small><strong>增长反馈</strong></li>
      </ol>
    </aside>
  );
}
