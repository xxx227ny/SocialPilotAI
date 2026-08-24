import { useEffect, useMemo, useRef, useState } from "react";

import { getApiErrorMessage } from "../../api/client";
import {
  getExactMarketingJob,
  getProductImageAsset,
  happyHorseVideoContentUrl,
  listProductVideoSources,
  preflightThreePlatformVideo,
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
  ThreePlatformVideoPreflight,
  UploadedProductImage,
} from "../../types/productMarketingVideo";
import {
  buildThreePlatformPreflightPayload,
  pollExactJob,
  RealProductVideoOperation,
  requireSuccessfulResult,
  selectThreePlatformSources,
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
  const [batchResults, setBatchResults] = useState<
    Array<{ platform: string; video: number; subtitle: number }>
  >([]);
  const [batchPreflight, setBatchPreflight] =
    useState<ThreePlatformVideoPreflight | null>(null);
  const [batchCostConfirmed, setBatchCostConfirmed] = useState(false);
  const referenceAssets = useMemo(
    () =>
      product.assets.filter(
        (asset) => asset.sha256 && asset.content_type?.startsWith("image/"),
      ),
    [product.assets],
  );
  const [referenceAssetId, setReferenceAssetId] = useState(0);
  const referenceAsset = useMemo(
    () => referenceAssets.find((asset) => asset.id === referenceAssetId) ?? null,
    [referenceAssetId, referenceAssets],
  );
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
    setBatchResults([]);
    setReferenceAssetId(referenceAssets[0]?.id ?? 0);
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
  }, [isPresentation, product.id, referenceAssets]);

  useEffect(() => {
    setBatchPreflight(null);
    setBatchCostConfirmed(false);
  }, [referenceAssetId, sources]);

  if (!realProductVideoEnabled || isPresentation) return null;

  async function generate() {
    if (!source || !referenceAsset?.sha256) return;
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
            reference_product_asset_id: referenceAsset.id,
            reference_product_asset_sha256: referenceAsset.sha256,
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

  async function generateCloudFinal(
    selectedSource: ProductVideoSource,
    active: { id: number; signal: AbortSignal },
    costConfirmed = true,
  ) {
      if (!referenceAsset?.sha256) throw new Error("请选择商品主参考图");
      setPhase("GENERATING_IMAGES");
      const images: UploadedProductImage[] = [];
      for (const scene of selectedSource.scenes) {
        const submitted = await submitWanxProductImageJob(
          product.id,
          {
            script_version_id: selectedSource.script_version_id,
            scene_sequence: scene.sequence,
            reference_product_asset_id: referenceAsset.id,
            reference_product_asset_sha256: referenceAsset.sha256,
            idempotency_key: [
              "real-product-wanx",
              product.id,
              selectedSource.script_version_id,
              scene.sequence,
              referenceAsset.id,
              referenceAsset.sha256,
            ].join(":"),
            cost_confirmed: costConfirmed,
          },
          active.signal,
        );
        const job = await pollExactJob(submitted.job, getExactMarketingJob, active.signal);
        const assetId = requireSuccessfulResult(job, "product_asset");
        images.push(await getProductImageAsset(product.id, assetId, active.signal));
      }
      setPhase("PREPARING_SHOTS");
      const shots = selectedSource.scenes.map((scene, index) => ({
        scene_id: scene.id,
        product_asset_id: images[index].id,
        product_asset_sha256: images[index].sha256,
        motion: MOTIONS[index % MOTIONS.length],
      }));
      const platform = {
        tiktok: "TIKTOK",
        youtube: "YOUTUBE_SHORTS",
        instagram: "INSTAGRAM_REELS",
      }[selectedSource.platform];
      const prepared = await prepareProductVideo(
        product.id,
        {
          variant_id: selectedSource.variant_id,
          script_version_id: selectedSource.script_version_id,
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
          script_version_id: selectedSource.script_version_id,
          reference_images: referenceImages,
        },
        active.signal,
      );
      if (preflight.ready !== true) throw new Error("HappyHorse生成条件尚未满足");
      const submitted = await submitHappyHorseVideo(
        product.id,
        {
          video_project_id: prepared.video_project_id,
          script_version_id: selectedSource.script_version_id,
          reference_images: referenceImages,
          input_digest: preflight.input_digest,
          preflight_digest: preflight.preflight_digest,
          preflight_expires_at: preflight.expires_at,
          cost_confirmed: costConfirmed,
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
      setCloudVideoArtifactId(artifactId);
      setPhase("COMPOSING");
      const compositionPreflight = await preflightVideoComposition(
        product.id,
        prepared.video_project_id,
        [
          {
            sequence: 1,
            start_ms: 0,
            end_ms: 15000,
            trim_start_ms: 0,
            trim_end_ms: 15000,
            transition_type: "cut",
            render_task_id: taskId,
            artifact_id: artifactId,
          },
        ],
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
      const compositionArtifact = await getCompositionArtifact(
        requireSuccessfulResult(compositionJob, "video_composition_artifact"),
        active.signal,
      );
      setPhase("VOICEOVER");
      const narration = selectedSource.scenes
        .map((scene) => scene.narration.trim())
        .join("\n");
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
          script_version_id: selectedSource.script_version_id,
          narration_digest: narrationDigest,
          language: selectedSource.language,
          voice: "longanhuan_v3.6",
          speaking_rate: 1,
          idempotency_key: `real-product-tts:${selectedSource.script_version_id}:${compositionArtifact.composition_id}`,
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
          cues: selectedSource.scenes.map((scene) => ({
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
      const artifact = await getCompositionEnhancementArtifact(
        requireSuccessfulResult(
          enhancementJob,
          "video_composition_enhancement_artifact",
        ),
        active.signal,
      );
      return {
        video: artifact.id,
        subtitle: artifact.subtitle_artifact_id,
        cloudVideo: artifactId,
      };
  }

  async function generateCloudVideo() {
    if (!source) return;
    const active = operation.current.begin();
    setCloudVideoArtifactId(null);
    setBatchResults([]);
    setMessage("");
    try {
      const output = await generateCloudFinal(source, active);
      if (operation.current.current(active.id)) {
        setResult({ video: output.video, subtitle: output.subtitle });
        setPhase("SUCCEEDED");
        setMessage("HappyHorse画面、千问配音和字幕混音成片已生成。");
      }
    } catch (error) {
      fail(active.id, error, "HappyHorse完整商品视频生成失败。");
    }
  }

  async function checkThreePlatformPreflight() {
    const payload = buildThreePlatformPreflightPayload(sources, referenceAsset);
    if (!payload) {
      setMessage("需要三平台各一个激活脚本，并选择商品主参考图。");
      return;
    }
    const active = operation.current.begin();
    setBatchPreflight(null);
    setBatchCostConfirmed(false);
    setMessage("正在检查三平台调用次数、费用和执行条件……");
    try {
      const checked = await preflightThreePlatformVideo(
        product.id,
        payload,
        active.signal,
      );
      if (!operation.current.current(active.id)) return;
      setBatchPreflight(checked);
      setMessage(
        checked.ready
          ? "三平台生成条件已满足，请核对调用与费用后确认。"
          : `三平台生成条件未满足：${checked.missing_requirements.join("、")}`,
      );
    } catch (error) {
      fail(active.id, error, "三平台生成条件检查失败。");
    }
  }

  async function generateThreePlatformBatch() {
    const selected = selectThreePlatformSources(sources);
    const payload = buildThreePlatformPreflightPayload(sources, referenceAsset);
    if (
      selected.length !== 3 ||
      !payload ||
      !batchPreflight?.ready ||
      !batchCostConfirmed
    ) {
      setMessage("请先完成三平台Preflight并确认费用。");
      return;
    }
    const active = operation.current.begin();
    setResult(null);
    setBatchResults([]);
    setMessage("三平台批量将按顺序执行，任一失败即停止。每个平台包含万象图、HappyHorse视频和千问TTS调用。");
    try {
      const current = await preflightThreePlatformVideo(
        product.id,
        payload,
        active.signal,
      );
      if (!current.ready || current.input_digest !== batchPreflight.input_digest) {
        throw new Error("三平台生成条件或费用已变化，请重新检查并确认。");
      }
      const completed: Array<{ platform: string; video: number; subtitle: number }> = [];
      for (const selectedSource of selected) {
        const output = await generateCloudFinal(
          selectedSource,
          active,
          batchCostConfirmed,
        );
        completed.push({
          platform: selectedSource.platform,
          video: output.video,
          subtitle: output.subtitle,
        });
        if (operation.current.current(active.id)) setBatchResults([...completed]);
      }
      if (operation.current.current(active.id)) {
        setPhase("SUCCEEDED");
        setMessage("TikTok、YouTube Shorts和Instagram Reels三条完整成片已生成。");
      }
    } catch (error) {
      fail(active.id, error, "三平台批量成片在首个失败处停止。");
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
      <label>
        商品主参考图（所有分镜冻结复用）
        <select
          value={referenceAssetId}
          onChange={(event) => setReferenceAssetId(Number(event.target.value))}
        >
          <option value={0}>选择商品主参考图</option>
          {referenceAssets.map((asset) => (
            <option key={asset.id} value={asset.id}>
              Asset #{asset.id} · {asset.file_name}
            </option>
          ))}
        </select>
      </label>
      <p>万象将按每个分镜自动生成一致的商品广告视觉；阶段：{phase}</p>
      <button
        type="button"
        disabled={!source || !referenceAsset || !["IDLE", "FAILED"].includes(phase)}
        onClick={() => void generate()}
      >
        生成15秒视频
      </button>
      <button
        type="button"
        disabled={
          !source ||
          !referenceAsset ||
          !["IDLE", "FAILED", "SUCCEEDED"].includes(phase)
        }
        onClick={() => void generateCloudVideo()}
      >
        生成单平台完整云成片
      </button>
      <button
        type="button"
        disabled={
          selectThreePlatformSources(sources).length !== 3 ||
          !referenceAsset ||
          !["IDLE", "FAILED", "SUCCEEDED"].includes(phase)
        }
        onClick={() => void checkThreePlatformPreflight()}
      >
        检查三平台调用与费用
      </button>
      {batchPreflight && (
        <div className="preflight-summary">
          <p>
            万象图片生成 {batchPreflight.wanx_image_generation_calls} 次 ·
            HappyHorse视频生成 {batchPreflight.happyhorse_generation_calls} 次 ·
            千问TTS {batchPreflight.qwen_tts_generation_calls} 次
          </p>
          <p>
            已知预计费用：{batchPreflight.known_estimated_cost} {batchPreflight.currency}。
            千问TTS费用尚未配置，因此该金额不是完整总费用。
          </p>
          <label>
            <input
              type="checkbox"
              checked={batchCostConfirmed}
              disabled={!batchPreflight.ready}
              onChange={(event) => setBatchCostConfirmed(event.target.checked)}
            />
            我已确认上述调用次数、已知费用及未计价的千问TTS调用
          </label>
        </div>
      )}
      <button
        type="button"
        disabled={
          selectThreePlatformSources(sources).length !== 3 ||
          !referenceAsset ||
          !batchPreflight?.ready ||
          !batchCostConfirmed ||
          !["IDLE", "FAILED", "SUCCEEDED"].includes(phase)
        }
        onClick={() => void generateThreePlatformBatch()}
      >
        批量生成三平台完整成片
      </button>
      <p>
        三平台批量将按顺序执行，每个平台会产生万象商品图、HappyHorse视频和千问TTS费用；
        任一平台失败即停止，已完成结果会保留。
      </p>
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
      {batchResults.map((item) => (
        <div key={item.platform}>
          <strong>{item.platform}</strong>
          <video controls src={compositionEnhancementContentUrl(item.video)} />
          <a href={compositionEnhancementContentUrl(item.video)} download>
            下载{item.platform} MP4
          </a>
          <a href={compositionSubtitleContentUrl(item.subtitle)} download>
            下载{item.platform} WebVTT
          </a>
        </div>
      ))}
      {message && <p role="status">{message}</p>}
    </section>
  );
}
