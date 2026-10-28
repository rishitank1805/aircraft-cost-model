import { ArrowLeft, Wind } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { GlossaryTerm } from "../components/GlossaryTerm";
import { Silhouette } from "../components/Silhouette";
import { SpecTable } from "../components/SpecTable";
import { ErrorBox, Loading, Notice, RoleBadge, SupportBadge } from "../components/ui";
import { useApi } from "../components/useApi";
import { DimensionsDiagram, TurbofanDiagram, WeightStack } from "../diagrams/Diagrams";
import { formatSpec, label, num } from "../format";
import { plainText, sentence, termInText } from "../plain";
import type { AircraftDetail, SpecValue } from "../types";

const SECTIONS = [
  ["overview", "A. Overview"], ["dimensions", "B. Dimensions"], ["weights", "C. Weight & payload"], ["engines", "D. Engines"],
  ["performance", "E. Flight performance"], ["cargo", "F. Cargo"], ["sources", "G. Sources & limitations"],
] as const;

const primary = (d: AircraftDetail, section: string, key: string): SpecValue | undefined =>
  d.sections[section]?.find((v) => v.key === key && v.primary);

export function AircraftDetailPage() {
  const { code = "" } = useParams();
  const { data, error, loading } = useApi(() => api.aircraftDetail(code), [code]);
  if (loading) return <div className="mx-auto max-w-7xl px-6"><Loading what="Loading aircraft" /></div>;
  if (error || !data) return <div className="mx-auto max-w-7xl p-6"><ErrorBox message={error ?? "not found"} /></div>;
  const d = data;
  const s = d.summary;
  const isFreighter = s.role === "cargo";
  return <>
    <header className="skew-band text-white">
      <div className="mx-auto grid max-w-7xl gap-6 px-6 py-8 md:grid-cols-[1fr_280px]">
        <div>
          <Link to="/aircraft" className="inline-flex items-center gap-1 text-sm text-white/70 hover:text-white"><ArrowLeft className="h-4 w-4" />Aircraft Library</Link>
          <h1 className="mt-2 text-4xl font-bold">{s.name}</h1>
          <p className="mt-1 text-white/80">{s.code}{s.icao_type_designator ? ` · ICAO type designator ${s.icao_type_designator}` : ""}
            {s.series ? ` · ${s.series} series` : ""}</p>
          <div className="mt-3 flex flex-wrap gap-2"><RoleBadge role={s.role} freighterType={s.freighter_type} /><SupportBadge supported={s.flight_model_supported} />
            {s.body_class && <span className="badge bg-white/15 text-white">{label(s.body_class)}</span>}</div>
        </div>
        <div className="overflow-hidden rounded-lg bg-white/95">
          <Silhouette bodyClass={s.body_class} engines={s.engine_count} freighter={isFreighter} />
          <p className="px-3 pb-2 text-[11px] text-slate-500">A schematic drawing. There's no licensed photograph of this aircraft.</p>
        </div>
      </div>
    </header>
    <nav className="sticky top-[52px] z-30 border-b border-slate-200 bg-white/95 backdrop-blur" aria-label="Sections">
      <div className="mx-auto flex max-w-7xl gap-1 overflow-x-auto px-6 py-2 text-sm">
        {SECTIONS.map(([id, title]) => <a key={id} href={`#${id}`} className="whitespace-nowrap rounded px-3 py-1 font-semibold text-navy hover:bg-tint">{title}</a>)}
      </div>
    </nav>
    <div className="mx-auto max-w-7xl space-y-12 px-6 py-8">
      <Overview d={d} />
      <section id="dimensions" className="scroll-mt-28 space-y-4">
        <h2 className="section-title">B. Dimensions</h2>
        <div className="grid gap-6 lg:grid-cols-2">
          <DimensionsDiagram length={primary(d, "dimensions", "length_m") && formatSpec(primary(d, "dimensions", "length_m")!)}
            span={primary(d, "dimensions", "wingspan_m") && formatSpec(primary(d, "dimensions", "wingspan_m")!)}
            height={primary(d, "dimensions", "height_m") && formatSpec(primary(d, "dimensions", "height_m")!)} />
          <Notice>Two sources can describe the same dimension differently. The FAA Aircraft Characteristics Database gives the
            overall length, the wingspan (with and without winglets) and the tail height. OpenAP gives the model's geometry,
            which includes a <em>fuselage</em> height. That isn't the overall height. Both are shown, each with its source.</Notice>
        </div>
        <SpecTable values={d.sections.dimensions ?? []} missing={d.missing.dimensions} missingLabels={d.missing_labels} />
      </section>
      <Weights d={d} />
      <section id="engines" className="scroll-mt-28 space-y-4">
        <h2 className="section-title">D. Engines</h2>
        <div className="grid gap-6 lg:grid-cols-2">
          <SpecTable values={d.sections.engines ?? []} missing={d.missing.engines} missingLabels={d.missing_labels} />
          <div className="space-y-3"><TurbofanDiagram />
            <p className="text-sm text-slate-700">A <GlossaryTerm slug="thrust">turbofan</GlossaryTerm> burns fuel in its core to drive a large
              fan. Most of the air goes around the core rather than through it, and that air produces most of the thrust. The more air
              that goes around, the higher the bypass ratio, and usually the lower
              the <GlossaryTerm slug="sfc">specific fuel consumption</GlossaryTerm>.</p></div>
        </div>
      </section>
      <Performance d={d} />
      <section id="cargo" className="scroll-mt-28 space-y-4">
        <h2 className="section-title">F. Cargo capabilities</h2>
        {isFreighter ? <>
          {d.freighter_programme && <Notice><strong>{label(d.freighter_programme.freighter_type)}.</strong> {d.freighter_programme.statement}
            {" "}Source: {d.freighter_programme.source_publisher}.
            {d.freighter_programme.notes && <span className="mt-1 block">{d.freighter_programme.notes}</span>}</Notice>}
          <SpecTable values={d.sections.cargo ?? []} missing={d.missing.cargo} missingLabels={d.missing_labels} />
          <p className="text-sm">Learn how freighters and conversions work in the <Link to="/freighter" className="text-cyan hover:underline">Freighter Explorer</Link>.</p>
        </> : <Notice>This is a passenger aircraft, so there are no main-deck cargo figures (cargo door, ULD positions, cargo volume).
          Lower-deck cargo figures aren't available either. {d.related.filter((r) => r.relation.startsWith("freighter"))
            .map((r) => <span key={r.code}>There is a freighter version: <Link className="text-cyan" to={`/aircraft/${r.code}`}>{r.code}</Link>. </span>)}</Notice>}
      </section>
      <Sources d={d} />
    </div>
  </>;
}

function Overview({ d }: { d: AircraftDetail }) {
  const s = d.summary;
  return <section id="overview" className="scroll-mt-28 space-y-4">
    <h2 className="section-title">A. Overview</h2>
    <div className="grid gap-6 lg:grid-cols-3">
      <div className="card space-y-3 p-5 lg:col-span-2">
        {d.description.length ? <ul className="space-y-2">{d.description.map((x) => <li key={x.text}>{x.text}
          <span className="block text-xs text-slate-500">Source: {plainText(x.source)}</span></li>)}</ul>
          : <p className="missing">There's no sourced description for this type yet.</p>}
        <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm md:grid-cols-3">
          <div><dt className="text-xs uppercase text-slate-500">Manufacturer</dt><dd className="font-semibold">{s.manufacturer ?? "not available"}</dd></div>
          <div><dt className="text-xs uppercase text-slate-500">Model</dt><dd className="font-semibold">{s.model ?? "not available"}</dd></div>
          <div><dt className="text-xs uppercase text-slate-500">Role</dt><dd className="font-semibold">{s.role ? label(s.role) : <span className="missing">not documented</span>}</dd>
            <dd className="text-[11px] text-slate-500">{d.role.evidence}</dd></div>
          <div><dt className="text-xs uppercase text-slate-500"><GlossaryTerm slug="narrowbody-widebody">Body type</GlossaryTerm></dt>
            <dd className="font-semibold">{s.body_class ? label(s.body_class) : <span className="missing">not documented</span>}</dd></div>
          <div><dt className="text-xs uppercase text-slate-500"><GlossaryTerm slug="passenger-vs-freighter">Freighter type</GlossaryTerm></dt>
            <dd className="font-semibold">{s.freighter_type ? label(s.freighter_type) : "not a freighter"}</dd></div>
          <div><dt className="text-xs uppercase text-slate-500">Model series</dt><dd className="font-semibold">{s.series ?? "not available"}</dd>
            <dd className="text-[11px] text-slate-500">{s.series_basis}</dd></div>
        </dl>
        {d.notes && <p className="text-xs text-slate-500">Note: {plainText(d.notes)}</p>}
      </div>
      <div className="space-y-3">
        <div className="card p-4 text-sm"><h3 className="font-semibold text-navy">Flight model</h3>
          {d.flight_model.supported ? <><p className="text-ok">You can fly this aircraft in the Flight Lab, which uses the OpenAP model.</p>
            <Link to={`/flight-lab?aircraft=${s.code}`} className="mt-2 inline-flex items-center gap-1 text-cyan"><Wind className="h-4 w-4" />Open in Flight Lab</Link></>
            : <><p>There's no flight model for this aircraft:</p><ul className="mt-1 list-disc pl-4 text-xs text-slate-600">{d.flight_model.reasons.map((r) => <li key={r}>{sentence(plainText(r)).replace(/\.?$/, ".")}</li>)}</ul></>}
        </div>
        {d.related.length > 0 && <div className="card p-4 text-sm"><h3 className="font-semibold text-navy">Related types</h3>
          <ul className="mt-1 space-y-1">{d.related.map((r) => <li key={r.code}>{r.available
            ? <Link className="font-semibold text-cyan" to={`/aircraft/${r.code}`}>{r.code}</Link> : <span className="font-semibold">{r.code}</span>}: {r.relation}
            {r.warning && <span className="block text-xs text-amber-700">{r.warning}</span>}</li>)}</ul></div>}
        {d.benchmarks && <div className="card p-4 text-sm"><h3 className="font-semibold text-navy">Public cost benchmark</h3>
          <p className="text-xs text-slate-600">{d.benchmarks.label}. Matched to the BTS category "{d.benchmarks.bts_description}" ({termInText(d.benchmarks.mapping_status)}).</p>
          <ul className="mt-2 space-y-1">{Object.entries(d.benchmarks.metrics).map(([k, m]) => <li key={k} className="flex justify-between gap-2">
            <span>{label(k)}</span><span className="font-semibold">{m ? `${num(m.usd_per_block_hour)} USD per block hour` : <span className="missing">not available</span>}</span></li>)}</ul>
          <Link to="/economics" className="mt-2 inline-block text-xs text-cyan">More in Operating Economics →</Link></div>}
      </div>
    </div>
  </section>;
}

function Weights({ d }: { d: AircraftDetail }) {
  const w = (key: string) => primary(d, "weights", key);
  const LADDER: [string, string][] = [["oew_kg", "Operating empty weight (OEW)"], ["mzfw_kg", "Maximum zero-fuel weight (MZFW)"],
    ["mlw_kg", "Maximum landing weight (MLW)"], ["mtow_kg", "Maximum takeoff weight (MTOW)"], ["max_ramp_weight_kg", "Maximum ramp weight"]];
  const ladder = LADDER.map(([k, title]) => ({ key: k, title, v: w(k) }));
  const max = Math.max(...ladder.map((x) => x.v?.value ?? 0), 1);
  const oew = w("oew_kg")?.value, mzfw = w("mzfw_kg")?.value, mtow = w("mtow_kg")?.value;
  const payload = w("max_structural_payload_kg");
  return <section id="weights" className="scroll-mt-28 space-y-4">
    <h2 className="section-title">C. Weight and payload</h2>
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4 text-sm">
      {[["mtow", "MTOW", "the most the aircraft may weigh at the start of the takeoff run"],
        ["mlw", "MLW", "the most it may weigh when it touches down"],
        ["oew", "OEW", "the aircraft ready to fly, with crew and fluids, but no payload or fuel"],
        ["mzfw", "MZFW", "the most it may weigh before fuel is added - this limits payload"]].map(([slug, t, text]) =>
        <div key={slug} className="card p-4"><GlossaryTerm slug={slug}><span className="font-bold text-navy">{t}</span></GlossaryTerm>
          <p className="mt-1 text-slate-600">{text}.</p></div>)}
    </div>
    <div className="card p-5">
      <h3 className="font-semibold text-navy">Weight limits on one scale</h3>
      <div className="mt-3 space-y-2">{ladder.map(({ key, title, v }) => <div key={key} className="grid grid-cols-[170px_1fr] items-center gap-3 text-sm">
        <span>{title}</span>
        {v && v.value !== null ? <div className="flex items-center gap-2"><div className={`h-4 rounded ${v.verification_status === "source_inconsistent" ? "bg-red-200" : "bg-navy"}`}
          style={{ width: `${(v.value / max) * 75}%` }} /><span className="whitespace-nowrap text-xs">{formatSpec(v)}{v.verification_status === "source_inconsistent" && " (inconsistent in source)"}</span></div>
          : <span className="missing text-xs">unavailable</span>}</div>)}</div>
      <p className="mt-3 text-xs text-slate-500">Each bar uses the preferred source for that weight, and the table below lists every source. Figures from
        different sources aren't mixed into one loading example.</p>
    </div>
    {oew && mzfw && mtow ? <WeightStack oew={oew} payload={mzfw - oew} fuel={Math.max(mtow - mzfw, 0)} mtow={mtow} />
      : <Notice>The combined weight diagram needs the OEW, MZFW and MTOW. This aircraft is missing:{" "}
        {[!oew && "OEW", !mzfw && "MZFW", !mtow && "MTOW"].filter(Boolean).join(", ")}, so the diagram isn't drawn from guesses.</Notice>}
    <Notice tone="warn"><GlossaryTerm slug="payload">Maximum structural payload</GlossaryTerm> is a limit set by the structure and the weight limits
      {payload ? ` (here: ${formatSpec(payload)}${payload.condition ? `, ${payload.condition}` : ""})` : ""}. It isn't the paid cargo on an actual flight,
      which depends on demand, how dense the cargo is and how much fuel the distance needs.</Notice>
    <SpecTable values={d.sections.weights ?? []} missing={d.missing.weights} missingLabels={d.missing_labels} />
  </section>;
}

function Performance({ d }: { d: AircraftDetail }) {
  const values = d.sections.performance ?? [];
  const published = values.filter((v) => v.source_type === "published_specification");
  const model = values.filter((v) => v.source_type !== "published_specification");
  return <section id="performance" className="scroll-mt-28 space-y-4">
    <h2 className="section-title">E. Flight performance</h2>
    <div className="grid gap-6 lg:grid-cols-2">
      <div><h3 className="mb-2 font-semibold text-navy">Published figures</h3>
        {published.length ? <SpecTable values={published} /> : <p className="missing">No published performance figures yet.</p>}</div>
      <div><h3 className="mb-2 font-semibold text-navy">Model values from OpenAP (not certified)</h3>
        {model.length ? <SpecTable values={model} /> : <p className="missing">No model values for this aircraft.</p>}</div>
    </div>
    {d.missing.performance && <p className="text-sm text-slate-600">Not available: {d.missing.performance.map((k) => d.missing_labels[k] ?? k).join(", ")}.</p>}
    <Notice>Fuel burn, climb and descent aren't fixed figures. They depend on the route, the payload and the weather.
      {d.flight_model.supported ? <> Try the <Link to={`/flight-lab?aircraft=${d.summary.code}`} className="text-cyan">Flight Lab</Link> to work them out with the OpenAP model
        (the results are model estimates).</> : " There's no flight model for this aircraft, so fuel and climb figures aren't worked out."}</Notice>
  </section>;
}

function Sources({ d }: { d: AircraftDetail }) {
  const all = Object.values(d.sections).flat();
  const bySource = new Map<string, number>();
  all.forEach((v) => bySource.set(v.source_name ?? "unknown", (bySource.get(v.source_name ?? "unknown") ?? 0) + 1));
  return <section id="sources" className="scroll-mt-28 space-y-4">
    <h2 className="section-title">G. Data sources and limitations</h2>
    <div className="grid gap-6 lg:grid-cols-2">
      <div className="card p-5"><h3 className="font-semibold text-navy">Sources used on this page</h3>
        <ul className="mt-2 space-y-1 text-sm">{[...bySource.entries()].map(([name, n]) => <li key={name} className="flex justify-between gap-3"><span>{name}</span><span className="text-slate-500">{n} {n === 1 ? "value" : "values"}</span></li>)}</ul></div>
      <div className="card p-5"><h3 className="font-semibold text-navy">What's missing</h3>
        {Object.keys(d.missing).length ? <ul className="mt-2 space-y-1 text-sm">{Object.entries(d.missing).map(([section, keys]) =>
          <li key={section}><span className="font-semibold">{label(section)}:</span> {keys.map((k) => d.missing_labels[k] ?? k).join(", ")}</li>)}</ul>
          : <p className="text-sm">Nothing we'd expect is missing.</p>}</div>
    </div>
    <ul className="list-disc space-y-1 pl-5 text-sm text-slate-600">{d.data_policy.map((p) => <li key={p}>{p}</li>)}</ul>
    <details className="card p-4"><summary className="cursor-pointer font-semibold text-navy">All {all.length} values and where they come from</summary>
      <div className="mt-3"><SpecTable values={all} /></div></details>
  </section>;
}
