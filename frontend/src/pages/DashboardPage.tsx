import { useEffect, useState } from "react";

import { getDemoSnapshot } from "../api/dashboard";
import portableBlenderVisual from "../assets/portable-blender.svg";
import { usePresentationMode } from "../context/PresentationModeContext";
import type {
  DashboardSnapshot,
  PipelineStatus,
  PlatformMetrics,
} from "../types/dashboard";

export function DashboardPage() {
  const { isPresentation } = usePresentationMode();
  const [snapshot, setSnapshot] = useState<DashboardSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState("");

  useEffect(() => {
    void getDemoSnapshot()
      .then((result) => {
        setSnapshot(result);
        setMessage("");
      })
      .catch(() => {
        setMessage("Demo Snapshot 尚未准备，请在比赛前完成预置数据准备。");
      })
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className={`showcase-dashboard${isPresentation ? " showcase-dashboard--presentation" : ""}`}>
      <ShowcaseHero snapshot={snapshot} />
      {loading ? (
        <ShowcaseState title="正在读取演示快照" detail="只读取预置数据，不触发任何生成流程。" />
      ) : snapshot ? (
        <SnapshotShowcase snapshot={snapshot} />
      ) : (
        <ShowcaseState title="演示快照未就绪" detail={message} error />
      )}
    </div>
  );
}

function ShowcaseHero({ snapshot }: { snapshot: DashboardSnapshot | null }) {
  return (
    <section className="showcase-hero">
      <div className="showcase-hero__brand">
        <span className="showcase-hero__mark">S</span>
        <div>
          <small>ALIBABA CLOUD AI HACKATHON</small>
          <h1>SocialPilot AI</h1>
          <p>AI 驱动跨境电商社媒增长闭环</p>
        </div>
      </div>
      <div className="showcase-trust">
        <span>{snapshot?.demo?.badge ?? "Demo Snapshot"}</span>
        <strong>{snapshot?.demo?.ai_calls ?? 0} AI Calls</strong>
        <span>{snapshot?.demo?.notice ?? "使用预置演示数据"}</span>
        <p>现场展示使用预置快照，真实 AI 链路已独立验证。</p>
      </div>
    </section>
  );
}

function SnapshotShowcase({ snapshot }: { snapshot: DashboardSnapshot }) {
  const metrics = snapshot.growth.metrics;
  return (
    <div className="showcase-content">
      <ProductStory snapshot={snapshot} />
      <ProductScenarios />
      <MarketingValueStory />
      <BusinessFlow snapshot={snapshot} />
      <section className="showcase-outcomes" aria-label="核心结果">
        <OutcomeCard
          eyebrow="CONTENT MATRIX"
          value={String(snapshot.copy_matrix?.copies.length ?? 0)}
          unit="个平台"
          label="差异化社媒内容"
        />
        <OutcomeCard
          eyebrow="VIDEO PLAN"
          value={String(snapshot.video_project?.duration_seconds ?? 0)}
          unit="秒"
          label="结构化视频生产方案"
        />
        <OutcomeCard
          eyebrow="GROWTH RESULT"
          value={metrics?.roas == null ? "—" : metrics.roas.toFixed(2)}
          unit="x ROAS"
          label="基于预置投放快照"
          accent
        />
      </section>
      <GrowthShowcase snapshot={snapshot} />
    </div>
  );
}

function ProductStory({ snapshot }: { snapshot: DashboardSnapshot }) {
  return (
    <section className="product-story">
      <div className="product-story__visual">
        <div className="product-story__visual-glow" aria-hidden="true" />
        <img src={portableBlenderVisual} alt="便携搅拌杯概念视觉，不代表真实商品照片" />
        <span>DEMO CONCEPT VISUAL</span>
      </div>
      <div className="product-story__copy">
        <span>DEMO PRODUCT · PORTABLE BLENDER</span>
        <h2>{snapshot.product.name.replace(" Demo", "")}</h2>
        <blockquote>面向高流动生活方式的随身鲜饮工具</blockquote>
        <p>{snapshot.product.description}</p>
        <div className="product-story__markets">
          <small>目标市场</small>
          {snapshot.product.target_markets.map((market) => <strong key={market}>{market}</strong>)}
        </div>
      </div>
      <div className="product-story__details">
        <StoryList title="商品卖点" items={snapshot.product.selling_points} />
        <div className="product-story__promise">
          <strong>商品理解</strong>
          <p>从便携设计、充电方式与使用门槛出发，连接用户场景与平台表达。</p>
          <span>Product insight → Content direction</span>
        </div>
      </div>
    </section>
  );
}

function ProductScenarios() {
  const scenarios = [
    { number: "01", name: "Morning Rush", title: "忙碌早晨", description: "用更短的准备时间，把随身鲜饮带进通勤节奏。", keywords: ["快速准备", "便携", "健康生活"] },
    { number: "02", name: "Desk Blend", title: "办公室场景", description: "无需大型设备，在办公桌边也能随时制作新鲜饮品。", keywords: ["轻量设备", "随时制作"] },
    { number: "03", name: "Gym Carry", title: "运动场景", description: "训练结束后随身携带，让补充与移动生活自然衔接。", keywords: ["训练后补充", "移动使用"] },
  ];

  return (
    <section className="product-scenarios">
      <header>
        <div><span>CROSS-BORDER STORY</span><h2>为什么这个商品适合跨境市场？</h2></div>
        <p>以下内容为 Demo 营销场景假设，用于展示商品洞察如何转化为内容方向。</p>
      </header>
      <div className="product-scenarios__grid">
        {scenarios.map((scenario) => (
          <article key={scenario.name}>
            <span>{scenario.number}</span>
            <small>{scenario.name}</small>
            <h3>{scenario.title}</h3>
            <p>{scenario.description}</p>
            <div>{scenario.keywords.map((keyword) => <em key={keyword}>{keyword}</em>)}</div>
          </article>
        ))}
      </div>
    </section>
  );
}

function MarketingValueStory() {
  const steps = [
    { number: "01", label: "商品卖点", detail: "理解产品能力与差异" },
    { number: "02", label: "用户需求", detail: "映射真实使用场景" },
    { number: "03", label: "平台内容", detail: "适配不同社媒表达" },
    { number: "04", label: "投放反馈", detail: "指导下一轮增长" },
  ];

  return (
    <section className="marketing-value-story">
      <header><span>MORE THAN GENERATION</span><h2>AI 理解商品，而不是只生成内容</h2></header>
      <div>
        {steps.map((step, index) => (
          <article key={step.label}>
            <span>{step.number}</span><strong>{step.label}</strong><p>{step.detail}</p>
            {index < steps.length - 1 && <i>→</i>}
          </article>
        ))}
      </div>
    </section>
  );
}

function BusinessFlow({ snapshot }: { snapshot: DashboardSnapshot }) {
  const metrics = snapshot.growth.metrics;
  const steps: Array<{ label: string; summary: string; status: PipelineStatus }> = [
    { label: "商品洞察", summary: `${snapshot.product.selling_points.length} 个核心卖点，聚焦 ${snapshot.product.target_markets.join(" / ")}`, status: "complete" },
    { label: "营销策略", summary: snapshot.strategy?.positioning ?? "等待营销策略", status: snapshot.strategy ? "complete" : "missing" },
    { label: "社媒内容矩阵", summary: snapshot.copy_matrix ? `${snapshot.copy_matrix.copies.length} 个平台差异化表达` : "等待内容矩阵", status: snapshot.copy_matrix ? "complete" : "missing" },
    { label: "短视频方案", summary: snapshot.video_project ? `${snapshot.video_project.duration_seconds} 秒 · ${snapshot.video_project.scenes.length} 个分镜` : "等待视频方案", status: snapshot.video_project ? "complete" : "missing" },
    { label: "投放分析", summary: metrics?.roas == null ? "等待投放数据" : `总体 ROAS ${metrics.roas.toFixed(2)}x`, status: metrics ? "complete" : "missing" },
    { label: "增长反馈", summary: snapshot.growth.recommendation?.recommendations[0] ?? "等待优化建议", status: snapshot.growth.recommendation ? "complete" : snapshot.growth.status },
  ];

  return (
    <section className="business-flow">
      <header><span>THE GROWTH LOOP</span><h2>从商品洞察到增长反馈</h2></header>
      <div className="business-flow__track">
        {steps.map((step, index) => (
          <article className={`business-step business-step--${step.status}`} key={step.label}>
            <span>{String(index + 1).padStart(2, "0")}</span>
            <div><small>{step.status === "complete" ? "已完成" : "待补充"}</small><strong>{step.label}</strong><p>{step.summary}</p></div>
            {index < steps.length - 1 && <i>↓</i>}
          </article>
        ))}
      </div>
      <div className="feedback-loop">增长数据反馈下一轮策略、文案与视频素材</div>
    </section>
  );
}

function GrowthShowcase({ snapshot }: { snapshot: DashboardSnapshot }) {
  const growth = snapshot.growth;
  const metrics = growth.metrics;
  return (
    <section className="growth-showcase">
      <header>
        <div><span>GROWTH COPILOT</span><h2>让投放数据指导下一轮内容</h2></div>
        <p>指标由确定性引擎基于 Campaign 总量计算，展示层不重新计算业务指标。</p>
      </header>
      {metrics ? <>
        <div className="growth-showcase__totals">
          <GrowthMetric label="ROAS" value={formatRatio(metrics.roas)} />
          <GrowthMetric label="CTR" value={formatPercent(metrics.ctr)} />
          <GrowthMetric label="CVR" value={formatPercent(metrics.conversion_rate)} />
          <GrowthMetric label="CPA" value={formatCurrency(metrics.cpa)} />
        </div>
        <div className="platform-performance">
          {growth.platform_metrics.map((item) => <PlatformCard item={item} key={item.platform} />)}
        </div>
      </> : <ShowcaseState title="暂无投放指标" detail="Snapshot 中没有可展示的 Campaign 数据。" />}
      {growth.recommendation && <div className="growth-next-action">
        <div><small>下一步增长动作</small><strong>{growth.recommendation.recommendations[0]}</strong></div>
        <p>{growth.recommendation.budget_suggestion}</p>
      </div>}
    </section>
  );
}

function PlatformCard({ item }: { item: PlatformMetrics }) {
  return (
    <article>
      <header><strong>{item.platform}</strong><span>{formatRatio(item.metrics.roas)} ROAS</span></header>
      <div><small>CTR</small><strong>{formatPercent(item.metrics.ctr)}</strong></div>
      <div><small>CVR</small><strong>{formatPercent(item.metrics.conversion_rate)}</strong></div>
      <div><small>CPA</small><strong>{formatCurrency(item.metrics.cpa)}</strong></div>
    </article>
  );
}

function OutcomeCard({ eyebrow, value, unit, label, accent = false }: { eyebrow: string; value: string; unit: string; label: string; accent?: boolean }) {
  return <article className={accent ? "outcome-card outcome-card--accent" : "outcome-card"}><span>{eyebrow}</span><div><strong>{value}</strong><em>{unit}</em></div><p>{label}</p></article>;
}

function GrowthMetric({ label, value }: { label: string; value: string }) {
  return <div><span>{label}</span><strong>{value}</strong></div>;
}

function StoryList({ title, items }: { title: string; items: string[] }) {
  return <div><strong>{title}</strong><ul>{items.map((item) => <li key={item}>{item}</li>)}</ul></div>;
}

function ShowcaseState({ title, detail, error = false }: { title: string; detail: string; error?: boolean }) {
  return <section className={`showcase-state${error ? " showcase-state--error" : ""}`}><span>{error ? "!" : "…"}</span><strong>{title}</strong><p>{detail}</p></section>;
}

function formatPercent(value: number) {
  return `${(value * 100).toFixed(2)}%`;
}

function formatCurrency(value: number | null) {
  return value == null ? "—" : `$${value.toFixed(2)}`;
}

function formatRatio(value: number | null) {
  return value == null ? "—" : `${value.toFixed(2)}x`;
}
