import type { AircraftDetail, AircraftList, CargoContent, Compare, FlightResult, GlossaryTopic } from "./types";

// Loosely typed JSON for the advanced economics module (shapes documented in docs/explorer_app.md).
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type Json = any;

export class ApiError extends Error {}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, init);
  if (!response.ok) {
    let detail = response.statusText;
    try { detail = (await response.json()).detail ?? detail; } catch { /* keep status text */ }
    throw new ApiError(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return response.json() as Promise<T>;
}

const qs = (params: Record<string, string | number | boolean | undefined | null>) => {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== "") search.set(k, String(v)); });
  const text = search.toString();
  return text ? `?${text}` : "";
};

export const api = {
  aircraft: (params: Record<string, string | number | boolean | undefined> = {}) => request<AircraftList>(`/aircraft${qs(params)}`),
  aircraftDetail: (code: string) => request<AircraftDetail>(`/aircraft/${encodeURIComponent(code)}`),
  compare: (codes: string[]) => request<Compare>(`/compare${qs({ codes: codes.join(",") })}`),
  glossary: (q?: string) => request<{ count: number; categories: string[]; topics: GlossaryTopic[] }>(`/glossary${qs({ q })}`),
  glossaryTopic: (slug: string) => request<GlossaryTopic>(`/glossary/${encodeURIComponent(slug)}`),
  cargo: () => request<CargoContent>("/cargo"),
  flightAircraft: () => request<{ items: { code: string; name: string; model: string }[]; note: string }>("/flight/aircraft"),
  airports: (q: string) => request<{ items: { ident: string; iata: string | null; icao: string | null; name: string | null;
    city: string | null; country: string | null; type: string }[] }>(`/airports/search${qs({ q })}`),
  estimateFlight: (body: { aircraft_code: string; origin: string; destination: string; payload_kg: number }) =>
    request<FlightResult>("/flight/estimate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
  economics: () => request<{ items: Json[]; notice: string }>("/economics/estimates"),
  economicsDetail: (id: number) => request<Json>(`/economics/estimates/${id}`),
  sensitivity: (id: number, parameter: string, levels: string) => request<Json>(`/economics/estimates/${id}/sensitivity${qs({ parameter, levels })}`),
  benchmarks: (aircraft?: string) => request<Json>(`/economics/benchmarks${qs({ aircraft })}`),
};
