import { AlertTriangle, CheckCircle2, ChevronDown, CircleSlash, ExternalLink, Info, Loader2 } from "lucide-react";
import { useState, type ReactNode } from "react";
import type { Reference } from "../types";
import { SOURCE_TYPE_LABEL, STATUS_LABEL, label } from "../format";
import { isAgencyUrl } from "../links";

export function Loading({ what = "Loading" }: { what?: string }) {
  return <div className="flex items-center gap-2 py-10 text-slate-500"><Loader2 className="h-5 w-5 animate-spin" />{what}…</div>;
}

export function ErrorBox({ message }: { message: string }) {
  return <div role="alert" className="rounded-md border border-danger/30 bg-red-50 p-4 text-danger">
    <AlertTriangle className="mr-2 inline h-4 w-4" />{message}</div>;
}

export function Notice({ children, tone = "info" }: { children: ReactNode; tone?: "info" | "warn" }) {
  const cls = tone === "warn" ? "border-warn/40 bg-orange-50 text-orange-900" : "border-cyan/30 bg-cyan-50 text-navy";
  return <div className={`flex gap-2 rounded-md border p-3 text-sm ${cls}`}>
    {tone === "warn" ? <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /> : <Info className="mt-0.5 h-4 w-4 shrink-0" />}
    <div>{children}</div></div>;
}

export function RoleBadge({ role, freighterType }: { role: string | null; freighterType: string | null }) {
  if (freighterType === "production_freighter") return <span className="badge bg-navy text-white">Production freighter</span>;
  if (freighterType === "converted_freighter") return <span className="badge bg-cyan text-white">Converted freighter (P2F)</span>;
  if (role === "passenger") return <span className="badge bg-slate-100 text-slate-700">Passenger</span>;
  return <span className="badge bg-slate-100 text-slate-400">Role not documented</span>;
}

export function SupportBadge({ supported }: { supported: boolean }) {
  return supported
    ? <span className="badge bg-emerald-50 text-ok"><CheckCircle2 className="h-3 w-3" />Flight model</span>
    : <span className="badge bg-slate-100 text-slate-500"><CircleSlash className="h-3 w-3" />No flight model</span>;
}

export function SourceTypeBadge({ type }: { type: string }) {
  const tone: Record<string, string> = {
    published_specification: "bg-navy/10 text-navy", documented_classification: "bg-navy/10 text-navy",
    engine_databank: "bg-cyan-50 text-cyan", open_model_data: "bg-amber-50 text-amber-800",
  };
  return <span className={`badge ${tone[type] ?? "bg-slate-100 text-slate-600"}`}>{SOURCE_TYPE_LABEL[type] ?? label(type)}</span>;
}

export function StatusBadge({ status }: { status: string }) {
  const tone = status === "source_inconsistent" ? "bg-red-50 text-danger" : status === "as_published" ? "bg-emerald-50 text-ok"
    : "bg-slate-100 text-slate-600";
  return <span className={`badge ${tone}`}>{STATUS_LABEL[status] ?? label(status)}</span>;
}

export function Accordion({ title, children, defaultOpen = false }: { title: ReactNode; children: ReactNode; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  return <div className="card">
    <button type="button" aria-expanded={open} onClick={() => setOpen(!open)}
      className="flex w-full items-center justify-between px-4 py-3 text-left font-semibold text-navy hover:bg-tint">
      <span>{title}</span><ChevronDown className={`h-4 w-4 transition ${open ? "rotate-180" : ""}`} />
    </button>
    {open && <div className="border-t border-slate-100 px-4 py-3">{children}</div>}
  </div>;
}

export function References({ refs }: { refs: Reference[] }) {
  if (!refs.length) return null;
  return <ul className="mt-2 space-y-1 text-xs text-slate-600">
    {refs.map((r) => <li key={r.url || r.title}>
      {isAgencyUrl(r.url)
        ? <a className="inline-flex items-center gap-1 text-cyan hover:underline" href={r.url} target="_blank" rel="noreferrer">
            {r.publisher}: {r.title}<ExternalLink className="h-3 w-3" /></a>
        : <span>{r.url.startsWith("http") ? `${r.publisher}: ${r.title}` : r.title.replace(/^Project documentation: /, "This site's notes: ")}</span>}
    </li>)}
  </ul>;
}

export function PageHeader({ title, subtitle, children }: { title: string; subtitle?: string; children?: ReactNode }) {
  return <header className="skew-band text-white">
    <div className="mx-auto max-w-7xl px-6 py-10">
      <h1 className="text-3xl font-bold md:text-4xl">{title}</h1>
      {subtitle && <p className="mt-2 max-w-3xl text-lg text-white/80">{subtitle}</p>}
      {children}
    </div>
  </header>;
}
