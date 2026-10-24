import { BarChart3, BookOpen, GitCompare, Home, Library, Package, Plane, Wind } from "lucide-react";
import { NavLink, Outlet } from "react-router-dom";

const NAV = [
  { to: "/", label: "Explore", icon: Home, end: true },
  { to: "/aircraft", label: "Aircraft Library", icon: Library },
  { to: "/compare", label: "Compare", icon: GitCompare },
  { to: "/freighter", label: "Freighter", icon: Package },
  { to: "/flight-lab", label: "Flight Lab", icon: Wind },
  { to: "/learn", label: "Knowledge Hub", icon: BookOpen },
  { to: "/economics", label: "Economics", icon: BarChart3, advanced: true },
];

export function Layout() {
  return <div className="flex min-h-screen flex-col">
    <nav className="sticky top-0 z-40 bg-navy text-white shadow" aria-label="Main navigation">
      <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-1 gap-y-1 px-4 py-2">
        <NavLink to="/" className="mr-4 flex items-center gap-2 py-1 text-lg font-bold">
          <Plane className="h-5 w-5 text-cyan" aria-hidden />Aircraft Explorer
        </NavLink>
        {NAV.map(({ to, label, icon: Icon, end, advanced }) =>
          <NavLink key={to} to={to} end={end}
            className={({ isActive }) => `flex items-center gap-1.5 rounded px-3 py-1.5 text-sm font-semibold transition ${
              isActive ? "bg-cyan text-white" : "text-white/80 hover:bg-white/10 hover:text-white"}`}>
            <Icon className="h-4 w-4" aria-hidden />{label}
            {advanced && <span className="rounded bg-white/15 px-1 text-[10px] uppercase tracking-wide">advanced</span>}
          </NavLink>)}
      </div>
    </nav>
    <main className="flex-1"><Outlet /></main>
    <footer className="bg-navy text-sm text-white/70">
      <div className="mx-auto max-w-7xl space-y-1 px-6 py-6">
        <p>Aircraft Explorer is an independent educational project. It isn't affiliated with, sponsored or endorsed by any
          company. Manufacturers and other organisations are named only as sources.</p>
        <p>Every figure shows where it came from and how it was checked. Missing figures are left empty, and OpenAP figures are
          model values, not certified specifications.</p>
      </div>
    </footer>
  </div>;
}
