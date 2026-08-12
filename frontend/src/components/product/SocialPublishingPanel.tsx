import { useCallback, useEffect, useRef, useState } from "react";

import {
  connectInstagram,
  connectTikTok,
  connectYouTube,
  disconnectInstagramAccount,
  disconnectTikTokAccount,
  disconnectSocialAccount,
  getPublishTask,
  getYouTubePublishJob,
  listPublishArtifacts,
  listPublishTasks,
  listSocialAccounts,
  listYouTubePublishJobs,
  preflightYouTubePublish,
  publishYouTube,
  refreshPublishTask,
} from "../../api/social";
import { getApiErrorMessage } from "../../api/client";
import {
  instagramAccountBindingEnabled,
  instagramPublishingEnabled,
  tiktokAccountBindingEnabled,
  socialAccountBindingEnabled,
  youtubePublishingEnabled,
} from "../../config/features";
import { usePresentationMode } from "../../context/PresentationModeContext";
import type { ExecutionJob } from "../../types/execution";
import type {
  PublishArtifactCandidate,
  PublishTask,
  SocialAccount,
  YouTubePreflight,
  YouTubePublishingMetadata,
} from "../../types/social";
import {
  canSubmitPrivateUpload,
  YOUTUBE_PUBLISH_SUBMIT_V1,
  canStartExactYouTubePublishResultRead,
  canReleaseYouTubePublishLock,
  cancelYouTubePublishControllers,
  exactPublishTaskResult,
  isCurrentYouTubePublishOperation,
  isCurrentExactYouTubePublishResultRead,
  isExactYouTubeRefreshJob,
  selectExactYouTubeSubmitJob,
  shouldContinueYouTubePublishPolling,
  youtubePublishJobNeedsPolling,
  shouldLoadPublishTaskHistory,
  shouldLoadSocialData,
} from "./socialPublishingState";
import {
  canReleaseInstagramOperationLock,
  canStartInstagramOperation,
  cancelInstagramOperations,
  instagramScopeSummary,
  isCurrentInstagramOperation,
  readInstagramOAuthStatus,
  safeInstagramAuthorizationUrl,
  shouldReleaseInstagramConnectLock,
} from "./instagramAccountState";
import type { InstagramOperationIdentity } from "./instagramAccountState";
import {
  canReleaseTikTokOperationLock,
  canStartTikTokOperation,
  cancelTikTokOperations,
  isCurrentTikTokOperation,
  readTikTokOAuthStatus,
  safeTikTokAuthorizationUrl,
  shouldReleaseTikTokConnectLock,
  tiktokScopeSummary,
} from "./tiktokAccountState";
import type { TikTokOperationIdentity } from "./tiktokAccountState";
import { InstagramPublishingPanel } from "./InstagramPublishingPanel";
import type {
  YouTubePublishOperationIdentity,
  YouTubePublishPollOutcome,
} from "./socialPublishingState";

type LoadState = "idle" | "loading" | "ready" | "failed";
type ActionState = "idle" | "working" | "failed";
type ResultReadState = "idle" | "reading" | "failed";

export function shouldLoadSocialAccounts(
  isPresentation: boolean,
  youtubeAccountBinding: boolean,
  instagramAccountBinding: boolean,
  tiktokAccountBinding: boolean,
  youtubePublishing: boolean,
  instagramPublishing: boolean,
): boolean {
  return (
    !isPresentation &&
    (youtubeAccountBinding ||
      instagramAccountBinding ||
      tiktokAccountBinding ||
      youtubePublishing ||
      instagramPublishing)
  );
}

export function findPlatformAccount(
  accounts: SocialAccount[],
  platform: SocialAccount["platform"],
): SocialAccount | undefined {
  return accounts.find((account) => account.platform === platform);
}

export function canLocallyDisconnectAccount(
  account: SocialAccount | undefined,
): boolean {
  return account?.connection_status === "CONNECTED";
}

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
    const loadAccountData = shouldLoadSocialAccounts(
      isPresentation,
      socialAccountBindingEnabled,
      instagramAccountBindingEnabled,
      tiktokAccountBindingEnabled,
      youtubePublishingEnabled,
      instagramPublishingEnabled,
    );
    const loadSocialData = shouldLoadSocialData(
      isPresentation,
      loadAccountData,
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
        loadAccountData
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
  const instagramOAuthStatus = readInstagramOAuthStatus(window.location.search);
  const tiktokOAuthStatus = readTikTokOAuthStatus(window.location.search);

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
      {instagramOAuthStatus === "connected" ? (
        <p className="social-publishing__notice is-success">
          Instagram Professional 账号授权已完成，正在显示安全账号身份。
        </p>
      ) : null}
      {instagramOAuthStatus === "denied" ? (
        <p className="social-publishing__notice is-error">
          你已取消 Instagram 授权，没有保存任何 Token。
        </p>
      ) : null}
      {instagramOAuthStatus === "failed" ? (
        <p className="social-publishing__notice is-error">
          Instagram 授权未完成；页面未接收 Provider 错误或敏感信息。
        </p>
      ) : null}
      {tiktokOAuthStatus === "connected" ? (
        <p className="social-publishing__notice is-success">
          TikTok 授权已完成，正在显示安全账号身份。
        </p>
      ) : null}
      {tiktokOAuthStatus === "denied" ? (
        <p className="social-publishing__notice is-error">
          你已取消 TikTok 授权，没有保存任何 Token。
        </p>
      ) : null}
      {tiktokOAuthStatus === "failed" ? (
        <p className="social-publishing__notice is-error">
          TikTok 授权未完成；页面未接收 Provider 错误或敏感信息。
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

      <InstagramAccountCard
        key={`instagram-${productId}`}
        productId={productId}
        accounts={accounts}
        onChanged={(account) => {
          setAccounts((current) => [
            account,
            ...current.filter((item) => item.id !== account.id),
          ]);
        }}
      />

      <TikTokAccountCard
        key={`tiktok-${productId}`}
        productId={productId}
        accounts={accounts}
        onChanged={(account) => {
          setAccounts((current) => [
            account,
            ...current.filter((item) => item.id !== account.id),
          ]);
        }}
      />

      {instagramPublishingEnabled ? (
        <InstagramPublishingPanel
          key={`instagram-publish-${productId}`}
          productId={productId}
          accounts={accounts}
          onTask={(nextTask) => setTasks((current) => [
            nextTask,
            ...current.filter((item) => item.id !== nextTask.id),
          ])}
        />
      ) : null}

      {youtubePublishingEnabled ? (
        <YouTubePublisher
          key={productId}
          productId={productId}
          accounts={accounts.filter(
            (account) => account.connection_status === "CONNECTED",
          )}
          artifacts={artifacts}
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

    </section>
  );
}

function InstagramAccountCard({
  productId,
  accounts,
  onChanged,
}: {
  productId: number;
  accounts: SocialAccount[];
  onChanged: (account: SocialAccount) => void;
}) {
  const instagram = accounts.find((account) => account.platform === "instagram");
  const [state, setState] = useState<ActionState>("idle");
  const [error, setError] = useState("");
  const operationIdRef = useRef(0);
  const connectRef = useRef<InstagramOperationIdentity | null>(null);
  const disconnectRef = useRef<InstagramOperationIdentity | null>(null);

  useEffect(() => {
    return () => {
      operationIdRef.current += 1;
      cancelInstagramOperations({
        connect: connectRef.current,
        disconnect: disconnectRef.current,
      });
      connectRef.current = null;
      disconnectRef.current = null;
    };
  }, [productId, instagram?.id]);

  async function connect() {
    if (
      !instagramAccountBindingEnabled ||
      !canStartInstagramOperation(connectRef.current, disconnectRef.current)
    ) {
      return;
    }
    const identity: InstagramOperationIdentity = {
      productId,
      accountId: instagram?.id ?? null,
      operationId: ++operationIdRef.current,
      controller: new AbortController(),
    };
    connectRef.current = identity;
    setState("working");
    setError("");
    let navigationStarted = false;
    try {
      const result = await connectInstagram(productId, identity.controller.signal);
      if (!isCurrentInstagramOperation(identity, connectRef.current)) return;
      const safeUrl = safeInstagramAuthorizationUrl(result.authorization_url);
      if (!safeUrl) throw new Error("Unsafe Instagram authorization URL");
      window.location.assign(safeUrl);
      navigationStarted = true;
    } catch (caught) {
      if (!isCurrentInstagramOperation(identity, connectRef.current)) return;
      setError(getApiErrorMessage(caught, "无法开始 Instagram Professional 授权。"));
      setState("failed");
    } finally {
      if (
        shouldReleaseInstagramConnectLock(
          identity,
          connectRef.current,
          navigationStarted,
        )
      ) {
        connectRef.current = null;
      }
    }
  }

  async function disconnect() {
    if (
      !instagram ||
      connectRef.current !== null ||
      disconnectRef.current !== null
    ) {
      return;
    }
    if (!window.confirm("确认仅在本机断开 Instagram？这不会撤销 Meta 侧的授权。")) {
      return;
    }
    const identity: InstagramOperationIdentity = {
      productId,
      accountId: instagram.id,
      operationId: ++operationIdRef.current,
      controller: new AbortController(),
    };
    disconnectRef.current = identity;
    setState("working");
    setError("");
    try {
      const account = await disconnectInstagramAccount(
        productId,
        instagram.id,
        identity.controller.signal,
      );
      if (!isCurrentInstagramOperation(identity, disconnectRef.current)) return;
      onChanged(account);
      setState("idle");
    } catch (caught) {
      if (!isCurrentInstagramOperation(identity, disconnectRef.current)) return;
      setError(getApiErrorMessage(caught, "Instagram 本地断开失败。"));
      setState("failed");
    } finally {
      if (canReleaseInstagramOperationLock(identity, disconnectRef.current)) {
        disconnectRef.current = null;
      }
    }
  }

  return (
    <div className="social-account-card social-account-card--instagram">
      <div>
        <span>Instagram Professional</span>
        <strong>{instagram?.display_name ?? "未连接"}</strong>
        <small>
          {instagram
            ? `${connectionLabel(instagram.connection_status)} · ${instagramScopeSummary(instagram.scopes)}`
            : instagramAccountBindingEnabled
              ? "支持 Business / Creator；不依赖 Facebook Page"
              : "Instagram 账号绑定 Gate 未开启"}
        </small>
      </div>
      <div className="social-account-card__actions">
        {!instagram || instagram.connection_status !== "CONNECTED" ? (
          <button
            type="button"
            onClick={() => void connect()}
            disabled={!instagramAccountBindingEnabled || state === "working"}
          >
            {state === "working" ? "连接中…" : "连接 Instagram"}
          </button>
        ) : (
          <button
            type="button"
            onClick={() => void disconnect()}
            disabled={state === "working"}
          >
            仅本地断开
          </button>
        )}
      </div>
      <small>本地断开只清除本机 Token，不等于在 Meta 侧撤销授权。</small>
      {error ? <p role="alert">{error}</p> : null}
    </div>
  );
}

function TikTokAccountCard({
  productId,
  accounts,
  onChanged,
}: {
  productId: number;
  accounts: SocialAccount[];
  onChanged: (account: SocialAccount) => void;
}) {
  const tiktok = findPlatformAccount(accounts, "tiktok");
  const [state, setState] = useState<ActionState>("idle");
  const [error, setError] = useState("");
  const operationIdRef = useRef(0);
  const connectRef = useRef<TikTokOperationIdentity | null>(null);
  const disconnectRef = useRef<TikTokOperationIdentity | null>(null);

  useEffect(() => () => {
    operationIdRef.current += 1;
    cancelTikTokOperations({
      connect: connectRef.current,
      disconnect: disconnectRef.current,
    });
    connectRef.current = null;
    disconnectRef.current = null;
  }, [productId, tiktok?.id]);

  async function connect() {
    if (!tiktokAccountBindingEnabled ||
      !canStartTikTokOperation(connectRef.current, disconnectRef.current)) return;
    const identity: TikTokOperationIdentity = {
      productId, accountId: tiktok?.id ?? null,
      operationId: ++operationIdRef.current, controller: new AbortController(),
    };
    connectRef.current = identity;
    setState("working");
    setError("");
    let navigationStarted = false;
    try {
      const result = await connectTikTok(productId, identity.controller.signal);
      if (!isCurrentTikTokOperation(identity, connectRef.current)) return;
      const safeUrl = safeTikTokAuthorizationUrl(result.authorization_url);
      if (!safeUrl) throw new Error("Unsafe TikTok authorization URL");
      window.location.assign(safeUrl);
      navigationStarted = true;
    } catch (caught) {
      if (!isCurrentTikTokOperation(identity, connectRef.current)) return;
      setError(getApiErrorMessage(caught, "无法开始 TikTok 授权。"));
      setState("failed");
    } finally {
      if (shouldReleaseTikTokConnectLock(
        identity, connectRef.current, navigationStarted,
      )) connectRef.current = null;
    }
  }

  async function disconnect() {
    if (!tiktok || connectRef.current !== null || disconnectRef.current !== null) return;
    if (!window.confirm("确认仅在本机断开 TikTok？这不会撤销 TikTok 侧授权。")) return;
    const identity: TikTokOperationIdentity = {
      productId, accountId: tiktok.id,
      operationId: ++operationIdRef.current, controller: new AbortController(),
    };
    disconnectRef.current = identity;
    setState("working");
    setError("");
    try {
      const account = await disconnectTikTokAccount(
        productId, tiktok.id, identity.controller.signal,
      );
      if (!isCurrentTikTokOperation(identity, disconnectRef.current)) return;
      onChanged(account);
      setState("idle");
    } catch (caught) {
      if (!isCurrentTikTokOperation(identity, disconnectRef.current)) return;
      setError(getApiErrorMessage(caught, "TikTok 本地断开失败。"));
      setState("failed");
    } finally {
      if (canReleaseTikTokOperationLock(identity, disconnectRef.current)) {
        disconnectRef.current = null;
      }
    }
  }

  return <div className="social-account-card social-account-card--tiktok">
    <div><span>TikTok</span><strong>{tiktok?.display_name ?? "未连接"}</strong>
      <small>{tiktok
        ? `${connectionLabel(tiktok.connection_status)} · ${tiktokScopeSummary(tiktok.scopes)}`
        : tiktokAccountBindingEnabled ? "Web Login Kit；视频发布留待下一阶段"
          : "TikTok 账号绑定 Gate 未开启"}</small></div>
    <div className="social-account-card__actions">
      {!canLocallyDisconnectAccount(tiktok) ?
        <button type="button" onClick={() => void connect()}
          disabled={!tiktokAccountBindingEnabled || state === "working"}>
          {state === "working" ? "连接中…" : "连接 TikTok"}</button> :
        <button type="button" onClick={() => void disconnect()}
          disabled={state === "working"}>本地断开 TikTok</button>}
    </div>
    <small>本地断开只清除本机 Token，不等于撤销 TikTok 侧授权。</small>
    {error ? <p role="alert">{error}</p> : null}
  </div>;
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
  onTask,
}: {
  productId: number;
  accounts: SocialAccount[];
  artifacts: PublishArtifactCandidate[];
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
  const [job, setJob] = useState<ExecutionJob | null>(null);
  const [task, setTask] = useState<PublishTask | null>(null);
  const [state, setState] = useState<ActionState>("idle");
  const [resultReadState, setResultReadState] = useState<ResultReadState>("idle");
  const [message, setMessage] = useState("");
  const currentProductId = useRef(productId);
  currentProductId.current = productId;
  const currentContextRef = useRef({
    productId,
    accountId: accountId ? Number(accountId) : null,
    artifactId: artifactId ? Number(artifactId) : null,
  });
  currentContextRef.current = {
    productId,
    accountId: accountId ? Number(accountId) : null,
    artifactId: artifactId ? Number(artifactId) : null,
  };
  const currentJobRef = useRef<ExecutionJob | null>(job);
  currentJobRef.current = job;
  const operationId = useRef(0);
  const preflightRef = useRef<YouTubePublishOperationIdentity | null>(null);
  const submitRef = useRef<YouTubePublishOperationIdentity | null>(null);
  const refreshRef = useRef<YouTubePublishOperationIdentity | null>(null);
  const pollRef = useRef<YouTubePublishOperationIdentity | null>(null);
  const resultReadRef = useRef<YouTubePublishOperationIdentity | null>(null);

  function metadata(): YouTubePublishingMetadata | null {
    if (!accountId || !artifactId || madeForKids === "") return null;
    return {
      social_account_id: Number(accountId),
      artifact_id: Number(artifactId),
      title,
      description,
      tags: tags.split(",").map((value) => value.trim()).filter(Boolean),
      privacy_status: "private",
      made_for_kids: madeForKids === "yes",
      synthetic_media: true,
      notify_subscribers: false,
    };
  }

  function identity(
    controller: AbortController,
    options: {
      inputDigest?: string | null;
      jobId?: number | null;
      publishTaskId?: number | null;
    } = {},
  ): YouTubePublishOperationIdentity {
    return {
      productId,
      accountId: accountId ? Number(accountId) : null,
      artifactId: artifactId ? Number(artifactId) : null,
      inputDigest: options.inputDigest ?? null,
      jobId: options.jobId ?? null,
      publishTaskId: options.publishTaskId ?? null,
      operationId: ++operationId.current,
      controller,
    };
  }

  function isCurrent(
    expected: YouTubePublishOperationIdentity,
    active: YouTubePublishOperationIdentity | null,
  ) {
    return (
      expected.productId === currentProductId.current &&
      isCurrentYouTubePublishOperation(expected, active)
    );
  }

  function isCurrentResultRead(
    expected: YouTubePublishOperationIdentity,
  ) {
    const context = currentContextRef.current;
    return (
      expected.productId === context.productId &&
      expected.accountId === context.accountId &&
      expected.artifactId === context.artifactId &&
      expected.operationId === operationId.current &&
      isCurrentExactYouTubePublishResultRead(
        expected,
        resultReadRef.current,
        currentJobRef.current,
      )
    );
  }

  function cancelOperations() {
    cancelYouTubePublishControllers({
      load: null,
      preflight: preflightRef.current,
      submit: submitRef.current,
      refresh: refreshRef.current,
      poll: pollRef.current,
      resultRead: resultReadRef.current,
    });
    preflightRef.current = null;
    submitRef.current = null;
    refreshRef.current = null;
    pollRef.current = null;
    resultReadRef.current = null;
  }

  function invalidate() {
    operationId.current += 1;
    cancelOperations();
    setPreflight(null);
    setConfirmed(false);
    setJob(null);
    setTask(null);
    setResultReadState("idle");
    setMessage("");
    setState("idle");
  }

  useEffect(() => {
    return () => {
      operationId.current += 1;
      cancelOperations();
    };
  }, []);

  useEffect(() => {
    operationId.current += 1;
    cancelOperations();
    setPreflight(null);
    setConfirmed(false);
    setJob(null);
    setTask(null);
    setResultReadState("idle");
    setMessage("");
    setState("idle");
  }, [productId]);

  async function runPreflight() {
    const data = metadata();
    if (!data) {
      setMessage("请选择账号、精确 Artifact，并明确 made-for-kids。");
      setState("failed");
      return;
    }
    if (preflightRef.current || submitRef.current) return;
    cancelOperations();
    const active = identity(new AbortController());
    preflightRef.current = active;
    setState("working");
    setMessage("");
    setConfirmed(false);
    setJob(null);
    setTask(null);
    setResultReadState("idle");
    try {
      const checked = await preflightYouTubePublish(
        productId, data, active.controller.signal,
      );
      if (
        !isCurrent(active, preflightRef.current) ||
        checked.product_id !== active.productId ||
        checked.social_account_id !== active.accountId ||
        checked.artifact_id !== active.artifactId
      ) return;
      const jobs = await listYouTubePublishJobs(
        YOUTUBE_PUBLISH_SUBMIT_V1,
        "product",
        productId,
        active.controller.signal,
      );
      if (!isCurrent(active, preflightRef.current)) return;
      setPreflight(checked);
      setJob(selectExactYouTubeSubmitJob(
        jobs,
        productId,
        Number(accountId),
        Number(artifactId),
        checked.input_digest,
      ));
      setState(checked.ready ? "idle" : "failed");
      if (!checked.ready) setMessage(checked.missing_requirements.join("；"));
    } catch (caught) {
      if (!isCurrent(active, preflightRef.current)) return;
      setState("failed");
      setMessage(getApiErrorMessage(caught, "YouTube Preflight 失败。"));
    } finally {
      if (canReleaseYouTubePublishLock(active, preflightRef.current)) {
        preflightRef.current = null;
      }
    }
  }

  async function enqueueSubmit() {
    const data = metadata();
    const checked = preflight;
    if (
      !data ||
      !checked ||
      !canSubmitPrivateUpload({
        preflightReady: checked.ready,
        confirmed,
        uploadLocked: submitRef.current !== null,
        madeForKidsSelected: madeForKids !== "",
        identityComplete: Boolean(accountId && artifactId),
      })
    ) return;
    const active = identity(new AbortController(), {
      inputDigest: checked.input_digest,
    });
    submitRef.current = active;
    setConfirmed(false);
    setState("working");
    setMessage("");
    try {
      const created = await publishYouTube(
        productId,
        {
          ...data,
          input_digest: checked.input_digest,
          preflight_digest: checked.preflight_digest,
          preflight_expires_at: checked.expires_at,
          idempotency_key: createIdempotencyKey(),
          confirm_upload: true,
        },
        active.controller.signal,
      );
      if (!isCurrent(active, submitRef.current)) return;
      const exact = selectExactYouTubeSubmitJob(
        [created.job],
        productId,
        Number(accountId),
        Number(artifactId),
        checked.input_digest,
      );
      if (!exact) {
        setState("failed");
        setMessage("入队结果身份不匹配；未执行上传恢复。");
        return;
      }
      setJob(exact);
      setState("idle");
    } catch (caught) {
      if (!isCurrent(active, submitRef.current)) return;
      setState("failed");
      setMessage(getApiErrorMessage(caught, "YouTube Submit Job 入队失败。"));
    } finally {
      if (canReleaseYouTubePublishLock(active, submitRef.current)) {
        submitRef.current = null;
      }
    }
  }

  useEffect(() => {
    if (!job || !youtubePublishJobNeedsPolling(job)) return;
    const active = identity(new AbortController(), {
      inputDigest: job.input_digest,
      jobId: job.id,
      publishTaskId: task?.id ?? null,
    });
    pollRef.current?.controller.abort();
    pollRef.current = active;
    let timer: number | null = null;
    let disposed = false;

    function schedule() {
      if (disposed || !isCurrent(active, pollRef.current)) return;
      timer = window.setTimeout(() => void pollOnce(), 1500);
    }

    async function pollOnce() {
      if (disposed || !isCurrent(active, pollRef.current)) return;
      let outcome: YouTubePublishPollOutcome = "LOCAL_READ_ERROR";
      try {
        const next = await getYouTubePublishJob(
          active.jobId!, active.controller.signal,
        );
        if (!isCurrent(active, pollRef.current) || next.id !== active.jobId) return;
        outcome = next;
        setJob(next);
        setMessage("");
      } catch (caught) {
        if (!isCurrent(active, pollRef.current)) return;
        setMessage(getApiErrorMessage(caught, "本地 Job 读取暂时失败。"));
      } finally {
        if (
          !disposed &&
          shouldContinueYouTubePublishPolling(active, pollRef.current, outcome)
        ) schedule();
      }
    }

    schedule();
    return () => {
      disposed = true;
      if (timer !== null) window.clearTimeout(timer);
      active.controller.abort();
      if (pollRef.current === active) pollRef.current = null;
    };
  }, [job?.id, job?.status]);

  async function readExactPublishTaskResult(targetJob: ExecutionJob) {
    if (
      !canStartExactYouTubePublishResultRead(
        targetJob,
        resultReadRef.current,
      )
    ) return;
    const publishTaskId = exactPublishTaskResult(targetJob);
    if (!publishTaskId) return;
    const active = identity(new AbortController(), {
      inputDigest: targetJob.input_digest,
      jobId: targetJob.id,
      publishTaskId,
    });
    resultReadRef.current = active;
    setResultReadState("reading");

    try {
        const exactTask = await getPublishTask(
          active.productId,
          active.publishTaskId!,
          active.controller.signal,
        );
        if (
          !isCurrentResultRead(active) ||
          exactTask.id !== active.publishTaskId ||
          exactTask.product_id !== active.productId ||
          exactTask.social_account_id !== active.accountId ||
          exactTask.artifact_id !== active.artifactId
        ) return;
        setTask(exactTask);
        onTask(exactTask);
        setResultReadState("idle");
        setMessage("");
      } catch (caught) {
        if (!isCurrentResultRead(active)) return;
        setResultReadState("failed");
        setMessage(getApiErrorMessage(caught, "精确 PublishTask 读取失败。"));
      } finally {
        if (isCurrentResultRead(active)) {
          resultReadRef.current = null;
        }
      }
  }

  useEffect(() => {
    if (!job || task) return;
    void readExactPublishTaskResult(job);
  }, [job?.id, job?.status, job?.result_entity_id]);

  async function enqueueRefresh() {
    if (
      !task ||
      !["SUBMITTED", "PROCESSING"].includes(task.status) ||
      refreshRef.current
    ) return;
    cancelOperations();
    const active = identity(new AbortController(), { publishTaskId: task.id });
    refreshRef.current = active;
    setMessage("");
    try {
      const created = await refreshPublishTask(
        productId,
        task.id,
        createRefreshRequestId(),
        active.controller.signal,
      );
      if (
        !isCurrent(active, refreshRef.current) ||
        !isExactYouTubeRefreshJob(
          created.job,
          productId,
          task.social_account_id,
          task.id,
        )
      ) return;
      setJob(created.job);
    } catch (caught) {
      if (!isCurrent(active, refreshRef.current)) return;
      setMessage(getApiErrorMessage(caught, "状态 Refresh Job 入队失败。"));
    } finally {
      if (canReleaseYouTubePublishLock(active, refreshRef.current)) {
        refreshRef.current = null;
      }
    }
  }

  const selectedArtifact = artifacts.find(
    (artifact) => artifact.artifact_id === Number(artifactId),
  );
  const submitUnknown = job?.status === "SUBMIT_UNKNOWN";
  const canRereadExactResult = canStartExactYouTubePublishResultRead(
    job,
    resultReadRef.current,
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
            <select value={accountId} onChange={(event) => {
              setAccountId(event.target.value);
              invalidate();
            }}>
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
            <select value={artifactId} onChange={(event) => {
              setArtifactId(event.target.value);
              invalidate();
            }}>
              <option value="">请选择 Artifact</option>
              {artifacts.map((artifact) => (
                <option key={artifact.artifact_id} value={artifact.artifact_id}>
                  Artifact #{artifact.artifact_id} · RenderTask #
                  {artifact.render_task_id} · VideoProject #
                  {artifact.video_project_id}
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
            <input value={title} maxLength={100} onChange={(event) => {
              setTitle(event.target.value);
              invalidate();
            }} />
          </label>
          <label>
            描述
            <textarea value={description} maxLength={5000} onChange={(event) => {
              setDescription(event.target.value);
              invalidate();
            }} />
          </label>
          <label>
            标签（英文逗号分隔）
            <input value={tags} onChange={(event) => {
              setTags(event.target.value);
              invalidate();
            }} />
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
          {preflight.ready && !job ? (
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
          {!job ? (
            <button
              type="button"
              onClick={() => void enqueueSubmit()}
              disabled={!canSubmitPrivateUpload({
                preflightReady: preflight.ready,
                confirmed,
                uploadLocked: submitRef.current !== null,
                madeForKidsSelected: madeForKids !== "",
                identityComplete: Boolean(accountId && artifactId),
              })}
            >
              创建 Private Upload Job
            </button>
          ) : null}
        </div>
      ) : null}
      {job ? (
        <p className="social-publishing__notice">
          Local Job #{job.id} · {job.status}
        </p>
      ) : null}
      {submitUnknown ? (
        <p className="social-publishing__notice is-error">
          上传结果不确定；禁止自动或显式重新上传。
        </p>
      ) : null}
      {message ? (
        <p className="social-publishing__notice is-error">{message}</p>
      ) : null}
      {resultReadState !== "idle" && job ? (
        <button
          type="button"
          onClick={() => void readExactPublishTaskResult(job)}
          disabled={!canRereadExactResult || resultReadState === "reading"}
        >
          {resultReadState === "reading"
            ? "正在读取精确 PublishTask 结果…"
            : "重新读取精确 PublishTask 结果"}
        </button>
      ) : null}
      {task ? (
        <div className="youtube-publish-task">
          <strong>PublishTask #{task.id} · {task.status}</strong>
          <span>Privacy: {task.privacy_status}</span>
          <span>AI 合成媒体披露：开启 · 订阅通知：关闭</span>
          <span>
            {task.uncertain
              ? "结果不确定，禁止重新上传"
              : "无自动 Provider 查询"}
          </span>
          <button
            type="button"
            onClick={() => void enqueueRefresh()}
            disabled={
              refreshRef.current !== null ||
              !task.provider_video_id ||
              !["SUBMITTED", "PROCESSING"].includes(task.status)
            }
          >
            创建一次显式 Refresh Job
          </button>
        </div>
      ) : null}
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
function createRefreshRequestId() {
  return typeof crypto.randomUUID === "function"
    ? `youtube-refresh-${crypto.randomUUID()}`
    : `youtube-refresh-${Date.now()}-${Math.random()
        .toString(16)
        .slice(2)}`;
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
