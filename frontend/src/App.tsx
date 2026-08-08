import { Navigate, Route, Routes, useLocation } from "react-router-dom";

import { usePresentationMode } from "./context/PresentationModeContext";
import { AppLayout } from "./layouts/AppLayout";
import { DashboardPage } from "./pages/DashboardPage";
import { ContentStudioPage } from "./pages/ContentStudioPage";
import { CopyMatrixPage } from "./pages/CopyMatrixPage";
import { GrowthCopilotPage } from "./pages/GrowthCopilotPage";
import { ProductCenterPage } from "./pages/ProductCenterPage";
import { SnapshotPresentationPage } from "./pages/SnapshotPresentationPage";
import { parseSnapshotPresentationRoute } from "./components/presentation/snapshotPresentationState";

export default function App() {
  const location = useLocation();
  const snapshotRoute = parseSnapshotPresentationRoute(location.search);
  if (snapshotRoute.kind !== "legacy") {
    return <SnapshotPresentationPage route={snapshotRoute} />;
  }
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={<DashboardPage />} />
        <Route path="products" element={<ProductCenterRoute />} />
        <Route path="copy-matrix" element={<CopyMatrixPage />} />
        <Route path="content-studio" element={<ContentStudioPage />} />
        <Route path="growth-copilot" element={<GrowthCopilotPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}

function ProductCenterRoute() {
  const { isPresentation } = usePresentationMode();
  return isPresentation ? (
    <Navigate to="/?mode=presentation" replace />
  ) : (
    <ProductCenterPage />
  );
}
