import type { VideoProject } from "../../types/video";

export function VideoHero({ project }: { project: VideoProject }) {
  return (
    <section className="video-blueprint-hero">
      <div>
        <span>AI VIDEO BLUEPRINT</span>
        <h1>AI短视频创意蓝图</h1>
        <p>将商品定位、用户场景和平台策略转化为可执行的视频分镜方案</p>
      </div>
      <div className="video-blueprint-hero__story">
        <small>CAMPAIGN CONCEPT</small>
        <h2>{project.title}</h2>
        <strong>{project.platform} · {project.duration_seconds}s · {project.aspect_ratio}</strong>
        <p>{project.concept}</p>
      </div>
    </section>
  );
}
