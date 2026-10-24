import { ArrowRight, BarChart3, BookOpen, GitCompare, Library, Package, Wind } from "lucide-react";
import { Link } from "react-router-dom";

const SECTIONS = [
  { to: "/aircraft", icon: Library, title: "Aircraft Library", text: "Every aircraft type in the database, with a source for each figure and the gaps left visible." },
  { to: "/freighter", icon: Package, title: "Freighter Explorer", text: "How freighters work: cargo doors, ULDs and the passenger-to-freighter conversion, step by step." },
  { to: "/compare", icon: GitCompare, title: "Compare Aircraft", text: "Put two or three aircraft side by side. Only figures that can fairly be compared are lined up." },
  { to: "/flight-lab", icon: Wind, title: "Flight Performance Lab", text: "Fly a route in the flight model and see each phase, the fuel burned, the block time and the weight." },
  { to: "/learn", icon: BookOpen, title: "Aviation Knowledge Hub", text: "MTOW, MZFW, payload and range, thrust, ULDs, block hours and more, explained with sources." },
  { to: "/economics", icon: BarChart3, title: "Operating Economics", text: "For the curious: what a flight might cost, what drives the cost and how it compares with public figures." },
];

export function HomePage() {
  return <>
    <header className="skew-band text-white">
      <div className="mx-auto max-w-7xl px-6 py-16">
        <p className="text-sm font-semibold uppercase tracking-widest text-cyan">Aircraft Explorer</p>
        <h1 className="mt-3 max-w-3xl text-4xl font-bold leading-tight md:text-5xl">Learn how passenger aircraft and freighter aircraft work.</h1>
        <p className="mt-4 max-w-2xl text-lg text-white/80">Everything here is built on open data. Each number tells you where it came from, and when
          something isn't known, we say so rather than guess.</p>
        <div className="mt-8 flex flex-wrap gap-3">
          <Link to="/aircraft" className="inline-flex items-center gap-2 rounded bg-cyan px-5 py-3 font-semibold hover:bg-cyan/90">Explore aircraft<ArrowRight className="h-4 w-4" /></Link>
          <Link to="/freighter" className="inline-flex items-center gap-2 rounded border border-white/40 px-5 py-3 font-semibold hover:bg-white/10">Learn about freighter aircraft</Link>
        </div>
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
          <li><Link className="text-cyan" to="/freighter">The P2F conversion</Link></li><li><Link className="text-cyan" to="/aircraft/A321P2F">A321P2F detail page</Link></li></ol></div>
        <div><h3 className="font-bold text-navy">Learning path: weights</h3><ol className="mt-2 list-decimal space-y-1 pl-5 text-sm">
          <li><Link className="text-cyan" to="/learn#oew">OEW</Link></li><li><Link className="text-cyan" to="/learn#mzfw">MZFW</Link></li>
          <li><Link className="text-cyan" to="/learn#mtow">MTOW</Link></li><li><Link className="text-cyan" to="/learn#payload-range">Payload and range</Link></li></ol></div>
        <div><h3 className="font-bold text-navy">Learning path: flight</h3><ol className="mt-2 list-decimal space-y-1 pl-5 text-sm">
          <li><Link className="text-cyan" to="/learn#block-hours">Block hours</Link></li><li><Link className="text-cyan" to="/learn#thrust">Thrust & turbofans</Link></li>
          <li><Link className="text-cyan" to="/flight-lab">Run a flight in the Lab</Link></li></ol></div>
      </div>
    </div>
  </>;
}
