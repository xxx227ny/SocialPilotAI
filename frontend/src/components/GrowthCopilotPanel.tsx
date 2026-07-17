import { useState } from "react";

import {
  generateGrowthAnalysis,
  uploadCampaignCsv,
} from "../api/growth";
import type { GrowthAnalysis } from "../types/growth";

interface GrowthCopilotPanelProps {
  productId: number;
}

export function GrowthCopilotPanel({ productId }: GrowthCopilotPanelProps) {
  const [file, setFile] = useState<File | null>(null);
  const [analysis, setAnalysis] = useState<GrowthAnalysis | null>(null);
  const [status, setStatus] = useState("");
  const [uploading, setUploading] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);

  async function handleUpload() {
    if (!file) {
      setStatus("请选择 CSV 文件。");
      return;
    }
    try {
      setUploading(true);
      setStatus("");
      const result = await uploadCampaignCsv(productId, file);
      setStatus(`已导入 ${result.imported_count} 条广告数据。`);
      setAnalysis(null);
    } catch {
      setStatus("CSV 导入失败，请检查字段、格式和数据范围。");
    } finally {
      setUploading(false);
    }
  }

  async function handleAnalyze() {
    try {
      setAnalyzing(true);
      setStatus("");
      setAnalysis(await generateGrowthAnalysis(productId));
    } catch {
      setStatus("分析失败，请先上传广告数据并生成营销分析。");
    } finally {
      setAnalyzing(false);
    }
  }

  return (
    <section className="growth-panel">
      <div className="growth-panel__header">
        <div>
          <span>GROWTH COPILOT</span>
          <strong>投流分析 MVP</strong>
        </div>
        <small>CSV 数据 · 聚合指标 · AI 建议</small>
      </div>
      <div className="growth-panel__controls">
        <label>
          <input
            accept=".csv,text/csv"
            type="file"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          />
          <span>{file?.name ?? "选择广告 CSV"}</span>
        </label>
        <button type="button" disabled={!file || uploading} onClick={handleUpload}>
          {uploading ? "导入中…" : "导入数据"}
        </button>
        <button
          className="growth-panel__analyze"
          type="button"
          disabled={analyzing}
          onClick={handleAnalyze}
        >
          {analyzing ? "分析中…" : "生成优化建议"}
        </button>
      </div>
      {status && <p className="growth-panel__status">{status}</p>}
      {analysis && (
        <div className="growth-result">
          <div className="growth-metrics">
            <Metric label="CTR" value={asPercent(analysis.metrics.ctr)} />
            <Metric
              label="CVR"
              value={asPercent(analysis.metrics.conversion_rate)}
            />
            <Metric label="CPA" value={asCurrency(analysis.metrics.cpa)} />
            <Metric label="ROAS" value={asRatio(analysis.metrics.roas)} />
          </div>
          <div className="growth-advice-grid">
            <Advice title="主要问题" items={analysis.recommendation.problems} />
            <Advice
              title="优化建议"
              items={analysis.recommendation.recommendations}
            />
            <Advice
              title="素材建议"
              items={analysis.recommendation.creative_suggestions}
            />
          </div>
          <div className="growth-budget">
            <small>预算建议</small>
            <p>{analysis.recommendation.budget_suggestion}</p>
          </div>
        </div>
      )}
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <small>{label}</small>
      <strong>{value}</strong>
    </div>
  );
}

function Advice({ title, items }: { title: string; items: string[] }) {
  return (
    <div>
      <strong>{title}</strong>
      <ul>
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

function asPercent(value: number) {
  return `${(value * 100).toFixed(2)}%`;
}

function asCurrency(value: number | null) {
  return value === null ? "—" : `$${value.toFixed(2)}`;
}

function asRatio(value: number | null) {
  return value === null ? "—" : `${value.toFixed(2)}x`;
}
