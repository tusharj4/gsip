"use client";

import { useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import type { GapAnalysisResult } from "@/lib/types";

// Surendranagar district approximate bbox — used as demo
const DEMO_BBOX = {
  type: "Polygon",
  coordinates: [[[71.2, 22.5], [72.5, 22.5], [72.5, 23.5], [71.2, 23.5], [71.2, 22.5]]],
};

const SERVICE_INFO: Record<string, { icon: string; desc: string; popUnit: number; radius: string }> = {
  anganwadi: { icon: "👶", desc: "Child development centres", popUnit: 800, radius: "1 km" },
  hospital:  { icon: "🏥", desc: "Hospitals and health centres", popUnit: 50_000, radius: "10 km" },
  school:    { icon: "🏫", desc: "Primary and secondary schools", popUnit: 1_000, radius: "2 km" },
  water:     { icon: "💧", desc: "Water supply points", popUnit: 5_000, radius: "500 m" },
};

export default function AnalysisPage() {
  const [analysisType, setAnalysisType] = useState("anganwadi");
  const [population, setPopulation] = useState<string>("459200");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<GapAnalysisResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const runAnalysis = async () => {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const resp = await api.post<GapAnalysisResult>("/api/v1/analysis/gaps", {
        geography_geojson: DEMO_BBOX,
        analysis_type: analysisType,
        population: parseInt(population) || undefined,
      });
      setResult(resp.data);
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg ?? "Analysis failed");
    } finally {
      setLoading(false);
    }
  };

  const info = SERVICE_INFO[analysisType];

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-brand-700 text-white px-6 py-3 flex items-center justify-between">
        <h1 className="font-semibold">Service Gap Analysis</h1>
        <div className="flex gap-3">
          <Link href="/" className="text-xs text-brand-100 hover:text-white">← Dashboard</Link>
          <Link href="/map" className="text-xs text-brand-100 hover:text-white">Map View</Link>
        </div>
      </header>

      <main className="max-w-4xl mx-auto px-6 py-8">
        {/* Configuration panel */}
        <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm mb-6">
          <h2 className="font-semibold text-brand-700 mb-4">Configure Analysis</h2>

          {/* Service type selector */}
          <div className="grid grid-cols-4 gap-3 mb-6">
            {Object.entries(SERVICE_INFO).map(([key, { icon, desc }]) => (
              <button
                key={key}
                onClick={() => setAnalysisType(key)}
                className={`p-3 rounded-xl border-2 text-left transition-all ${
                  analysisType === key
                    ? "border-brand-500 bg-brand-50"
                    : "border-gray-200 hover:border-brand-200"
                }`}
              >
                <div className="text-2xl mb-1">{icon}</div>
                <div className="text-xs font-semibold capitalize text-gray-800">{key}</div>
                <div className="text-xs text-gray-500">{desc}</div>
              </button>
            ))}
          </div>

          {/* Service info */}
          <div className="bg-blue-50 rounded-lg p-3 mb-4 text-sm text-blue-800">
            <strong>{info.icon} {analysisType.charAt(0).toUpperCase() + analysisType.slice(1)}</strong>:
            1 facility per {info.popUnit.toLocaleString()} population · Service radius: {info.radius}
          </div>

          {/* Population input */}
          <div className="flex gap-4 items-end">
            <div className="flex-1">
              <label className="block text-xs font-medium text-gray-600 mb-1">
                Study Area Population
              </label>
              <input
                type="number"
                value={population}
                onChange={(e) => setPopulation(e.target.value)}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
                placeholder="e.g. 459200 (Surendranagar district)"
              />
              <p className="text-xs text-gray-400 mt-1">
                Demo uses Surendranagar district bbox (Gujarat). Draw custom area on{" "}
                <Link href="/map" className="text-brand-500 underline">Map</Link>.
              </p>
            </div>
            <button
              onClick={runAnalysis}
              disabled={loading}
              className="bg-brand-500 hover:bg-brand-700 disabled:opacity-50 text-white font-medium px-6 py-2 rounded-lg text-sm"
            >
              {loading ? "Analysing…" : "Run Analysis"}
            </button>
          </div>
        </div>

        {error && (
          <div className="bg-red-50 border border-red-200 rounded-xl p-4 text-sm text-red-700">{error}</div>
        )}

        {/* Results */}
        {result && (
          <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
            <div className="bg-brand-700 text-white px-6 py-4">
              <h2 className="font-semibold text-lg">
                {info.icon} {analysisType.charAt(0).toUpperCase() + analysisType.slice(1)} Gap Analysis Results
              </h2>
            </div>

            {/* Key metrics */}
            <div className="grid grid-cols-4 divide-x divide-gray-100 border-b border-gray-100">
              {[
                { label: "Population", value: result.population?.toLocaleString() ?? "—" },
                { label: "Required", value: result.required_count ?? "—", note: "facilities needed" },
                { label: "Existing", value: result.existing_count ?? "—", note: "in area" },
                {
                  label: "Gap",
                  value: result.gap_count ?? "—",
                  note: "to be built",
                  highlight: (result.gap_count ?? 0) > 0,
                },
              ].map(({ label, value, note, highlight }) => (
                <div key={label} className="p-5 text-center">
                  <div className={`text-3xl font-bold ${highlight ? "text-red-600" : "text-brand-700"}`}>
                    {value}
                  </div>
                  <div className="text-xs font-medium text-gray-600 mt-1">{label}</div>
                  {note && <div className="text-xs text-gray-400">{note}</div>}
                </div>
              ))}
            </div>

            {/* Parameters */}
            <div className="px-6 py-4 bg-gray-50 text-xs text-gray-500">
              <strong>Parameters:</strong>{" "}
              {Object.entries(result.parameters)
                .map(([k, v]) => `${k.replace(/_/g, " ")}: ${v}`)
                .join(" · ")}
            </div>

            {/* Action */}
            {(result.gap_count ?? 0) > 0 && (
              <div className="px-6 py-4 border-t border-gray-100">
                <p className="text-sm text-gray-700">
                  <strong>{result.gap_count}</strong> additional {analysisType} facilities are needed
                  in this area. View the uncovered zones on the map to identify candidate sites.
                </p>
                <Link
                  href="/map"
                  className="inline-block mt-3 text-sm bg-brand-500 text-white px-4 py-2 rounded-lg hover:bg-brand-700"
                >
                  View on Map
                </Link>
              </div>
            )}
          </div>
        )}
      </main>
    </div>
  );
}
