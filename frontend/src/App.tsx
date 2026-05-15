import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import AppShell from "./components/layout/AppShell";
import CropWorkspace from "./components/crop/CropWorkspace";
import MinWidthGuard from "./components/layout/MinWidthGuard";

export default function App() {
  return (
    <MinWidthGuard>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<AppShell />} />
          <Route path="/crop-tool" element={<CropWorkspace />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </MinWidthGuard>
  );
}