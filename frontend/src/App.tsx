import { lazy, Suspense } from "react";
import { Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { AircraftDetailPage } from "./pages/AircraftDetail";
import { CargoPage } from "./pages/Cargo";
import { HomePage } from "./pages/Home";
import { KnowledgeHubPage } from "./pages/KnowledgeHub";
import { LibraryPage } from "./pages/Library";
import { Loading } from "./components/ui";

// Chart-heavy pages are split into separate chunks.
const ComparePage = lazy(() => import("./pages/Compare").then((m) => ({ default: m.ComparePage })));
const FlightLabPage = lazy(() => import("./pages/FlightLab").then((m) => ({ default: m.FlightLabPage })));
const EconomicsPage = lazy(() => import("./pages/Economics").then((m) => ({ default: m.EconomicsPage })));

export function App() {
  return <Suspense fallback={<div className="mx-auto max-w-7xl px-6"><Loading /></div>}><Routes>
    <Route element={<Layout />}>
      <Route index element={<HomePage />} />
      <Route path="aircraft" element={<LibraryPage />} />
      <Route path="aircraft/:code" element={<AircraftDetailPage />} />
      <Route path="compare" element={<ComparePage />} />
      <Route path="cargo" element={<CargoPage />} />
      <Route path="flight-lab" element={<FlightLabPage />} />
      <Route path="learn" element={<KnowledgeHubPage />} />
      <Route path="economics" element={<EconomicsPage />} />
      <Route path="*" element={<div className="mx-auto max-w-3xl p-10">Page not found.</div>} />
    </Route>
  </Routes></Suspense>;
}
