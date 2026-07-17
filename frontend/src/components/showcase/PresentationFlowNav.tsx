import { NavLink } from "react-router-dom";

const journey = [
  {
    phase: "Understand",
    items: [{ number: "01", label: "Overview", to: "/", end: true }],
  },
  {
    phase: "Create",
    items: [
      { number: "02", label: "Copy Matrix", to: "/copy-matrix", end: false },
      { number: "03", label: "Video Blueprint", to: "/content-studio", end: false },
    ],
  },
  {
    phase: "Optimize",
    items: [{ number: "04", label: "Growth Copilot", to: "/growth-copilot", end: false }],
  },
];

export function PresentationFlowNav() {
  return (
    <nav className="presentation-flow-nav" aria-label="Demo Journey">
      <span className="presentation-flow-nav__title">Demo Journey</span>
      {journey.map((group, groupIndex) => (
        <div className="presentation-flow-nav__group" key={group.phase}>
          {groupIndex > 0 && <i aria-hidden="true">→</i>}
          <div>
            <small>{group.phase}</small>
            <div className="presentation-flow-nav__links">
              {group.items.map((item) => (
                <NavLink
                  className={({ isActive }) => `presentation-flow-nav__link${isActive ? " presentation-flow-nav__link--active" : ""}`}
                  end={item.end}
                  key={item.to}
                  to={{ pathname: item.to, search: "?mode=presentation" }}
                >
                  <em>{item.number}</em>
                  <strong>{item.label}</strong>
                </NavLink>
              ))}
            </div>
          </div>
        </div>
      ))}
    </nav>
  );
}
