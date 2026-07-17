import { usePresentationMode } from "../../context/PresentationModeContext";

export function PresentationToolbar() {
  const { isPresentation, togglePresentation } = usePresentationMode();

  return (
    <div className={`presentation-toolbar${isPresentation ? " presentation-toolbar--active" : ""}`}>
      {isPresentation && <span>SocialPilot AI · 比赛演示模式</span>}
      <button type="button" onClick={togglePresentation}>
        {isPresentation ? "退出演示（ESC）" : "进入演示"}
      </button>
    </div>
  );
}
