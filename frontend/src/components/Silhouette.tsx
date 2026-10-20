import { termInText } from "../plain";

/** Schematic top-view silhouette by body type and engine count (not a photograph, not to scale). */
export function Silhouette({ bodyClass, engines, freighter }: { bodyClass: string | null; engines: number | null; freighter: boolean }) {
  const w = bodyClass === "widebody" ? 14 : bodyClass === "regional_jet" ? 8 : 10;
  const span = bodyClass === "widebody" ? 110 : bodyClass === "regional_jet" ? 70 : 90;
  const pods = engines === 4 ? [-0.65, -0.35, 0.35, 0.65] : engines === 2 ? [-0.4, 0.4] : [];
  return <svg viewBox="-70 -10 140 120" className="h-28 w-full" role="img"
    aria-label={`Schematic drawing of ${bodyClass ? `a ${termInText(bodyClass)}` : "an"} aircraft${freighter ? " (freighter)" : ""}. There's no licensed photograph.`}>
    <rect x="-70" y="-10" width="140" height="120" fill={freighter ? "#e6f6fb" : "#f1f1f5"} />
    <g fill="#001450" opacity={0.85}>
      <rect x={-w / 2} y={2} width={w} height={96} rx={w / 2} />
      <path d={`M${-w / 2} 38 L${-span / 2} 58 L${-span / 2} 63 L${-w / 2} 52 Z M${w / 2} 38 L${span / 2} 58 L${span / 2} 63 L${w / 2} 52 Z`} />
      <path d={`M${-w / 2} 88 L-20 96 L-20 99 L${-w / 2} 95 Z M${w / 2} 88 L20 96 L20 99 L${w / 2} 95 Z`} />
    </g>
    <g fill="#00a0d1">{pods.map((p) => <rect key={p} x={(p * span) / 2 - 3} y={44 + Math.abs(p) * 14} width={6} height={10} rx={2} />)}</g>
  </svg>;
}
