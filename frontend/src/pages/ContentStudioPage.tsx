import { useCallback, useEffect, useState } from "react";

import { getVideoRenderArtifacts } from "../api/videos";
import { DemoContextBar } from "../components/showcase/DemoContextBar";
import { LiveWanxGenerationPanel } from "../components/video/LiveWanxGenerationPanel";
import { VideoHero } from "../components/video/VideoHero";
import { VideoStoryboard } from "../components/video/VideoStoryboard";
import { VerifiedWanxOutput } from "../components/video/VerifiedWanxOutput";
import {
  isLiveWanxDemoEnabled,
  selectLatestPlayableArtifact,
} from "../components/video/liveWanxGeneration";
import { useDemoSnapshot } from "../hooks/useDemoSnapshot";
import { usePresentationMode } from "../context/PresentationModeContext";
import type { VideoRenderArtifact } from "../types/video";

export function ContentStudioPage() {
  const { snapshot, loading, error } = useDemoSnapshot();
  const { isPresentation } = usePresentationMode();
  const [artifacts, setArtifacts] = useState<VideoRenderArtifact[]>([]);
  const videoProjectId = snapshot?.video_project?.id;
  const liveWanxEnabled = isLiveWanxDemoEnabled(
    import.meta.env.VITE_ENABLE_LIVE_WANX_DEMO,
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

  return (
    <div className="competition-page video-blueprint-page">
      <DemoContextBar />
      {loading ? (
        <PageState title="正在读取视频蓝图" detail="只读取预置方案，不触发视频策划或任何 AI 调用。" />
      ) : snapshot?.video_project ? (
        <>
          <VideoHero project={snapshot.video_project} />
          <VideoStoryboard scenes={snapshot.video_project.scenes} />
          {playableArtifact && (
            <VerifiedWanxOutput artifact={playableArtifact} />
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

function PageState({ title, detail, error = false }: { title: string; detail: string; error?: boolean }) {
  return <section className={`competition-state${error ? " competition-state--error" : ""}`}><span>{error ? "!" : "…"}</span><strong>{title}</strong><p>{detail}</p></section>;
}
