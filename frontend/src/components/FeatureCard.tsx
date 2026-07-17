interface FeatureCardProps {
  eyebrow: string;
  title: string;
  description: string;
  accent: "violet" | "blue" | "orange";
  icon: string;
}

export function FeatureCard({
  eyebrow,
  title,
  description,
  accent,
  icon,
}: FeatureCardProps) {
  return (
    <article className={`feature-card feature-card--${accent}`}>
      <div className="feature-card__top">
        <span className="feature-card__icon" aria-hidden="true">
          {icon}
        </span>
        <span className="feature-card__eyebrow">{eyebrow}</span>
      </div>
      <h3>{title}</h3>
      <p>{description}</p>
      <div className="feature-card__status">
        <span /> 基础架构已就绪
      </div>
    </article>
  );
}
