"use client";

import dynamic from "next/dynamic";

// MapLibre GL requires browser APIs — load client-side only
const MapContainer = dynamic(
  () => import("@/components/map/MapContainer"),
  { ssr: false, loading: () => <div className="flex-1 bg-gray-200 animate-pulse" /> }
);

export default function MapPage() {
  return (
    <div className="h-screen flex flex-col overflow-hidden">
      <header className="bg-brand-700 text-white px-4 py-2 flex items-center justify-between shrink-0">
        <span className="font-semibold text-sm">GSIP — Map View</span>
        <a href="/" className="text-xs text-brand-100 hover:text-white">← Dashboard</a>
      </header>
      <div className="flex flex-1 overflow-hidden">
        <MapContainer />
      </div>
    </div>
  );
}
