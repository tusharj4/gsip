import type { Metadata } from "next";
import "./globals.css";
import { AuthProvider } from "@/contexts/AuthContext";

// MapLibre GL CSS — served as a static file from /public/vendor/ to avoid
// webpack alias conflicts. The file is committed to the repo at
// frontend/public/vendor/maplibre-gl.css (copied from node_modules at build time).
const MAPLIBRE_CSS = "/vendor/maplibre-gl.css";

export const metadata: Metadata = {
  title: "GatiShakti Intelligence Platform",
  description:
    "Geospatial decision support system for India's infrastructure planning — conflict detection, gap analysis, route optimization.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="stylesheet" href={MAPLIBRE_CSS} />
      </head>
      <body className="bg-gray-50 text-gray-900 antialiased">
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
