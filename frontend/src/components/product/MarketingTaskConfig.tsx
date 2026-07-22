import { useEffect, useMemo, useRef, useState } from "react";

import { getApiErrorMessage } from "../../api/client";
import {
  createMarketingTask,
  getLatestMarketingTask,
} from "../../api/marketingTasks";
import { updateProduct } from "../../api/products";
import type { PlatformCopy } from "../../types/copy";
import type { MarketingTask } from "../../types/marketing";
import type { Product } from "../../types/product";

type PlatformName = PlatformCopy["platform"];
type SaveState = "synced" | "dirty" | "saving" | "success" | "error";
type TaskState =
  | "loading"
  | "empty"
  | "ready"
  | "load-error"
  | "creating"
  | "checking"
  | "create-error";

interface MarketingTaskConfigProps {
  product: Product;
  selectedPlatforms: PlatformName[];
  onPlatformsChange: (platforms: PlatformName[]) => void;
  onProductUpdated: (product: Product) => void;
}

const MARKET_OPTIONS = [
  { code: "US", label: "United States", aliases: ["us", "usa", "united states"] },
  { code: "CA", label: "Canada", aliases: ["ca", "canada"] },
  { code: "UK", label: "United Kingdom", aliases: ["uk", "gb", "united kingdom"] },
  { code: "DE", label: "Germany", aliases: ["de", "germany"] },
  { code: "FR", label: "France", aliases: ["fr", "france"] },
  { code: "AU", label: "Australia", aliases: ["au", "australia"] },
  { code: "JP", label: "Japan", aliases: ["jp", "japan"] },
  { code: "SG", label: "Singapore", aliases: ["sg", "singapore"] },
] as const;

const PLATFORM_OPTIONS: Array<{
  name: PlatformName;
  purpose: string;
}> = [
  { name: "TikTok", purpose: "短视频 Hook、UGC 表达与情绪驱动" },
  { name: "Instagram", purpose: "Lifestyle 视觉叙事与品牌表达" },
  { name: "Facebook", purpose: "完整功能价值与理性购买理由" },
];

function normalize(value: string) {
  return value.trim().toLocaleLowerCase("en-US");
}

function marketKey(value: string) {
  const normalized = normalize(value);
  const known = MARKET_OPTIONS.find((option) =>
    option.aliases.some((alias) => alias === normalized),
  );
  return known?.code ?? `legacy:${normalized}`;
}

function exactUnique(values: string[]) {
  return values.filter(
    (value, index, all) =>
      value.trim().length > 0 &&
      all.findIndex((candidate) => normalize(candidate) === normalize(value)) ===
        index,
  );
}

function languageForMarkets(markets: string[]) {
  const languageByMarket: Record<string, string> = {
    US: "English",
    CA: "English/French",
    UK: "English",
    DE: "German",
    FR: "French",
    AU: "English",
    JP: "Japanese",
    SG: "English",
  };
  return [...new Set(markets.map((market) => languageByMarket[market]))].join(
    ", ",
  );
}

function formatTaskTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "时间未知";
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

export function MarketingTaskConfig({
  product,
  selectedPlatforms,
  onPlatformsChange,
  onProductUpdated,
}: MarketingTaskConfigProps) {
  const [markets, setMarkets] = useState<string[]>(product.target_markets);
  const [saveState, setSaveState] = useState<SaveState>("synced");
  const [saveError, setSaveError] = useState("");
  const [taskState, setTaskState] = useState<TaskState>("loading");
  const [taskError, setTaskError] = useState("");
  const [savedTask, setSavedTask] = useState<MarketingTask | null>(null);
  const [taskRetryKey, setTaskRetryKey] = useState(0);
  const saveLock = useRef(false);
  const saveRequestId = useRef(0);
  const marketsRef = useRef(markets);
  const taskSubmitLock = useRef(false);
  const taskRequestId = useRef(0);
  const taskController = useRef<AbortController | null>(null);
  const platformsChangeRef = useRef(onPlatformsChange);
  const activeProductId = useRef(product.id);
  const configuredProductId = useRef(product.id);
  const lastSavedMarketSignature = useRef<string | null>(null);
  const productMarketSignature = JSON.stringify(product.target_markets);
  activeProductId.current = product.id;
  platformsChangeRef.current = onPlatformsChange;

  useEffect(() => {
    const sameProduct = configuredProductId.current === product.id;
    configuredProductId.current = product.id;
    saveRequestId.current += 1;
    saveLock.current = false;
    marketsRef.current = [...product.target_markets];
    setMarkets([...product.target_markets]);
    setSaveState(
      sameProduct && lastSavedMarketSignature.current === productMarketSignature
        ? "success"
        : "synced",
    );
    setSaveError("");
    if (!sameProduct) lastSavedMarketSignature.current = null;
  }, [product.id, productMarketSignature]);

  useEffect(() => {
    const productId = product.id;
    const requestId = ++taskRequestId.current;
    const controller = new AbortController();
    taskController.current?.abort();
    taskController.current = controller;
    taskSubmitLock.current = false;
    setSavedTask(null);
    setTaskError("");
    setTaskState("loading");

    void getLatestMarketingTask(productId, controller.signal)
      .then((task) => {
        if (
          controller.signal.aborted ||
          requestId !== taskRequestId.current ||
          activeProductId.current !== productId
        ) {
          return;
        }
        if (task === null) {
          setTaskState("empty");
          return;
        }
        setSavedTask(task);
        platformsChangeRef.current(task.platforms);
        setTaskState("ready");
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted || requestId !== taskRequestId.current) {
          return;
        }
        setTaskError(
          getApiErrorMessage(error, "最近任务输入读取失败，请恢复服务后重试。"),
        );
        setTaskState("load-error");
      });

    return () => controller.abort();
  }, [product.id, taskRetryKey]);

  const selectedMarketKeys = useMemo(
    () => [...new Set(markets.map(marketKey))],
    [markets],
  );
  const selectedMarketCount = selectedMarketKeys.length;
  const marketsValid = selectedMarketCount >= 1 && selectedMarketCount <= 5;
  const hasUnsavedMarkets =
    JSON.stringify(markets) !== JSON.stringify(product.target_markets);
  const legacyMarkets = markets.filter((market) =>
    marketKey(market).startsWith("legacy:"),
  );

  const productValid =
    product.name.trim().length >= 2 &&
    Boolean(product.category?.trim()) &&
    Boolean(product.description?.trim()) &&
    product.selling_points.length > 0;
  const platformsValid =
    selectedPlatforms.length >= 1 && selectedPlatforms.length <= 3;
  const taskReady =
    productValid &&
    marketsValid &&
    legacyMarkets.length === 0 &&
    !hasUnsavedMarkets &&
    platformsValid;

  function updateMarkets(nextMarkets: string[]) {
    marketsRef.current = nextMarkets;
    setMarkets(nextMarkets);
    setSaveState(
      JSON.stringify(nextMarkets) === productMarketSignature ? "synced" : "dirty",
    );
    setSaveError("");
  }

  function toggleMarket(code: (typeof MARKET_OPTIONS)[number]["code"]) {
    const currentMarkets = marketsRef.current;
    const currentKeys = [...new Set(currentMarkets.map(marketKey))];
    const nextMarkets = currentKeys.includes(code)
      ? currentMarkets.filter((market) => marketKey(market) !== code)
      : currentKeys.length >= 5
        ? currentMarkets
        : [...currentMarkets, code];
    marketsRef.current = nextMarkets;
    setMarkets(nextMarkets);
    setSaveState(
      JSON.stringify(nextMarkets) === productMarketSignature
        ? "synced"
        : "dirty",
    );
    setSaveError("");
  }

  function removeLegacyMarket(value: string) {
    updateMarkets(markets.filter((market) => market !== value));
  }

  function togglePlatform(platform: PlatformName) {
    onPlatformsChange(
      selectedPlatforms.includes(platform)
        ? selectedPlatforms.filter((item) => item !== platform)
        : [...selectedPlatforms, platform],
    );
  }

  async function saveMarkets() {
    if (saveLock.current || !hasUnsavedMarkets || !marketsValid) return;

    const requestId = ++saveRequestId.current;
    const productId = product.id;
    const payloadMarkets = exactUnique(
      marketsRef.current.map((market) => market.trim()),
    );
    saveLock.current = true;
    setSaveState("saving");
    setSaveError("");

    try {
      const updatedProduct = await updateProduct(productId, {
        target_markets: payloadMarkets,
      });
      if (
        requestId !== saveRequestId.current ||
        activeProductId.current !== productId
      ) {
        return;
      }
      lastSavedMarketSignature.current = JSON.stringify(
        updatedProduct.target_markets,
      );
      onProductUpdated(updatedProduct);
      marketsRef.current = [...updatedProduct.target_markets];
      setMarkets([...updatedProduct.target_markets]);
      setSaveState("success");
    } catch (error) {
      if (
        requestId !== saveRequestId.current ||
        activeProductId.current !== productId
      ) {
        return;
      }
      setSaveError(
        getApiErrorMessage(error, "目标市场保存失败，请恢复服务后重试。"),
      );
      setSaveState("error");
    } finally {
      if (
        requestId === saveRequestId.current &&
        activeProductId.current === productId
      ) {
        saveLock.current = false;
      }
    }
  }

  async function createTask() {
    if (
      taskSubmitLock.current ||
      !taskReady ||
      taskState === "loading" ||
      taskState === "load-error" ||
      taskState === "creating" ||
      taskState === "checking"
    ) {
      return;
    }

    const requestId = ++taskRequestId.current;
    const productId = product.id;
    const previousTaskId = savedTask?.id ?? null;
    const controller = new AbortController();
    taskController.current?.abort();
    taskController.current = controller;
    taskSubmitLock.current = true;
    setTaskError("");
    setTaskState("creating");

    const targetMarkets = product.target_markets.map((market) =>
      marketKey(market).replace("legacy:", ""),
    );
    const payload = {
      product_id: productId,
      audience: `Cross-border consumers in ${targetMarkets.join(", ")}`,
      language: languageForMarkets(targetMarkets),
      platforms: selectedPlatforms,
      tone: "Clear and trustworthy",
      objective: `Prepare social marketing input for ${product.name}`,
    };

    try {
      const task = await createMarketingTask(payload, controller.signal);
      if (
        requestId !== taskRequestId.current ||
        activeProductId.current !== productId
      ) {
        return;
      }
      setSavedTask(task);
      platformsChangeRef.current(task.platforms);
      setTaskState("ready");
    } catch (error) {
      if (
        controller.signal.aborted ||
        requestId !== taskRequestId.current ||
        activeProductId.current !== productId
      ) {
        return;
      }
      setTaskState("checking");
      try {
        const latest = await getLatestMarketingTask(productId);
        if (
          requestId !== taskRequestId.current ||
          activeProductId.current !== productId
        ) {
          return;
        }
        if (latest !== null && latest.id !== previousTaskId) {
          setSavedTask(latest);
          platformsChangeRef.current(latest.platforms);
          setTaskState("ready");
          return;
        }
      } catch {
        // The original request may have reached Backend; keep the retry explicit.
      }
      setTaskError(
        getApiErrorMessage(
          error,
          "任务输入保存失败；已尝试核对最近记录，请恢复服务后重试。",
        ),
      );
      setTaskState("create-error");
    } finally {
      if (
        requestId === taskRequestId.current &&
        activeProductId.current === productId
      ) {
        taskSubmitLock.current = false;
      }
    }
  }

  return (
    <section className="marketing-task-config" aria-label="营销任务配置">
      <header>
        <div>
          <span>MARKETING BRIEF INPUT</span>
          <h4>营销任务配置</h4>
          <p>保存真实 MarketingBrief 输入；本操作不会调用 AI 或生成内容。</p>
        </div>
        <strong className={taskReady ? "task-ready" : "task-not-ready"}>
          {taskReady ? "配置已就绪" : "配置未就绪"}
        </strong>
      </header>

      <div className="marketing-config-block">
        <div className="marketing-config-heading">
          <div>
            <h5>目标市场</h5>
            <p>保存到当前 Product 的 target_markets</p>
          </div>
          <strong>{selectedMarketCount} / 5</strong>
        </div>
        <div className="market-option-grid">
          {MARKET_OPTIONS.map((option) => {
            const selected = selectedMarketKeys.includes(option.code);
            const disabled = !selected && selectedMarketCount >= 5;
            return (
              <button
                className={selected ? "market-option market-option--selected" : "market-option"}
                type="button"
                key={option.code}
                onClick={() => toggleMarket(option.code)}
                disabled={disabled || saveState === "saving"}
                aria-pressed={selected}
              >
                <strong>{option.code}</strong>
                <span>{option.label}</span>
              </button>
            );
          })}
        </div>
        {legacyMarkets.length > 0 && (
          <div className="legacy-markets">
            <strong>兼容保留的历史市场值</strong>
            <p>这些值来自 Backend，除非你明确移除并保存，否则不会被删除。</p>
            <div>
              {legacyMarkets.map((market) => (
                <button
                  type="button"
                  key={market}
                  onClick={() => removeLegacyMarket(market)}
                  disabled={saveState === "saving"}
                  aria-label={`移除历史市场 ${market}`}
                >
                  {market} ×
                </button>
              ))}
            </div>
          </div>
        )}
        {!marketsValid && (
          <p className="marketing-config-error">
            请选择 1—5 个不重复的目标市场。
          </p>
        )}
        <div className="market-save-row">
          <div aria-live="polite">
            {saveState === "synced" && <span>已与 Backend 同步</span>}
            {saveState === "dirty" && <span>有未保存修改</span>}
            {saveState === "saving" && <span>正在保存目标市场…</span>}
            {saveState === "success" && <span>目标市场已保存到 Backend</span>}
            {saveState === "error" && <span className="save-error">{saveError}</span>}
          </div>
          <button
            type="button"
            onClick={() => void saveMarkets()}
            disabled={!hasUnsavedMarkets || !marketsValid || saveState === "saving"}
          >
            {saveState === "saving"
              ? "保存中…"
              : saveState === "error"
                ? "重试保存"
                : "保存目标市场"}
          </button>
        </div>
      </div>

      <div className="marketing-config-block">
        <div className="marketing-config-heading">
          <div>
            <h5>内容平台</h5>
            <p>仅选择现有内容链路支持的平台</p>
          </div>
          <strong>{selectedPlatforms.length} / 3</strong>
        </div>
        <div className="platform-option-grid">
          {PLATFORM_OPTIONS.map((option) => {
            const selected = selectedPlatforms.includes(option.name);
            return (
              <button
                className={selected ? "platform-option platform-option--selected" : "platform-option"}
                type="button"
                key={option.name}
                onClick={() => togglePlatform(option.name)}
                aria-pressed={selected}
              >
                <strong>{option.name}</strong>
                <span>{option.purpose}</span>
              </button>
            );
          })}
        </div>
        {!platformsValid && (
          <p className="marketing-config-error">请选择 1—3 个内容平台。</p>
        )}
        <p className="platform-draft-boundary">
          创建前平台是按商品隔离的会话草稿；点击“创建营销任务输入”后将写入
          MarketingBrief。此操作不代表发布或已获得社媒账号授权。
        </p>
      </div>

      <div className="task-readiness-summary">
        <div className="marketing-config-heading">
          <div>
            <h5>任务就绪摘要</h5>
            <p>确认后只保存任务输入，不会调用 AI</p>
          </div>
        </div>
        <dl>
          <div><dt>当前商品</dt><dd>#{product.id} · {product.name}</dd></div>
          <div><dt>目标市场</dt><dd>{markets.length > 0 ? markets.join("、") : "未选择"}</dd></div>
          <div><dt>内容平台</dt><dd>{selectedPlatforms.length > 0 ? selectedPlatforms.join("、") : "未选择"}</dd></div>
          <div><dt>商品卖点</dt><dd>{product.selling_points.length} 个</dd></div>
          <div><dt>商品描述</dt><dd>{product.description?.trim() ? "完整" : "不完整"}</dd></div>
          <div><dt>市场持久化</dt><dd>{hasUnsavedMarkets ? "尚有未保存修改" : "已保存"}</dd></div>
        </dl>
        {legacyMarkets.length > 0 && (
          <p className="marketing-config-error">
            历史未知市场不能用于创建任务；请明确移除并保存受支持市场。
          </p>
        )}
        <p className="task-ai-boundary">
          本操作只保存任务输入，不会调用 Qwen、Wanx 或任何 AI Provider。
        </p>
        <button
          type="button"
          onClick={() => void createTask()}
          disabled={
            !taskReady ||
            taskState === "loading" ||
            taskState === "load-error" ||
            taskState === "creating" ||
            taskState === "checking"
          }
        >
          {taskState === "creating"
            ? "正在保存任务输入…"
            : taskState === "checking"
              ? "正在核对 Backend 记录…"
              : "创建营销任务输入"}
        </button>

        <div className="task-record-state" aria-live="polite">
          {taskState === "loading" && <p>正在从 Backend 恢复最近任务输入…</p>}
          {taskState === "empty" && <p>当前商品尚无已保存的任务输入。</p>}
          {taskState === "load-error" && (
            <div className="task-record-error">
              <p>{taskError}</p>
              <button type="button" onClick={() => setTaskRetryKey((key) => key + 1)}>
                重试读取
              </button>
            </div>
          )}
          {taskState === "create-error" && (
            <div className="task-record-error">
              <p>{taskError}</p>
              <button type="button" onClick={() => void createTask()}>
                重试创建
              </button>
            </div>
          )}
          {savedTask && taskState === "ready" && (
            <article className="task-record-card">
              <header>
                <div>
                  <span>BACKEND SAVED</span>
                  <strong>MarketingBrief #{savedTask.id}</strong>
                </div>
                <time>{formatTaskTime(savedTask.created_at)}</time>
              </header>
              <dl>
                <div><dt>关联商品</dt><dd>#{savedTask.product_id} · {product.name}</dd></div>
                <div><dt>目标市场</dt><dd>{savedTask.target_markets.join("、")}</dd></div>
                <div><dt>已保存平台</dt><dd>{savedTask.platforms.join("、")}</dd></div>
                <div><dt>保存状态</dt><dd>Backend 真实记录已保存</dd></div>
              </dl>
              <p>任务输入已保存，等待 V2-C2 AI 策略生成。</p>
            </article>
          )}
        </div>
      </div>
    </section>
  );
}
