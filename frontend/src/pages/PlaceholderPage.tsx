interface PlaceholderPageProps {
  eyebrow: string;
  title: string;
  description: string;
  icon: string;
}

export function PlaceholderPage({
  eyebrow,
  title,
  description,
  icon,
}: PlaceholderPageProps) {
  return (
    <section className="placeholder-page">
      <div className="placeholder-page__icon">{icon}</div>
      <span>{eyebrow}</span>
      <h1>{title}</h1>
      <p>{description}</p>
      <div className="placeholder-page__notice">
        <strong>模块底座已预留</strong>
        <span>业务功能将在下一阶段逐步开放</span>
      </div>
    </section>
  );
}
