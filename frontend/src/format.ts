import type { SpecValue } from "./types";

const nf = (digits: number) => new Intl.NumberFormat("en-GB", { maximumFractionDigits: digits, minimumFractionDigits: 0 });

/** Human-readable value. Display rounding only; the exact stored value is shown in the source panel. */
export function formatSpec(v: Pick<SpecValue, "value" | "value_text" | "unit">): string {
  if (v.value === null || v.value === undefined) return v.value_text ?? "unavailable";
  const x = v.value;
  switch (v.unit) {
    case "kg": return `${nf(0).format(x)} kg (${nf(1).format(x / 1000)} t)`;
    case "m": return `${nf(2).format(x)} m`;
    case "m2": return `${nf(1).format(x)} m²`;
    case "m3": return `${nf(0).format(x)} m³`;
    case "L": return `${nf(0).format(x)} L`;
    case "kN": return `${nf(1).format(x)} kN`;
    case "Mach": return `Mach ${nf(2).format(x)}`;
    case "kt": return `${nf(0).format(x)} kt`;
    case "km": return `${nf(0).format(x)} km (${nf(0).format(x / 1.852)} NM)`;
    case "NM": return `${nf(0).format(x)} NM (${nf(0).format(x * 1.852)} km)`;
    case "deg": return `${nf(1).format(x)}°`;
    case "seats": return `${nf(0).format(x)} seats`;
    case "count": return nf(0).format(x);
    case "ratio": return nf(2).format(x);
    default: return `${nf(2).format(x)}${v.unit ? ` ${v.unit}` : ""}`;
  }
}

export const num = (x: number | null | undefined, digits = 0) => (x === null || x === undefined ? "unavailable" : nf(digits).format(x));

export const label = (text: string | null | undefined) => (text ? text.replace(/_/g, " ") : "unavailable");

export const SOURCE_TYPE_LABEL: Record<string, string> = {
  published_specification: "Published specification",
  open_model_data: "Open model data (OpenAP)",
  engine_databank: "ICAO engine databank",
  documented_classification: "Documented classification",
};

export const STATUS_LABEL: Record<string, string> = {
  as_published: "As published",
  shared_designator_row: "Shared row (several models)",
  source_inconsistent: "Inconsistent in source - not verified",
  unverified_model_value: "Model value - not certified",
};
