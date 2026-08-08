import type { PresentationSnapshot } from "../../types/presentationSnapshot";

export interface SnapshotProductView {
  id: number | null;
  name: string;
  category: string;
  description: string;
  sellingPoints: string[];
  targetMarkets: string[];
}

export interface SnapshotBriefView {
  id: number | null;
  audience: string;
  language: string;
  platforms: string[];
  tone: string;
  objective: string;
}

export interface SnapshotStrategyView {
  id: number | null;
  positioning: string;
  audienceInsights: string[];
  angles: string[];
  risks: string[];
  evidence: string[];
}

export interface SnapshotCopyView {
  platform: string;
  hook: string;
  caption: string;
  hashtags: string[];
  cta: string;
}

export interface SnapshotSceneView {
  sequence: number | null;
  durationSeconds: number | null;
  shotType: string;
  visualDescription: string;
  action: string;
  narration: string;
}

export interface SnapshotVideoView {
  id: number | null;
  platform: string;
  title: string;
  concept: string;
  durationSeconds: number | null;
  aspectRatio: string;
  status: string;
  cta: string;
  scenes: SnapshotSceneView[];
}

export interface SnapshotRenderView {
  id: number | null;
  status: string;
  providerName: string;
  durationSeconds: number | null;
  aspectRatio: string;
  resolution: string;
}

export interface SnapshotArtifactView {
  id: number | null;
  renderTaskId: number | null;
  contentType: string;
  sizeBytes: number | null;
  sha256: string;
}

export interface SnapshotPublishView {
  id: number | null;
  platform: string;
  privacyStatus: string;
  status: string;
  completedAt: string;
  artifactId: number | null;
}

export interface SnapshotCampaignView {
  id: number | null;
  platform: string;
  campaignName: string;
  impressions: number;
  clicks: number;
  conversions: number;
  spend: number;
  revenue: number;
}

export interface SnapshotMetricsView {
  impressions: number | null;
  clicks: number | null;
  conversions: number | null;
  spend: number | null;
  revenue: number | null;
  ctr: number | null;
  conversionRate: number | null;
  cpa: number | null;
  roas: number | null;
}

export interface SnapshotRecommendationView {
  problems: string[];
  recommendations: string[];
  creativeSuggestions: string[];
  budgetSuggestion: string;
  rawSummary: string;
}

export interface SnapshotPresentationView {
  product: SnapshotProductView | null;
  brief: SnapshotBriefView | null;
  strategy: SnapshotStrategyView | null;
  copyMatrixId: number | null;
  copies: SnapshotCopyView[];
  video: SnapshotVideoView | null;
  render: SnapshotRenderView | null;
  artifact: SnapshotArtifactView | null;
  publish: SnapshotPublishView | null;
  campaigns: SnapshotCampaignView[];
  metrics: SnapshotMetricsView | null;
  recommendation: SnapshotRecommendationView | null;
}

export interface SnapshotPlatformMetrics {
  platform: string;
  records: number;
  impressions: number;
  clicks: number;
  conversions: number;
  spend: number;
  revenue: number;
  ctr: number | null;
  conversionRate: number | null;
  cpa: number | null;
  roas: number | null;
}

export function readSnapshotPresentationView(
  snapshot: PresentationSnapshot,
): SnapshotPresentationView {
  const payload = asRecord(snapshot.snapshot_payload) ?? {};
  const product = asRecord(payload.product);
  const brief = asRecord(payload.marketing_brief);
  const strategy = asRecord(payload.marketing_strategy);
  const copyMatrix = asRecord(payload.copy_matrix);
  const video = asRecord(payload.video_project);
  const render = asRecord(payload.render_task);
  const artifact = asRecord(payload.artifact);
  const publish = asRecord(payload.publish_task);
  const metrics = asRecord(payload.campaign_metrics);
  const recommendation = asRecord(payload.growth_recommendation);

  return {
    product: product
      ? {
          id: numberOrNull(product.id),
          name: stringOrEmpty(product.name),
          category: stringOrEmpty(product.category),
          description: stringOrEmpty(product.description),
          sellingPoints: stringArray(product.selling_points),
          targetMarkets: stringArray(product.target_markets),
        }
      : null,
    brief: brief
      ? {
          id: numberOrNull(brief.id),
          audience: stringOrEmpty(brief.audience),
          language: stringOrEmpty(brief.language),
          platforms: stringArray(brief.platforms),
          tone: stringOrEmpty(brief.tone),
          objective: stringOrEmpty(brief.objective),
        }
      : null,
    strategy: strategy
      ? {
          id: numberOrNull(strategy.id),
          positioning: stringOrEmpty(strategy.positioning),
          audienceInsights: stringArray(strategy.audience_insights),
          angles: stringArray(strategy.angles),
          risks: stringArray(strategy.risks),
          evidence: stringArray(strategy.evidence),
        }
      : null,
    copyMatrixId: numberOrNull(copyMatrix?.id),
    copies: recordArray(copyMatrix?.copies).map((copy) => ({
      platform: stringOrEmpty(copy.platform),
      hook: stringOrEmpty(copy.hook),
      caption: stringOrEmpty(copy.caption),
      hashtags: stringArray(copy.hashtags),
      cta: stringOrEmpty(copy.cta),
    })),
    video: video
      ? {
          id: numberOrNull(video.id),
          platform: stringOrEmpty(video.platform),
          title: stringOrEmpty(video.title),
          concept: stringOrEmpty(video.concept),
          durationSeconds: numberOrNull(video.duration_seconds),
          aspectRatio: stringOrEmpty(video.aspect_ratio),
          status: stringOrEmpty(video.status),
          cta: stringOrEmpty(video.cta),
          scenes: recordArray(video.scenes).map((scene) => ({
            sequence: numberOrNull(scene.sequence),
            durationSeconds: numberOrNull(scene.duration_seconds),
            shotType: stringOrEmpty(scene.shot_type),
            visualDescription: stringOrEmpty(scene.visual_description),
            action: stringOrEmpty(scene.action),
            narration: stringOrEmpty(scene.narration),
          })),
        }
      : null,
    render: render
      ? {
          id: numberOrNull(render.id),
          status: stringOrEmpty(render.status),
          providerName: stringOrEmpty(render.provider_name),
          durationSeconds: numberOrNull(render.duration_seconds),
          aspectRatio: stringOrEmpty(render.aspect_ratio),
          resolution: stringOrEmpty(render.resolution),
        }
      : null,
    artifact: artifact
      ? {
          id: numberOrNull(artifact.id),
          renderTaskId: numberOrNull(artifact.video_render_task_id),
          contentType: stringOrEmpty(artifact.content_type),
          sizeBytes: numberOrNull(artifact.size_bytes),
          sha256: stringOrEmpty(artifact.sha256),
        }
      : null,
    publish: publish
      ? {
          id: numberOrNull(publish.id),
          platform: stringOrEmpty(publish.platform),
          privacyStatus: stringOrEmpty(publish.privacy_status),
          status: stringOrEmpty(publish.status),
          completedAt: stringOrEmpty(publish.completed_at),
          artifactId: numberOrNull(publish.artifact_id),
        }
      : null,
    campaigns: recordArray(payload.campaigns).map((campaign) => ({
      id: numberOrNull(campaign.id),
      platform: stringOrEmpty(campaign.platform),
      campaignName: stringOrEmpty(campaign.campaign_name),
      impressions: numberOrZero(campaign.impressions),
      clicks: numberOrZero(campaign.clicks),
      conversions: numberOrZero(campaign.conversions),
      spend: numberOrZero(campaign.spend),
      revenue: numberOrZero(campaign.revenue),
    })),
    metrics: metrics
      ? {
          impressions: numberOrNull(metrics.impressions),
          clicks: numberOrNull(metrics.clicks),
          conversions: numberOrNull(metrics.conversions),
          spend: numberOrNull(metrics.spend),
          revenue: numberOrNull(metrics.revenue),
          ctr: numberOrNull(metrics.ctr),
          conversionRate: numberOrNull(metrics.conversion_rate),
          cpa: numberOrNull(metrics.cpa),
          roas: numberOrNull(metrics.roas),
        }
      : null,
    recommendation: recommendation
      ? {
          problems: stringArray(recommendation.problems),
          recommendations: stringArray(recommendation.recommendations),
          creativeSuggestions: stringArray(
            recommendation.creative_suggestions,
          ),
          budgetSuggestion: stringOrEmpty(
            recommendation.budget_suggestion,
          ),
          rawSummary: stringOrEmpty(recommendation.summary),
        }
      : null,
  };
}

export function formatSnapshotCopyIdentity(
  strategyId: number | null,
  copyMatrixId: number | null,
): string {
  return strategyId !== null && copyMatrixId !== null
    ? `Strategy #${strategyId} \u2192 CopyMatrix #${copyMatrixId}`
    : "\u6765\u6e90\u8eab\u4efd\u7f3a\u5931";
}

export function groupSnapshotCampaignMetrics(
  campaigns: SnapshotCampaignView[],
): SnapshotPlatformMetrics[] {
  const groups = new Map<string, SnapshotCampaignView[]>();
  for (const campaign of campaigns) {
    const platform = campaign.platform || "未标记平台";
    groups.set(platform, [...(groups.get(platform) ?? []), campaign]);
  }
  return [...groups.entries()].map(([platform, records]) => {
    const totals = records.reduce(
      (result, campaign) => ({
        impressions: result.impressions + campaign.impressions,
        clicks: result.clicks + campaign.clicks,
        conversions: result.conversions + campaign.conversions,
        spend: result.spend + campaign.spend,
        revenue: result.revenue + campaign.revenue,
      }),
      { impressions: 0, clicks: 0, conversions: 0, spend: 0, revenue: 0 },
    );
    return {
      platform,
      records: records.length,
      ...totals,
      ctr: divide(totals.clicks, totals.impressions),
      conversionRate: divide(totals.conversions, totals.clicks),
      cpa: divide(totals.spend, totals.conversions),
      roas: divide(totals.revenue, totals.spend),
    };
  });
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function recordArray(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value)
    ? value.map(asRecord).filter((item): item is Record<string, unknown> => item !== null)
    : [];
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

function stringOrEmpty(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function numberOrNull(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function numberOrZero(value: unknown): number {
  return numberOrNull(value) ?? 0;
}

function divide(numerator: number, denominator: number): number | null {
  return denominator > 0 ? numerator / denominator : null;
}
