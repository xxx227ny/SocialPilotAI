import { Navigate, Route, Routes } from "react-router-dom";

import { AppLayout } from "./layouts/AppLayout";
import { DashboardPage } from "./pages/DashboardPage";
import { ContentStudioPage } from "./pages/ContentStudioPage";
import { CopyMatrixPage } from "./pages/CopyMatrixPage";
import { GrowthCopilotPage } from "./pages/GrowthCopilotPage";
import { ProductCenterPage } from "./pages/ProductCenterPage";

export default function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={<DashboardPage />} />
        <Route path="products" element={<ProductCenterPage />} />
        <Route path="copy-matrix" element={<CopyMatrixPage />} />
        <Route path="content-studio" element={<ContentStudioPage />} />
        <Route path="growth-copilot" element={<GrowthCopilotPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
