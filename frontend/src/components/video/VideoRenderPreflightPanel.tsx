import { useEffect, useRef, useState } from "react";

import { getApiErrorMessage } from "../../api/client";
import {
  executeVideoProjectRender,
  getLatestVideoProjectForProduct,
  getVideoProject,
  getVideoRenderArtifactMetadata,
  getVideoRenderJob,
  getVideoRenderPreflight,
  listVideoRenderJobs,
  recoverVideoRenderTask,
  refreshWorkspaceVideoRenderTask,
} from "../../api/videos";
import { videoRenderExecutionEnabled } from "../../config/features";
import { usePresentationMode } from "../../context/PresentationModeContext";
import type { ExecutionJob } from "../../types/execution";
import type { Product } from "../../types/product";
import type {
  VideoProject,
  VideoRenderOperation,
  VideoRenderPreflight,
} from "../../types/video";
import { StableVideoArtifactPanel } from "./StableVideoArtifactPanel";
import {
  WANX_VIDEO_RENDER_REFRESH_V1,
  WANX_VIDEO_RENDER_SUBMIT_V1,
  buildVideoRenderSubmitRequest,
  cancelVideoRenderRequestControllers,
  canReleaseVideoRenderOperationLock,
  canStartVideoRenderResultRead,
  exactVideoRenderResult,
  isCurrentVideoRenderOperation,
  selectExactVideoRenderSubmitJob,
  shouldContinueVideoRenderPolling,
  videoRenderJobNeedsPolling,
} from "./videoRenderQueueState";
import type {
  VideoRenderOperationIdentity,
  VideoRenderPollOutcome,
} from "./videoRenderQueueState";

type LoadState = "loading" | "ready" | "blocked" | "error";
const LOCAL_JOB_POLL_INTERVAL_MS = 1500;

export function VideoRenderPreflightPanel({
  product,
  videoProjectId,
}: {
  product: Product;
  videoProjectId?: number;
}) {
  const { isPresentation } = usePresentationMode();
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [project, setProject] = useState<VideoProject | null>(null);
  const [preflight, setPreflight] = useState<VideoRenderPreflight | null>(null);
  const [job, setJob] = useState<ExecutionJob | null>(null);
  const [operation, setOperation] = useState<VideoRenderOperation | null>(null);
  const [costConfirmed, setCostConfirmed] = useState(false);
  const [message, setMessage] = useState("");
  const [jobReused, setJobReused] = useState(false);
  const [resultReadFailedJobId, setResultReadFailedJobId] = useState<
    number | null
  >(null);
  const operationIdRef = useRef(0);
  const loadControllerRef = useRef<AbortController | null>(null);
  const activeContextRef = useRef({
    productId: product.id,
    videoProjectId: null as number | null,
  });
  const submitLockRef = useRef<VideoRenderOperationIdentity | null>(null);
  const refreshLockRef = useRef<VideoRenderOperationIdentity | null>(null);
  const pollIdentityRef = useRef<VideoRenderOperationIdentity | null>(null);
  const resultReadLockRef = useRef<VideoRenderOperationIdentity | null>(null);
  const autoResultReadJobIdRef = useRef<number | null>(null);

  function createIdentity(
    exactProjectId: number,
    jobId: number | null,
    renderTaskId: number | null,
  ): VideoRenderOperationIdentity {
    return {
      productId: product.id,
      videoProjectId: exactProjectId,
      jobId,
      renderTaskId,
      operationId: ++operationIdRef.current,
      controller: new AbortController(),
    };
  }

  function contextMatches(identity: VideoRenderOperationIdentity): boolean {
    return (
      activeContextRef.current.productId === identity.productId &&
      activeContextRef.current.videoProjectId === identity.videoProjectId
    );
  }

  function requestIsCurrent(
    identity: VideoRenderOperationIdentity,
    current: VideoRenderOperationIdentity | null,
  ): boolean {
    return (
      contextMatches(identity) &&
      isCurrentVideoRenderOperation(identity, current)
    );
  }

  function cancelIdentity(identity: VideoRenderOperationIdentity | null) {
    identity?.controller.abort();
  }

  useEffect(() => {
    return () => {
      cancelVideoRenderRequestControllers({
        load: loadControllerRef.current,
        submit: submitLockRef.current,
        refresh: refreshLockRef.current,
        poll: pollIdentityRef.current,
        resultRead: resultReadLockRef.current,
      });
      operationIdRef.current += 1;
      activeContextRef.current = {
        productId: -1,
        videoProjectId: null,
      };
      loadControllerRef.current = null;
      submitLockRef.current = null;
      refreshLockRef.current = null;
      pollIdentityRef.current = null;
      resultReadLockRef.current = null;
      autoResultReadJobIdRef.current = null;
    };
  }, []);

  useEffect(() => {
    loadControllerRef.current?.abort();
    cancelIdentity(submitLockRef.current);
    cancelIdentity(refreshLockRef.current);
    cancelIdentity(pollIdentityRef.current);
    cancelIdentity(resultReadLockRef.current);
    submitLockRef.current = null;
    refreshLockRef.current = null;
    pollIdentityRef.current = null;
    resultReadLockRef.current = null;
    autoResultReadJobIdRef.current = null;
    activeContextRef.current = {
      productId: product.id,
      videoProjectId: null,
    };
    setProject(null);
    setPreflight(null);
    setJob(null);
    setOperation(null);
    setCostConfirmed(false);
    setMessage("");
    setJobReused(false);
    setResultReadFailedJobId(null);
    if (isPresentation) return;

    const controller = new AbortController();
    loadControllerRef.current = controller;
    const operationId = ++operationIdRef.current;
    setLoadState("loading");

    async function load() {
      try {
        const loadedProject = videoProjectId
          ? await getVideoProject(videoProjectId, controller.signal)
          : await getLatestVideoProjectForProduct(product.id, controller.signal);
        if (
          controller.signal.aborted ||
          loadedProject.product_id !== product.id ||
          operationId !== operationIdRef.current
        ) {
          return;
        }
        activeContextRef.current = {
          productId: product.id,
          videoProjectId: loadedProject.id,
        };
        setProject(loadedProject);
        const checked = await getVideoRenderPreflight(
          loadedProject.id,
          controller.signal,
        );
        if (
          controller.signal.aborted ||
          operationId !== operationIdRef.current ||
          activeContextRef.current.productId !== product.id ||
          activeContextRef.current.videoProjectId !== loadedProject.id ||
          checked.product_id !== product.id ||
          checked.video_project_id !== loadedProject.id
        ) {
          return;
        }
        setPreflight(checked);
        const jobs = await listVideoRenderJobs(
          WANX_VIDEO_RENDER_SUBMIT_V1,
          "video_project",
          loadedProject.id,
          controller.signal,
        );
        if (
          controller.signal.aborted ||
          operationId !== operationIdRef.current ||
          activeContextRef.current.productId !== product.id ||
          activeContextRef.current.videoProjectId !== loadedProject.id
        ) {
          return;
        }
        const restored = selectExactVideoRenderSubmitJob(
          jobs,
          loadedProject.id,
          checked.input_digest,
        );
        setJob(restored);
        setJobReused(restored !== null);
        setLoadState(checked.ready_for_execution ? "ready" : "blocked");
      } catch (error) {
        if (
          controller.signal.aborted ||
          operationId !== operationIdRef.current
        ) {
          return;
        }
        setMessage(getApiErrorMessage(error, "Video Render Preflight failed"));
        setLoadState("error");
      }
    }

    void load();
    return () => controller.abort();
  }, [isPresentation, product.id, videoProjectId]);

  useEffect(() => {
    if (!job || !project || !videoRenderJobNeedsPolling(job)) return;
    const identity = createIdentity(
      project.id,
      job.id,
      operation?.task.id ?? null,
    );
    pollIdentityRef.current = identity;
    let timer: number | null = null;
    let disposed = false;

    function scheduleNextPoll() {
      if (disposed || !requestIsCurrent(identity, pollIdentityRef.current)) {
        return;
      }
      timer = window.setTimeout(() => void pollOnce(), LOCAL_JOB_POLL_INTERVAL_MS);
    }

    async function pollOnce() {
      if (disposed || !requestIsCurrent(identity, pollIdentityRef.current)) {
        return;
      }
      let outcome: VideoRenderPollOutcome = "LOCAL_READ_ERROR";
      try {
        const current = await getVideoRenderJob(
          identity.jobId!,
          identity.controller.signal,
        );
        if (
          !requestIsCurrent(identity, pollIdentityRef.current) ||
          current.id !== identity.jobId
        ) {
          return;
        }
        outcome = current;
        setJob(current);
        setMessage("");
      } catch (error) {
        if (!requestIsCurrent(identity, pollIdentityRef.current)) return;
        setMessage(getApiErrorMessage(error, "Local Job polling failed"));
      } finally {
        if (
          !disposed &&
          shouldContinueVideoRenderPolling(
            identity,
            pollIdentityRef.current,
            outcome,
          )
        ) {
          scheduleNextPoll();
        }
      }
    }

    scheduleNextPoll();
    return () => {
      disposed = true;
      if (timer !== null) window.clearTimeout(timer);
      identity.controller.abort();
      if (pollIdentityRef.current === identity) pollIdentityRef.current = null;
    };
  }, [job?.id, job?.status, operation?.task.id, project?.id]);

  async function readExactLocalResult(exactJob: ExecutionJob) {
    if (!project || !canStartVideoRenderResultRead(resultReadLockRef.current)) {
      return;
    }
    const result = exactVideoRenderResult(exactJob);
    if (!result) {
      setMessage("The Job succeeded without an exact local result identity.");
      return;
    }
    const identity = createIdentity(
      project.id,
      exactJob.id,
      result.type === "video_render_task" ? result.id : null,
    );
    resultReadLockRef.current = identity;
    setResultReadFailedJobId(null);
    setMessage("");
    try {
      let taskId = result.id;
      if (result.type === "video_render_artifact") {
        const artifact = await getVideoRenderArtifactMetadata(
          result.id,
          identity.controller.signal,
        );
        if (
          !requestIsCurrent(identity, resultReadLockRef.current) ||
          exactJob.id !== identity.jobId ||
          artifact.id !== result.id
        ) {
          return;
        }
        taskId = artifact.video_render_task_id;
      }
      const recovered = await recoverVideoRenderTask(
        taskId,
        identity.controller.signal,
      );
      if (
        !requestIsCurrent(identity, resultReadLockRef.current) ||
        exactJob.id !== identity.jobId ||
        recovered.product_id !== identity.productId ||
        recovered.video_project_id !== identity.videoProjectId ||
        recovered.task.id !== taskId
      ) {
        return;
      }
      setOperation(recovered);
      setResultReadFailedJobId(null);
      setMessage("");
    } catch (error) {
      if (!requestIsCurrent(identity, resultReadLockRef.current)) return;
      setResultReadFailedJobId(exactJob.id);
      setMessage(getApiErrorMessage(error, "Exact local result read failed"));
    } finally {
      if (
        contextMatches(identity) &&
        canReleaseVideoRenderOperationLock(
          identity,
          resultReadLockRef.current,
        )
      ) {
        resultReadLockRef.current = null;
      }
    }
  }

  useEffect(() => {
    if (!job || job.status !== "SUCCEEDED" || !project) return;
    if (autoResultReadJobIdRef.current === job.id) return;
    autoResultReadJobIdRef.current = job.id;
    void readExactLocalResult(job);
  }, [job?.id, job?.status, job?.result_entity_id, job?.result_entity_type, project]);

  function replaceLocalOperation() {
    cancelIdentity(pollIdentityRef.current);
    cancelIdentity(resultReadLockRef.current);
    pollIdentityRef.current = null;
    resultReadLockRef.current = null;
    autoResultReadJobIdRef.current = null;
    setResultReadFailedJobId(null);
  }

  async function submit() {
    if (
      !project ||
      !preflight ||
      !costConfirmed ||
      !preflight.ready_for_execution ||
      !videoRenderExecutionEnabled ||
      submitLockRef.current !== null
    ) {
      return;
    }
    replaceLocalOperation();
    const identity = createIdentity(project.id, null, null);
    submitLockRef.current = identity;
    setMessage("");
    try {
      const created = await executeVideoProjectRender(
        project.id,
        buildVideoRenderSubmitRequest(preflight),
        identity.controller.signal,
      );
      if (
        !requestIsCurrent(identity, submitLockRef.current) ||
        created.job.source_id !== identity.videoProjectId ||
        created.job.job_type !== WANX_VIDEO_RENDER_SUBMIT_V1
      ) {
        return;
      }
      setJob(created.job);
      setJobReused(created.reused);
      setCostConfirmed(false);
    } catch (error) {
      if (!requestIsCurrent(identity, submitLockRef.current)) return;
      setMessage(getApiErrorMessage(error, "Video Render enqueue failed"));
    } finally {
      if (
        contextMatches(identity) &&
        canReleaseVideoRenderOperationLock(identity, submitLockRef.current)
      ) {
        submitLockRef.current = null;
      }
    }
  }

  async function refresh() {
    if (!project || !operation || refreshLockRef.current !== null) return;
    replaceLocalOperation();
    const taskId = operation.task.id;
    const identity = createIdentity(project.id, null, taskId);
    refreshLockRef.current = identity;
    setMessage("");
    try {
      const created = await refreshWorkspaceVideoRenderTask(
        taskId,
        {
          video_project_id: project.id,
          refresh_request_id: createRefreshRequestId(),
        },
        identity.controller.signal,
      );
      if (
        !requestIsCurrent(identity, refreshLockRef.current) ||
        created.job.source_id !== taskId ||
        created.job.job_type !== WANX_VIDEO_RENDER_REFRESH_V1
      ) {
        return;
      }
      setJob(created.job);
      setJobReused(created.reused);
    } catch (error) {
      if (!requestIsCurrent(identity, refreshLockRef.current)) return;
      setMessage(getApiErrorMessage(error, "Explicit refresh enqueue failed"));
    } finally {
      if (
        contextMatches(identity) &&
        canReleaseVideoRenderOperationLock(identity, refreshLockRef.current)
      ) {
        refreshLockRef.current = null;
      }
    }
  }

  if (isPresentation) return null;

  const refreshAllowed =
    operation?.recovery.explicit_refresh_allowed === true &&
    !videoRenderJobNeedsPolling(job) &&
    refreshLockRef.current === null;
  const submitUnknown = job?.status === "SUBMIT_UNKNOWN";
  const submitVisible = !submitUnknown && job === null && operation === null;
  const resultReadFailed =
    job?.status === "SUCCEEDED" && resultReadFailedJobId === job.id;

  return (
    <section className="video-render-preflight" aria-busy={loadState === "loading"}>
      <header className="video-render-preflight__header">
        <div>
          <p className="product-detail-card__eyebrow">Wanx Execution Queue</p>
          <h3>Single-scene Render Artifact</h3>
        </div>
        <span className={`video-render-preflight__status is-${loadState}`}>
          {job?.status ?? loadState}
        </span>
      </header>

      {project ? (
        <p className="video-render-preflight__association">
          Exact VideoProject #{project.id}; first scene only. This is not a complete
          15-second composed video.
        </p>
      ) : null}
      {preflight ? (
        <div className="video-render-preflight__checks">
          <span>Input digest: {preflight.input_digest.slice(0, 12)}…</span>
          <span>Model: {preflight.provider_model}</span>
          <span>Resolution: {preflight.resolution}</span>
        </div>
      ) : null}
      {message ? <p className="video-render-preflight__safe-error">{message}</p> : null}
      {submitUnknown ? (
        <p className="video-render-preflight__safe-error">
          Provider submission is uncertain. Automatic and explicit resubmission are
          disabled.
        </p>
      ) : null}
      {job ? (
        <p className="video-render-preflight__association">
          Local Job #{job.id} · {job.status} {jobReused ? "· reused" : ""}
        </p>
      ) : null}

      {resultReadFailed && job ? (
        <button
          type="button"
          onClick={() => void readExactLocalResult(job)}
          disabled={resultReadLockRef.current !== null}
        >
          Re-read local result
        </button>
      ) : null}

      {submitVisible ? (
        <div className="video-render-preflight__execution">
          <label>
            <input
              type="checkbox"
              checked={costConfirmed}
              onChange={(event) => setCostConfirmed(event.target.checked)}
              disabled={videoRenderJobNeedsPolling(job)}
            />
            I explicitly confirm possible Wanx usage charges.
          </label>
          <button
            type="button"
            onClick={() => void submit()}
            disabled={
              !costConfirmed ||
              !preflight?.ready_for_execution ||
              !videoRenderExecutionEnabled ||
              videoRenderJobNeedsPolling(job)
            }
          >
            Enqueue single-scene render
          </button>
        </div>
      ) : null}

      {operation ? (
        <div className="video-render-preflight__execution">
          <p>
            RenderTask #{operation.task.id} · {operation.task.status}
          </p>
          {refreshAllowed ? (
            <button type="button" onClick={() => void refresh()}>
              Enqueue one explicit refresh
            </button>
          ) : null}
          {operation.artifact ? (
            <StableVideoArtifactPanel
              productId={operation.product_id}
              videoProjectId={operation.video_project_id}
              renderTaskId={operation.task.id}
              artifact={operation.artifact}
            />
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

function createRefreshRequestId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `refresh-${Date.now()}-${Math.random().toString(36).slice(2, 12)}`;
}
