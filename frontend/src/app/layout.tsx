import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "GatiShakti Intelligence Platform",
  description:
    "Geospatial decision support system for India's infrastructure planning — conflict detection, gap analysis, route optimization.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-gray-50 text-gray-900 antialiased">{children}</body>
    </html>
  );
}
