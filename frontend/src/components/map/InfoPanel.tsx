"use client";

import type { ClickedFeature } from "./MapContainer";

interface Props {
  feature: ClickedFeature;
  onClose: () => void;
}

export default function InfoPanel({ feature, onClose }: Props) {
  const entries = Object.entries(feature.properties).filter(
    ([k]) => !["id", "layer_id"].includes(k)
  );

  return (
    <div className="bg-white rounded-xl shadow-xl border border-gray-200 overflow-hidden">
      <div className="bg-brand-700 text-white px-4 py-3 flex items-center justify-between">
        <div>
          <p className="text-xs text-brand-100">Selected Feature</p>
          <h3 className="font-semibold text-sm capitalize">{feature.layerName.replace(/_/g, " ")}</h3>
        </div>
        <button
          onClick={onClose}
          className="text-brand-100 hover:text-white text-lg leading-none"
          aria-label="Close"
        >
          ×
        </button>
      </div>

      <div className="p-3 max-h-80 overflow-y-auto">
        <p className="text-xs text-gray-500 mb-2">
          {feature.coordinates[1].toFixed(5)}, {feature.coordinates[0].toFixed(5)}
        </p>
        {entries.length === 0 ? (
          <p className="text-xs text-gray-400 italic">No properties</p>
        ) : (
          <dl className="space-y-1">
            {entries.map(([key, value]) => (
              <div key={key} className="flex gap-2">
                <dt className="text-xs text-gray-500 w-24 shrink-0 capitalize">
                  {key.replace(/_/g, " ")}:
                </dt>
                <dd className="text-xs text-gray-800 font-medium break-all">
                  {String(value ?? "—")}
                </dd>
              </div>
            ))}
          </dl>
        )}
      </div>
    </div>
  );
}
