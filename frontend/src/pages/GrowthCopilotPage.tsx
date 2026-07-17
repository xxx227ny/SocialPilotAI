import { DemoContextBar } from "../components/showcase/DemoContextBar";
import { PerformanceFeedbackLoop } from "../components/growth/PerformanceFeedbackLoop";
import { WinningCreativePattern } from "../components/growth/WinningCreativePattern";
import { useDemoSnapshot } from "../hooks/useDemoSnapshot";
import type { CampaignMetrics, GrowthRecommendation } from "../types/growth";
import type { PlatformMetrics } from "../types/dashboard";

export function GrowthCopilotPage() {
  const { snapshot, loading, error } = useDemoSnapshot();

  return (
    <div className="competition-page growth-competition-page">
      <DemoContextBar />
      <header className="competition-hero growth-competition-hero">
        <div><span>GROWTH COPILOT</span><h1>Growth Copilot</h1><p>让投放数据指导下一轮内容与预算优化</p></div>
        <div className="readonly-badge"><strong>Demo Snapshot</strong><span>基于预置投放数据</span></div>
      </header>
      {loading ? (
        <PageState title="正在读取增长快照" detail="只读取既有指标和建议，不触发分析流程。" />
      ) : snapshot ? (
        <>
          {snapshot.growth.metrics ? <>
            <OverallMetrics metrics={snapshot.growth.metrics} />
            <PlatformComparison platforms={snapshot.growth.platform_metrics} />
          </> : <PageState title="暂无总体指标" detail="当前 Snapshot 中没有 Campaign 指标。" />}
          <WinningCreativePattern
            strategy={snapshot.strategy}
            copyMatrix={snapshot.copy_matrix}
            videoProject={snapshot.video_project}
            platforms={snapshot.growth.platform_metrics}
          />
          <PerformanceFeedbackLoop
            metrics={snapshot.growth.metrics}
            platforms={snapshot.growth.platform_metrics}
            recommendation={snapshot.growth.recommendation}
            copyMatrix={snapshot.copy_matrix}
            videoProject={snapshot.video_project}
          />
          {snapshot.growth.recommendation ? <RecommendationPanel recommendation={snapshot.growth.recommendation} /> : <PageState title="暂无优化建议" detail="当前 Snapshot 中没有可展示的增长建议。" />}
        </>
      ) : (
        <PageState title="演示快照未就绪" detail={error} error />
      )}
    </div>
  );
}

function OverallMetrics({ metrics }: { metrics: CampaignMetrics }) {
  return (
    <section className="growth-overview">
      <header><span>AGGREGATED PERFORMANCE</span><h2>总体投放表现</h2><p>所有指标直接读取后端确定性 Metrics Engine 结果。</p></header>
      <div>
        <MetricCard label="ROAS" value={ratio(metrics.roas)} note="收入 / 花费" accent />
        <MetricCard label="CTR" value={percent(metrics.ctr)} note="点击 / 曝光" />
        <MetricCard label="CVR" value={percent(metrics.conversion_rate)} note="转化 / 点击" />
        <MetricCard label="CPA" value={currency(metrics.cpa)} note="单次转化成本" />
      </div>
    </section>
  );
}

function PlatformComparison({ platforms }: { platforms: PlatformMetrics[] }) {
  return (
    <section className="growth-platform-section">
      <header><span>CHANNEL PERFORMANCE</span><h2>平台效果对比</h2></header>
      {platforms.length > 0 ? <div className="growth-platform-grid">
        {platforms.map((item) => <article key={item.platform}>
          <header><span>{item.platform.slice(0, 1)}</span><div><small>PLATFORM</small><strong>{item.platform}</strong></div></header>
          <div className="platform-roas"><small>ROAS</small><strong>{ratio(item.metrics.roas)}</strong></div>
          <dl>
            <div><dt>CTR</dt><dd>{percent(item.metrics.ctr)}</dd></div>
            <div><dt>CVR</dt><dd>{percent(item.metrics.conversion_rate)}</dd></div>
            <div><dt>CPA</dt><dd>{currency(item.metrics.cpa)}</dd></div>
          </dl>
        </article>)}
      </div> : <PageState title="暂无平台指标" detail="当前 Snapshot 中没有平台维度 Campaign 数据。" />}
    </section>
  );
}

function RecommendationPanel({ recommendation }: { recommendation: GrowthRecommendation }) {
  return (
    <section className="recommendation-showcase">
      <header><span>OPTIMIZATION SNAPSHOT</span><h2>基于投放数据，系统建议</h2></header>
      <div className="recommendation-grid">
        <AdviceCard number="01" title="问题发现" items={recommendation.problems} />
        <AdviceCard number="02" title="优化建议" items={recommendation.recommendations} />
        <AdviceCard number="03" title="素材建议" items={recommendation.creative_suggestions} />
      </div>
      <div className="budget-recommendation"><span>预算建议</span><p>{recommendation.budget_suggestion}</p></div>
    </section>
  );
}

function MetricCard({ label, value, note, accent = false }: { label: string; value: string; note: string; accent?: boolean }) {
  return <article className={accent ? "growth-metric-card growth-metric-card--accent" : "growth-metric-card"}><span>{label}</span><strong>{value}</strong><p>{note}</p></article>;
}

function AdviceCard({ number, title, items }: { number: string; title: string; items: string[] }) {
  return <article><span>{number}</span><strong>{title}</strong><ul>{items.map((item) => <li key={item}>{item}</li>)}</ul></article>;
}

function PageState({ title, detail, error = false }: { title: string; detail: string; error?: boolean }) {
  return <section className={`competition-state${error ? " competition-state--error" : ""}`}><span>{error ? "!" : "…"}</span><strong>{title}</strong><p>{detail}</p></section>;
}

function percent(value: number) { return `${(value * 100).toFixed(2)}%`; }
function currency(value: number | null) { return value == null ? "—" : `$${value.toFixed(2)}`; }
function ratio(value: number | null) { return value == null ? "—" : `${value.toFixed(2)}x`; }
