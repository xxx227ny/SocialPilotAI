import { useEffect, useRef, useState } from "react";

import { getApiErrorMessage } from "../../api/client";
import { getProduct, listProducts } from "../../api/products";
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
  const [products, setProducts] = useState<Product[]>([]);
  const [selectedId, setSelectedId] = useState(() => {
    if (!storageKey) return 0;
    try {
      const stored = Number(window.localStorage.getItem(storageKey));
      return Number.isInteger(stored) && stored > 0 ? stored : 0;
    } catch {
      return 0;
    }
  });
  const [selectedProduct, setSelectedProduct] = useState<Product | null>(null);
  const [message, setMessage] = useState("正在读取商品……");
  const requestId = useRef(0);

  useEffect(() => {
    let active = true;
    void listProducts()
      .then((items) => {
        if (!active) return;
        setProducts(items);
        if (selectedId > 0 && !items.some((item) => item.id === selectedId)) {
          setSelectedId(0);
          if (storageKey) {
            try {
              window.localStorage.removeItem(storageKey);
            } catch {
              // Storage may be unavailable in a restricted browser session.
            }
          }
        }
        setMessage(items.length > 0 ? "请选择要操作的商品。" : "尚未创建商品，请先前往商品中心。 ");
      })
      .catch((error) => {
        if (active) {
          setMessage(getApiErrorMessage(error, "商品列表读取失败，请检查本地服务。"));
        }
      });
    return () => {
      active = false;
    };
  }, [storageKey]);

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

  useEffect(() => {
    const currentRequest = ++requestId.current;
    setSelectedProduct(null);
    if (selectedId <= 0) return;
    const controller = new AbortController();
    setMessage("正在读取所选商品……");
    void getProduct(selectedId, controller.signal)
      .then((product) => {
        if (currentRequest !== requestId.current) return;
        setSelectedProduct(product);
        setMessage("");
      })
      .catch((error) => {
        if (!controller.signal.aborted && currentRequest === requestId.current) {
          setMessage(getApiErrorMessage(error, "所选商品读取失败，请重新选择。"));
        }
      });
    return () => controller.abort();
  }, [selectedId]);

  function updateProduct(product: Product) {
    setProducts((items) =>
      items.map((item) => (item.id === product.id ? product : item)),
    );
    setSelectedProduct(product);
  }

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
      {message ? <p role="status">{message}</p> : null}
      {selectedProduct ? children(selectedProduct, updateProduct) : null}
    </section>
  );
}
