import {
  groupSnapshotCampaignMetrics,
  type SnapshotMetricsView,
  type SnapshotPresentationView,
  type SnapshotRecommendationView,
} from "./snapshotPresentationPayload";

export function SnapshotGrowthSlide({ view }: { view: SnapshotPresentationView }) {
  const platformMetrics = groupSnapshotCampaignMetrics(view.campaigns);
  return (
    <div className="snapshot-slide snapshot-growth-slide">
      <header className="snapshot-slide-title">
        <div><span>04 · GROWTH COPILOT</span><h2>投放指标与决策证据</h2></div>
        <p>所有Campaign及指标来自当前不可变Snapshot；页面不执行广告操作，也不重新计算或写回业务记录。</p>
      </header>

      {view.metrics ? (
        <section className="snapshot-growth-totals">
          <Metric label="CTR" value={formatPercent(view.metrics.ctr)} />
          <Metric label="CVR" value={formatPercent(view.metrics.conversionRate)} />
          <Metric label="CPA" value={formatMoney(view.metrics.cpa)} />
          <Metric label="ROAS" value={formatRatio(view.metrics.roas)} accent />
        </section>
      ) : <Empty title="汇总指标缺失" text="Snapshot没有campaign_metrics，不从当前Campaign重新补齐汇总结果。" />}

      <section className="snapshot-growth-layout">
        <article className="snapshot-campaign-evidence">
          <header><span>CAMPAIGN RECORDS</span><strong>{view.campaigns.length}条快照记录</strong></header>
          {view.campaigns.length > 0 ? (
            <>
              <div className="snapshot-campaign-list">
                {view.campaigns.map((campaign, index) => (
                  <section key={`${campaign.id ?? index}-${campaign.platform}`}>
                    <div><small>{campaign.platform || "平台缺失"}</small><strong>{campaign.campaignName || `Campaign #${campaign.id ?? index + 1}`}</strong></div>
                    <dl>
                      <Fact label="曝光" value={formatInteger(campaign.impressions)} />
                      <Fact label="点击" value={formatInteger(campaign.clicks)} />
                      <Fact label="转化" value={formatInteger(campaign.conversions)} />
                      <Fact label="花费" value={formatMoney(campaign.spend)} />
                      <Fact label="收入" value={formatMoney(campaign.revenue)} />
                    </dl>
                  </section>
                ))}
              </div>
              <div className="snapshot-platform-metrics">
                {platformMetrics.map((metrics) => (
                  <section key={metrics.platform}>
                    <header><strong>{metrics.platform}</strong><span>{metrics.records} records</span></header>
                    <dl>
                      <Fact label="CTR" value={formatPercent(metrics.ctr)} />
                      <Fact label="CVR" value={formatPercent(metrics.conversionRate)} />
                      <Fact label="CPA" value={formatMoney(metrics.cpa)} />
                      <Fact label="ROAS" value={formatRatio(metrics.roas)} />
                    </dl>
                  </section>
                ))}
              </div>
            </>
          ) : <Empty title="Campaign缺失" text="Snapshot未包含Campaign记录，不显示其他商品或当前数据库数据。" />}
        </article>

        <RecommendationCard recommendation={view.recommendation} />
      </section>
    </div>
  );
}

function RecommendationCard({ recommendation }: { recommendation: SnapshotRecommendationView | null }) {
  return (
    <article className="snapshot-recommendation-card">
      <header><span>STORED RECOMMENDATION</span><strong>{recommendation ? "Snapshot Evidence" : "缺失"}</strong></header>
      {recommendation ? (
        <>
          {recommendation.rawSummary ? <blockquote>{recommendation.rawSummary}</blockquote> : null}
          <RecommendationList title="问题" values={recommendation.problems} />
          <RecommendationList title="决策建议" values={recommendation.recommendations} />
          <RecommendationList title="创意建议" values={recommendation.creativeSuggestions} />
          {recommendation.budgetSuggestion ? <div className="snapshot-budget-suggestion"><small>预算建议</small><p>{recommendation.budgetSuggestion}</p></div> : null}
        </>
      ) : <Empty title="Recommendation缺失" text="Snapshot未包含Recommendation，不调用AI或旧Demo数据补齐。" />}
      <footer>
        <strong>只读决策证据</strong>
        <span>不自动修改预算 · 不授权广告投放操作</span>
      </footer>
    </article>
  );
}

function RecommendationList({ title, values }: { title: string; values: string[] }) {
  if (values.length === 0) return null;
  return <section><small>{title}</small><ul>{values.map((value) => <li key={value}>{value}</li>)}</ul></section>;
}

function Metric({ label, value, accent = false }: { label: string; value: string; accent?: boolean }) {
  return <article className={accent ? "is-accent" : ""}><small>{label}</small><strong>{value}</strong><span>Snapshot aggregate</span></article>;
}

function Fact({ label, value }: { label: string; value: string }) {
  return <div><dt>{label}</dt><dd>{value}</dd></div>;
}

function Empty({ title, text }: { title: string; text: string }) {
  return <div className="snapshot-empty-evidence"><strong>{title}</strong><p>{text}</p></div>;
}

function formatInteger(value: number): string {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(value);
}

function formatPercent(value: number | null): string {
  return value == null ? "—" : `${(value * 100).toFixed(2)}%`;
}

function formatMoney(value: number | null): string {
  return value == null ? "—" : `$${value.toFixed(2)}`;
}

function formatRatio(value: number | null): string {
  return value == null ? "—" : `${value.toFixed(2)}x`;
}

export function snapshotMetricValues(metrics: SnapshotMetricsView | null) {
  return metrics
    ? [formatPercent(metrics.ctr), formatPercent(metrics.conversionRate), formatMoney(metrics.cpa), formatRatio(metrics.roas)]
    : [];
}
