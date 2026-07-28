import axios from "axios";
import { useEffect, useRef, useState } from "react";

import {
  downloadVideoRenderArtifact,
  getVideoRenderArtifactMetadata,
  getVideoRenderArtifactContentUrl,
} from "../../api/videos";
import type {
  VideoRenderArtifactReference,
  VideoRenderArtifactSafe,
} from "../../types/video";

type ArtifactState =
  | "artifact_idle"
  | "artifact_loading"
  | "artifact_ready"
  | "artifact_missing"
  | "artifact_invalid";
type PlaybackState =
  | "playback_loading"
  | "playback_ready"
  | "playback_failed";
type DownloadState = "download_ready" | "download_failed";

interface Props {
  productId: number;
  videoProjectId: number;
  renderTaskId: number;
  artifact: VideoRenderArtifactReference;
}

export function StableVideoArtifactPanel({
  productId,
  videoProjectId,
  renderTaskId,
  artifact,
}: Props) {
  const [artifactState, setArtifactState] =
    useState<ArtifactState>("artifact_idle");
  const [playbackState, setPlaybackState] =
    useState<PlaybackState>("playback_loading");
  const [downloadState, setDownloadState] =
    useState<DownloadState>("download_ready");
  const [metadata, setMetadata] =
    useState<VideoRenderArtifactSafe | null>(null);
  const [error, setError] = useState("");
  const [retryKey, setRetryKey] = useState(0);
  const [playerKey, setPlayerKey] = useState(0);
  const requestIdRef = useRef(0);
  const downloadLockRef = useRef(false);
  const downloadControllerRef = useRef<AbortController | null>(null);

  useEffect(() => {
    const requestId = ++requestIdRef.current;
    const controller = new AbortController();
    downloadControllerRef.current?.abort();
    downloadLockRef.current = false;
    setArtifactState("artifact_loading");
    setPlaybackState("playback_loading");
    setDownloadState("download_ready");
    setMetadata(null);
    setError("");

    getVideoRenderArtifactMetadata(artifact.id, controller.signal)
      .then((result) => {
        if (
          controller.signal.aborted ||
          requestIdRef.current !== requestId ||
          result.id !== artifact.id ||
          result.video_render_task_id !== renderTaskId
        ) {
          return;
        }
        setMetadata(result);
        setArtifactState("artifact_ready");
      })
      .catch((loadError: unknown) => {
        if (
          controller.signal.aborted ||
          requestIdRef.current !== requestId
        ) {
          return;
        }
        const missing =
          axios.isAxiosError(loadError) &&
          loadError.response?.status === 404;
        setArtifactState(missing ? "artifact_missing" : "artifact_invalid");
        setError(
          missing
            ? "已保存视频文件当前不可用。请恢复文件后重试本地读取。"
            : "已保存视频完整性检查未通过。未访问 Provider，可安全重试。",
        );
      });

    return () => controller.abort();
  }, [
    artifact.id,
    productId,
    renderTaskId,
    retryKey,
    videoProjectId,
  ]);

  useEffect(
    () => () => {
      downloadControllerRef.current?.abort();
    },
    [],
  );

  async function download() {
    if (!metadata || downloadLockRef.current) return;
    downloadLockRef.current = true;
    const controller = new AbortController();
    downloadControllerRef.current = controller;
    setDownloadState("download_ready");
    try {
      const blob = await downloadVideoRenderArtifact(
        metadata.id,
        controller.signal,
      );
      if (controller.signal.aborted || metadata.id !== artifact.id) return;
      const extension =
        metadata.content_type === "video/webm" ? "webm" : "mp4";
      const objectUrl = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = objectUrl;
      link.download = `video-artifact-${metadata.id}-task-${renderTaskId}.${extension}`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(objectUrl);
    } catch {
      if (!controller.signal.aborted) {
        setDownloadState("download_failed");
        setError("下载失败。未触发 Render Submit、Refresh 或 Provider。");
      }
    } finally {
      if (downloadControllerRef.current === controller) {
        downloadControllerRef.current = null;
        downloadLockRef.current = false;
      }
    }
  }

  if (
    artifactState === "artifact_idle" ||
    artifactState === "artifact_loading"
  ) {
    return (
      <div className="stable-video-artifact is-loading" aria-busy="true">
        <strong>正在验证已保存视频</strong>
        <p>只读取本地 Artifact 元数据，不访问 Provider。</p>
      </div>
    );
  }

  if (!metadata) {
    return (
      <div className="stable-video-artifact is-error">
        <strong>
          {artifactState === "artifact_missing"
            ? "已保存视频缺失"
            : "已保存视频不可用"}
        </strong>
        <p>{error}</p>
        <button type="button" onClick={() => setRetryKey((value) => value + 1)}>
          重试读取本地 Artifact
        </button>
      </div>
    );
  }

  return (
    <section className="stable-video-artifact" data-state={artifactState}>
      <header>
        <div>
          <span>本地稳定资产</span>
          <h5>生成视频已保存</h5>
        </div>
        <strong>Artifact #{metadata.id}</strong>
      </header>
      <div className="stable-video-artifact__facts">
        <Info label="RenderTask" value={`#${metadata.video_render_task_id}`} />
        <Info label="Scene" value="Scene 1" />
        <Info label="Content-Type" value={metadata.content_type} />
        <Info label="文件大小" value={formatBytes(metadata.size_bytes)} />
        <Info label="SHA-256" value={abbreviateHash(metadata.sha256)} />
        <Info label="创建时间" value={formatDateTime(metadata.created_at)} />
      </div>
      <p className="stable-video-artifact__notice">
        文件已持久化到受控本地存储；播放与下载只使用 Backend 稳定 API。
        当前阶段仅支持单 Scene 视频，不代表多场景合成能力。
      </p>
      <div className="stable-video-artifact__player">
        {playbackState === "playback_loading" ? (
          <span className="stable-video-artifact__player-state">
            正在加载视频元数据…
          </span>
        ) : null}
        <video
          key={playerKey}
          controls
          preload="metadata"
          src={getVideoRenderArtifactContentUrl(metadata.id)}
          onLoadStart={() => setPlaybackState("playback_loading")}
          onLoadedMetadata={() => setPlaybackState("playback_ready")}
          onCanPlay={() => setPlaybackState("playback_ready")}
          onError={() => setPlaybackState("playback_failed")}
        >
          当前浏览器不支持视频播放。
        </video>
      </div>
      {playbackState === "playback_failed" ? (
        <div className="stable-video-artifact__inline-error">
          <span>视频播放失败。可安全重试稳定 Content API。</span>
          <button
            type="button"
            onClick={() => {
              setPlaybackState("playback_loading");
              setPlayerKey((value) => value + 1);
            }}
          >
            重试播放
          </button>
        </div>
      ) : null}
      <div className="stable-video-artifact__actions">
        <button type="button" onClick={() => void download()}>
          下载已保存视频
        </button>
        {downloadState === "download_failed" ? (
          <span role="alert">{error}</span>
        ) : null}
      </div>
    </section>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function formatBytes(value: number) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(2)} MB`;
}

function abbreviateHash(value: string) {
  return `${value.slice(0, 12)}…${value.slice(-12)}`;
}

function formatDateTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "时间未知";
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}
