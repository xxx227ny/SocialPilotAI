export function formatCampaignRecordEvidence(
  campaignIds: number[],
): string | null {
  if (campaignIds.length === 0) return null;
  return `${campaignIds.length} Campaign Records · ${campaignIds
    .map((campaignId) => `#${campaignId}`)
    .join(" · ")}`;
}

export function storedRecommendationLabel(
  recommendation: object | null,
): string | null {
  return recommendation
    ? "Stored Recommendation · Competition Demo Snapshot"
    : null;
}
