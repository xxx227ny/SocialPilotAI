import React, { useState } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import axios from "axios";
import { apiClient } from "../../src/api/client";
import { ProductCenterPage } from "../../src/pages/ProductCenterPage";
import { PresentationModeProvider } from "../../src/context/PresentationModeContext";
import { SystemReadinessPanel } from "../../src/components/system/SystemReadinessPanel";
import "../../src/styles.css";

let mode = new URLSearchParams(location.search).get("offline") ? "offline" : "healthy";
let readCount = 0;
let writeCount = 0;
const version = { id: 21, brand_kit_id: 11, version_number: 1, digest: "a".repeat(64), brand_name: "Fixture Brand", positioning: "Test only", default_language: "en-US", brand_tone: "Clear", preferred_terms: [], forbidden_terms: [], target_regions: [], audience_guidelines: [], visual_guidelines: [], required_disclosures: [], claims_constraints: [], created_at: "2026-08-30T00:00:00Z" };
const kit = { id: 11, name: "隔离测试品牌", versions: [version], created_at: version.created_at, updated_at: version.created_at };
const product = { id: 901, name: "隔离商品 A", category: "测试配件", description: "只用于本地读取失败恢复验收的模拟资料。", selling_points: ["不触发真实服务"], target_markets: ["US"], assets: [], brand_kit_id: 11, brand_kit_version_id: 21, created_at: version.created_at, updated_at: version.created_at };
const products = [product, { ...product, id: 902, name: "隔离商品 B" }];
const item = { ready: true, message: "ready" };
const readiness = { backend: item, qwen: item, wanx: item, database: { ...item, revision_status: "head", revision: "fixture" }, artifact_storage: item, execution_worker: item, google_youtube: item, meta_instagram: item, tiktok: item, pinterest: item, tiktok_publishing: item, instagram_publishing: item, provider_calls: 0, database_writes: 0, automatic_actions: false };
apiClient.defaults.adapter = async (config) => {
  const method = (config.method ?? "get").toLowerCase();
  if (method !== "get") {
    writeCount++;
    await new Promise(resolve => setTimeout(resolve, 600));
    throw new axios.AxiosError("simulated uncertain write", "ERR_NETWORK", config);
  }
  readCount++;
  if (mode === "slow") await new Promise(resolve => setTimeout(resolve, 6000));
  if (mode === "offline" || (mode === "brand-failure" && config.url === "/brand-kits")) {
    throw new axios.AxiosError("simulated offline", "ERR_NETWORK", config);
  }
  let data: unknown;
  if (config.url === "/system/readiness") data = readiness;
  else if (config.url === "/brand-kits") data = [kit];
  else if (config.url === "/products") data = products;
  else if (config.url?.startsWith("/products/")) data = products.find(p => config.url === `/products/${p.id}`);
  else if (config.url === "/marketing-tasks") data = [{ id: 31, product_id: Number(config.params?.product_id), target_regions: ["US"], platforms: ["tiktok"] }];
  else throw new Error(`Fixture does not implement ${method} ${config.url}`);
  return { data, status: 200, statusText: "OK", headers: {}, config };
};

function Fixture() {
  const [network, setNetwork] = useState(mode);
  const [revision, setRevision] = useState(0);
  const [stats, setStats] = useState("");
  const [page, setPage] = useState("商品中心");
  function select(next: string) { mode = next; setNetwork(next); }
  return <BrowserRouter><PresentationModeProvider>
    <aside style={{ padding: 20, background: "white", position: "sticky", top: 0, zIndex: 20 }}>
      <h1>隔离验收 · 不连接真实后台</h1>
      <p>模拟网络：{network}</p>
      <button onClick={() => select("offline")}>模拟所有读取失败</button>{" "}
      <button onClick={() => select("brand-failure")}>仅品牌读取失败</button>{" "}
      <button onClick={() => { select("slow"); window.dispatchEvent(new Event("online")); }}>模拟六秒慢读取</button>{" "}
      <button onClick={() => { select("healthy"); window.dispatchEvent(new Event("online")); }}>恢复连接并重新读取</button>{" "}
      <button onClick={() => setRevision(v => v + 1)}>重建页面测试首次读取</button>{" "}
      <button onClick={() => setStats(`读取 ${readCount} 次；写入 ${writeCount} 次`)}>显示请求统计</button>
      <p>{stats}</p>
      <nav>{["商品中心", "文案矩阵", "视频工厂"].map(name => <button key={name} onClick={() => setPage(name)}>{name}</button>)}</nav>
    </aside>
    <div key={revision}><SystemReadinessPanel /><main style={{ padding: 24 }}>{page === "商品中心" ? <ProductCenterPage /> : <h2>{page}（隔离测试占位页面）</h2>}</main></div>
  </PresentationModeProvider></BrowserRouter>;
}
createRoot(document.getElementById("root")!).render(<Fixture />);
