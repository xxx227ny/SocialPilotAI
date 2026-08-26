import { Link } from "react-router-dom";

const capabilities = [
  {
    number: "01",
    title: "AI 短视频批量生产",
    summary: "根据商品卖点和目标平台，自动完成脚本、商品画面、配音、字幕与成片。",
    details: ["支持 TikTok、YouTube Shorts、Instagram Reels", "三平台独立生成，失败互不影响", "成片可在线预览并批量下载"],
    action: "进入视频工厂",
    to: "/content-studio",
  },
  {
    number: "02",
    title: "AI 社媒文案矩阵",
    summary: "围绕同一商品，为不同社交平台生成符合平台语气和内容结构的营销文案。",
    details: ["适配 TikTok、Instagram、Facebook、Pinterest", "支持复制、导出和重新生成", "品牌规则与商品卖点贯穿全部文案"],
    action: "进入文案矩阵",
    to: "/copy-matrix",
  },
  {
    number: "03",
    title: "AI 投流策略优化",
    summary: "汇总各渠道投放数据，计算 ROAS 等核心指标，并给出预算和竞价调整建议。",
    details: ["统一查看渠道表现", "识别高效与低效投放", "在安全沙箱中验证优化方案"],
    action: "进入投流优化",
    to: "/growth-copilot",
  },
];

const workflow = [
  { title: "建立商品资料", detail: "在商品中心录入商品名称、卖点、目标市场、品牌规则，并上传清晰商品图。", to: "/products", action: "打开商品中心" },
  { title: "生成内容矩阵", detail: "选择商品和目标平台，使用千问生成各平台文案；确认内容后可复制或导出。", to: "/copy-matrix", action: "开始生成文案" },
  { title: "批量生成视频", detail: "创建批量任务，确认模型调用与费用，让系统依次完成脚本、画面、配音和成片。", to: "/content-studio", action: "开始生成视频" },
  { title: "分析并优化投放", detail: "导入或使用沙箱投放数据，查看 ROAS、CTR、CVR 和 CPA，再应用优化建议。", to: "/growth-copilot", action: "查看投放分析" },
];

export function DashboardPage() {
  return (
    <div className="home-guide">
      <section className="home-guide__hero">
        <div>
          <span className="home-guide__eyebrow">SOCIALPILOT AI 使用指南</span>
          <h1>从一个商品，完成跨平台内容生产与增长优化</h1>
          <p>
            SocialPilot 是面向跨境电商团队的 AI 社媒营销工作台。系统把商品资料、平台文案、
            营销视频和投放反馈串成一条可操作的业务流程，减少在多个工具之间反复切换。
          </p>
          <div className="home-guide__actions">
            <Link className="home-guide__primary" to="/products">开始使用</Link>
            <a href="#usage-guide">查看使用步骤</a>
          </div>
        </div>
        <aside aria-label="产品流程摘要">
          <span>完整营销闭环</span>
          <ol>
            <li><strong>理解商品</strong><small>资料、卖点与品牌规则</small></li>
            <li><strong>生产内容</strong><small>文案、图片、配音与视频</small></li>
            <li><strong>优化增长</strong><small>ROAS 分析与策略建议</small></li>
          </ol>
        </aside>
      </section>

      <section className="home-guide__section" aria-labelledby="product-introduction">
        <header>
          <span>产品说明</span>
          <h2 id="product-introduction">SocialPilot 能帮你做什么？</h2>
          <p>只需准备商品信息和商品图片，系统即可协助完成内容生产、视频制作和投放优化。</p>
        </header>
        <div className="home-guide__summary">
          <article><strong>输入</strong><p>商品资料、商品图片、品牌规则和目标平台。</p></article>
          <article><strong>AI 处理</strong><p>千问负责理解、脚本、文案和配音，万象负责商品视觉与动态视频。</p></article>
          <article><strong>输出</strong><p>平台文案、营销成片、字幕文件、投放建议和可核验记录。</p></article>
        </div>
      </section>

      <section className="home-guide__section" aria-labelledby="product-capabilities">
        <header>
          <span>产品功能</span>
          <h2 id="product-capabilities">围绕比赛三大目标构建</h2>
          <p>每个模块均可单独使用，也可以按照商品 → 文案 → 视频 → 投放的顺序形成完整闭环。</p>
        </header>
        <div className="home-guide__capabilities">
          {capabilities.map((capability) => (
            <article key={capability.number}>
              <span>{capability.number}</span>
              <h3>{capability.title}</h3>
              <p>{capability.summary}</p>
              <ul>{capability.details.map((detail) => <li key={detail}>{detail}</li>)}</ul>
              <Link to={capability.to}>{capability.action}<span aria-hidden="true">→</span></Link>
            </article>
          ))}
        </div>
      </section>

      <section className="home-guide__section home-guide__section--workflow" id="usage-guide" aria-labelledby="usage-guide-title">
        <header>
          <span>使用说明</span>
          <h2 id="usage-guide-title">第一次使用，按这四步操作</h2>
          <p>建议先完成商品与品牌资料，再依次生成文案和视频，最后进入投流优化查看增长建议。</p>
        </header>
        <ol className="home-guide__workflow">
          {workflow.map((step, index) => (
            <li key={step.title}>
              <span>{index + 1}</span>
              <div><h3>{step.title}</h3><p>{step.detail}</p><Link to={step.to}>{step.action}</Link></div>
            </li>
          ))}
        </ol>
      </section>

      <section className="home-guide__tip">
        <div><span>演示建议</span><strong>第一次体验时，先选择一个资料完整且已绑定品牌版本的商品。</strong></div>
        <p>涉及千问、万象或语音模型的操作会先显示预计调用次数与费用，确认后才会正式执行。</p>
      </section>
    </div>
  );
}
