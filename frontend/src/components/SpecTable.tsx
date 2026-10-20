import { ChevronRight, ExternalLink } from "lucide-react";
import { Fragment, useState } from "react";
import type { SpecValue } from "../types";
import { formatSpec } from "../format";
import { isAgencyUrl, stripCompanyUrls } from "../links";
import { GlossaryTerm } from "./GlossaryTerm";
import { SourceTypeBadge, StatusBadge } from "./ui";

/** All values of a section, grouped by specification; every value expands to its full provenance. */
export function SpecTable({ values, missing = [], missingLabels = {} }: {
  values: SpecValue[]; missing?: string[]; missingLabels?: Record<string, string>;
}) {
  const [open, setOpen] = useState<string | null>(null);
  const groups = new Map<string, SpecValue[]>();
  values.forEach((v) => groups.set(v.key, [...(groups.get(v.key) ?? []), v]));
  return <div className="overflow-x-auto"><table className="w-full text-sm">
    <thead><tr className="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-500">
      <th className="py-2 pr-4">Specification</th><th className="py-2 pr-4">Value</th><th className="py-2 pr-4">Source type</th>
      <th className="py-2 pr-4">Verification</th><th className="py-2">Variant / condition</th></tr></thead>
    <tbody>
      {[...groups.entries()].map(([key, group]) => group.sort((a, b) => Number(b.primary) - Number(a.primary)).map((v, i) => {
        const id = `${key}-${v.source_id}-${i}`;
        return <Fragment key={id}>
          <tr className={`border-b border-slate-100 align-top ${v.verification_status === "source_inconsistent" ? "bg-red-50/50" : ""}`}>
            <td className="py-2 pr-4 font-medium">
              {i === 0 ? (v.glossary ? <GlossaryTerm slug={v.glossary}>{v.label}</GlossaryTerm> : v.label)
                : <span className="text-xs text-slate-400">↳ other source</span>}
            </td>
            <td className="py-2 pr-4">
              <button type="button" className="inline-flex items-center gap-1 text-left hover:text-cyan" aria-expanded={open === id}
                onClick={() => setOpen(open === id ? null : id)}>
                <ChevronRight className={`h-3 w-3 transition ${open === id ? "rotate-90" : ""}`} />
                <span className={v.verification_status === "source_inconsistent" ? "line-through" : "font-semibold"}>{formatSpec(v)}</span>
              </button>
            </td>
            <td className="py-2 pr-4"><SourceTypeBadge type={v.source_type} /></td>
            <td className="py-2 pr-4"><StatusBadge status={v.verification_status} /></td>
            <td className="py-2 text-xs text-slate-600">{v.variant}{v.condition && <span className="block text-amber-700">Condition: {v.condition}</span>}</td>
          </tr>
          {open === id && <tr className="bg-tint"><td colSpan={5} className="px-6 py-3 text-xs">
            <dl className="grid gap-x-6 gap-y-1 md:grid-cols-2">
              <dt className="font-semibold">Source</dt><dd>{v.source_name ?? "unavailable"} {isAgencyUrl(v.source_url) &&
                <a href={v.source_url!} target="_blank" rel="noreferrer" className="inline-flex items-center text-cyan">link<ExternalLink className="h-3 w-3" /></a>}</dd>
              <dt className="font-semibold">Reference</dt><dd>{stripCompanyUrls(v.source_reference) || "unavailable"}</dd>
              <dt className="font-semibold">Licence</dt><dd>{v.source_license ?? "unavailable"}</dd>
              <dt className="font-semibold">Exact stored value</dt><dd>{v.value_exact ?? v.value_text ?? "unavailable"} {v.unit ?? ""}</dd>
              <dt className="font-semibold">As published</dt><dd>{v.original_value ? `${v.original_value} ${v.original_unit ?? ""}` : "same as stored"}</dd>
              <dt className="font-semibold">Notes</dt><dd>{stripCompanyUrls(v.notes) || "none"}</dd>
            </dl></td></tr>}
        </Fragment>;
      }))}
      {missing.map((key) => <tr key={`missing-${key}`} className="border-b border-slate-100">
        <td className="py-2 pr-4 font-medium text-slate-500">{missingLabels[key] ?? key}</td>
        <td className="py-2 pr-4 missing" colSpan={4}>unavailable - no verified source in the database</td></tr>)}
    </tbody></table></div>;
}
