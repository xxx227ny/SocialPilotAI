import { useCallback, useEffect, useRef, useState } from "react";
import axios from "axios";

import {
  getApiErrorMessage,
  getProviderFailureDetails,
  getProviderFailureMessage,
} from "../api/client";
import {
  executeGrowthRecommendation,
  executeV2Copy,
  getFeedbackContext,
  getGrowthRecommendationPreflight,
  preflightV2Copy,
  uploadCampaignCsv,
} from "../api/growth";
import {
  copyExecutionEnabled,
  growthExecutionEnabled,
  v2CopyExecutionEnabled,
  v2VideoProjectExecutionEnabled,
} from "../config/features";
import {
  executeV2VideoProject,
  preflightV2VideoProject,
} from "../api/videos";
import type {
  V2CopyExecutionResult,
  V2CopyPreflight,
} from "../types/copy";
import type {
  CampaignMetrics,
  FeedbackContext,
  GrowthAnalysis,
  GrowthRecommendationPreflight,
  ProviderFailureDetails,
} from "../types/growth";
import type {
  V2VideoProjectExecutionResult,
  V2VideoProjectPreflight,
} from "../types/video";

interface GrowthCopilotPanelProps {
  productId: number;
  onVideoProjectGenerated?: (videoProjectId: number) => void;
}

type ContextState =
  | "loading"
  | "empty"
  | "ready"
  | "incomplete"
  | "error";
type PreflightState = "idle" | "checking" | "ready" | "blocked" | "failed";
type ExecutionState =
  | "idle"
  | "submitting"
  | "succeeded"
  | "failed"
  | "uncertain";

const MISSING_LABELS: Record<string, string> = {
  campaign_data: "Campaign投放数据",
  video_project: "VideoProject",
  marketing_strategy: "MarketingStrategy",
  copy_matrix: "CopyMatrix",
  exact_content_chain: "同一Product的精确内容链",
  supported_reference_platforms: "受支持的精确Copy/Video平台",
  provider_configuration: "Qwen Provider安全配置",
  qwen_credentials_configuration: "Qwen凭据配置",
  qwen_workspace_configuration: "Qwen Workspace配置",
  qwen_region_configuration: "Qwen Region配置",
  qwen_endpoint_configuration: "Qwen Endpoint配置",
  qwen_model_configuration: "Qwen模型配置",
  growth_execution: "Backend Growth执行开关",
  stale_context_digest: "当前FeedbackContext已变化",
  recommendation_digest_mismatch: "Recommendation摘要不匹配",
  source_content_chain_mismatch: "Recommendation源内容链不匹配",
  source_video_project_schema: "源VideoProject生产Schema无效",
  recommendation_copy_platforms: "Copy约束平台不符合精确源CopyMatrix",
  product_input: "商品生成资料不完整",
  copy_execution: "Backend Copy执行开关",
  v2_copy_execution: "Backend V2 Copy执行开关",
  candidate_copy_matrix_mismatch: "候选CopyMatrix身份或Strategy关联不匹配",
  recommendation_video_platform: "Recommendation视频平台与源VideoProject不匹配",
  candidate_copy_platform: "候选CopyMatrix缺少严格有效的目标平台文案",
  v2_video_project_execution: "Backend V2 VideoProject执行开关",
};

function isUncertainGenerationError(error: unknown): boolean {
  if (!axios.isAxiosError(error)) return false;
  if (!error.response) {
    return error.code === "ECONNABORTED" || error.code === "ETIMEDOUT";
  }
  const data = error.response.data as
    | { error?: { message?: unknown } }
    | undefined;
  return (
    [503, 504].includes(error.response.status) &&
    [
      "Qwen service is unavailable",
      "Qwen request result is uncertain",
      "Qwen provider is temporarily unavailable",
    ].includes(String(data?.error?.message ?? ""))
  );
}

export function GrowthCopilotPanel({
  productId,
  onVideoProjectGenerated,
}: GrowthCopilotPanelProps) {
  const [file, setFile] = useState<File | null>(null);
  const [context, setContext] = useState<FeedbackContext | null>(null);
  const [contextState, setContextState] =
    useState<ContextState>("loading");
  const [contextError, setContextError] = useState("");
  const [notice, setNotice] = useState("");
  const [uploading, setUploading] = useState(false);
  const [reading, setReading] = useState(false);
  const [preflight, setPreflight] =
    useState<GrowthRecommendationPreflight | null>(null);
  const [preflightState, setPreflightState] =
    useState<PreflightState>("idle");
  const [preflightError, setPreflightError] = useState("");
  const [feeConfirmed, setFeeConfirmed] = useState(false);
  const [authorizationConsumed, setAuthorizationConsumed] =
    useState(false);
  const [executionState, setExecutionState] =
    useState<ExecutionState>("idle");
  const [executionError, setExecutionError] = useState("");
  const [recommendationFailure, setRecommendationFailure] =
    useState<ProviderFailureDetails | null>(null);
  const [recommendationResult, setRecommendationResult] =
    useState<GrowthAnalysis | null>(null);
  const [v2Preflight, setV2Preflight] =
    useState<V2CopyPreflight | null>(null);
  const [v2PreflightState, setV2PreflightState] =
    useState<PreflightState>("idle");
  const [v2PreflightError, setV2PreflightError] = useState("");
  const [v2FeeConfirmed, setV2FeeConfirmed] = useState(false);
  const [v2AuthorizationConsumed, setV2AuthorizationConsumed] =
    useState(false);
  const [v2ExecutionState, setV2ExecutionState] =
    useState<ExecutionState>("idle");
  const [v2ExecutionError, setV2ExecutionError] = useState("");
  const [v2Result, setV2Result] =
    useState<V2CopyExecutionResult | null>(null);
  const [v2VideoPreflight, setV2VideoPreflight] =
    useState<V2VideoProjectPreflight | null>(null);
  const [v2VideoPreflightState, setV2VideoPreflightState] =
    useState<PreflightState>("idle");
  const [v2VideoPreflightError, setV2VideoPreflightError] = useState("");
  const [v2VideoFeeConfirmed, setV2VideoFeeConfirmed] = useState(false);
  const [v2VideoAuthorizationConsumed, setV2VideoAuthorizationConsumed] =
    useState(false);
  const [v2VideoExecutionState, setV2VideoExecutionState] =
    useState<ExecutionState>("idle");
  const [v2VideoExecutionError, setV2VideoExecutionError] = useState("");
  const [v2VideoResult, setV2VideoResult] =
    useState<V2VideoProjectExecutionResult | null>(null);
  const currentProductId = useRef(productId);
  const contextRequestId = useRef(0);
  const uploadRequestId = useRef(0);
  const contextController = useRef<AbortController | null>(null);
  const uploadController = useRef<AbortController | null>(null);
  const preflightController = useRef<AbortController | null>(null);
  const executionController = useRef<AbortController | null>(null);
  const v2PreflightController = useRef<AbortController | null>(null);
  const v2ExecutionController = useRef<AbortController | null>(null);
  const v2VideoPreflightController =
    useRef<AbortController | null>(null);
  const v2VideoExecutionController =
    useRef<AbortController | null>(null);
  const preflightRequestId = useRef(0);
  const executionRequestId = useRef(0);
  const v2PreflightRequestId = useRef(0);
  const v2ExecutionRequestId = useRef(0);
  const v2VideoPreflightRequestId = useRef(0);
  const v2VideoExecutionRequestId = useRef(0);
  const manualReadLock = useRef(false);
  const uploadLock = useRef(false);
  const preflightLock = useRef(false);
  const executionLock = useRef(false);
  const authorizationConsumedRef = useRef(false);
  const v2PreflightLock = useRef(false);
  const v2ExecutionLock = useRef(false);
  const v2AuthorizationConsumedRef = useRef(false);
  const v2VideoPreflightLock = useRef(false);
  const v2VideoExecutionLock = useRef(false);
  const v2VideoAuthorizationConsumedRef = useRef(false);

  const resetV2Video = useCallback(() => {
    v2VideoPreflightRequestId.current += 1;
    v2VideoExecutionRequestId.current += 1;
    v2VideoPreflightController.current?.abort();
    v2VideoExecutionController.current?.abort();
    v2VideoPreflightLock.current = false;
    v2VideoExecutionLock.current = false;
    v2VideoAuthorizationConsumedRef.current = false;
    setV2VideoPreflight(null);
    setV2VideoPreflightState("idle");
    setV2VideoPreflightError("");
    setV2VideoFeeConfirmed(false);
    setV2VideoAuthorizationConsumed(false);
    setV2VideoExecutionState("idle");
    setV2VideoExecutionError("");
    setV2VideoResult(null);
  }, []);

  const resetV2Copy = useCallback(() => {
    v2PreflightRequestId.current += 1;
    v2ExecutionRequestId.current += 1;
    v2PreflightController.current?.abort();
    v2ExecutionController.current?.abort();
    v2PreflightLock.current = false;
    v2ExecutionLock.current = false;
    v2AuthorizationConsumedRef.current = false;
    setV2Preflight(null);
    setV2PreflightState("idle");
    setV2PreflightError("");
    setV2FeeConfirmed(false);
    setV2AuthorizationConsumed(false);
    setV2ExecutionState("idle");
    setV2ExecutionError("");
    setV2Result(null);
    resetV2Video();
  }, [resetV2Video]);

  const resetRecommendation = useCallback(() => {
    preflightRequestId.current += 1;
    executionRequestId.current += 1;
    preflightController.current?.abort();
    executionController.current?.abort();
    preflightLock.current = false;
    executionLock.current = false;
    authorizationConsumedRef.current = false;
    setPreflight(null);
    setPreflightState("idle");
    setPreflightError("");
    setFeeConfirmed(false);
    setAuthorizationConsumed(false);
    setExecutionState("idle");
    setExecutionError("");
    setRecommendationFailure(null);
    setRecommendationResult(null);
    resetV2Copy();
  }, [resetV2Copy]);

  const readContext = useCallback(
    async (expectedProductId: number, manual: boolean) => {
      if (
        manual &&
        (manualReadLock.current ||
          executionLock.current ||
          v2ExecutionLock.current ||
          v2VideoExecutionLock.current)
      ) {
        return;
      }
      if (manual) manualReadLock.current = true;

      const requestId = ++contextRequestId.current;
      const controller = new AbortController();
      contextController.current?.abort();
      contextController.current = controller;
      setReading(manual);
      setContextState("loading");
      setContextError("");

      try {
        const result = await getFeedbackContext(
          expectedProductId,
          controller.signal,
        );
        if (
          controller.signal.aborted ||
          requestId !== contextRequestId.current ||
          currentProductId.current !== expectedProductId ||
          result.product_id !== expectedProductId
        ) {
          return;
        }
        resetRecommendation();
        setContext(result);
        setContextState(
          result.campaign_count === 0
            ? "empty"
            : result.context_ready
              ? "ready"
              : "incomplete",
        );
      } catch (error) {
        if (
          controller.signal.aborted ||
          requestId !== contextRequestId.current ||
          currentProductId.current !== expectedProductId
        ) {
          return;
        }
        setContext(null);
        setContextState("error");
        setContextError(
          getApiErrorMessage(
            error,
            "FeedbackContext读取失败，请检查Backend连接后重试。",
          ),
        );
      } finally {
        if (requestId === contextRequestId.current) {
          setReading(false);
        }
        if (manual) manualReadLock.current = false;
      }
    },
    [resetRecommendation],
  );

  useEffect(() => {
    currentProductId.current = productId;
    setFile(null);
    setNotice("");
    setContext(null);
    setContextError("");
    resetRecommendation();
    uploadRequestId.current += 1;
    uploadController.current?.abort();
    uploadLock.current = false;
    setUploading(false);
    void readContext(productId, false);

    return () => {
      contextController.current?.abort();
      uploadController.current?.abort();
      preflightController.current?.abort();
      executionController.current?.abort();
      v2PreflightController.current?.abort();
      v2ExecutionController.current?.abort();
      v2VideoPreflightController.current?.abort();
      v2VideoExecutionController.current?.abort();
    };
  }, [productId, readContext, resetRecommendation]);

  async function handleUpload() {
    if (
      !file ||
      uploadLock.current ||
      executionLock.current ||
      v2ExecutionLock.current ||
      v2VideoExecutionLock.current
    )
      return;
    uploadLock.current = true;
    const expectedProductId = productId;
    const requestId = ++uploadRequestId.current;
    const controller = new AbortController();
    uploadController.current?.abort();
    uploadController.current = controller;
    setUploading(true);
    setNotice("");
    resetRecommendation();

    try {
      const result = await uploadCampaignCsv(
        expectedProductId,
        file,
        controller.signal,
      );
      if (
        controller.signal.aborted ||
        requestId !== uploadRequestId.current ||
        currentProductId.current !== expectedProductId ||
        result.product_id !== expectedProductId
      ) {
        return;
      }
      setNotice(
        `已导入${result.imported_count}条Campaign记录；本操作未调用AI。`,
      );
      setFile(null);
      await readContext(expectedProductId, false);
    } catch (error) {
      if (
        controller.signal.aborted ||
        requestId !== uploadRequestId.current ||
        currentProductId.current !== expectedProductId
      ) {
        return;
      }
      setNotice(
        getApiErrorMessage(
          error,
          "Campaign CSV导入失败，请检查字段、格式和数据范围。",
        ),
      );
    } finally {
      if (requestId === uploadRequestId.current) {
        setUploading(false);
        uploadLock.current = false;
      }
    }
  }

  async function handlePreflight() {
    if (
      !context ||
      preflightLock.current ||
      executionLock.current ||
      v2ExecutionLock.current ||
      v2VideoExecutionLock.current
    ) {
      return;
    }
    preflightLock.current = true;
    const expectedProductId = productId;
    const expectedContext = context;
    const requestId = ++preflightRequestId.current;
    const controller = new AbortController();
    preflightController.current?.abort();
    preflightController.current = controller;
    setPreflightState("checking");
    setPreflightError("");
    setFeeConfirmed(false);
    setExecutionState("idle");
    setExecutionError("");
    setRecommendationFailure(null);
    setRecommendationResult(null);
    try {
      const result = await getGrowthRecommendationPreflight(
        expectedProductId,
        controller.signal,
      );
      if (
        controller.signal.aborted ||
        requestId !== preflightRequestId.current ||
        currentProductId.current !== expectedProductId ||
        !samePreflightIdentity(result, expectedContext)
      ) {
        return;
      }
      setPreflight(result);
      setPreflightState(result.ready_for_execution ? "ready" : "blocked");
      authorizationConsumedRef.current = false;
      setAuthorizationConsumed(false);
    } catch (error) {
      if (
        controller.signal.aborted ||
        requestId !== preflightRequestId.current ||
        currentProductId.current !== expectedProductId
      ) {
        return;
      }
      setPreflight(null);
      setPreflightState("failed");
      setPreflightError(
        getApiErrorMessage(
          error,
          "Recommendation Preflight失败，请恢复Backend后重试。",
        ),
      );
    } finally {
      if (requestId === preflightRequestId.current) {
        preflightLock.current = false;
      }
    }
  }

  const canExecute = Boolean(
    growthExecutionEnabled &&
      context?.context_ready &&
      preflightState === "ready" &&
      preflight?.ready_for_execution &&
      preflight &&
      context &&
      samePreflightIdentity(preflight, context) &&
      feeConfirmed &&
      !authorizationConsumed &&
      v2ExecutionState !== "submitting" &&
      executionState !== "submitting",
  );

  async function handleExecuteRecommendation() {
    if (
      !canExecute ||
      !context ||
      !preflight ||
      executionLock.current ||
      v2ExecutionLock.current ||
      v2VideoExecutionLock.current ||
      authorizationConsumedRef.current
    ) {
      return;
    }
    executionLock.current = true;
    authorizationConsumedRef.current = true;
    setAuthorizationConsumed(true);
    setFeeConfirmed(false);
    const expectedProductId = productId;
    const expectedContext = context;
    const requestId = ++executionRequestId.current;
    const controller = new AbortController();
    executionController.current?.abort();
    executionController.current = controller;
    setExecutionState("submitting");
    setExecutionError("");
    setRecommendationFailure(null);
    setRecommendationResult(null);
    try {
      const result = await executeGrowthRecommendation(
        expectedProductId,
        expectedContext.context_digest,
        controller.signal,
      );
      if (
        controller.signal.aborted ||
        requestId !== executionRequestId.current ||
        currentProductId.current !== expectedProductId ||
        !sameExecutionIdentity(result, expectedContext)
      ) {
        return;
      }
      resetV2Copy();
      setRecommendationResult(result);
      setExecutionState("succeeded");
      setPreflight(null);
      setPreflightState("idle");
    } catch (error) {
      if (
        controller.signal.aborted ||
        requestId !== executionRequestId.current ||
        currentProductId.current !== expectedProductId
      ) {
        return;
      }
      const providerFailure = getProviderFailureDetails(error, true);
      const uncertain =
        providerFailure?.uncertain ?? isUncertainGenerationError(error);
      setRecommendationFailure(providerFailure);
      setExecutionState(uncertain ? "uncertain" : "failed");
      setExecutionError(
        providerFailure
          ? getProviderFailureMessage(providerFailure)
          : uncertain
          ? "执行结果不确定；不会自动重试。重新执行前必须重新Preflight并确认费用。"
          : getApiErrorMessage(
              error,
              "Recommendation执行失败；不会自动重试。",
            ),
      );
      setPreflight(null);
      setPreflightState("idle");
      setFeeConfirmed(false);
    } finally {
      if (requestId === executionRequestId.current) {
        executionLock.current = false;
      }
    }
  }

  const canPreflightV2 = Boolean(
    recommendationResult &&
      context &&
      sameExecutionIdentity(recommendationResult, context) &&
      executionState !== "submitting" &&
      v2ExecutionState !== "submitting" &&
      v2ExecutionState !== "succeeded" &&
      v2ExecutionState !== "uncertain",
  );

  async function handleV2Preflight() {
    if (
      !canPreflightV2 ||
      !recommendationResult ||
      v2PreflightLock.current ||
      v2ExecutionLock.current ||
      executionLock.current ||
      v2VideoExecutionLock.current
    ) {
      return;
    }
    v2PreflightLock.current = true;
    const expectedProductId = productId;
    const expectedRecommendation = recommendationResult;
    const requestId = ++v2PreflightRequestId.current;
    const controller = new AbortController();
    v2PreflightController.current?.abort();
    v2PreflightController.current = controller;
    setV2PreflightState("checking");
    setV2PreflightError("");
    setV2FeeConfirmed(false);
    setV2AuthorizationConsumed(false);
    v2AuthorizationConsumedRef.current = false;
    setV2ExecutionState("idle");
    setV2ExecutionError("");
    setV2Result(null);
    try {
      const result = await preflightV2Copy(
        expectedProductId,
        v2SourceRequest(expectedRecommendation),
        controller.signal,
      );
      if (
        controller.signal.aborted ||
        requestId !== v2PreflightRequestId.current ||
        currentProductId.current !== expectedProductId ||
        recommendationResult !== expectedRecommendation ||
        !sameV2PreflightIdentity(
          result,
          expectedRecommendation,
          expectedProductId,
        )
      ) {
        return;
      }
      setV2Preflight(result);
      setV2PreflightState(
        result.ready_for_execution ? "ready" : "blocked",
      );
    } catch (error) {
      if (
        controller.signal.aborted ||
        requestId !== v2PreflightRequestId.current ||
        currentProductId.current !== expectedProductId
      ) {
        return;
      }
      setV2Preflight(null);
      setV2PreflightState("failed");
      setV2PreflightError(
        getApiErrorMessage(
          error,
          "V2 Copy Preflight失败，请重新读取Context后重试。",
        ),
      );
    } finally {
      if (requestId === v2PreflightRequestId.current) {
        v2PreflightLock.current = false;
      }
    }
  }

  const canExecuteV2 = Boolean(
    recommendationResult &&
      v2Preflight &&
      v2PreflightState === "ready" &&
      v2Preflight.ready_for_execution &&
      sameV2PreflightIdentity(
        v2Preflight,
        recommendationResult,
        productId,
      ) &&
      copyExecutionEnabled &&
      v2CopyExecutionEnabled &&
      v2FeeConfirmed &&
      !v2AuthorizationConsumed &&
      v2ExecutionState !== "submitting",
  );

  async function handleExecuteV2Copy() {
    if (
      !canExecuteV2 ||
      !recommendationResult ||
      !v2Preflight ||
      v2ExecutionLock.current ||
      executionLock.current ||
      v2VideoExecutionLock.current ||
      v2AuthorizationConsumedRef.current
    ) {
      return;
    }
    v2ExecutionLock.current = true;
    v2AuthorizationConsumedRef.current = true;
    setV2AuthorizationConsumed(true);
    setV2FeeConfirmed(false);
    const expectedProductId = productId;
    const expectedRecommendation = recommendationResult;
    const expectedPreflight = v2Preflight;
    const requestId = ++v2ExecutionRequestId.current;
    const controller = new AbortController();
    v2ExecutionController.current?.abort();
    v2ExecutionController.current = controller;
    setV2ExecutionState("submitting");
    setV2ExecutionError("");
    setV2Result(null);
    try {
      const result = await executeV2Copy(
        expectedProductId,
        {
          ...v2SourceRequest(expectedRecommendation),
          expected_preflight_digest:
            expectedPreflight.preflight_digest,
        },
        controller.signal,
      );
      if (
        controller.signal.aborted ||
        requestId !== v2ExecutionRequestId.current ||
        currentProductId.current !== expectedProductId ||
        recommendationResult !== expectedRecommendation ||
        !sameV2ExecutionIdentity(
          result,
          expectedRecommendation,
          expectedProductId,
        )
      ) {
        return;
      }
      if (!hasConsistentV2PlatformEvidence(result, expectedPreflight)) {
        setV2ExecutionState("failed");
        setV2ExecutionError(
          "Backend返回的V2 Copy平台或Digest证据不一致；结果不会作为成功候选使用。",
        );
        setV2Preflight(null);
        setV2PreflightState("idle");
        setV2FeeConfirmed(false);
        return;
      }
      resetV2Video();
      setV2Result(result);
      setV2ExecutionState("succeeded");
      setV2Preflight(null);
      setV2PreflightState("idle");
    } catch (error) {
      if (
        controller.signal.aborted ||
        requestId !== v2ExecutionRequestId.current ||
        currentProductId.current !== expectedProductId
      ) {
        return;
      }
      const uncertain = isUncertainGenerationError(error);
      setV2ExecutionState(uncertain ? "uncertain" : "failed");
      setV2ExecutionError(
        uncertain
          ? "V2 Copy结果不确定；不会自动重试，也不能在当前Recommendation上直接重提。"
          : getApiErrorMessage(
              error,
              "V2 Copy生成失败；重新执行前必须重新Preflight并确认费用。",
            ),
      );
      setV2Preflight(null);
      setV2PreflightState("idle");
      setV2FeeConfirmed(false);
    } finally {
      if (requestId === v2ExecutionRequestId.current) {
        v2ExecutionLock.current = false;
      }
    }
  }

  const canPreflightV2Video = Boolean(
    recommendationResult &&
      v2Result &&
      v2ExecutionState === "succeeded" &&
      sameV2ExecutionIdentity(
        v2Result,
        recommendationResult,
        productId,
      ) &&
      v2VideoExecutionState !== "submitting" &&
      v2VideoExecutionState !== "succeeded" &&
      v2VideoExecutionState !== "uncertain",
  );

  async function handleV2VideoPreflight() {
    if (
      !canPreflightV2Video ||
      !recommendationResult ||
      !v2Result ||
      v2VideoPreflightLock.current ||
      v2VideoExecutionLock.current ||
      executionLock.current ||
      v2ExecutionLock.current
    ) {
      return;
    }
    v2VideoPreflightLock.current = true;
    const expectedProductId = productId;
    const expectedRecommendation = recommendationResult;
    const expectedCopy = v2Result;
    const requestId = ++v2VideoPreflightRequestId.current;
    const controller = new AbortController();
    v2VideoPreflightController.current?.abort();
    v2VideoPreflightController.current = controller;
    setV2VideoPreflightState("checking");
    setV2VideoPreflightError("");
    setV2VideoFeeConfirmed(false);
    setV2VideoAuthorizationConsumed(false);
    v2VideoAuthorizationConsumedRef.current = false;
    setV2VideoExecutionState("idle");
    setV2VideoExecutionError("");
    setV2VideoResult(null);
    try {
      const result = await preflightV2VideoProject(
        expectedProductId,
        v2VideoSourceRequest(expectedRecommendation, expectedCopy),
        controller.signal,
      );
      if (
        controller.signal.aborted ||
        requestId !== v2VideoPreflightRequestId.current ||
        currentProductId.current !== expectedProductId ||
        recommendationResult !== expectedRecommendation ||
        v2Result !== expectedCopy ||
        !sameV2VideoPreflightIdentity(
          result,
          expectedRecommendation,
          expectedCopy,
          expectedProductId,
        )
      ) {
        return;
      }
      setV2VideoPreflight(result);
      setV2VideoPreflightState(
        result.ready_for_execution ? "ready" : "blocked",
      );
    } catch (error) {
      if (
        controller.signal.aborted ||
        requestId !== v2VideoPreflightRequestId.current ||
        currentProductId.current !== expectedProductId
      ) {
        return;
      }
      setV2VideoPreflight(null);
      setV2VideoPreflightState("failed");
      setV2VideoPreflightError(
        getApiErrorMessage(
          error,
          "V2 VideoProject Preflight failed; reread Context and retry.",
        ),
      );
    } finally {
      if (requestId === v2VideoPreflightRequestId.current) {
        v2VideoPreflightLock.current = false;
      }
    }
  }

  const canExecuteV2Video = Boolean(
    recommendationResult &&
      v2Result &&
      v2VideoPreflight &&
      v2VideoPreflightState === "ready" &&
      v2VideoPreflight.ready_for_execution &&
      sameV2VideoPreflightIdentity(
        v2VideoPreflight,
        recommendationResult,
        v2Result,
        productId,
      ) &&
      v2VideoProjectExecutionEnabled &&
      v2VideoFeeConfirmed &&
      !v2VideoAuthorizationConsumed &&
      v2VideoExecutionState !== "submitting",
  );

  async function handleExecuteV2Video() {
    if (
      !canExecuteV2Video ||
      !recommendationResult ||
      !v2Result ||
      !v2VideoPreflight ||
      v2VideoExecutionLock.current ||
      executionLock.current ||
      v2ExecutionLock.current ||
      v2VideoAuthorizationConsumedRef.current
    ) {
      return;
    }
    v2VideoExecutionLock.current = true;
    v2VideoAuthorizationConsumedRef.current = true;
    setV2VideoAuthorizationConsumed(true);
    setV2VideoFeeConfirmed(false);
    const expectedProductId = productId;
    const expectedRecommendation = recommendationResult;
    const expectedCopy = v2Result;
    const expectedPreflight = v2VideoPreflight;
    const requestId = ++v2VideoExecutionRequestId.current;
    const controller = new AbortController();
    v2VideoExecutionController.current?.abort();
    v2VideoExecutionController.current = controller;
    setV2VideoExecutionState("submitting");
    setV2VideoExecutionError("");
    setV2VideoResult(null);
    try {
      const result = await executeV2VideoProject(
        expectedProductId,
        {
          ...v2VideoSourceRequest(expectedRecommendation, expectedCopy),
          expected_preflight_digest:
            expectedPreflight.preflight_digest,
        },
        controller.signal,
      );
      if (
        controller.signal.aborted ||
        requestId !== v2VideoExecutionRequestId.current ||
        currentProductId.current !== expectedProductId ||
        recommendationResult !== expectedRecommendation ||
        v2Result !== expectedCopy ||
        !sameV2VideoExecutionIdentity(
          result,
          expectedRecommendation,
          expectedCopy,
          expectedPreflight,
          expectedProductId,
        )
      ) {
        return;
      }
      setV2VideoResult(result);
      setV2VideoExecutionState("succeeded");
      setV2VideoPreflight(null);
      setV2VideoPreflightState("idle");
      onVideoProjectGenerated?.(result.generated_video_project.id);
    } catch (error) {
      if (
        controller.signal.aborted ||
        requestId !== v2VideoExecutionRequestId.current ||
        currentProductId.current !== expectedProductId
      ) {
        return;
      }
      const uncertain = isUncertainGenerationError(error);
      setV2VideoExecutionState(uncertain ? "uncertain" : "failed");
      setV2VideoExecutionError(
        uncertain
          ? "V2 VideoProject result is uncertain. No automatic retry or latest-project recovery will be used."
          : getApiErrorMessage(
              error,
              "V2 VideoProject generation failed; run a new Preflight and confirm cost again.",
            ),
      );
      setV2VideoPreflight(null);
      setV2VideoPreflightState("idle");
      setV2VideoFeeConfirmed(false);
    } finally {
      if (requestId === v2VideoExecutionRequestId.current) {
        v2VideoExecutionLock.current = false;
      }
    }
  }

  const panelSubmitting =
    executionState === "submitting" ||
    v2ExecutionState === "submitting" ||
    v2VideoExecutionState === "submitting";

  return (
    <section className="growth-panel" aria-label="Structured FeedbackContext">
      <div className="growth-panel__header">
        <div>
          <span>STRUCTURED FEEDBACK CONTEXT</span>
          <strong>投放反馈上下文</strong>
        </div>
        <div className="growth-panel__zero-ai">
          <strong>
            {(recommendationResult?.provider_calls ?? 0) +
              (v2Result?.provider_calls ?? 0) +
              (v2VideoResult?.provider_calls ?? 0)}{" "}
            AI Calls
          </strong>
          <small>Context读取始终Provider-free</small>
        </div>
      </div>

      <div className="growth-panel__controls">
        <label>
          <input
            accept=".csv,text/csv"
            type="file"
            disabled={uploading || panelSubmitting}
            onChange={(event) =>
              setFile(event.target.files?.[0] ?? null)
            }
          />
          <span>{file?.name ?? "选择Campaign CSV"}</span>
        </label>
        <button
          type="button"
          disabled={
            !file ||
            uploading ||
            panelSubmitting
          }
          onClick={() => void handleUpload()}
        >
          {uploading ? "导入中…" : "导入Campaign CSV"}
        </button>
        <button
          type="button"
          disabled={
            reading ||
            contextState === "loading" ||
            panelSubmitting
          }
          onClick={() => void readContext(productId, true)}
        >
          {reading ? "读取中…" : "重新读取FeedbackContext"}
        </button>
      </div>
      <p className="growth-panel__boundary">
        CSV导入会追加Campaign记录，但不会调用AI；重复导入当前不会自动去重或替换。
      </p>
      {notice && <p className="growth-panel__status">{notice}</p>}

      {contextState === "loading" && (
        <ContextMessage
          title="正在读取FeedbackContext"
          detail="正在从本地持久化Campaign与精确内容链构建确定性快照。"
        />
      )}
      {contextState === "error" && (
        <ContextMessage
          title="FeedbackContext读取失败"
          detail={contextError}
          error
        />
      )}
      {contextState === "empty" && context && (
        <ContextMessage
          title="尚无Campaign数据"
          detail="Context已安全返回；请主动导入合法CSV。系统不会自动上传或调用AI。"
        />
      )}
      {(contextState === "ready" || contextState === "incomplete") &&
        context && <ContextResult context={context} />}

      <section
        className="growth-recommendation"
        aria-label="Recommendation Constraints"
      >
        <div className="growth-context-section-title">
          <strong>Recommendation-to-Generation Constraints</strong>
          <small>只生成测试假设与后续生成约束</small>
        </div>
        <div className="growth-recommendation__actions">
          <button
            type="button"
            disabled={
              !context ||
              preflightState === "checking" ||
              panelSubmitting
            }
            onClick={() => void handlePreflight()}
          >
            {preflightState === "checking"
              ? "检查中…"
              : "运行Recommendation Preflight"}
          </button>
          <span>
            Frontend Gate：
            {growthExecutionEnabled ? "已开启" : "默认关闭"}
          </span>
        </div>

        {preflightState === "idle" && (
          <ContextMessage
            title="尚未运行Preflight"
            detail="这是只读检查，不调用Provider、不写数据库。"
          />
        )}
        {preflightState === "checking" && (
          <ContextMessage
            title="正在运行Recommendation Preflight"
            detail="正在重新核对Product、Context Digest与原子内容链。"
          />
        )}
        {preflightState === "failed" && (
          <ContextMessage
            title="Recommendation Preflight失败"
            detail={preflightError}
            error
          />
        )}
        {(preflightState === "ready" ||
          preflightState === "blocked") &&
          preflight && (
            <PreflightResult
              preflight={preflight}
              state={preflightState}
            />
          )}

        <label className="growth-recommendation__confirm">
          <input
            type="checkbox"
            checked={feeConfirmed}
            disabled={
              preflightState !== "ready" ||
              authorizationConsumed ||
              panelSubmitting
            }
            onChange={(event) => setFeeConfirmed(event.target.checked)}
          />
          <span>
            我确认本次Recommendation会调用Qwen，可能产生费用；失败或不确定后不会自动重试。
          </span>
        </label>
        <button
          className="growth-recommendation__execute"
          type="button"
          disabled={!canExecute}
          onClick={() => void handleExecuteRecommendation()}
        >
          {executionState === "submitting"
            ? "正在生成受约束Recommendation…"
            : "调用Qwen生成受约束Recommendation"}
        </button>
        {executionState === "failed" && (
          <ContextMessage
            title="Recommendation执行失败"
            detail={executionError}
            error
          />
        )}
        {executionState === "uncertain" && (
          <ContextMessage
            title="Recommendation执行结果不确定"
            detail={executionError}
            error
          />
        )}
        {recommendationFailure && (
          <ProviderFailureSummary failure={recommendationFailure} />
        )}
        {executionState === "succeeded" && recommendationResult && (
          <RecommendationResult result={recommendationResult} />
        )}

        <p className="growth-panel__boundary">
          Recommendation不持久化；页面刷新后可能丢失。再次执行可能再次产生Provider费用。
          C4.2必须重新验证Product、Digest和精确内容链。
        </p>

        {recommendationResult && (
          <section
            className="growth-v2-copy"
            aria-label="Recommendation-Bound V2 Copy"
          >
            <div className="growth-context-section-title">
              <strong>V2 Copy Candidate</strong>
              <small>
                独立Preflight、独立费用确认；不会继承Recommendation授权
              </small>
            </div>
            <div className="growth-recommendation__actions">
              <button
                type="button"
                disabled={
                  !canPreflightV2 ||
                  v2PreflightState === "checking" ||
                  panelSubmitting
                }
                onClick={() => void handleV2Preflight()}
              >
                {v2PreflightState === "checking"
                  ? "检查中…"
                  : "运行V2 Copy Preflight"}
              </button>
              <span>
                Frontend Gates：
                {copyExecutionEnabled && v2CopyExecutionEnabled
                  ? "均已开启"
                  : "默认关闭"}
              </span>
            </div>

            {v2PreflightState === "idle" &&
              v2ExecutionState !== "succeeded" &&
              v2ExecutionState !== "uncertain" && (
                <ContextMessage
                  title="尚未运行V2 Copy Preflight"
                  detail="只读核对Recommendation Digest、Context和精确内容链，不调用Provider、不写数据库。"
                />
              )}
            {v2PreflightState === "checking" && (
              <ContextMessage
                title="正在运行V2 Copy Preflight"
                detail="正在重新计算摘要并核对全部源身份。"
              />
            )}
            {v2PreflightState === "failed" && (
              <ContextMessage
                title="V2 Copy Preflight失败"
                detail={v2PreflightError}
                error
              />
            )}
            {(v2PreflightState === "ready" ||
              v2PreflightState === "blocked") &&
              v2Preflight && (
                <V2CopyPreflightResult
                  preflight={v2Preflight}
                  state={v2PreflightState}
                />
              )}

            <label className="growth-recommendation__confirm">
              <input
                type="checkbox"
                checked={v2FeeConfirmed}
                disabled={
                  v2PreflightState !== "ready" ||
                  v2AuthorizationConsumed ||
                  panelSubmitting
                }
                onChange={(event) =>
                  setV2FeeConfirmed(event.target.checked)
                }
              />
              <span>
                我单独确认本次V2 Copy Candidate会调用Qwen并可能产生费用；此授权仅使用一次。
              </span>
            </label>
            <button
              className="growth-recommendation__execute"
              type="button"
              disabled={!canExecuteV2}
              onClick={() => void handleExecuteV2Copy()}
            >
              {v2ExecutionState === "submitting"
                ? "正在生成V2 Copy Candidate…"
                : "调用Qwen生成V2 Copy Candidate"}
            </button>
            {v2ExecutionState === "failed" && (
              <ContextMessage
                title="V2 Copy生成失败"
                detail={v2ExecutionError}
                error
              />
            )}
            {v2ExecutionState === "uncertain" && (
              <ContextMessage
                title="V2 Copy结果不确定"
                detail={v2ExecutionError}
                error
              />
            )}
            {v2ExecutionState === "succeeded" && v2Result && (
              <V2CopyCandidateResult result={v2Result} />
            )}
            <p className="growth-panel__boundary">
              仅保存V2 Copy Candidate；未修改源Copy，未创建VideoProject，
              父子版本关系尚未持久化。网络响应丢失时无法可靠确认本次是否落库，
              不会自动重试或用latest CopyMatrix冒充结果。
            </p>
          </section>
        )}

        {recommendationResult && v2Result && (
          <section
            className="growth-v2-video"
            aria-label="Recommendation-Bound V2 VideoProject"
          >
            <div className="growth-context-section-title">
              <strong>V2 VideoProject Candidate</strong>
              <small>
                Exact candidate CopyMatrix #{v2Result.generated_copy_matrix.id};
                Qwen planning only, no Wanx or render
              </small>
            </div>
            <div className="growth-recommendation__actions">
              <button
                type="button"
                disabled={
                  !canPreflightV2Video ||
                  v2VideoPreflightState === "checking" ||
                  panelSubmitting
                }
                onClick={() => void handleV2VideoPreflight()}
              >
                {v2VideoPreflightState === "checking"
                  ? "Checking..."
                  : "Run V2 VideoProject Preflight"}
              </button>
              <span>
                Frontend Gate:{" "}
                {v2VideoProjectExecutionEnabled
                  ? "enabled"
                  : "default closed"}
              </span>
            </div>
            {v2VideoPreflightState === "idle" &&
              v2VideoExecutionState !== "succeeded" &&
              v2VideoExecutionState !== "uncertain" && (
                <ContextMessage
                  title="V2 VideoProject Preflight not yet run"
                  detail="Read-only validation; no Provider call and no database write."
                />
              )}
            {v2VideoPreflightState === "checking" && (
              <ContextMessage
                title="Checking V2 VideoProject inputs"
                detail="Revalidating Context, Recommendation, source chain, candidate CopyMatrix, and production constraints."
              />
            )}
            {v2VideoPreflightState === "failed" && (
              <ContextMessage
                title="V2 VideoProject Preflight failed"
                detail={v2VideoPreflightError}
                error
              />
            )}
            {(v2VideoPreflightState === "ready" ||
              v2VideoPreflightState === "blocked") &&
              v2VideoPreflight && (
                <V2VideoPreflightResult
                  preflight={v2VideoPreflight}
                  state={v2VideoPreflightState}
                />
              )}
            <label className="growth-recommendation__confirm">
              <input
                type="checkbox"
                checked={v2VideoFeeConfirmed}
                disabled={
                  v2VideoPreflightState !== "ready" ||
                  v2VideoAuthorizationConsumed ||
                  panelSubmitting
                }
                onChange={(event) =>
                  setV2VideoFeeConfirmed(event.target.checked)
                }
              />
              <span>
                I separately authorize this single Qwen VideoProject-planning
                call. This authorization does not permit Wanx or rendering.
              </span>
            </label>
            <button
              className="growth-recommendation__execute"
              type="button"
              disabled={!canExecuteV2Video}
              onClick={() => void handleExecuteV2Video()}
            >
              {v2VideoExecutionState === "submitting"
                ? "Generating V2 VideoProject..."
                : "Call Qwen to create V2 VideoProject"}
            </button>
            {v2VideoExecutionState === "failed" && (
              <ContextMessage
                title="V2 VideoProject generation failed"
                detail={v2VideoExecutionError}
                error
              />
            )}
            {v2VideoExecutionState === "uncertain" && (
              <ContextMessage
                title="V2 VideoProject result uncertain"
                detail={v2VideoExecutionError}
                error
              />
            )}
            {v2VideoExecutionState === "succeeded" && v2VideoResult && (
              <V2VideoCandidateResult result={v2VideoResult} />
            )}
            <p className="growth-panel__boundary">
              The saved VideoProject references the exact V2 Copy Candidate.
              Recommendation and parent-version provenance are not persisted.
              No automatic render, retry, Submit, Refresh, or latest-project
              recovery is performed.
            </p>
          </section>
        )}
      </section>
    </section>
  );
}

function ContextMessage({
  title,
  detail,
  error = false,
}: {
  title: string;
  detail: string;
  error?: boolean;
}) {
  return (
    <div
      className={`growth-context-state${
        error ? " growth-context-state--error" : ""
      }`}
    >
      <strong>{title}</strong>
      <p>{detail}</p>
    </div>
  );
}

function ContextResult({ context }: { context: FeedbackContext }) {
  return (
    <div className="growth-context-result">
      <div className="growth-context-summary">
        <div>
          <small>Context readiness</small>
          <strong>
            {context.context_ready ? "READY" : "INCOMPLETE"}
          </strong>
        </div>
        <div>
          <small>Campaign</small>
          <strong>{context.campaign_count}条</strong>
        </div>
        <div>
          <small>日期范围</small>
          <strong>
            {context.date_from && context.date_to
              ? `${context.date_from} — ${context.date_to}`
              : "尚无日期"}
          </strong>
        </div>
        <div>
          <small>Context Digest</small>
          <strong title={context.context_digest}>
            {context.context_digest.slice(0, 12)}…
          </strong>
        </div>
      </div>

      {context.overall_metrics && (
        <>
          <div className="growth-context-section-title">
            <strong>总体指标</strong>
            <small>先聚合总量，再计算比率</small>
          </div>
          <MetricsGrid metrics={context.overall_metrics} />
        </>
      )}

      <div className="growth-context-platforms">
        {context.platform_metrics.map((item) => (
          <article key={item.platform}>
            <strong>{item.platform}</strong>
            <MetricsGrid metrics={item.metrics} compact />
          </article>
        ))}
      </div>

      {context.content_chain_ready ? (
        <div className="growth-context-chain">
          <div>
            <small>MarketingStrategy</small>
            <strong>{asId(context.marketing_strategy_id)}</strong>
          </div>
          <div>
            <small>CopyMatrix</small>
            <strong>{asId(context.copy_matrix_id)}</strong>
          </div>
          <div>
            <small>VideoProject</small>
            <strong>{asId(context.video_project_id)}</strong>
          </div>
          <p>
            精确选择：latest VideoProject → 它引用的CopyMatrix与MarketingStrategy
          </p>
        </div>
      ) : (
        <div className="growth-context-chain">
          <strong>精确内容链未就绪</strong>
          <p>仅在完整链通过当前Product身份和引用一致性校验后显示内容ID。</p>
        </div>
      )}

      {context.missing_requirements.length > 0 && (
        <div className="growth-context-missing">
          <strong>Missing requirements</strong>
          <ul>
            {context.missing_requirements.map((item) => (
              <li key={item}>{MISSING_LABELS[item] ?? item}</li>
            ))}
          </ul>
        </div>
      )}

      <p className="growth-context-attribution">
        产品级归因边界：Campaign指标只能归属于当前Product，不能证明由当前CopyMatrix、
        VideoProject或Artifact产生。当前内容链仅是下一阶段的精确参考链；
        VideoProject没有MarketingBrief外键。
      </p>
    </div>
  );
}

function ProviderFailureSummary({
  failure,
}: {
  failure: ProviderFailureDetails;
}) {
  return (
    <div className="growth-recommendation__preflight">
      <strong>安全错误诊断</strong>
      <div className="growth-context-summary">
        <div>
          <small>错误类别</small>
          <strong>{failure.safe_error_code}</strong>
        </div>
        <div>
          <small>失败阶段</small>
          <strong>{failure.phase}</strong>
        </div>
        <div>
          <small>Provider HTTP</small>
          <strong>{failure.provider_http_status ?? "未收到响应"}</strong>
        </div>
        <div>
          <small>可能计费</small>
          <strong>{failure.potentially_billable ? "是" : "否"}</strong>
        </div>
      </div>
      {failure.request_id_digest && (
        <p>Request ID安全摘要：{failure.request_id_digest}</p>
      )}
      <p>失败后旧Preflight和费用授权已失效，不会自动重试。</p>
    </div>
  );
}

function PreflightResult({
  preflight,
  state,
}: {
  preflight: GrowthRecommendationPreflight;
  state: "ready" | "blocked";
}) {
  return (
    <div className="growth-recommendation__preflight">
      <div className="growth-context-summary">
        <div>
          <small>Preflight</small>
          <strong>{state === "ready" ? "READY" : "BLOCKED"}</strong>
        </div>
        <div>
          <small>Input</small>
          <strong>{preflight.input_ready ? "READY" : "BLOCKED"}</strong>
        </div>
        <div>
          <small>Provider配置</small>
          <strong>
            {preflight.provider_configured ? "已配置" : "未配置"}
          </strong>
        </div>
        <div>
          <small>Backend Gate</small>
          <strong>
            {preflight.execution_enabled ? "已开启" : "默认关闭"}
          </strong>
        </div>
      </div>
      <p>{preflight.cost_notice}</p>
      <p>{preflight.attribution_notice}</p>
      {preflight.missing_requirements.length > 0 && (
        <div className="growth-context-missing">
          <strong>Blocked requirements</strong>
          <ul>
            {preflight.missing_requirements.map((item) => (
              <li key={item}>{MISSING_LABELS[item] ?? item}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function RecommendationResult({ result }: { result: GrowthAnalysis }) {
  const recommendation = result.recommendation;
  return (
    <div className="growth-recommendation__result">
      <div className="growth-context-section-title">
        <strong>本次受约束Recommendation</strong>
        <small>
          Context {result.source_context_digest.slice(0, 12)}… · Strategy #
          {result.source_marketing_strategy_id} · CopyMatrix #
          {result.source_copy_matrix_id} · VideoProject #
          {result.source_video_project_id}
        </small>
      </div>
      <p>{recommendation.summary}</p>

      <h5>Observations · 测试假设</h5>
      <div className="growth-recommendation__cards">
        {recommendation.observations.map((item, index) => (
          <article
            key={`${item.scope}-${item.platform ?? "overall"}-${item.metric}-${index}`}
          >
            <strong>
              {item.platform ?? "Overall"} · {item.metric}
            </strong>
            <small>{item.direction}</small>
            <p>{item.hypothesis}</p>
          </article>
        ))}
      </div>

      <h5>Copy constraints</h5>
      <div className="growth-recommendation__cards">
        {recommendation.copy_constraints.map((item) => (
          <article key={item.platform}>
            <strong>{item.platform}</strong>
            <p>Hook：{item.hook_direction}</p>
            <p>Angle：{item.message_angle}</p>
            <p>CTA：{item.cta_direction}</p>
            <p>保留：{item.must_preserve.join("；")}</p>
            <p>避免：{item.must_avoid.join("；")}</p>
          </article>
        ))}
      </div>

      <h5>Video constraint</h5>
      <article className="growth-recommendation__video">
        <strong>{recommendation.video_constraint.platform}</strong>
        <p>Opening：{recommendation.video_constraint.opening_hook_direction}</p>
        <p>Visual：{recommendation.video_constraint.visual_focus}</p>
        <p>Pacing：{recommendation.video_constraint.pacing_direction}</p>
        <p>CTA：{recommendation.video_constraint.cta_direction}</p>
      </article>

      <h5>Budget guidance</h5>
      <p>{recommendation.budget_guidance}</p>
      <p className="growth-context-attribution">
        Product级数据形成的测试假设，不是创意因果证明。本次结果未持久化、
        未修改预算、未生成V2 Copy或VideoProject，也没有自动执行权限。
      </p>
      <p className="growth-context-attribution">
        Recommendation Digest：
        <span title={result.recommendation_digest}>
          {result.recommendation_digest.slice(0, 12)}…
        </span>
        ；完整性范围为确定性往返校验，不是签名、鉴权或Provider来源证明。
      </p>
    </div>
  );
}

function V2CopyPreflightResult({
  preflight,
  state,
}: {
  preflight: V2CopyPreflight;
  state: "ready" | "blocked";
}) {
  return (
    <div className="growth-recommendation__preflight">
      <div className="growth-context-summary">
        <div>
          <small>V2 Preflight</small>
          <strong>{state === "ready" ? "READY" : "BLOCKED"}</strong>
        </div>
        <div>
          <small>源CopyMatrix平台</small>
          <strong>{preflight.source_copy_platforms.join(" / ")}</strong>
        </div>
        <div>
          <small>Recommendation允许引用平台</small>
          <strong>
            {preflight.allowed_copy_constraint_platforms.join(" / ")}
          </strong>
        </div>
        <div>
          <small>Recommendation实际Copy目标平台</small>
          <strong>
            {preflight.recommendation_target_copy_platforms.join(" / ")}
          </strong>
        </div>
        <div>
          <small>本次V2 Copy生成目标平台</small>
          <strong>{preflight.v2_copy_target_platforms.join(" / ")}</strong>
        </div>
        <div>
          <small>Copy Gate</small>
          <strong>
            {preflight.copy_execution_enabled ? "已开启" : "默认关闭"}
          </strong>
        </div>
        <div>
          <small>V2 Copy Gate</small>
          <strong>
            {preflight.v2_copy_execution_enabled
              ? "已开启"
              : "默认关闭"}
          </strong>
        </div>
      </div>
      <p>
        Preflight Digest：
        <span title={preflight.preflight_digest}>
          {preflight.preflight_digest.slice(0, 12)}…
        </span>
      </p>
      <p>{preflight.cost_notice}</p>
      <p>{preflight.association_notice}</p>
      {preflight.missing_requirements.length > 0 && (
        <div className="growth-context-missing">
          <strong>Blocked requirements</strong>
          <ul>
            {preflight.missing_requirements.map((item) => (
              <li key={item}>{MISSING_LABELS[item] ?? item}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function V2CopyCandidateResult({
  result,
}: {
  result: V2CopyExecutionResult;
}) {
  return (
    <div className="growth-v2-copy__result">
      <div className="growth-context-section-title">
        <strong>V2 Copy Candidate</strong>
        <small>
          CopyMatrix #{result.copy_matrix_id}
        </small>
      </div>
      <div className="growth-context-summary">
        <div>
          <small>源CopyMatrix平台</small>
          <strong>{result.source_copy_platforms.join(" / ")}</strong>
        </div>
        <div>
          <small>Recommendation允许引用平台</small>
          <strong>
            {result.allowed_copy_constraint_platforms.join(" / ")}
          </strong>
        </div>
        <div>
          <small>Recommendation实际Copy目标平台</small>
          <strong>
            {result.recommendation_target_copy_platforms.join(" / ")}
          </strong>
        </div>
        <div>
          <small>本次V2 Copy生成目标平台</small>
          <strong>{result.v2_copy_target_platforms.join(" / ")}</strong>
        </div>
        <div>
          <small>实际持久化候选平台</small>
          <strong>{result.persisted_copy_platforms.join(" / ")}</strong>
        </div>
      </div>
      <div className="growth-context-chain">
        <div>
          <small>Source Strategy</small>
          <strong>#{result.source_marketing_strategy_id}</strong>
        </div>
        <div>
          <small>Source CopyMatrix</small>
          <strong>#{result.source_copy_matrix_id}</strong>
        </div>
        <div>
          <small>Source VideoProject</small>
          <strong>#{result.source_video_project_id}</strong>
        </div>
      </div>
      <p>
        Context {result.source_context_digest.slice(0, 12)}… · Recommendation{" "}
        {result.source_recommendation_digest.slice(0, 12)}…
      </p>
      <div className="growth-v2-copy__cards">
        {result.generated_copy_matrix.copies.map((copy) => (
          <article key={copy.platform}>
            <strong>{copy.platform}</strong>
            <p>Hook：{copy.hook}</p>
            <p>Caption：{copy.caption}</p>
            <p>Hashtags：{copy.hashtags.join(" ")}</p>
            <p>CTA：{copy.cta}</p>
          </article>
        ))}
      </div>
      <ul className="growth-v2-copy__boundaries">
        <li>仅保存V2 Copy Candidate</li>
        <li>未修改源Copy</li>
        <li>未创建VideoProject</li>
        <li>父子版本关系尚未持久化</li>
      </ul>
    </div>
  );
}

function V2VideoPreflightResult({
  preflight,
  state,
}: {
  preflight: V2VideoProjectPreflight;
  state: "ready" | "blocked";
}) {
  return (
    <div className="growth-recommendation__preflight">
      <div className="growth-context-summary">
        <div>
          <small>Preflight</small>
          <strong>{state === "ready" ? "READY" : "BLOCKED"}</strong>
        </div>
        <div>
          <small>Candidate CopyMatrix</small>
          <strong>#{preflight.candidate_copy_matrix_id}</strong>
        </div>
        <div>
          <small>Production</small>
          <strong>
            {preflight.platform} · {preflight.duration_seconds}s ·{" "}
            {preflight.aspect_ratio}
          </strong>
        </div>
        <div>
          <small>Backend Gate</small>
          <strong>
            {preflight.v2_video_project_execution_enabled
              ? "enabled"
              : "default closed"}
          </strong>
        </div>
      </div>
      <p>
        Preflight Digest:{" "}
        <span title={preflight.preflight_digest}>
          {preflight.preflight_digest.slice(0, 12)}…
        </span>
      </p>
      <p>{preflight.cost_notice}</p>
      <p>{preflight.association_notice}</p>
      {preflight.missing_requirements.length > 0 && (
        <div className="growth-context-missing">
          <strong>Blocked requirements</strong>
          <ul>
            {preflight.missing_requirements.map((item) => (
              <li key={item}>{MISSING_LABELS[item] ?? item}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function V2VideoCandidateResult({
  result,
}: {
  result: V2VideoProjectExecutionResult;
}) {
  const project = result.generated_video_project;
  return (
    <div className="growth-v2-video__result">
      <div className="growth-context-section-title">
        <strong>
          VideoProject #{project.id} · {project.title}
        </strong>
        <small>
          CopyMatrix #{result.candidate_copy_matrix_id} · {project.platform} ·{" "}
          {project.duration_seconds}s · {project.aspect_ratio}
        </small>
      </div>
      <p>{project.concept}</p>
      <ul className="growth-v2-video__scenes">
        {project.scenes.map((scene) => (
          <li key={scene.sequence}>
            <strong>
              Scene {scene.sequence} · {scene.duration_seconds}s ·{" "}
              {scene.shot_type}
            </strong>
            <p>{scene.visual_description}</p>
            <p>{scene.action}</p>
            <p>{scene.narration}</p>
          </li>
        ))}
      </ul>
      <p>CTA: {project.cta}</p>
      <ul className="growth-v2-copy__boundaries">
        <li>
          Candidate CopyMatrix association persisted ={" "}
          {result.candidate_copy_matrix_association_persisted ? "yes" : "no"}
        </li>
        <li>
          Candidate Copy → source Copy parent persisted ={" "}
          {result.candidate_copy_source_parent_relation_persisted
            ? "yes"
            : "no"}
        </li>
        <li>
          New VideoProject → source VideoProject parent persisted ={" "}
          {result.source_video_parent_relation_persisted ? "yes" : "no"}
        </li>
        <li>
          Recommendation persisted ={" "}
          {result.recommendation_persisted ? "yes" : "no"}
        </li>
        <li>Wanx Calls = {result.wanx_calls}</li>
        <li>RenderTask = {result.render_tasks_created}</li>
        <li>Artifact = {result.artifacts_created}</li>
        <li>尚未渲染</li>
      </ul>
      <p>{result.association_notice}</p>
    </div>
  );
}

function MetricsGrid({
  metrics,
  compact = false,
}: {
  metrics: CampaignMetrics;
  compact?: boolean;
}) {
  return (
    <div
      className={`growth-metrics${
        compact ? " growth-metrics--compact" : ""
      }`}
    >
      <Metric label="CTR" value={asPercent(metrics.ctr)} />
      <Metric
        label="CVR"
        value={asPercent(metrics.conversion_rate)}
      />
      <Metric label="CPA" value={asCurrency(metrics.cpa)} />
      <Metric label="ROAS" value={asRatio(metrics.roas)} />
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <small>{label}</small>
      <strong>{value}</strong>
    </div>
  );
}

function asId(value: number | null) {
  return value === null ? "未就绪" : `#${value}`;
}

function asPercent(value: number) {
  return `${(value * 100).toFixed(2)}%`;
}

function asCurrency(value: number | null) {
  return value === null ? "—" : `$${value.toFixed(2)}`;
}

function asRatio(value: number | null) {
  return value === null ? "—" : `${value.toFixed(2)}x`;
}

function samePreflightIdentity(
  preflight: GrowthRecommendationPreflight,
  context: FeedbackContext,
) {
  return (
    preflight.product_id === context.product_id &&
    preflight.context_digest === context.context_digest &&
    preflight.marketing_strategy_id === context.marketing_strategy_id &&
    preflight.copy_matrix_id === context.copy_matrix_id &&
    preflight.video_project_id === context.video_project_id
  );
}

function sameExecutionIdentity(
  result: GrowthAnalysis,
  context: FeedbackContext,
) {
  return (
    result.product_id === context.product_id &&
    result.source_context_digest === context.context_digest &&
    result.source_marketing_strategy_id ===
      context.marketing_strategy_id &&
    result.source_copy_matrix_id === context.copy_matrix_id &&
    result.source_video_project_id === context.video_project_id
  );
}

function v2SourceRequest(result: GrowthAnalysis) {
  return {
    source_context_digest: result.source_context_digest,
    source_marketing_strategy_id:
      result.source_marketing_strategy_id,
    source_copy_matrix_id: result.source_copy_matrix_id,
    source_video_project_id: result.source_video_project_id,
    recommendation_digest: result.recommendation_digest,
    recommendation: result.recommendation,
  };
}

function sameV2PreflightIdentity(
  preflight: V2CopyPreflight,
  recommendation: GrowthAnalysis,
  productId: number,
) {
  return (
    preflight.product_id === productId &&
    preflight.source_context_digest ===
      recommendation.source_context_digest &&
    preflight.source_recommendation_digest ===
      recommendation.recommendation_digest &&
    preflight.source_marketing_strategy_id ===
      recommendation.source_marketing_strategy_id &&
    preflight.source_copy_matrix_id ===
      recommendation.source_copy_matrix_id &&
    preflight.source_video_project_id ===
      recommendation.source_video_project_id
  );
}

function sameV2ExecutionIdentity(
  result: V2CopyExecutionResult,
  recommendation: GrowthAnalysis,
  productId: number,
) {
  return (
    result.product_id === productId &&
    result.source_context_digest ===
      recommendation.source_context_digest &&
    result.source_recommendation_digest ===
      recommendation.recommendation_digest &&
    result.source_marketing_strategy_id ===
      recommendation.source_marketing_strategy_id &&
    result.source_copy_matrix_id ===
      recommendation.source_copy_matrix_id &&
    result.source_video_project_id ===
      recommendation.source_video_project_id
  );
}

function sameOrderedPlatforms(left: string[], right: string[]) {
  return (
    left.length === right.length &&
    left.every((platform, index) => platform === right[index])
  );
}

function hasConsistentV2PlatformEvidence(
  result: V2CopyExecutionResult,
  preflight: V2CopyPreflight,
) {
  const generatedPlatforms = result.generated_copy_matrix.copies.map(
    (copy) => copy.platform,
  );
  return (
    result.preflight_digest === preflight.preflight_digest &&
    result.copy_matrix_id === result.generated_copy_matrix.id &&
    sameOrderedPlatforms(
      result.recommendation_target_copy_platforms,
      result.v2_copy_target_platforms,
    ) &&
    sameOrderedPlatforms(
      result.v2_copy_target_platforms,
      preflight.v2_copy_target_platforms,
    ) &&
    sameOrderedPlatforms(
      result.v2_copy_target_platforms,
      result.persisted_copy_platforms,
    ) &&
    sameOrderedPlatforms(result.persisted_copy_platforms, generatedPlatforms)
  );
}

function v2VideoSourceRequest(
  recommendation: GrowthAnalysis,
  copy: V2CopyExecutionResult,
) {
  return {
    ...v2SourceRequest(recommendation),
    candidate_copy_matrix_id: copy.generated_copy_matrix.id,
  };
}

function sameV2VideoPreflightIdentity(
  preflight: V2VideoProjectPreflight,
  recommendation: GrowthAnalysis,
  copy: V2CopyExecutionResult,
  productId: number,
) {
  return (
    preflight.product_id === productId &&
    preflight.source_context_digest ===
      recommendation.source_context_digest &&
    preflight.source_recommendation_digest ===
      recommendation.recommendation_digest &&
    preflight.source_marketing_strategy_id ===
      recommendation.source_marketing_strategy_id &&
    preflight.source_copy_matrix_id ===
      recommendation.source_copy_matrix_id &&
    preflight.source_video_project_id ===
      recommendation.source_video_project_id &&
    preflight.candidate_copy_matrix_id ===
      copy.generated_copy_matrix.id
  );
}

function sameV2VideoExecutionIdentity(
  result: V2VideoProjectExecutionResult,
  recommendation: GrowthAnalysis,
  copy: V2CopyExecutionResult,
  preflight: V2VideoProjectPreflight,
  productId: number,
) {
  return (
    result.product_id === productId &&
    result.source_context_digest ===
      recommendation.source_context_digest &&
    result.source_recommendation_digest ===
      recommendation.recommendation_digest &&
    result.source_marketing_strategy_id ===
      recommendation.source_marketing_strategy_id &&
    result.source_copy_matrix_id ===
      recommendation.source_copy_matrix_id &&
    result.source_video_project_id ===
      recommendation.source_video_project_id &&
    result.candidate_copy_matrix_id ===
      copy.generated_copy_matrix.id &&
    result.generated_video_project.product_id === productId &&
    result.generated_video_project.marketing_strategy_id ===
      recommendation.source_marketing_strategy_id &&
    result.generated_video_project.copy_matrix_id ===
      copy.generated_copy_matrix.id &&
    result.generated_video_project.platform === preflight.platform &&
    result.generated_video_project.duration_seconds ===
      preflight.duration_seconds &&
    result.generated_video_project.aspect_ratio === preflight.aspect_ratio
  );
}
