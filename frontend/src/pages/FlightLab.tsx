import { Play } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api";
import { GlossaryTerm } from "../components/GlossaryTerm";
import { Accordion, ErrorBox, Loading, Notice, PageHeader } from "../components/ui";
import { useApi } from "../components/useApi";
import { FlightPhasesDiagram } from "../diagrams/Diagrams";
import { label, num } from "../format";
import type { FlightResult } from "../types";

const PHASE_COLORS: Record<string, string> = { taxi_out: "#94a3b8", takeoff: "#0f2a6b", climb: "#00a0d1", cruise: "#001450",
  descent: "#38bdf8", landing: "#0f2a6b", landing_roll: "#64748b", taxi_in: "#cbd5e1" };
const PHASE_HELP: [string, string][] = [
  ["Taxi", "Moving on the ground between gate and runway. The model uses idle fuel flow (ICAO databank, 7 % thrust) with all engines running and default taxi times (13 + 13 min)."],
  ["Takeoff", "Acceleration on the runway at takeoff thrust until lift-off."],
  ["Climb", "Climb to cruise altitude following the OpenAP WRAP speed and vertical-rate profile."],
  ["Cruise", "Level flight at the cruise Mach number; the aircraft gets lighter as fuel burns."],
  ["Descent", "Idle-thrust-like descent following the WRAP profile to the approach."],
  ["Landing", "Final approach to touchdown, then the landing roll on the runway."],
  ["Block time", "From off-block to on-block: taxi-out + flight + landing roll + taxi-in. Many costs are measured per block hour."],
];

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
      className="mt-1 w-full rounded-md border border-slate-300 p-2 uppercase focus:border-cyan focus:outline-none" placeholder="IATA/ICAO or city" />
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
    <PageHeader title="Flight Performance Lab" subtitle="Run the project's OpenAP-based flight model for supported aircraft and see how a flight is built up." />
    <div className="mx-auto max-w-7xl space-y-6 px-6 py-8">
      <form onSubmit={run} className="card grid gap-4 p-5 md:grid-cols-5">
        <label className="block md:col-span-2"><span className="text-xs font-semibold uppercase text-slate-500">Aircraft (supported models only)</span>
          <select value={aircraft} onChange={(e) => setAircraft(e.target.value)} className="mt-1 w-full rounded-md border border-slate-300 bg-white p-2">
            {supported.data?.items.map((a) => <option key={a.code} value={a.code}>{a.name} ({a.code})</option>)}
            {notSupported && <option value={aircraft}>{aircraft} (not supported)</option>}</select></label>
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
      {notSupported && <Notice tone="warn">{aircraft} has no supported performance model. Freighters are not supported and no passenger model is substituted.</Notice>}
      {busy && <Loading what="Running the flight model" />}
      {error && <ErrorBox message={error} />}
      {result && <Results r={result} />}
      <section className="space-y-3"><h2 className="section-title">How a flight is built up</h2>
        <div className="grid gap-6 lg:grid-cols-2"><FlightPhasesDiagram />
          <div className="space-y-2">{PHASE_HELP.map(([t, x]) => <Accordion key={t} title={t}><p className="text-sm">{x}</p></Accordion>)}</div></div>
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
    <Notice tone="warn"><strong>Model estimate - {label(r.status)}.</strong> {r.labels.join(" ")} Not saved to the database.</Notice>
    <div className="grid gap-4 md:grid-cols-4">
      <Card title="Block time" value={`${num(r.times_min.block, 1)} min`} sub={`${num(r.times_min.block / 60, 2)} block hours`} />
      <Card title="Block fuel" value={`${num(r.fuel_kg.block)} kg`} sub={`${num(r.fuel_kg.per_block_hour)} kg per block hour`} />
      <Card title="Great-circle distance" value={`${num(r.distance.great_circle_nm)} NM`} sub={`modelled route ${num(r.distance.estimated_route_nm)} NM (${r.distance.method})`} />
      <Card title="Takeoff mass" value={`${num(r.mass_kg.takeoff)} kg`} sub={`landing ${num(r.mass_kg.landing)} kg`} />
    </div>
    <div className="card p-5"><h3 className="font-semibold text-navy">Phase timeline (minutes)</h3>
      <ResponsiveContainer width="100%" height={110}><BarChart layout="vertical" data={timeline}>
        <XAxis type="number" unit=" min" /><YAxis type="category" hide /><Tooltip /><Legend />
        {phases.map((p) => <Bar isAnimationActive={false} key={p.key} dataKey={p.name} stackId="t" fill={PHASE_COLORS[p.key] ?? "#64748b"} />)}
      </BarChart></ResponsiveContainer></div>
    <div className="grid gap-6 lg:grid-cols-2">
      <div className="card p-5"><h3 className="font-semibold text-navy"><GlossaryTerm slug="fuel-burn">Fuel burn</GlossaryTerm> by phase (kg)</h3>
        <ResponsiveContainer width="100%" height={240}><BarChart data={phases}><CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="name" fontSize={11} /><YAxis /><Tooltip /><Bar isAnimationActive={false} dataKey="fuel" fill="#00a0d1" name="Fuel (kg)" /></BarChart></ResponsiveContainer></div>
      <div className="card p-5"><h3 className="font-semibold text-navy">Altitude and aircraft mass (airborne)</h3>
        <ResponsiveContainer width="100%" height={240}><LineChart data={traj}><CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="min" type="number" unit=" min" tickFormatter={(v) => v.toFixed(0)} /><YAxis yAxisId="a" unit=" ft" /><YAxis yAxisId="m" orientation="right" unit=" t" domain={["auto", "auto"]} />
          <Tooltip /><Legend /><Line isAnimationActive={false} yAxisId="a" dataKey="altitude" stroke="#001450" dot={false} name="Altitude (ft)" />
          <Line isAnimationActive={false} yAxisId="m" dataKey="mass" stroke="#00a0d1" dot={false} name="Mass (t)" /></LineChart></ResponsiveContainer></div>
    </div>
    <div className="grid gap-6 lg:grid-cols-2">
      <div className="card p-5"><h3 className="font-semibold text-navy"><GlossaryTerm slug="block-hours">Block time</GlossaryTerm> breakdown</h3>
        <ul className="mt-2 space-y-1 text-sm">{["taxi_out", "airborne", "landing_roll", "taxi_in"].map((k) => <li key={k} className="flex justify-between">
          <span>{label(k)}</span><span>{num(r.times_min[k], 1)} min</span></li>)}
          <li className="flex justify-between border-t pt-1 font-semibold"><span>Block</span><span>{num(r.times_min.block, 1)} min</span></li></ul>
        <h3 className="mt-4 font-semibold text-navy">Mass at each boundary</h3>
        <ul className="mt-2 space-y-1 text-sm">{Object.entries(r.mass_kg).map(([k, v]) => <li key={k} className="flex justify-between"><span>{label(k)}</span><span>{num(v)} kg</span></li>)}</ul></div>
      <div className="card p-5"><h3 className="font-semibold text-navy">Limit checks</h3>
        <ul className="mt-2 space-y-1 text-sm">{r.checks.map((c) => <li key={c.name} className="flex justify-between gap-3">
          <span>{label(c.name)}</span><span className={c.status === "passed" ? "text-ok" : c.status === "not_performed" ? "text-slate-500" : "text-danger"}>
            {label(c.status)}{c.limit !== null && c.value !== null ? ` (${num(c.value)} / ${num(c.limit)} ${c.unit})` : ""}</span></li>)}</ul>
        <p className="mt-3 text-xs text-slate-500">Checks marked "not performed" lack a certified limit in the database - they are never shown as passed.</p></div>
    </div>
    <details className="card p-4"><summary className="cursor-pointer font-semibold text-navy">Assumptions ({r.assumptions.length}) and warnings ({r.warnings.length})</summary>
      <ul className="mt-2 space-y-1 text-xs">{r.assumptions.map((a) => <li key={a.name}><span className="font-semibold">{label(a.name)}</span>: {a.value} {a.unit ?? ""} [{a.source_type}] {a.notes}</li>)}</ul>
      <ul className="mt-2 list-disc pl-5 text-xs text-amber-800">{r.warnings.map((w) => <li key={w}>{w}</li>)}</ul>
      <p className="mt-2 text-xs text-slate-500">Model chain: {r.model}</p></details>
  </section>;
}
