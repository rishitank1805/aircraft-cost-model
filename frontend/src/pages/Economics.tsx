import { useState } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, type Json } from "../api";
import { GlossaryTerm } from "../components/GlossaryTerm";
import { ErrorBox, Loading, Notice, PageHeader } from "../components/ui";
import { useApi } from "../components/useApi";
import { label, num } from "../format";

const money = (v: string | null | undefined) => (v === null || v === undefined ? null : num(Number(v), 2));

export function EconomicsPage() {
  const list = useApi(() => api.economics(), []);
  const [id, setId] = useState(1);
  const detail = useApi(() => api.economicsDetail(id), [id]);
  const [parameter, setParameter] = useState("fuel_price");
  const sens = useApi(() => api.sensitivity(id, parameter, "-20,-10,0,10,20"), [id, parameter]);
  const bench = useApi(() => api.benchmarks("B777F"), []);
  return <>
    <PageHeader title="Operating Economics" subtitle="Advanced module: the project's Part 3-5 cost estimates, unit costs, sensitivity and public benchmarks." />
    <div className="mx-auto max-w-7xl space-y-8 px-6 py-8">
      {list.data && <Notice tone="warn">{list.data.notice}</Notice>}
      {list.loading && <Loading />}{list.error && <ErrorBox message={list.error} />}
      {list.data && <div className="card overflow-x-auto"><table className="w-full text-sm">
        <thead className="bg-tint text-left text-xs uppercase text-slate-500"><tr>{["Estimate", "Aircraft", "Route", "Scenario", "Pricing date", "COC (calculated subtotal)", "Complete COC", "Coverage"].map((h) => <th key={h} className="p-2">{h}</th>)}</tr></thead>
        <tbody>{list.data.items.map((e: Json) => <tr key={e.id} onClick={() => setId(e.id)} className={`cursor-pointer border-t ${e.id === id ? "bg-cyan-50" : "hover:bg-tint"}`}>
          <td className="p-2">#{e.id}</td><td className="p-2">{e.aircraft}</td><td className="p-2">{e.route}</td><td className="p-2">{e.scenario}</td><td className="p-2">{e.pricing_date}</td>
          <td className="p-2">{money(e.coc_subtotal)} {e.currency} <span className="badge bg-orange-50 text-orange-800">partial</span></td>
          <td className="p-2">{e.complete_coc ? money(e.complete_coc) : <span className="missing">unavailable</span>}</td><td className="p-2">{e.coverage}</td></tr>)}</tbody></table></div>}
      {detail.data && <Detail d={detail.data} />}
      <section className="space-y-3"><h2 className="section-title">Scenario sensitivity</h2>
        <select value={parameter} onChange={(e) => setParameter(e.target.value)} className="rounded border p-2 text-sm" aria-label="Parameter">
          {["fuel_price", "airframe_maintenance_rate", "annual_utilization", "crew_compensation"].map((p) => <option key={p} value={p}>{label(p)}</option>)}</select>
        {sens.loading && <Loading />}{sens.error && <ErrorBox message={sens.error} />}
        {sens.data && <div className="card p-4"><p className="text-xs text-slate-500">{sens.data.statement} Values are PARTIAL calculated COC subtotals.</p>
          <ResponsiveContainer width="100%" height={260}><LineChart data={sens.data.rows.map((r: Json) => ({ level: r.variations[0]?.change, coc: Number(r.outputs.coc) }))}>
            <CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="level" unit="%" /><YAxis domain={["auto", "auto"]} /><Tooltip />
            <Line isAnimationActive={false} dataKey="coc" stroke="#00a0d1" strokeWidth={2} name={`COC subtotal (${sens.data.currency})`} /></LineChart></ResponsiveContainer></div>}
      </section>
      <section className="space-y-3"><h2 className="section-title">Public benchmarks</h2>
        {bench.data && <><Notice>{bench.data.notice}</Notice>
          <div className="grid gap-4 md:grid-cols-2">
            <div className="card p-4"><h3 className="font-semibold text-navy">FAA Economic Values Table 4-7 (YE June 2023, USD per block hour)</h3>
              <ul className="mt-2 space-y-2 text-sm">{bench.data.faa_table_4_7.map((f: Json) => <li key={f.category}><span className="font-semibold">{label(f.category)}</span>: {f.amount_usd_per_block_hour} (original)
                {f.adjustments.map((a: Json) => <span key={a.index + a.status} className="block text-xs text-slate-600">{a.status === "adjusted"
                  ? `Index-adjusted (proxy ${a.index}, ${a.target_period}): ${money(a.adjusted)} - pending owner approval` : `Adjustment unavailable: ${a.reason}`}</span>)}</li>)}</ul></div>
            {bench.data.bts && <div className="card p-4"><h3 className="font-semibold text-navy">BTS Form 41: 777F (benchmark only)</h3>
              <p className="text-xs text-slate-600">{bench.data.bts.label}</p>
              <ul className="mt-2 space-y-1 text-sm">{Object.entries(bench.data.bts.metrics).map(([k, m]: [string, Json]) => <li key={k} className="flex justify-between">
                <span>{label(k)}</span><span>{m ? `${num(m.usd_per_block_hour)} USD/BH (${m.carriers.join(", ")})` : "unavailable"}</span></li>)}</ul></div>}
          </div></>}
      </section>
    </div>
  </>;
}

function Detail({ d }: { d: Json }) {
  return <section className="space-y-4"><h2 className="section-title">Estimate #{d.id}: {d.label}</h2>
    <p className="text-sm text-slate-600">{d.flight.aircraft_code} {d.flight.origin}-{d.flight.destination} · scenario "{d.scenario}" · pricing date {d.pricing_date} ·
      dimensions: coverage <strong>{d.dimensions.cost_coverage}</strong>, validity <strong>{d.dimensions.operational_validity}</strong>, quality <strong>{d.dimensions.source_quality}</strong></p>
    <div className="grid gap-4 md:grid-cols-3">{Object.entries(d.totals).map(([k, t]: [string, Json]) => <div key={k} className="card p-4">
      <p className="text-xs uppercase text-slate-500"><GlossaryTerm slug={k === "coc" ? "coc" : "doc"}>{k.toUpperCase().replace("_", " ")}</GlossaryTerm></p>
      <p className="text-2xl font-bold text-navy">{money(t.calculated_subtotal)} {d.currency}</p>
      <p className="text-xs text-orange-800">{t.complete ? "complete" : `PARTIAL - complete unavailable (missing ${t.missing.join(", ")})`}</p></div>)}</div>
    <div className="grid gap-4 lg:grid-cols-2">{d.categories.map((c: Json) => <div key={c.category} className="card p-4">
      <h3 className="font-semibold text-navy">{label(c.category)} <span className="text-sm font-normal text-slate-500">
        calculated subtotal {c.calculated_subtotal ? money(c.calculated_subtotal) : "N/A"}{c.missing.length ? " (partial)" : ""}</span></h3>
      <ul className="mt-2 space-y-1 text-sm">{c.components.map((x: Json) => <li key={x.name} className="flex justify-between gap-3">
        <span>{label(x.name)}</span><span className={x.amount ? "" : "missing"}>{x.amount ? money(x.amount) : x.status === "not_applicable" ? "n/a" : `N/A - ${label(x.status)}`}</span></li>)}</ul></div>)}</div>
    <div className="card p-4"><h3 className="font-semibold text-navy">Unit costs</h3><ul className="mt-2 space-y-1 text-sm">{d.unit_metrics.map((m: Json) => <li key={m.metric_name + m.cost_measure} className="flex justify-between gap-3">
      <span>{m.label}</span><span>{m.metric_value ? `${num(Number(m.metric_value), 2)} ${m.metric_unit}` : <span className="missing">{m.metric_status}{m.warnings[0] ? ` - ${m.warnings[0]}` : ""}</span>}</span></li>)}</ul></div>
  </section>;
}
