"use client";

/**
 * ConflictOverlay — auto-loads and renders conflict zones for an existing project.
 *
 * When a project_id is passed (e.g. from /map?project_id=xxx) it:
 *   1. Fetches GET /api/v1/analysis/conflicts/{project_id}
 *   2. Renders conflict polygons on the map coloured by severity
 *   3. Shows a collapsible summary panel
 */

import { useEffect, useState } from "react";
import maplibregl from "maplibre-gl";
import { api } from "@/lib/api";
import type { ConflictReport, Project } from "@/lib/types";

interface Props {
  map: maplibregl.Map;
  projectId: string;
}

const SEVERITY_COLOUR: Record<string, string> = {
  blocker: "#ff4d4d",
  high:    "#ff9933",
  medium:  "#ffcc00",
  low:     "#90ee90",
};

const SEVERITY_ORDER = ["blocker", "high", "medium", "low"];

const SOURCE_ID  = "overlay-conflicts";
const FILL_ID    = "overlay-conflicts-fill";
const BORDER_ID  = "overlay-conflicts-border";
const CORRIDOR_SOURCE = "overlay-corridor";
const CORRIDOR_LAYER  = "overlay-corridor-line";

export default function ConflictOverlay({ map, projectId }: Props) {
  const [conflicts, setConflicts] = useState<ConflictReport[]>([]);
  const [project, setProject]     = useState<Project | null>(null);
  const [loading, setLoading]     = useState(true);
  const [collapsed, setCollapsed] = useState(false);
  const [error, setError]         = useState<string | null>(null);

  useEffect(() => {
    if (!projectId) return;

    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const [projResp, conflictResp] = await Promise.all([
          api.get<Project>(`/api/v1/projects/${projectId}`),
          api.get<ConflictReport[]>(`/api/v1/analysis/conflicts/${projectId}`),
        ]);
        setProject(projResp.data);
        setConflicts(conflictResp.data);

        // Draw project corridor on map
        if (projResp.data.corridor_geojson) {
          const corridorGeoJSON: GeoJSON.FeatureCollection = {
            type: "FeatureCollection",
            features: [
              {
                type: "Feature",
                geometry: projResp.data.corridor_geojson as GeoJSON.Geometry,
                properties: { name: projResp.data.name },
              },
            ],
          };
          if (map.getSource(CORRIDOR_SOURCE)) {
            (map.getSource(CORRIDOR_SOURCE) as maplibregl.GeoJSONSource).setData(corridorGeoJSON);
          } else {
            map.addSource(CORRIDOR_SOURCE, { type: "geojson", data: corridorGeoJSON });
            map.addLayer({
              id: CORRIDOR_LAYER,
              type: "line",
              source: CORRIDOR_SOURCE,
              paint: {
                "line-color": "#1a3a6e",
                "line-width": 4,
                "line-dasharray": [4, 2],
              },
            });
          }
        }

        // Draw conflict zones on map
        const features = conflictResp.data
          .filter((r) => r.conflict_geojson)
          .map((r) => ({
            type: "Feature" as const,
            geometry: r.conflict_geojson! as GeoJSON.Geometry,
            properties: {
              severity: r.severity ?? "low",
              conflict_type: r.conflict_type ?? "unknown",
              area_sqm: r.area_sqm ?? 0,
            },
          }));
        const fc: GeoJSON.FeatureCollection = { type: "FeatureCollection", features };

        if (map.getSource(SOURCE_ID)) {
          (map.getSource(SOURCE_ID) as maplibregl.GeoJSONSource).setData(fc);
        } else {
          map.addSource(SOURCE_ID, { type: "geojson", data: fc });
          map.addLayer({
            id: FILL_ID,
            type: "fill",
            source: SOURCE_ID,
            paint: {
              "fill-color": [
                "match", ["get", "severity"],
                "blocker", SEVERITY_COLOUR.blocker,
                "high",    SEVERITY_COLOUR.high,
                "medium",  SEVERITY_COLOUR.medium,
                SEVERITY_COLOUR.low,
              ],
              "fill-opacity": 0.45,
            },
          });
          map.addLayer({
            id: BORDER_ID,
            type: "line",
            source: SOURCE_ID,
            paint: {
              "line-color": [
                "match", ["get", "severity"],
                "blocker", SEVERITY_COLOUR.blocker,
                "high",    SEVERITY_COLOUR.high,
                "medium",  SEVERITY_COLOUR.medium,
                SEVERITY_COLOUR.low,
              ],
              "line-width": 1.5,
            },
          });
        }

        // Fly map to corridor bounding box
        if (features.length > 0 || projResp.data.corridor_geojson) {
          const allCoords: number[][] = [];
          if (projResp.data.corridor_geojson) {
            const geom = projResp.data.corridor_geojson as { type: string; coordinates: number[][] };
            if (geom.type === "LineString") allCoords.push(...geom.coordinates);
          }
          if (allCoords.length >= 2) {
            const lngs = allCoords.map((c) => c[0]);
            const lats = allCoords.map((c) => c[1]);
            map.fitBounds(
              [[Math.min(...lngs), Math.min(...lats)], [Math.max(...lngs), Math.max(...lats)]],
              { padding: 80, duration: 1200 }
            );
          }
        }
      } catch (err) {
        console.error("Failed to load project overlay:", err);
        setError("Could not load project data. Try again.");
      } finally {
        setLoading(false);
      }
    };

    load();

    // Clean up map layers on unmount
    return () => {
      for (const id of [FILL_ID, BORDER_ID, CORRIDOR_LAYER]) {
        if (map.getLayer(id)) map.removeLayer(id);
      }
      for (const id of [SOURCE_ID, CORRIDOR_SOURCE]) {
        if (map.getSource(id)) map.removeSource(id);
      }
    };
  }, [map, projectId]);

  const sorted = [...conflicts].sort(
    (a, b) =>
      SEVERITY_ORDER.indexOf(a.severity ?? "low") - SEVERITY_ORDER.indexOf(b.severity ?? "low")
  );

  const counts = SEVERITY_ORDER.reduce<Record<string, number>>((acc, s) => {
    acc[s] = sorted.filter((c) => c.severity === s).length;
    return acc;
  }, {});

  if (loading) {
    return (
      <div className="absolute top-4 right-4 z-20 bg-white rounded-xl shadow-xl border border-gray-200 p-4 w-72">
        <p className="text-xs text-gray-500 animate-pulse">Loading project overlay…</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="absolute top-4 right-4 z-20 bg-red-50 border border-red-200 rounded-xl shadow p-4 w-72">
        <p className="text-xs text-red-700">{error}</p>
      </div>
    );
  }

  return (
    <div className="absolute top-4 right-4 z-20 bg-white rounded-xl shadow-xl border border-gray-200 w-80 overflow-hidden">
      {/* Header */}
      <button
        className="w-full bg-brand-700 text-white px-4 py-3 flex items-center justify-between text-left"
        onClick={() => setCollapsed((c) => !c)}
      >
        <div>
          <p className="text-xs text-brand-100">Active Project</p>
          <p className="font-semibold text-sm truncate max-w-[220px]">
            {project?.name ?? "—"}
          </p>
        </div>
        <span className="text-brand-200 text-lg">{collapsed ? "▼" : "▲"}</span>
      </button>

      {!collapsed && (
        <>
          {/* Severity summary pills */}
          <div className="flex gap-2 px-4 py-3 border-b border-gray-100">
            {SEVERITY_ORDER.map((s) => (
              <div
                key={s}
                className="flex flex-col items-center px-2 py-1 rounded-lg"
                style={{ backgroundColor: SEVERITY_COLOUR[s] + "33" }}
              >
                <span
                  className="text-sm font-bold"
                  style={{ color: s === "medium" ? "#7a6000" : s === "low" ? "#3a7a00" : SEVERITY_COLOUR[s] }}
                >
                  {counts[s]}
                </span>
                <span className="text-xs text-gray-600 capitalize">{s}</span>
              </div>
            ))}
            <div className="flex flex-col items-center px-2 py-1 rounded-lg bg-gray-100 ml-auto">
              <span className="text-sm font-bold text-gray-700">{sorted.length}</span>
              <span className="text-xs text-gray-500">total</span>
            </div>
          </div>

          {/* Conflict list */}
          <div className="max-h-60 overflow-y-auto divide-y divide-gray-50">
            {sorted.length === 0 ? (
              <p className="text-xs text-green-600 font-medium text-center py-4">
                ✅ No conflicts detected
              </p>
            ) : (
              sorted.map((c) => (
                <div key={c.id} className="px-4 py-2 flex items-center gap-3">
                  <span
                    className="text-xs font-bold px-2 py-0.5 rounded shrink-0 text-white"
                    style={{ backgroundColor: SEVERITY_COLOUR[c.severity ?? "low"] }}
                  >
                    {(c.severity ?? "low").toUpperCase()}
                  </span>
                  <div className="min-w-0">
                    <p className="text-xs font-medium text-gray-800 capitalize">
                      {(c.conflict_type ?? "unknown").replace(/_/g, " ")}
                    </p>
                    {c.area_sqm && (
                      <p className="text-xs text-gray-400">
                        {(c.area_sqm / 10_000).toFixed(2)} ha
                      </p>
                    )}
                  </div>
                </div>
              ))
            )}
          </div>

          {/* Footer actions */}
          <div className="px-4 py-3 bg-gray-50 border-t border-gray-100 flex gap-2">
            {project?.corridor_geojson && (
              <a
                href={`/api/v1/reports/${projectId}/generate`}
                target="_blank"
                rel="noreferrer"
                className="text-xs bg-brand-500 text-white px-3 py-1.5 rounded-lg hover:bg-brand-700 font-medium"
              >
                PDF Report
              </a>
            )}
            <a
              href="/projects"
              className="text-xs bg-gray-200 text-gray-700 px-3 py-1.5 rounded-lg hover:bg-gray-300 font-medium"
            >
              All Projects
            </a>
          </div>
        </>
      )}
    </div>
  );
}
