import type { VideoRenderArtifact } from "../../types/video";
import { getVideoRenderArtifactPreviewUrl } from "../../api/videos";

interface VerifiedWanxOutputProps {
  artifact: VideoRenderArtifact;
}

export function VerifiedWanxOutput({ artifact }: VerifiedWanxOutputProps) {
  const playbackUrl = artifact.storage_path
    ? getVideoRenderArtifactPreviewUrl(artifact.id)
    : artifact.provider_output_url;
  if (!playbackUrl) return null;

  const usage = asRecord(artifact.metadata.usage);
  const duration = readValue(usage?.duration, artifact.metadata.duration);
  const aspectRatio = readValue(usage?.ratio, artifact.metadata.ratio);
  const resolution = formatResolution(
    readValue(
      usage?.resolution,
      usage?.SR,
      artifact.metadata.resolution,
    ),
  );

  return (
    <section className="verified-wanx-output">
      <div className="verified-wanx-output__player">
        <video
          controls
          playsInline
          preload="metadata"
          src={playbackUrl}
        >
          Your browser does not support video playback.
        </video>
      </div>
      <div className="verified-wanx-output__details">
        <span>Verified Wanx Output</span>
        <h2>Pre-generated before presentation</h2>
        <p>
          This verified render is loaded from an existing VideoRenderArtifact.
          No generation or status refresh runs when this page opens.
        </p>
        <div className="verified-wanx-output__trust">
          <strong>0 live AI calls</strong>
          <small>Read-only artifact playback</small>
        </div>
        <dl>
          <RenderFact label="Artifact" value={`#${artifact.id}`} />
          <RenderFact
            label="Render task"
            value={`#${artifact.video_render_task_id}`}
          />
          <RenderFact label="Status" value="SUCCEEDED" />
          <RenderFact label="Duration" value={formatDuration(duration)} />
          <RenderFact label="Aspect ratio" value={formatValue(aspectRatio)} />
          <RenderFact label="Resolution" value={resolution} />
          <RenderFact label="Generated source" value="Wanx Provider" />
        </dl>
      </div>
    </section>
  );
}

function RenderFact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function readValue(...values: unknown[]): string | number | null {
  const value = values.find(
    (candidate) =>
      (typeof candidate === "string" && candidate.trim() !== "") ||
      typeof candidate === "number",
  );
  return typeof value === "string" || typeof value === "number" ? value : null;
}

function formatDuration(value: string | number | null): string {
  return value === null ? "—" : `${value}s`;
}

function formatResolution(value: string | number | null): string {
  if (value === null) return "—";
  if (typeof value === "number") return `${value}P`;
  return /^\d+$/.test(value) ? `${value}P` : value;
}

function formatValue(value: string | number | null): string {
  return value === null ? "—" : String(value);
}
