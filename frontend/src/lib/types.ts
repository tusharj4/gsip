/**
 * TypeScript types mirroring the FastAPI Pydantic response schemas.
 */

export interface GISLayer {
  id: string;
  name: string;
  slug: string;
  category: "infrastructure" | "regulatory" | "socioeconomic" | "natural";
  ministry_owner: string | null;
  status: string;
  source_url: string | null;
  last_synced_at: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  feature_count: number;
}

export interface Project {
  id: string;
  name: string;
  ministry: string | null;
  project_type: string | null;
  status: string;
  corridor_geojson: GeoJSONGeometry | null;
  buffer_m: number;
  cost_crore: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface ConflictReport {
  id: string;
  project_id: string;
  layer_id: string | null;
  conflict_geojson: GeoJSONGeometry | null;
  conflict_type: string | null;
  severity: "blocker" | "high" | "medium" | "low" | null;
  area_sqm: number | null;
  description: string | null;
  created_at: string;
}

export interface GapAnalysisResult {
  id: string;
  analysis_type: string | null;
  geography_geojson: GeoJSONGeometry | null;
  population: number | null;
  required_count: number | null;
  existing_count: number | null;
  gap_count: number | null;
  uncovered_geojson: GeoJSONGeometry | null;
  candidate_sites: unknown | null;
  parameters: Record<string, unknown>;
  created_at: string;
}

export interface NLQueryResponse {
  question: string;
  sql: string;
  result_type: "geojson" | "table" | "scalar";
  geojson: { type: "FeatureCollection"; features: GeoJSONFeature[] } | null;
  rows: Record<string, unknown>[] | null;
  scalar: unknown | null;
  row_count: number;
  execution_ms: number;
}

// Minimal GeoJSON types (subset of the full spec)
export interface GeoJSONGeometry {
  type: string;
  coordinates: unknown;
}

export interface GeoJSONFeature {
  type: "Feature";
  id?: string | number;
  geometry: GeoJSONGeometry;
  properties: Record<string, unknown>;
}
