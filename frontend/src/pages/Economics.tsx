import { useState } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, type Json } from "../api";
import { Formula, Formulas } from "../components/Formula";
import { GlossaryTerm } from "../components/GlossaryTerm";
import { ErrorBox, Loading, Notice, PageHeader } from "../components/ui";
import { useApi } from "../components/useApi";
import { label, num } from "../format";
import { joinWords, plainPeriod, plainText, sentence, termInText } from "../plain";
import type { FormulaSpec } from "../types";

const money = (v: string | null | undefined) => (v === null || v === undefined ? null : num(Number(v), 2));

const PER: Record<string, string> = { block_hour: "per block hour", nautical_mile: "per nautical mile", revenue_tonne_nm: "per revenue tonne-mile" };

// Price indices used to bring the FAA figures up to date (U.S. Bureau of Labor Statistics series).
const INDEX_NAME: Record<string, string> = {
  CIU2014300000000I: "the Employment Cost Index for transportation and warehousing workers",
  PCU524126524126: "the Producer Price Index for property and casualty insurers",
};

const UNIT_COSTS: FormulaSpec[] = [
  { result: "Cost per block hour", numerator: "cost of the flight", denominator: "block hours" },
  { result: "Cost per nautical mile", numerator: "cost of the flight", denominator: "distance in nautical miles" },
  { result: "Cost per revenue tonne-mile", numerator: "cost of the flight", denominator: "revenue cargo in tonnes × distance in nautical miles" },
];

const INDEX_ADJUSTMENT: FormulaSpec = { result: "Adjusted value", expression: "published value × (average index in the target period ÷ average index in the base period)" };

export function EconomicsPage() {
  const list = useApi(() => api.economics(), []);
  const [id, setId] = useState(1);
  const detail = useApi(() => api.economicsDetail(id), [id]);
  const [parameter, setParameter] = useState("fuel_price");
  const sens = useApi(() => api.sensitivity(id, parameter, "-20,-10,0,10,20"), [id, parameter]);
  const bench = useApi(() => api.benchmarks("B777F"), []);
  return <>
    <PageHeader title="Operating Economics" subtitle="For the curious: what a flight might cost, what drives that cost, and how it compares with public figures." />
    <div className="mx-auto max-w-7xl space-y-8 px-6 py-8">
      {list.data && <Notice tone="warn">{list.data.notice}</Notice>}
      {list.loading && <Loading />}{list.error && <ErrorBox message={list.error} />}
      {list.data && <div className="card overflow-x-auto"><table className="w-full text-sm">
        <thead className="bg-tint text-left text-xs uppercase text-slate-500"><tr>{["Aircraft", "Route", "Scenario", "Prices as of", "COC so far", "Complete COC", "Costs covered"].map((h) => <th key={h} className="p-2">{h}</th>)}</tr></thead>
        <tbody>{list.data.items.map((e: Json) => <tr key={e.id} onClick={() => setId(e.id)} className={`cursor-pointer border-t ${e.id === id ? "bg-cyan-50" : "hover:bg-tint"}`}>
          <td className="p-2">{e.aircraft}</td><td className="p-2">{e.route.replace("-", " → ")}</td><td className="p-2">{e.scenario}</td><td className="p-2">{e.pricing_date}</td>
          <td className="p-2">{money(e.coc_subtotal)} {e.currency} <span className="badge bg-orange-50 text-orange-800">partial</span></td>
          <td className="p-2">{e.complete_coc ? money(e.complete_coc) : <span className="missing">not available</span>}</td><td className="p-2">{label(e.coverage)}</td></tr>)}</tbody></table></div>}
      {detail.data && <Detail d={detail.data} />}
      <section className="space-y-3"><h2 className="section-title">What if one input changes?</h2>
        <select value={parameter} onChange={(e) => setParameter(e.target.value)} className="rounded border p-2 text-sm" aria-label="Input to change">
          {["fuel_price", "airframe_maintenance_rate", "annual_utilization", "crew_compensation"].map((p) => <option key={p} value={p}>{label(p)}</option>)}</select>
        {sens.loading && <Loading />}{sens.error && <ErrorBox message={sens.error} />}
        {sens.data && <div className="card p-4"><p className="text-xs text-slate-500">{plainText(sens.data.statement)} The figures are partial COC subtotals.</p>
          <ResponsiveContainer width="100%" height={260}><LineChart data={sens.data.rows.map((r: Json) => ({ level: r.variations[0]?.change, coc: Number(r.outputs.coc) }))}>
            <CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="level" unit="%" /><YAxis domain={["auto", "auto"]} /><Tooltip />
            <Line isAnimationActive={false} dataKey="coc" stroke="#00a0d1" strokeWidth={2} name={`COC so far (${sens.data.currency})`} /></LineChart></ResponsiveContainer></div>}
      </section>
      <section className="space-y-3"><h2 className="section-title">Public benchmarks</h2>
        {bench.data && <><Notice>{bench.data.notice}</Notice>
          <div className="grid gap-4 md:grid-cols-2">
            <div className="card space-y-3 p-4"><h3 className="font-semibold text-navy">FAA Economic Values, Table 4-7 (year to June 2023, USD per block hour)</h3>
              <ul className="space-y-2 text-sm">{bench.data.faa_table_4_7.map((f: Json) => <li key={f.category}><span className="font-semibold">{label(f.category)}:</span> {num(Number(f.amount_usd_per_block_hour))} USD per block hour, as published
                {f.adjustments.map((a: Json) => <span key={a.index + a.status} className="block text-xs text-slate-600">{a.status === "adjusted"
                  ? `Adjusted to ${plainPeriod(a.target_period)} with ${INDEX_NAME[a.index] ?? "a price index"}: ${money(a.adjusted)} USD. This index is a stand-in for the real cost and hasn't been approved yet.`
                  : plainText(a.reason)}</span>)}</li>)}</ul>
              <Formula f={INDEX_ADJUSTMENT} /></div>
            {bench.data.bts && <div className="card p-4"><h3 className="font-semibold text-navy">BTS Form 41: Boeing 777F (benchmark only)</h3>
              <p className="text-xs text-slate-600">{bench.data.bts.label}.</p>
              <ul className="mt-2 space-y-1 text-sm">{Object.entries(bench.data.bts.metrics).map(([k, m]: [string, Json]) => <li key={k} className="flex justify-between gap-3">
                <span>{label(k)}</span><span className="text-right">{m ? `${num(m.usd_per_block_hour)} USD per block hour (${m.carriers.length} U.S. ${m.carriers.length === 1 ? "carrier" : "carriers"})` : "not available"}</span></li>)}</ul></div>}
          </div></>}
      </section>
    </div>
  </>;
}

function Detail({ d }: { d: Json }) {
  return <section className="space-y-4"><h2 className="section-title">{d.flight.aircraft_code}: {d.flight.origin} → {d.flight.destination}</h2>
    <p className="text-sm text-slate-600">Scenario "{d.scenario}", with prices as of {d.pricing_date}.</p>
    <ul className="grid gap-2 text-sm md:grid-cols-3">
      <li className="card p-3"><span className="block text-xs uppercase text-slate-500">Costs covered</span>{sentence(termInText(d.dimensions.cost_coverage))}</li>
      <li className="card p-3"><span className="block text-xs uppercase text-slate-500">Flight model</span>{sentence(termInText(d.dimensions.operational_validity))}</li>
      <li className="card p-3"><span className="block text-xs uppercase text-slate-500">Where the figures come from</span>{sentence(plainText(d.dimensions.source_quality))}</li>
    </ul>
    <div className="grid gap-4 md:grid-cols-3">{Object.entries(d.totals).map(([k, t]: [string, Json]) => <div key={k} className="card p-4">
      <p className="text-xs uppercase text-slate-500"><GlossaryTerm slug={k === "coc" ? "coc" : "doc"}>{label(k)}</GlossaryTerm></p>
      <p className="text-2xl font-bold text-navy">{money(t.calculated_subtotal)} {d.currency}</p>
      <p className="text-xs text-orange-800">{t.complete ? "complete" : `Partial. Missing: ${joinWords(t.missing.map(termInText))}.`}</p></div>)}</div>
    <div className="grid gap-4 lg:grid-cols-2">{d.categories.map((c: Json) => <div key={c.category} className="card p-4">
      <h3 className="font-semibold text-navy">{label(c.category)} <span className="text-sm font-normal text-slate-500">
        {c.calculated_subtotal ? `subtotal ${money(c.calculated_subtotal)}` : "no subtotal"}{c.missing.length ? " (partial)" : ""}</span></h3>
      <ul className="mt-2 space-y-1 text-sm">{c.components.map((x: Json) => <li key={x.name} className="flex justify-between gap-3">
        <span>{label(x.name)}</span><span className={x.amount ? "" : "missing"}>{x.amount ? money(x.amount) : x.status === "not_applicable" ? "not applicable" : `not available: ${termInText(x.status)}`}</span></li>)}</ul></div>)}</div>
    <div className="card space-y-3 p-4"><h3 className="font-semibold text-navy">Cost per unit</h3>
      <ul className="space-y-1 text-sm">{d.unit_metrics.map((m: Json) => <li key={m.metric_name + m.cost_measure} className="flex justify-between gap-3">
        <span>{m.label}</span><span className="text-right">{m.metric_value ? `${num(Number(m.metric_value), 2)} ${m.currency} ${PER[m.denominator_unit] ?? ""}`
          : <span className="missing">{m.cost_measure === "complete_total" ? "Not available while some costs are missing."
            : m.warnings[0] ? sentence(plainText(m.warnings[0])) : "Not available."}</span>}</span></li>)}</ul>
      <Formulas items={UNIT_COSTS} /></div>
  </section>;
}
