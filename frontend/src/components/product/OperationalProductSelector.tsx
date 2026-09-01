import { useCallback, useEffect, useState } from "react";

import { getApiErrorMessage } from "../../api/client";
import { getProduct, listProducts } from "../../api/products";
import { useReadResource } from "../../hooks/useReadResource";
import type { Product } from "../../types/product";

export function OperationalProductSelector({
  title,
  description,
  storageKey,
  children,
}: {
  title: string;
  description: string;
  storageKey?: string;
  children: (
    product: Product,
    updateProduct: (product: Product) => void,
  ) => React.ReactNode;
}) {
  const productList = useReadResource("products", listProducts);
  const products = productList.data ?? [];
  const [selectedId, setSelectedId] = useState(() => {
    if (!storageKey) return 0;
    try {
      const stored = Number(window.localStorage.getItem(storageKey));
      return Number.isInteger(stored) && stored > 0 ? stored : 0;
    } catch {
      return 0;
    }
  });
  const loadSelectedProduct = useCallback(
    (signal: AbortSignal) => selectedId > 0
      ? getProduct(selectedId, signal)
      : Promise.resolve(null),
    [selectedId],
  );
  const selected = useReadResource(`product:${selectedId}`, loadSelectedProduct);
  const selectedProduct = selected.data;

  useEffect(() => {
    // Only discard a remembered choice after a successful authoritative read.
    // A slow or interrupted refresh must not erase a choice that was just used.
    if (
      productList.loadedAt !== null &&
      !productList.loading &&
      !productList.error &&
      selectedId > 0 &&
      !products.some((item) => item.id === selectedId)
    ) {
      setSelectedId(0);
    }
  }, [productList.loadedAt, productList.loading, productList.error, products, selectedId]);

  useEffect(() => {
    if (!storageKey) return;
    try {
      if (selectedId > 0) {
        window.localStorage.setItem(storageKey, String(selectedId));
      } else {
        window.localStorage.removeItem(storageKey);
      }
    } catch {
      // The selector still works when browser storage is unavailable.
    }
  }, [selectedId, storageKey]);

  function updateProduct(product: Product) {
    productList.updateData((items) =>
      (items ?? []).map((item) => (item.id === product.id ? product : item)),
    );
    selected.updateData(product);
  }

  const listMessage = productList.loadedAt === null
    ? productList.error
      ? getApiErrorMessage(productList.error, "商品列表读取失败，请稍后重试。")
      : "正在首次读取商品……"
    : products.length === 0
      ? "尚未创建商品，请先前往商品中心。"
      : selectedId === 0
        ? "请选择要操作的商品。"
        : "";
  const detailMessage = selectedId > 0 && selectedProduct === null
    ? selected.error
      ? getApiErrorMessage(selected.error, "所选商品读取失败，请重新读取。")
      : "正在首次读取所选商品……"
    : "";

  return (
    <section className="operational-product-workspace">
      <header>
        <div>
          <span>选择操作商品</span>
          <h2>{title}</h2>
          <p>{description}</p>
        </div>
        <label>
          当前商品
          <select
            value={selectedId}
            onChange={(event) => setSelectedId(Number(event.target.value))}
          >
            <option value={0}>请选择商品</option>
            {products.map((product) => (
              <option key={product.id} value={product.id}>
                #{product.id} · {product.name}
              </option>
            ))}
          </select>
        </label>
      </header>
      {listMessage || detailMessage ? (
        <p role="status">
          {detailMessage || listMessage}
          {(productList.error || selected.error) ? (
            <button type="button" onClick={productList.error ? productList.refresh : selected.refresh}>
              重新读取
            </button>
          ) : null}
        </p>
      ) : null}
      {selectedProduct ? children(selectedProduct, updateProduct) : null}
    </section>
  );
}
