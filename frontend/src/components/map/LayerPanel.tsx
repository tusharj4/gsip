"use client";

import { useEffect, useState, useCallback, useMemo } from "react";
import maplibregl from "maplibre-gl";
import { api } from "@/lib/api";
import type { GISLayer } from "@/lib/types";

interface Props {
  map: maplibregl.Map | null;
  mapReady: boolean;
}

const CATEGORY_COLOURS: Record<string, string> = {
  infrastructure: "#2563eb",
  regulatory:     "#dc2626",
  socioeconomic:  "#16a34a",
  natural:        "#d97706",
};

const CATEGORY_ICONS: Record<string, string> = {
  infrastructure: "🏗️",
  regulatory:     "⚖️",
  socioeconomic:  "👥",
  natural:        "🌿",
};

export default function LayerPanel({ map, mapReady }: Props) {
  const [layers,   setLayers]   = useState<GISLayer[]>([]);
  const [visible,  setVisible]  = useState<Set<string>>(new Set());
  const [opacity,  setOpacity]  = useState<Record<string, number>>({});
  const [loading,  setLoading]  = useState(true);
  const [search,   setSearch]   = useState("");
  const [ministry, setMinistry] = useState<string>("all");

  useEffect(() => {
    api
      .get<GISLayer[]>("/api/v1/layers/?status=published&limit=500")
      .then((r) => setLayers(r.data))
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  // Unique ministry list derived from loaded layers
  const ministries = useMemo(() => {
    const set = new Set<string>();
    for (const l of layers) {
      if (l.ministry_owner) set.add(l.ministry_owner);
    }
    return Array.from(set).sort();
  }, [layers]);

  // Filtered + searched layers
  const filtered = useMemo(() => {
    return layers.filter((l) => {
      const matchSearch =
        !search.trim() ||
        l.name.toLowerCase().includes(search.toLowerCase()) ||
        l.slug.toLowerCase().includes(search.toLowerCase());
      const matchMinistry =
        ministry === "all" || l.ministry_owner === ministry;
      return matchSearch && matchMinistry;
    });
  }, [layers, search, ministry]);

  const toggleLayer = useCallback(
    (layer: GISLayer) => {
      if (!map || !mapReady) return;
      const layerId  = `gsip-${layer.slug}`;
      const lineId   = `${layerId}-line`;
      const circleId = `${layerId}-circle`;
      const sourceId = `src-${layer.slug}`;

      if (visible.has(layer.slug)) {
        // Hide all sub-layers
        for (const id of [layerId, lineId, circleId]) {
          if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", "none");
        }
        setVisible((prev) => { const s = new Set(prev); s.delete(layer.slug); return s; });
      } else {
        // Add source if not yet registered
        if (!map.getSource(sourceId)) {
          map.addSource(sourceId, {
            type: "geojson",
            // Proxy through Next.js rewrite or direct backend call
            data: `${process.env.NEXT_PUBLIC_API_URL ?? ""}/api/v1/layers/${layer.id}/features`,
          });
        }

        const colour = CATEGORY_COLOURS[layer.category] ?? "#6366f1";
        const op     = (opacity[layer.slug] ?? 70) / 100;

        // Polygon fill
        if (!map.getLayer(layerId)) {
          map.addLayer({
            id: layerId,
            type: "fill",
            source: sourceId,
            paint: {
              "fill-color":         colour,
              "fill-opacity":       op * 0.7,
              "fill-outline-color": colour,
            },
            filter: ["==", ["geometry-type"], "Polygon"],
          });
        } else {
          map.setLayoutProperty(layerId, "visibility", "visible");
        }

        // LineString
        if (!map.getLayer(lineId)) {
          map.addLayer({
            id: lineId,
            type: "line",
            source: sourceId,
            paint: { "line-color": colour, "line-width": 2.5, "line-opacity": op },
            filter: ["==", ["geometry-type"], "LineString"],
          });
        } else {
          map.setLayoutProperty(lineId, "visibility", "visible");
        }

        // Point / circle
        if (!map.getLayer(circleId)) {
          map.addLayer({
            id: circleId,
            type: "circle",
            source: sourceId,
            paint: {
              "circle-color":   colour,
              "circle-radius":  5,
              "circle-opacity": op,
            },
            filter: ["==", ["geometry-type"], "Point"],
          });
        } else {
          map.setLayoutProperty(circleId, "visibility", "visible");
        }

        setVisible((prev) => new Set(prev).add(layer.slug));
      }
    },
    [map, mapReady, visible, opacity]
  );

  const setLayerOpacity = useCallback(
    (slug: string, value: number) => {
      setOpacity((prev) => ({ ...prev, [slug]: value }));
      if (!map) return;
      const op = value / 100;
      const layerId  = `gsip-${slug}`;
      const lineId   = `${layerId}-line`;
      const circleId = `${layerId}-circle`;
      if (map.getLayer(layerId))  map.setPaintProperty(layerId,  "fill-opacity",   op * 0.7);
      if (map.getLayer(lineId))   map.setPaintProperty(lineId,   "line-opacity",   op);
      if (map.getLayer(circleId)) map.setPaintProperty(circleId, "circle-opacity", op);
    },
    [map]
  );

  const grouped = useMemo(
    () =>
      filtered.reduce<Record<string, GISLayer[]>>((acc, l) => {
        (acc[l.category] ??= []).push(l);
        return acc;
      }, {}),
    [filtered]
  );

  const visibleCount = visible.size;

  return (
    <div className="flex flex-col h-full">
      {/* Panel header */}
      <div className="px-4 py-3 border-b border-gray-200 bg-brand-700 text-white shrink-0">
        <h2 className="font-semibold text-sm">GIS Layers</h2>
        <p className="text-xs text-brand-100">
          {layers.length} published · {visibleCount} visible
        </p>
      </div>

      {/* Search + Ministry filter */}
      <div className="px-3 py-3 border-b border-gray-100 space-y-2 shrink-0">
        <input
          type="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search layers…"
          className="w-full text-xs border border-gray-300 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-brand-500"
        />
        {ministries.length > 0 && (
          <select
            value={ministry}
            onChange={(e) => setMinistry(e.target.value)}
            className="w-full text-xs border border-gray-300 rounded-lg px-2 py-1.5 bg-white focus:outline-none"
          >
            <option value="all">All Ministries</option>
            {ministries.map((m) => (
              <option key={m} value={m}>{m}</option>
            ))}
          </select>
        )}
      </div>

      {/* Layer list */}
      <div className="flex-1 overflow-y-auto">
        {loading ? (
          <div className="p-4 text-xs text-gray-400 animate-pulse">Loading layers…</div>
        ) : Object.keys(grouped).length === 0 ? (
          <div className="p-4 text-xs text-gray-400 text-center">
            {layers.length === 0 ? "No published layers yet." : "No layers match your filter."}
          </div>
        ) : (
          Object.entries(grouped).map(([category, catLayers]) => (
            <div key={category}>
              {/* Category header */}
              <div
                className="px-4 py-2 text-xs font-bold uppercase tracking-wider text-white flex items-center gap-1.5"
                style={{ backgroundColor: CATEGORY_COLOURS[category] ?? "#6366f1" }}
              >
                <span>{CATEGORY_ICONS[category]}</span>
                <span>{category}</span>
                <span className="ml-auto font-normal opacity-80">{catLayers.length}</span>
              </div>

              {catLayers.map((layer) => (
                <div key={layer.id} className="border-b border-gray-100">
                  <div className="flex items-center gap-2 px-4 py-2 hover:bg-gray-50 transition-colors">
                    <input
                      type="checkbox"
                      id={`layer-${layer.slug}`}
                      checked={visible.has(layer.slug)}
                      onChange={() => toggleLayer(layer)}
                      className="rounded accent-brand-500 shrink-0"
                    />
                    <label
                      htmlFor={`layer-${layer.slug}`}
                      className="flex-1 min-w-0 cursor-pointer"
                    >
                      <p className="text-xs text-gray-800 truncate">{layer.name}</p>
                      {layer.ministry_owner && (
                        <p className="text-xs text-gray-400 truncate">{layer.ministry_owner}</p>
                      )}
                    </label>
                    <span className="text-xs text-gray-400 shrink-0 tabular-nums">
                      {layer.feature_count.toLocaleString()}
                    </span>
                  </div>

                  {visible.has(layer.slug) && (
                    <div className="px-4 pb-2 flex items-center gap-2">
                      <span className="text-xs text-gray-400 w-8">
                        {opacity[layer.slug] ?? 70}%
                      </span>
                      <input
                        type="range"
                        min={10}
                        max={100}
                        value={opacity[layer.slug] ?? 70}
                        onChange={(e) => setLayerOpacity(layer.slug, Number(e.target.value))}
                        className="flex-1 h-1 accent-brand-500"
                        aria-label={`Opacity for ${layer.name}`}
                      />
                    </div>
                  )}
                </div>
              ))}
            </div>
          ))
        )}
      </div>

      {/* Footer */}
      {visibleCount > 0 && (
        <div className="px-4 py-2 border-t border-gray-100 bg-gray-50 shrink-0">
          <button
            onClick={() => {
              // Hide all visible layers at once
              for (const slug of visible) {
                const ids = [`gsip-${slug}`, `gsip-${slug}-line`, `gsip-${slug}-circle`];
                for (const id of ids) {
                  if (map?.getLayer(id)) map.setLayoutProperty(id, "visibility", "none");
                }
              }
              setVisible(new Set());
            }}
            className="text-xs text-gray-500 hover:text-red-600 underline"
          >
            Hide all ({visibleCount})
          </button>
        </div>
      )}
    </div>
  );
}
