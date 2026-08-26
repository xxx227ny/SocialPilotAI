import { NavLink, Outlet, useNavigate } from "react-router-dom";

import { PresentationToolbar } from "../components/dashboard/PresentationToolbar";
import { PresentationFlowNav } from "../components/showcase/PresentationFlowNav";
import { SystemReadinessPanel } from "../components/system/SystemReadinessPanel";
import { usePresentationMode } from "../context/PresentationModeContext";
import { useAuth } from "../context/AuthContext";

const navItems = [
  { to: "/", label: "主页", icon: "⌂", end: true },
  { to: "/products", label: "商品中心", icon: "□" },
  { to: "/copy-matrix", label: "文案矩阵", icon: "✦" },
  { to: "/content-studio", label: "视频工厂", icon: "▶" },
  { to: "/growth-copilot", label: "投流优化", icon: "↗" },
];

export function AppLayout() {
  const { isPresentation } = usePresentationMode();
  const { enabled: authEnabled, logout, username } = useAuth();
  const navigate = useNavigate();

  const handleLogout = async () => {
    await logout();
    navigate("/", { replace: true });
  };

  return (
    <div className={`app-shell${isPresentation ? " app-shell--presentation" : ""}`}>
      {!isPresentation && <aside className="sidebar">
        <div className="brand">
          <span className="brand__mark">S</span>
          <div>
            <strong>SocialPilot</strong>
            <small>智能营销增长系统</small>
          </div>
        </div>

        <nav className="nav" aria-label="主要导航">
          <span className="nav__label">工作台</span>
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `nav__item${isActive ? " nav__item--active" : ""}`
              }
            >
              <span className="nav__icon" aria-hidden="true">{item.icon}</span>
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="sidebar__footer">
          <div className="sidebar__badge">黑客松</div>
          <p>跨境营销增长引擎</p>
          <small>阶段 09 · 演示就绪</small>
        </div>
      </aside>}

      <div className="workspace">
        {!isPresentation && <header className="topbar">
          <div>
            <strong>SocialPilot AI</strong>
            <span>跨境电商社媒营销增长平台</span>
          </div>
          <div className="topbar__right">
            <span className="phase-pill">黑客松演示</span>
            <PresentationToolbar />
            {authEnabled && <div className="account-menu">
              <span className="avatar" aria-hidden="true">SP</span>
              <span className="account-menu__name">{username}</span>
              <button type="button" onClick={handleLogout}>退出登录</button>
            </div>}
            {!authEnabled && <span className="avatar">SP</span>}
          </div>
        </header>}
        {isPresentation && <>
          <PresentationFlowNav />
          <PresentationToolbar />
        </>}
        {!isPresentation && <SystemReadinessPanel />}
        <main className="main-content">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
