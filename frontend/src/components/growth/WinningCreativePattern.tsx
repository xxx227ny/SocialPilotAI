import type { DashboardCopyMatrix, DashboardStrategy, PlatformMetrics } from "../../types/dashboard";
import type { VideoProject, VideoScene } from "../../types/video";
import { findLeadingPlatform } from "./PerformanceFeedbackLoop";

interface WinningCreativePatternProps {
  strategy: DashboardStrategy | null;
  copyMatrix: DashboardCopyMatrix | null;
  videoProject: VideoProject | null;
  platforms: PlatformMetrics[];
}

export function WinningCreativePattern({ strategy, copyMatrix, videoProject, platforms }: WinningCreativePatternProps) {
  const leader = findLeadingPlatform(platforms);
  const relatedCopy = copyMatrix?.copies.find((copy) => copy.platform.toLowerCase() === leader?.platform.toLowerCase()) ?? copyMatrix?.copies[0];
  const relatedScenes = videoProject?.scenes.filter((scene) => scene.sequence === 2 || scene.sequence === 3).slice(0, 2) ?? [];

  return (
    <section className="winning-pattern">
      <header><div><span>WINNING CREATIVE PATTERN</span><h2>高表现内容方向</h2></div><p>把平台表现与已有策略、文案和视频蓝图并置，形成下一轮可测试方向。</p></header>
      <div className="winning-pattern__grid">
        <PatternCard number="01" label="Creative Direction" title="创意方向"><strong>{strategy?.angles[0] ?? "等待营销策略角度"}</strong><p>{strategy?.positioning ?? "当前 Snapshot 暂无商品定位。"}</p></PatternCard>
        <PatternCard number="02" label="Related Hook" title={relatedCopy ? `${relatedCopy.platform} Hook` : "相关平台 Hook"}><blockquote>{relatedCopy?.hook ?? "当前 Snapshot 暂无可关联的平台文案。"}</blockquote>{leader && <p>关联当前 ROAS 领先平台：{leader.platform}</p>}</PatternCard>
        <PatternCard number="03" label="Related Video Scene" title="对应视频场景">{relatedScenes.length > 0 ? <div className="winning-pattern__scenes">{relatedScenes.map((scene) => <SceneDirection scene={scene} key={scene.sequence} />)}</div> : <p>当前 Snapshot 暂无可关联的视频分镜。</p>}</PatternCard>
      </div>
      <small className="winning-pattern__disclaimer">这是基于预置快照的内容方向展示，不构成创意级广告归因结论。</small>
    </section>
  );
}

const sceneNames: Record<number, string> = { 2: "Desk Blend", 3: "Gym Carry" };
function SceneDirection({ scene }: { scene: VideoScene }) { return <div><span>{sceneNames[scene.sequence] ?? `Scene ${scene.sequence}`}</span><p>{scene.visual_description}</p></div>; }
function PatternCard({ number, label, title, children }: { number: string; label: string; title: string; children: React.ReactNode }) { return <article><header><span>{number}</span><div><small>{label}</small><strong>{title}</strong></div></header>{children}</article>; }
