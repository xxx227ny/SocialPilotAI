import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { getApiErrorMessage } from "../../api/client";
import { getFeedbackContext } from "../../api/growth";
import {
  createPresentationSnapshot,
  listPresentationSnapshots,
} from "../../api/presentationSnapshots";
import { listPublishArtifacts, listPublishTasks } from "../../api/social";
import { getVideoProject } from "../../api/videos";
import type {
  PresentationSnapshot,
  PresentationSnapshotCreateRequest,
  PresentationSnapshotSection,
} from "../../types/presentationSnapshot";
import type { PublishTask } from "../../types/social";
import { snapshotPresentationUrl } from "../presentation/snapshotPresentationState";
import {
  autoSelectedArtifactId,
  buildPresentationArtifactSources,
  buildPresentationSnapshotRequest,
  findSameSourcePresentationSnapshot,
  matchingPublishTasks,
  type PresentationArtifactSource,
} from "./presentationSnapshotState";

type LoadState = "loading" | "ready" | "error";
type SaveOutcome = "new" | "reused" | "history" | null;

const SECTION_LABELS: Record<PresentationSnapshotSection, string> = {
  marketing_brief: "MarketingBrief",
  marketing_strategy: "Strategy",
  copy_matrix: "CopyMatrix",
  video_project: "VideoProject",
  render_task: "RenderTask",
  artifact: "Artifact",
  publish_task: "PublishTask",
  campaigns: "Campaigns",
};

export function PresentationSnapshotPanel({ productId }: { productId: number }) {
  const [sources, setSources] = useState<PresentationArtifactSource[]>([]);
  const [publishTasks, setPublishTasks] = useState<PublishTask[]>([]);
  const [campaignIds, setCampaignIds] = useState<number[]>([]);
  const [selectedArtifactId, setSelectedArtifactId] = useState<number | null>(null);
  const [selectedPublishTaskId, setSelectedPublishTaskId] = useState<
    number | null
  >(null);
  const [sourceState, setSourceState] = useState<LoadState>("loading");
  const [sourceError, setSourceError] = useState("");
  const [history, setHistory] = useState<PresentationSnapshot[]>([]);
  const [historyState, setHistoryState] = useState<LoadState>("loading");
  const [historyError, setHistoryError] = useState("");
  const [currentSnapshot, setCurrentSnapshot] =
    useState<PresentationSnapshot | null>(null);
  const [saveOutcome, setSaveOutcome] = useState<SaveOutcome>(null);
  const [saveError, setSaveError] = useState("");
  const [saving, setSaving] = useState(false);
  const createInFlight = useRef(false);

  const loadHistory = useCallback(async (signal?: AbortSignal) => {
    setHistoryState("loading");
    setHistoryError("");
    try {
      const snapshots = await listPresentationSnapshots(productId, signal);
      setHistory(snapshots);
      setHistoryState("ready");
    } catch (error) {
      if (signal?.aborted) return;
      setHistoryError(getApiErrorMessage(error, "演示快照历史读取失败。"));
      setHistoryState("error");
    }
  }, [productId]);

  useEffect(() => {
    const controller = new AbortController();
    setSources([]);
    setPublishTasks([]);
    setCampaignIds([]);
    setSelectedArtifactId(null);
    setSelectedPublishTaskId(null);
    setCurrentSnapshot(null);
    setSaveOutcome(null);
    setSaveError("");
    setSourceState("loading");
    setSourceError("");

    void Promise.all([
      listPublishArtifacts(productId, controller.signal),
      listPublishTasks(productId, controller.signal),
      getFeedbackContext(productId, controller.signal),
    ])
      .then(async ([artifacts, tasks, feedback]) => {
        const videoProjectIds = [
          ...new Set(artifacts.map((artifact) => artifact.video_project_id)),
        ];
        const projects = await Promise.all(
          videoProjectIds.map((videoProjectId) =>
            getVideoProject(videoProjectId, controller.signal),
          ),
        );
        if (controller.signal.aborted) return;
        const exactSources = buildPresentationArtifactSources(
          productId,
          artifacts,
          projects,
        );
        setSources(exactSources);
        setPublishTasks(tasks);
        setCampaignIds(feedback.campaign_ids);
        setSelectedArtifactId(autoSelectedArtifactId(exactSources));
        setSourceState("ready");
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setSourceError(
          getApiErrorMessage(error, "精确快照来源读取失败，请检查本地服务。"),
        );
        setSourceState("error");
      });

    void loadHistory(controller.signal);
    return () => controller.abort();
  }, [loadHistory, productId]);

  const selectedSource = useMemo(
    () =>
      sources.find((source) => source.artifact_id === selectedArtifactId) ?? null,
    [selectedArtifactId, sources],
  );
  const matchingTasks = useMemo(
    () =>
      selectedArtifactId === null
        ? []
        : matchingPublishTasks(publishTasks, productId, selectedArtifactId),
    [productId, publishTasks, selectedArtifactId],
  );

  useEffect(() => {
    setSelectedPublishTaskId(
      matchingTasks.length === 1 ? matchingTasks[0].id : null,
    );
    setCurrentSnapshot(null);
    setSaveOutcome(null);
    setSaveError("");
  }, [matchingTasks]);

  const resolvedPublishTaskId =
    matchingTasks.length === 1
      ? matchingTasks[0].id
      : selectedPublishTaskId;
  const publishIdentityReady =
    matchingTasks.length <= 1 || resolvedPublishTaskId !== null;
  const request = useMemo<PresentationSnapshotCreateRequest | null>(
    () =>
      selectedSource && publishIdentityReady
        ? buildPresentationSnapshotRequest(
            selectedSource,
            resolvedPublishTaskId,
            campaignIds,
          )
        : null,
    [campaignIds, publishIdentityReady, resolvedPublishTaskId, selectedSource],
  );
  const sameSourceHistory = useMemo(
    () => (request ? findSameSourcePresentationSnapshot(history, request) : null),
    [history, request],
  );
  const displayedSnapshot = currentSnapshot ?? sameSourceHistory;
  const displayedOutcome: SaveOutcome =
    saveOutcome ?? (sameSourceHistory ? "history" : null);

  async function createSnapshot() {
    if (!request || createInFlight.current) return;
    setSaveError("");
    createInFlight.current = true;
    setSaving(true);
    try {
      const result = await createPresentationSnapshot(productId, request);
      setCurrentSnapshot(result.snapshot);
      setSaveOutcome(result.reused ? "reused" : "new");
      setHistory((current) => [
        ...current.filter((item) => item.id !== result.snapshot.id),
        result.snapshot,
      ]);
    } catch (error) {
      setSaveError(getApiErrorMessage(error, "演示快照创建失败。"));
    } finally {
      createInFlight.current = false;
      setSaving(false);
    }
  }

  return (
    <section className="presentation-snapshot-panel" aria-label="演示快照">
      <header className="presentation-snapshot-panel__heading">
        <div>
          <span>PRESENTATION SNAPSHOT</span>
          <h4>创建演示快照</h4>
          <p>只读取本地精确关系并保存不可变副本；不会调用任何 Provider。</p>
        </div>
        <button
          className="text-button"
          type="button"
          onClick={() => void loadHistory()}
          disabled={historyState === "loading"}
        >
          {historyState === "loading" ? "读取中…" : "重新读取历史"}
        </button>
      </header>

      {sourceState === "loading" ? (
        <p className="presentation-snapshot-panel__notice">正在发现本地精确来源…</p>
      ) : sourceState === "error" ? (
        <p className="presentation-snapshot-panel__notice presentation-snapshot-panel__notice--error">
          {sourceError}
        </p>
      ) : sources.length === 0 ? (
        <p className="presentation-snapshot-panel__notice">
          当前商品没有通过文件与关系校验的 Artifact，暂不能创建快照。
        </p>
      ) : (
        <div className="presentation-snapshot-panel__source">
          <label>
            已验证 Artifact
            <select
              value={selectedArtifactId ?? ""}
              onChange={(event) =>
                setSelectedArtifactId(
                  event.target.value ? Number(event.target.value) : null,
                )
              }
            >
              <option value="">
                {sources.length > 1 ? "请选择精确 Artifact" : "请选择 Artifact"}
              </option>
              {sources.map((source) => (
                <option key={source.artifact_id} value={source.artifact_id}>
                  Artifact #{source.artifact_id} · VideoProject #{source.video_project_id}
                </option>
              ))}
            </select>
          </label>
          {sources.length > 1 && selectedArtifactId === null ? (
            <small>检测到多个合法 Artifact，必须由用户明确选择，不使用 latest。</small>
          ) : null}

          {selectedSource ? (
            <div className="presentation-snapshot-panel__identity">
              <Identity label="Product" value={productId} />
              <Identity label="MarketingBrief" missing />
              <Identity label="Strategy" value={selectedSource.marketing_strategy_id} />
              <Identity label="CopyMatrix" value={selectedSource.copy_matrix_id} />
              <Identity label="VideoProject" value={selectedSource.video_project_id} />
              <Identity label="RenderTask" value={selectedSource.render_task_id} />
              <Identity label="Artifact" value={selectedSource.artifact_id} />
            </div>
          ) : null}

          {selectedSource && matchingTasks.length > 1 ? (
            <label>
              匹配的 PublishTask
              <select
                value={selectedPublishTaskId ?? ""}
                onChange={(event) =>
                  setSelectedPublishTaskId(
                    event.target.value ? Number(event.target.value) : null,
                  )
                }
              >
                <option value="">请选择精确 PublishTask</option>
                {matchingTasks.map((task) => (
                  <option key={task.id} value={task.id}>
                    PublishTask #{task.id} · {task.status} · {task.privacy_status}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          {selectedSource ? (
            <p className="presentation-snapshot-panel__associations">
              PublishTask：
              {matchingTasks.length === 0
                ? "缺失"
                : resolvedPublishTaskId === null
                  ? "待明确选择"
                  : `#${resolvedPublishTaskId}`} · Campaign IDs：
              {campaignIds.length > 0
                ? campaignIds.map((id) => `#${id}`).join(" · ")
                : "缺失"}
            </p>
          ) : null}

          <button
            className="primary-action"
            type="button"
            onClick={() => void createSnapshot()}
            disabled={!request || saving}
          >
            {saving
              ? "正在创建…"
              : "创建演示快照"}
          </button>
          {saveError ? (
            <p className="presentation-snapshot-panel__notice presentation-snapshot-panel__notice--error">
              {saveError}
            </p>
          ) : null}
        </div>
      )}

      {displayedSnapshot ? (
        <SnapshotRecord snapshot={displayedSnapshot} outcome={displayedOutcome} />
      ) : null}

      <div className="presentation-snapshot-panel__history">
        <h5>历史快照</h5>
        {historyState === "error" ? (
          <p className="presentation-snapshot-panel__notice presentation-snapshot-panel__notice--error">
            {historyError}
          </p>
        ) : historyState === "ready" && history.length === 0 ? (
          <p className="presentation-snapshot-panel__notice">当前商品还没有演示快照。</p>
        ) : (
          history.map((snapshot) => (
            <SnapshotRecord key={snapshot.id} snapshot={snapshot} outcome="history" compact />
          ))
        )}
      </div>
    </section>
  );
}

function Identity({
  label,
  value,
  missing = false,
}: {
  label: string;
  value?: number;
  missing?: boolean;
}) {
  return (
    <span>
      <small>{label}</small>
      <strong>{missing ? "缺失" : `#${value}`}</strong>
    </span>
  );
}

function SnapshotRecord({
  snapshot,
  outcome,
  compact = false,
}: {
  snapshot: PresentationSnapshot;
  outcome: SaveOutcome;
  compact?: boolean;
}) {
  const included = (Object.keys(SECTION_LABELS) as PresentationSnapshotSection[])
    .filter((section) => !snapshot.missing_sections.includes(section))
    .map((section) => SECTION_LABELS[section]);
  const missing = snapshot.missing_sections.map((section) => SECTION_LABELS[section]);
  return (
    <article className={`presentation-snapshot-record${compact ? " presentation-snapshot-record--compact" : ""}`}>
      <header>
        <strong>Snapshot #{snapshot.id}</strong>
        <span>
          {outcome === "new"
            ? "新建"
            : outcome === "reused"
              ? "已复用"
              : "同来源历史"}
        </span>
      </header>
      <p>
        Digest：<code>{digestSummary(snapshot.digest)}</code> · 创建时间：
        {formatDateTime(snapshot.created_at)}
      </p>
      <p>包含项：{included.length > 0 ? included.join(" · ") : "无"}</p>
      <p>缺失项：{missing.length > 0 ? missing.join(" · ") : "无"}</p>
      {compact ? (
        <a
          className="presentation-snapshot-record__enter"
          href={snapshotPresentationUrl(snapshot.id)}
        >
          进入演示
        </a>
      ) : null}
    </article>
  );
}

function digestSummary(digest: string): string {
  return digest.length > 20
    ? `${digest.slice(0, 12)}…${digest.slice(-8)}`
    : digest;
}

function formatDateTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "时间未知"
    : new Intl.DateTimeFormat("zh-CN", {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(date);
}
