import type { DashboardCopyMatrix, PlatformMetrics } from "../../types/dashboard";
import type { CampaignMetrics, GrowthRecommendation } from "../../types/growth";
import type { VideoProject } from "../../types/video";

interface PerformanceFeedbackLoopProps {
  metrics: CampaignMetrics | null;
  platforms: PlatformMetrics[];
  recommendation: GrowthRecommendation | null;
  copyMatrix: DashboardCopyMatrix | null;
  videoProject: VideoProject | null;
}

export function PerformanceFeedbackLoop({ metrics, platforms, recommendation, copyMatrix, videoProject }: PerformanceFeedbackLoopProps) {
  const leader = findLeadingPlatform(platforms);
  const relatedCopy = copyMatrix?.copies.find((copy) => copy.platform.toLowerCase() === leader?.platform.toLowerCase());

  return (
    <section className="performance-intelligence-loop">
      <header><div><span>PERFORMANCE INTELLIGENCE LOOP</span><h2>让表现反馈进入下一轮内容生产</h2></div><p>基于 Demo Snapshot 识别方向，不代表真实广告归因或确定性增长承诺。</p></header>
      <div className="performance-intelligence-loop__track">
        <LoopStage number="01" label="Performance Snapshot" title="当前投放表现">
          {metrics ? <dl className="feedback-metric-list"><Metric label="ROAS" value={ratio(metrics.roas)} /><Metric label="CTR" value={percent(metrics.ctr)} /><Metric label="CVR" value={percent(metrics.conversion_rate)} /><Metric label="CPA" value={currency(metrics.cpa)} /></dl> : <Fallback text="等待总体投放指标" />}
        </LoopStage>
        <LoopStage number="02" label="Performance Insight" title="识别高表现平台" accent>
          {leader ? <div className="feedback-leader"><strong>{leader.platform}</strong><span>shows strongest performance</span><em>ROAS {ratio(leader.metrics.roas)}</em></div> : <Fallback text="等待平台维度指标" />}
        </LoopStage>
        <LoopStage number="03" label="Optimization Direction" title="提炼下一轮优化方向">
          {recommendation ? <ul className="feedback-direction-list">{recommendation.recommendations.slice(0, 1).map((item) => <li key={item}>{item}</li>)}{recommendation.creative_suggestions.slice(0, 2).map((item) => <li key={item}>{item}</li>)}<li>{recommendation.budget_suggestion}</li></ul> : <Fallback text="等待增长优化建议" />}
        </LoopStage>
        <LoopStage number="04" label="Next Creation" title="连接 Copy + Video">
          <div className="next-creation-directions"><Direction action="Refine" content={relatedCopy?.hook ?? "Portable lifestyle storytelling"} /><Direction action="Strengthen" content={recommendation?.creative_suggestions[0] ?? "USB charging scenario"} /><Direction action="Continue" content={videoProject?.concept ?? "Morning routine content"} /></div>
        </LoopStage>
      </div>
      <div className="performance-intelligence-loop__return">Performance → Pattern → Copy + Video → Next Performance Snapshot</div>
    </section>
  );
}

export function findLeadingPlatform(platforms: PlatformMetrics[]) {
  return platforms.reduce<PlatformMetrics | null>((best, current) => {
    if (current.metrics.roas == null) return best;
    if (best?.metrics.roas == null || current.metrics.roas > best.metrics.roas) return current;
    return best;
  }, null);
}

function LoopStage({ number, label, title, children, accent = false }: { number: string; label: string; title: string; children: React.ReactNode; accent?: boolean }) {
  return <article className={accent ? "feedback-loop-stage feedback-loop-stage--accent" : "feedback-loop-stage"}><header><span>{number}</span><div><small>{label}</small><strong>{title}</strong></div></header>{children}</article>;
}

function Metric({ label, value }: { label: string; value: string }) { return <div><dt>{label}</dt><dd>{value}</dd></div>; }
function Direction({ action, content }: { action: string; content: string }) { return <div><small>{action}</small><p>{content}</p></div>; }
function Fallback({ text }: { text: string }) { return <p className="feedback-loop-fallback">{text}</p>; }
function percent(value: number) { return `${(value * 100).toFixed(2)}%`; }
function currency(value: number | null) { return value == null ? "—" : `$${value.toFixed(2)}`; }
function ratio(value: number | null) { return value == null ? "—" : `${value.toFixed(2)}x`; }
