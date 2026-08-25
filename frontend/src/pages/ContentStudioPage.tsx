import { useCallback, useEffect, useState } from "react";

import { listPublishTasks } from "../api/social";
import { getVideoRenderArtifacts } from "../api/videos";
import { OperationalProductSelector } from "../components/product/OperationalProductSelector";
import { PresentationSnapshotPanel } from "../components/product/PresentationSnapshotPanel";
import { SocialPublishingPanel } from "../components/product/SocialPublishingPanel";
import { DemoContextBar } from "../components/showcase/DemoContextBar";
import { LiveWanxGenerationPanel } from "../components/video/LiveWanxGenerationPanel";
import { BatchVideoJobPanel } from "../components/video/BatchVideoJobPanel";
import { InitialVideoProjectPanel } from "../components/video/InitialVideoProjectPanel";
import { RealProductVideoPanel } from "../components/video/RealProductVideoPanel";
import { VideoCompositionPanel } from "../components/video/VideoCompositionPanel";
import { VideoRenderPreflightPanel } from "../components/video/VideoRenderPreflightPanel";
import { shouldMountBatchVideoFlow } from "../components/video/batchVideoJobState";
import { VideoHero } from "../components/video/VideoHero";
import { VideoStoryboard } from "../components/video/VideoStoryboard";
import { VerifiedWanxOutput } from "../components/video/VerifiedWanxOutput";
import { PresentationDeliveryEvidence } from "../components/video/PresentationDeliveryEvidence";
import { selectPresentationDeliveryEvidence } from "../components/video/selectPresentationDeliveryEvidence";
import {
  isLiveWanxDemoEnabled,
  selectLatestPlayableArtifact,
} from "../components/video/liveWanxGeneration";
import { useDemoSnapshot } from "../hooks/useDemoSnapshot";
import { usePresentationMode } from "../context/PresentationModeContext";
import type { PublishTask } from "../types/social";
import type { VideoRenderArtifact } from "../types/video";
import { batchVideoJobsEnabled, qwenVideoScriptGenerationEnabled, videoScriptVersionsEnabled } from "../config/features";

export function ContentStudioPage() {
  const { snapshot, loading, error } = useDemoSnapshot();
  const { isPresentation } = usePresentationMode();
  const [artifacts, setArtifacts] = useState<VideoRenderArtifact[]>([]);
  const [publishTasks, setPublishTasks] = useState<PublishTask[]>([]);
  const [deliveryLoading, setDeliveryLoading] = useState(false);
  const [deliveryLoadFailed, setDeliveryLoadFailed] = useState(false);
  const videoProjectId = snapshot?.video_project?.id;
  const productId = snapshot?.product.id;
  const liveWanxEnabled = isLiveWanxDemoEnabled(
    import.meta.env.VITE_ENABLE_LIVE_WANX_DEMO,
  );
  const showBatchVideoJobs = shouldMountBatchVideoFlow(
    batchVideoJobsEnabled,
    isPresentation,
  );

  const loadArtifacts = useCallback(async () => {
    if (videoProjectId === undefined) {
      setArtifacts([]);
      return;
    }
    try {
      setArtifacts(await getVideoRenderArtifacts(videoProjectId));
    } catch {
      setArtifacts([]);
    }
  }, [videoProjectId]);

  useEffect(() => {
    setArtifacts([]);
    void loadArtifacts();
  }, [loadArtifacts]);

  const playableArtifact = selectLatestPlayableArtifact(artifacts);
  const playableArtifactId = playableArtifact?.id;

  useEffect(() => {
    setPublishTasks([]);
    setDeliveryLoadFailed(false);
    if (!isPresentation || productId === undefined || playableArtifactId === undefined) {
      setDeliveryLoading(false);
      return;
    }

    const controller = new AbortController();
    setDeliveryLoading(true);
    void listPublishTasks(productId, controller.signal)
      .then((tasks) => {
        setPublishTasks(
          selectPresentationDeliveryEvidence(tasks, productId, playableArtifactId),
        );
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        setDeliveryLoadFailed(true);
      })
      .finally(() => {
        if (!controller.signal.aborted) setDeliveryLoading(false);
      });

    return () => controller.abort();
  }, [isPresentation, playableArtifactId, productId]);

  if (!isPresentation) {
    return <VideoProductionWorkspace showBatchVideoJobs={showBatchVideoJobs} />;
  }

  return (
    <div className="competition-page video-blueprint-page">
      <DemoContextBar />
      {showBatchVideoJobs && <BatchVideoJobPanel scriptVersionsEnabled={videoScriptVersionsEnabled} qwenScriptEnabled={qwenVideoScriptGenerationEnabled} />}
      {loading ? (
        <PageState title="正在读取视频蓝图" detail="只读取预置方案，不触发视频策划或任何 AI 调用。" />
      ) : snapshot?.video_project ? (
        <>
          <VideoHero project={snapshot.video_project} />
          <VideoStoryboard scenes={snapshot.video_project.scenes} />
          {playableArtifact && (
            <>
              <VerifiedWanxOutput artifact={playableArtifact} />
              {isPresentation && (
                <PresentationDeliveryEvidence
                  tasks={publishTasks}
                  loading={deliveryLoading}
                  loadFailed={deliveryLoadFailed}
                />
              )}
            </>
          )}
          {liveWanxEnabled && !isPresentation && (
            <LiveWanxGenerationPanel
              videoProjectId={snapshot.video_project.id}
              onArtifactReady={loadArtifacts}
            />
          )}
          <section className="video-blueprint-cta">
            <div><span>END CARD</span><h2>从生活方式故事走向购买行动</h2></div>
            <strong>{snapshot.video_project.cta}</strong>
          </section>
        </>
      ) : snapshot ? (
        <PageState title="视频蓝图暂缺" detail="当前 Demo Snapshot 中没有可展示的视频生产方案。" />
      ) : (
        <PageState title="演示快照未就绪" detail={error} error />
      )}
    </div>
  );
}

type VideoWorkspaceView = "production" | "batch" | "advanced";

function VideoProductionWorkspace({
  showBatchVideoJobs,
}: {
  showBatchVideoJobs: boolean;
}) {
  const [view, setView] = useState<VideoWorkspaceView>("production");

  return (
    <div className="competition-page video-workspace-page">
      <header className="competition-hero">
        <div>
          <span>视频生产工作台</span>
          <h1>AI 视频工厂</h1>
          <p>批量编排、一键商品视频和高级制作按任务分区展示。</p>
        </div>
        <div className="readonly-badge">
          <strong>目标 1</strong>
          <span>脚本 → 画面 → 配音 → 成片</span>
        </div>
      </header>

      <nav className="workspace-tabs" aria-label="视频工厂功能分区">
        <button
          type="button"
          className={view === "production" ? "workspace-tabs__active" : ""}
          onClick={() => setView("production")}
        >
          一键商品视频
        </button>
        {showBatchVideoJobs ? (
          <button
            type="button"
            className={view === "batch" ? "workspace-tabs__active" : ""}
            onClick={() => setView("batch")}
          >
            批量任务
          </button>
        ) : null}
        <button
          type="button"
          className={view === "advanced" ? "workspace-tabs__active" : ""}
          onClick={() => setView("advanced")}
        >
          高级制作与交付
        </button>
      </nav>

      {view === "production" ? (
        <OperationalProductSelector
          title="真实商品视频生产"
          description="选择商品后运行三平台一键生产，并查看每个平台的进度、失败原因和成片。"
        >
          {(product) => <RealProductVideoPanel product={product} />}
        </OperationalProductSelector>
      ) : null}

      {view === "batch" && showBatchVideoJobs ? (
        <BatchVideoJobPanel
          scriptVersionsEnabled={videoScriptVersionsEnabled}
          qwenScriptEnabled={qwenVideoScriptGenerationEnabled}
        />
      ) : null}

      {view === "advanced" ? <AdvancedVideoWorkspace /> : null}
    </div>
  );
}

function AdvancedVideoWorkspace() {
  const [videoProjectId, setVideoProjectId] = useState<number | undefined>();

  return (
    <OperationalProductSelector
      title="高级制作与交付"
      description="用于单场景蓝图、渲染、合成、社交发布和演示快照；普通一键生产无需进入这里。"
    >
      {(product) => (
        <div className="advanced-video-workspace">
          <InitialVideoProjectPanel
            product={product}
            onGenerated={setVideoProjectId}
          />
          <VideoRenderPreflightPanel
            product={product}
            videoProjectId={videoProjectId}
          />
          <VideoCompositionPanel
            product={product}
            videoProjectId={videoProjectId}
          />
          <SocialPublishingPanel productId={product.id} />
          <PresentationSnapshotPanel productId={product.id} />
        </div>
      )}
    </OperationalProductSelector>
  );
}

function PageState({ title, detail, error = false }: { title: string; detail: string; error?: boolean }) {
  return <section className={`competition-state${error ? " competition-state--error" : ""}`}><span>{error ? "!" : "…"}</span><strong>{title}</strong><p>{detail}</p></section>;
}
