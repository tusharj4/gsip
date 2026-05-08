import { Suspense } from "react";
import dynamic from "next/dynamic";

/**
 * Map page — loads MapLibre GL client-side only (browser APIs required).
 *
 * Wrapped in Suspense because MapContainer uses useSearchParams() to read
 * the optional ?project_id= query param. Next.js 14 App Router requires a
 * Suspense boundary for any component that calls useSearchParams().
 */
const MapContainer = dynamic(
  () => import("@/components/map/MapContainer"),
  {
    ssr: false,
    loading: () => (
      <div className="flex-1 flex items-center justify-center bg-gray-100">
        <div className="text-sm text-gray-400 animate-pulse">Loading map…</div>
      </div>
    ),
  }
);

export default function MapPage() {
  return (
    <div className="h-screen flex flex-col overflow-hidden">
      <header className="bg-brand-700 text-white px-4 py-2 flex items-center justify-between shrink-0 shadow">
        <div className="flex items-center gap-3">
          <span className="font-semibold text-sm">GSIP — Map View</span>
        </div>
        <nav className="flex items-center gap-4 text-xs text-brand-100">
          <a href="/projects" className="hover:text-white transition-colors">Projects</a>
          <a href="/analysis" className="hover:text-white transition-colors">Analysis</a>
          <a href="/reports" className="hover:text-white transition-colors">Reports</a>
          <a href="/" className="hover:text-white transition-colors">← Dashboard</a>
        </nav>
      </header>

      <div className="flex flex-1 overflow-hidden">
        {/* Suspense required for useSearchParams() in MapContainer */}
        <Suspense
          fallback={
            <div className="flex-1 flex items-center justify-center bg-gray-100">
              <div className="text-sm text-gray-400 animate-pulse">Loading map…</div>
            </div>
          }
        >
          <MapContainer />
        </Suspense>
      </div>
    </div>
  );
}
