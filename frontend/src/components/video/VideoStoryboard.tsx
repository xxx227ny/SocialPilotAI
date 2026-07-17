import type { VideoScene } from "../../types/video";

const sceneStories: Record<number, { title: string; fallback: string; objective: string }> = {
  1: { title: "Stop the scroll", fallback: "水果快速进入搅拌杯", objective: "前三秒吸引用户注意" },
  2: { title: "Desk Blend", fallback: "办公桌旁完成制作", objective: "展示便利办公场景" },
  3: { title: "Gym Carry", fallback: "通勤到健身房", objective: "强化移动生活方式" },
  4: { title: "Product Hero", fallback: "产品展示和 CTA 收尾", objective: "推动购买行动" },
};

export function VideoStoryboard({ scenes }: { scenes: VideoScene[] }) {
  const storyboard = [...scenes].sort((a, b) => a.sequence - b.sequence).slice(0, 4);

  return (
    <section className="video-storyboard">
      <header>
        <div><span>STORYBOARD</span><h2>从 Hook 到行动的完整叙事</h2></div>
        <p>每个分镜直接读取 Demo Snapshot，不在展示现场重新生成。</p>
      </header>
      <div className="video-storyboard__track">
        {storyboard.map((scene) => {
          const story = sceneStories[scene.sequence] ?? {
            title: `Scene ${String(scene.sequence).padStart(2, "0")}`,
            fallback: scene.visual_description,
            objective: scene.action,
          };
          return (
            <article key={scene.sequence}>
              <div className="video-storyboard__number">{String(scene.sequence).padStart(2, "0")}</div>
              <small>SCENE {String(scene.sequence).padStart(2, "0")}</small>
              <h3>{story.title}</h3>
              <strong>{scene.duration_seconds}s</strong>
              <p>{scene.visual_description || story.fallback}</p>
              <dl>
                <div><dt>视觉</dt><dd>{scene.shot_type}</dd></div>
                <div><dt>目标</dt><dd>{story.objective}</dd></div>
              </dl>
            </article>
          );
        })}
      </div>
    </section>
  );
}
