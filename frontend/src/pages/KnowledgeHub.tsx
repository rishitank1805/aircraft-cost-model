import { Search } from "lucide-react";
import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { api } from "../api";
import { ErrorBox, Loading, PageHeader, References } from "../components/ui";
import { useApi } from "../components/useApi";
import { DIAGRAMS } from "../diagrams/Diagrams";
import { Formulas } from "../components/Formula";
import { label } from "../format";

export function KnowledgeHubPage() {
  const [q, setQ] = useState("");
  const [category, setCategory] = useState("");
  const { data, error, loading } = useApi(() => api.glossary(q || undefined), [q]);
  const { hash } = useLocation();
  useEffect(() => {
    if (hash && data) document.getElementById(hash.slice(1))?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [hash, data]);
  const topics = (data?.topics ?? []).filter((t) => !category || t.category === category);
  return <>
    <PageHeader title="Aviation Knowledge Hub" subtitle="The terms you'll meet on the aircraft pages, explained simply, each with an example and its sources." />
    <div className="mx-auto max-w-5xl px-6 py-8">
      <div className="flex flex-wrap gap-3">
        <label className="relative flex-1"><span className="sr-only">Search topics</span><Search className="absolute left-2 top-2.5 h-4 w-4 text-slate-400" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search, for example payload, ULD or thrust"
            className="w-full rounded-md border border-slate-300 py-2 pl-8 pr-2 focus:border-cyan focus:outline-none" /></label>
        <div className="flex flex-wrap gap-1" role="group" aria-label="Categories">
          {["", ...(data?.categories ?? [])].map((c) => <button key={c || "all"} type="button" onClick={() => setCategory(c)} aria-pressed={category === c}
            className={`rounded-full px-3 py-1 text-sm font-semibold ${category === c ? "bg-navy text-white" : "bg-tint text-navy"}`}>{c || "All"}</button>)}
        </div>
      </div>
      {loading && <Loading />}{error && <ErrorBox message={error} />}
      <div className="mt-6 space-y-6">
        {topics.map((t) => <article key={t.slug} id={t.slug} className="card scroll-mt-28 p-6">
          <p className="text-xs font-semibold uppercase tracking-wide text-cyan">{t.category}</p>
          <h2 className="text-2xl font-bold text-navy">{t.term}</h2>
          {t.aliases.length > 0 && <p className="text-xs text-slate-500">Also called: {t.aliases.join(", ")}</p>}
          <div className="mt-4 grid gap-6 lg:grid-cols-[1fr_320px]">
            <div className="space-y-3 text-[15px]">
              <p><span className="font-semibold text-navy">What it is. </span>{t.definition}</p>
              <Formulas items={t.formulas} />
              <p><span className="font-semibold text-navy">Why it matters. </span>{t.why_it_matters}</p>
              <p className="rounded-md bg-cyan-50 p-3"><span className="font-semibold text-navy">Example. </span>{t.example}</p>
              {t.related_specs.length > 0 && <p className="text-sm">Where you'll see it: {t.related_specs.map(label).filter((x, i, all) => all.indexOf(x) === i).join(", ")}</p>}
              <p className="text-xs text-slate-500">{t.basis}</p>
              <References refs={t.references} />
            </div>
            {t.diagram && DIAGRAMS[t.diagram] && <div>{DIAGRAMS[t.diagram]()}</div>}
          </div>
        </article>)}
        {data && !topics.length && <p className="text-slate-500">No topic matches.</p>}
      </div>
    </div>
  </>;
}
