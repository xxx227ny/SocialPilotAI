import { useEffect, useMemo, useRef, useState } from "react";

import { getApiErrorMessage } from "../../api/client";
import {
  compositionArtifactPreviewUrl,
  getCompositionArtifact,
  getCompositionJob,
  preflightVideoComposition,
  submitVideoComposition,
} from "../../api/videoCompositions";
import { getVideoProject, getVideoRenderArtifacts } from "../../api/videos";
import { videoCompositionEnabled } from "../../config/features";
import { usePresentationMode } from "../../context/PresentationModeContext";
import type { ExecutionJob } from "../../types/execution";
import type { Product } from "../../types/product";
import type { VideoProject, VideoRenderArtifact } from "../../types/video";
import type { CompositionShotInput, VideoCompositionArtifact, VideoCompositionPreflight } from "../../types/videoComposition";
import { exactCompositionResult, selectionIdentity, shouldPollComposition } from "./videoCompositionState";
import { VideoCompositionEnhancementPanel } from "./VideoCompositionEnhancementPanel";

export function VideoCompositionPanel({ product, videoProjectId }: { product: Product; videoProjectId?: number }) {
  const { isPresentation } = usePresentationMode();
  const [project, setProject] = useState<VideoProject | null>(null);
  const [artifacts, setArtifacts] = useState<VideoRenderArtifact[]>([]);
  const [selections, setSelections] = useState<Record<number, number>>({});
  const [preflight, setPreflight] = useState<VideoCompositionPreflight | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [job, setJob] = useState<ExecutionJob | null>(null);
  const [result, setResult] = useState<VideoCompositionArtifact | null>(null);
  const [message, setMessage] = useState("");
  const submitLock = useRef(false);
  const resultLock = useRef(false);
  const identity = useMemo(() => selectionIdentity(selections), [selections]);

  useEffect(() => {
    setProject(null); setArtifacts([]); setSelections({}); setPreflight(null); setConfirmed(false); setJob(null); setResult(null); setMessage("");
    if (!videoCompositionEnabled || isPresentation || !videoProjectId) return;
    const controller = new AbortController();
    Promise.all([getVideoProject(videoProjectId, controller.signal), getVideoRenderArtifacts(videoProjectId)])
      .then(([nextProject, nextArtifacts]) => { if (!controller.signal.aborted) { setProject(nextProject); setArtifacts(nextArtifacts); } })
      .catch((error) => { if (!controller.signal.aborted) setMessage(getApiErrorMessage(error, "成片来源加载失败。")); });
    return () => controller.abort();
  }, [isPresentation, product.id, videoProjectId]);

  useEffect(() => { setPreflight(null); setConfirmed(false); setJob(null); setResult(null); setMessage(""); }, [identity]);

  useEffect(() => {
    if (!job || !shouldPollComposition(job)) return;
    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      try { const next = await getCompositionJob(job.id, controller.signal); if (!controller.signal.aborted) setJob(next); }
      catch { if (!controller.signal.aborted) setMessage("本地任务读取暂时失败，将继续读取同一任务。"); }
    }, 1500);
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [job]);

  useEffect(() => {
    if (!job) return;
    const artifactId = exactCompositionResult(job);
    if (!artifactId || result?.id === artifactId || resultLock.current) return;
    resultLock.current = true;
    const controller = new AbortController();
    getCompositionArtifact(artifactId, controller.signal)
      .then((artifact) => { if (!controller.signal.aborted) setResult(artifact); })
      .catch((error) => { if (!controller.signal.aborted) setMessage(getApiErrorMessage(error, "成片记录读取失败，请显式重读。")); })
      .finally(() => { if (!controller.signal.aborted) resultLock.current = false; });
    return () => controller.abort();
  }, [job, result]);

  if (!videoCompositionEnabled || isPresentation || !videoProjectId) return null;
  const scenes = project?.scenes ?? [];
  const selectedShots = scenes.map((scene, index) => {
    const artifactId = selections[scene.sequence];
    const artifact = artifacts.find((item) => item.id === artifactId);
    const start = scenes.slice(0, index).reduce((sum, item) => sum + item.duration_seconds * 1000, 0);
    return artifact ? { sequence: scene.sequence, start_ms: start, end_ms: start + scene.duration_seconds * 1000, trim_start_ms: 0, trim_end_ms: scene.duration_seconds * 1000, transition_type: "cut" as const, render_task_id: artifact.video_render_task_id, artifact_id: artifact.id } : null;
  }).filter((shot): shot is CompositionShotInput => shot !== null);

  async function runPreflight() {
    if (!project || selectedShots.length < 3) return;
    try { setPreflight(await preflightVideoComposition(product.id, project.id, selectedShots)); setMessage(""); }
    catch (error) { setMessage(getApiErrorMessage(error, "成片前置检查失败。")); }
  }
  async function submit() {
    if (!preflight || submitLock.current) return;
    submitLock.current = true;
    try { const response = await submitVideoComposition(product.id, preflight); setJob(response.job); setMessage(response.reused ? "已复用精确合成任务。" : "已创建本地合成任务。"); }
    catch (error) { setMessage(getApiErrorMessage(error, "成片任务创建失败。")); }
    finally { submitLock.current = false; }
  }

  return <section className="video-composition-panel">
    <h4>15秒多镜头本地成片</h4>
    <p>本地合成使用确定性静音 AAC 占位音轨；这不是配音或背景音乐。</p>
    <p>输出合同：15秒 · MP4 · H.264 High · AAC-LC · 1080×1920 · CFR 30fps</p>
    {scenes.map((scene) => <label key={scene.sequence}>镜头 #{scene.sequence} · {scene.duration_seconds}s
      <select value={selections[scene.sequence] ?? ""} onChange={(event) => setSelections((current) => ({ ...current, [scene.sequence]: Number(event.target.value) }))}>
        <option value="">明确选择来源视频</option>
        {artifacts.filter((artifact) => artifact.video_render_task_id > 0).map((artifact) => <option key={artifact.id} value={artifact.id}>视频 #{artifact.id} · 渲染任务 #{artifact.video_render_task_id}</option>)}
      </select>
    </label>)}
    <div className="composition-timeline">{selectedShots.map((shot) => <span key={shot.sequence}>#{shot.sequence} {shot.start_ms/1000}–{shot.end_ms/1000}秒 · 视频 #{shot.artifact_id}</span>)}</div>
    <button type="button" onClick={() => void runPreflight()} disabled={selectedShots.length < 3 || submitLock.current}>运行零模型调用前置检查</button>
    {preflight && <><label><input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />确认本地CPU与磁盘写入</label><button type="button" disabled={!confirmed || submitLock.current} onClick={() => void submit()}>创建15秒成片</button></>}
    {job && <p>任务 #{job.id} · {job.status}</p>}
    {result && <><p>合成视频 #{result.id} · {result.duration_ms}毫秒 · {result.video_codec}/{result.audio_codec}</p><video controls playsInline preload="metadata" src={compositionArtifactPreviewUrl(result.id)} /><VideoCompositionEnhancementPanel product={product} artifact={result} /></>}
    {job?.status === "SUCCEEDED" && !result && <button type="button" onClick={() => setJob({ ...job })} disabled={resultLock.current}>重新读取精确成片记录</button>}
    {message && <p role="status">{message}</p>}
  </section>;
}
