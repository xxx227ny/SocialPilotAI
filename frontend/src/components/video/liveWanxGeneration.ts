import type {
  LiveRenderTaskResponse,
  VideoRenderArtifact,
  VideoRenderTaskStatus,
} from "../../types/video";

export const LIVE_POLL_INTERVAL_MS = 15_000;
export const LIVE_MAX_WAIT_MS = 5 * 60_000;

const ACTIVE_STATUSES: VideoRenderTaskStatus[] = [
  "CREATED",
  "SUBMITTED",
  "PENDING",
  "RUNNING",
];

interface ExecuteLiveGenerationOptions {
  videoProjectId: number;
  create: (videoProjectId: number) => Promise<LiveRenderTaskResponse>;
  refresh: (taskId: number) => Promise<LiveRenderTaskResponse>;
  onStatus: (status: VideoRenderTaskStatus) => void;
  onArtifactReady: () => Promise<void>;
  isActive: () => boolean;
  wait?: (milliseconds: number) => Promise<void>;
  now?: () => number;
}

export function isLiveWanxDemoEnabled(value: unknown): boolean {
  return value === "true";
}

export function selectLatestPlayableArtifact(
  artifacts: VideoRenderArtifact[],
): VideoRenderArtifact | undefined {
  return [...artifacts]
    .reverse()
    .find((artifact) => artifact.storage_path || artifact.provider_output_url);
}

export async function executeLiveGeneration({
  videoProjectId,
  create,
  refresh,
  onStatus,
  onArtifactReady,
  isActive,
  wait = delay,
  now = Date.now,
}: ExecuteLiveGenerationOptions): Promise<LiveRenderTaskResponse> {
  let result = await create(videoProjectId);
  if (!isActive()) return result;
  onStatus(result.task.status);
  const deadline = now() + LIVE_MAX_WAIT_MS;

  while (ACTIVE_STATUSES.includes(result.task.status) && now() < deadline) {
    await wait(Math.min(LIVE_POLL_INTERVAL_MS, deadline - now()));
    if (!isActive() || now() >= deadline) return result;
    result = await refresh(result.task.id);
    if (!isActive()) return result;
    onStatus(result.task.status);
  }

  if (result.task.status === "SUCCEEDED" && result.artifact) {
    await onArtifactReady();
  }
  return result;
}

function delay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => globalThis.setTimeout(resolve, milliseconds));
}
