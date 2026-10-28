import { stripCompanyUrls } from "./links";

/**
 * Plain-language wording for everything the API returns as an identifier (statuses, field names,
 * dataset keys) or as a technical reference (file names, column names). The API keeps its exact
 * identifiers for provenance; the screen shows these words instead.
 */
const TERMS: Record<string, string> = {
  // aircraft roles and classes
  passenger: "Passenger", cargo: "Cargo", production_freighter: "Production freighter",
  converted_freighter: "Converted freighter (P2F)", narrowbody: "Narrowbody", widebody: "Widebody",
  regional_jet: "Regional jet", business_jet: "Business jet", turbofan: "Turbofan", wing: "Under the wings",
  rear: "On the rear fuselage",
  // page sections
  overview: "Overview", classification: "Classification", dimensions: "Dimensions", weights: "Weights",
  engines: "Engines", performance: "Performance", capacity: "Seating", sources: "Sources",
  // source types and datasets
  published_specification: "Published specification", open_model_data: "Open model data (OpenAP)",
  engine_databank: "ICAO engine databank", documented_classification: "Documented classification",
  physical_constant: "Physical constant", project_default: "Default setting", modelling_assumption: "Model assumption",
  database: "Aircraft and airport data", openap_model: "OpenAP model", user_input: "Your input",
  user_assumption: "Your assumption",
  curated_freighter_published_specs: "Manufacturer and conversion-provider web pages",
  faa_aircraft_characteristics_database: "FAA Aircraft Characteristics Database",
  faa_economic_values_tables_4_16_4_17: "FAA Economic Values",
  openap_aircraft_properties: "OpenAP aircraft data",
  openap_engines_csv: "OpenAP engine data (ICAO Engine Emissions Databank)",
  // specification names (Knowledge Hub "related specifications")
  base_aircraft: "Converted from", body_class: "Body type", bypass_ratio: "Bypass ratio", cargo_barrier: "Cargo barrier",
  cargo_capacity_statement: "Published cargo capacity", cargo_loading_system: "Cargo loading system",
  conversion_provider: "Conversion provider", engine_count: "Number of engines", engine_model: "Engine model",
  engine_type: "Engine type", freighter_type: "Freighter type", fuel_capacity_l: "Fuel capacity",
  fuselage_width_m: "Fuselage width", lower_deck_capacity: "Lower-deck positions", main_deck_capacity: "Main-deck positions",
  main_deck_cargo_door: "Main-deck cargo door", main_deck_compartment_class: "Main-deck compartment class",
  max_ramp_weight_kg: "Maximum ramp weight", max_structural_payload_kg: "Maximum structural payload", mlw_kg: "MLW",
  mtow_kg: "MTOW", mzfw_kg: "MZFW", oew_kg: "OEW", nominal_cruise_range_km: "Nominal cruise range",
  published_range_km: "Published range", published_range_nm: "Published range", rated_thrust_kn: "Rated thrust",
  // Knowledge Hub topics linked from other pages (slugs with "-" read as "_")
  uld: "ULDs", cargo_pallet: "Cargo pallets", p2f_conversion: "P2F conversion", passenger_vs_freighter: "Passenger vs freighter",
  payload_range: "Payload and range",
  // flight phases and times
  taxi_out: "Taxi-out", takeoff: "Takeoff", climb: "Climb", cruise: "Cruise", descent: "Descent",
  approach: "Approach", landing_roll: "Landing roll", taxi_in: "Taxi-in", takeoff_roll: "Takeoff roll",
  airborne: "Airborne", trip: "Trip", block: "Block",
  // limit checks
  payload_nonnegative: "Payload is zero or more", planned_fuel_nonnegative: "Fuel load is zero or more",
  max_payload: "Maximum payload", mzfw: "MZFW", max_ramp_weight: "Maximum ramp weight", mtow: "MTOW",
  mlw: "MLW", oew: "OEW", fuel_capacity: "Fuel tank capacity",
  mass_decreases_with_fuel_burn: "Weight falls as fuel burns",
  passed: "passed", failed: "limit exceeded", not_performed: "not checked",
  // flight assumptions
  distance_method: "Distance calculation", route_distance_method: "Route", route_factor: "Route factor",
  wind: "Wind", atmosphere: "Atmosphere", origin_elevation_ft: "Departure airport elevation",
  destination_elevation_ft: "Arrival airport elevation", requested_cruise_altitude_ft: "Planned cruise altitude",
  cruise_altitude_ft: "Cruise altitude flown", cruise_mach: "Cruise speed (Mach)",
  kinematic_parameters: "Climb, cruise and descent profile", takeoff_thrust: "Takeoff thrust",
  reverse_thrust: "Reverse thrust", taxi_out_min: "Taxi-out time", taxi_in_min: "Taxi-in time",
  operating_empty_weight_kg: "Operating empty weight", payload_kg: "Payload", taxi_fuel_flow_kg_s: "Taxi fuel flow",
  fuel_density_kg_per_l: "Fuel density", contingency_pct_of_trip: "Contingency fuel", alternate_fuel_kg: "Alternate fuel",
  final_reserve_fuel_kg: "Final reserve fuel", great_circle: "great circle",
  // cost categories and components
  direct_variable: "Direct variable costs", direct_fixed: "Direct fixed costs", indirect: "Indirect costs",
  noncash: "Non-cash costs", financing: "Financing costs", fuel: "Fuel", airframe_maintenance: "Airframe maintenance",
  engine_maintenance: "Engine maintenance", engine_llp: "Engine life-limited parts", navigation: "En-route navigation charges",
  terminal_navigation: "Terminal navigation charges", landing: "Landing charges", ground_handling: "Ground handling",
  crew_allowances: "Crew allowances", crew_salaries: "Crew salaries", insurance: "Insurance", operating_lease: "Operating lease",
  administration: "Administration", cargo_sales: "Cargo sales", general_administrative: "General and administrative",
  depreciation: "Depreciation", financing_interest: "Financing interest", coc: "COC", toc: "TOC", total_costs: "Total costs",
  // cost statuses and quality
  calculated: "calculated", calculated_benchmark: "from a public benchmark", calculated_assumption: "from a scenario assumption",
  not_applicable: "not applicable", unavailable: "not available", unavailable_public_tariff: "no public tariff available",
  unavailable_route_geometry: "no route data for this charge", missing_required_input: "an input is missing",
  incomplete: "incomplete", complete: "complete", partial: "partial", none: "none",
  calculated_limits_unverified: "calculated, but some weight limits could not be checked",
  explicit_user_assumption: "illustrative assumption", illustrative_assumption: "illustrative assumption",
  public_market_benchmark: "public market price", public_financial_benchmark: "public financial benchmark",
  observed_public_data: "published charges", modelled_estimate: "model estimate",
  // scenario parameters and benchmarks
  fuel_price: "Fuel price", airframe_maintenance_rate: "Airframe maintenance rate", annual_utilization: "Annual utilisation",
  crew_compensation: "Crew pay", crew: "Crew", maintenance: "Maintenance",
  aircraft_operating_total: "Total aircraft operating cost", maintenance_total: "Maintenance (total)",
  pilots_and_copilots: "Pilots and co-pilots", exact_type_match: "exact type match",
  configuration_match: "same type and configuration", family_match: "same aircraft family", owned: "owned", leased: "leased",
};

// Only an ordinary capitalised first word is lower-cased in a sentence; "FAA", "MZFW" or "OpenAP" stay as they are.
const ORDINARY_WORD = /^[A-Z][a-z]*(?=[\s,(-]|$)/;

/** Display label for an identifier, e.g. "taxi_out" -> "Taxi-out". Unknown identifiers lose their underscores. */
export function term(id: string | null | undefined): string {
  if (!id) return "unavailable";
  const known = TERMS[id];
  if (known) return known;
  const words = id.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** The same label for use inside a sentence ("Landing charges" -> "landing charges", "MZFW" stays). */
export function termInText(id: string): string {
  const t = term(id);
  return ORDINARY_WORD.test(t) ? t.charAt(0).toLowerCase() + t.slice(1) : t;
}

/** Capitalises the first letter, for API text that starts mid-sentence. */
export const sentence = (text: string) => (text ? text.charAt(0).toUpperCase() + text.slice(1) : text);

/** "a, b, c" -> "a, b and c". */
export function joinWords(items: string[]): string {
  return items.length <= 1 ? items.join("") : `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}

const listOfTerms = (list: string) => joinWords(list.split(/,\s*/).map((x) => termInText(x.trim())));

/** Technical references and engine messages rewritten as plain sentences. Order matters: specific first. */
const RULES: [RegExp, string | ((...m: string[]) => string)][] = [
  [/aircraft_type\.engine_model \(source: OpenAP engine\.default \(one of several engine options\)\)/g,
    "OpenAP aircraft data (its default engine; other engines are available)"],
  [/^source: OpenAP engine\.default \(one of several engine options\)$/, "OpenAP's default engine; other engines are available."],
  [/(?:aircraft_type\.fuel_capacity_kg \()?derived: fuel_capacity_l x 0\.8025 kg\/L \(jet fuel density used by OpenAP mass\.py\)\)?/g,
    "Worked out from the fuel capacity in litres at 0.8025 kg per litre, the jet fuel density OpenAP uses"],
  [/(?:aircraft_type\.cruise_speed_kt \()?derived: true airspeed from cruise_mach at cruise_altitude_m, ISA standard atmosphere \(openap\.aero\.mach2tas\)\)?/g,
    "Worked out from the cruise Mach number at cruise altitude, in the standard atmosphere"],
  [/aircraft_type\.source_id=\d+ \((OpenAP [\d.]+)\)/g, "$1 aircraft data"],
  [/aircraft_type\.\w+ \(source\)/g, "OpenAP aircraft data"],
  [/OpenAP aircraft YAML \(openap\/data\/aircraft\)/g, "OpenAP aircraft data"],
  [/OpenAP engines\.csv max_thrust \(ICAO EEDB rated output\)/g, "OpenAP engine data (rated thrust from the ICAO Engine Emissions Databank)"],
  [/OpenAP engines\.csv (?:bpr|pr)\b/g, "OpenAP engine data (ICAO Engine Emissions Databank)"],
  [/OpenAP mass\.py litre-to-kg factor/g, "OpenAP's litre-to-kilogram factor"],
  [/ \(package metadata\)/g, ""],
  [/The bundled data directory \(openap\/data\/\) contains a GNU GPL v3 LICENSE file/g, "Its data files are under the GNU GPL v3"],
  [/airport\.elevation_ft/g, "OurAirports airport data"],
  [/OpenAP ([\d.]+) WRAP (\w+) default values/g, "typical OpenAP values for the $2"],
  [/Variant -> engine options listed by OpenAP/g, "Engine options for each variant, as listed by OpenAP"],
  [/No OpenAP WRAP kinematic model for (\S+) \(synonyms not used\)/g,
    "OpenAP has no climb, cruise and descent profile for the $1, and we don't borrow one from a similar aircraft"],
  [/No OpenAP drag polar for (\S+) \(synonyms not used\)/g, "OpenAP has no drag data for the $1"],
  [/Default engine (\S+) not found in OpenAP engine databank/g, "OpenAP has no engine data for its default engine, the $1"],
  [/^Route too short to reach (\d+) ft; cruise altitude lowered to (\d+) ft$/,
    (_, a, b) => `The route is too short to climb to ${Number(a).toLocaleString("en-GB")} ft, so the cruise altitude was lowered to ${Number(b).toLocaleString("en-GB")} ft.`],
  [/^No contingency, alternate or final reserve fuel included; not a dispatch fuel plan$/,
    "No contingency, alternate or reserve fuel is included. This is not a fuel plan an airline could fly with."],
  [/^Flight not fully validated; checks not performed: (.+)$/,
    (_, list) => `Not every limit could be checked. There is no published value for: ${listOfTerms(list)}.`],
  [/^revenue cargo payload not provided: RTNM and cost per RTNM are unavailable.*$/,
    "No revenue cargo weight was entered, so revenue tonne-miles (RTNM) and cost per RTNM can't be worked out. The payload in the flight model is only a weight assumption, not paid cargo."],
  [/^RTNM unavailable: revenue cargo payload not provided$/, "RTNM can't be worked out without a revenue cargo weight."],
  [/^complete (COC|TOC|total costs) unavailable: missing (.+)$/,
    (_, what, list) => `There is no complete ${what} figure, because these costs are missing: ${listOfTerms(list)}.`],
  [/^partial: numerator excludes unavailable components \((.+)\)$/,
    (_, list) => `Partial figure. It leaves out ${listOfTerms(list)}, which aren't available.`],
  [/^Part 2 block time \(off-block to on-block\)$/, "block time from the flight model (gate to gate)"],
  [/^modelled_route: modelled route distance from Part 2 \(great_circle\)$/, "route distance from the flight model (great circle)"],
  [/^revenue cargo payload not provided x modelled_route distance$/, "needs a revenue cargo weight"],
  [/^Deterministic scenario outcomes for user-chosen input levels; not forecasts and not probability estimates\.$/,
    "Each point recalculates the cost with one input changed. These are what-if results, not forecasts."],
  [/^No verified aircraft-maintenance price index is available.*$/,
    "There is no reliable price index for aircraft maintenance, so this figure is not adjusted."],
  [/^mixed: (.+)$/, (_, list) => `mixed (${listOfTerms(list.split(/,\s*/).filter((x) => x !== "mixed").join(", "))})`],
  [/^(maximum payload|MZFW) not available from free sources$/i, "No free public source gives this limit for the aircraft."],
  [/^maximum ramp weight not in master data$/i, "There's no published maximum ramp weight for this aircraft."],
  // database notes on aircraft
  [/^OpenAP aircraft model\. Not available from OpenAP: MZFW, maximum payload, variant\. Nominal cruise range is retained in the processed file only and is not a payload-independent range\.$/,
    "Figures come from the OpenAP aircraft model, which doesn't give the MZFW, the maximum payload or the variant. OpenAP's nominal cruise range doesn't state a payload, so it isn't used as a fixed range."],
  [/OpenAP (\w+) models the (\S+) passenger aircraft; its weights and performance are not applicable to the freighter without validation\./g,
    "OpenAP's $1 model is the $2 passenger aircraft, so its weights and performance don't apply to the freighter."],
  [/OpenAP (\w+) models the (\S+) passenger aircraft; not substituted\./g,
    "OpenAP's $1 model is the $2 passenger aircraft, so it isn't used for the freighter."],
  [/Conversion of the (\S+) passenger aircraft\. OpenAP \S+ models the passenger aircraft; conversion changes OEW and payload limits; not substituted\./g,
    "A conversion of the $1 passenger aircraft. OpenAP's $1 model is the passenger version, and the conversion changes the OEW and payload limits, so it isn't used here."],
  [/No OpenAP model for designator (\w+)\. OpenAP's synonym table maps \w+ to (\w+) \(([^)]+)\), a different airframe; this project does not use it\./g,
    "OpenAP has no model for the $1 designator. It would stand in the $2 ($3), which is a different aircraft, so we don't use it."],
  [/Performance and weight fields are NULL pending a documented public source\./g,
    "Performance and weight figures stay empty until a public source documents them."],
  // flight model assumptions
  [/^haversine, spherical Earth, R = 6371\.0088 km \(IUGG mean radius\)$/, "shortest distance over a round Earth (radius 6,371 km)"],
  [/^none \(ground speed = true airspeed\)$/, "none, so ground speed equals airspeed"],
  [/^ISA, no temperature deviation$/, "standard atmosphere, no temperature deviation"],
  [/^100% rated take-off thrust during the take-off roll \(no derate\)$/, "full rated thrust for the takeoff roll (no reduced-thrust takeoff)"],
  [/^not modelled; landing roll at ground idle$/, "not modelled; the landing roll is at ground idle"],
  [/^typical \(mean\) WRAP values; kinematics independent of mass$/, "Typical values for the type. The flight profile doesn't change with weight."],
  [/^WRAP mean cruise altitude rounded to the nearest 1,000 ft$/, "OpenAP's typical cruise altitude, rounded to the nearest 1,000 ft."],
  [/^OpenAP type-level OEW; not operator-specific$/, "OpenAP's OEW for the type, not any particular airline's aircraft."],
  [/^user-supplied planning quantity; no regulatory fuel policy is applied$/, "Set to zero here. No regulatory fuel policy is applied."],
  [/^26 min split equally \(project assumption\); not an observed airport-specific taxi time$/,
    "26 minutes split equally between departure and arrival (our assumption), not a measured time at these airports."],
  [/^1\.0 means no route extension is assumed$/, "1.0 means the shortest path, with no detours."],
  [/^Great-circle distance; no route extension assumed \(not an actual flown route\)$/,
    "Shortest distance over the Earth's surface, with no detours. It isn't the route actually flown."],
  [/^Actual winds can materially change flight time and fuel burn$/, "Real winds can change the flight time and fuel burn a lot."],
  [/^altitude actually used \(may be lower than requested on short routes\)$/, "The altitude actually flown. It can be lower than planned on short routes."],
  [/^idle \(7% rated thrust\) fuel flow for all engines$/, "Idle fuel flow (7 % of rated thrust) for all engines."],
  [/^generic jet fuel density used to convert fuel capacity \(L\) to mass; actual batches vary$/,
    "A typical jet fuel density, used to turn litres into kilograms. Real fuel varies a little."],
  [/^Earth radius 6371\.0088 km; spherical model$/, "Earth treated as a sphere with a radius of 6,371 km."],
  [/ x (?=\d)/g, " × "],
  [/\s*\(retrieved \d{4}-\d{2}-\d{2}\)/g, ""],
];

// Links (official agencies only, after stripping) are kept as they are; other snake_case words are translated.
const IDENTIFIER = /(https?:\/\/\S+)|\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b/g;

/** Rewrites a technical sentence or reference from the API in plain words. */
export function plainText(text: string | null | undefined): string {
  if (!text) return "";
  let out = stripCompanyUrls(text);
  for (const [pattern, replacement] of RULES) {
    out = typeof replacement === "string" ? out.replace(pattern, replacement)
      : out.replace(pattern, (...m: unknown[]) => replacement(...(m.slice(0, -2) as string[])));
  }
  return out.replace(IDENTIFIER, (id, url?: string) => (url ? url : termInText(id)));
}

const UNITS: Record<string, string> = { m2: "m²", m3: "m³", "kg/s": "kg/s", ratio: "", count: "", deg: "°" };

/** Units as they are written, e.g. "m2" -> "m²". */
export const unitText = (unit: string | null | undefined) => (unit ? UNITS[unit] ?? unit : "");

/** Index adjustment periods: "2023-Q04..2024-Q03" -> "Q4 2023 to Q3 2024", "YE2023Q2" -> "year to June 2023". */
export function plainPeriod(period: string | null | undefined): string {
  if (!period) return "";
  const month = (m: string) => new Date(2000, Number(m) - 1, 1).toLocaleString("en-GB", { month: "short" });
  const one = (p: string) => p
    .replace(/^YE(\d{4})Q(\d)$/, (_, y, q) => `year to ${["March", "June", "September", "December"][Number(q) - 1]} ${y}`)
    .replace(/^(\d{4})-Q0?(\d)$/, "Q$2 $1").replace(/^(\d{4})-M(\d{2})$/, (_, y, m) => `${month(m)} ${y}`)
    .replace(/^(\d{4})Q(\d)$/, "Q$2 $1");
  return period.split("..").map(one).join(" to ");
}
