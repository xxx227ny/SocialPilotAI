import { useCallback, useEffect, useRef, useState } from "react";

import {
  connectYouTube,
  disconnectSocialAccount,
  listPublishArtifacts,
  listPublishTasks,
  listSocialAccounts,
  preflightYouTubePublish,
  publishYouTube,
  refreshPublishTask,
} from "../../api/social";
import { getApiErrorMessage } from "../../api/client";
import {
  socialAccountBindingEnabled,
  youtubePublishingEnabled,
} from "../../config/features";
import { usePresentationMode } from "../../context/PresentationModeContext";
import type {
  PublishArtifactCandidate,
  PublishTask,
  SocialAccount,
  YouTubePreflight,
  YouTubePublishingMetadata,
} from "../../types/social";
import {
  canSubmitPrivateUpload,
  shouldLoadPublishTaskHistory,
  shouldLoadSocialData,
} from "./socialPublishingState";

type LoadState = "idle" | "loading" | "ready" | "failed";
type ActionState = "idle" | "working" | "failed";

export function SocialPublishingPanel({ productId }: { productId: number }) {
  const { isPresentation } = usePresentationMode();
  const [accounts, setAccounts] = useState<SocialAccount[]>([]);
  const [artifacts, setArtifacts] = useState<PublishArtifactCandidate[]>([]);
  const [tasks, setTasks] = useState<PublishTask[]>([]);
  const [loadState, setLoadState] = useState<LoadState>("idle");
  const [message, setMessage] = useState("");
  const requestId = useRef(0);
  const loadController = useRef<AbortController | null>(null);

  const load = useCallback(async () => {
    const loadSocialData = shouldLoadSocialData(
      isPresentation,
      socialAccountBindingEnabled,
      youtubePublishingEnabled,
    );
    const loadTaskHistory = shouldLoadPublishTaskHistory(isPresentation);
    if (!loadSocialData && !loadTaskHistory) {
      return;
    }
    const current = ++requestId.current;
    const controller = new AbortController();
    loadController.current?.abort();
    loadController.current = controller;
    setLoadState("loading");
    setMessage("");
    try {
      const [nextAccounts, nextArtifacts, nextTasks] = await Promise.all([
        loadSocialData && socialAccountBindingEnabled
          ? listSocialAccounts(productId, controller.signal)
          : Promise.resolve([]),
        youtubePublishingEnabled
          ? listPublishArtifacts(productId, controller.signal)
          : Promise.resolve([]),
        loadTaskHistory
          ? listPublishTasks(productId, controller.signal)
          : Promise.resolve([]),
      ]);
      if (current !== requestId.current) return;
      setAccounts(nextAccounts);
      setArtifacts(nextArtifacts);
      setTasks(nextTasks);
      setLoadState("ready");
    } catch (error) {
      if (current !== requestId.current || controller.signal.aborted) return;
      setMessage(
        getApiErrorMessage(error, "社交发布状态读取失败，请检查 Backend。"),
      );
      setLoadState("failed");
    }
  }, [isPresentation, productId]);

  useEffect(() => {
    void load();
    return () => {
      requestId.current += 1;
      loadController.current?.abort();
    };
  }, [load]);

  if (isPresentation) return null;

  const oauthStatus = new URLSearchParams(window.location.search).get(
    "youtube_oauth",
  );

  return (
    <section className="social-publishing" data-testid="social-publishing">
      <header className="social-publishing__header">
        <div>
          <span>SOCIAL PUBLISHING</span>
          <h4>社交发布</h4>
          <p>选择精确的已保存视频，并通过一次性确认发布为 YouTube Private。</p>
        </div>
        <button
          type="button"
          onClick={() => void load()}
          disabled={loadState === "loading"}
        >
          {!youtubePublishingEnabled ? "重新读取本地记录" : (
            <>
          {loadState === "loading" ? "读取中…" : "重新读取"}
            </>
          )}
        </button>
      </header>

      {oauthStatus === "connected" ? (
        <p className="social-publishing__notice is-success">
          YouTube 授权回调已完成，正在显示安全 Channel 身份。
        </p>
      ) : null}
      {oauthStatus === "denied" ? (
        <p className="social-publishing__notice is-error">
          你已取消 YouTube 授权，没有保存任何 Token。
        </p>
      ) : null}
      {message ? (
        <p className="social-publishing__notice is-error" role="alert">
          {message}
        </p>
      ) : null}

      <AccountCards
        productId={productId}
        accounts={accounts}
        readOnly={!youtubePublishingEnabled}
        onChanged={(account) => {
          setAccounts((current) => [
            account,
            ...current.filter((item) => item.id !== account.id),
          ]);
        }}
      />

      {youtubePublishingEnabled ? (
        <YouTubePublisher
          key={productId}
          productId={productId}
          accounts={accounts.filter(
            (account) => account.connection_status === "CONNECTED",
          )}
          artifacts={artifacts}
          recoveredTasks={tasks}
          onTask={(task) => {
            setTasks((current) => [
              task,
              ...current.filter((item) => item.id !== task.id),
            ]);
          }}
        />
      ) : (
        <>
        <p className="social-publishing__disabled">
          YouTube 发布功能当前由 Frontend Feature Gate 关闭。
        </p>
        <ReadOnlyPublishTaskHistory tasks={tasks} />
        </>
      )}

      <div className="social-publishing__future">
        <PlatformPlaceholder name="Instagram" />
        <PlatformPlaceholder name="TikTok" />
      </div>
    </section>
  );
}

function AccountCards({
  productId,
  accounts,
  readOnly,
  onChanged,
}: {
  productId: number;
  accounts: SocialAccount[];
  readOnly: boolean;
  onChanged: (account: SocialAccount) => void;
}) {
  const [state, setState] = useState<ActionState>("idle");
  const [error, setError] = useState("");
  const lock = useRef(false);
  const youtube = accounts.find((account) => account.platform === "youtube");

  async function connect() {
    if (lock.current || !socialAccountBindingEnabled) return;
    lock.current = true;
    setState("working");
    setError("");
    const controller = new AbortController();
    try {
      const result = await connectYouTube(productId, controller.signal);
      window.location.assign(result.authorization_url);
    } catch (caught) {
      setError(getApiErrorMessage(caught, "无法开始 YouTube 授权。"));
      setState("failed");
      lock.current = false;
    }
  }

  async function disconnect(revoke: boolean) {
    if (!youtube || lock.current) return;
    const action = revoke ? "撤销 Google 授权并解除绑定" : "仅在本机解除绑定";
    if (!window.confirm(`确认${action}？此操作不会删除 YouTube 视频。`)) return;
    lock.current = true;
    setState("working");
    setError("");
    try {
      onChanged(await disconnectSocialAccount(productId, youtube.id, revoke));
      setState("idle");
    } catch (caught) {
      setError(getApiErrorMessage(caught, "YouTube 账号断开失败。"));
      setState("failed");
    } finally {
      lock.current = false;
    }
  }

  return (
    <div className="social-account-card">
      <div>
        <span>YouTube</span>
        <strong>{youtube?.display_name ?? "未连接"}</strong>
        <small>
          {youtube
            ? connectionLabel(youtube.connection_status)
            : socialAccountBindingEnabled
              ? "可以连接当前 Product 的 Channel"
              : "账号绑定 Gate 未开启"}
        </small>
      </div>
      {!readOnly ? <div className="social-account-card__actions">
        {!youtube || youtube.connection_status !== "CONNECTED" ? (
          <button
            type="button"
            onClick={() => void connect()}
            disabled={!socialAccountBindingEnabled || state === "working"}
          >
            {state === "working" ? "连接中…" : "连接 YouTube"}
          </button>
        ) : (
          <>
            <button
              type="button"
              onClick={() => void disconnect(false)}
              disabled={state === "working"}
            >
              仅本地断开
            </button>
            <button
              type="button"
              onClick={() => void disconnect(true)}
              disabled={state === "working"}
            >
              撤销授权并断开
            </button>
          </>
        )}
      </div> : null}
      {error ? <p role="alert">{error}</p> : null}
    </div>
  );
}

function ReadOnlyPublishTaskHistory({ tasks }: { tasks: PublishTask[] }) {
  return (
    <div data-testid="read-only-publish-task-history">
      {tasks.length === 0 ? (
        <p className="social-publishing__empty">暂无本地发布记录。</p>
      ) : (
        tasks.map((task) => (
          <div className="youtube-publish-task" key={task.id}>
            <strong>
              PublishTask #{task.id} · {task.status}
            </strong>
            <span>Video ID: {task.provider_video_id ?? "尚无确定身份"}</span>
            <span>Privacy: {task.privacy_status}</span>
            <span>
              Completed: {task.completed_at ? formatTaskTime(task.completed_at) : "—"}
            </span>
          </div>
        ))
      )}
    </div>
  );
}

function YouTubePublisher({
  productId,
  accounts,
  artifacts,
  recoveredTasks,
  onTask,
}: {
  productId: number;
  accounts: SocialAccount[];
  artifacts: PublishArtifactCandidate[];
  recoveredTasks: PublishTask[];
  onTask: (task: PublishTask) => void;
}) {
  const [accountId, setAccountId] = useState("");
  const [artifactId, setArtifactId] = useState("");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [tags, setTags] = useState("");
  const [madeForKids, setMadeForKids] = useState<"" | "yes" | "no">("");
  const [preflight, setPreflight] = useState<YouTubePreflight | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [task, setTask] = useState<PublishTask | null>(
    recoveredTasks[0] ?? null,
  );
  const [state, setState] = useState<ActionState>("idle");
  const [message, setMessage] = useState("");
  const preflightLock = useRef(false);
  const uploadLock = useRef(false);
  const refreshLock = useRef(false);
  const requestId = useRef(0);
  const controller = useRef<AbortController | null>(null);

  useEffect(() => {
    setTask((current) => current ?? recoveredTasks[0] ?? null);
  }, [recoveredTasks]);

  function invalidate() {
    requestId.current += 1;
    controller.current?.abort();
    setPreflight(null);
    setConfirmed(false);
    setMessage("");
    setState("idle");
    preflightLock.current = false;
  }

  function payload(): YouTubePublishingMetadata | null {
    if (!accountId || !artifactId || madeForKids === "") return null;
    return {
      social_account_id: Number(accountId),
      artifact_id: Number(artifactId),
      title,
      description,
      tags: tags
        .split(",")
        .map((value) => value.trim())
        .filter(Boolean),
      privacy_status: "private",
      made_for_kids: madeForKids === "yes",
      synthetic_media: true,
      notify_subscribers: false,
    };
  }

  async function runPreflight() {
    const data = payload();
    if (!data) {
      setMessage("请选择账号、精确 Artifact，并明确 made-for-kids。 ");
      setState("failed");
      return;
    }
    if (preflightLock.current || uploadLock.current) return;
    preflightLock.current = true;
    setState("working");
    setMessage("");
    setConfirmed(false);
    const current = ++requestId.current;
    const nextController = new AbortController();
    controller.current?.abort();
    controller.current = nextController;
    try {
      const result = await preflightYouTubePublish(
        productId,
        data,
        nextController.signal,
      );
      if (current !== requestId.current) return;
      setPreflight(result);
      setState(result.ready ? "idle" : "failed");
      if (!result.ready) setMessage(result.missing_requirements.join("；"));
    } catch (caught) {
      if (current !== requestId.current || nextController.signal.aborted) return;
      setState("failed");
      setMessage(getApiErrorMessage(caught, "YouTube Preflight 失败。"));
    } finally {
      if (current === requestId.current) preflightLock.current = false;
    }
  }

  async function upload() {
    const data = payload();
    const expected = preflight;
    if (
      !data ||
      !expected ||
      !canSubmitPrivateUpload({
        preflightReady: expected?.ready ?? false,
        confirmed,
        uploadLocked: uploadLock.current,
        madeForKidsSelected: madeForKids !== "",
        identityComplete: Boolean(accountId && artifactId),
      })
    ) return;
    uploadLock.current = true;
    setConfirmed(false);
    setPreflight(null);
    setState("working");
    setMessage("");
    const current = ++requestId.current;
    const nextController = new AbortController();
    controller.current?.abort();
    controller.current = nextController;
    try {
      const result = await publishYouTube(
        productId,
        {
          ...data,
          preflight_digest: expected.preflight_digest,
          preflight_expires_at: expected.expires_at,
          idempotency_key: createIdempotencyKey(),
          confirm_upload: true,
        },
        nextController.signal,
      );
      if (current !== requestId.current) return;
      setTask(result.task);
      onTask(result.task);
      setState(result.task.uncertain ? "failed" : "idle");
      if (result.task.uncertain) {
        setMessage("上传结果不确定；不会自动重传。请恢复任务后再处理。");
      }
    } catch (caught) {
      if (current !== requestId.current || nextController.signal.aborted) return;
      setState("failed");
      setMessage(
        getApiErrorMessage(
          caught,
          "浏览器未获得确定结果；不会自动重试，请重新读取任务。",
        ),
      );
    } finally {
      if (current === requestId.current) uploadLock.current = false;
    }
  }

  async function refresh() {
    if (!task || refreshLock.current) return;
    refreshLock.current = true;
    setMessage("");
    try {
      const result = await refreshPublishTask(productId, task.id);
      setTask(result.task);
      onTask(result.task);
    } catch (caught) {
      setMessage(getApiErrorMessage(caught, "状态刷新失败，不会重新上传。"));
    } finally {
      refreshLock.current = false;
    }
  }

  const selectedArtifact = artifacts.find(
    (artifact) => artifact.artifact_id === Number(artifactId),
  );

  return (
    <div className="youtube-publisher">
      <header>
        <div>
          <span>YOUTUBE PRIVATE</span>
          <h5>发布草稿</h5>
        </div>
        <strong>Private · AI 披露开启 · 不通知订阅者</strong>
      </header>

      {accounts.length === 0 || artifacts.length === 0 ? (
        <p className="social-publishing__empty">
          {accounts.length === 0
            ? "请先连接当前 Product 的 YouTube Channel。"
            : "当前 Product 没有通过完整关系和文件校验的可发布 Artifact。"}
        </p>
      ) : (
        <div className="youtube-publisher__form">
          <label>
            YouTube Channel
            <select
              value={accountId}
              onChange={(event) => {
                setAccountId(event.target.value);
                invalidate();
              }}
            >
              <option value="">请选择账号</option>
              {accounts.map((account) => (
                <option key={account.id} value={account.id}>
                  {account.display_name}
                </option>
              ))}
            </select>
          </label>
          <label>
            精确 Artifact
            <select
              value={artifactId}
              onChange={(event) => {
                setArtifactId(event.target.value);
                invalidate();
              }}
            >
              <option value="">请选择 Artifact</option>
              {artifacts.map((artifact) => (
                <option key={artifact.artifact_id} value={artifact.artifact_id}>
                  Artifact #{artifact.artifact_id} · RenderTask #{artifact.render_task_id}
                  {" · "}VideoProject #{artifact.video_project_id}
                </option>
              ))}
            </select>
          </label>
          {selectedArtifact ? (
            <p className="youtube-publisher__identity">
              CopyMatrix #{selectedArtifact.copy_matrix_id} · VideoProject #
              {selectedArtifact.video_project_id} · RenderTask #
              {selectedArtifact.render_task_id} · Artifact #
              {selectedArtifact.artifact_id}
            </p>
          ) : null}
          <label>
            标题
            <input
              value={title}
              maxLength={100}
              onChange={(event) => {
                setTitle(event.target.value);
                invalidate();
              }}
            />
          </label>
          <label>
            描述
            <textarea
              value={description}
              maxLength={5000}
              onChange={(event) => {
                setDescription(event.target.value);
                invalidate();
              }}
            />
          </label>
          <label>
            标签（英文逗号分隔）
            <input
              value={tags}
              onChange={(event) => {
                setTags(event.target.value);
                invalidate();
              }}
            />
          </label>
          <fieldset>
            <legend>是否为儿童内容（必须明确选择）</legend>
            <label>
              <input
                type="radio"
                name={`made-for-kids-${productId}`}
                checked={madeForKids === "yes"}
                onChange={() => {
                  setMadeForKids("yes");
                  invalidate();
                }}
              />
              是
            </label>
            <label>
              <input
                type="radio"
                name={`made-for-kids-${productId}`}
                checked={madeForKids === "no"}
                onChange={() => {
                  setMadeForKids("no");
                  invalidate();
                }}
              />
              否
            </label>
          </fieldset>
          <button
            type="button"
            onClick={() => void runPreflight()}
            disabled={state === "working"}
          >
            {state === "working" ? "校验中…" : "运行 Provider-free Preflight"}
          </button>
        </div>
      )}

      {preflight ? (
        <div className={`youtube-preflight is-${preflight.status.toLowerCase()}`}>
          <strong>{preflight.status}</strong>
          <span>Provider 调用 0 · 数据库写入 0</span>
          {preflight.ready ? (
            <label>
              <input
                type="checkbox"
                checked={confirmed}
                onChange={(event) => setConfirmed(event.target.checked)}
              />
              我确认本次会向所选 Channel 上传一个 Private 视频；AI 内容披露开启，
              不通知订阅者。
            </label>
          ) : null}
          <button
            type="button"
            onClick={() => void upload()}
            disabled={
              !canSubmitPrivateUpload({
                preflightReady: preflight.ready,
                confirmed,
                uploadLocked: uploadLock.current,
                madeForKidsSelected: madeForKids !== "",
                identityComplete: Boolean(accountId && artifactId),
              })
            }
          >
            上传一次 Private 视频
          </button>
        </div>
      ) : null}

      {message ? <p className="social-publishing__notice is-error">{message}</p> : null}
      {task ? (
        <div className="youtube-publish-task">
          <strong>
            PublishTask #{task.id} · {task.status}
          </strong>
          <span>
            Provider Video ID：{task.provider_video_id ?? "尚无确定身份"}
          </span>
          <span>{task.uncertain ? "结果不确定，禁止自动重传" : "无自动重试"}</span>
          <button
            type="button"
            onClick={() => void refresh()}
            disabled={
              refreshLock.current ||
              !task.provider_video_id ||
              !["SUBMITTED", "PROCESSING"].includes(task.status)
            }
          >
            显式刷新同一任务
          </button>
        </div>
      ) : null}
    </div>
  );
}

function PlatformPlaceholder({ name }: { name: string }) {
  return (
    <div>
      <strong>{name}</strong>
      <span>即将支持</span>
      <button type="button" disabled>
        即将支持
      </button>
    </div>
  );
}

function connectionLabel(status: SocialAccount["connection_status"]) {
  return {
    CONNECTED: "已连接",
    DISCONNECTED: "已断开",
    EXPIRED: "授权过期",
    FAILED: "连接失败",
  }[status];
}

function createIdempotencyKey() {
  return typeof crypto.randomUUID === "function"
    ? `youtube-${crypto.randomUUID()}`
    : `youtube-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function formatTaskTime(value: string) {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}
