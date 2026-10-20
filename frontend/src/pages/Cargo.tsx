import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { GlossaryTerm } from "../components/GlossaryTerm";
import { Accordion, ErrorBox, Loading, Notice, PageHeader, References, RoleBadge, SupportBadge } from "../components/ui";
import { useApi } from "../components/useApi";
import { BodyCrossSection, P2FDiagram, PayloadRangeDiagram, UldDiagram } from "../diagrams/Diagrams";
import { formatSpec, label } from "../format";

const STEP_PART: Record<number, number> = { 3: 0, 4: 1, 5: 2, 6: 4 };

export function CargoPage() {
  const { data, error, loading } = useApi(() => api.cargo(), []);
  const [step, setStep] = useState(1);
  if (loading) return <div className="mx-auto max-w-7xl px-6"><Loading /></div>;
  if (error || !data) return <div className="mx-auto max-w-7xl p-6"><ErrorBox message={error ?? "unavailable"} /></div>;
  const current = data.conversion_steps.find((s) => s.step === step)!;
  return <>
    <PageHeader title="Cargo & P2F Explorer" subtitle="How freighters work, what a passenger-to-freighter conversion involves, and the five target freighters of this project." />
    <div className="mx-auto max-w-7xl space-y-12 px-6 py-8">
      <section className="space-y-3"><h2 className="section-title">Freighter fundamentals</h2>
        <div className="grid gap-6 lg:grid-cols-[1fr_380px]">
          <div className="space-y-3">{data.explainers.map((e, i) => <Accordion key={e.id} title={e.title} defaultOpen={i === 0}>
            <p>{e.body}</p>
            {e.glossary.length > 0 && <p className="mt-2 text-sm">Learn more: {e.glossary.map((g) => <span key={g} className="mr-2"><GlossaryTerm slug={g}>{label(g)}</GlossaryTerm></span>)}</p>}
            <p className="mt-2 text-xs text-slate-500">Basis: {e.basis}</p><References refs={e.references} /></Accordion>)}</div>
          <div className="space-y-4"><UldDiagram /><BodyCrossSection /><PayloadRangeDiagram /></div>
        </div>
      </section>
      <section className="space-y-4"><h2 className="section-title">The P2F conversion, step by step</h2>
        <ol className="flex flex-wrap gap-2" aria-label="Conversion steps">{data.conversion_steps.map((s) => <li key={s.step}>
          <button type="button" onClick={() => setStep(s.step)} aria-current={s.step === step ? "step" : undefined}
            className={`rounded-full px-3 py-1.5 text-sm font-semibold ${s.step === step ? "bg-cyan text-white" : s.step < step ? "bg-navy text-white" : "bg-tint text-navy"}`}>
            {s.step}. {s.title}</button></li>)}</ol>
        <div className="grid gap-6 lg:grid-cols-2">
          <div className="card space-y-2 p-5"><h3 className="text-xl font-bold text-navy">Step {current.step}: {current.title}</h3>
            <p>{current.body}</p><p className="text-xs text-slate-500">Basis: {current.basis}</p><References refs={current.references} />
            <div className="flex gap-2 pt-2">
              <button type="button" disabled={step === 1} onClick={() => setStep(step - 1)} className="rounded border px-3 py-1 text-sm disabled:opacity-40">Previous</button>
              <button type="button" disabled={step === data.conversion_steps.length} onClick={() => setStep(step + 1)} className="rounded bg-navy px-3 py-1 text-sm text-white disabled:opacity-40">Next</button>
            </div></div>
          <P2FDiagram active={STEP_PART[step] ?? -1} />
        </div>
      </section>
      <section className="space-y-4"><h2 className="section-title">The five target freighters</h2>
        <Notice>Four are production (factory-built) freighters; only the A321P2F is a passenger-to-freighter conversion. None has a
          supported flight-performance model in this project, so no route-specific performance or cost is calculated, and no passenger
          model is substituted.</Notice>
        <div className="grid gap-4 lg:grid-cols-2">{data.targets.map((t) => <article key={t.code} className="card space-y-3 p-5">
          <div className="flex items-start justify-between gap-2"><div>
            <h3 className="text-xl font-bold text-navy"><Link to={`/aircraft/${t.code}`} className="hover:text-cyan">{t.name}</Link></h3>
            <p className="text-xs text-slate-500">{t.code}</p></div>
            <div className="flex flex-col items-end gap-1"><RoleBadge role="cargo" freighterType={t.freighter_type} /><SupportBadge supported={t.flight_model_supported} /></div></div>
          <p className="text-sm">{t.summary}</p>
          <p className="text-xs text-amber-700">Not to be confused with: {t.not_to_confuse_with}</p>
          {t.published_facts.length ? <ul className="space-y-1 text-sm">{t.published_facts.map((f) => <li key={f.key} className="flex justify-between gap-3 border-b border-slate-100 py-1">
            <span>{f.label}</span><span className="text-right font-semibold">{formatSpec(f)}{f.condition && <span className="block text-[11px] font-normal text-slate-500">{f.condition}</span>}</span></li>)}</ul>
            : <p className="missing text-sm">No published cargo figures are held for this type.</p>}
          {t.missing_labels.length > 0 && <p className="text-xs text-slate-500">Unavailable (no verified source): {t.missing_labels.join(", ")}</p>}
          <References refs={t.references} />
        </article>)}</div>
      </section>
      <p className="text-xs text-slate-500">{data.disclaimer}</p>
    </div>
  </>;
}
