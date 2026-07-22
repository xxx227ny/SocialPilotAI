import { useCallback, useEffect, useRef, useState } from "react";

import { generateCopyMatrix } from "../api/copies";
import { getApiErrorMessage } from "../api/client";
import { getProduct, listProducts } from "../api/products";
import { generateMarketingStrategy } from "../api/strategies";
import { GrowthCopilotPanel } from "../components/GrowthCopilotPanel";
import { MarketingTaskConfig } from "../components/product/MarketingTaskConfig";
import { ProductCreateForm } from "../components/product/ProductCreateForm";
import type { CopyMatrix, PlatformCopy } from "../types/copy";
import type { Product } from "../types/product";
import type { MarketingStrategy } from "../types/strategy";

type ListState = "loading" | "refreshing" | "ready" | "error";
type DetailState = "idle" | "loading" | "ready" | "error";
type PlatformName = PlatformCopy["platform"];

export function ProductCenterPage() {
  const [products, setProducts] = useState<Product[]>([]);
  const [listState, setListState] = useState<ListState>("loading");
  const [listError, setListError] = useState("");
  const [selectedProductId, setSelectedProductId] = useState<number | null>(null);
  const [selectedProduct, setSelectedProduct] = useState<Product | null>(null);
  const [detailState, setDetailState] = useState<DetailState>("idle");
  const [detailError, setDetailError] = useState("");
  const [detailRetryKey, setDetailRetryKey] = useState(0);
  const [newlyCreatedId, setNewlyCreatedId] = useState<number | null>(null);
  const [platformDrafts, setPlatformDrafts] = useState<
    Record<number, PlatformName[]>
  >({});
  const listRequestId = useRef(0);

  const [generatingProductId, setGeneratingProductId] = useState<number | null>(
    null,
  );
  const [generatingCopyProductId, setGeneratingCopyProductId] = useState<
    number | null
  >(null);
  const [strategies, setStrategies] = useState<Record<number, MarketingStrategy>>(
    {},
  );
  const [copyMatrices, setCopyMatrices] = useState<Record<number, CopyMatrix>>(
    {},
  );
  const [workflowMessage, setWorkflowMessage] = useState("");

  const loadProducts = useCallback(async (preferredProductId?: number) => {
    const requestId = ++listRequestId.current;
    setListState((current) => (current === "ready" ? "refreshing" : "loading"));
    setListError("");

    try {
      const loadedProducts = await listProducts();
      if (requestId !== listRequestId.current) return;
      setProducts(loadedProducts);
      setListState("ready");

      if (
        preferredProductId !== undefined &&
        loadedProducts.some((product) => product.id === preferredProductId)
      ) {
        setSelectedProductId(preferredProductId);
      }
    } catch (error) {
      if (requestId !== listRequestId.current) return;
      setListError(
        getApiErrorMessage(error, "商品列表加载失败，请检查服务连接后重试。"),
      );
      setListState("error");
    }
  }, []);

  useEffect(() => {
    void loadProducts();
  }, [loadProducts]);

  useEffect(() => {
    if (selectedProductId === null) {
      setSelectedProduct(null);
      setDetailState("idle");
      setDetailError("");
      return;
    }

    const controller = new AbortController();
    let active = true;
    setDetailState("loading");
    setDetailError("");

    void getProduct(selectedProductId, controller.signal)
      .then((product) => {
        if (!active) return;
        setSelectedProduct(product);
        setDetailState("ready");
      })
      .catch((error: unknown) => {
        if (!active || controller.signal.aborted) return;
        setSelectedProduct(null);
        setDetailError(
          getApiErrorMessage(error, "商品详情加载失败，请稍后重试。"),
        );
        setDetailState("error");
      });

    return () => {
      active = false;
      controller.abort();
    };
  }, [selectedProductId, detailRetryKey]);

  function handleProductCreated(product: Product) {
    setProducts((current) => [
      product,
      ...current.filter((item) => item.id !== product.id),
    ]);
    setNewlyCreatedId(product.id);
    setSelectedProductId(product.id);
    setSelectedProduct(product);
    setDetailState("ready");
    setListError("");
    void loadProducts(product.id);
  }

  function selectProduct(productId: number) {
    setSelectedProductId(productId);
    setNewlyCreatedId((current) => (current === productId ? current : null));
  }

  function handleProductUpdated(product: Product) {
    setProducts((current) =>
      current.map((item) => (item.id === product.id ? product : item)),
    );
    setSelectedProduct((current) =>
      current?.id === product.id ? product : current,
    );
  }

  function updatePlatformDraft(productId: number, platforms: PlatformName[]) {
    setPlatformDrafts((current) => ({ ...current, [productId]: platforms }));
  }

  async function handleGenerateStrategy(productId: number) {
    try {
      setGeneratingProductId(productId);
      setWorkflowMessage("");
      const strategy = await generateMarketingStrategy(productId);
      setStrategies((current) => ({ ...current, [productId]: strategy }));
    } catch {
      setWorkflowMessage("营销分析生成失败，请检查百炼配置或稍后重试。");
    } finally {
      setGeneratingProductId(null);
    }
  }

  async function handleGenerateCopy(productId: number) {
    try {
      setGeneratingCopyProductId(productId);
      setWorkflowMessage("");
      const copyMatrix = await generateCopyMatrix(productId);
      setCopyMatrices((current) => ({ ...current, [productId]: copyMatrix }));
    } catch {
      setWorkflowMessage("社媒文案生成失败，请先完成营销分析或稍后重试。");
    } finally {
      setGeneratingCopyProductId(null);
    }
  }

  return (
    <div className="product-center">
      <header className="page-heading">
        <div>
          <span>PRODUCT CENTER</span>
          <h1>商品资料中心</h1>
          <p>创建真实商品资料，并从现有 Product API 查看列表与完整详情。</p>
        </div>
        <div className="product-count">
          <strong>{products.length}</strong>
          <span>已录入商品</span>
        </div>
      </header>

      <div className="product-layout">
        <ProductCreateForm onCreated={handleProductCreated} />

        <div className="product-management">
          <section className="product-panel product-panel--list">
            <div className="panel-heading">
              <div>
                <span className="panel-heading__icon panel-heading__icon--dark">▦</span>
                <div>
                  <h2>商品列表</h2>
                  <p>来自 Backend Product API 的真实商品记录</p>
                </div>
              </div>
              <button
                className="text-button"
                type="button"
                onClick={() => void loadProducts()}
                disabled={listState === "loading" || listState === "refreshing"}
              >
                {listState === "refreshing" ? "刷新中…" : "刷新"}
              </button>
            </div>

            <div className="product-list" aria-busy={listState === "loading"}>
              {listState === "loading" ? (
                <ProductState title="正在加载商品" detail="正在读取真实商品列表…" />
              ) : listState === "error" ? (
                <ProductState
                  title="商品列表加载失败"
                  detail={listError}
                  actionLabel="重试加载"
                  onAction={() => void loadProducts()}
                  error
                />
              ) : products.length === 0 ? (
                <ProductState
                  title="还没有商品资料"
                  detail="使用左侧表单创建第一个真实商品。"
                />
              ) : (
                products.map((product) => {
                  const selected = product.id === selectedProductId;
                  const newlyCreated = product.id === newlyCreatedId;
                  return (
                    <button
                      className={`product-list-item${selected ? " product-list-item--selected" : ""}${newlyCreated ? " product-list-item--new" : ""}`}
                      type="button"
                      key={product.id}
                      onClick={() => selectProduct(product.id)}
                      aria-pressed={selected}
                    >
                      <span className="product-item__index">
                        {product.name.slice(0, 1).toUpperCase()}
                      </span>
                      <span className="product-list-item__content">
                        <span className="product-list-item__title">
                          <strong>{product.name}</strong>
                          <small>#{String(product.id).padStart(3, "0")}</small>
                        </span>
                        <span className="product-list-item__category">
                          {product.category || "未分类"}
                        </span>
                        <span className="product-list-item__meta">
                          <span>{product.selling_points.length} 个卖点</span>
                          <span>更新于 {formatDateTime(product.updated_at)}</span>
                        </span>
                      </span>
                      {newlyCreated && <em>新创建</em>}
                    </button>
                  );
                })
              )}
            </div>
          </section>

          <section className="product-panel product-panel--detail">
            <div className="panel-heading">
              <div>
                <span className="panel-heading__icon">◎</span>
                <div>
                  <h2>商品详情</h2>
                  <p>选择商品后独立请求完整资料</p>
                </div>
              </div>
            </div>

            <div className="product-detail" aria-busy={detailState === "loading"}>
              {detailState === "idle" ? (
                <ProductState
                  title="请选择一个商品"
                  detail="点击上方列表项，查看描述、卖点、目标市场、素材和时间信息。"
                />
              ) : detailState === "loading" ? (
                <ProductState title="正在加载详情" detail="正在读取单商品 API…" />
              ) : detailState === "error" ? (
                <ProductState
                  title="商品详情加载失败"
                  detail={detailError}
                  actionLabel="重试详情"
                  onAction={() => setDetailRetryKey((current) => current + 1)}
                  error
                />
              ) : selectedProduct ? (
                <ProductDetail
                  product={selectedProduct}
                  strategy={strategies[selectedProduct.id]}
                  copyMatrix={copyMatrices[selectedProduct.id]}
                  generatingStrategy={generatingProductId === selectedProduct.id}
                  generatingCopy={generatingCopyProductId === selectedProduct.id}
                  workflowMessage={workflowMessage}
                  selectedPlatforms={platformDrafts[selectedProduct.id] ?? []}
                  onPlatformsChange={(platforms) =>
                    updatePlatformDraft(selectedProduct.id, platforms)
                  }
                  onProductUpdated={handleProductUpdated}
                  onGenerateStrategy={() =>
                    void handleGenerateStrategy(selectedProduct.id)
                  }
                  onGenerateCopy={() => void handleGenerateCopy(selectedProduct.id)}
                />
              ) : null}
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}

function ProductState({
  title,
  detail,
  actionLabel,
  onAction,
  error = false,
}: {
  title: string;
  detail: string;
  actionLabel?: string;
  onAction?: () => void;
  error?: boolean;
}) {
  return (
    <div className={`product-state${error ? " product-state--error" : ""}`}>
      <span>{error ? "!" : "◇"}</span>
      <strong>{title}</strong>
      <p>{detail}</p>
      {actionLabel && onAction && (
        <button type="button" onClick={onAction}>
          {actionLabel}
        </button>
      )}
    </div>
  );
}

function ProductDetail({
  product,
  strategy,
  copyMatrix,
  generatingStrategy,
  generatingCopy,
  workflowMessage,
  selectedPlatforms,
  onPlatformsChange,
  onProductUpdated,
  onGenerateStrategy,
  onGenerateCopy,
}: {
  product: Product;
  strategy?: MarketingStrategy;
  copyMatrix?: CopyMatrix;
  generatingStrategy: boolean;
  generatingCopy: boolean;
  workflowMessage: string;
  selectedPlatforms: PlatformName[];
  onPlatformsChange: (platforms: PlatformName[]) => void;
  onProductUpdated: (product: Product) => void;
  onGenerateStrategy: () => void;
  onGenerateCopy: () => void;
}) {
  return (
    <article className="product-detail-card">
      <header>
        <div>
          <span>PRODUCT #{String(product.id).padStart(3, "0")}</span>
          <h3>{product.name}</h3>
          <p>{product.category || "未分类"}</p>
        </div>
        <div className="product-detail-card__times">
          <small>创建：{formatDateTime(product.created_at)}</small>
          <small>更新：{formatDateTime(product.updated_at)}</small>
        </div>
      </header>

      <section>
        <h4>完整描述</h4>
        <p>{product.description || "尚未填写商品描述"}</p>
      </section>

      <div className="product-detail-card__grid">
        <section>
          <h4>商品卖点</h4>
          <ul>
            {product.selling_points.map((point) => (
              <li key={point}>{point}</li>
            ))}
          </ul>
        </section>
        <section>
          <h4>目标市场</h4>
          {product.target_markets.length > 0 ? (
            <div className="product-tags">
              {product.target_markets.map((market) => (
                <span key={market}>{market}</span>
              ))}
            </div>
          ) : (
            <p className="product-detail-card__unset">尚未设置</p>
          )}
        </section>
      </div>

      <section className="product-detail-card__assets">
        <h4>素材摘要</h4>
        <strong>{product.assets.length} 个素材</strong>
        {product.assets.length > 0 && (
          <ul>
            {product.assets.map((asset) => (
              <li key={asset.id}>
                {asset.file_name} · {asset.file_type.toUpperCase()}
              </li>
            ))}
          </ul>
        )}
      </section>

      <MarketingTaskConfig
        product={product}
        selectedPlatforms={selectedPlatforms}
        onPlatformsChange={onPlatformsChange}
        onProductUpdated={onProductUpdated}
      />

      <section className="product-detail-card__existing-workflow">
        <div className="product-item__actions">
          <button
            type="button"
            onClick={onGenerateStrategy}
            disabled={generatingStrategy}
          >
            {generatingStrategy ? "分析中…" : "生成营销分析"}
          </button>
          <button
            className="copy-action-button"
            type="button"
            title={strategy ? "一次生成三个平台文案" : "请先生成营销分析"}
            onClick={onGenerateCopy}
            disabled={!strategy || generatingCopy}
          >
            {generatingCopy ? "生成中…" : "生成社媒文案"}
          </button>
        </div>
        {workflowMessage && <p className="form-message">{workflowMessage}</p>}
        {strategy && (
          <div className="strategy-result">
            <div className="strategy-result__header">
              <span>QWEN MARKETING ANALYSIS</span>
              <strong>营销分析</strong>
            </div>
            <div className="strategy-result__positioning">
              <small>定位</small>
              <p>{strategy.positioning}</p>
            </div>
            <div className="strategy-result__grid">
              <StrategyList title="目标用户" items={strategy.audience_insights} />
              <StrategyList title="营销角度" items={strategy.angles} />
              <StrategyList title="风险提示" items={strategy.risks} warning />
            </div>
          </div>
        )}
        {copyMatrix && (
          <div className="copy-matrix-result">
            <div className="copy-matrix-result__header">
              <div>
                <span>COPY MATRIX</span>
                <strong>三平台社媒文案</strong>
              </div>
              <small>一次生成 · 3 个平台</small>
            </div>
            <div className="copy-platform-grid">
              {copyMatrix.copies.map((copy) => (
                <article
                  className={`copy-platform-card copy-platform-card--${copy.platform.toLowerCase()}`}
                  key={copy.platform}
                >
                  <div className="copy-platform-card__title">
                    <strong>{copy.platform}</strong>
                    <span>{platformLabel(copy.platform)}</span>
                  </div>
                  <CopyField title="Hook" content={copy.hook} />
                  <CopyField title="Caption" content={copy.caption} />
                  <div className="copy-field">
                    <small>Hashtags</small>
                    <div className="copy-hashtags">
                      {copy.hashtags.map((hashtag) => (
                        <span key={hashtag}>{hashtag}</span>
                      ))}
                    </div>
                  </div>
                  <CopyField title="CTA" content={copy.cta} accent />
                </article>
              ))}
            </div>
          </div>
        )}
        <GrowthCopilotPanel productId={product.id} />
      </section>
    </article>
  );
}

function formatDateTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "时间未知";
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function platformLabel(platform: "TikTok" | "Instagram" | "Facebook") {
  return {
    TikTok: "UGC · 情绪驱动",
    Instagram: "Lifestyle · 品牌感",
    Facebook: "功能价值 · 理性购买",
  }[platform];
}

function CopyField({
  title,
  content,
  accent = false,
}: {
  title: string;
  content: string;
  accent?: boolean;
}) {
  return (
    <div className={`copy-field${accent ? " copy-field--accent" : ""}`}>
      <small>{title}</small>
      <p>{content}</p>
    </div>
  );
}

function StrategyList({
  title,
  items,
  warning = false,
}: {
  title: string;
  items: string[];
  warning?: boolean;
}) {
  return (
    <div className={`strategy-list${warning ? " strategy-list--warning" : ""}`}>
      <strong>{title}</strong>
      <ul>
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}
