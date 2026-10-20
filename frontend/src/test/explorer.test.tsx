import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { GlossaryTerm } from "../components/GlossaryTerm";
import { SpecTable } from "../components/SpecTable";
import { formatSpec } from "../format";
import { AircraftDetailPage } from "../pages/AircraftDetail";
import { LibraryPage } from "../pages/Library";
import { detail, mockFetch, spec, summary } from "./fixtures";

afterEach(() => vi.unstubAllGlobals());

describe("formatting", () => {
  it("never shows a missing value as zero", () => {
    expect(formatSpec({ value: null, value_text: null, unit: "kg" })).toBe("unavailable");
    expect(formatSpec({ value: 93500, value_text: null, unit: "kg" })).toBe("93,500 kg (93.5 t)");
    expect(formatSpec({ value: 5000, value_text: null, unit: "NM" })).toBe("5,000 NM (9,260 km)");
    expect(formatSpec({ value: null, value_text: "14 AAY container positions", unit: null })).toBe("14 AAY container positions");
  });
});

describe("SpecTable", () => {
  it("lists missing specifications and reveals provenance", async () => {
    render(<MemoryRouter><SpecTable values={[spec({})]} missing={["oew_kg"]} missingLabels={{ oew_kg: "Operating empty weight (OEW)" }} /></MemoryRouter>);
    expect(screen.getByText("Operating empty weight (OEW)")).toBeInTheDocument();
    expect(screen.getByText(/No verified source has been found yet/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /93,500 kg/ }));
    expect(screen.getByText("EFW page")).toBeInTheDocument();
    expect(screen.getByText("93,5 t")).toBeInTheDocument();
  });

  it("strikes through values that are inconsistent in their source", () => {
    render(<MemoryRouter><SpecTable values={[spec({ value: 187000, verification_status: "source_inconsistent", primary: false })]} /></MemoryRouter>);
    expect(screen.getByText("187,000 kg (187 t)")).toHaveClass("line-through");
    expect(screen.getByText(/Inconsistent in source/)).toBeInTheDocument();
  });
});

describe("GlossaryTerm", () => {
  it("shows the definition in context", async () => {
    vi.stubGlobal("fetch", mockFetch({ "/glossary/mzfw": { slug: "mzfw", term: "Maximum Zero-Fuel Weight (MZFW)",
      definition: "The maximum authorized weight of an aircraft without fuel." } }));
    render(<MemoryRouter><GlossaryTerm slug="mzfw">MZFW</GlossaryTerm></MemoryRouter>);
    await userEvent.hover(screen.getByRole("button", { name: /MZFW/ }));
    expect(await screen.findByRole("tooltip")).toHaveTextContent("without fuel");
  });
});

describe("Library", () => {
  it("renders cards with role, support status and visible gaps", async () => {
    vi.stubGlobal("fetch", mockFetch({ "/aircraft": { total: 2, count: 2, notes: ["Unknown values are shown as unavailable."],
      facets: { manufacturer: ["Airbus"], role: ["cargo", "passenger"] },
      items: [summary(), summary({ code: "A320", name: "Airbus A320", role: "passenger", freighter_type: null, mtow_kg: null,
        engine_count: 2, flight_model_supported: true })] } }));
    render(<MemoryRouter initialEntries={["/aircraft"]}><LibraryPage /></MemoryRouter>);
    const card = (await screen.findByText("Airbus A320")).closest("a")!;
    expect(within(card).getByText("Flight model")).toBeInTheDocument();
    expect(within(card).getByText("unavailable")).toBeInTheDocument(); // MTOW missing, not 0
    expect(screen.getByText("Converted freighter (P2F)")).toBeInTheDocument();
  });
});

describe("Aircraft detail", () => {
  it("does not draw a weight diagram from assumptions when OEW is missing", async () => {
    vi.stubGlobal("fetch", mockFetch({ "/aircraft/A321P2F": detail() }));
    render(<MemoryRouter initialEntries={["/aircraft/A321P2F"]}><Routes><Route path="/aircraft/:code" element={<AircraftDetailPage />} /></Routes></MemoryRouter>);
    expect(await screen.findByRole("heading", { level: 1, name: "Airbus A321P2F" })).toBeInTheDocument();
    expect(screen.getByText(/isn't drawn from guesses/)).toHaveTextContent("missing: OEW");
    expect(screen.getByText(/no licensed photograph/)).toBeInTheDocument();
    await waitFor(() => expect(screen.getAllByText("Overall length").length).toBeGreaterThan(0));
  });
});

describe("external links", () => {
  it("links only official public agencies and shows company sources as plain text", async () => {
    const { isAgencyUrl, stripCompanyUrls } = await import("../links");
    expect(isAgencyUrl("https://www.faa.gov/x")).toBe(true);
    expect(isAgencyUrl("https://www.grc.nasa.gov/www")).toBe(true);
    expect(isAgencyUrl("https://www.elbeflugzeugwerke.com/en/")).toBe(false);
    expect(isAgencyUrl("https://www.boeing.com/commercial/freighters")).toBe(false);
    expect(stripCompanyUrls("Boeing: https://www.boeing.com/commercial/freighters (retrieved 2026-10-16)")).toBe("Boeing (retrieved 2026-10-16)");
    const { References } = await import("../components/ui");
    render(<References refs={[{ title: "A330-200F", publisher: "Airbus", url: "https://www.aircraft.airbus.com/x" },
      { title: "Handbook", publisher: "FAA", url: "https://www.faa.gov/h.pdf" }]} />);
    expect(screen.getByText("Airbus: A330-200F").closest("a")).toBeNull();
    expect(screen.getByRole("link")).toHaveAttribute("href", "https://www.faa.gov/h.pdf");
  });
});

describe("plain language", () => {
  it("shows identifiers and technical references as plain words", async () => {
    const { plainText, plainPeriod, term } = await import("../plain");
    expect(term("calculated_limits_unverified")).toBe("calculated, but some weight limits could not be checked");
    expect(term("taxi_out")).toBe("Taxi-out");
    expect(term("some_new_status")).toBe("Some new status");
    expect(plainText("aircraft_type.mtow_kg (source)")).toBe("OpenAP aircraft data");
    expect(plainText("OpenAP engines.csv bpr")).toBe("OpenAP engine data (ICAO Engine Emissions Databank)");
    expect(plainText("Flight not fully validated; checks not performed: max_payload, mzfw, max_ramp_weight"))
      .toBe("Not every limit could be checked. There is no published value for: maximum payload, MZFW and maximum ramp weight.");
    expect(plainText("complete COC unavailable: missing navigation, terminal_navigation, landing, ground_handling"))
      .toBe("There is no complete COC figure, because these costs are missing: en-route navigation charges, terminal navigation charges, landing charges and ground handling.");
    expect(plainText("mixed: explicit_user_assumption, public_market_benchmark")).toBe("mixed (illustrative assumption and public market price)");
    expect(plainText("values come from different sources: faa_aircraft_characteristics_database, openap_aircraft_properties"))
      .toBe("values come from different sources: FAA Aircraft Characteristics Database, OpenAP aircraft data");
    expect(plainText("capacity 24,210 L x 0.8025 kg/L")).toBe("capacity 24,210 L × 0.8025 kg/L");
    expect(plainPeriod("2023-Q04..2024-Q03")).toBe("Q4 2023 to Q3 2024");
    expect(plainPeriod("YE2023Q2")).toBe("year to June 2023");
    // nothing that looks like code is left
    for (const text of ["aircraft_type.cruise_speed_kt (derived: true airspeed from cruise_mach at cruise_altitude_m, ISA standard atmosphere (openap.aero.mach2tas))",
      "No OpenAP WRAP kinematic model for A19N (synonyms not used)", "OpenAP mass.py litre-to-kg factor"]) {
      expect(plainText(text)).not.toMatch(/[a-z]+_[a-z]+|\.py|\.csv|\(source\)|synonyms/);
    }
  });

  it("sets formulas as maths, with a fraction bar for division", async () => {
    const { Formula } = await import("../components/Formula");
    const { container } = render(<Formula f={{ result: "TSFC", numerator: "fuel flow", denominator: "thrust" }} />);
    expect(container.querySelector(".frac")).toHaveTextContent("fuel flowthrust");
    expect(screen.getByRole("math")).toHaveTextContent("TSFC=fuel flowthrust");
    expect(container.textContent).not.toMatch(/[*/]/);
  });
});
