"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import type { Project } from "@/lib/types";

export default function ReportsPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState<string | null>(null);

  useEffect(() => {
    api.get<Project[]>("/api/v1/projects/?limit=100")
      .then((r) => setProjects(r.data.filter((p) => p.corridor_geojson)))
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  const downloadReport = async (projectId: string) => {
    setGenerating(projectId);
    try {
      const resp = await fetch(`/api/v1/reports/${projectId}/generate`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `gsip-report-${projectId}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error("Report generation failed:", err);
      alert("Report generation failed. Ensure the project has a corridor set.");
    } finally {
      setGenerating(null);
    }
  };

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-brand-700 text-white px-6 py-3 flex items-center justify-between">
        <h1 className="font-semibold">Pre-Alignment Reports</h1>
        <div className="flex gap-3">
          <Link href="/" className="text-xs text-brand-100 hover:text-white">← Dashboard</Link>
          <Link href="/projects" className="text-xs text-brand-100 hover:text-white">Projects</Link>
        </div>
      </header>

      <main className="max-w-4xl mx-auto px-6 py-8">
        <div className="bg-blue-50 border border-blue-200 rounded-xl p-4 mb-6 text-sm text-blue-800">
          <strong>📄 Pre-Alignment Report</strong> — Generated PDF containing: project metadata,
          corridor map thumbnail, conflict summary table sorted by severity, required regulatory
          clearances, and gap analysis summary. Only projects with a drawn corridor are listed.
        </div>

        {loading ? (
          <div className="text-sm text-gray-400 animate-pulse">Loading projects…</div>
        ) : projects.length === 0 ? (
          <div className="text-center py-12">
            <p className="text-gray-500 text-sm mb-3">No projects with corridors found.</p>
            <Link href="/map" className="text-brand-500 underline text-sm">
              Draw a corridor on the Map →
            </Link>
          </div>
        ) : (
          <div className="space-y-3">
            {projects.map((p) => (
              <div key={p.id} className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm flex items-center justify-between">
                <div>
                  <h3 className="font-semibold text-gray-900">{p.name}</h3>
                  <p className="text-xs text-gray-500">
                    {p.project_type} · {p.ministry ?? "No ministry"} · Buffer: {p.buffer_m}m
                  </p>
                </div>
                <button
                  onClick={() => downloadReport(p.id)}
                  disabled={generating === p.id}
                  className="flex items-center gap-2 bg-brand-500 hover:bg-brand-700 disabled:opacity-50 text-white text-sm font-medium px-4 py-2 rounded-lg"
                >
                  {generating === p.id ? (
                    <><span className="animate-spin">⟳</span> Generating…</>
                  ) : (
                    <>📥 Download PDF</>
                  )}
                </button>
              </div>
            ))}
          </div>
        )}

        {/* Report contents reference */}
        <div className="mt-8 bg-white rounded-xl border border-gray-200 p-5">
          <h2 className="font-semibold text-brand-700 mb-3">What's in the Report?</h2>
          <div className="grid grid-cols-2 gap-3 text-sm">
            {[
              ["📋 Project Metadata", "Name, ministry, type, buffer, cost estimate"],
              ["🗺️ Corridor Map", "Static OSM thumbnail with corridor overlay"],
              ["⚠️ Conflict Table", "All conflicts ranked by severity (blocker → low)"],
              ["📜 Clearances Required", "Regulatory clearances mapped to detected conflicts"],
              ["📊 Gap Summary", "Service gaps identified in the project area"],
              ["🛣️ Alternatives", "Scored alternative alignments (when available)"],
            ].map(([title, desc]) => (
              <div key={title as string} className="bg-gray-50 rounded-lg p-3">
                <div className="font-medium text-gray-800 text-sm">{title}</div>
                <div className="text-xs text-gray-500 mt-0.5">{desc}</div>
              </div>
            ))}
          </div>
        </div>
      </main>
    </div>
  );
}
