import { useEffect, useMemo, useRef, useState } from "react";

import { getApiErrorMessage } from "../../api/client";
import {
  getExactMarketingJob,
  getProductImageAsset,
  happyHorseVideoContentUrl,
  listProductVideoSources,
  preflightHappyHorseVideo,
  prepareProductVideo,
  refreshHappyHorseVideo,
  submitHappyHorseVideo,
  submitProductImageJob,
  submitWanxProductImageJob,
  submitVoiceoverJob,
} from "../../api/productMarketingVideo";
import {
  getCompositionArtifact,
  preflightVideoComposition,
  submitVideoComposition,
} from "../../api/videoCompositions";
import {
  compositionEnhancementContentUrl,
  compositionSubtitleContentUrl,
  getCompositionEnhancementArtifact,
  preflightCompositionEnhancement,
  submitCompositionEnhancement,
} from "../../api/videoCompositionEnhancements";
import { realProductVideoEnabled } from "../../config/features";
import { usePresentationMode } from "../../context/PresentationModeContext";
import type { Product } from "../../types/product";
import type {
  ProductVideoSource,
  RealProductVideoPhase,
  UploadedProductImage,
} from "../../types/productMarketingVideo";
import {
  pollExactJob,
  RealProductVideoOperation,
  requireSuccessfulResult,
} from "./realProductVideoState";

const MOTIONS = ["zoom_in", "pan_right", "zoom_out", "pan_left"] as const;

export function RealProductVideoPanel({ product }: { product: Product }) {
  const { isPresentation } = usePresentationMode();
  const operation = useRef(new RealProductVideoOperation());
  const [sources, setSources] = useState<ProductVideoSource[]>([]);
  const [sourceId, setSourceId] = useState(0);
  const [phase, setPhase] = useState<RealProductVideoPhase>("IDLE");
  const [message, setMessage] = useState("");
  const [result, setResult] = useState<{ video: number; subtitle: number } | null>(null);
  const [cloudVideoArtifactId, setCloudVideoArtifactId] = useState<number | null>(null);
  const source = useMemo(
    () => sources.find((item) => item.variant_id === sourceId) ?? null,
    [sourceId, sources],
  );

  useEffect(() => {
    operation.current.stop();
    setSources([]);
    setSourceId(0);
    setResult(null);
    setCloudVideoArtifactId(null);
    if (!realProductVideoEnabled || isPresentation) return;
    const active = operation.current.begin();
    listProductVideoSources(product.id, active.signal)
      .then((items) => {
        if (operation.current.current(active.id)) {
          setSources(items);
          setSourceId(items[0]?.variant_id ?? 0);
        }
      })
      .catch((error) => {
        if (operation.current.current(active.id)) {
          setMessage(getApiErrorMessage(error, "可用Variant读取失败。"));
        }
      });
    return () => operation.current.stop();
  }, [isPresentation, product.id]);

  if (!realProductVideoEnabled || isPresentation) return null;

  async function generate() {
    if (!source) return;
    const active = operation.current.begin();
    setResult(null);
    setMessage("");
    try {
      setPhase("GENERATING_IMAGES");
      const images: UploadedProductImage[] = [];
      for (const scene of source.scenes) {
        const submitted = await submitWanxProductImageJob(
          product.id,
          {
            script_version_id: source.script_version_id,
            scene_sequence: scene.sequence,
            idempotency_key: crypto.randomUUID(),
            cost_confirmed: true,
          },
          active.signal,
        );
        const job = await pollExactJob(
          submitted.job,
          getExactMarketingJob,
          active.signal,
        );
        const assetId = requireSuccessfulResult(job, "product_asset");
        images.push(await getProductImageAsset(product.id, assetId, active.signal));
      }
      setPhase("PREPARING_SHOTS");
      const shots = source.scenes.map((scene, index) => {
        const image = images[index % images.length];
        return {
          scene_id: scene.id,
          product_asset_id: image.id,
          product_asset_sha256: image.sha256,
          motion: MOTIONS[index % MOTIONS.length],
        };
      });
      const platform = {
        tiktok: "TIKTOK",
        youtube: "YOUTUBE_SHORTS",
        instagram: "INSTAGRAM_REELS",
      }[source.platform];
      const prepared = await prepareProductVideo(
        product.id,
        {
          variant_id: source.variant_id,
          script_version_id: source.script_version_id,
          platform,
          shots,
        },
        active.signal,
      );
      const rendered: Array<{ task: number; artifact: number }> = [];
      for (const [index, scene] of source.scenes.entries()) {
        const submitted = await submitProductImageJob(
          product.id,
          {
            video_project_id: prepared.video_project_id,
            scene_sequence: scene.sequence,
            product_asset_id: shots[index].product_asset_id,
            product_asset_sha256: shots[index].product_asset_sha256,
            motion: shots[index].motion,
            input_digest: prepared.input_digest,
          },
          active.signal,
        );
        const job = await pollExactJob(submitted.job, getExactMarketingJob, active.signal);
        rendered.push({
          task: job.source_id,
          artifact: requireSuccessfulResult(job, "video_render_artifact"),
        });
      }
      setPhase("COMPOSING");
      const compositionInput = source.scenes.map((scene, index) => ({
        sequence: scene.sequence,
        start_ms: scene.start_ms,
        end_ms: scene.end_ms,
        trim_start_ms: 0,
        trim_end_ms: scene.end_ms - scene.start_ms,
        transition_type: "cut" as const,
        render_task_id: rendered[index].task,
        artifact_id: rendered[index].artifact,
      }));
      const compositionPreflight = await preflightVideoComposition(
        product.id,
        prepared.video_project_id,
        compositionInput,
        active.signal,
      );
      const compositionSubmit = await submitVideoComposition(
        product.id,
        compositionPreflight,
        active.signal,
      );
      const compositionJob = await pollExactJob(
        compositionSubmit.job,
        getExactMarketingJob,
        active.signal,
      );
      const compositionArtifactId = requireSuccessfulResult(
        compositionJob,
        "video_composition_artifact",
      );
      const compositionArtifact = await getCompositionArtifact(
        compositionArtifactId,
        active.signal,
      );
      setPhase("VOICEOVER");
      const narration = source.scenes.map((scene) => scene.narration.trim()).join("\n");
      const digestBytes = await crypto.subtle.digest(
        "SHA-256",
        new TextEncoder().encode(narration),
      );
      const narrationDigest = Array.from(new Uint8Array(digestBytes), (byte) =>
        byte.toString(16).padStart(2, "0"),
      ).join("");
      const voiceSubmit = await submitVoiceoverJob(
        product.id,
        {
          composition_id: compositionArtifact.composition_id,
          script_version_id: source.script_version_id,
          narration_digest: narrationDigest,
          language: source.language,
          voice: "longanhuan_v3.6",
          speaking_rate: 1,
          idempotency_key: crypto.randomUUID(),
        },
        active.signal,
      );
      const voiceJob = await pollExactJob(
        voiceSubmit.job,
        getExactMarketingJob,
        active.signal,
      );
      const voiceoverArtifactId = requireSuccessfulResult(
        voiceJob,
        "video_composition_audio_artifact",
      );
      setPhase("ENHANCING");
      const enhancementPreflight = await preflightCompositionEnhancement(
        product.id,
        {
          composition_id: compositionArtifact.composition_id,
          source_artifact_id: compositionArtifact.id,
          voiceover_artifact_id: voiceoverArtifactId,
          music_artifact_id: null,
          cues: source.scenes.map((scene) => ({
            sequence: scene.sequence,
            start_ms: scene.start_ms,
            end_ms: scene.end_ms,
            text: scene.subtitle_draft,
          })),
          style: {
            font_size: 48,
            max_chars_per_line: 18,
            bottom_margin: 280,
            outline_width: 3,
          },
          mix: {
            voiceover_gain_db: 0,
            music_gain_db: -18,
            ducking_reduction_db: 12,
            target_lufs: -14,
            true_peak_db: -1,
          },
        },
        active.signal,
      );
      const enhancementSubmit = await submitCompositionEnhancement(
        product.id,
        enhancementPreflight,
        active.signal,
      );
      const enhancementJob = await pollExactJob(
        enhancementSubmit.job,
        getExactMarketingJob,
        active.signal,
      );
      const enhancementArtifactId = requireSuccessfulResult(
        enhancementJob,
        "video_composition_enhancement_artifact",
      );
      const artifact = await getCompositionEnhancementArtifact(
        enhancementArtifactId,
        active.signal,
      );
      if (operation.current.current(active.id)) {
        setResult({ video: artifact.id, subtitle: artifact.subtitle_artifact_id });
        setPhase("SUCCEEDED");
        setMessage("15秒真实商品视频已生成，旁白来自千问云配音。");
      }
    } catch (error) {
      fail(active.id, error, "真实商品视频生成失败。");
    }
  }

  async function generateCloudVideo() {
    if (!source) return;
    const active = operation.current.begin();
    setCloudVideoArtifactId(null);
    setMessage("");
    try {
      setPhase("GENERATING_IMAGES");
      const images: UploadedProductImage[] = [];
      for (const scene of source.scenes) {
        const submitted = await submitWanxProductImageJob(
          product.id,
          {
            script_version_id: source.script_version_id,
            scene_sequence: scene.sequence,
            idempotency_key: crypto.randomUUID(),
            cost_confirmed: true,
          },
          active.signal,
        );
        const job = await pollExactJob(submitted.job, getExactMarketingJob, active.signal);
        const assetId = requireSuccessfulResult(job, "product_asset");
        images.push(await getProductImageAsset(product.id, assetId, active.signal));
      }
      setPhase("PREPARING_SHOTS");
      const shots = source.scenes.map((scene, index) => ({
        scene_id: scene.id,
        product_asset_id: images[index].id,
        product_asset_sha256: images[index].sha256,
        motion: MOTIONS[index % MOTIONS.length],
      }));
      const platform = {
        tiktok: "TIKTOK",
        youtube: "YOUTUBE_SHORTS",
        instagram: "INSTAGRAM_REELS",
      }[source.platform];
      const prepared = await prepareProductVideo(
        product.id,
        {
          variant_id: source.variant_id,
          script_version_id: source.script_version_id,
          platform,
          shots,
        },
        active.signal,
      );
      setPhase("CLOUD_VIDEO");
      const referenceImages = images.map((image) => ({
        product_asset_id: image.id,
        product_asset_sha256: image.sha256,
      }));
      const preflight = await preflightHappyHorseVideo(
        product.id,
        {
          video_project_id: prepared.video_project_id,
          script_version_id: source.script_version_id,
          reference_images: referenceImages,
        },
        active.signal,
      );
      if (preflight.ready !== true) throw new Error("HappyHorse生成条件尚未满足");
      const submitted = await submitHappyHorseVideo(
        product.id,
        {
          video_project_id: prepared.video_project_id,
          script_version_id: source.script_version_id,
          reference_images: referenceImages,
          input_digest: preflight.input_digest,
          preflight_digest: preflight.preflight_digest,
          preflight_expires_at: preflight.expires_at,
          cost_confirmed: true,
        },
        active.signal,
      );
      const submitJob = await pollExactJob(
        submitted.job,
        getExactMarketingJob,
        active.signal,
      );
      const taskId = requireSuccessfulResult(submitJob, "video_render_task");
      let artifactId: number | null = null;
      for (let attempt = 0; attempt < 90 && artifactId === null; attempt += 1) {
        await new Promise<void>((resolve, reject) => {
          const timer = window.setTimeout(resolve, 2000);
          active.signal.addEventListener(
            "abort",
            () => {
              window.clearTimeout(timer);
              reject(new DOMException("Aborted", "AbortError"));
            },
            { once: true },
          );
        });
        const refresh = await refreshHappyHorseVideo(
          product.id,
          taskId,
          prepared.video_project_id,
          crypto.randomUUID(),
          active.signal,
        );
        const refreshJob = await pollExactJob(
          refresh.job,
          getExactMarketingJob,
          active.signal,
        );
        if (
          refreshJob.status === "SUCCEEDED" &&
          refreshJob.result_entity_type === "video_render_artifact" &&
          refreshJob.result_entity_id
        ) {
          artifactId = refreshJob.result_entity_id;
        } else if (refreshJob.status !== "SUCCEEDED") {
          requireSuccessfulResult(refreshJob, "video_render_artifact");
        }
      }
      if (artifactId === null) throw new Error("HappyHorse视频生成等待超时");
      if (operation.current.current(active.id)) {
        setCloudVideoArtifactId(artifactId);
        setPhase("SUCCEEDED");
        setMessage("HappyHorse 15秒商品云视频已生成。下一阶段接入千问配音与字幕。");
      }
    } catch (error) {
      fail(active.id, error, "HappyHorse商品视频生成失败。");
    }
  }

  function fail(id: number, error: unknown, fallback: string) {
    if (!operation.current.current(id)) return;
    setPhase("FAILED");
    setMessage(getApiErrorMessage(error, fallback));
  }

  return (
    <section className="video-composition-panel">
      <h4>真实商品素材15秒视频</h4>
      <p>千问脚本 · 万象商品视觉 · HappyHorse参考图生视频 · 千问云配音</p>
      <p>旁白若超过15秒会安全停止；请缩短文案后重新生成，不会裁断语音。</p>
      <label>
        Variant与激活脚本
        <select value={sourceId} onChange={(event) => setSourceId(Number(event.target.value))}>
          <option value={0}>选择精确Variant</option>
          {sources.map((item) => (
            <option key={item.variant_id} value={item.variant_id}>
              Variant #{item.variant_id} · Script #{item.script_version_id} · {item.platform}
            </option>
          ))}
        </select>
      </label>
      <p>万象将按每个分镜自动生成一致的商品广告视觉；阶段：{phase}</p>
      <button
        type="button"
        disabled={!source || !["IDLE", "FAILED"].includes(phase)}
        onClick={() => void generate()}
      >
        生成15秒视频
      </button>
      <button
        type="button"
        disabled={!source || !["IDLE", "FAILED", "SUCCEEDED"].includes(phase)}
        onClick={() => void generateCloudVideo()}
      >
        生成HappyHorse 15秒云视频
      </button>
      {cloudVideoArtifactId && (
        <div>
          <video controls src={happyHorseVideoContentUrl(cloudVideoArtifactId)} />
          <a href={happyHorseVideoContentUrl(cloudVideoArtifactId)} download>
            下载HappyHorse MP4
          </a>
        </div>
      )}
      {result && (
        <div>
          <video controls src={compositionEnhancementContentUrl(result.video)} />
          <a href={compositionEnhancementContentUrl(result.video)} download>
            下载MP4
          </a>
          <a href={compositionSubtitleContentUrl(result.subtitle)} download>
            下载WebVTT
          </a>
        </div>
      )}
      {message && <p role="status">{message}</p>}
    </section>
  );
}
