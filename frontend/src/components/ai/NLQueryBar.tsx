"use client";

import { useState, type FormEvent } from "react";
import maplibregl from "maplibre-gl";
import { api } from "@/lib/api";
import type { NLQueryResponse } from "@/lib/types";

interface Props {
  map: maplibregl.Map;
}

export default function NLQueryBar({ map }: Props) {
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<NLQueryResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!question.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);

    try {
      const resp = await api.post<NLQueryResponse>("/api/v1/ai/query", { question });
      setResult(resp.data);

      // Render GeoJSON results on map
      if (resp.data.geojson && resp.data.geojson.features.length > 0) {
        const srcId = "ai-query-result";
        const layerId = "ai-query-fill";
        // Cast to GeoJSON.FeatureCollection — the API guarantees well-formed GeoJSON
        const fc = resp.data.geojson as unknown as GeoJSON.FeatureCollection;
        if (map.getSource(srcId)) {
          (map.getSource(srcId) as maplibregl.GeoJSONSource).setData(fc);
        } else {
          map.addSource(srcId, { type: "geojson", data: fc });
          map.addLayer({
            id: layerId,
            type: "circle",
            source: srcId,
            paint: { "circle-color": "#6366f1", "circle-radius": 6, "circle-opacity": 0.8 },
          });
        }
      }
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg ?? "Query failed. Try rephrasing your question.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="bg-white rounded-2xl shadow-2xl border border-gray-200 overflow-hidden">
      <form onSubmit={submit} className="flex items-center gap-2 px-4 py-3">
        <span className="text-purple-600 text-lg shrink-0">✨</span>
        <input
          type="text"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder='Ask anything, e.g. "How many hospitals within 10km of NH48 in Gujarat?"'
          className="flex-1 text-sm outline-none text-gray-800 placeholder-gray-400"
          disabled={loading}
        />
        <button
          type="submit"
          disabled={loading || !question.trim()}
          className="bg-purple-600 hover:bg-purple-700 disabled:opacity-50 text-white text-sm font-medium px-4 py-1.5 rounded-lg transition-colors shrink-0"
        >
          {loading ? "…" : "Ask"}
        </button>
      </form>

      {error && (
        <div className="px-4 pb-3 text-xs text-red-600">{error}</div>
      )}

      {result && !error && (
        <div className="border-t border-gray-100 px-4 py-3">
          <p className="text-xs text-gray-500 mb-1">
            {result.row_count} result{result.row_count !== 1 ? "s" : ""} · {result.execution_ms.toFixed(0)}ms
          </p>
          {result.result_type === "scalar" && result.scalar !== null && (
            <p className="text-2xl font-bold text-brand-700">{String(result.scalar)}</p>
          )}
          {result.result_type === "table" && result.rows && result.rows.length > 0 && (
            <div className="overflow-x-auto">
              <table className="text-xs w-full">
                <thead>
                  <tr>
                    {Object.keys(result.rows[0]).map((k) => (
                      <th key={k} className="text-left text-gray-500 font-medium pb-1 pr-3">{k}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {result.rows.slice(0, 10).map((row, i) => (
                    <tr key={i}>
                      {Object.values(row).map((v, j) => (
                        <td key={j} className="text-gray-800 pr-3 py-0.5">{String(v ?? "—")}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
              {result.row_count > 10 && (
                <p className="text-xs text-gray-400 mt-1">+ {result.row_count - 10} more rows</p>
              )}
            </div>
          )}
          {result.result_type === "geojson" && (
            <p className="text-xs text-green-600 font-medium">
              {result.row_count} features plotted on map
            </p>
          )}
          <details className="mt-2">
            <summary className="text-xs text-gray-400 cursor-pointer hover:text-gray-600">
              View SQL
            </summary>
            <pre className="text-xs bg-gray-50 rounded p-2 mt-1 overflow-x-auto text-gray-700 font-mono">
              {result.sql}
            </pre>
          </details>
        </div>
      )}
    </div>
  );
}
