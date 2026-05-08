"use client";

import { useEffect, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import { api } from "@/lib/api";
import type { ConflictReport } from "@/lib/types";

interface Props {
  map: maplibregl.Map;
}

type DrawMode = "idle" | "drawing" | "done";

export default function DrawTool({ map }: Props) {
  const [mode, setMode] = useState<DrawMode>("idle");
  const [conflicts, setConflicts] = useState<ConflictReport[]>([]);
  const [loading, setLoading] = useState(false);
  const [projectId, setProjectId] = useState<string | null>(null);
  const pointsRef = useRef<[number, number][]>([]);

  useEffect(() => {
    if (mode !== "drawing") return;

    const onClick = (e: maplibregl.MapMouseEvent) => {
      pointsRef.current.push([e.lngLat.lng, e.lngLat.lat]);
      // Preview line as we draw
      updateDrawPreview();
    };

    const onDblClick = (e: maplibregl.MapMouseEvent) => {
      e.preventDefault();
      if (pointsRef.current.length < 2) return;
      setMode("done");
      finaliseCorridor();
    };

    map.on("click", onClick);
    map.on("dblclick", onDblClick);
    map.getCanvas().style.cursor = "crosshair";

    return () => {
      map.off("click", onClick);
      map.off("dblclick", onDblClick);
      map.getCanvas().style.cursor = "";
    };
  }, [mode, map]);

  const updateDrawPreview = () => {
    const coords = pointsRef.current;
    if (coords.length < 2) return;
    const geojson: GeoJSON.FeatureCollection = {
      type: "FeatureCollection",
      features: [{ type: "Feature", geometry: { type: "LineString", coordinates: coords }, properties: {} }],
    };
    if (map.getSource("draw-preview")) {
      (map.getSource("draw-preview") as maplibregl.GeoJSONSource).setData(geojson);
    } else {
      map.addSource("draw-preview", { type: "geojson", data: geojson });
      map.addLayer({
        id: "draw-preview-line",
        type: "line",
        source: "draw-preview",
        paint: { "line-color": "#f59e0b", "line-width": 3, "line-dasharray": [2, 2] },
      });
    }
  };

  const finaliseCorridor = async () => {
    const coords = pointsRef.current;
    if (coords.length < 2) return;
    setLoading(true);
    try {
      // Create project with the drawn corridor
      const projResp = await api.post<{ id: string }>("/api/v1/projects/", {
        name: `Corridor drawn ${new Date().toLocaleString()}`,
        project_type: "road",
        corridor_geojson: { type: "LineString", coordinates: coords },
        buffer_m: 500,
      });
      const pid = projResp.data.id;
      setProjectId(pid);

      // Run conflict detection
      const conflictResp = await api.post<ConflictReport[]>("/api/v1/analysis/conflicts", {
        project_id: pid,
        buffer_m: 500,
      });
      setConflicts(conflictResp.data);

      // Visualise conflict zones on map
      addConflictLayer(conflictResp.data);
    } catch (err) {
      console.error("Conflict detection failed:", err);
    } finally {
      setLoading(false);
    }
  };

  const addConflictLayer = (reports: ConflictReport[]) => {
    const severityColour: Record<string, string> = {
      blocker: "#ff4d4d",
      high: "#ff9933",
      medium: "#ffcc00",
      low: "#90ee90",
    };
    const features = reports
      .filter((r) => r.conflict_geojson)
      .map((r) => ({
        type: "Feature" as const,
        geometry: r.conflict_geojson!,
        properties: { severity: r.severity, conflict_type: r.conflict_type },
      }));
    const geojson: GeoJSON.FeatureCollection = { type: "FeatureCollection", features };

    if (map.getSource("conflicts")) {
      (map.getSource("conflicts") as maplibregl.GeoJSONSource).setData(geojson);
    } else {
      map.addSource("conflicts", { type: "geojson", data: geojson });
      map.addLayer({
        id: "conflicts-fill",
        type: "fill",
        source: "conflicts",
        paint: {
          "fill-color": [
            "match", ["get", "severity"],
            "blocker", severityColour.blocker,
            "high", severityColour.high,
            "medium", severityColour.medium,
            severityColour.low,
          ],
          "fill-opacity": 0.5,
        },
      });
    }
  };

  const reset = () => {
    pointsRef.current = [];
    setConflicts([]);
    setProjectId(null);
    setMode("idle");
    if (map.getLayer("draw-preview-line")) map.removeLayer("draw-preview-line");
    if (map.getSource("draw-preview")) map.removeSource("draw-preview");
    if (map.getLayer("conflicts-fill")) map.removeLayer("conflicts-fill");
    if (map.getSource("conflicts")) map.removeSource("conflicts");
  };

  const SEVERITY_ORDER = ["blocker", "high", "medium", "low"];
  const sorted = [...conflicts].sort(
    (a, b) => SEVERITY_ORDER.indexOf(a.severity ?? "low") - SEVERITY_ORDER.indexOf(b.severity ?? "low")
  );

  return (
    <>
      {/* Draw controls */}
      <div className="absolute top-4 left-[300px] z-20 flex gap-2">
        {mode === "idle" && (
          <button
            onClick={() => { pointsRef.current = []; setMode("drawing"); }}
            className="bg-amber-500 hover:bg-amber-600 text-white text-sm font-medium px-4 py-2 rounded-lg shadow"
          >
            ✏️ Draw Corridor
          </button>
        )}
        {mode === "drawing" && (
          <span className="bg-white text-gray-700 text-sm px-4 py-2 rounded-lg shadow border border-amber-400">
            Click to add points · Double-click to finish
          </span>
        )}
        {(mode === "done" || conflicts.length > 0) && (
          <button
            onClick={reset}
            className="bg-gray-600 hover:bg-gray-700 text-white text-sm px-3 py-2 rounded-lg shadow"
          >
            Clear
          </button>
        )}
        {loading && (
          <span className="bg-white text-gray-600 text-sm px-4 py-2 rounded-lg shadow animate-pulse">
            Detecting conflicts…
          </span>
        )}
      </div>

      {/* Conflict results panel */}
      {sorted.length > 0 && (
        <div className="absolute top-16 left-[300px] z-20 bg-white rounded-xl shadow-xl border border-gray-200 w-96 max-h-80 overflow-y-auto">
          <div className="bg-red-600 text-white px-4 py-2 rounded-t-xl">
            <p className="font-semibold text-sm">{sorted.length} Conflicts Detected</p>
            {projectId && (
              <a
                href={`/api/v1/reports/${projectId}/generate`}
                target="_blank"
                className="text-xs text-red-100 hover:text-white underline"
              >
                Download PDF Report
              </a>
            )}
          </div>
          <div className="divide-y divide-gray-100">
            {sorted.map((c) => (
              <div key={c.id} className="px-4 py-2 flex items-start gap-3">
                <span className={`text-xs font-bold px-2 py-0.5 rounded shrink-0 badge-${c.severity}`}>
                  {(c.severity ?? "low").toUpperCase()}
                </span>
                <div className="min-w-0">
                  <p className="text-xs font-medium text-gray-800 capitalize">
                    {(c.conflict_type ?? "unknown").replace(/_/g, " ")}
                  </p>
                  <p className="text-xs text-gray-500">
                    {c.area_sqm ? `${(c.area_sqm / 10000).toFixed(2)} ha` : ""}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </>
  );
}
