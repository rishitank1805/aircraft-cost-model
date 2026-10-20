import type { FormulaSpec } from "../types";

/** A formula set as written maths: "result = expression", or a fraction with a horizontal bar. */
export function Formula({ f }: { f: FormulaSpec }) {
  return <div className="formula" role="math" aria-label={`${f.result} ${f.relation ?? "="} ${f.expression ?? `${f.numerator} divided by ${f.denominator}`}`}>
    <span>{f.result}</span>
    <span className="px-2">{f.relation ?? "="}</span>
    {f.numerator !== undefined
      ? <span className="frac"><span>{f.numerator}</span><span>{f.denominator}</span></span>
      : <span>{f.expression}</span>}
    {f.note && <span className="formula-note">{f.note}</span>}
  </div>;
}

export function Formulas({ items }: { items?: FormulaSpec[] | null }) {
  if (!items?.length) return null;
  return <div className="space-y-2 rounded-md border border-slate-200 bg-tint/60 p-3">{items.map((f) => <Formula key={f.result + (f.expression ?? f.numerator)} f={f} />)}</div>;
}
