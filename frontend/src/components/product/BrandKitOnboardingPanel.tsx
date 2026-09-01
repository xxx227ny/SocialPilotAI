import { useCallback, useMemo, useRef, useState, type SetStateAction } from "react";
import { useReadResource } from "../../hooks/useReadResource";

import {
  bindProductBrandKitVersion,
  createBrandKit,
  createBrandKitVersion,
  deleteBrandKit,
  deleteBrandKitVersion,
  listBrandKits,
  unbindProductBrandKitVersion,
} from "../../api/brandKits";
import { getApiErrorMessage } from "../../api/client";
import { getSystemReadiness } from "../../api/health";
import { listMarketingTasks } from "../../api/marketingTasks";
import type {
  BrandKit,
  BrandKitVersion,
  BrandKitVersionInput,
} from "../../types/brandKit";
import type { Product } from "../../types/product";
import {
  automaticallySelectedVersionId,
  deriveOnboardingSteps,
  findBrandKitVersion,
  mergeBrandKitVersion,
  runWithSynchronousRequestLock,
  SAFE_QWEN_CONFIGURATION_GUIDANCE,
  versionCreationMessage,
} from "./brandKitOnboardingState";

interface Props {
  products: Product[];
  productsAvailable?: boolean;
  productDetailAvailable?: boolean;
  selectedProduct: Product | null;
  briefRevision: number;
  onProductUpdated: (product: Product) => void;
}

interface VersionDraft {
  brandName: string;
  positioning: string;
  defaultLanguage: string;
  brandTone: string;
  preferredTerms: string;
  forbiddenTerms: string;
  targetRegions: string;
  audienceGuidelines: string;
  visualGuidelines: string;
  requiredDisclosures: string;
  claimsConstraints: string;
}

const EMPTY_VERSION: VersionDraft = {
  brandName: "",
  positioning: "",
  defaultLanguage: "",
  brandTone: "",
  preferredTerms: "",
  forbiddenTerms: "",
  targetRegions: "",
  audienceGuidelines: "",
  visualGuidelines: "",
  requiredDisclosures: "",
  claimsConstraints: "",
};

function lines(value: string) {
  return value
    .split(/\r?\n|,/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function toPayload(draft: VersionDraft): BrandKitVersionInput {
  return {
    brand_name: draft.brandName.trim(),
    positioning: draft.positioning.trim(),
    default_language: draft.defaultLanguage.trim(),
    brand_tone: draft.brandTone.trim(),
    preferred_terms: lines(draft.preferredTerms),
    forbidden_terms: lines(draft.forbiddenTerms),
    target_regions: lines(draft.targetRegions),
    audience_guidelines: lines(draft.audienceGuidelines),
    visual_guidelines: lines(draft.visualGuidelines),
    required_disclosures: lines(draft.requiredDisclosures),
    claims_constraints: lines(draft.claimsConstraints),
  };
}

function fromVersion(version: BrandKitVersion): VersionDraft {
  return {
    brandName: version.brand_name,
    positioning: version.positioning,
    defaultLanguage: version.default_language,
    brandTone: version.brand_tone,
    preferredTerms: version.preferred_terms.join("\n"),
    forbiddenTerms: version.forbidden_terms.join("\n"),
    targetRegions: version.target_regions.join("\n"),
    audienceGuidelines: version.audience_guidelines.join("\n"),
    visualGuidelines: version.visual_guidelines.join("\n"),
    requiredDisclosures: version.required_disclosures.join("\n"),
    claimsConstraints: version.claims_constraints.join("\n"),
  };
}

export function BrandKitOnboardingPanel({
  products,
  productsAvailable = true,
  productDetailAvailable = true,
  selectedProduct,
  briefRevision,
  onProductUpdated,
}: Props) {
  const [collapsed, setCollapsed] = useState(false);
  const readinessRead = useReadResource("system-readiness", getSystemReadiness);
  const kitsRead = useReadResource("brand-kits", listBrandKits);
  const loadBriefs = useCallback((signal: AbortSignal) => selectedProduct
    ? listMarketingTasks(selectedProduct.id, signal) : Promise.resolve([]),
  [selectedProduct?.id, briefRevision]);
  const briefsRead = useReadResource(`briefs:${selectedProduct?.id ?? "none"}`, loadBriefs);
  const readiness = readinessRead.data;
  const brandKits = kitsRead.data ?? [];
  const briefs = briefsRead.data ?? [];
  const loading = readinessRead.loading || kitsRead.loading || briefsRead.loading;
  const loadError = [
    ["系统状态", readinessRead.error], ["品牌规范", kitsRead.error], ["营销任务", briefsRead.error],
  ].filter(([, error]) => error).map(([label, error]) => `${label}：${getApiErrorMessage(error, "暂时无法读取，请稍后重试。")}`).join(" ");
  function reloadReads() {
    readinessRead.refresh();
    kitsRead.refresh();
    briefsRead.refresh();
  }
  function setBrandKits(action: SetStateAction<BrandKit[]>) {
    kitsRead.updateData((current) => typeof action === "function" ? action(current ?? []) : action);
  }
  const [selectedKitId, setSelectedKitId] = useState<number | null>(null);
  const [selectedVersionId, setSelectedVersionId] = useState<number | null>(null);
  const [kitName, setKitName] = useState("");
  const [draft, setDraft] = useState<VersionDraft>(EMPTY_VERSION);
  const [actionState, setActionState] = useState("");
  const [actionError, setActionError] = useState("");
  const createKitLock = useRef(false);
  const createVersionLock = useRef(false);
  const bindingLock = useRef(false);
  const deletionLock = useRef(false);

  const selectedKit = useMemo(
    () => brandKits.find((kit) => kit.id === selectedKitId) ?? null,
    [brandKits, selectedKitId],
  );
  const selectedVersion = findBrandKitVersion(brandKits, selectedVersionId);
  const steps = deriveOnboardingSteps(
    readiness,
    brandKits,
    products,
    selectedProduct,
    briefs,
  );
  const knownSteps = [
    readinessRead.loadedAt !== null,
    kitsRead.loadedAt !== null,
    productsAvailable,
    productDetailAvailable && kitsRead.loadedAt !== null,
    productDetailAvailable && briefsRead.loadedAt !== null,
    readinessRead.loadedAt !== null && kitsRead.loadedAt !== null && productsAvailable && productDetailAvailable && briefsRead.loadedAt !== null,
  ];

  function chooseKit(kit: BrandKit) {
    const versionId = automaticallySelectedVersionId(kit);
    setSelectedKitId(kit.id);
    setSelectedVersionId(versionId);
    setDraft(versionId ? fromVersion(kit.versions[0]) : EMPTY_VERSION);
    setActionState("");
    setActionError("");
  }

  function chooseVersion(version: BrandKitVersion) {
    setSelectedVersionId(version.id);
    setDraft(fromVersion(version));
    setActionState("");
    setActionError("");
  }

  async function handleCreateKit() {
    if (createKitLock.current) return;
    await runWithSynchronousRequestLock(createKitLock, async () => {
      setActionError("");
      setActionState("正在创建品牌规范与版本 1……");
      try {
        const kit = await createBrandKit({
          name: kitName.trim(),
          version: toPayload(draft),
        });
        setBrandKits((current) => [...current, kit]);
        setSelectedKitId(kit.id);
        setSelectedVersionId(kit.versions[0]?.id ?? null);
        setKitName("");
        setActionState(`已创建品牌规范 #${kit.id} · 版本 1`);
      } catch (error) {
        setActionState("");
        setActionError(
          getApiErrorMessage(error, "品牌规范创建失败，可修正后重试。"),
        );
      }
    });
  }

  async function handleCreateVersion() {
    if (createVersionLock.current || !selectedKit) return;
    await runWithSynchronousRequestLock(createVersionLock, async () => {
      setActionError("");
      setActionState("正在保存不可变版本…");
      try {
        const result = await createBrandKitVersion(selectedKit.id, toPayload(draft));
        setBrandKits((current) =>
          mergeBrandKitVersion(current, selectedKit.id, result.version),
        );
        setSelectedVersionId(result.version.id);
        setDraft(fromVersion(result.version));
        setActionState(versionCreationMessage(result));
      } catch (error) {
        setActionState("");
        setActionError(
          getApiErrorMessage(error, "品牌版本创建失败，可修正后重试。"),
        );
      }
    });
  }

  async function handleBinding(unbind: boolean) {
    if (
      bindingLock.current ||
      !selectedProduct ||
      (!unbind && (!selectedKit || !selectedVersion))
    ) {
      return;
    }
    await runWithSynchronousRequestLock(bindingLock, async () => {
      setActionError("");
      setActionState(unbind ? "正在解除精确版本绑定…" : "正在绑定精确版本…");
      try {
        const updated = unbind
          ? await unbindProductBrandKitVersion(selectedProduct.id)
          : await bindProductBrandKitVersion(selectedProduct.id, {
              brand_kit_id: selectedKit!.id,
              brand_kit_version_id: selectedVersion!.id,
            });
        onProductUpdated(updated);
        setActionState(
          unbind
            ? "已解除品牌规范版本绑定"
            : `已绑定品牌规范版本 #${updated.brand_kit_version_id}`,
        );
      } catch (error) {
        setActionState("");
        setActionError(
          getApiErrorMessage(error, "版本绑定操作失败，可恢复后重试。"),
        );
      }
    });
  }

  async function handleDeleteVersion(version: BrandKitVersion) {
    if (
      deletionLock.current ||
      !selectedKit ||
      selectedKit.versions.length <= 1 ||
      !window.confirm(
        `确定删除品牌规范 #${selectedKit.id} 的未使用版本 ${version.version_number} 吗？此操作不可撤销。`,
      )
    ) {
      return;
    }
    await runWithSynchronousRequestLock(deletionLock, async () => {
      setActionError("");
      setActionState("正在检查引用并删除不可变版本……");
      try {
        await deleteBrandKitVersion(selectedKit.id, version.id);
        const remainingVersions = selectedKit.versions.filter(
          (item) => item.id !== version.id,
        );
        const updatedKit = { ...selectedKit, versions: remainingVersions };
        setBrandKits((current) =>
          current.map((kit) => (kit.id === updatedKit.id ? updatedKit : kit)),
        );
        const nextVersionId = automaticallySelectedVersionId(updatedKit);
        setSelectedVersionId(nextVersionId);
        setDraft(
          nextVersionId && remainingVersions[0]
            ? fromVersion(remainingVersions[0])
            : EMPTY_VERSION,
        );
        setActionState(`已删除未使用的不可变版本 #${version.id}`);
      } catch (error) {
        setActionState("");
        setActionError(
          getApiErrorMessage(error, "版本删除失败；该版本可能仍被业务记录引用。"),
        );
      }
    });
  }

  async function handleDeleteKit(kit: BrandKit) {
    if (
      deletionLock.current ||
      !window.confirm(
        `确定删除品牌规范“${kit.name}”及其全部未使用版本吗？此操作不可撤销。`,
      )
    ) {
      return;
    }
    await runWithSynchronousRequestLock(deletionLock, async () => {
      setActionError("");
      setActionState("正在检查引用并删除品牌规范……");
      try {
        await deleteBrandKit(kit.id);
        setBrandKits((current) => current.filter((item) => item.id !== kit.id));
        setSelectedKitId(null);
        setSelectedVersionId(null);
        setDraft(EMPTY_VERSION);
        setActionState(`已删除品牌规范 #${kit.id}`);
      } catch (error) {
        setActionState("");
        setActionError(
          getApiErrorMessage(error, "品牌规范删除失败；其中可能有版本仍被业务记录引用。"),
        );
      }
    });
  }

  return (
    <section className="brand-onboarding" aria-label="首次使用引导与品牌规范">
      <header className="brand-onboarding__header">
        <div>
          <span>首次使用 · 本地数据</span>
          <h2>首次使用引导</h2>
          <p>状态来自本地数据库与系统就绪检查；刷新或重启后会重新计算。</p>
        </div>
        <button type="button" onClick={() => setCollapsed((value) => !value)}>
          {collapsed ? "展开" : "收起"}
        </button>
      </header>

      {!collapsed && (
        <>
          <ol className="brand-onboarding__steps">
            {steps.map((step, index) => (
              <li className={step.complete ? "is-complete" : "is-pending"} key={step.id}>
                <span>{knownSteps[index] && step.complete ? "✓" : step.id}</span>
                <strong>{step.label}</strong>
                <small>{!knownSteps[index] ? "待确认" : step.complete ? "已完成" : "待完成"}</small>
              </li>
            ))}
          </ol>

          {readinessRead.error === null && !readinessRead.loading && readiness?.qwen.ready === false && (
            <p className="brand-onboarding__configuration">
              {SAFE_QWEN_CONFIGURATION_GUIDANCE}
            </p>
          )}
          {loading && <p>正在分别读取系统状态、品牌规范和营销任务；已有资料会保留。</p>}
          {loadError && (
            <div className="brand-onboarding__error" role="alert">
              <p>{loadError}</p>
              <p>读取失败不代表资料被删除或 API Key 失效。已加载的区域仍可查看；失败区域如有旧资料，将保留上次结果。</p>
              <button type="button" disabled={loading} onClick={reloadReads}>
                重新读取
              </button>
            </div>
          )}

          <div className="brand-kit-workspace">
            <section className="brand-kit-list">
              <header>
                <div>
                  <h3>品牌规范与不可变版本</h3>
                  <p>存在多个版本时不会自动选择最新记录，必须明确选择。</p>
                </div>
                <button type="button" disabled={kitsRead.loading} onClick={kitsRead.refresh}>
                  重新读取本地记录
                </button>
              </header>
              {brandKits.length === 0 ? (
                <p className="brand-kit-empty">{kitsRead.error ? "品牌规范暂时无法读取，不能确认是否为空；请先重新读取，勿重复创建。" : kitsRead.loadedAt === null ? "正在读取品牌规范…" : "尚无品牌规范；系统不会自动创建。"}</p>
              ) : (
                brandKits.map((kit) => (
                  <article className={selectedKitId === kit.id ? "is-selected" : ""} key={kit.id}>
                    <button type="button" onClick={() => chooseKit(kit)}>
                      <strong>品牌规范 #{kit.id} · {kit.name}</strong>
                      <span>{kit.versions.length} 个不可变版本</span>
                    </button>
                    {selectedKitId === kit.id && (
                      <div className="brand-kit-version-list">
                        {kit.versions.length > 1 && selectedVersionId === null && (
                          <p>存在多个版本，请明确选择；不会自动使用最新版本。</p>
                        )}
                        {kit.versions.map((version) => (
                          <div className="brand-kit-version-row" key={version.id}>
                            <label>
                              <input
                                type="radio"
                                name={`brand-kit-${kit.id}-version`}
                                checked={selectedVersionId === version.id}
                                onChange={() => chooseVersion(version)}
                              />
                              <span>
                                版本 {version.version_number} · #{version.id} · {version.digest.slice(0, 12)}…
                              </span>
                            </label>
                            <button
                              type="button"
                              className="brand-kit-danger-button"
                              disabled={kit.versions.length <= 1}
                              title={
                                kit.versions.length <= 1
                                  ? "最后一个版本不能单独删除，请删除整个品牌规范"
                                  : "仅未被任何业务记录引用时可删除"
                              }
                              onClick={() => void handleDeleteVersion(version)}
                            >
                              删除版本
                            </button>
                          </div>
                        ))}
                        <button
                          type="button"
                          className="brand-kit-danger-button brand-kit-delete-button"
                          onClick={() => void handleDeleteKit(kit)}
                        >
                          删除整个品牌规范
                        </button>
                      </div>
                    )}
                  </article>
                ))
              )}
            </section>

            <section className="brand-kit-editor">
              <header>
                <h3>{selectedKit ? `为品牌规范 #${selectedKit.id} 创建新版本` : "创建品牌规范与版本 1"}</h3>
                <p>编辑会创建新版本，不会覆盖或删除历史版本。</p>
              </header>
              {!selectedKit && (
                <label>
                  品牌规范名称
                  <input value={kitName} onChange={(event) => setKitName(event.target.value)} />
                </label>
              )}
              <VersionEditor draft={draft} onChange={setDraft} />
              <div className="brand-kit-editor__actions">
                {selectedKit ? (
                  <button type="button" onClick={() => void handleCreateVersion()}>
                    创建或复用不可变版本
                  </button>
                ) : (
                  <button type="button" disabled={kitsRead.loadedAt === null || !!kitsRead.error} onClick={() => void handleCreateKit()}>
                    创建品牌规范与版本 1
                  </button>
                )}
                {selectedKit && (
                  <button
                    type="button"
                    className="text-button"
                    onClick={() => {
                      setSelectedKitId(null);
                      setSelectedVersionId(null);
                      setDraft(EMPTY_VERSION);
                    }}
                  >
                    返回新建品牌规范
                  </button>
                )}
              </div>
            </section>
          </div>

          {selectedVersion && <VersionEvidence version={selectedVersion} />}

          <section className="brand-kit-binding">
            <div>
              <h3>商品与品牌规范版本绑定</h3>
              <p>
                {selectedProduct
                  ? `当前商品 #${selectedProduct.id} · 已绑定版本 ${selectedProduct.brand_kit_version_id ?? "无"}`
                  : "请先在商品列表明确选择商品。"}
              </p>
            </div>
            <div>
              <button
                type="button"
                disabled={!selectedProduct || !selectedKit || !selectedVersion}
                onClick={() => void handleBinding(false)}
              >
                绑定当前明确版本
              </button>
              <button
                type="button"
                disabled={!selectedProduct?.brand_kit_version_id}
                onClick={() => void handleBinding(true)}
              >
                解除绑定
              </button>
            </div>
          </section>

          {(actionState || actionError) && (
            <p className={actionError ? "brand-onboarding__error" : "brand-onboarding__success"} role="status">
              {actionError || actionState}
            </p>
          )}
        </>
      )}
    </section>
  );
}

function VersionEditor({
  draft,
  onChange,
}: {
  draft: VersionDraft;
  onChange: (draft: VersionDraft) => void;
}) {
  function field<K extends keyof VersionDraft>(key: K, value: VersionDraft[K]) {
    onChange({ ...draft, [key]: value });
  }
  const listFields: Array<{ key: keyof VersionDraft; label: string }> = [
    { key: "preferredTerms", label: "推荐用语" },
    { key: "forbiddenTerms", label: "禁用词" },
    { key: "targetRegions", label: "目标地区" },
    { key: "audienceGuidelines", label: "受众规范" },
    { key: "visualGuidelines", label: "视觉规范" },
    { key: "requiredDisclosures", label: "必须披露" },
    { key: "claimsConstraints", label: "声明限制" },
  ];
  return (
    <div className="brand-kit-fields">
      <label>品牌名称<input value={draft.brandName} onChange={(event) => field("brandName", event.target.value)} /></label>
      <label>默认语言<input value={draft.defaultLanguage} onChange={(event) => field("defaultLanguage", event.target.value)} /></label>
      <label className="is-wide">品牌定位<textarea value={draft.positioning} onChange={(event) => field("positioning", event.target.value)} /></label>
      <label className="is-wide">品牌语气<textarea value={draft.brandTone} onChange={(event) => field("brandTone", event.target.value)} /></label>
      {listFields.map((item) => (
        <label key={item.key}>
          {item.label}
          <textarea
            value={draft[item.key]}
            onChange={(event) => field(item.key, event.target.value)}
            placeholder="每行一项"
          />
        </label>
      ))}
    </div>
  );
}

function VersionEvidence({ version }: { version: BrandKitVersion }) {
  const groups = [
    ["推荐用语", version.preferred_terms],
    ["禁用词", version.forbidden_terms],
    ["地区", version.target_regions],
    ["受众", version.audience_guidelines],
    ["视觉", version.visual_guidelines],
    ["披露", version.required_disclosures],
    ["声明限制", version.claims_constraints],
  ] as const;
  return (
    <article className="brand-version-evidence">
      <header>
        <div><span>不可变版本</span><h3>品牌规范版本 #{version.id} · 版本 {version.version_number}</h3></div>
        <code>{version.digest.slice(0, 16)}…</code>
      </header>
      <dl>
        <div><dt>品牌名称</dt><dd>{version.brand_name}</dd></div>
        <div><dt>定位</dt><dd>{version.positioning}</dd></div>
        <div><dt>语言</dt><dd>{version.default_language}</dd></div>
        <div><dt>语气</dt><dd>{version.brand_tone}</dd></div>
      </dl>
      <div className="brand-version-evidence__groups">
        {groups.map(([label, values]) => (
          <section key={label}><strong>{label}</strong><p>{values.length ? values.join(" · ") : "未设置"}</p></section>
        ))}
      </div>
    </article>
  );
}
