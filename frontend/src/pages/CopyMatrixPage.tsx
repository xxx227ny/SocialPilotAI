import { DemoContextBar } from "../components/showcase/DemoContextBar";
import { useDemoSnapshot } from "../hooks/useDemoSnapshot";
import type { PlatformCopy } from "../types/copy";

const platformDetails: Record<PlatformCopy["platform"], { number: string; traits: string[]; approach: string; logic: string[] }> = {
  TikTok: { number: "01", traits: ["UGC", "短视频", "情绪驱动"], approach: "短视频情绪驱动", logic: ["Hook 优先", "UGC 表达", "快速转化"] },
  Instagram: { number: "02", traits: ["Lifestyle", "品牌感", "视觉表达"], approach: "生活方式表达", logic: ["视觉美学", "品牌塑造"] },
  Facebook: { number: "03", traits: ["功能价值", "购买理由"], approach: "功能价值表达", logic: ["信息完整", "购买决策"] },
};

export function CopyMatrixPage() {
  const { snapshot, loading, error } = useDemoSnapshot();

  return (
    <div className="competition-page copy-showcase-page">
      <DemoContextBar />
      <PageHero
        eyebrow="COPY MATRIX"
        title="AI 社媒文案矩阵"
        subtitle="同一商品策略，自动适配不同社媒平台表达"
      />
      {loading ? (
        <PageState title="正在读取文案快照" detail="只读取预置内容，不触发文案生成。" />
      ) : snapshot ? (
        <>
          <section className="copy-strategy-summary">
            <div className="copy-strategy-summary__product">
              <span>DEMO PRODUCT</span>
              <h2>{snapshot.product.name.replace(" Demo", "")}</h2>
              <p>{snapshot.product.description}</p>
            </div>
            <StrategyFact title="市场定位" content={snapshot.strategy?.positioning ?? "暂无定位快照"} />
            <StrategyFact title="用户洞察" content={snapshot.strategy?.audience_insights[0] ?? "暂无用户洞察"} />
            <StrategyFact title="营销角度" content={snapshot.strategy?.angles[0] ?? "暂无营销角度"} />
          </section>

          <section className="content-strategy-focus" aria-label="商品内容策略主线">
            <div>
              <span>PRODUCT STORY → CONTENT</span>
              <h2>这个商品的内容策略围绕</h2>
              <p>从商品卖点和 Demo 用户场景中提炼统一内容主线，再适配不同平台表达。</p>
            </div>
            <ul>
              <li><span>01</span><strong>便携</strong><small>突出随身使用与低门槛</small></li>
              <li><span>02</span><strong>移动生活</strong><small>连接通勤、办公与运动场景</small></li>
              <li><span>03</span><strong>快速准备</strong><small>用更短路径呈现产品价值</small></li>
            </ul>
          </section>

          {snapshot.copy_matrix ? (
            <section className="copy-showcase-grid" aria-label="三平台文案矩阵">
              {snapshot.copy_matrix.copies.map((copy) => <PlatformCopyCard copy={copy} key={copy.platform} />)}
            </section>
          ) : (
            <PageState title="文案矩阵暂缺" detail="当前 Snapshot 中没有可展示的多平台文案。" />
          )}

          <section className="adaptation-logic">
            <header><span>PLATFORM ADAPTATION</span><h2>平台适配逻辑</h2></header>
            <div>
              <LogicStep number="01" title="同一商品策略" detail="统一定位、受众与核心卖点" />
              <i>↓</i>
              <LogicStep number="02" title="不同平台用户习惯" detail="理解内容节奏与购买决策方式" />
              <i>↓</i>
              <LogicStep number="03" title="不同内容表达" detail="生成适合平台语境的 Hook、Caption 与 CTA" />
            </div>
          </section>
        </>
      ) : (
        <PageState title="演示快照未就绪" detail={error} error />
      )}
    </div>
  );
}

function PlatformCopyCard({ copy }: { copy: PlatformCopy }) {
  const details = platformDetails[copy.platform];
  return (
    <article className="platform-copy-showcase">
      <header>
        <span>{details.number}</span>
        <div><small>SOCIAL CHANNEL</small><h2>{copy.platform}</h2></div>
        <div className="platform-copy-showcase__traits">{details.traits.map((trait) => <em key={trait}>{trait}</em>)}</div>
      </header>
      <CopySection label="HOOK" content={copy.hook} featured />
      <CopySection label="CAPTION" content={copy.caption} />
      <div className="copy-showcase-hashtags"><small>HASHTAGS</small><div>{copy.hashtags.map((tag) => <span key={tag}>{tag}</span>)}</div></div>
      <CopySection label="CALL TO ACTION" content={copy.cta} action />
      <div className="platform-copy-showcase__logic">
        <small>AI 平台适配逻辑</small>
        <strong>{details.approach}</strong>
        <ul>{details.logic.map((item) => <li key={item}>{item}</li>)}</ul>
      </div>
    </article>
  );
}

function CopySection({ label, content, featured = false, action = false }: { label: string; content: string; featured?: boolean; action?: boolean }) {
  return <div className={`copy-showcase-field${featured ? " copy-showcase-field--featured" : ""}${action ? " copy-showcase-field--action" : ""}`}><small>{label}</small><p>{content}</p></div>;
}

function StrategyFact({ title, content }: { title: string; content: string }) {
  return <div className="strategy-fact"><small>{title}</small><p>{content}</p></div>;
}

function LogicStep({ number, title, detail }: { number: string; title: string; detail: string }) {
  return <article><span>{number}</span><strong>{title}</strong><p>{detail}</p></article>;
}

function PageHero({ eyebrow, title, subtitle }: { eyebrow: string; title: string; subtitle: string }) {
  return <header className="competition-hero"><div><span>{eyebrow}</span><h1>{title}</h1><p>{subtitle}</p></div><div className="readonly-badge"><strong>Demo Snapshot</strong><span>只读展示</span></div></header>;
}

function PageState({ title, detail, error = false }: { title: string; detail: string; error?: boolean }) {
  return <section className={`competition-state${error ? " competition-state--error" : ""}`}><span>{error ? "!" : "…"}</span><strong>{title}</strong><p>{detail}</p></section>;
}
