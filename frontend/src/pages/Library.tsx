import { LayoutGrid, Search, Table2 } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { ErrorBox, Loading, Notice, PageHeader, RoleBadge, SupportBadge } from "../components/ui";
import { Silhouette } from "../components/Silhouette";
import { useApi } from "../components/useApi";
import { label, num } from "../format";
import type { AircraftSummary } from "../types";

const FILTERS: { key: string; title: string }[] = [
  { key: "manufacturer", title: "Manufacturer" }, { key: "series", title: "Model series" }, { key: "role", title: "Role" },
  { key: "freighter_type", title: "Freighter type" }, { key: "body_class", title: "Body type" }, { key: "engine_count", title: "Engines" },
];

export function LibraryPage() {
  const [params, setParams] = useSearchParams();
  const [view, setView] = useState<"cards" | "table">("cards");
  const query = Object.fromEntries(params.entries());
  const { data, error, loading } = useApi(() => api.aircraft(query), [params.toString()]);
  const set = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value); else next.delete(key);
    setParams(next, { replace: true });
  };
  const items = data?.items ?? [];
  const sorted = useMemo(() => [...items].sort((a, b) => a.name.localeCompare(b.name)), [items]);
  // Totals for the whole library, independent of the filters.
  const all = useApi(() => api.aircraft(), []);
  const stats: [string, number | undefined][] = [["Aircraft types", all.data?.total],
    ["Freighters", all.data?.items.filter((a) => a.role === "cargo").length],
    ["With a flight model", all.data?.items.filter((a) => a.flight_model_supported).length]];

  return <>
    <PageHeader title="Aircraft Library" subtitle="Browse every aircraft type in the database. If a figure isn't known, it says so. Nothing is guessed.">
      <dl className="mt-8 grid max-w-2xl grid-cols-3 gap-6">
        {stats.map(([t, v]) => <div key={t}><dt className="text-sm text-white/70">{t}</dt><dd className="text-3xl font-bold">{v ?? "…"}</dd></div>)}
      </dl>
    </PageHeader>
    <div className="mx-auto max-w-7xl px-6 py-8">
      <div className="grid gap-6 lg:grid-cols-[260px_1fr]">
        <aside className="space-y-4" aria-label="Filters">
          <label className="block"><span className="text-xs font-semibold uppercase text-slate-500">Search</span>
            <div className="relative mt-1"><Search className="absolute left-2 top-2.5 h-4 w-4 text-slate-400" />
              <input value={query.search ?? ""} onChange={(e) => set("search", e.target.value)} placeholder="Name, code or ICAO designator"
                className="w-full rounded-md border border-slate-300 py-2 pl-8 pr-2 focus:border-cyan focus:outline-none" /></div></label>
          {FILTERS.map(({ key, title }) => <label key={key} className="block">
            <span className="text-xs font-semibold uppercase text-slate-500">{title}</span>
            <select value={query[key] ?? ""} onChange={(e) => set(key, e.target.value)}
              className="mt-1 w-full rounded-md border border-slate-300 bg-white p-2 focus:border-cyan focus:outline-none">
              <option value="">All</option>
              {(data?.facets[key] ?? []).map((v) => <option key={v} value={v}>{label(v)}</option>)}
            </select></label>)}
          <label className="block"><span className="text-xs font-semibold uppercase text-slate-500">Flight model</span>
            <select value={query.flight_model ?? ""} onChange={(e) => set("flight_model", e.target.value)}
              className="mt-1 w-full rounded-md border border-slate-300 bg-white p-2">
              <option value="">All</option><option value="true">Available</option><option value="false">Not available</option></select></label>
          {data && <ul className="space-y-1 text-xs text-slate-500">{data.notes.map((n) => <li key={n}>• {n}</li>)}</ul>}
        </aside>
        <section>
          <div className="mb-4 flex items-center justify-between">
            <p className="text-sm text-slate-600">{data ? `${data.count} of ${data.total} aircraft` : ""}</p>
            <div className="flex gap-1" role="group" aria-label="View">
              <button type="button" aria-pressed={view === "cards"} onClick={() => setView("cards")}
                className={`rounded p-2 ${view === "cards" ? "bg-navy text-white" : "bg-tint"}`}><LayoutGrid className="h-4 w-4" /><span className="sr-only">Cards</span></button>
              <button type="button" aria-pressed={view === "table"} onClick={() => setView("table")}
                className={`rounded p-2 ${view === "table" ? "bg-navy text-white" : "bg-tint"}`}><Table2 className="h-4 w-4" /><span className="sr-only">Table</span></button>
            </div>
          </div>
          {loading && <Loading what="Loading aircraft" />}
          {error && <ErrorBox message={error} />}
          {data && !sorted.length && <Notice>No aircraft match these filters.</Notice>}
          {data && view === "cards" && <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{sorted.map((a) => <AircraftCard key={a.code} a={a} />)}</div>}
          {data && view === "table" && <AircraftTable items={sorted} />}
        </section>
      </div>
    </div>
  </>;
}

function AircraftCard({ a }: { a: AircraftSummary }) {
  return <Link to={`/aircraft/${encodeURIComponent(a.code)}`} className="card group overflow-hidden transition hover:-translate-y-0.5 hover:shadow-md">
    <Silhouette bodyClass={a.body_class} engines={a.engine_count} freighter={a.role === "cargo"} />
    <div className="space-y-2 p-4">
      <div className="flex items-start justify-between gap-2">
        <div><h3 className="font-bold text-navy group-hover:text-cyan">{a.name}</h3>
          <p className="text-xs text-slate-500">{a.code}{a.icao_type_designator ? ` · ICAO ${a.icao_type_designator}` : ""}{a.series ? ` · ${a.series} series` : ""}</p></div>
      </div>
      <div className="flex flex-wrap gap-1"><RoleBadge role={a.role} freighterType={a.freighter_type} /><SupportBadge supported={a.flight_model_supported} />
        {a.body_class ? <span className="badge bg-tint text-navy">{label(a.body_class)}</span> : <span className="badge bg-tint text-slate-400">body type not documented</span>}</div>
      <p className="text-xs text-slate-600">MTOW {a.mtow_kg ? `${num(a.mtow_kg / 1000, 1)} t` : <span className="missing">unavailable</span>}
        {" · "}{a.engine_count ? `${a.engine_count} engines` : <span className="missing">engines unavailable</span>}</p>
      <div aria-label="Key specification coverage" className="h-1.5 rounded bg-tint">
        <div className="h-1.5 rounded bg-cyan" style={{ width: `${(a.key_spec_coverage.present / a.key_spec_coverage.expected) * 100}%` }} /></div>
      <p className="text-[11px] text-slate-500">{a.key_spec_coverage.present} of {a.key_spec_coverage.expected} key figures have a source</p>
    </div>
  </Link>;
}

function AircraftTable({ items }: { items: AircraftSummary[] }) {
  return <div className="card overflow-x-auto"><table className="w-full text-sm">
    <thead className="bg-tint text-left text-xs uppercase text-slate-500"><tr>
      {["Aircraft", "Code", "Manufacturer", "Series", "Role", "Body", "Engines", "MTOW", "Flight model", "Key figures"].map((h) => <th key={h} className="p-2">{h}</th>)}</tr></thead>
    <tbody>{items.map((a) => <tr key={a.code} className="border-t border-slate-100 hover:bg-cyan-50">
      <td className="p-2 font-semibold"><Link className="text-navy hover:text-cyan" to={`/aircraft/${encodeURIComponent(a.code)}`}>{a.name}</Link></td>
      <td className="p-2">{a.code}</td><td className="p-2">{a.manufacturer ?? <span className="missing">unavailable</span>}</td>
      <td className="p-2">{a.series ?? <span className="missing">-</span>}</td>
      <td className="p-2"><RoleBadge role={a.role} freighterType={a.freighter_type} /></td>
      <td className="p-2">{a.body_class ? label(a.body_class) : <span className="missing">not documented</span>}</td>
      <td className="p-2">{a.engine_count ?? <span className="missing">unavailable</span>}</td>
      <td className="p-2">{a.mtow_kg ? `${num(a.mtow_kg)} kg` : <span className="missing">unavailable</span>}</td>
      <td className="p-2"><SupportBadge supported={a.flight_model_supported} /></td>
      <td className="p-2">{a.key_spec_coverage.present} of {a.key_spec_coverage.expected}</td></tr>)}</tbody>
  </table></div>;
}
