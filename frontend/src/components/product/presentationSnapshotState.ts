import type {
  PresentationSnapshot,
  PresentationSnapshotCreateRequest,
} from "../../types/presentationSnapshot";
import type { PublishArtifactCandidate, PublishTask } from "../../types/social";
import type { VideoProject } from "../../types/video";

export interface PresentationArtifactSource extends PublishArtifactCandidate {
  marketing_strategy_id: number;
}

export function buildPresentationArtifactSources(
  productId: number,
  artifacts: PublishArtifactCandidate[],
  videoProjects: VideoProject[],
): PresentationArtifactSource[] {
  const projectsById = new Map(videoProjects.map((project) => [project.id, project]));
  return artifacts
    .flatMap((artifact) => {
      const project = projectsById.get(artifact.video_project_id);
      if (
        !project ||
        project.product_id !== productId ||
        project.copy_matrix_id !== artifact.copy_matrix_id
      ) {
        return [];
      }
      return [{ ...artifact, marketing_strategy_id: project.marketing_strategy_id }];
    })
    .sort((left, right) => left.artifact_id - right.artifact_id);
}

export function autoSelectedArtifactId(
  sources: PresentationArtifactSource[],
): number | null {
  return sources.length === 1 ? sources[0].artifact_id : null;
}

export function matchingPublishTasks(
  tasks: PublishTask[],
  productId: number,
  artifactId: number,
): PublishTask[] {
  return tasks
    .filter(
      (task) => task.product_id === productId && task.artifact_id === artifactId,
    )
    .sort((left, right) => left.id - right.id);
}

export function buildPresentationSnapshotRequest(
  source: PresentationArtifactSource,
  publishTaskId: number | null,
  campaignIds: number[],
): PresentationSnapshotCreateRequest {
  return {
    marketing_brief_id: null,
    marketing_strategy_id: source.marketing_strategy_id,
    copy_matrix_id: source.copy_matrix_id,
    video_project_id: source.video_project_id,
    render_task_id: source.render_task_id,
    artifact_id: source.artifact_id,
    publish_task_id: publishTaskId,
    campaign_ids: [...new Set(campaignIds)].sort((left, right) => left - right),
  };
}

export function findSameSourcePresentationSnapshot(
  snapshots: PresentationSnapshot[],
  request: PresentationSnapshotCreateRequest,
): PresentationSnapshot | null {
  const requestedCampaigns = canonicalIds(request.campaign_ids);
  return (
    snapshots.find(
      (snapshot) =>
        snapshot.marketing_brief_id === request.marketing_brief_id &&
        snapshot.marketing_strategy_id === request.marketing_strategy_id &&
        snapshot.copy_matrix_id === request.copy_matrix_id &&
        snapshot.video_project_id === request.video_project_id &&
        snapshot.render_task_id === request.render_task_id &&
        snapshot.artifact_id === request.artifact_id &&
        snapshot.publish_task_id === request.publish_task_id &&
        canonicalIds(snapshot.campaign_ids) === requestedCampaigns,
    ) ?? null
  );
}

function canonicalIds(ids: number[]): string {
  return [...new Set(ids)].sort((left, right) => left - right).join(",");
}
