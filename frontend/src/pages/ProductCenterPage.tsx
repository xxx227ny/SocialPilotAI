import { useCallback, useEffect, useRef, useState } from "react";

import { getApiErrorMessage } from "../api/client";
import {
  deleteProduct,
  deleteProductImage,
  getProduct,
  listProducts,
  productImageContentUrl,
  uploadProductImage,
} from "../api/products";
import { BrandKitOnboardingPanel } from "../components/product/BrandKitOnboardingPanel";
import { ProductCreateForm } from "../components/product/ProductCreateForm";
import { usePresentationMode } from "../context/PresentationModeContext";
import type { Product } from "../types/product";

type ListState = "loading" | "refreshing" | "ready" | "error";
type DetailState = "idle" | "loading" | "ready" | "error";
const PRODUCT_CENTER_SELECTION_KEY = "socialpilot.productCenter.selectedProduct";

function restoredProductCenterSelection() {
  try {
    const stored = Number(
      window.localStorage.getItem(PRODUCT_CENTER_SELECTION_KEY),
    );
    return Number.isInteger(stored) && stored > 0 ? stored : null;
  } catch {
    return null;
  }
}

export function ProductCenterPage() {
  const { isPresentation } = usePresentationMode();
  const [products, setProducts] = useState<Product[]>([]);
  const [listState, setListState] = useState<ListState>("loading");
  const [listError, setListError] = useState("");
  const [selectedProductId, setSelectedProductId] = useState<number | null>(
    restoredProductCenterSelection,
  );
  const [selectedProduct, setSelectedProduct] = useState<Product | null>(null);
  const [detailState, setDetailState] = useState<DetailState>("idle");
  const [detailError, setDetailError] = useState("");
  const [detailRetryKey, setDetailRetryKey] = useState(0);
  const [newlyCreatedId, setNewlyCreatedId] = useState<number | null>(null);
  const listRequestId = useRef(0);

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
    if (
      listState === "ready" &&
      selectedProductId !== null &&
      !products.some((product) => product.id === selectedProductId)
    ) {
      setSelectedProductId(null);
    }
  }, [listState, products, selectedProductId]);

  useEffect(() => {
    try {
      if (selectedProductId === null) {
        window.localStorage.removeItem(PRODUCT_CENTER_SELECTION_KEY);
      } else {
        window.localStorage.setItem(
          PRODUCT_CENTER_SELECTION_KEY,
          String(selectedProductId),
        );
      }
    } catch {
      // 商品中心在受限浏览器中仍可正常使用，只是不保留选择。
    }
  }, [selectedProductId]);

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

  function handleProductDeleted(productId: number) {
    setProducts((current) => current.filter((item) => item.id !== productId));
    setSelectedProductId(null);
    setSelectedProduct(null);
    setDetailState("idle");
    setDetailError("");
    setNewlyCreatedId((current) => (current === productId ? null : current));
    void loadProducts();
  }

  return (
    <div className="product-center">
      <header className="page-heading">
        <div>
          <span>商品资料中心</span>
          <h1>商品资料中心</h1>
          <p>创建真实商品资料，并从后端商品接口查看列表与完整详情。</p>
        </div>
        <div className="product-count">
          <strong>{products.length}</strong>
          <span>已录入商品</span>
        </div>
      </header>

      {!isPresentation && (
        <BrandKitOnboardingPanel
          products={products}
          selectedProduct={selectedProduct}
          briefRevision={0}
          onProductUpdated={handleProductUpdated}
        />
      )}

      <div className="product-layout">
        <ProductCreateForm onCreated={handleProductCreated} />

        <div className="product-management">
          <section className="product-panel product-panel--list">
            <div className="panel-heading">
              <div>
                <span className="panel-heading__icon panel-heading__icon--dark">▦</span>
                <div>
                  <h2>商品列表</h2>
                  <p>来自后端商品接口的真实商品记录</p>
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
                <ProductState title="正在加载详情" detail="正在读取单个商品资料……" />
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
                  key={selectedProduct.id}
                  product={selectedProduct}
                  allowUpload={!isPresentation}
                  onProductUpdated={handleProductUpdated}
                  onProductDeleted={handleProductDeleted}
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
  allowUpload,
  onProductUpdated,
  onProductDeleted,
}: {
  product: Product;
  allowUpload: boolean;
  onProductUpdated: (product: Product) => void;
  onProductDeleted: (productId: number) => void;
}) {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadMessage, setUploadMessage] = useState("");
  const [uploadError, setUploadError] = useState("");
  const [deletingAssetId, setDeletingAssetId] = useState<number | null>(null);
  const [deletingProduct, setDeletingProduct] = useState(false);
  const [deleteMessage, setDeleteMessage] = useState("");
  const [deleteError, setDeleteError] = useState("");
  const uploadRequestId = useRef(0);
  const uploadController = useRef<AbortController | null>(null);
  const deleteController = useRef<AbortController | null>(null);

  useEffect(
    () => () => {
      uploadRequestId.current += 1;
      uploadController.current?.abort();
      deleteController.current?.abort();
    },
    [],
  );

  async function handleUpload() {
    if (!selectedFile || uploading) return;
    const requestId = ++uploadRequestId.current;
    uploadController.current?.abort();
    const controller = new AbortController();
    uploadController.current = controller;
    setUploading(true);
    setUploadMessage("");
    setUploadError("");
    try {
      const uploaded = await uploadProductImage(
        product.id,
        selectedFile,
        controller.signal,
      );
      const refreshed = await getProduct(product.id, controller.signal);
      if (requestId !== uploadRequestId.current) return;
      onProductUpdated(refreshed);
      setSelectedFile(null);
      setUploadMessage(
        uploaded.reused
          ? `图片内容已存在，已复用素材 #${uploaded.id}。`
          : `真实商品图片已上传为素材 #${uploaded.id}。`,
      );
    } catch (error) {
      if (controller.signal.aborted || requestId !== uploadRequestId.current) return;
      setUploadError(
        getApiErrorMessage(error, "真实商品图片上传失败，请检查格式后重试。"),
      );
    } finally {
      if (requestId === uploadRequestId.current) setUploading(false);
    }
  }

  async function handleDeleteAsset(assetId: number, fileName: string) {
    if (deletingAssetId !== null || deletingProduct) return;
    if (
      !window.confirm(
        `确认删除素材 #${assetId}「${fileName}」？如果素材已用于视频或成片，系统会安全拒绝。`,
      )
    ) {
      return;
    }
    deleteController.current?.abort();
    const controller = new AbortController();
    deleteController.current = controller;
    setDeletingAssetId(assetId);
    setDeleteMessage("");
    setDeleteError("");
    try {
      await deleteProductImage(product.id, assetId, controller.signal);
      const refreshed = await getProduct(product.id, controller.signal);
      if (controller.signal.aborted) return;
      onProductUpdated(refreshed);
      setDeleteMessage(`素材 #${assetId} 已删除。`);
    } catch (error) {
      if (controller.signal.aborted) return;
      setDeleteError(
        getApiErrorMessage(error, "素材删除失败，请刷新后重试。"),
      );
    } finally {
      if (!controller.signal.aborted) setDeletingAssetId(null);
    }
  }

  async function handleDeleteProduct() {
    if (deletingProduct || deletingAssetId !== null) return;
    if (
      !window.confirm(
        `确认删除整个商品资料「${product.name}」？未被历史任务引用的商品素材也会一并删除。此操作不可撤销。`,
      )
    ) {
      return;
    }
    deleteController.current?.abort();
    const controller = new AbortController();
    deleteController.current = controller;
    setDeletingProduct(true);
    setDeleteMessage("");
    setDeleteError("");
    try {
      await deleteProduct(product.id, controller.signal);
      if (controller.signal.aborted) return;
      onProductDeleted(product.id);
    } catch (error) {
      if (controller.signal.aborted) return;
      setDeleteError(
        getApiErrorMessage(
          error,
          "商品删除失败；若已有脚本、视频或投流记录，系统会保护历史数据。",
        ),
      );
    } finally {
      if (!controller.signal.aborted) setDeletingProduct(false);
    }
  }

  return (
    <article className="product-detail-card">
      <header>
        <div>
          <span>商品 #{String(product.id).padStart(3, "0")}</span>
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

      {allowUpload && (
        <section className="product-asset-upload">
          <div>
            <h4>上传真实商品素材</h4>
            <p>
              请选择清晰的商品实拍图或官方商品图。视频工厂会把你选中的图片作为所有分镜的主参考图。
            </p>
          </div>
          <label className="product-asset-upload__picker">
            <span>选择 JPG、PNG 或 WebP 图片</span>
            <input
              type="file"
              accept="image/jpeg,image/png,image/webp"
              disabled={uploading}
              onChange={(event) => {
                setSelectedFile(event.target.files?.[0] ?? null);
                setUploadMessage("");
                setUploadError("");
              }}
            />
          </label>
          {selectedFile && (
            <p className="product-asset-upload__selection">
              已选择：{selectedFile.name} · {formatFileSize(selectedFile.size)}
            </p>
          )}
          <button
            type="button"
            disabled={!selectedFile || uploading}
            onClick={() => void handleUpload()}
          >
            {uploading ? "上传中…" : "上传并加入商品素材"}
          </button>
          {uploadMessage && <p className="product-asset-upload__success">{uploadMessage}</p>}
          {uploadError && <p className="product-asset-upload__error">{uploadError}</p>}
        </section>
      )}

      <section className="product-detail-card__assets">
        <h4>素材摘要</h4>
        <strong>{product.assets.length} 个素材</strong>
        {product.assets.length > 0 && (
          <div className="product-asset-grid">
            {product.assets.map((asset) => (
              <article key={asset.id}>
                {asset.sha256 && asset.content_type?.startsWith("image/") ? (
                  <img
                    src={productImageContentUrl(product.id, asset.id)}
                    alt={`${product.name} 素材 ${asset.id}`}
                    loading="lazy"
                  />
                ) : (
                  <div className="product-asset-grid__placeholder">无预览</div>
                )}
                <div>
                  <strong>素材 #{asset.id}</strong>
                  <span
                    className={
                      asset.file_name === "wanx-product.png"
                        ? "product-asset-origin product-asset-origin--ai"
                        : "product-asset-origin"
                    }
                  >
                    {asset.file_name === "wanx-product.png"
                      ? "万象生成素材"
                      : "商品参考素材"}
                  </span>
                  <p>{asset.file_name}</p>
                  <small>
                    {asset.width && asset.height
                      ? `${asset.width} × ${asset.height} · `
                      : ""}
                    {asset.size_bytes ? formatFileSize(asset.size_bytes) : asset.file_type.toUpperCase()}
                  </small>
                  {allowUpload && (
                    <button
                      className="product-asset-delete-button"
                      type="button"
                      disabled={deletingAssetId !== null || deletingProduct}
                      onClick={() =>
                        void handleDeleteAsset(asset.id, asset.file_name)
                      }
                    >
                      {deletingAssetId === asset.id ? "删除中…" : "删除素材"}
                    </button>
                  )}
                </div>
              </article>
            ))}
          </div>
        )}
      </section>

      {allowUpload && (
        <section className="product-danger-zone">
          <div>
            <h4>删除商品资料</h4>
            <p>
              仅未被历史任务引用的商品可以删除；已有脚本、视频、发布或投流记录时，系统会拒绝删除以保护证据。
            </p>
          </div>
          <button
            type="button"
            disabled={deletingProduct || deletingAssetId !== null}
            onClick={() => void handleDeleteProduct()}
          >
            {deletingProduct ? "删除中…" : "删除整个商品资料"}
          </button>
        </section>
      )}

      {deleteMessage && (
        <p className="product-asset-upload__success" role="status">
          {deleteMessage}
        </p>
      )}
      {deleteError && (
        <p className="product-asset-upload__error" role="alert">
          {deleteError}
        </p>
      )}

      <p className="product-detail-card__workflow-note">
        文案生成请前往“文案矩阵”，商品视频生产请前往“视频工厂”。
      </p>
    </article>
  );
}

function formatFileSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDateTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "时间未知";
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}
