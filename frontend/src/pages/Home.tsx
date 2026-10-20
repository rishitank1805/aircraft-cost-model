import { ArrowRight, BarChart3, BookOpen, GitCompare, Library, Package, Wind } from "lucide-react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useApi } from "../components/useApi";

const SECTIONS = [
  { to: "/aircraft", icon: Library, title: "Aircraft Library", text: "Browse every aircraft type with sourced specifications and visible gaps." },
  { to: "/cargo", icon: Package, title: "Cargo & P2F Explorer", text: "Freighters, main-deck doors, ULDs and the passenger-to-freighter conversion step by step." },
  { to: "/compare", icon: GitCompare, title: "Compare Aircraft", text: "Two or three aircraft side by side - only like-for-like values are compared." },
  { to: "/flight-lab", icon: Wind, title: "Flight Performance Lab", text: "Run the project's OpenAP-based model: phases, fuel burn, block time and mass." },
  { to: "/learn", icon: BookOpen, title: "Aviation Knowledge Hub", text: "MTOW, MZFW, payload-range, thrust, ULDs, block hours and more - with sources." },
  { to: "/economics", icon: BarChart3, title: "Operating Economics", text: "Advanced: fuel and full operating-cost estimates, sensitivity and public benchmarks." },
];

export function HomePage() {
  const { data } = useApi(() => api.aircraft(), []);
  const freighters = data?.items.filter((a) => a.role === "cargo").length;
  const flight = data?.items.filter((a) => a.flight_model_supported).length;
  return <>
    <header className="skew-band text-white">
      <div className="mx-auto max-w-7xl px-6 py-16">
        <p className="text-sm font-semibold uppercase tracking-widest text-cyan">Open Aircraft Explorer</p>
        <h1 className="mt-3 max-w-3xl text-4xl font-bold leading-tight md:text-5xl">Understand aircraft - from specifications to freighter conversions.</h1>
        <p className="mt-4 max-w-2xl text-lg text-white/80">An interactive learning platform built on an open, source-traceable aircraft database.
          Every number shows where it comes from; missing data stays visibly missing.</p>
        <div className="mt-8 flex flex-wrap gap-3">
          <Link to="/aircraft" className="inline-flex items-center gap-2 rounded bg-cyan px-5 py-3 font-semibold hover:bg-cyan/90">Explore aircraft<ArrowRight className="h-4 w-4" /></Link>
          <Link to="/cargo" className="inline-flex items-center gap-2 rounded border border-white/40 px-5 py-3 font-semibold hover:bg-white/10">Learn about P2F conversion</Link>
        </div>
        <dl className="mt-10 grid max-w-2xl grid-cols-3 gap-6">
          {[["Aircraft types", data?.total], ["Freighters", freighters], ["Flight models", flight]].map(([t, v]) =>
            <div key={t as string}><dt className="text-sm text-white/70">{t}</dt><dd className="text-3xl font-bold">{v ?? "…"}</dd></div>)}
        </dl>
      </div>
    </header>
    <div className="mx-auto max-w-7xl px-6 py-12">
      <h2 className="section-title">Start learning</h2>
      <div className="mt-6 grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {SECTIONS.map(({ to, icon: Icon, title, text }) => <Link key={to} to={to} className="card group p-5 transition hover:-translate-y-0.5 hover:border-cyan hover:shadow-md">
          <Icon className="h-7 w-7 text-cyan" aria-hidden /><h3 className="mt-3 text-lg font-bold text-navy group-hover:text-cyan">{title}</h3>
          <p className="mt-1 text-sm text-slate-600">{text}</p></Link>)}
      </div>
      <div className="mt-12 grid gap-6 rounded-lg bg-tint p-6 md:grid-cols-3">
        <div><h3 className="font-bold text-navy">Learning path: freighter basics</h3><ol className="mt-2 list-decimal space-y-1 pl-5 text-sm">
          <li><Link className="text-cyan" to="/learn#passenger-vs-freighter">Passenger vs freighter</Link></li><li><Link className="text-cyan" to="/learn#uld">ULDs and pallets</Link></li>
          <li><Link className="text-cyan" to="/cargo">The P2F conversion</Link></li><li><Link className="text-cyan" to="/aircraft/A321P2F">A321P2F detail page</Link></li></ol></div>
        <div><h3 className="font-bold text-navy">Learning path: weights</h3><ol className="mt-2 list-decimal space-y-1 pl-5 text-sm">
          <li><Link className="text-cyan" to="/learn#oew">OEW</Link></li><li><Link className="text-cyan" to="/learn#mzfw">MZFW</Link></li>
          <li><Link className="text-cyan" to="/learn#mtow">MTOW</Link></li><li><Link className="text-cyan" to="/learn#payload-range">Payload-range</Link></li></ol></div>
        <div><h3 className="font-bold text-navy">Learning path: flight</h3><ol className="mt-2 list-decimal space-y-1 pl-5 text-sm">
          <li><Link className="text-cyan" to="/learn#block-hours">Block hours</Link></li><li><Link className="text-cyan" to="/learn#thrust">Thrust & turbofans</Link></li>
          <li><Link className="text-cyan" to="/flight-lab">Run a flight in the Lab</Link></li></ol></div>
      </div>
    </div>
  </>;
}
