import { useEffect, useRef, useState } from "react";

import {
  finalizeInstagramPublish,
  getInstagramPublishJob,
  getPublishTask,
  listInstagramPublishArtifacts,
  listInstagramPublishJobs,
  preflightInstagramFinalize,
  preflightInstagramPublish,
  publishInstagram,
  refreshInstagramPublish,
} from "../../api/social";
import { getApiErrorMessage } from "../../api/client";
import type { ExecutionJob } from "../../types/execution";
import type {
  InstagramPublishPreflight,
  InstagramPublishingMetadata,
  PublishArtifactCandidate,
  PublishTask,
  SocialAccount,
} from "../../types/social";
import {
  INSTAGRAM_PUBLISH_FINALIZE_V1,
  INSTAGRAM_PUBLISH_REFRESH_V1,
  INSTAGRAM_PUBLISH_SUBMIT_V1,
  canEnqueueInstagramFinalize,
  canEnqueueInstagramRefresh,
  canReleaseInstagramPublishLock,
  cancelInstagramPublishingOperations,
  exactInstagramPublishTaskId,
  instagramJobNeedsPolling,
  isCurrentInstagramPublishOperation,
  isExactInstagramJob,
  isSameExactInstagramPollJob,
  shouldAdvanceInstagramPollCycle,
  type InstagramPublishIdentity,
} from "./instagramPublishingState";

export function InstagramPublishingPanel({ productId, accounts, onTask }: {
  productId: number; accounts: SocialAccount[]; onTask: (task: PublishTask) => void;
}) {
  const account = accounts.find((item) => item.platform === "instagram" && item.connection_status === "CONNECTED");
  const [artifacts, setArtifacts] = useState<PublishArtifactCandidate[]>([]);
  const [artifactId, setArtifactId] = useState("");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [tags, setTags] = useState("");
  const [shareToFeed, setShareToFeed] = useState(false);
  const [preflight, setPreflight] = useState<InstagramPublishPreflight | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [job, setJob] = useState<ExecutionJob | null>(null);
  const [task, setTask] = useState<PublishTask | null>(null);
  const [message, setMessage] = useState("");
  const [reading, setReading] = useState(false);
  const [pollCycle, setPollCycle] = useState(0);
  const operation = useRef(0);
  const submit = useRef<InstagramPublishIdentity | null>(null);
  const refresh = useRef<InstagramPublishIdentity | null>(null);
  const finalize = useRef<InstagramPublishIdentity | null>(null);
  const poll = useRef<InstagramPublishIdentity | null>(null);
  const read = useRef<InstagramPublishIdentity | null>(null);

  const identity = (controller: AbortController, jobId: number | null = null,
    taskId: number | null = null): InstagramPublishIdentity => ({
      productId, accountId: account?.id ?? 0, artifactId: Number(artifactId), jobId,
      taskId, operationId: ++operation.current, controller,
    });

  const cancelAll = () => {
    operation.current += 1;
    cancelInstagramPublishingOperations([submit.current, refresh.current, finalize.current, poll.current, read.current]);
    submit.current = refresh.current = finalize.current = poll.current = read.current = null;
  };

  useEffect(() => {
    const controller = new AbortController();
    if (account) void listInstagramPublishArtifacts(productId, controller.signal)
      .then((items) => { if (!controller.signal.aborted) setArtifacts(items); })
      .catch(() => { if (!controller.signal.aborted) setMessage("Instagram Artifact 读取失败"); });
    return () => { controller.abort(); cancelAll(); };
  }, [productId, account?.id]);

  useEffect(() => {
    if (!instagramJobNeedsPolling(job)) return;
    const controller = new AbortController();
    const active = identity(controller, job!.id, task?.id ?? null);
    poll.current?.controller.abort();
    poll.current = active;
    const timer = window.setTimeout(async () => {
      try {
        const next = await getInstagramPublishJob(job!.id, controller.signal);
        if (
          !isCurrentInstagramPublishOperation(active, poll.current)
          || !isSameExactInstagramPollJob(job!, next)
        ) return;
        setJob(next);
        if (shouldAdvanceInstagramPollCycle(next, true)) {
          setPollCycle((value) => value + 1);
        }
      } catch (error) {
        if (isCurrentInstagramPublishOperation(active, poll.current)) {
          setMessage(getApiErrorMessage(error, "本地 Job 读取暂时失败，将继续轮询"));
          setPollCycle((value) => value + 1);
        }
      } finally {
        if (canReleaseInstagramPublishLock(active, poll.current)) poll.current = null;
      }
    }, 1200);
    return () => { window.clearTimeout(timer); controller.abort(); if (poll.current === active) poll.current = null; };
  }, [job?.id, job?.status, productId, account?.id, artifactId, pollCycle]);

  useEffect(() => {
    if (exactInstagramPublishTaskId(job) && !read.current) void readExact();
  }, [job?.id, job?.status, job?.result_entity_id]);

  function metadata(): InstagramPublishingMetadata | null {
    if (!account || !artifactId || !title.trim()) return null;
    return { social_account_id: account.id, artifact_id: Number(artifactId), title,
      description, tags: tags.split(",").map((value) => value.trim()).filter(Boolean),
      privacy_status: "public", made_for_kids: false, synthetic_media: true,
      notify_subscribers: false, share_to_feed: shareToFeed };
  }

  function invalidate() { cancelAll(); setPreflight(null); setConfirmed(false); setJob(null); setTask(null); setMessage(""); }

  async function runPreflight() {
    const data = metadata(); if (!data || submit.current) return;
    const active = identity(new AbortController()); submit.current = active; setMessage("");
    try {
      const checked = await preflightInstagramPublish(productId, data, active.controller.signal);
      if (!isCurrentInstagramPublishOperation(active, submit.current)) return;
      setPreflight(checked);
      const jobs = await listInstagramPublishJobs(INSTAGRAM_PUBLISH_SUBMIT_V1, "product", productId, active.controller.signal);
      if (!isCurrentInstagramPublishOperation(active, submit.current)) return;
      const exact = jobs.find((item) => isExactInstagramJob(item, INSTAGRAM_PUBLISH_SUBMIT_V1, "product", productId)
        && item.input_payload.preflight_input_digest === checked.input_digest);
      if (exact) setJob(exact);
    } catch (error) { if (isCurrentInstagramPublishOperation(active, submit.current)) setMessage(getApiErrorMessage(error, "Instagram Preflight 失败")); }
    finally { if (canReleaseInstagramPublishLock(active, submit.current)) submit.current = null; }
  }

  async function enqueueSubmit() {
    const data = metadata(); if (!data || !preflight?.ready || !confirmed || submit.current) return;
    const active = identity(new AbortController()); submit.current = active; setMessage("");
    try {
      const created = await publishInstagram(productId, { ...data, input_digest: preflight.input_digest,
        preflight_digest: preflight.preflight_digest, preflight_expires_at: preflight.expires_at,
        idempotency_key: requestId("instagram-submit"), confirm_upload: true }, active.controller.signal);
      if (isCurrentInstagramPublishOperation(active, submit.current)
        && isExactInstagramJob(created.job, INSTAGRAM_PUBLISH_SUBMIT_V1, "product", productId)) setJob(created.job);
    } catch (error) { if (isCurrentInstagramPublishOperation(active, submit.current)) setMessage(getApiErrorMessage(error, "Submit Job 入队失败")); }
    finally { if (canReleaseInstagramPublishLock(active, submit.current)) submit.current = null; }
  }

  async function readExact() {
    const taskId = exactInstagramPublishTaskId(job); if (!taskId || !account || read.current) return;
    const active = identity(new AbortController(), job!.id, taskId); read.current = active; setReading(true);
    try {
      const exact = await getPublishTask(productId, taskId, active.controller.signal);
      if (!isCurrentInstagramPublishOperation(active, read.current) || exact.id !== taskId || exact.platform !== "instagram"
        || exact.social_account_id !== account.id || exact.artifact_id !== Number(artifactId)) return;
      setTask(exact); onTask(exact); setMessage("");
    } catch (error) { if (isCurrentInstagramPublishOperation(active, read.current)) setMessage(getApiErrorMessage(error, "精确 PublishTask 读取失败")); }
    finally { if (canReleaseInstagramPublishLock(active, read.current)) { read.current = null; setReading(false); } }
  }

  async function enqueueRefresh() {
    if (!task || !canEnqueueInstagramRefresh(task.status, job) || refresh.current) return;
    const active = identity(new AbortController(), null, task.id); refresh.current = active;
    try { const created = await refreshInstagramPublish(productId, task.id, requestId("instagram-refresh"), active.controller.signal);
      if (isCurrentInstagramPublishOperation(active, refresh.current) && isExactInstagramJob(created.job, INSTAGRAM_PUBLISH_REFRESH_V1, "publish_task", task.id)) setJob(created.job); }
    catch (error) { if (isCurrentInstagramPublishOperation(active, refresh.current)) setMessage(getApiErrorMessage(error, "Refresh Job 入队失败")); }
    finally { if (canReleaseInstagramPublishLock(active, refresh.current)) refresh.current = null; }
  }

  async function enqueueFinalize() {
    if (!task || !canEnqueueInstagramFinalize(task.status, job) || finalize.current || !window.confirm("确认公开发布此 Instagram Reel？")) return;
    const active = identity(new AbortController(), null, task.id); finalize.current = active;
    try { const checked = await preflightInstagramFinalize(productId, task.id, active.controller.signal);
      if (!isCurrentInstagramPublishOperation(active, finalize.current)) return;
      const created = await finalizeInstagramPublish(task.id, { product_id: productId,
        finalize_request_id: requestId("instagram-finalize"), input_digest: checked.input_digest,
        preflight_digest: checked.preflight_digest, preflight_expires_at: checked.expires_at,
        confirm_public_publish: true }, active.controller.signal);
      if (isCurrentInstagramPublishOperation(active, finalize.current) && isExactInstagramJob(created.job, INSTAGRAM_PUBLISH_FINALIZE_V1, "publish_task", task.id)) setJob(created.job); }
    catch (error) { if (isCurrentInstagramPublishOperation(active, finalize.current)) setMessage(getApiErrorMessage(error, "Finalize Job 入队失败")); }
    finally { if (canReleaseInstagramPublishLock(active, finalize.current)) finalize.current = null; }
  }

  if (!account) return <p className="social-publishing__empty">请先连接当前 Product 的 Instagram Professional Account。</p>;
  return <div className="youtube-publisher" data-testid="instagram-publish-queue">
    <header><div><span>INSTAGRAM REEL</span><h5>Reel 发布队列</h5></div><strong>公开发布必须单独确认</strong></header>
    <p>Artifact 是单场景渲染 Artifact，不是完整 15 秒成片。Meta Content Publishing 不沿用 YouTube 的 made-for-kids 或 private 概念；AI 合成披露为本地审计策略。</p>
    <select value={artifactId} onChange={(e) => { setArtifactId(e.target.value); invalidate(); }}><option value="">选择精确 Artifact</option>{artifacts.map((a) => <option key={a.artifact_id} value={a.artifact_id}>Artifact #{a.artifact_id} / RenderTask #{a.render_task_id}</option>)}</select>
    <input aria-label="本地任务标签" value={title} onChange={(e) => { setTitle(e.target.value); invalidate(); }} />
    <textarea aria-label="Instagram caption 描述" value={description} onChange={(e) => { setDescription(e.target.value); invalidate(); }} />
    <input aria-label="hashtags" value={tags} onChange={(e) => { setTags(e.target.value); invalidate(); }} />
    <label><input type="checkbox" checked={shareToFeed} onChange={(e) => { setShareToFeed(e.target.checked); invalidate(); }} />同时分享到 Feed</label>
    <button onClick={() => void runPreflight()}>Provider-free Preflight</button>
    {preflight?.ready && !job ? <><label><input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />确认准备并上传 Reel（不会公开发布）</label><button disabled={!confirmed || submit.current !== null} onClick={() => void enqueueSubmit()}>准备并上传 Reel</button></> : null}
    {job ? <p>Local Job #{job.id} · {job.status}</p> : null}
    {job?.status === "SUBMIT_UNKNOWN" ? <p role="alert">外部提交结果不确定，禁止重试。</p> : null}
    {exactInstagramPublishTaskId(job) ? <button disabled={reading} onClick={() => void readExact()}>{reading ? "正在读取精确 PublishTask 结果…" : "重新读取精确 PublishTask 结果"}</button> : null}
    {task ? <div><strong>PublishTask #{task.id} · {task.status}</strong><button disabled={!canEnqueueInstagramRefresh(task.status, job) || refresh.current !== null} onClick={() => void enqueueRefresh()}>刷新处理状态</button><button disabled={!canEnqueueInstagramFinalize(task.status, job) || finalize.current !== null} onClick={() => void enqueueFinalize()}>确认公开发布</button></div> : null}
    {message ? <p role="alert">{message}</p> : null}
  </div>;
}

function requestId(prefix: string): string {
  return `${prefix}-${typeof crypto.randomUUID === "function" ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`}`;
}
