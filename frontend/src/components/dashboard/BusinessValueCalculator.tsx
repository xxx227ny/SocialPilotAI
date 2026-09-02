import { useMemo, useState } from "react";

type CalculatorInputProps = {
  label: string;
  value: number;
  min: number;
  max: number;
  suffix: string;
  onChange: (value: number) => void;
};

export function BusinessValueCalculator() {
  const [campaigns, setCampaigns] = useState(4);
  const [platforms, setPlatforms] = useState(3);
  const [assetsPerPlatform, setAssetsPerPlatform] = useState(4);
  const [manualMinutes, setManualMinutes] = useState(90);
  const [assistedMinutes, setAssistedMinutes] = useState(30);
  const [hourlyCost, setHourlyCost] = useState(80);

  const result = useMemo(() => {
    const deliverables = campaigns * platforms * assetsPerPlatform;
    const manualHours = (deliverables * manualMinutes) / 60;
    const assistedHours = (deliverables * assistedMinutes) / 60;
    const hoursSaved = Math.max(0, manualHours - assistedHours);
    const efficiency = manualHours > 0 ? (hoursSaved / manualHours) * 100 : 0;
    return {
      deliverables,
      manualHours,
      assistedHours,
      hoursSaved,
      efficiency,
      laborSaved: hoursSaved * hourlyCost,
    };
  }, [assetsPerPlatform, assistedMinutes, campaigns, hourlyCost, manualMinutes, platforms]);

  return (
    <section className="business-value" aria-labelledby="business-value-title">
      <header>
        <div>
          <span>业务价值测算</span>
          <h2 id="business-value-title">把内容生产效率换算成时间与人力成本</h2>
          <p>按团队自己的工作量和工时填写。结果仅为透明公式测算，不冒充真实客户成效。</p>
        </div>
        <strong>所有计算均在浏览器本地完成</strong>
      </header>

      <div className="business-value__body">
        <form className="business-value__inputs" onSubmit={(event) => event.preventDefault()}>
          <CalculatorInput label="每月商品 / 活动数" value={campaigns} min={1} max={100} suffix="个" onChange={setCampaigns} />
          <CalculatorInput label="覆盖平台数" value={platforms} min={1} max={5} suffix="个平台" onChange={setPlatforms} />
          <CalculatorInput label="每个平台内容数" value={assetsPerPlatform} min={1} max={30} suffix="条" onChange={setAssetsPerPlatform} />
          <CalculatorInput label="传统单条制作时间" value={manualMinutes} min={5} max={600} suffix="分钟" onChange={setManualMinutes} />
          <CalculatorInput label="AI 辅助单条时间" value={assistedMinutes} min={1} max={600} suffix="分钟" onChange={setAssistedMinutes} />
          <CalculatorInput label="综合人力成本" value={hourlyCost} min={0} max={2000} suffix="元 / 小时" onChange={setHourlyCost} />
        </form>

        <div className="business-value__results" aria-live="polite">
          <div><span>月度内容产出</span><strong>{integer(result.deliverables)} 条</strong></div>
          <div><span>预计节省工时</span><strong>{decimal(result.hoursSaved)} 小时</strong></div>
          <div><span>制作时间降幅</span><strong>{decimal(result.efficiency)}%</strong></div>
          <div><span>预计节省人力成本</span><strong>¥{integer(result.laborSaved)}</strong></div>
          <p>
            传统流程约 {decimal(result.manualHours)} 小时，AI 辅助流程约 {decimal(result.assistedHours)} 小时。
            实际结果受素材质量、审核轮次、模型价格和团队流程影响。
          </p>
        </div>
      </div>

      <ol className="business-value__story">
        <li><span>01</span><div><strong>目标用户</strong><p>跨境电商中小团队、独立站卖家与社媒运营人员。</p></div></li>
        <li><span>02</span><div><strong>核心痛点</strong><p>同一商品要重复改写多平台文案、制作竖版视频并分散查看投放反馈。</p></div></li>
        <li><span>03</span><div><strong>落地方式</strong><p>用户注册独立工作区、绑定自己的百炼 Key，再从商品资料进入文案、视频与增长闭环。</p></div></li>
        <li><span>04</span><div><strong>可规模化</strong><p>按工作区隔离账号、数据与成本，平台只提供工作流和安全执行能力。</p></div></li>
      </ol>
    </section>
  );
}

function CalculatorInput({ label, value, min, max, suffix, onChange }: CalculatorInputProps) {
  return (
    <label>
      <span>{label}</span>
      <span className="business-value__input">
        <input
          type="number"
          value={value}
          min={min}
          max={max}
          onChange={(event) => onChange(clamp(Number(event.target.value), min, max))}
        />
        <small>{suffix}</small>
      </span>
    </label>
  );
}

function clamp(value: number, min: number, max: number) {
  if (!Number.isFinite(value)) return min;
  return Math.min(max, Math.max(min, value));
}

function integer(value: number) {
  return new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 0 }).format(value);
}

function decimal(value: number) {
  return new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 1 }).format(value);
}
