import type { AircraftDetail, AircraftSummary, SpecValue } from "../types";

export const spec = (over: Partial<SpecValue>): SpecValue => ({
  key: "mtow_kg", label: "Maximum takeoff weight (MTOW)", section: "weights", value: 93500, value_exact: "93500", value_text: null,
  unit: "kg", source_id: 21, source_name: "Curated transcription", source_dataset: "curated_freighter_published_specs",
  source_url: null, source_license: "facts with citation", source_reference: "EFW page", source_type: "published_specification",
  verification_status: "as_published", variant: "A321P2F (weight variant 011)", condition: null, notes: null,
  original_value: "93,5", original_unit: "t", glossary: "mtow", primary: true, ...over,
});

export const summary = (over: Partial<AircraftSummary> = {}): AircraftSummary => ({
  code: "A321P2F", name: "Airbus A321P2F", manufacturer: "Airbus", model: "A321P2F", variant: null, icao_type_designator: "A321",
  series: "A321", series_basis: "derived from the model designation", role: "cargo", freighter_type: "converted_freighter",
  body_class: "narrowbody", engine_count: null, engine_model: null, mtow_kg: 93500, mtow_source: "curated", aircraft_data: null,
  flight_model_supported: false, key_spec_coverage: { present: 2, expected: 10 }, image: null, ...over,
});

export const detail = (): AircraftDetail => ({
  summary: summary(), role: { role: "cargo", freighter_type: "converted_freighter", evidence: "curated source" },
  description: [{ text: "It is a passenger-to-freighter conversion of the A321-200.", source: "EFW" }],
  sections: { weights: [spec({}), spec({ key: "mzfw_kg", label: "Maximum zero-fuel weight (MZFW)", value: 73800, glossary: "mzfw" })],
    cargo: [spec({ key: "freighter_type", label: "Freighter type", section: "cargo", value: null, value_text: "converted_freighter", unit: null })] },
  missing: { weights: ["oew_kg"], dimensions: ["length_m"] }, missing_labels: { oew_kg: "Operating empty weight (OEW)", length_m: "Overall length" },
  flight_model: { supported: false, reasons: ["No OpenAP performance model"] }, related: [], freighter_programme: null,
  benchmarks: null, notes: null, data_policy: ["Missing values stay missing."],
});

export function mockFetch(routes: Record<string, unknown>) {
  return vi.fn(async (url: string) => {
    const path = Object.keys(routes).find((p) => url.startsWith(`/api${p}`));
    if (!path) return new Response(JSON.stringify({ detail: "not found" }), { status: 404 });
    return new Response(JSON.stringify(routes[path]), { status: 200, headers: { "Content-Type": "application/json" } });
  });
}
