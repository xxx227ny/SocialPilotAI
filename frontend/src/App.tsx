import { lazy, Suspense } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";

import { usePresentationMode } from "./context/PresentationModeContext";
import { useAuth } from "./context/AuthContext";
import { AppLayout } from "./layouts/AppLayout";
import { LoginPage } from "./pages/LoginPage";
import { parseSnapshotPresentationRoute } from "./components/presentation/snapshotPresentationState";

const DashboardPage = lazy(() =>
  import("./pages/DashboardPage").then((module) => ({ default: module.DashboardPage })),
);
const ContentStudioPage = lazy(() =>
  import("./pages/ContentStudioPage").then((module) => ({ default: module.ContentStudioPage })),
);
const CopyMatrixPage = lazy(() =>
  import("./pages/CopyMatrixPage").then((module) => ({ default: module.CopyMatrixPage })),
);
const GrowthCopilotPage = lazy(() =>
  import("./pages/GrowthCopilotPage").then((module) => ({ default: module.GrowthCopilotPage })),
);
const ProductCenterPage = lazy(() =>
  import("./pages/ProductCenterPage").then((module) => ({ default: module.ProductCenterPage })),
);
const SnapshotPresentationPage = lazy(() =>
  import("./pages/SnapshotPresentationPage").then((module) => ({ default: module.SnapshotPresentationPage })),
);
const ApiKeySettingsPage = lazy(() =>
  import("./pages/ApiKeySettingsPage").then((module) => ({ default: module.ApiKeySettingsPage })),
);
const AccountSecurityPage = lazy(() =>
  import("./pages/AccountSecurityPage").then((module) => ({ default: module.AccountSecurityPage })),
);
const SocialAccountsPage = lazy(() =>
  import("./pages/SocialAccountsPage").then((module) => ({ default: module.SocialAccountsPage })),
);

export default function App() {
  const {
    authenticated,
    checking,
    emailVerified,
    emailVerificationRequired,
  } = useAuth();
  const location = useLocation();
  if (checking) {
    return <main className="auth-loading" aria-live="polite">正在检查登录状态…</main>;
  }
  const accountAction = new URLSearchParams(location.search).get("action");
  if (accountAction === "reset-password" || accountAction === "verify-email") {
    return <LoginPage />;
  }
  if (!authenticated) {
    return <LoginPage />;
  }
  if (
    emailVerificationRequired
    && !emailVerified
    && location.pathname !== "/settings/account-security"
  ) {
    return <Navigate to="/settings/account-security" replace />;
  }
  const snapshotRoute = parseSnapshotPresentationRoute(location.search);
  if (snapshotRoute.kind !== "legacy") {
    return (
      <Suspense fallback={<PageLoading />}>
        <SnapshotPresentationPage route={snapshotRoute} />
      </Suspense>
    );
  }
  return (
    <Suspense fallback={<PageLoading />}>
      <Routes>
        <Route element={<AppLayout />}>
          <Route index element={<DashboardPage />} />
          <Route path="products" element={<ProductCenterRoute />} />
          <Route path="copy-matrix" element={<CopyMatrixPage />} />
          <Route path="content-studio" element={<ContentStudioPage />} />
          <Route path="growth-copilot" element={<GrowthCopilotPage />} />
          <Route path="settings/api-key" element={<ApiKeySettingsPage />} />
          <Route path="settings/social-accounts" element={<SocialAccountsPage />} />
          <Route path="settings/account-security" element={<AccountSecurityPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </Suspense>
  );
}

function PageLoading() {
  return <main className="auth-loading" aria-live="polite">正在加载当前功能…</main>;
}

function ProductCenterRoute() {
  const { isPresentation } = usePresentationMode();
  return isPresentation ? (
    <Navigate to="/?mode=presentation" replace />
  ) : (
    <ProductCenterPage />
  );
}
