import { useCallback, useEffect, useState } from "react";

import { listProducts } from "../api/products";
import { generateCopyMatrix } from "../api/copies";
import { generateMarketingStrategy } from "../api/strategies";
import { ProductCreateForm } from "../components/product/ProductCreateForm";
import type { CopyMatrix } from "../types/copy";
import type { Product } from "../types/product";
import type { MarketingStrategy } from "../types/strategy";
import { GrowthCopilotPanel } from "../components/GrowthCopilotPanel";

export function ProductCenterPage() {
  const [products, setProducts] = useState<Product[]>([]);
  const [loading, setLoading] = useState(true);
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
  const [message, setMessage] = useState("");

  const loadProducts = useCallback(async () => {
    try {
      setLoading(true);
      setProducts(await listProducts());
      setMessage("");
    } catch {
      setMessage("无法连接商品服务，请确认后端已启动。");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadProducts();
  }, [loadProducts]);

  function handleProductCreated(product: Product) {
    setProducts((current) => [
      product,
      ...current.filter((item) => item.id !== product.id),
    ]);
    setMessage("");
  }

  async function handleGenerateStrategy(productId: number) {
    try {
      setGeneratingProductId(productId);
      setMessage("");
      const strategy = await generateMarketingStrategy(productId);
      setStrategies((current) => ({ ...current, [productId]: strategy }));
    } catch {
      setMessage("营销分析生成失败，请检查百炼配置或稍后重试。");
    } finally {
      setGeneratingProductId(null);
    }
  }

  async function handleGenerateCopy(productId: number) {
    try {
      setGeneratingCopyProductId(productId);
      setMessage("");
      const copyMatrix = await generateCopyMatrix(productId);
      setCopyMatrices((current) => ({
        ...current,
        [productId]: copyMatrix,
      }));
    } catch {
      setMessage("社媒文案生成失败，请先完成营销分析或稍后重试。");
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
          <p>沉淀标准化商品信息，为后续营销工作流提供可信的数据基础。</p>
        </div>
        <div className="product-count">
          <strong>{products.length}</strong>
          <span>已录入商品</span>
        </div>
      </header>

      <div className="product-layout">
        <ProductCreateForm onCreated={handleProductCreated} />

        <section className="product-panel product-panel--list">
          <div className="panel-heading">
            <div>
              <span className="panel-heading__icon panel-heading__icon--dark">□</span>
              <div>
                <h2>商品列表</h2>
                <p>已录入的商品资料与市场信息</p>
              </div>
            </div>
            <button className="text-button" type="button" onClick={() => void loadProducts()}>
              刷新
            </button>
          </div>

          <div className="product-list">
            {loading ? (
              <div className="product-empty">正在加载商品…</div>
            ) : products.length === 0 ? (
              <div className="product-empty">
                <span>□</span>
                <strong>还没有商品资料</strong>
                <p>使用左侧表单创建第一个商品。</p>
              </div>
            ) : (
              products.map((product) => (
                <article className="product-item" key={product.id}>
                  <div className="product-item__index">
                    {product.name.slice(0, 1).toUpperCase()}
                  </div>
                  <div className="product-item__content">
                    <div className="product-item__title">
                      <div>
                        <h3>{product.name}</h3>
                        <span>{product.category || "未分类"}</span>
                      </div>
                      <div className="product-item__actions">
                        <small>#{String(product.id).padStart(3, "0")}</small>
                        <button
                          type="button"
                          onClick={() => void handleGenerateStrategy(product.id)}
                          disabled={generatingProductId === product.id}
                        >
                          {generatingProductId === product.id
                            ? "分析中…"
                            : "生成营销分析"}
                        </button>
                        <button
                          className="copy-action-button"
                          type="button"
                          title={
                            strategies[product.id]
                              ? "一次生成三个平台文案"
                              : "请先生成营销分析"
                          }
                          onClick={() => void handleGenerateCopy(product.id)}
                          disabled={
                            !strategies[product.id] ||
                            generatingCopyProductId === product.id
                          }
                        >
                          {generatingCopyProductId === product.id
                            ? "生成中…"
                            : "生成社媒文案"}
                        </button>
                      </div>
                    </div>
                    <p>{product.description || "暂无商品描述"}</p>
                    <div className="product-tags">
                      {product.target_markets.map((market) => (
                        <span key={market}>{market}</span>
                      ))}
                    </div>
                    <div className="product-item__meta">
                      <span>{product.selling_points.length} 个卖点</span>
                      <span>{product.assets.length} 个素材</span>
                      <span>
                        更新于 {new Date(product.updated_at).toLocaleDateString("zh-CN")}
                      </span>
                    </div>
                    {strategies[product.id] && (
                      <div className="strategy-result">
                        <div className="strategy-result__header">
                          <span>QWEN MARKETING ANALYSIS</span>
                          <strong>营销分析</strong>
                        </div>
                        <div className="strategy-result__positioning">
                          <small>定位</small>
                          <p>{strategies[product.id].positioning}</p>
                        </div>
                        <div className="strategy-result__grid">
                          <StrategyList
                            title="目标用户"
                            items={strategies[product.id].audience_insights}
                          />
                          <StrategyList
                            title="营销角度"
                            items={strategies[product.id].angles}
                          />
                          <StrategyList
                            title="风险提示"
                            items={strategies[product.id].risks}
                            warning
                          />
                        </div>
                      </div>
                    )}
                    {copyMatrices[product.id] && (
                      <div className="copy-matrix-result">
                        <div className="copy-matrix-result__header">
                          <div>
                            <span>COPY MATRIX</span>
                            <strong>三平台社媒文案</strong>
                          </div>
                          <small>一次生成 · 3 个平台</small>
                        </div>
                        <div className="copy-platform-grid">
                          {copyMatrices[product.id].copies.map((copy) => (
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
                  </div>
                </article>
              ))
            )}
          </div>
        </section>
      </div>
    </div>
  );
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
