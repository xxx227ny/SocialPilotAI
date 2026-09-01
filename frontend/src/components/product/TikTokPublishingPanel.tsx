import { useEffect, useRef, useState } from "react";

import { getApiErrorMessage } from "../../api/client";
import {
  getPublishTask,
  getTikTokCreatorInfoSnapshot,
  getYouTubePublishJob,
  listTikTokPublishArtifacts,
  preflightTikTokPublish,
  publishTikTok,
  queryTikTokCreatorInfo,
  refreshTikTokPublish,
} from "../../api/social";
import type { ExecutionJob } from "../../types/execution";
import type {
  PublishArtifactCandidate,
  PublishTask,
  SocialAccount,
  TikTokCreatorInfoSnapshot,
  TikTokPublishPreflight,
  TikTokPublishingMetadata,
} from "../../types/social";
import {
  disclosureValid,
  exactTikTokResultId,
  interactionSettings,
  isCurrentTikTokOperation,
  isExactTikTokJob,
  isFreshTikTokSnapshot,
  runTikTokSerialPoll,
  TIKTOK_CREATOR_INFO_V1,
  TIKTOK_PUBLISH_REFRESH_V1,
  TIKTOK_PUBLISH_SUBMIT_V1,
} from "./tiktokPublishingState";
import type { TikTokJobIdentity } from "./tiktokPublishingState";
import type { TikTokOperationIdentity } from "./tiktokPublishingState";

type OperationKind =
  | "artifacts" | "creator" | "poll" | "snapshot" | "preflight"
  | "submit" | "task" | "refresh";

interface OperationIdentity extends TikTokOperationIdentity {
  controller: AbortController;
  timer: number | null;
}

export function TikTokPublishingPanel({ productId, accounts, onTask }: {
  productId: number; accounts: SocialAccount[]; onTask: (task: PublishTask) => void;
}) {
  const account = accounts.find((item) =>
    item.platform === "tiktok" && item.connection_status === "CONNECTED");
  const [snapshot, setSnapshot] = useState<TikTokCreatorInfoSnapshot | null>(null);
  const [artifacts, setArtifacts] = useState<PublishArtifactCandidate[]>([]);
  const [artifactId, setArtifactId] = useState(0);
  const [title, setTitle] = useState("");
  const [privacy, setPrivacy] = useState("");
  const [description, setDescription] = useState("");
  const [tags, setTags] = useState("");
  const [allowComments, setAllowComments] = useState(false);
  const [allowDuet, setAllowDuet] = useState(false);
  const [allowStitch, setAllowStitch] = useState(false);
  const [organicDisclosure, setOrganicDisclosure] = useState(false);
  const [brandedDisclosure, setBrandedDisclosure] = useState(false);
  const [preflight, setPreflight] = useState<TikTokPublishPreflight | null>(null);
  const [job, setJob] = useState<ExecutionJob | null>(null);
  const [task, setTask] = useState<PublishTask | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [message, setMessage] = useState("");
  const [snapshotRetryId, setSnapshotRetryId] = useState<number | null>(null);
  const [taskRetryId, setTaskRetryId] = useState<number | null>(null);
  const operations = useRef<Partial<Record<OperationKind, OperationIdentity>>>({});
  const sequence = useRef(0);
  const mounted = useRef(true);
  const liveIdentity = useRef({
    productId,
    accountId: account?.id ?? null,
    snapshotId: snapshot?.id ?? null,
    artifactId: artifactId || null,
    jobId: job?.id ?? null,
    taskId: task?.id ?? null,
  });
  liveIdentity.current.productId = productId;
  liveIdentity.current.accountId = account?.id ?? null;
  liveIdentity.current.snapshotId = snapshot?.id ?? null;
  liveIdentity.current.artifactId = artifactId || null;
  liveIdentity.current.jobId = job?.id ?? null;
  liveIdentity.current.taskId = task?.id ?? null;

  function identity(kind: OperationKind, values: Partial<OperationIdentity> = {}) {
    if (!mounted.current) return null;
    operations.current[kind]?.controller.abort();
    const next: OperationIdentity = {
      productId, accountId: account?.id ?? null, snapshotId: snapshot?.id ?? null,
      artifactId: artifactId || null, jobId: job?.id ?? null, taskId: task?.id ?? null,
      operationId: ++sequence.current, controller: new AbortController(), timer: null,
      ...values,
    };
    operations.current[kind] = next;
    return next;
  }

  function current(kind: OperationKind, value: OperationIdentity): boolean {
    const observed: TikTokOperationIdentity = {
      ...liveIdentity.current,
      operationId: value.operationId,
    };
    return mounted.current && !value.controller.signal.aborted
      && operations.current[kind] === value
      && isCurrentTikTokOperation(value, observed);
  }

  function release(kind: OperationKind, value: OperationIdentity) {
    if (value.timer !== null) window.clearTimeout(value.timer);
    if (operations.current[kind] === value) delete operations.current[kind];
  }

  function waitForPoll(operation: OperationIdentity): Promise<boolean> {
    return new Promise((resolve) => {
      const abort = () => {
        if (operation.timer !== null) window.clearTimeout(operation.timer);
        operation.timer = null;
        resolve(false);
      };
      operation.controller.signal.addEventListener("abort", abort, { once: true });
      operation.timer = window.setTimeout(() => {
        operation.timer = null;
        operation.controller.signal.removeEventListener("abort", abort);
        resolve(current("poll", operation));
      }, 800);
    });
  }

  function invalidatePreflight() { setPreflight(null); setConfirmed(false); }

  useEffect(() => {
    mounted.current = true;
    Object.values(operations.current).forEach((item) => {
      if (item?.timer !== null) window.clearTimeout(item.timer);
      item?.controller.abort();
    });
    operations.current = {};
    liveIdentity.current = { productId, accountId: account?.id ?? null,
      snapshotId: null, artifactId: null, jobId: null, taskId: null };
    setSnapshot(null); setArtifacts([]); setArtifactId(0); setPreflight(null);
    setConfirmed(false); setJob(null); setTask(null); setSnapshotRetryId(null);
    setTaskRetryId(null); setMessage("");
    const operation = identity("artifacts", { accountId: account?.id ?? null });
    if (!operation) return;
    void listTikTokPublishArtifacts(productId, operation.controller.signal)
      .then((items) => {
        if (!current("artifacts", operation)) return;
        const selected = items[items.length - 1]?.artifact_id ?? 0;
        liveIdentity.current.artifactId = selected || null;
        setArtifacts(items); setArtifactId(selected);
      })
      .catch((error) => {
        if (current("artifacts", operation) && !operation.controller.signal.aborted)
          setMessage(getApiErrorMessage(error, "Unable to load safe TikTok Artifact candidates."));
      })
      .finally(() => release("artifacts", operation));
    return () => {
      mounted.current = false;
      Object.values(operations.current).forEach((item) => {
        if (item?.timer !== null) window.clearTimeout(item.timer);
        item?.controller.abort();
      });
      operations.current = {};
    };
  }, [productId, account?.id]);

  async function poll(initial: ExecutionJob, expected: TikTokJobIdentity) {
    liveIdentity.current.jobId = expected.jobId;
    const operation = identity("poll", { jobId: expected.jobId });
    if (!operation) return;
    try {
      const terminal = await runTikTokSerialPoll(initial, {
        signal: operation.controller.signal,
        identity: expected,
        wait: () => waitForPoll(operation),
        read: (signal) => getYouTubePublishJob(expected.jobId, signal),
        contextCurrent: () => current("poll", operation),
        accept: (next) => setJob(next),
        transientError: (error) => setMessage(getApiErrorMessage(
          error, "Temporary local Job read failed; continuing exact Job.")),
      });
      if (terminal && current("poll", operation)) await readExactResult(terminal);
    } finally {
      release("poll", operation);
    }
  }

  async function readSnapshot(snapshotId: number) {
    if (!account || operations.current.snapshot) return;
    liveIdentity.current.snapshotId = snapshotId;
    const operation = identity("snapshot", { snapshotId, accountId: account.id });
    if (!operation) return;
    try {
      const value = await getTikTokCreatorInfoSnapshot(
        snapshotId, productId, account.id, operation.controller.signal);
      if (!current("snapshot", operation) || value.id !== snapshotId
        || value.product_id !== productId || value.social_account_id !== account.id) return;
      setSnapshot(value); setPrivacy(value.privacy_level_options[0] ?? "");
      setAllowComments(!value.comment_disabled); setAllowDuet(!value.duet_disabled);
      setAllowStitch(!value.stitch_disabled); setSnapshotRetryId(null);
    } catch (error) {
      if (current("snapshot", operation) && !operation.controller.signal.aborted) {
        setSnapshotRetryId(snapshotId);
        setMessage(getApiErrorMessage(error, "Exact Creator Info result read failed."));
      }
    } finally { release("snapshot", operation); }
  }

  async function readTask(taskId: number) {
    if (!account || operations.current.task) return;
    liveIdentity.current.taskId = taskId;
    const operation = identity("task", { taskId, accountId: account.id });
    if (!operation) return;
    try {
      const value = await getPublishTask(productId, taskId, operation.controller.signal);
      if (!current("task", operation) || value.id !== taskId || value.product_id !== productId
        || value.social_account_id !== account.id || value.artifact_id !== artifactId
        || value.platform !== "tiktok") return;
      setTask(value); onTask(value); setTaskRetryId(null);
    } catch (error) {
      if (current("task", operation) && !operation.controller.signal.aborted) {
        setTaskRetryId(taskId);
        setMessage(getApiErrorMessage(error, "Exact PublishTask result read failed."));
      }
    } finally { release("task", operation); }
  }

  async function readExactResult(terminal: ExecutionJob) {
    if (terminal.status !== "SUCCEEDED") return;
    const snapshotId = exactTikTokResultId(terminal, "tiktok_creator_info_snapshot");
    const taskId = exactTikTokResultId(terminal, "publish_task");
    if (snapshotId) await readSnapshot(snapshotId);
    else if (taskId) await readTask(taskId);
    else setMessage("TikTok Job returned an invalid exact result identity.");
  }

  const metadata = (): TikTokPublishingMetadata => ({
    social_account_id: account?.id ?? 0, creator_info_snapshot_id: snapshot?.id ?? 0,
    artifact_id: artifactId, title, description,
    tags: tags.split(",").map((value) => value.trim()).filter(Boolean), privacy_status: privacy,
    ...interactionSettings(snapshot ?? {
      comment_disabled: true, duet_disabled: true, stitch_disabled: true,
    }, { comments: allowComments, duet: allowDuet, stitch: allowStitch }),
    brand_content_toggle: brandedDisclosure, brand_organic_toggle: organicDisclosure,
  });

  async function creatorInfo() {
    if (!account || operations.current.creator) return;
    const operation = identity("creator", { accountId: account.id }); setMessage("");
    if (!operation) return;
    try {
      const result = await queryTikTokCreatorInfo(productId, account.id, operation.controller.signal);
      if (!current("creator", operation)) return;
      const expected = { jobId: result.job.id, jobType: TIKTOK_CREATOR_INFO_V1,
        sourceType: "social_account", sourceId: account.id };
      if (!isExactTikTokJob(result.job, expected)) throw new Error("Creator Job identity mismatch");
      liveIdentity.current.jobId = result.job.id;
      setJob(result.job); await poll(result.job, expected);
    } catch (error) {
      if (current("creator", operation) && !operation.controller.signal.aborted)
        setMessage(getApiErrorMessage(error, "Creator Info enqueue failed safely."));
    } finally { release("creator", operation); }
  }

  async function runPreflight() {
    if (operations.current.preflight) return;
    const operation = identity("preflight"); setMessage("");
    if (!operation) return;
    try {
      const result = await preflightTikTokPublish(productId, metadata(), operation.controller.signal);
      if (!current("preflight", operation)) return;
      setPreflight(result); setConfirmed(false);
    } catch (error) {
      if (current("preflight", operation) && !operation.controller.signal.aborted)
        setMessage(getApiErrorMessage(error, "TikTok Preflight failed safely."));
    } finally { release("preflight", operation); }
  }

  async function submit() {
    if (!preflight || operations.current.submit || job?.status === "SUBMIT_UNKNOWN") return;
    const operation = identity("submit"); setMessage("");
    if (!operation) return;
    try {
      const result = await publishTikTok(productId, { ...metadata(),
        input_digest: preflight.input_digest, preflight_digest: preflight.preflight_digest,
        preflight_expires_at: preflight.expires_at, confirm_upload: true },
      operation.controller.signal);
      if (!current("submit", operation)) return;
      const expected = { jobId: result.job.id, jobType: TIKTOK_PUBLISH_SUBMIT_V1,
        sourceType: "product", sourceId: productId };
      if (!isExactTikTokJob(result.job, expected)) throw new Error("Submit Job identity mismatch");
      liveIdentity.current.jobId = result.job.id;
      setJob(result.job); await poll(result.job, expected);
    } catch (error) {
      if (current("submit", operation) && !operation.controller.signal.aborted)
        setMessage(getApiErrorMessage(error, "TikTok Submit enqueue failed safely."));
    } finally { release("submit", operation); }
  }

  async function refresh() {
    if (!task || operations.current.refresh || task.status !== "PROCESSING") return;
    const operation = identity("refresh", { taskId: task.id }); setMessage("");
    if (!operation) return;
    try {
      const result = await refreshTikTokPublish(
        productId, task.id, crypto.randomUUID(), operation.controller.signal);
      if (!current("refresh", operation)) return;
      const expected = { jobId: result.job.id, jobType: TIKTOK_PUBLISH_REFRESH_V1,
        sourceType: "publish_task", sourceId: task.id };
      if (!isExactTikTokJob(result.job, expected)) throw new Error("Refresh Job identity mismatch");
      liveIdentity.current.jobId = result.job.id;
      setJob(result.job); await poll(result.job, expected);
    } catch (error) {
      if (current("refresh", operation) && !operation.controller.signal.aborted)
        setMessage(getApiErrorMessage(error, "TikTok status Refresh failed; original task retained."));
    } finally { release("refresh", operation); }
  }

  const fresh = snapshot && isFreshTikTokSnapshot(snapshot.expires_at);
  const disclosureReady = disclosureValid(organicDisclosure, brandedDisclosure);
  return <section className="tiktok-publishing-panel" data-testid="tiktok-publishing-panel">
    <h5>TikTok Direct Post</h5>
    <p>Creator Info is read explicitly. Content Posting API audit approval remains an external prerequisite.</p>
    <button type="button" disabled={!account || Boolean(operations.current.creator)} onClick={() => void creatorInfo()}>Read Creator Info</button>
    {snapshotRetryId ? <button type="button" disabled={Boolean(operations.current.snapshot)} onClick={() => void readSnapshot(snapshotRetryId)}>重新读取精确 Creator Info 结果</button> : null}
    {fresh ? <div>
      <p>Creator snapshot #{snapshot.id} · {snapshot.creator_nickname} · expires {snapshot.expires_at}</p>
      <label>Local task title<input value={title} maxLength={100} onChange={(e) => { setTitle(e.target.value); invalidatePreflight(); }} /></label>
      <label>Artifact<select value={artifactId} onChange={(e) => { const next = Number(e.target.value); liveIdentity.current.artifactId = next || null; operations.current.poll?.controller.abort(); setArtifactId(next); invalidatePreflight(); }}><option value={0}>Select exact Artifact</option>{artifacts.map((item) => <option key={item.artifact_id} value={item.artifact_id}>Artifact #{item.artifact_id}</option>)}</select></label>
      <label>Privacy<select value={privacy} onChange={(e) => { setPrivacy(e.target.value); invalidatePreflight(); }}>{snapshot.privacy_level_options.map((item) => <option key={item}>{item}</option>)}</select></label>
      <label><input type="checkbox" checked={allowComments} disabled={snapshot.comment_disabled} onChange={(e) => { setAllowComments(e.target.checked); invalidatePreflight(); }} />Allow comments</label>
      <label><input type="checkbox" checked={allowDuet} disabled={snapshot.duet_disabled} onChange={(e) => { setAllowDuet(e.target.checked); invalidatePreflight(); }} />Allow duet</label>
      <label><input type="checkbox" checked={allowStitch} disabled={snapshot.stitch_disabled} onChange={(e) => { setAllowStitch(e.target.checked); invalidatePreflight(); }} />Allow stitch</label>
      <label><input type="checkbox" checked={organicDisclosure} onChange={(e) => { setOrganicDisclosure(e.target.checked); invalidatePreflight(); }} />自有品牌推广（brand_organic_toggle）</label>
      <label><input type="checkbox" checked={brandedDisclosure} onChange={(e) => { setBrandedDisclosure(e.target.checked); if (e.target.checked) setOrganicDisclosure(true); invalidatePreflight(); }} />第三方品牌商业内容（brand_content_toggle）</label>
      <p>至少选择一项披露；第三方品牌商业内容同时要求自有/自然内容披露组合。</p>
      <label>Description<textarea value={description} onChange={(e) => { setDescription(e.target.value); invalidatePreflight(); }} /></label>
      <label>Tags<input value={tags} onChange={(e) => { setTags(e.target.value); invalidatePreflight(); }} /></label>
      <button type="button" disabled={!artifactId || !title.trim() || !disclosureReady} onClick={() => void runPreflight()}>Run Provider-free Preflight</button>
      {preflight?.ready ? <><p>READY · Digest {preflight.preflight_digest.slice(0, 12)}…</p><label><input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />I confirm this exact upload and disclosures.</label><button type="button" disabled={!confirmed || job?.status === "SUBMIT_UNKNOWN"} onClick={() => void submit()}>Submit Once</button></> : null}
    </div> : <p>No fresh Creator Info snapshot. Publishing controls remain disabled.</p>}
    {job ? <p>Local Job #{job.id} · {job.status}</p> : null}
    {task ? <p>PublishTask #{task.id} · {task.status} · {task.privacy_status}</p> : null}
    {task?.status === "PROCESSING" ? <button type="button" onClick={() => void refresh()}>刷新 TikTok 发布状态</button> : null}
    {taskRetryId ? <button type="button" disabled={Boolean(operations.current.task)} onClick={() => void readTask(taskRetryId)}>重新读取精确 PublishTask 结果</button> : null}
    {job?.status === "SUBMIT_UNKNOWN" ? <p role="alert">Submission is uncertain. Upload and automatic retry are disabled.</p> : null}
    {message ? <p role="alert">{message}</p> : null}
  </section>;
}
