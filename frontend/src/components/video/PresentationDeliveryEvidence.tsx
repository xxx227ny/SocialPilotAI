import type { PublishTask } from "../../types/social";

interface PresentationDeliveryEvidenceProps {
  tasks: PublishTask[];
  loading: boolean;
  loadFailed: boolean;
}

export function PresentationDeliveryEvidence({
  tasks,
  loading,
  loadFailed,
}: PresentationDeliveryEvidenceProps) {
  return (
    <section className="presentation-delivery-evidence" aria-label="YouTube Delivery Evidence">
      <header>
        <span>DELIVERY EVIDENCE</span>
        <h2>YouTube Private</h2>
        <p>仅展示与当前 Product 和 Artifact 精确关联的本地成功记录。</p>
      </header>

      {loading ? (
        <p className="presentation-delivery-evidence__empty">正在读取本地发布记录…</p>
      ) : loadFailed ? (
        <p className="presentation-delivery-evidence__empty">
          本地发布记录读取失败；未展示未经验证的交付证据。
        </p>
      ) : tasks.length === 0 ? (
        <p className="presentation-delivery-evidence__empty">
          当前 Artifact 没有匹配的 YouTube Private 成功记录。
        </p>
      ) : (
        <div className="presentation-delivery-evidence__records">
          {tasks.map((task) => (
            <article key={task.id}>
              <strong>PublishTask #{task.id}</strong>
              <dl>
                <EvidenceFact label="Status" value="SUCCEEDED" />
                <EvidenceFact label="Privacy" value="YouTube Private" />
                <EvidenceFact label="Artifact" value={`#${task.artifact_id}`} />
                <EvidenceFact
                  label="完成时间"
                  value={task.completed_at ? formatCompletedAt(task.completed_at) : "未记录"}
                />
                <EvidenceFact
                  label="Provider 确认身份"
                  value={task.provider_video_id ? "已记录" : "未记录"}
                />
              </dl>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

function EvidenceFact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function formatCompletedAt(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN");
}
