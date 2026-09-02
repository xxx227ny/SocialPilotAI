import { type FormEvent, useRef, useState } from "react";

import { getApiErrorMessage, isUnconfirmedApiMutation } from "../../api/client";
import { createProduct, listProducts } from "../../api/products";
import type { Product, ProductCreatePayload } from "../../types/product";

interface ProductCreateFormProps {
  onCreated: (product: Product) => void;
}

interface ProductFormState {
  name: string;
  category: string;
  description: string;
  sellingPoints: string[];
}

interface ProductFormErrors {
  name?: string;
  category?: string;
  description?: string;
  sellingPoints?: Record<number, string>;
  sellingPointsSummary?: string;
}

function emptyForm(): ProductFormState {
  return {
    name: "",
    category: "",
    description: "",
    sellingPoints: [""],
  };
}

function validateForm(
  form: ProductFormState,
): { errors: ProductFormErrors; payload?: ProductCreatePayload } {
  const errors: ProductFormErrors = {};
  const name = form.name.trim();
  const category = form.category.trim();
  const description = form.description.trim();

  if (name.length < 2 || name.length > 120) {
    errors.name = "商品名称需为 2—120 个字符。";
  }
  if (category.length < 2 || category.length > 80) {
    errors.category = "商品分类需为 2—80 个字符。";
  }
  if (description.length < 10 || description.length > 2000) {
    errors.description = "商品描述需为 10—2000 个字符。";
  }

  const pointErrors: Record<number, string> = {};
  form.sellingPoints.forEach((point, index) => {
    const length = point.trim().length;
    if (length > 0 && (length < 2 || length > 160)) {
      pointErrors[index] = "每项卖点需为 2—160 个字符。";
    }
  });
  if (Object.keys(pointErrors).length > 0) {
    errors.sellingPoints = pointErrors;
  }

  const normalizedPoints = form.sellingPoints
    .map((point) => point.trim())
    .filter(Boolean)
    .filter((point, index, all) => all.indexOf(point) === index);
  if (normalizedPoints.length === 0) {
    errors.sellingPointsSummary = "请至少填写一个有效卖点。";
  } else if (normalizedPoints.length > 8) {
    errors.sellingPointsSummary = "商品卖点最多 8 项。";
  }

  if (
    errors.name ||
    errors.category ||
    errors.description ||
    errors.sellingPoints ||
    errors.sellingPointsSummary
  ) {
    return { errors };
  }

  return {
    errors,
    payload: {
      name,
      category,
      description,
      selling_points: normalizedPoints,
    },
  };
}

function matchesRecentCreation(
  product: Product,
  payload: ProductCreatePayload,
  requestedAt: number,
) {
  return product.name === payload.name
    && product.category === payload.category
    && product.description === payload.description
    && product.selling_points.length === payload.selling_points.length
    && product.selling_points.every(
      (point, index) => point === payload.selling_points[index],
    )
    && Date.parse(product.created_at) >= requestedAt - 2_000;
}

function wait(milliseconds: number) {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

export function ProductCreateForm({ onCreated }: ProductCreateFormProps) {
  const [form, setForm] = useState<ProductFormState>(emptyForm);
  const [errors, setErrors] = useState<ProductFormErrors>({});
  const [submitting, setSubmitting] = useState(false);
  const [requestError, setRequestError] = useState("");
  const [createdProduct, setCreatedProduct] = useState<Product | null>(null);
  const submitLock = useRef(false);

  function updateField(field: "name" | "category" | "description", value: string) {
    setForm((current) => ({ ...current, [field]: value }));
    setErrors((current) => ({ ...current, [field]: undefined }));
  }

  function updateSellingPoint(index: number, value: string) {
    setForm((current) => ({
      ...current,
      sellingPoints: current.sellingPoints.map((point, pointIndex) =>
        pointIndex === index ? value : point,
      ),
    }));
    setErrors((current) => ({
      ...current,
      sellingPoints: {
        ...current.sellingPoints,
        [index]: "",
      },
      sellingPointsSummary: undefined,
    }));
  }

  function addSellingPoint() {
    setForm((current) =>
      current.sellingPoints.length >= 8
        ? current
        : { ...current, sellingPoints: [...current.sellingPoints, ""] },
    );
  }

  function removeSellingPoint(index: number) {
    setForm((current) => ({
      ...current,
      sellingPoints:
        current.sellingPoints.length === 1
          ? [""]
          : current.sellingPoints.filter((_, pointIndex) => pointIndex !== index),
    }));
    setErrors((current) => ({
      ...current,
      sellingPoints: undefined,
      sellingPointsSummary: undefined,
    }));
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitLock.current) return;

    const validation = validateForm(form);
    setErrors(validation.errors);
    setRequestError("");
    setCreatedProduct(null);
    if (!validation.payload) return;

    submitLock.current = true;
    setSubmitting(true);
    const requestedAt = Date.now();
    try {
      const product = await createProduct(validation.payload);
      setCreatedProduct(product);
      setForm(emptyForm());
      onCreated(product);
    } catch (error) {
      if (isUnconfirmedApiMutation(error)) {
        try {
          await wait(800);
          const products = await listProducts();
          const recovered = products.find((product) =>
            matchesRecentCreation(product, validation.payload!, requestedAt),
          );
          if (recovered) {
            setCreatedProduct(recovered);
            setForm(emptyForm());
            onCreated(recovered);
            setRequestError("");
            return;
          }
        } catch {
          // Preserve the original delivery uncertainty when confirmation also fails.
        }
      }
      setRequestError(
        getApiErrorMessage(error, "商品创建失败，请检查服务连接后重试。"),
      );
    } finally {
      submitLock.current = false;
      setSubmitting(false);
    }
  }

  return (
    <section className="product-panel product-panel--form">
      <div className="panel-heading">
        <div>
          <span className="panel-heading__icon">＋</span>
          <div>
            <h2>创建商品</h2>
            <p>四项资料均为必填，不会自动触发 AI</p>
          </div>
        </div>
      </div>

      <form className="product-form" onSubmit={handleSubmit} noValidate>
        <div className="product-form__field">
          <label htmlFor="product-name">
            商品名称 <em>*</em>
          </label>
          <input
            id="product-name"
            value={form.name}
            onChange={(event) => updateField("name", event.target.value)}
            placeholder="例如：USB Portable Blender"
            maxLength={120}
            aria-invalid={Boolean(errors.name)}
          />
          <small>必填，2—120 个字符，将自动去除首尾空格。</small>
          {errors.name && <small className="field-error">{errors.name}</small>}
        </div>

        <div className="product-form__field">
          <label htmlFor="product-category">
            商品分类 <em>*</em>
          </label>
          <input
            id="product-category"
            value={form.category}
            onChange={(event) => updateField("category", event.target.value)}
            placeholder="例如：Portable Kitchen Appliance"
            maxLength={80}
            aria-invalid={Boolean(errors.category)}
          />
          <small>必填，2—80 个字符。</small>
          {errors.category && <small className="field-error">{errors.category}</small>}
        </div>

        <div className="product-form__field">
          <label htmlFor="product-description">
            商品描述 <em>*</em>
          </label>
          <textarea
            id="product-description"
            value={form.description}
            onChange={(event) => updateField("description", event.target.value)}
            placeholder="描述商品、使用场景和核心价值"
            rows={4}
            maxLength={2000}
            aria-invalid={Boolean(errors.description)}
          />
          <small>必填，10—2000 个字符；当前 {form.description.length} 个字符。</small>
          {errors.description && (
            <small className="field-error">{errors.description}</small>
          )}
        </div>

        <fieldset className="selling-points-fieldset">
          <legend>
            商品卖点 <em>*</em>
          </legend>
          <div className="selling-points-fieldset__heading">
            <small>1—8 项，每项 2—160 个字符；空白项会在提交前清除。</small>
            <button
              type="button"
              onClick={addSellingPoint}
              disabled={form.sellingPoints.length >= 8 || submitting}
            >
              ＋ 增加卖点
            </button>
          </div>
          {form.sellingPoints.map((point, index) => (
            <div className="selling-point-row" key={index}>
              <div>
                <label htmlFor={`selling-point-${index}`}>卖点 {index + 1}</label>
                <input
                  id={`selling-point-${index}`}
                  value={point}
                  onChange={(event) => updateSellingPoint(index, event.target.value)}
                  placeholder="例如：USB rechargeable"
                  maxLength={160}
                  aria-invalid={Boolean(errors.sellingPoints?.[index])}
                />
                {errors.sellingPoints?.[index] && (
                  <small className="field-error">
                    {errors.sellingPoints[index]}
                  </small>
                )}
              </div>
              <button
                className="selling-point-row__remove"
                type="button"
                onClick={() => removeSellingPoint(index)}
                disabled={form.sellingPoints.length === 1 || submitting}
                aria-label={`删除卖点 ${index + 1}`}
              >
                删除
              </button>
            </div>
          ))}
          {errors.sellingPointsSummary && (
            <small className="field-error">{errors.sellingPointsSummary}</small>
          )}
        </fieldset>

        {requestError && (
          <div className="form-message" role="alert">
            {requestError}
          </div>
        )}
        <button className="primary-button" type="submit" disabled={submitting}>
          {submitting ? "正在创建，请勿重复提交…" : "创建商品"}
        </button>
      </form>

      {createdProduct && (
        <div className="product-create-success" role="status">
          <span>创建成功</span>
          <strong>
            #{createdProduct.id} · {createdProduct.name}
          </strong>
          <p>{createdProduct.category}</p>
          <small>{createdProduct.selling_points.join("、")}</small>
        </div>
      )}
    </section>
  );
}
