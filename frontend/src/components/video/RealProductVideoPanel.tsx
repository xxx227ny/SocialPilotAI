import { useEffect, useMemo, useRef, useState } from "react";

import {
  getApiErrorMessage,
  hasApiErrorMessage,
  isUnconfirmedApiMutation,
} from "../../api/client";
import {
  createBatchVideo,
  createOrRecoverBatchQwenScripts,
  getProductVideoWorkflowContext,
  listBatchVideoVariants,
  preflightBatchVideo,
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
  happyHorseVideoPreviewUrl,
  listProductVideoSources,
  pauseProductVideoProductionBatch,
  productVideoProductionBatchDownloadUrl,
  preflightThreePlatformVideo,
  preflightHappyHorseVideo,
  prepareProductVideo,
  refreshHappyHorseVideo,
  resumeProductVideoProductionBatch,
  submitHappyHorseVideo,
  submitWanxProductImageJob,
  submitVoiceoverJob,
} from "../../api/productMarketingVideo";
import {
  executeVideoProjectRender,
  getVideoRenderJob,
  getVideoRenderPreflight,
  refreshWorkspaceVideoRenderTask,
} from "../../api/videos";
import {
  getCompositionArtifact,
  preflightVideoComposition,
  submitVideoComposition,
} from "../../api/videoCompositions";
import {
  compositionEnhancementContentUrl,
  compositionEnhancementPreviewUrl,
  compositionSubtitleContentUrl,
  getCompositionEnhancementArtifact,
  preflightCompositionEnhancement,
  submitCompositionEnhancement,
} from "../../api/videoCompositionEnhancements";
import { realProductVideoEnabled } from "../../config/features";
import { usePresentationMode } from "../../context/PresentationModeContext";
import type { Product } from "../../types/product";
import type {
  BatchPlatform,
  BatchQwenScriptPreflight,
  BatchQwenScriptRequest,
  BatchVideoRequest,
  BatchVideoVariant,
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
  buildSinglePlatformPreflightPayload,
  buildSinglePlatformQwenScriptRequest,
  pollExactJob,
  preflightBatchScriptsWithCopyFallback,
  productionBatchTerminal,
  productionBatchRecoverable,
  productionPollDelayMs,
  productionFailureMessage,
  productionProgress,
  productionStageLabel,
  RealProductVideoOperation,
  oneClickBatchRequirementMessage,
  requireSuccessfulResult,
  selectNewestProductionSnapshot,
  selectThreePlatformSources,
  shouldMonitorProductionBatch,
} from "./realProductVideoState";
import { newBatchIdempotencyKey } from "./batchVideoJobState";

const MOTIONS = ["zoom_in", "pan_right", "zoom_out", "pan_left"] as const;

export function RealProductVideoPanel({ product }: { product: Product }) {
  const { isPresentation } = usePresentationMode();
  const operation = useRef(new RealProductVideoOperation());
  const workflowContextOperation = useRef(new RealProductVideoOperation());
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
  const [oneClickFeedback, setOneClickFeedback] = useState("");
  const [singlePlatform, setSinglePlatform] =
    useState<BatchPlatform>("tiktok");
  const [singleRequest, setSingleRequest] =
    useState<BatchQwenScriptRequest | null>(null);
  const [singlePreflight, setSinglePreflight] =
    useState<BatchQwenScriptPreflight | null>(null);
  const [singleCostConfirmed, setSingleCostConfirmed] = useState(false);
  const [singleFeedback, setSingleFeedback] = useState("");
  const [production, setProduction] =
    useState<ProductVideoProductionResult | null>(null);
  const [productionBatchId, setProductionBatchId] = useState("");
  const [productionRefreshing, setProductionRefreshing] = useState(false);
  const [productionRefreshError, setProductionRefreshError] = useState("");
  const [productionLastReadAt, setProductionLastReadAt] = useState("");
  const [workflowContextLoading, setWorkflowContextLoading] = useState(false);
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
    const storedResult = window.localStorage.getItem(
      `socialpilot.videoResult.${product.id}`,
    );
    try {
      const parsed = storedResult
        ? (JSON.parse(storedResult) as { video?: unknown; subtitle?: unknown })
        : null;
      if (
        parsed &&
        Number.isInteger(parsed.video) &&
        Number(parsed.video) > 0 &&
        Number.isInteger(parsed.subtitle) &&
        Number(parsed.subtitle) > 0
      ) {
        setResult({
          video: Number(parsed.video),
          subtitle: Number(parsed.subtitle),
        });
        setPhase("SUCCEEDED");
      } else {
        setResult(null);
        setPhase("IDLE");
      }
    } catch {
      setResult(null);
      setPhase("IDLE");
    }
    setCloudVideoArtifactId(null);
    setProduction(null);
    setOneClickRequest(null);
    setOneClickPreflight(null);
    setOneClickCostConfirmed(false);
    setOneClickFeedback("");
    setSingleRequest(null);
    setSinglePreflight(null);
    setSingleCostConfirmed(false);
    setSingleFeedback("");
    setScriptBatchId(
      window.localStorage.getItem(`socialpilot.scriptBatch.${product.id}`) ?? "",
    );
    setStrategyId(
      Number(
        window.localStorage.getItem(`socialpilot.videoStrategy.${product.id}`),
      ) || 0,
    );
    const storedCopyMatrixId = Number(
      window.localStorage.getItem(`socialpilot.videoCopyMatrix.${product.id}`),
    );
    setCopyMatrixId(storedCopyMatrixId > 0 ? storedCopyMatrixId : null);
    setProductionBatchId(
      window.localStorage.getItem(`socialpilot.productionBatch.${product.id}`) ??
        "",
    );
    if (!realProductVideoEnabled || isPresentation) return;
    void refreshWorkflowContext(true);
    const active = operation.current.begin();
    listProductVideoSources(product.id, active.signal)
      .then((items) => {
        if (operation.current.current(active.id)) {
          setSources(items);
          const storedSourceId = Number(
            window.localStorage.getItem(`socialpilot.videoSource.${product.id}`),
          );
          setSourceId(
            items.some((item) => item.variant_id === storedSourceId)
              ? storedSourceId
              : (items[0]?.variant_id ?? 0),
          );
        }
      })
      .catch((error) => {
        if (operation.current.current(active.id)) {
          setMessage(getApiErrorMessage(error, "可用Variant读取失败。"));
        }
    });
    return () => {
      operation.current.stop();
      workflowContextOperation.current.stop();
    };
  }, [isPresentation, product.id]);

  useEffect(() => {
    const storedReferenceId = Number(
      window.localStorage.getItem(`socialpilot.videoReference.${product.id}`),
    );
    setReferenceAssetId(
      referenceAssets.some((asset) => asset.id === storedReferenceId)
        ? storedReferenceId
        : (referenceAssets[0]?.id ?? 0),
    );
  }, [product.id, referenceAssets]);

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
        applyProduction(value);
        setProductionBatchId(String(value.batch.id));
        if (value.batch.status === "SUCCEEDED") {
          setPhase("SUCCEEDED");
          setMessage("已恢复上次成片和下载结果。");
        } else if (productionBatchTerminal(value.batch, value.items)) {
          setPhase("FAILED");
          setMessage("已恢复上次生产批次；可查看失败原因或恢复原任务。");
        } else {
          setPhase("GENERATING_IMAGES");
          setMessage("已恢复正在进行的视频生产批次，可继续推进。");
        }
      })
      .catch(() => {
        setMessage("上次生产批次暂时读取失败，编号已保留，可稍后重新加载。");
      });
    return () => controller.abort();
  }, [isPresentation, product.id]);

  useEffect(() => {
    if (
      !production ||
      isPresentation ||
      !shouldMonitorProductionBatch(production.batch, production.items)
    ) {
      return;
    }
    let disposed = false;
    let timer = 0;
    let controller: AbortController | null = null;
    let refreshSequence = 0;

    const schedule = (delay: number) => {
      timer = window.setTimeout(() => void refresh(), delay);
    };
    const refresh = async () => {
      controller?.abort();
      const currentController = new AbortController();
      const currentSequence = ++refreshSequence;
      controller = currentController;
      setProductionRefreshing(true);
      try {
        const refreshed = await getProductVideoProductionBatch(
          product.id,
          production.batch.id,
          currentController.signal,
        );
        if (disposed || currentSequence !== refreshSequence) return;
        applyProduction(refreshed);
        setProductionRefreshError("");
        if (productionBatchTerminal(refreshed.batch, refreshed.items)) {
          setPhase(refreshed.batch.status === "SUCCEEDED" ? "SUCCEEDED" : "FAILED");
          setMessage(
            refreshed.batch.status === "SUCCEEDED"
              ? refreshed.items.length === 1
                ? "单平台完整成片已生成，可以预览和下载。"
                : "三平台完整成片已生成，可分别预览和下载。"
              : "批次已结束，失败平台保留明确原因，成功平台结果仍可下载。",
          );
          return;
        }
        schedule(productionPollDelayMs(refreshed.items));
      } catch (error) {
        if (
          disposed ||
          currentController.signal.aborted ||
          currentSequence !== refreshSequence
        ) {
          return;
        }
        setProductionRefreshError(
          getApiErrorMessage(error, "自动刷新暂时中断；不会重复提交任务或产生费用。"),
        );
        schedule(10_000);
      } finally {
        if (!disposed && currentSequence === refreshSequence) {
          setProductionRefreshing(false);
        }
      }
    };
    const refreshWhenVisible = () => {
      if (document.visibilityState !== "visible") return;
      window.clearTimeout(timer);
      void refresh();
    };

    schedule(productionPollDelayMs(production.items));
    window.addEventListener("online", refreshWhenVisible);
    document.addEventListener("visibilitychange", refreshWhenVisible);
    return () => {
      disposed = true;
      window.clearTimeout(timer);
      controller?.abort();
      window.removeEventListener("online", refreshWhenVisible);
      document.removeEventListener("visibilitychange", refreshWhenVisible);
    };
  }, [isPresentation, product.id, production?.batch.id, production?.batch.status]);

  useEffect(() => {
    setBatchPreflight(null);
    setBatchCostConfirmed(false);
    setOneClickPreflight(null);
    setOneClickCostConfirmed(false);
    setOneClickFeedback("");
    setSingleRequest(null);
    setSinglePreflight(null);
    setSingleCostConfirmed(false);
    setSingleFeedback("");
  }, [referenceAssetId, sources]);

  if (!realProductVideoEnabled || isPresentation) return null;

  async function refreshWorkflowContext(silent = false) {
    const active = workflowContextOperation.current.begin();
    setWorkflowContextLoading(true);
    if (!silent) {
      const feedback = "正在自动匹配当前商品的最新可用生产资料……";
      setMessage(feedback);
      setOneClickFeedback(feedback);
      setSingleFeedback(feedback);
    }
    try {
      const context = await getProductVideoWorkflowContext(
        product.id,
        active.signal,
      );
      if (!workflowContextOperation.current.current(active.id)) return;
      setScriptBatchId(context.batch_id ? String(context.batch_id) : "");
      setStrategyId(context.strategy_id ?? 0);
      setCopyMatrixId(context.copy_matrix_id);
      setReferenceAssetId(context.reference_asset_id ?? 0);
      saveWorkflowContextValue(
        `socialpilot.scriptBatch.${product.id}`,
        context.batch_id,
      );
      saveWorkflowContextValue(
        `socialpilot.videoStrategy.${product.id}`,
        context.strategy_id,
      );
      saveWorkflowContextValue(
        `socialpilot.videoCopyMatrix.${product.id}`,
        context.copy_matrix_id,
      );
      saveWorkflowContextValue(
        `socialpilot.videoReference.${product.id}`,
        context.reference_asset_id,
      );
      setOneClickRequest(null);
      setOneClickPreflight(null);
      setOneClickCostConfirmed(false);
      setSingleRequest(null);
      setSinglePreflight(null);
      setSingleCostConfirmed(false);
      const missingLabels: Record<string, string> = {
        three_platform_batch: "三平台批量任务",
        marketing_strategy: "营销策略",
        reference_image: "商品主参考图",
      };
      const feedback = context.ready
        ? "已自动匹配最新三平台批次、营销策略和商品主图，无需手填内部编号。"
        : `自动匹配完成；请先补齐：${context.missing_requirements
            .map((item) => missingLabels[item] ?? item)
            .join("、")}。`;
      setMessage(feedback);
      setOneClickFeedback(feedback);
      setSingleFeedback(feedback);
    } catch (error) {
      if (workflowContextOperation.current.current(active.id)) {
        const feedback = getApiErrorMessage(
          error,
          "自动匹配生产资料失败，仍可手动填写精确编号。",
        );
        setMessage(feedback);
        setOneClickFeedback(feedback);
        setSingleFeedback(feedback);
      }
    } finally {
      if (workflowContextOperation.current.current(active.id)) {
        setWorkflowContextLoading(false);
      }
    }
  }

  async function generate() {
    if (!source || !referenceAsset?.sha256) return;
    const active = operation.current.begin();
    setResult(null);
    setMessage("");
    try {
      setPhase("PREPARING_SHOTS");
      const shots = source.scenes.map((scene, index) => ({
          scene_id: scene.id,
          product_asset_id: referenceAsset.id,
          product_asset_sha256: referenceAsset.sha256,
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
      const dynamic = await generateWanxDynamicVideo(
        prepared.video_project_id,
        { id: referenceAsset.id, sha256: referenceAsset.sha256 },
        active,
      );
      setPhase("COMPOSING");
      const compositionInput = [{
        sequence: 1,
        start_ms: 0,
        end_ms: 15000,
        trim_start_ms: 0,
        trim_end_ms: 15000,
        transition_type: "cut" as const,
        render_task_id: dynamic.taskId,
        artifact_id: dynamic.artifactId,
      }];
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
      const voiceSubmit = await submitVoiceoverJob(
        product.id,
        {
          composition_id: compositionArtifact.composition_id,
          script_version_id: source.script_version_id,
          narration_digest: source.narration_digest,
          language: source.language,
          voice: "longanlingxin",
          speaking_rate: 1,
          idempotency_key:
            `real-product-video:${source.script_version_id}:` +
            `${compositionArtifact.composition_id}:voiceover-v1`,
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
        saveFinalResult(artifact.id, artifact.subtitle_artifact_id);
        setPhase("SUCCEEDED");
        setMessage("15秒万象动态商品视频已生成，旁白来自千问云配音。");
      }
    } catch (error) {
      fail(active.id, error, "真实商品视频生成失败。");
    }
  }

  async function generateWanxDynamicVideo(
    videoProjectId: number,
    reference: { id: number; sha256: string },
    active: { id: number; signal: AbortSignal },
  ) {
    const preflight = await getVideoRenderPreflight(videoProjectId, active.signal);
    if (!preflight.ready_for_execution) {
      throw new Error(`万象视频生成条件未满足：${preflight.missing_requirements.join("、")}`);
    }
    const submitted = await executeVideoProjectRender(
      videoProjectId,
      {
        product_id: preflight.product_id,
        marketing_strategy_id: preflight.marketing_strategy_id,
        copy_matrix_id: preflight.copy_matrix_id,
        input_digest: preflight.input_digest,
        preflight_digest: preflight.preflight_digest,
        preflight_expires_at: preflight.expires_at,
        cost_confirmed: true,
        render_mode: "product_reference",
        reference_product_asset_id: reference.id,
        reference_product_asset_sha256: reference.sha256,
      },
      active.signal,
    );
    const submitJob = await pollExactJob(
      submitted.job,
      getVideoRenderJob,
      active.signal,
    );
    const taskId = requireSuccessfulResult(submitJob, "video_render_task");
    for (let attempt = 0; attempt < 90; attempt += 1) {
      await waitForProduction(active.signal);
      const refreshed = await refreshWorkspaceVideoRenderTask(
        taskId,
        {
          video_project_id: videoProjectId,
          refresh_request_id: `product-i2v:${taskId}:${crypto.randomUUID()}`,
        },
        active.signal,
      );
      const refreshJob = await pollExactJob(
        refreshed.job,
        getVideoRenderJob,
        active.signal,
      );
      if (
        refreshJob.status === "SUCCEEDED" &&
        refreshJob.result_entity_type === "video_render_artifact" &&
        refreshJob.result_entity_id
      ) {
        return { taskId, artifactId: refreshJob.result_entity_id };
      }
      if (refreshJob.status !== "SUCCEEDED") {
        requireSuccessfulResult(refreshJob, "video_render_artifact");
      }
    }
    throw new Error("万象动态视频生成等待超时，任务已保留，可稍后恢复。");
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
      const voiceSubmit = await submitVoiceoverJob(
        product.id,
        {
          composition_id: compositionArtifact.composition_id,
          script_version_id: selectedSource.script_version_id,
          narration_digest: selectedSource.narration_digest,
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
        saveFinalResult(output.video, output.subtitle);
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
    let batchId = Number(scriptBatchId);
    const inputIssue = oneClickPreflightInputIssue(
      strategyId,
      Boolean(referenceAsset),
    );
    if (inputIssue) {
      setMessage(inputIssue);
      setOneClickFeedback(inputIssue);
      return;
    }
    const active = operation.current.begin();
    setOneClickRequest(null);
    setOneClickPreflight(null);
    setOneClickCostConfirmed(false);
    const checkingMessage = "正在核对三平台脚本和完整模型调用费用……";
    setMessage(checkingMessage);
    setOneClickFeedback(checkingMessage);
    try {
      let variants = Number.isInteger(batchId) && batchId > 0
        ? await listBatchVideoVariants(batchId, active.signal)
        : [];
      let request = buildBatchQwenScriptRequest(
        variants,
        product.id,
        strategyId,
        copyMatrixId,
      );
      let createdFreshBatch = false;
      if (!request) {
        const fresh = await createFreshScriptBatch(
          ["youtube", "tiktok", "instagram"],
          active,
        );
        batchId = fresh.batchId;
        variants = fresh.variants;
        createdFreshBatch = true;
        request = buildBatchQwenScriptRequest(
          variants,
          product.id,
          strategyId,
          copyMatrixId,
        );
        if (!request) {
          throw new Error(
            oneClickBatchRequirementMessage(variants, product.id, batchId) ??
              "全新脚本批次不满足三平台生成条件。",
          );
        }
      }
      let fallback = await preflightBatchScriptsWithCopyFallback(
        request,
        (current) =>
          preflightBatchQwenScripts(batchId, current, active.signal),
        (error) =>
          hasApiErrorMessage(error, "Target-platform copy is unavailable"),
      );
      if (
        !fallback.checked.ready_for_execution &&
        fallback.checked.items.some((item) => item.quota_remaining <= 0)
      ) {
        const fresh = await createFreshScriptBatch(
          ["youtube", "tiktok", "instagram"],
          active,
        );
        batchId = fresh.batchId;
        const freshRequest = buildBatchQwenScriptRequest(
          fresh.variants,
          product.id,
          strategyId,
          fallback.request.copy_matrix_id,
        );
        if (!freshRequest) {
          throw new Error("全新脚本批次未能准备三平台变体。");
        }
        fallback = await preflightBatchScriptsWithCopyFallback(
          freshRequest,
          (current) =>
            preflightBatchQwenScripts(batchId, current, active.signal),
          (error) =>
            hasApiErrorMessage(error, "Target-platform copy is unavailable"),
        );
        createdFreshBatch = true;
      }
      const checked = fallback.checked;
      if (fallback.ignoredIncompatibleCopyMatrix) {
        setCopyMatrixId(null);
        window.localStorage.removeItem(
          `socialpilot.videoCopyMatrix.${product.id}`,
        );
      }
      if (!operation.current.current(active.id)) return;
      setOneClickRequest(fallback.request);
      setOneClickPreflight(checked);
      window.localStorage.setItem(
        `socialpilot.scriptBatch.${product.id}`,
        String(batchId),
      );
      const feedback = checked.ready_for_execution
        ? createdFreshBatch
          ? "旧批次脚本额度已用完，系统已自动创建全新脚本批次；完整链路检查已通过，请确认调用次数和费用。"
          : fallback.ignoredIncompatibleCopyMatrix
          ? "文案矩阵不含 YouTube 文案，系统已自动改用商品资料与营销策略生成三平台脚本。完整链路检查已通过，请确认调用次数和费用。"
          : "完整链路检查已通过，请确认模型调用次数和费用。"
        : oneClickBlockedMessage(checked);
      setMessage(feedback);
      setOneClickFeedback(feedback);
    } catch (error) {
      if (!operation.current.current(active.id)) return;
      const feedback = getApiErrorMessage(error, "一键完整生产前置检查失败。");
      setMessage(feedback);
      setOneClickFeedback(feedback);
    }
  }

  async function checkSinglePlatformPreflight() {
    let batchId = Number(scriptBatchId);
    const inputIssue = oneClickPreflightInputIssue(
      strategyId,
      Boolean(referenceAsset),
    );
    if (inputIssue) {
      setMessage(inputIssue);
      setSingleFeedback(inputIssue);
      return;
    }
    const active = operation.current.begin();
    setSingleRequest(null);
    setSinglePreflight(null);
    setSingleCostConfirmed(false);
    const label = platformLabel(singlePlatform);
    const checkingMessage = `正在核对 ${label} 单平台脚本和完整成片费用……`;
    setMessage(checkingMessage);
    setSingleFeedback(checkingMessage);
    try {
      let variants = Number.isInteger(batchId) && batchId > 0
        ? await listBatchVideoVariants(batchId, active.signal)
        : [];
      let request = buildSinglePlatformQwenScriptRequest(
        variants,
        product.id,
        singlePlatform,
        strategyId,
        copyMatrixId,
      );
      let createdFreshBatch = false;
      if (!request) {
        const fresh = await createFreshScriptBatch([singlePlatform], active);
        batchId = fresh.batchId;
        variants = fresh.variants;
        createdFreshBatch = true;
        request = buildSinglePlatformQwenScriptRequest(
          variants,
          product.id,
          singlePlatform,
          strategyId,
          copyMatrixId,
        );
        if (!request) {
          throw new Error(`全新脚本批次未能准备 ${label} 变体。`);
        }
      }
      let fallback = await preflightBatchScriptsWithCopyFallback(
        request,
        (current) =>
          preflightBatchQwenScripts(batchId, current, active.signal),
        (error) =>
          hasApiErrorMessage(error, "Target-platform copy is unavailable"),
      );
      if (
        !fallback.checked.ready_for_execution &&
        fallback.checked.items.some((item) => item.quota_remaining <= 0)
      ) {
        const fresh = await createFreshScriptBatch([singlePlatform], active);
        batchId = fresh.batchId;
        const freshRequest = buildSinglePlatformQwenScriptRequest(
          fresh.variants,
          product.id,
          singlePlatform,
          strategyId,
          fallback.request.copy_matrix_id,
        );
        if (!freshRequest) {
          throw new Error(`全新脚本批次未能准备 ${label} 变体。`);
        }
        fallback = await preflightBatchScriptsWithCopyFallback(
          freshRequest,
          (current) =>
            preflightBatchQwenScripts(batchId, current, active.signal),
          (error) =>
            hasApiErrorMessage(error, "Target-platform copy is unavailable"),
        );
        createdFreshBatch = true;
      }
      if (!operation.current.current(active.id)) return;
      if (fallback.ignoredIncompatibleCopyMatrix) {
        setCopyMatrixId(null);
        window.localStorage.removeItem(
          `socialpilot.videoCopyMatrix.${product.id}`,
        );
      }
      setSingleRequest(fallback.request);
      setSinglePreflight(fallback.checked);
      window.localStorage.setItem(
        `socialpilot.scriptBatch.${product.id}`,
        String(batchId),
      );
      const feedback = fallback.checked.ready_for_execution
        ? createdFreshBatch
          ? `旧批次脚本额度已用完，系统已自动创建 ${label} 全新脚本批次；检查已通过，请确认费用。`
          : fallback.ignoredIncompatibleCopyMatrix
          ? `${label} 文案不在当前文案矩阵中，系统已安全改用商品资料与营销策略；检查已通过，请确认费用。`
          : `${label} 单平台完整链路检查已通过，请确认调用次数和费用。`
        : oneClickBlockedMessage(fallback.checked);
      setMessage(feedback);
      setSingleFeedback(feedback);
    } catch (error) {
      if (!operation.current.current(active.id)) return;
      const feedback = getApiErrorMessage(error, `${label} 单平台前置检查失败。`);
      setMessage(feedback);
      setSingleFeedback(feedback);
    }
  }

  async function createFreshScriptBatch(
    platforms: BatchPlatform[],
    active: { id: number; signal: AbortSignal },
  ): Promise<{ batchId: number; variants: BatchVideoVariant[] }> {
    const request: BatchVideoRequest = {
      product_ids: [product.id],
      platforms,
      variants_per_platform: 1,
      duration_seconds: 15,
      aspect_ratio: "9:16",
      language: "zh-CN",
      priority: 50,
      max_concurrency: platforms.length,
      creative_angle: null,
      idempotency_key: newBatchIdempotencyKey(),
      reuse_identical: false,
    };
    setMessage("正在自动创建全新脚本批次，不会复用旧脚本……");
    const checked = await preflightBatchVideo(request, active.signal);
    if (!checked.ready) throw new Error("全新脚本批次前置检查未通过。");
    const created = await createBatchVideo(request, checked, active.signal);
    const batchId = created.batch.id;
    setScriptBatchId(String(batchId));
    window.localStorage.setItem(
      `socialpilot.scriptBatch.${product.id}`,
      String(batchId),
    );
    let variants = created.variants;
    for (let attempt = 0; attempt < 30; attempt += 1) {
      if (!operation.current.current(active.id)) {
        throw new DOMException("Aborted", "AbortError");
      }
      if (
        variants.length === platforms.length &&
        variants.every((item) => item.status === "READY_FOR_SCRIPT")
      ) {
        return { batchId, variants };
      }
      if (
        variants.some((item) =>
          ["FAILED", "CANCELLED"].includes(item.status),
        )
      ) {
        throw new Error("全新脚本批次编排失败，未调用千问。");
      }
      await waitForUnconfirmedAdvance(active.signal);
      variants = await listBatchVideoVariants(batchId, active.signal);
    }
    throw new Error("全新脚本批次准备超时，未调用千问；稍后可重新检查。");
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
        throw new Error(`平台脚本生成未完成：${failures.join("、")}`);
      }
      setMessage(
        request.variant_ids.length === 1
          ? "千问正在生成所选平台脚本，任务可按精确批次恢复……"
          : "千问正在生成三个平台脚本，任务可按精确批次恢复……",
      );
      await waitForProduction(active.signal);
    }
    throw new Error("平台脚本等待超时，已保留任务，可稍后继续。");
  }

  async function generateSinglePlatformVideo() {
    const batchId = Number(scriptBatchId);
    if (
      !singleRequest ||
      !singlePreflight?.ready_for_execution ||
      !singleCostConfirmed ||
      !referenceAsset?.sha256 ||
      !Number.isInteger(batchId) ||
      batchId <= 0
    ) {
      setMessage("请先检查所选平台的完整链路并确认费用。");
      return;
    }
    const active = operation.current.begin();
    const label = platformLabel(singlePlatform);
    setPhase("GENERATING_SCRIPTS");
    setResult(null);
    setProduction(null);
    setMessage(`正在复核费用并生成 ${label} 脚本……`);
    try {
      const current = singlePreflight;
      await driveBatchQwenScripts(batchId, singleRequest, current, active);
      const refreshedSources = await listProductVideoSources(
        product.id,
        active.signal,
      );
      const selectedVariantId = singleRequest.variant_ids[0];
      const exactSource = refreshedSources.find(
        (item) => item.variant_id === selectedVariantId,
      );
      if (!exactSource || exactSource.platform !== singlePlatform) {
        throw new Error(`${label} 脚本已生成，但精确激活来源恢复失败。`);
      }
      setSources(refreshedSources);
      setSourceId(exactSource.variant_id);
      window.localStorage.setItem(
        `socialpilot.videoSource.${product.id}`,
        String(exactSource.variant_id),
      );
      const payload = buildSinglePlatformPreflightPayload(
        exactSource,
        referenceAsset,
      );
      if (!payload) throw new Error(`${label} 成片输入不完整。`);
      const videoChecked = await preflightThreePlatformVideo(
        product.id,
        payload,
        active.signal,
      );
      if (
        !videoChecked.ready ||
        videoChecked.wanx_image_generation_calls !==
          current.wanx_image_generation_calls ||
        videoChecked.dynamic_video_generation_calls !==
          current.dynamic_video_generation_calls ||
        videoChecked.dynamic_video_provider !== current.dynamic_video_provider ||
        videoChecked.qwen_tts_generation_calls !==
          current.qwen_tts_generation_calls ||
        videoChecked.known_estimated_cost !== current.known_downstream_cost
      ) {
        throw new Error("脚本生成后的单平台调用次数或费用与确认值不一致。");
      }
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
      setProductionBatchId(String(created.batch.id));
      applyProduction(created);
      setMessage(`${label} 正在生成画面、配音、字幕和最终成片；刷新页面后仍可恢复。`);
      await driveProductionBatch(created, active);
    } catch (error) {
      fail(active.id, error, `${label} 单平台完整生产失败，现有批次和任务均已保留。`);
    }
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
        videoChecked.dynamic_video_generation_calls !==
          current.dynamic_video_generation_calls ||
        videoChecked.dynamic_video_provider !==
          current.dynamic_video_provider ||
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
    setProduction((current) => selectNewestProductionSnapshot(current, value));
    setProductionLastReadAt(
      new Date().toLocaleTimeString("zh-CN", { hour12: false }),
    );
  }

  async function refreshProductionBatchNow() {
    if (!production || productionRefreshing) return;
    const controller = new AbortController();
    setProductionRefreshing(true);
    try {
      const refreshed = await getProductVideoProductionBatch(
        product.id,
        production.batch.id,
        controller.signal,
      );
      applyProduction(refreshed);
      setProductionRefreshError("");
      setMessage("已读取服务器上的最新批次进度；不会重新生成或产生模型费用。");
    } catch (error) {
      setProductionRefreshError(
        getApiErrorMessage(error, "进度读取失败，请检查网络后重试。"),
      );
    } finally {
      setProductionRefreshing(false);
    }
  }

  function saveFinalResult(video: number, subtitle: number) {
    const value = { video, subtitle };
    setResult(value);
    window.localStorage.setItem(
      `socialpilot.videoResult.${product.id}`,
      JSON.stringify(value),
    );
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
          setMessage(
            current.items.length === 1
              ? "单平台完整成片已生成，可以预览和下载。"
              : "三平台完整成片已生成，可分别预览和下载。",
          );
        } else {
          setPhase("FAILED");
          setMessage("批次已结束，失败平台保留明确原因，成功平台结果仍可下载。");
        }
        return;
      }
      const beforeAdvance = current;
      try {
        current = await advanceProductVideoProductionBatch(
          product.id,
          current.batch.id,
          active.signal,
        );
      } catch (error) {
        if (!isUnconfirmedApiMutation(error)) throw error;
        const recovered = await recoverUnconfirmedProductionAdvance(
          beforeAdvance,
          active,
        );
        if (!recovered) return;
        current = recovered;
      }
      if (!operation.current.current(active.id)) return;
      applyProduction(current);
      if (!productionBatchTerminal(current.batch, current.items)) {
        await waitForProduction(active.signal, current.items);
      }
    }
    throw new Error("批量生产等待超时，已保留批次，可稍后继续。 ");
  }

  function productionCheckpoint(value: ProductVideoProductionResult) {
    return JSON.stringify([
      value.batch.status,
      value.batch.updated_at,
      value.items.map((item) => [
        item.id,
        item.status,
        item.stage,
        item.updated_at,
        item.safe_error_code,
        item.final_video_artifact_id,
      ]),
    ]);
  }

  async function recoverUnconfirmedProductionAdvance(
    previous: ProductVideoProductionResult,
    active: { id: number; signal: AbortSignal },
  ): Promise<ProductVideoProductionResult | null> {
    const previousCheckpoint = productionCheckpoint(previous);
    setMessage("连接确认超时，正在安全核对同一生产批次；不会重复提交或重复计费。");
    for (let attempt = 0; attempt < 30; attempt += 1) {
      const recovered = await getProductVideoProductionBatch(
        product.id,
        previous.batch.id,
        active.signal,
      );
      if (!operation.current.current(active.id)) return null;
      applyProduction(recovered);
      if (
        productionBatchTerminal(recovered.batch, recovered.items) ||
        productionCheckpoint(recovered) !== previousCheckpoint
      ) {
        setMessage("连接已自动恢复，已按同一批次的服务端状态继续；未重复提交。");
        return recovered;
      }
      await waitForUnconfirmedAdvance(active.signal);
    }
    setMessage(
      "暂未取得本次推进的服务端确认，已停止自动提交。请按当前批次号重新读取记录核对。",
    );
    return null;
  }

  async function waitForUnconfirmedAdvance(signal: AbortSignal) {
    await new Promise<void>((resolve, reject) => {
      const timer = window.setTimeout(resolve, 2_000);
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
    const hasFailedImages = production.items.some(
      (item) =>
        item.status === "FAILED" &&
        item.safe_error_code === "PRODUCTION_WANX_IMAGE_FAILED",
    );
    const hasUncertainVoiceover = production.items.some(
      (item) =>
        item.status === "FAILED" &&
        item.safe_error_code === "PRODUCTION_VOICEOVER_SUBMIT_UNKNOWN",
    );
    const hasTimelineVoiceover = production.items.some(
      (item) =>
        item.status === "FAILED" &&
        item.safe_error_code === "PRODUCTION_VOICEOVER_EXCEEDS_TIMELINE" &&
        Number(item.stage_state_json.voiceover_timeline_retry_count ?? 0) < 1,
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
      hasFailedImages &&
      !window.confirm(
        "确认仅重试失败平台的万象商品画面？已成功画面和其他平台不会重新生成；本次会重新调用失败画面，可能产生相应费用。",
      )
    ) {
      return;
    }
    if (
      hasTimelineVoiceover &&
      !window.confirm(
        "确认只重试超时平台的千问配音？系统会保留全部旁白，通过无损变速适配到15秒；已成功平台不会重做，本次可能产生一次千问TTS费用。",
      )
    ) {
      return;
    }
    if (
      !hasUncertainVoiceover &&
      !hasTimelineVoiceover &&
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
        production.batch.status === "PAUSED" ||
        productionBatchRecoverable(production.batch, production.items)
          ? await resumeProductVideoProductionBatch(
              product.id,
              production.batch.id,
              hasUncertainVoiceover,
              hasFailedImages,
              hasTimelineVoiceover,
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
    if (
      !window.confirm(
        "确认取消当前生产批次？取消后不会继续推进；已产生的模型费用和已完成结果会保留。",
      )
    ) {
      return;
    }
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
      <header className="video-composition-panel__header">
        <div>
          <span>15 秒商品成片</span>
          <h4>真实商品视频生成</h4>
          <p>千问脚本 · 万象商品视觉与动态视频 · 千问云配音</p>
        </div>
        <p className="video-composition-panel__safety-note">
          <strong>安全时长保护</strong>
          旁白若超过15秒会安全停止；请缩短文案后重新生成，不会裁断语音。
        </p>
      </header>

      <div className="video-source-grid">
        <div className="video-source-field">
          <label>
            <span>已激活脚本</span>
            <small>首次一键生成前可为空</small>
            <select
              aria-label="已激活脚本（首次一键生成前可为空）"
              value={sourceId}
              onChange={(event) => {
                const value = Number(event.target.value);
                setSourceId(value);
                window.localStorage.setItem(
                  `socialpilot.videoSource.${product.id}`,
                  String(value),
                );
              }}
            >
              <option value={0}>选择精确视频变体</option>
              {sources.map((item) => (
                <option key={item.variant_id} value={item.variant_id}>
                  变体 #{item.variant_id} · 脚本 #{item.script_version_id} · {item.platform}
                </option>
              ))}
            </select>
          </label>
          {sources.length === 0 && (
            <p className="preflight-summary" role="status">
              当前商品还没有已激活脚本；完成下方费用确认后，系统会自动生成并激活所需版本。
            </p>
          )}
        </div>

        <div className="video-source-field">
          <label>
            <span>商品主参考图</span>
            <small>所有分镜冻结复用</small>
            <select
              aria-label="商品主参考图（所有分镜冻结复用）"
              value={referenceAssetId}
              onChange={(event) => {
                const value = Number(event.target.value);
                setReferenceAssetId(value);
                window.localStorage.setItem(
                  `socialpilot.videoReference.${product.id}`,
                  String(value),
                );
              }}
            >
              <option value={0}>选择商品主参考图</option>
              {referenceAssets.map((asset) => (
                <option key={asset.id} value={asset.id}>
                  素材 #{asset.id} · {asset.file_name}
                </option>
              ))}
            </select>
          </label>
          {referenceAssets.length === 0 && (
            <p className="preflight-summary" role="alert">
              当前商品尚未上传图片素材，请先到商品中心为该商品上传至少一张清晰主图。
            </p>
          )}
        </div>
      </div>

      <fieldset className="video-generation-workflow">
        <legend>选择生成方式</legend>
        <div className="video-workflow-setup">
          <div>
            <strong>资料已按当前商品自动匹配</strong>
            <p>
              单平台只生成所选平台；三平台会同时处理 TikTok、YouTube Shorts 和 Instagram Reels。
              首次执行不需要预先选择已激活脚本。
            </p>
          </div>
          <button
            type="button"
            disabled={workflowContextLoading || productionActive}
            onClick={() => void refreshWorkflowContext()}
          >
            {workflowContextLoading ? "正在自动匹配……" : "自动匹配最新可用资料"}
          </button>
        </div>

        <details className="video-workflow-advanced">
          <summary>高级参数：查看或调整精确编号</summary>
          <p>系统默认选择当前账号、当前商品下的最新安全匹配记录，无需手填内部编号。</p>
          <div className="video-workflow-advanced__grid">
            <label>
              精确批次编号
              <input
                type="number"
                min="1"
                value={scriptBatchId}
                onChange={(event) => {
                  setScriptBatchId(event.target.value);
                  window.localStorage.setItem(
                    `socialpilot.scriptBatch.${product.id}`,
                    event.target.value,
                  );
                  setOneClickPreflight(null);
                  setOneClickCostConfirmed(false);
                  setOneClickFeedback("");
                  setSinglePreflight(null);
                  setSingleCostConfirmed(false);
                  setSingleFeedback("");
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
                  const value = Number(event.target.value) || 0;
                  setStrategyId(value);
                  window.localStorage.setItem(
                    `socialpilot.videoStrategy.${product.id}`,
                    String(value),
                  );
                  setOneClickPreflight(null);
                  setOneClickCostConfirmed(false);
                  setOneClickFeedback("");
                  setSinglePreflight(null);
                  setSingleCostConfirmed(false);
                  setSingleFeedback("");
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
                  const value = Number(event.target.value) || null;
                  setCopyMatrixId(value);
                  if (value) {
                    window.localStorage.setItem(
                      `socialpilot.videoCopyMatrix.${product.id}`,
                      String(value),
                    );
                  } else {
                    window.localStorage.removeItem(
                      `socialpilot.videoCopyMatrix.${product.id}`,
                    );
                  }
                  setOneClickPreflight(null);
                  setOneClickCostConfirmed(false);
                  setOneClickFeedback("");
                  setSinglePreflight(null);
                  setSingleCostConfirmed(false);
                  setSingleFeedback("");
                }}
              />
            </label>
          </div>
          <p>文案矩阵为可选项；缺少平台文案时，系统会使用商品资料与营销策略生成脚本。</p>
        </details>

        <div className="video-generation-mode-grid">
          <fieldset className="video-generation-mode-card">
          <legend>生成单个平台视频</legend>
          <p>适合单独测试平台效果，只产生所选平台的模型调用与费用。</p>
          <label>
            目标平台
            <select
              value={singlePlatform}
              disabled={productionActive}
              onChange={(event) => {
                setSinglePlatform(event.target.value as BatchPlatform);
                setSingleRequest(null);
                setSinglePreflight(null);
                setSingleCostConfirmed(false);
                setSingleFeedback("");
              }}
            >
              <option value="tiktok">TikTok</option>
              <option value="youtube">YouTube Shorts</option>
              <option value="instagram">Instagram Reels</option>
            </select>
          </label>
          <button
            type="button"
            disabled={
              productionActive ||
              !["IDLE", "FAILED", "SUCCEEDED"].includes(phase)
            }
            aria-describedby="single-platform-preflight-feedback"
            onClick={() => void checkSinglePlatformPreflight()}
          >
            检查所选平台的调用与费用
          </button>
          <p
            id="single-platform-preflight-feedback"
            className="preflight-summary"
            role="status"
            aria-live="polite"
          >
            {singleFeedback ||
              oneClickPreflightInputIssue(
                strategyId,
                Boolean(referenceAsset),
              ) ||
              `将只检查并生成 ${platformLabel(singlePlatform)}；检查本身不会产生模型费用。`}
          </p>
          {singlePreflight && (
            <div className="preflight-summary">
              <p>
                仅生成 {platformLabel(singlePlatform)}：千问脚本 {singlePreflight.estimated_provider_calls} 次 ·
                万象图片 {singlePreflight.wanx_image_generation_calls} 次 · 动态视频（
                {singlePreflight.dynamic_video_model}）{singlePreflight.dynamic_video_generation_calls} 次 ·
                千问TTS {singlePreflight.qwen_tts_generation_calls} 次
              </p>
              <p>
                已知费用区间：{singlePreflight.total_known_cost_min}–
                {singlePreflight.total_known_cost_max} {singlePreflight.currency}。
                千问TTS尚未计价，最终总费用可能更高。
              </p>
              <p>视频变体：{singlePreflight.variant_ids[0]}；其他两个平台不会生成，也不会产生调用费用。</p>
              <div className="model-cost-confirmation-block">
                <label className="model-cost-confirmation">
                  <input
                    type="checkbox"
                    checked={singleCostConfirmed}
                    disabled={!singlePreflight.ready_for_execution}
                    onChange={(event) =>
                      setSingleCostConfirmed(event.target.checked)
                    }
                  />
                  <span>我已确认该平台的模型调用、已知费用区间及未计价的千问TTS</span>
                </label>
                {!singlePreflight.ready_for_execution && (
                  <p className="model-cost-confirmation__blocked" role="alert">
                    当前检查尚未通过。{oneClickBlockedMessage(singlePreflight)}
                  </p>
                )}
              </div>
              <button
                type="button"
                disabled={
                  !singleCostConfirmed ||
                  !singlePreflight.ready_for_execution ||
                  productionActive ||
                  !["IDLE", "FAILED", "SUCCEEDED"].includes(phase)
                }
                onClick={() => void generateSinglePlatformVideo()}
              >
                确认并生成 {platformLabel(singlePlatform)} 单独视频
              </button>
            </div>
          )}
          </fieldset>

          <section className="video-generation-mode-card" aria-labelledby="three-platform-video-title">
          <header>
            <span>推荐</span>
            <div>
              <h5 id="three-platform-video-title">一键生成三个平台视频</h5>
              <p>一次生成三个平台各一条完整视频；任一平台失败不会阻塞其他平台。</p>
            </div>
          </header>
          <button
            type="button"
            disabled={
              !["IDLE", "FAILED", "SUCCEEDED"].includes(phase)
            }
            aria-describedby="one-click-preflight-feedback"
            onClick={() => void checkOneClickPreflight()}
          >
            检查脚本到成片的完整调用与费用
          </button>
          <p
            id="one-click-preflight-feedback"
            className="preflight-summary"
            role="status"
            aria-live="polite"
          >
            {oneClickFeedback ||
              oneClickPreflightInputIssue(
                strategyId,
                Boolean(referenceAsset),
              ) ||
              "资料已填写，可以开始检查；检查不会生成内容或产生模型费用。"}
          </p>
          {oneClickPreflight && (
            <div className="preflight-summary">
              <p>
                千问脚本 {oneClickPreflight.estimated_provider_calls} 次 · 万象图片
                {oneClickPreflight.wanx_image_generation_calls} 次 · 动态视频（
                {oneClickPreflight.dynamic_video_model}）
                {oneClickPreflight.dynamic_video_generation_calls} 次 · 千问TTS
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
          </section>
        </div>
      </fieldset>
      <details className="video-legacy-tools">
        <summary>已激活脚本高级入口（通常无需使用）</summary>
      <p>万象将根据商品主参考图生成真实动态商品演示；阶段：{phaseLabel(phase)}</p>
      <button
        type="button"
        disabled={
          !source ||
          !referenceAsset ||
          !["IDLE", "FAILED", "SUCCEEDED"].includes(phase)
        }
        onClick={() => void generate()}
      >
        生成15秒动态商品视频
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
            动态视频（{batchPreflight.dynamic_video_model}）生成
            {batchPreflight.dynamic_video_generation_calls} 次 ·
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
      </details>
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
        <section className="production-batch-status" aria-label="视频生产进度">
          <header>
            <strong>生产批次 #{production.batch.id}</strong>
            <span>状态：{productionBatchStatusLabel(production.batch.status)}</span>
          </header>
          <div
            className={`production-batch-monitor${
              productionRefreshError ? " production-batch-monitor--error" : ""
            }`}
            role="status"
          >
            <div>
              <strong>
                {productionRefreshError
                  ? "进度连接暂时中断"
                  : productionRefreshing
                    ? "正在读取最新进度"
                    : shouldMonitorProductionBatch(production.batch, production.items)
                      ? "进度自动刷新已开启"
                      : "当前批次无需自动刷新"}
              </strong>
              <small>
                {productionRefreshError ||
                  (productionLastReadAt
                    ? `上次成功读取：${productionLastReadAt}`
                    : "正在等待首次进度读取")}
              </small>
            </div>
            <button
              type="button"
              disabled={productionRefreshing}
              onClick={() => void refreshProductionBatchNow()}
            >
              {productionRefreshing ? "刷新中……" : "立即刷新进度"}
            </button>
          </div>
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
                    <ResilientVideoPreview
                      label={`${item.platform} 成片`}
                      previewUrl={compositionEnhancementPreviewUrl(
                        item.final_video_artifact_id,
                      )}
                      sourceUrl={compositionEnhancementContentUrl(
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
              {production.items.length === 1
                ? "下载单平台成片与字幕"
                : production.items.filter(
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
                  }/${production.items.length}）`}
            </a>
          )}
        </section>
      )}
      {cloudVideoArtifactId && (
        <div>
          <ResilientVideoPreview
            label="HappyHorse 成片"
            previewUrl={happyHorseVideoPreviewUrl(cloudVideoArtifactId)}
            sourceUrl={happyHorseVideoContentUrl(cloudVideoArtifactId)}
          />
          <a href={happyHorseVideoContentUrl(cloudVideoArtifactId)} download>
            下载HappyHorse MP4
          </a>
        </div>
      )}
      {result && (
        <div>
          <ResilientVideoPreview
            label="最终合成视频"
            previewUrl={compositionEnhancementPreviewUrl(result.video)}
            sourceUrl={compositionEnhancementContentUrl(result.video)}
          />
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

function ResilientVideoPreview({
  label,
  previewUrl,
  sourceUrl,
}: {
  label: string;
  previewUrl: string;
  sourceUrl: string;
}) {
  const [mode, setMode] = useState<"preview" | "source">("preview");
  const [failed, setFailed] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    setMode("preview");
    setFailed(false);
    setReloadKey(0);
  }, [previewUrl, sourceUrl]);

  const retry = () => {
    setMode("preview");
    setFailed(false);
    setReloadKey((value) => value + 1);
  };

  return (
    <div className="resilient-video-preview">
      <video
        key={`${mode}-${reloadKey}`}
        aria-label={label}
        controls
        playsInline
        preload="metadata"
        src={mode === "preview" ? previewUrl : sourceUrl}
        onLoadedData={() => setFailed(false)}
        onError={() => {
          if (mode === "preview") {
            setMode("source");
            setFailed(false);
          } else {
            setFailed(true);
          }
        }}
      />
      {mode === "source" && !failed ? (
        <small role="status">低码率预览暂时不可用，已切换到原始成片。</small>
      ) : null}
      {failed ? (
        <div className="resilient-video-preview__error" role="alert">
          <span>视频读取失败，请检查网络或 VPN 后重新加载。</span>
          <button type="button" onClick={retry}>重新加载视频</button>
        </div>
      ) : null}
    </div>
  );
}

function saveWorkflowContextValue(key: string, value: number | null) {
  if (value) {
    window.localStorage.setItem(key, String(value));
  } else {
    window.localStorage.removeItem(key);
  }
}

function platformLabel(platform: BatchPlatform) {
  return {
    tiktok: "TikTok",
    youtube: "YouTube Shorts",
    instagram: "Instagram Reels",
  }[platform];
}

function oneClickPreflightInputIssue(
  strategyId: number,
  hasReferenceAsset: boolean,
) {
  if (!Number.isInteger(strategyId) || strategyId <= 0) {
    return "暂时不能检查：当前商品缺少营销策略，请先在“文案矩阵”生成并保存营销策略。";
  }
  if (!hasReferenceAsset) {
    return "暂时不能检查：请选择商品主参考图；如果没有图片，请先到“商品中心”上传。";
  }
  return "";
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
