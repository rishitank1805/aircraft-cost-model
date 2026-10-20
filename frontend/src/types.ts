export interface Reference { title: string; publisher: string; url: string }

export interface SpecValue {
  key: string; label: string; section: string;
  value: number | null; value_exact: string | null; value_text: string | null; unit: string | null;
  source_id: number | null; source_name: string | null; source_dataset: string | null; source_url: string | null;
  source_license: string | null; source_reference: string | null; source_type: string; verification_status: string;
  variant: string | null; condition: string | null; notes: string | null;
  original_value: string | null; original_unit: string | null; glossary: string | null; primary: boolean;
}

export interface AircraftSummary {
  code: string; name: string; manufacturer: string | null; model: string | null; variant: string | null;
  icao_type_designator: string | null; series: string | null; series_basis: string;
  role: "passenger" | "cargo" | null; freighter_type: string | null; body_class: string | null;
  engine_count: number | null; engine_model: string | null; mtow_kg: number | null; mtow_source: string | null;
  aircraft_data: string | null; flight_model_supported: boolean;
  key_spec_coverage: { present: number; expected: number }; image: null;
}

export interface AircraftList {
  total: number; count: number; items: AircraftSummary[]; facets: Record<string, string[]>; notes: string[];
}

export interface Related { code: string; relation: string; available: boolean; warning: string | null }

export interface BenchmarkMetric { usd_per_block_hour: number; carriers: string[]; rows: number; periods: string[] }

export interface AircraftDetail {
  summary: AircraftSummary;
  role: { role: string | null; freighter_type: string | null; evidence: string };
  description: { text: string; source: string }[];
  sections: Record<string, SpecValue[]>;
  missing: Record<string, string[]>;
  missing_labels: Record<string, string>;
  flight_model: { supported: boolean; reasons: string[]; description?: string | null };
  related: Related[];
  freighter_programme: Record<string, string> | null;
  benchmarks: { bts_type: string; bts_config: string; bts_description: string; mapping_status: string; mapping_notes: string;
    metrics: Record<string, BenchmarkMetric | null>; label: string } | null;
  notes: string | null;
  data_policy: string[];
}

export interface CompareRow {
  key: string; label: string; section: string; glossary: string | null; why_it_matters: string | null;
  like_for_like: boolean; issues: string[]; cells: (SpecValue | null)[];
}
export interface Compare { aircraft: AircraftSummary[]; rows: CompareRow[]; rule: string }

export interface GlossaryTopic {
  slug: string; term: string; category: string; definition: string; why_it_matters: string; example: string;
  diagram: string | null; related_specs: string[]; aliases: string[]; references: Reference[]; basis: string;
}

export interface CargoContent {
  explainers: { id: string; title: string; body: string; glossary: string[]; references: Reference[]; basis: string }[];
  conversion_steps: { step: number; title: string; body: string; references: Reference[]; basis: string }[];
  targets: { code: string; name: string; freighter_type: string; summary: string; not_to_confuse_with: string;
    references: Reference[]; published_facts: SpecValue[]; missing: Record<string, string[]>; missing_labels: string[]; flight_model_supported: boolean }[];
  disclaimer: string;
}

export interface FlightResult {
  saved: boolean; status: string; feasible: boolean; aircraft: string; aircraft_name: string; model: string;
  origin: { ident: string; iata: string | null; name: string | null };
  destination: { ident: string; iata: string | null; name: string | null };
  distance: { great_circle_nm: number; great_circle_km: number; estimated_route_nm: number; method: string; description: string };
  times_min: Record<string, number>; fuel_kg: Record<string, number>; mass_kg: Record<string, number>;
  phases: { phase: string; sequence_number: number; start_time_s: number; duration_s: number; distance_nm: number | null;
    start_altitude_ft: number; end_altitude_ft: number; start_mass_kg: number; end_mass_kg: number; fuel_burn_kg: number;
    fuel_flow_method: string }[];
  checks: { name: string; status: string; value: number | null; limit: number | null; unit: string; note: string }[];
  assumptions: { name: string; value: string; unit: string | null; source_type: string; source_reference: string | null; notes: string | null }[];
  warnings: string[]; trajectory: Record<string, number | string>[]; labels: string[];
}

