import { Play } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api";
import { GlossaryTerm } from "../components/GlossaryTerm";
import { Accordion, ErrorBox, Loading, Notice, PageHeader } from "../components/ui";
import { useApi } from "../components/useApi";
import { FlightPhasesDiagram } from "../diagrams/Diagrams";
import { Formula } from "../components/Formula";
import { label, num } from "../format";
import { plainText, sentence, termInText, unitText } from "../plain";
import type { FlightResult } from "../types";

const PHASE_COLORS: Record<string, string> = { taxi_out: "#94a3b8", takeoff: "#0f2a6b", climb: "#00a0d1", cruise: "#001450",
  descent: "#38bdf8", landing: "#0f2a6b", landing_roll: "#64748b", taxi_in: "#cbd5e1" };
const PHASE_HELP: [string, string][] = [
  ["Taxi", "Moving on the ground between the gate and the runway. The model uses the engines' idle fuel flow (7 % of rated thrust, from the ICAO engine databank) and allows 13 minutes of taxiing at each end."],
  ["Takeoff", "The aircraft speeds up along the runway at takeoff thrust until it lifts off."],
  ["Climb", "The climb to cruise altitude, at the speeds and climb rates OpenAP gives as typical for the aircraft."],
  ["Cruise", "Level flight at the cruise Mach number. The aircraft gets lighter as it burns fuel."],
  ["Descent", "The engines are throttled back to near idle and the aircraft comes down towards the airport, again following OpenAP's typical profile."],
  ["Landing", "The final approach to touchdown, then the roll along the runway."],
  ["Block time", "The time from leaving the gate to arriving at the gate. Many costs are counted per block hour."],
];

const BLOCK_TIME = { result: "Block time", expression: "taxi-out + time in the air + landing roll + taxi-in" };
const BLOCK_FUEL = { result: "Block fuel", expression: "taxi-out fuel + trip fuel + landing-roll fuel + taxi-in fuel" };
const MASS_LABEL: Record<string, string> = { zero_fuel: "Zero-fuel weight", ramp: "Ramp weight (before taxi)", takeoff: "Takeoff weight",
  landing: "Landing weight", block_in: "Weight on arrival at the gate" };
// Internal settings of the calculation itself; they don't help explain the flight.
const HIDDEN_ASSUMPTIONS = new Set(["fuel_accounting_basis", "time_step_s", "integration_method", "convergence_tolerance_kg"]);

/** "OpenAP 2.6.2: aircraft A320 (Airbus A320), engine CFM56-5B4 x2, ..." -> a plain sentence. */
function aboutModel(model: string): string {
  const m = model.match(/^OpenAP ([\d.]+): aircraft \S+ \((.+?)\), engine (.+?) x(\d+)/);
  return m ? `Worked out with OpenAP ${m[1]} for the ${m[2]}, with ${m[4]} ${m[3]} engines.` : "Worked out with the OpenAP model.";
}

function assumptionValue(a: { value: string; unit: string | null }): string {
  const n = Number(a.value);
  if (a.value !== "" && Number.isFinite(n)) return `${num(n, n % 1 ? 4 : 0)}${a.unit === "%" ? " %" : a.unit && a.unit !== "ratio" ? ` ${unitText(a.unit)}` : ""}`;
  return plainText(a.value);
}

function AirportInput({ id, value, onChange, labelText }: { id: string; value: string; onChange: (v: string) => void; labelText: string }) {
  const [q, setQ] = useState(value);
  const [items, setItems] = useState<{ ident: string; iata: string | null; name: string | null; city: string | null }[]>([]);
  useEffect(() => {
    if (q.length < 2 || q === value) { setItems([]); return; }
    const t = setTimeout(() => api.airports(q).then((r) => setItems(r.items), () => setItems([])), 250);
    return () => clearTimeout(t);
  }, [q, value]);
  return <label className="relative block" htmlFor={id}><span className="text-xs font-semibold uppercase text-slate-500">{labelText}</span>
    <input id={id} value={q} onChange={(e) => { setQ(e.target.value); onChange(e.target.value.toUpperCase()); }} autoComplete="off"
      className="mt-1 w-full rounded-md border border-slate-300 p-2 uppercase focus:border-cyan focus:outline-none" placeholder="Airport code or city" />
    {items.length > 0 && <ul className="absolute z-20 mt-1 max-h-60 w-full overflow-auto rounded-md border bg-white shadow-lg" role="listbox">
      {items.map((a) => <li key={a.ident}><button type="button" className="w-full px-3 py-2 text-left text-sm hover:bg-cyan-50"
        onClick={() => { const code = a.iata ?? a.ident; setQ(code); onChange(code); setItems([]); }}>
        <span className="font-semibold">{a.iata ?? a.ident}</span> {a.name} <span className="text-slate-500">{a.city}</span></button></li>)}</ul>}
  </label>;
}

export function FlightLabPage() {
  const [params] = useSearchParams();
  const supported = useApi(() => api.flightAircraft(), []);
  const [aircraft, setAircraft] = useState(params.get("aircraft") ?? "A320");
  const [origin, setOrigin] = useState(params.get("origin") ?? "FRA");
  const [destination, setDestination] = useState(params.get("destination") ?? "CDG");
  const [payload, setPayload] = useState(Number(params.get("payload") ?? 10000));
  const [result, setResult] = useState<FlightResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const run = (e?: FormEvent) => {
    e?.preventDefault(); setBusy(true); setError(null);
    api.estimateFlight({ aircraft_code: aircraft, origin, destination, payload_kg: payload })
      .then(setResult, (err: Error) => { setResult(null); setError(err.message); }).finally(() => setBusy(false));
  };
  useEffect(() => { if (params.get("run") === "1") run(); }, []); // deep link: ?aircraft=..&origin=..&destination=..&payload=..&run=1
  const notSupported = supported.data && !supported.data.items.some((a) => a.code === aircraft);
  return <>
    <PageHeader title="Flight Performance Lab" subtitle="Pick an aircraft and a route, and see how the flight works out, phase by phase." />
    <div className="mx-auto max-w-7xl space-y-6 px-6 py-8">
      <form onSubmit={run} className="card grid gap-4 p-5 md:grid-cols-5">
        <label className="block md:col-span-2"><span className="text-xs font-semibold uppercase text-slate-500">Aircraft (only those with a flight model)</span>
          <select value={aircraft} onChange={(e) => setAircraft(e.target.value)} className="mt-1 w-full rounded-md border border-slate-300 bg-white p-2">
            {supported.data?.items.map((a) => <option key={a.code} value={a.code}>{a.name} ({a.code})</option>)}
            {notSupported && <option value={aircraft}>{aircraft} (no flight model)</option>}</select></label>
        <AirportInput id="origin" value={origin} onChange={setOrigin} labelText="Origin" />
        <AirportInput id="destination" value={destination} onChange={setDestination} labelText="Destination" />
        <label className="block"><span className="text-xs font-semibold uppercase text-slate-500"><GlossaryTerm slug="payload">Payload</GlossaryTerm> (kg)</span>
          <input type="number" min={0} step={500} value={payload} onChange={(e) => setPayload(Number(e.target.value))}
            className="mt-1 w-full rounded-md border border-slate-300 p-2" /></label>
        <div className="md:col-span-5 flex flex-wrap items-center gap-3">
          <button type="submit" disabled={busy || !!notSupported} className="inline-flex items-center gap-2 rounded bg-cyan px-5 py-2 font-semibold text-white disabled:opacity-50">
            <Play className="h-4 w-4" />{busy ? "Calculating…" : "Calculate flight"}</button>
          <span className="text-xs text-slate-500">{supported.data?.note}</span>
        </div>
      </form>
      {notSupported && <Notice tone="warn">There's no flight model for the {aircraft}. Freighters aren't covered, and a passenger model isn't used in their place.</Notice>}
      {busy && <Loading what="Working out the flight" />}
      {error && <ErrorBox message={error} />}
      {result && <Results r={result} />}
      <section className="space-y-3"><h2 className="section-title">How a flight is built up</h2>
        <div className="grid gap-6 lg:grid-cols-2"><FlightPhasesDiagram />
          <div className="space-y-2">{PHASE_HELP.map(([t, x]) => <Accordion key={t} title={t}><p className="text-sm">{x}</p>
            {t === "Block time" && <div className="mt-2"><Formula f={BLOCK_TIME} /></div>}</Accordion>)}</div></div>
      </section>
    </div>
  </>;
}

function Card({ title, value, sub }: { title: string; value: string; sub?: string }) {
  return <div className="card p-4"><p className="text-xs uppercase text-slate-500">{title}</p><p className="text-2xl font-bold text-navy">{value}</p>
    {sub && <p className="text-xs text-slate-500">{sub}</p>}</div>;
}

function Results({ r }: { r: FlightResult }) {
  const phases = r.phases.map((p) => ({ name: label(p.phase), minutes: p.duration_s / 60, fuel: p.fuel_burn_kg, key: p.phase }));
  const timeline = [Object.fromEntries(phases.map((p) => [p.name, Number(p.minutes.toFixed(2))]))];
  const traj = r.trajectory.map((t) => ({ min: Number(t.time_s) / 60, altitude: Number(t.altitude_ft), mass: Number(t.aircraft_mass_kg) / 1000 }));
  return <section className="space-y-6" aria-live="polite">
    <Notice tone="warn"><strong>Model estimate.</strong> The result is {termInText(r.status)}. {r.labels.join(" ")} Nothing is saved.</Notice>
    <div className="grid gap-4 md:grid-cols-4">
      <Card title="Block time" value={`${num(r.times_min.block, 1)} min`} sub={`${num(r.times_min.block / 60, 2)} block hours`} />
      <Card title="Block fuel" value={`${num(r.fuel_kg.block)} kg`} sub={`${num(r.fuel_kg.per_block_hour)} kg per block hour`} />
      <Card title="Great-circle distance" value={`${num(r.distance.great_circle_nm)} NM`} sub={`route flown in the model: ${num(r.distance.estimated_route_nm)} NM (${termInText(r.distance.method)})`} />
      <Card title="Takeoff weight" value={`${num(r.mass_kg.takeoff)} kg`} sub={`landing ${num(r.mass_kg.landing)} kg`} />
    </div>
    <div className="card p-5"><h3 className="font-semibold text-navy">Where the time goes (minutes)</h3>
      <ResponsiveContainer width="100%" height={110}><BarChart layout="vertical" data={timeline}>
        <XAxis type="number" unit=" min" /><YAxis type="category" hide /><Tooltip /><Legend />
        {phases.map((p) => <Bar isAnimationActive={false} key={p.key} dataKey={p.name} stackId="t" fill={PHASE_COLORS[p.key] ?? "#64748b"} />)}
      </BarChart></ResponsiveContainer></div>
    <div className="grid gap-6 lg:grid-cols-2">
      <div className="card p-5"><h3 className="font-semibold text-navy"><GlossaryTerm slug="fuel-burn">Fuel burn</GlossaryTerm> by phase (kg)</h3>
        <ResponsiveContainer width="100%" height={240}><BarChart data={phases}><CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="name" fontSize={11} /><YAxis /><Tooltip /><Bar isAnimationActive={false} dataKey="fuel" fill="#00a0d1" name="Fuel (kg)" /></BarChart></ResponsiveContainer></div>
      <div className="card p-5"><h3 className="font-semibold text-navy">Altitude and weight in flight</h3>
        <ResponsiveContainer width="100%" height={240}><LineChart data={traj}><CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="min" type="number" unit=" min" tickFormatter={(v) => v.toFixed(0)} /><YAxis yAxisId="a" unit=" ft" /><YAxis yAxisId="m" orientation="right" unit=" t" domain={["auto", "auto"]} />
          <Tooltip /><Legend /><Line isAnimationActive={false} yAxisId="a" dataKey="altitude" stroke="#001450" dot={false} name="Altitude (ft)" />
          <Line isAnimationActive={false} yAxisId="m" dataKey="mass" stroke="#00a0d1" dot={false} name="Weight (t)" /></LineChart></ResponsiveContainer></div>
    </div>
    <div className="grid gap-6 lg:grid-cols-2">
      <div className="card p-5"><h3 className="font-semibold text-navy"><GlossaryTerm slug="block-hours">Block time</GlossaryTerm> breakdown</h3>
        <ul className="mt-2 space-y-1 text-sm">{["taxi_out", "airborne", "landing_roll", "taxi_in"].map((k) => <li key={k} className="flex justify-between">
          <span>{label(k)}</span><span>{num(r.times_min[k], 1)} min</span></li>)}
          <li className="flex justify-between border-t pt-1 font-semibold"><span>Block time</span><span>{num(r.times_min.block, 1)} min</span></li></ul>
        <div className="mt-3 space-y-2"><Formula f={BLOCK_TIME} /><Formula f={BLOCK_FUEL} /></div>
        <h3 className="mt-4 font-semibold text-navy">Weight at each stage</h3>
        <ul className="mt-2 space-y-1 text-sm">{Object.entries(r.mass_kg).map(([k, v]) => <li key={k} className="flex justify-between"><span>{MASS_LABEL[k] ?? label(k)}</span><span>{num(v)} kg</span></li>)}</ul></div>
      <div className="card p-5"><h3 className="font-semibold text-navy">Weight and fuel limits</h3>
        <ul className="mt-2 space-y-1 text-sm">{r.checks.map((c) => <li key={c.name} className="flex justify-between gap-3">
          <span>{label(c.name)}</span><span className={`text-right ${c.status === "passed" ? "text-ok" : c.status === "not_performed" ? "text-slate-500" : "text-danger"}`}>
            {label(c.status)}{c.limit !== null && c.value !== null && c.limit > 0 ? ` (${num(c.value)} of ${num(c.limit)} ${c.unit} allowed)` : ""}
            {c.status === "not_performed" && c.note && <span className="block text-[11px]">{sentence(plainText(c.note))}</span>}</span></li>)}</ul>
        <p className="mt-3 text-xs text-slate-500">"Not checked" means there's no certified limit to compare against. Those checks are never counted as passed.</p></div>
    </div>
    <details className="card p-4"><summary className="cursor-pointer font-semibold text-navy">How this was worked out: assumptions and warnings</summary>
      <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-amber-800">{r.warnings.map((w) => <li key={w}>{sentence(plainText(w))}</li>)}</ul>
      <table className="mt-3 w-full text-xs"><tbody>{r.assumptions.filter((a) => !HIDDEN_ASSUMPTIONS.has(a.name)).map((a) => <tr key={a.name} className="border-t border-slate-100 align-top">
        <td className="py-1 pr-3 font-semibold">{label(a.name)}</td><td className="py-1 pr-3">{assumptionValue(a)}</td>
        <td className="py-1 pr-3 text-slate-500">{label(a.source_type)}</td><td className="py-1 text-slate-600">{plainText(a.notes)}</td></tr>)}</tbody></table>
      <p className="mt-2 text-xs text-slate-500">{aboutModel(r.model)}</p></details>
  </section>;
}
