"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import type { Project } from "@/lib/types";

const STATUS_COLOURS: Record<string, string> = {
  draft:     "bg-gray-100 text-gray-600",
  submitted: "bg-yellow-100 text-yellow-700",
  approved:  "bg-blue-100 text-blue-700",
  active:    "bg-green-100 text-green-700",
  completed: "bg-purple-100 text-purple-700",
};

const TYPE_ICONS: Record<string, string> = {
  road:     "🛣️",
  railway:  "🚆",
  pipeline: "🔧",
  power:    "⚡",
  telecom:  "📡",
};

export default function ProjectsPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [newType, setNewType] = useState("road");

  useEffect(() => {
    api.get<Project[]>("/api/v1/projects/?limit=100")
      .then((r) => setProjects(r.data))
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  const createProject = async () => {
    if (!newName.trim()) return;
    const resp = await api.post<Project>("/api/v1/projects/", {
      name: newName,
      project_type: newType,
    });
    setProjects((prev) => [resp.data, ...prev]);
    setNewName("");
    setCreating(false);
  };

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-brand-700 text-white px-6 py-3 flex items-center justify-between">
        <h1 className="font-semibold">Infrastructure Projects</h1>
        <div className="flex gap-3 items-center">
          <Link href="/" className="text-xs text-brand-100 hover:text-white">← Dashboard</Link>
          <Link href="/map" className="text-xs text-brand-100 hover:text-white">Map View</Link>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-6 py-8">
        {/* New project form */}
        <div className="bg-white rounded-xl border border-gray-200 p-5 mb-6 shadow-sm">
          <h2 className="font-semibold text-brand-700 mb-3">New Project</h2>
          <div className="flex gap-3">
            <input
              type="text"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="Project name, e.g. NH-48 Widening Mumbai–Pune"
              className="flex-1 border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
              onKeyDown={(e) => e.key === "Enter" && createProject()}
            />
            <select
              value={newType}
              onChange={(e) => setNewType(e.target.value)}
              className="border border-gray-300 rounded-lg px-3 py-2 text-sm"
            >
              {["road", "railway", "pipeline", "power", "telecom"].map((t) => (
                <option key={t} value={t}>{TYPE_ICONS[t]} {t}</option>
              ))}
            </select>
            <button
              onClick={createProject}
              className="bg-brand-500 hover:bg-brand-700 text-white text-sm font-medium px-5 py-2 rounded-lg"
            >
              Create
            </button>
          </div>
        </div>

        {/* Project list */}
        {loading ? (
          <div className="text-sm text-gray-500 animate-pulse">Loading projects…</div>
        ) : projects.length === 0 ? (
          <div className="text-sm text-gray-400 text-center py-12">No projects yet. Create one above.</div>
        ) : (
          <div className="space-y-3">
            {projects.map((p) => (
              <div key={p.id} className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm hover:shadow-md transition-shadow">
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-3">
                    <span className="text-2xl">{TYPE_ICONS[p.project_type ?? "road"] ?? "🏗️"}</span>
                    <div>
                      <h3 className="font-semibold text-gray-900">{p.name}</h3>
                      <p className="text-xs text-gray-500">{p.ministry ?? "Ministry not set"}</p>
                    </div>
                  </div>
                  <span className={`text-xs font-medium px-2 py-1 rounded-full ${STATUS_COLOURS[p.status] ?? "bg-gray-100"}`}>
                    {p.status}
                  </span>
                </div>

                <div className="mt-3 flex gap-6 text-xs text-gray-500">
                  <span>Buffer: {p.buffer_m}m</span>
                  {p.cost_crore && <span>Cost: ₹{p.cost_crore} Cr</span>}
                  <span>{p.corridor_geojson ? "✅ Corridor set" : "⚠️ No corridor"}</span>
                </div>

                <div className="mt-3 flex gap-2">
                  <Link
                    href={`/map?project_id=${p.id}`}
                    className="text-xs bg-brand-50 text-brand-700 border border-brand-200 px-3 py-1 rounded-lg hover:bg-brand-100"
                  >
                    Open on Map
                  </Link>
                  {p.corridor_geojson && (
                    <a
                      href={`/api/v1/reports/${p.id}/generate`}
                      target="_blank"
                      className="text-xs bg-gray-50 text-gray-600 border border-gray-200 px-3 py-1 rounded-lg hover:bg-gray-100"
                    >
                      Download PDF Report
                    </a>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </main>
    </div>
  );
}
