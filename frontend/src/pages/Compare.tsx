import { AlertTriangle, CheckCircle2 } from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api";
import { GlossaryTerm } from "../components/GlossaryTerm";
import { ErrorBox, Loading, Notice, PageHeader, RoleBadge } from "../components/ui";
import { useApi } from "../components/useApi";
import { formatSpec, label } from "../format";
import type { CompareRow } from "../types";

const COLORS = ["#001450", "#00a0d1", "#f59e0b"];

export function ComparePage() {
  const [params, setParams] = useSearchParams();
  const selected = (params.get("codes") ?? "A320,A321").split(",").filter(Boolean);
  const list = useApi(() => api.aircraft(), []);
  const ready = selected.length >= 2 && selected.length <= 3;
  const cmp = useApi(() => (ready ? api.compare(selected) : Promise.resolve(null)), [selected.join(",")]);
  const setSlot = (i: number, code: string) => {
    const next = [...selected];
    if (code) next[i] = code; else next.splice(i, 1);
    setParams({ codes: [...new Set(next.filter(Boolean))].join(",") }, { replace: true });
  };
  const rows = cmp.data?.rows ?? [];
  const charts = rows.filter((r) => r.like_for_like && r.cells.every((c) => c?.value !== null && c?.value !== undefined)
    && ["m", "kg", "kN", "L"].includes(r.cells[0]?.unit ?? ""));
  return <>
    <PageHeader title="Compare Aircraft" subtitle="Select two or three aircraft. Only values with the same source, unit and condition are treated as like-for-like." />
    <div className="mx-auto max-w-7xl space-y-6 px-6 py-8">
      <div className="grid gap-3 md:grid-cols-3">
        {[0, 1, 2].map((i) => <label key={i} className="block"><span className="text-xs font-semibold uppercase text-slate-500">Aircraft {i + 1}{i === 2 && " (optional)"}</span>
          <select value={selected[i] ?? ""} onChange={(e) => setSlot(i, e.target.value)} className="mt-1 w-full rounded-md border border-slate-300 bg-white p-2">
            <option value="">{i === 2 ? "None" : "Select…"}</option>
            {list.data?.items.map((a) => <option key={a.code} value={a.code}>{a.name} ({a.code})</option>)}
          </select></label>)}
      </div>
      {!ready && <Notice>Select at least two different aircraft.</Notice>}
      {cmp.loading && ready && <Loading what="Comparing" />}{cmp.error && <ErrorBox message={cmp.error} />}
      {cmp.data && <>
        <Notice>{cmp.data.rule}</Notice>
        <div className="card overflow-x-auto"><table className="w-full text-sm">
          <thead className="bg-tint"><tr><th className="p-3 text-left">Specification</th>
            {cmp.data.aircraft.map((a, i) => <th key={a.code} className="p-3 text-left" style={{ color: COLORS[i] }}>{a.name}
              <span className="block"><RoleBadge role={a.role} freighterType={a.freighter_type} /></span></th>)}
            <th className="p-3 text-left">Comparable?</th></tr></thead>
          <tbody>{rows.map((r) => <Row key={r.key} r={r} />)}</tbody>
        </table></div>
        {charts.length > 0 && <div className="grid gap-4 md:grid-cols-2">{charts.map((r) => <div key={r.key} className="card p-4">
          <h3 className="font-semibold text-navy">{r.label} ({r.cells[0]?.unit})</h3>
          <p className="text-xs text-slate-500">Source: {r.cells[0]?.source_name}</p>
          <ResponsiveContainer width="100%" height={200}><BarChart data={[Object.fromEntries(cmp.data!.aircraft.map((a, i) => [a.code, r.cells[i]?.value]))]}>
            <CartesianGrid strokeDasharray="3 3" /><XAxis hide /><YAxis /><Tooltip /><Legend />
            {cmp.data!.aircraft.map((a, i) => <Bar isAnimationActive={false} key={a.code} dataKey={a.code} fill={COLORS[i]} />)}
          </BarChart></ResponsiveContainer></div>)}</div>}
      </>}
    </div>
  </>;
}

function Row({ r }: { r: CompareRow }) {
  return <tr className="border-t border-slate-100 align-top">
    <td className="p-3 font-medium">{r.glossary ? <GlossaryTerm slug={r.glossary}>{r.label}</GlossaryTerm> : r.label}
      <span className="block text-xs text-slate-400">{label(r.section)}</span>
      {r.why_it_matters && <span className="block text-xs text-slate-500">{r.why_it_matters}</span>}</td>
    {r.cells.map((c, i) => <td key={i} className="p-3">{c ? <><span className="font-semibold">{formatSpec(c)}</span>
      <span className="block text-[11px] text-slate-500">{c.source_dataset}{c.condition ? ` · ${c.condition}` : ""}</span></>
      : <span className="missing">unavailable</span>}</td>)}
    <td className="p-3 text-xs">{r.like_for_like
      ? <span className="inline-flex items-center gap-1 text-ok"><CheckCircle2 className="h-4 w-4" />like-for-like</span>
      : <span className="text-amber-700"><AlertTriangle className="mr-1 inline h-4 w-4" />{r.issues.join("; ")}</span>}</td>
  </tr>;
}
