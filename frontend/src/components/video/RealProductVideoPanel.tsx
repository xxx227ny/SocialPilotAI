import { useEffect, useMemo, useRef, useState } from "react";

import { getApiErrorMessage } from "../../api/client";
import {
  createOrRecoverBatchQwenScripts,
  listBatchVideoVariants,
  preflightBatchQwenScripts,
} from "../../api/batchVideoJobs";
import {
  advanceProductVideoProductionBatch,
  cancelProductVideoProductionBatch,
  createProductVideoProductionBatch,
  getExactMarketingJob,
  getProductImageAsset,
  getProductVideoProductionBatch,
  happyHorseVideoContentUrl,
  listProductVideoSources,
  pauseProductVideoProductionBatch,
  productVideoProductionBatchDownloadUrl,
  preflightThreePlatformVideo,
  preflightHappyHorseVideo,
  prepareProductVideo,
  refreshHappyHorseVideo,
  resumeProductVideoProductionBatch,
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
  BatchQwenScriptPreflight,
  BatchQwenScriptRequest,
} from "../../types/batchVideo";
import type {
  ProductVideoProductionItem,
  ProductVideoProductionResult,
  ProductVideoSource,
  RealProductVideoPhase,
  ThreePlatformVideoPreflight,
  UploadedProductImage,
} from "../../types/productMarketingVideo";
import {
  buildThreePlatformPreflightPayload,
  buildBatchQwenScriptRequest,
  pollExactJob,
  productionBatchTerminal,
  productionBatchRecoverable,
  productionPollDelayMs,
  productionFailureMessage,
  productionProgress,
  productionStageLabel,
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
  const [batchPreflight, setBatchPreflight] =
    useState<ThreePlatformVideoPreflight | null>(null);
  const [batchCostConfirmed, setBatchCostConfirmed] = useState(false);
  const [scriptBatchId, setScriptBatchId] = useState("");
  const [strategyId, setStrategyId] = useState(0);
  const [copyMatrixId, setCopyMatrixId] = useState<number | null>(null);
  const [oneClickRequest, setOneClickRequest] =
    useState<BatchQwenScriptRequest | null>(null);
  const [oneClickPreflight, setOneClickPreflight] =
    useState<BatchQwenScriptPreflight | null>(null);
  const [oneClickCostConfirmed, setOneClickCostConfirmed] = useState(false);
  const [production, setProduction] =
    useState<ProductVideoProductionResult | null>(null);
  const [productionBatchId, setProductionBatchId] = useState("");
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
  const productionActive = Boolean(
    production && !productionBatchTerminal(production.batch, production.items),
  );

  useEffect(() => {
    operation.current.stop();
    setSources([]);
    setSourceId(0);
    setResult(null);
    setCloudVideoArtifactId(null);
    setProduction(null);
    setOneClickRequest(null);
    setOneClickPreflight(null);
    setOneClickCostConfirmed(false);
    setScriptBatchId(
      window.localStorage.getItem(`socialpilot.scriptBatch.${product.id}`) ?? "",
    );
    setProductionBatchId(
      window.localStorage.getItem(`socialpilot.productionBatch.${product.id}`) ??
        "",
    );
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
    if (!realProductVideoEnabled || isPresentation) return;
    const stored = window.localStorage.getItem(
      `socialpilot.productionBatch.${product.id}`,
    );
    const batchId = Number(stored);
    if (!Number.isInteger(batchId) || batchId <= 0) return;
    const controller = new AbortController();
    getProductVideoProductionBatch(product.id, batchId, controller.signal)
      .then((value) => {
        setProduction(value);
      })
      .catch(() => {
        window.localStorage.removeItem(`socialpilot.productionBatch.${product.id}`);
      });
    return () => controller.abort();
  }, [isPresentation, product.id]);

  useEffect(() => {
    setBatchPreflight(null);
    setBatchCostConfirmed(false);
    setOneClickPreflight(null);
    setOneClickCostConfirmed(false);
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
          voice: "longanlingxin",
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
          voice: "longanlingxin",
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

  async function checkOneClickPreflight() {
    const batchId = Number(scriptBatchId);
    if (!Number.isInteger(batchId) || batchId <= 0 || !referenceAsset) {
      setMessage("请输入精确Batch ID、Strategy ID并选择商品主参考图。");
      return;
    }
    const active = operation.current.begin();
    setOneClickRequest(null);
    setOneClickPreflight(null);
    setOneClickCostConfirmed(false);
    setMessage("正在核对三平台Variant和完整模型调用费用……");
    try {
      const variants = await listBatchVideoVariants(batchId, active.signal);
      const request = buildBatchQwenScriptRequest(
        variants,
        product.id,
        strategyId,
        copyMatrixId,
      );
      if (!request) {
        throw new Error("该Batch没有当前商品的三个READY平台Variant。");
      }
      const checked = await preflightBatchQwenScripts(
        batchId,
        request,
        active.signal,
      );
      if (!operation.current.current(active.id)) return;
      setOneClickRequest(request);
      setOneClickPreflight(checked);
      window.localStorage.setItem(
        `socialpilot.scriptBatch.${product.id}`,
        String(batchId),
      );
      setMessage(
        checked.ready_for_execution
          ? "完整链路Preflight通过，请确认模型调用次数和费用。"
          : oneClickBlockedMessage(checked),
      );
    } catch (error) {
      if (!operation.current.current(active.id)) return;
      setPhase("FAILED");
      const detail = getApiErrorMessage(error, "一键完整生产前置检查失败。");
      setMessage(
        detail === "Target-platform copy is unavailable"
          ? "所选文案矩阵缺少 YouTube 文案。请清空“可选文案矩阵编号”后重新检查，系统将使用商品与营销策略生成三平台脚本。"
          : detail,
      );
    }
  }

  async function driveBatchQwenScripts(
    batchId: number,
    request: BatchQwenScriptRequest,
    checked: BatchQwenScriptPreflight,
    active: { id: number; signal: AbortSignal },
  ) {
    for (let attempt = 0; attempt < 900; attempt += 1) {
      const current = await createOrRecoverBatchQwenScripts(
        batchId,
        request,
        checked,
        active.signal,
      );
      if (!operation.current.current(active.id)) {
        throw new DOMException("Aborted", "AbortError");
      }
      if (current.status === "READY") return current;
      if (["FAILED", "PARTIAL_FAILED"].includes(current.status)) {
        const failures = current.items
          .filter((item) => item.status === "FAILED" || item.status === "SUBMIT_UNKNOWN")
          .map((item) => `${item.platform}:${item.safe_error_code ?? item.status}`);
        throw new Error(`三平台脚本生成未完成：${failures.join("、")}`);
      }
      setMessage("千问正在生成三个平台脚本，任务可按精确Batch恢复……");
      await waitForProduction(active.signal);
    }
    throw new Error("三平台脚本等待超时，已保留Job，可稍后继续。");
  }

  async function generateOneClickBatch() {
    const batchId = Number(scriptBatchId);
    if (
      !oneClickRequest ||
      !oneClickPreflight?.ready_for_execution ||
      !oneClickCostConfirmed ||
      !referenceAsset?.sha256 ||
      !Number.isInteger(batchId) ||
      batchId <= 0
    ) {
      setMessage("请先完成完整链路Preflight并确认费用。");
      return;
    }
    const active = operation.current.begin();
    setPhase("GENERATING_SCRIPTS");
    setResult(null);
    setMessage("正在复核费用并创建三平台千问脚本Job……");
    try {
      const current = oneClickPreflight;
      await driveBatchQwenScripts(batchId, oneClickRequest, current, active);
      const refreshedSources = await listProductVideoSources(
        product.id,
        active.signal,
      );
      const selectedIds = new Set(oneClickRequest.variant_ids);
      const exactSources = selectThreePlatformSources(
        refreshedSources.filter((item) => selectedIds.has(item.variant_id)),
      );
      if (exactSources.length !== 3) {
        throw new Error("三平台脚本已生成，但精确激活来源恢复失败。");
      }
      setSources(refreshedSources);
      setSourceId(exactSources[0].variant_id);
      const payload = buildThreePlatformPreflightPayload(
        exactSources,
        referenceAsset,
      );
      if (!payload) throw new Error("三平台成片输入不完整。");
      const videoChecked = await preflightThreePlatformVideo(
        product.id,
        payload,
        active.signal,
      );
      if (
        !videoChecked.ready ||
        videoChecked.wanx_image_generation_calls !==
          current.wanx_image_generation_calls ||
        videoChecked.happyhorse_generation_calls !==
          current.happyhorse_generation_calls ||
        videoChecked.qwen_tts_generation_calls !==
          current.qwen_tts_generation_calls ||
        videoChecked.known_estimated_cost !== current.known_downstream_cost
      ) {
        throw new Error("脚本生成后的成片调用次数或费用与确认值不一致。");
      }
      setBatchPreflight(videoChecked);
      setBatchCostConfirmed(true);
      setPhase("GENERATING_IMAGES");
      const created = await createProductVideoProductionBatch(
        product.id,
        {
          ...payload,
          input_digest: videoChecked.input_digest,
          idempotency_key: `product-video-production:${product.id}:${videoChecked.input_digest}`,
          cost_confirmed: true,
        },
        active.signal,
      );
      window.localStorage.setItem(
        `socialpilot.productionBatch.${product.id}`,
        String(created.batch.id),
      );
      applyProduction(created);
      setMessage("脚本已激活，正在继续生成画面、配音、字幕和成片……");
      await driveProductionBatch(created, active);
    } catch (error) {
      fail(active.id, error, "一键完整生产失败，现有Batch和Job均已保留。");
    }
  }

  function applyProduction(value: ProductVideoProductionResult) {
    setProduction(value);
  }

  async function waitForProduction(
    signal: AbortSignal,
    items: ProductVideoProductionItem[] = [],
  ) {
    await new Promise<void>((resolve, reject) => {
      const timer = window.setTimeout(resolve, productionPollDelayMs(items));
      signal.addEventListener(
        "abort",
        () => {
          window.clearTimeout(timer);
          reject(new DOMException("Aborted", "AbortError"));
        },
        { once: true },
      );
    });
  }

  async function driveProductionBatch(
    initial: ProductVideoProductionResult,
    active: { id: number; signal: AbortSignal },
  ) {
    let current = initial;
    for (let attempt = 0; attempt < 1800; attempt += 1) {
      if (current.batch.status === "PAUSED") return;
      if (productionBatchTerminal(current.batch, current.items)) {
        applyProduction(current);
        if (current.batch.status === "SUCCEEDED") {
          setPhase("SUCCEEDED");
          setMessage("三平台完整成片已生成，可分别预览和下载。");
        } else {
          setPhase("FAILED");
          setMessage("批次已结束，失败平台保留明确原因，成功平台结果仍可下载。");
        }
        return;
      }
      current = await advanceProductVideoProductionBatch(
        product.id,
        current.batch.id,
        active.signal,
      );
      if (!operation.current.current(active.id)) return;
      applyProduction(current);
      if (!productionBatchTerminal(current.batch, current.items)) {
        await waitForProduction(active.signal, current.items);
      }
    }
    throw new Error("批量生产等待超时，已保留批次，可稍后继续。 ");
  }

  async function generateThreePlatformBatch() {
    const payload = buildThreePlatformPreflightPayload(sources, referenceAsset);
    if (
      !payload ||
      !batchPreflight?.ready ||
      !batchCostConfirmed
    ) {
      setMessage("请先完成三平台Preflight并确认费用。");
      return;
    }
    const active = operation.current.begin();
    setResult(null);
    setPhase("GENERATING_IMAGES");
    setMessage("正在创建可恢复的三平台生产批次……");
    try {
      const current = await preflightThreePlatformVideo(
        product.id,
        payload,
        active.signal,
      );
      if (!current.ready || current.input_digest !== batchPreflight.input_digest) {
        throw new Error("三平台生成条件或费用已变化，请重新检查并确认。");
      }
      const created = await createProductVideoProductionBatch(
        product.id,
        {
          ...payload,
          input_digest: current.input_digest,
          idempotency_key: `product-video-production:${product.id}:${current.input_digest}`,
          cost_confirmed: true,
        },
        active.signal,
      );
      window.localStorage.setItem(
        `socialpilot.productionBatch.${product.id}`,
        String(created.batch.id),
      );
      applyProduction(created);
      setMessage("三平台正在并行推进，刷新页面后仍可恢复此批次。");
      await driveProductionBatch(created, active);
    } catch (error) {
      fail(active.id, error, "三平台持久化生产失败。");
    }
  }

  async function continueProductionBatch() {
    if (!production) return;
    const hasUncertainVoiceover = production.items.some(
      (item) =>
        item.status === "FAILED" &&
        item.safe_error_code === "PRODUCTION_VOICEOVER_SUBMIT_UNKNOWN",
    );
    if (
      hasUncertainVoiceover &&
      !window.confirm(
        "上一次千问配音结果不确定。确认使用当前通道为失败平台创建一次替换配音？原任务记录会保留，本次可能产生一次重复费用。",
      )
    ) {
      return;
    }
    if (
      !hasUncertainVoiceover &&
      production.batch.status === "PARTIAL_FAILED" &&
      production.items.some(
        (item) =>
          item.status === "FAILED" &&
          item.safe_error_code === "PRODUCTION_VOICEOVER_FAILED",
      ) &&
      !window.confirm(
        "确认只重试失败平台的千问配音？已成功平台不会重新生成；本次可能再次调用千问 TTS 并产生费用。",
      )
    ) {
      return;
    }
    const active = operation.current.begin();
    try {
        const resumed =
          ["PAUSED", "PARTIAL_FAILED"].includes(production.batch.status)
            ? await resumeProductVideoProductionBatch(
              product.id,
              production.batch.id,
              hasUncertainVoiceover,
              active.signal,
            )
          : production;
      applyProduction(resumed);
      setMessage("已继续推进现有批次。");
      await driveProductionBatch(resumed, active);
    } catch (error) {
      fail(active.id, error, "继续批次失败。");
    }
  }

  async function recoverProductionBatch() {
    const batchId = Number(productionBatchId);
    if (!Number.isInteger(batchId) || batchId <= 0) {
      setMessage("请输入有效的生产批次编号。");
      return;
    }
    const active = operation.current.begin();
    try {
      const recovered = await getProductVideoProductionBatch(
        product.id,
        batchId,
        active.signal,
      );
      if (!operation.current.current(active.id)) return;
      window.localStorage.setItem(
        `socialpilot.productionBatch.${product.id}`,
        String(recovered.batch.id),
      );
      applyProduction(recovered);
      setMessage(
        recovered.items.some((item) => item.final_video_artifact_id !== null)
          ? "已有成片已恢复，可直接预览和下载，不会重新调用模型。"
          : "生产批次已恢复，可继续查看进度或重试失败平台。",
      );
    } catch (error) {
      fail(active.id, error, "生产批次恢复失败，请检查商品和批次编号。");
    }
  }

  async function pauseProductionBatch() {
    if (!production) return;
    const active = operation.current.begin();
    try {
      const paused = await pauseProductVideoProductionBatch(
        product.id,
        production.batch.id,
        active.signal,
      );
      applyProduction(paused);
      setMessage("批次已暂停，已完成内容和当前进度均已保留。");
    } catch (error) {
      fail(active.id, error, "暂停批次失败。");
    }
  }

  async function cancelProductionBatch() {
    if (!production) return;
    const active = operation.current.begin();
    try {
      const cancelled = await cancelProductVideoProductionBatch(
        product.id,
        production.batch.id,
        active.signal,
      );
      applyProduction(cancelled);
      setPhase("FAILED");
      setMessage("批次已取消；已生成的安全结果仍然保留。");
    } catch (error) {
      fail(active.id, error, "取消批次失败。");
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
        视频变体与已激活脚本
        <select value={sourceId} onChange={(event) => setSourceId(Number(event.target.value))}>
          <option value={0}>选择精确视频变体</option>
          {sources.map((item) => (
            <option key={item.variant_id} value={item.variant_id}>
              变体 #{item.variant_id} · 脚本 #{item.script_version_id} · {item.platform}
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
              素材 #{asset.id} · {asset.file_name}
            </option>
          ))}
        </select>
      </label>
      <fieldset>
        <legend>一键生成：三平台脚本 → 画面 → 配音 → 成片</legend>
        <p>
          使用批量任务中同一商品的 TikTok、YouTube Shorts 和 Instagram
          Reels 第一个“脚本就绪”变体；所有记录均按精确编号固定。
        </p>
        <label>
          精确批次编号
          <input
            type="number"
            min="1"
            value={scriptBatchId}
            onChange={(event) => {
              setScriptBatchId(event.target.value);
              setOneClickPreflight(null);
              setOneClickCostConfirmed(false);
            }}
          />
        </label>
        <label>
          精确营销策略编号
          <input
            type="number"
            min="1"
            value={strategyId || ""}
            onChange={(event) => {
              setStrategyId(Number(event.target.value) || 0);
              setOneClickPreflight(null);
              setOneClickCostConfirmed(false);
            }}
          />
        </label>
        <label>
          可选文案矩阵编号
          <input
            type="number"
            min="1"
            value={copyMatrixId ?? ""}
            onChange={(event) => {
              setCopyMatrixId(Number(event.target.value) || null);
              setOneClickPreflight(null);
              setOneClickCostConfirmed(false);
            }}
          />
        </label>
        <p>
          文案矩阵必须同时包含三个视频平台的文案；如果没有 YouTube 文案，请将此项留空。
        </p>
        <button
          type="button"
          disabled={
            !referenceAsset ||
            strategyId <= 0 ||
            !["IDLE", "FAILED", "SUCCEEDED"].includes(phase)
          }
          onClick={() => void checkOneClickPreflight()}
        >
          检查脚本到成片的完整调用与费用
        </button>
        {oneClickPreflight && (
          <div className="preflight-summary">
            <p>
              千问脚本 {oneClickPreflight.estimated_provider_calls} 次 · 万象图片
              {oneClickPreflight.wanx_image_generation_calls} 次 · HappyHorse视频
              {oneClickPreflight.happyhorse_generation_calls} 次 · 千问TTS
              {oneClickPreflight.qwen_tts_generation_calls} 次
            </p>
            <p>
              已知费用区间：{oneClickPreflight.total_known_cost_min}–
              {oneClickPreflight.total_known_cost_max} {oneClickPreflight.currency}。
              千问TTS尚未计价，最终总费用可能更高。
            </p>
            <p>
              视频变体：{oneClickPreflight.variant_ids.join(" / ")}；成功脚本将保持“未审核”状态，
              {oneClickPreflight.will_auto_activate_exact_results
                ? "为完成一键链路会自动激活精确版本。"
                : "需要人工激活后才能继续。"}
            </p>
            <div className="model-cost-confirmation-block">
              <label className="model-cost-confirmation">
                <input
                  type="checkbox"
                  checked={oneClickCostConfirmed}
                  disabled={!oneClickPreflight.ready_for_execution}
                  onChange={(event) =>
                    setOneClickCostConfirmed(event.target.checked)
                  }
                />
                <span>我已确认全部模型调用、已知费用区间及未计价的千问TTS</span>
              </label>
              {!oneClickPreflight.ready_for_execution && (
                <p className="model-cost-confirmation__blocked" role="alert">
                  当前检查尚未通过，因此费用确认暂时不可勾选。{oneClickBlockedMessage(oneClickPreflight)}
                </p>
              )}
            </div>
            <button
              type="button"
              disabled={
                !oneClickCostConfirmed ||
                !oneClickPreflight.ready_for_execution ||
                productionActive ||
                !["IDLE", "FAILED", "SUCCEEDED"].includes(phase)
              }
              onClick={() => void generateOneClickBatch()}
            >
              确认并一键生成三平台完整成片
            </button>
          </div>
        )}
      </fieldset>
      <p>万象将按每个分镜自动生成一致的商品广告视觉；阶段：{phaseLabel(phase)}</p>
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
          productionActive ||
          !["IDLE", "FAILED", "SUCCEEDED"].includes(phase)
        }
        onClick={() => void generateThreePlatformBatch()}
      >
        批量生成三平台完整成片
      </button>
      <p>
        三个平台独立推进：一个平台失败不会阻塞其他平台；刷新页面后可按精确批次继续。
      </p>
      <div className="production-batch-recovery">
        <label>
          恢复已有生产批次
          <input
            type="number"
            min={1}
            aria-label="已有生产批次编号"
            value={productionBatchId}
            onChange={(event) => setProductionBatchId(event.target.value)}
          />
        </label>
        <button
          type="button"
          disabled={!productionBatchId.trim()}
          onClick={() => void recoverProductionBatch()}
        >
          按批次编号加载已有成片
        </button>
        <small>恢复只读取已有结果，不会重新生成，也不会产生模型费用。</small>
      </div>
      {production && (
        <section className="production-batch-status" aria-label="三平台生产进度">
          <header>
            <strong>生产批次 #{production.batch.id}</strong>
            <span>状态：{productionBatchStatusLabel(production.batch.status)}</span>
          </header>
          <div className="production-batch-actions">
            <button
              type="button"
              disabled={!["WAITING", "RUNNING"].includes(production.batch.status)}
              onClick={() => void pauseProductionBatch()}
            >
              暂停批次
            </button>
            <button
              type="button"
              disabled={
                productionBatchTerminal(production.batch, production.items) &&
                !productionBatchRecoverable(production.batch, production.items)
              }
              onClick={() => void continueProductionBatch()}
            >
              {productionBatchRecoverable(production.batch, production.items)
                ? "重试失败平台"
                : "继续推进"}
            </button>
            <button
              type="button"
              disabled={productionBatchTerminal(
                production.batch,
                production.items,
              )}
              onClick={() => void cancelProductionBatch()}
            >
              取消批次
            </button>
          </div>
          <div className="production-platform-grid">
            {production.items.map((item) => (
              <article key={item.id} className="production-platform-card">
                <strong>{item.platform}</strong>
                <span>{productionStageLabel(item)}</span>
                <progress value={productionProgress(item)} max={100} />
                <small>{productionProgress(item)}%</small>
                {item.safe_error_code && (
                  <p role="alert">
                    {productionFailureMessage(item.safe_error_code)}
                  </p>
                )}
                {item.final_video_artifact_id && item.subtitle_artifact_id && (
                  <div>
                    <video
                      controls
                      src={compositionEnhancementContentUrl(
                        item.final_video_artifact_id,
                      )}
                    />
                    <a
                      href={compositionEnhancementContentUrl(
                        item.final_video_artifact_id,
                      )}
                      download
                    >
                      下载{item.platform} MP4
                    </a>
                    <a
                      href={compositionSubtitleContentUrl(
                        item.subtitle_artifact_id,
                      )}
                      download
                    >
                      下载{item.platform} WebVTT
                    </a>
                  </div>
                )}
              </article>
            ))}
          </div>
          {production.items.some(
            (item) =>
              item.status === "SUCCEEDED" &&
              item.final_video_artifact_id !== null &&
              item.subtitle_artifact_id !== null,
          ) && (
            <a
              className="button-link"
              href={productVideoProductionBatchDownloadUrl(
                product.id,
                production.batch.id,
              )}
              download
            >
              {production.items.filter(
                (item) =>
                  item.status === "SUCCEEDED" &&
                  item.final_video_artifact_id !== null &&
                  item.subtitle_artifact_id !== null,
              ).length === 3
                ? "批量下载三平台成片与字幕"
                : `批量下载已完成成片（${
                    production.items.filter(
                      (item) =>
                        item.status === "SUCCEEDED" &&
                        item.final_video_artifact_id !== null &&
                        item.subtitle_artifact_id !== null,
                    ).length
                  }/3）`}
            </a>
          )}
        </section>
      )}
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

function phaseLabel(phase: RealProductVideoPhase) {
  return {
    IDLE: "等待开始",
    UPLOADING: "正在上传素材",
    GENERATING_SCRIPTS: "正在生成脚本",
    GENERATING_IMAGES: "正在生成商品画面",
    PREPARING_SHOTS: "正在准备动态分镜",
    CLOUD_VIDEO: "正在生成云端视频",
    COMPOSING: "正在合成画面",
    VOICEOVER: "正在生成配音",
    ENHANCING: "正在混音和添加字幕",
    SUCCEEDED: "已完成",
    FAILED: "已失败",
  }[phase];
}

function oneClickBlockedMessage(checked: BatchQwenScriptPreflight) {
  const costMissing = checked.items.some(
    (item) =>
      item.estimated_cost_min === null ||
      item.estimated_cost_max === null ||
      item.cost_estimate_basis === null,
  );
  if (costMissing) return "千问脚本费用配置尚未就绪，请管理员先完成费用配置。";
  if (checked.items.some((item) => item.quota_remaining <= 0)) {
    return "当前批次的千问脚本额度已用完，并且没有可恢复的同一任务；请新建批次后重试。";
  }
  return "千问脚本生成条件尚未满足，请重新检查批次与脚本状态。";
}

function productionBatchStatusLabel(status: string) {
  return {
    WAITING: "等待执行",
    RUNNING: "执行中",
    PAUSED: "已暂停",
    SUCCEEDED: "已完成",
    PARTIAL_FAILED: "部分失败",
    FAILED: "已失败",
    CANCELLED: "已取消",
  }[status] ?? "状态未知";
}
