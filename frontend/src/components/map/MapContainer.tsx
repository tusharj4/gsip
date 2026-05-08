"use client";

import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import LayerPanel from "./LayerPanel";
import InfoPanel from "./InfoPanel";
import DrawTool from "./DrawTool";
import ConflictOverlay from "./ConflictOverlay";
import NLQueryBar from "../ai/NLQueryBar";

export interface ClickedFeature {
  layerName: string;
  properties: Record<string, unknown>;
  coordinates: [number, number];
}

export default function MapContainer() {
  const searchParams   = useSearchParams();
  const projectId      = searchParams.get("project_id");

  const mapRef         = useRef<maplibregl.Map | null>(null);
  const containerRef   = useRef<HTMLDivElement>(null);
  const [mapReady, setMapReady] = useState(false);
  const [clickedFeature, setClickedFeature] = useState<ClickedFeature | null>(null);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const map = new maplibregl.Map({
      container: containerRef.current,
      // OpenFreeMap — completely free, no API key required
      style: "https://tiles.openfreemap.org/styles/liberty",
      center: [78.96, 22.59], // Centre of India
      zoom: 5,
      maxBounds: [
        [61.0, 6.0],    // SW — broad India + neighbours bbox
        [101.0, 38.0],  // NE
      ],
    });

    map.addControl(new maplibregl.NavigationControl(), "top-right");
    map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-left");
    map.addControl(
      new maplibregl.GeolocateControl({ trackUserLocation: false }),
      "top-right"
    );
    map.addControl(
      new maplibregl.FullscreenControl(),
      "top-right"
    );

    map.on("load", () => setMapReady(true));

    // Click handler — inspect features from GSIP layers (prefixed "gsip-")
    map.on("click", (e) => {
      const gsipLayerIds = map
        .getStyle()
        .layers
        ?.filter((l) => l.id.startsWith("gsip-"))
        .map((l) => l.id) ?? [];

      if (gsipLayerIds.length === 0) {
        setClickedFeature(null);
        return;
      }

      const features = map.queryRenderedFeatures(e.point, { layers: gsipLayerIds });
      if (features.length > 0) {
        const f = features[0];
        setClickedFeature({
          layerName: f.layer.id.replace("gsip-", ""),
          properties: f.properties as Record<string, unknown>,
          coordinates: [e.lngLat.lng, e.lngLat.lat],
        });
      } else {
        setClickedFeature(null);
      }
    });

    // Pointer cursor over GSIP layers
    map.on("mousemove", (e) => {
      const gsipLayerIds = map
        .getStyle()
        .layers
        ?.filter((l) => l.id.startsWith("gsip-"))
        .map((l) => l.id) ?? [];
      if (gsipLayerIds.length === 0) return;
      const features = map.queryRenderedFeatures(e.point, { layers: gsipLayerIds });
      map.getCanvas().style.cursor = features.length > 0 ? "pointer" : "";
    });

    mapRef.current = map;
    return () => map.remove();
  }, []);

  return (
    <div className="flex flex-1 overflow-hidden relative">
      {/* Left sidebar — layer panel */}
      <div className="w-72 bg-white border-r border-gray-200 flex flex-col overflow-y-auto z-10 shrink-0">
        <LayerPanel map={mapRef.current} mapReady={mapReady} />
      </div>

      {/* Map canvas */}
      <div ref={containerRef} className="flex-1 relative" />

      {/* Draw tool — floats over map, hidden when viewing existing project */}
      {mapReady && mapRef.current && !projectId && (
        <DrawTool map={mapRef.current} />
      )}

      {/* Conflict overlay — shown when navigated with ?project_id= */}
      {mapReady && mapRef.current && projectId && (
        <ConflictOverlay map={mapRef.current} projectId={projectId} />
      )}

      {/* Right info panel — shown when a GSIP layer feature is clicked */}
      {clickedFeature && (
        <div className="absolute right-4 bottom-24 w-72 z-20">
          <InfoPanel feature={clickedFeature} onClose={() => setClickedFeature(null)} />
        </div>
      )}

      {/* AI natural language query bar — bottom centre */}
      {mapReady && mapRef.current && (
        <div className="absolute bottom-8 left-1/2 -translate-x-1/2 z-20 w-full max-w-2xl px-4">
          <NLQueryBar map={mapRef.current} />
        </div>
      )}
    </div>
  );
}
