/* Schematic, labelled teaching diagrams (not to scale, not any specific aircraft's artwork). */
import type { ReactNode } from "react";

const NAVY = "#001450", CYAN = "#00a0d1", GREY = "#94a3b8";

function Frame({ title, children, caption, viewBox = "0 0 640 260" }: { title: string; children: ReactNode; caption?: string; viewBox?: string }) {
  return <figure className="card overflow-hidden p-4">
    <svg viewBox={viewBox} role="img" aria-label={title} className="w-full">{children}</svg>
    <figcaption className="mt-2 text-xs text-slate-500"><span className="font-semibold text-navy">{title}.</span> {caption ?? "Schematic, not to scale."}</figcaption>
  </figure>;
}

function Arrow({ x1, y1, x2, y2, label, lx, ly }: { x1: number; y1: number; x2: number; y2: number; label: string; lx: number; ly: number }) {
  return <g stroke={CYAN} strokeWidth={1.5} fill={CYAN}>
    <line x1={x1} y1={y1} x2={x2} y2={y2} markerStart="url(#arr)" markerEnd="url(#arr)" />
    <text x={lx} y={ly} stroke="none" fontSize={13} fontWeight={600} textAnchor="middle" fill={NAVY}>{label}</text>
  </g>;
}

const Defs = () => <defs><marker id="arr" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
  <path d="M 0 0 L 10 5 L 0 10 z" fill={CYAN} /></marker></defs>;

export function DimensionsDiagram({ length, span, height }: { length?: string; span?: string; height?: string }) {
  return <Frame title="What the dimensions measure" viewBox="0 0 640 300"
    caption="Length: nose to tail. Wingspan: wing tip to wing tip (with or without winglets is stated). Height: ground to top of the fin. Schematic, not to scale.">
    <Defs />
    {/* side view */}
    <g fill="#e2e8f0" stroke={NAVY} strokeWidth={1.5}>
      <path d="M40 150 Q30 135 60 128 L270 128 Q300 128 312 112 L330 70 L350 70 L345 128 L350 150 Z" />
      <path d="M150 145 L210 160 L230 160 L190 145 Z" />
      <circle cx="110" cy="160" r="5" /><circle cx="200" cy="162" r="5" />
    </g>
    <line x1="30" y1="170" x2="360" y2="170" stroke={GREY} strokeDasharray="4 3" />
    <Arrow x1={38} y1={195} x2={352} y2={195} label={`Length${length ? `: ${length}` : ""}`} lx={195} ly={215} />
    <Arrow x1={372} y1={168} x2={372} y2={70} label="" lx={0} ly={0} />
    <text x={380} y={120} fontSize={13} fontWeight={600} fill={NAVY}>{`Height${height ? `: ${height}` : ""}`}</text>
    {/* top view */}
    <g fill="#e2e8f0" stroke={NAVY} strokeWidth={1.5} transform="translate(470 40)">
      <rect x="-8" y="0" width="16" height="200" rx="8" />
      <path d="M-8 80 L-95 125 L-95 135 L-8 110 Z M8 80 L95 125 L95 135 L8 110 Z" />
      <path d="M-8 180 L-35 195 L-35 200 L-8 192 Z M8 180 L35 195 L35 200 L8 192 Z" />
    </g>
    <Arrow x1={375} y1={262} x2={565} y2={262} label={`Wingspan${span ? `: ${span}` : ""}`} lx={470} ly={285} />
  </Frame>;
}

export function WeightStack({ oew, payload, fuel, mtow, conceptual = false }: {
  oew: number; payload: number; fuel: number; mtow: number; conceptual?: boolean;
}) {
  const total = Math.max(mtow, oew + payload + fuel);
  const w = (x: number) => (x / total) * 560;
  return <Frame title="Empty weight, payload and fuel within MTOW" viewBox="0 0 640 150"
    caption={conceptual ? "Conceptual proportions only - not data for any aircraft. Takeoff weight = operating empty weight + payload + fuel, and must not exceed MTOW."
      : "Computed from the values on this page: payload up to MZFW - OEW, remaining fuel up to MTOW. One possible loading, not a published loading case."}>
    <rect x={40} y={40} width={w(oew)} height={40} fill={NAVY} />
    <rect x={40 + w(oew)} y={40} width={w(payload)} height={40} fill={CYAN} />
    <rect x={40 + w(oew + payload)} y={40} width={w(fuel)} height={40} fill="#f59e0b" />
    <line x1={40 + w(mtow)} y1={25} x2={40 + w(mtow)} y2={95} stroke="#a80a00" strokeWidth={2} strokeDasharray="5 3" />
    <text x={40 + w(mtow)} y={20} fontSize={12} textAnchor="end" fill="#a80a00">MTOW</text>
    <g fontSize={12} fill={NAVY}>
      <rect x={40} y={110} width={12} height={12} fill={NAVY} /><text x={58} y={121}>Operating empty weight</text>
      <rect x={230} y={110} width={12} height={12} fill={CYAN} /><text x={248} y={121}>Payload</text>
      <rect x={330} y={110} width={12} height={12} fill="#f59e0b" /><text x={348} y={121}>Fuel</text>
    </g>
  </Frame>;
}

export function TurbofanDiagram() {
  return <Frame title="How a turbofan works" viewBox="0 0 640 220"
    caption="The fan pushes most air around the core (bypass air, most of the thrust). The core compresses air, burns fuel and the turbine drives the fan and compressor. Based on NASA Glenn's turbofan explanation.">
    <g stroke={NAVY} strokeWidth={1.5} fill="none">
      <path d="M60 40 L520 60 L520 160 L60 180 Z" fill="#f1f5f9" />
      <rect x="170" y="85" width="300" height="50" rx="8" fill="#e2e8f0" />
    </g>
    <g fill={CYAN}><rect x="80" y="45" width="14" height="130" rx="4" /></g>
    <g fontSize={12} fill={NAVY} fontWeight={600}>
      <text x="70" y="200">Fan</text><text x="185" y="80">Compressor</text><text x="290" y="80">Combustor</text>
      <text x="385" y="80">Turbine</text><text x="200" y="35">Bypass air (cold)</text><text x="490" y="115">Core exhaust</text>
    </g>
    <g stroke={CYAN} strokeWidth={2} markerEnd="url(#arr)"><Defs />
      <line x1="20" y1="110" x2="70" y2="110" /><line x1="110" y1="60" x2="560" y2="60" /><line x1="110" y1="160" x2="560" y2="160" />
      <line x1="470" y1="110" x2="600" y2="110" /></g>
    <rect x="285" y="95" width="60" height="30" fill="#fb923c" opacity={0.7} />
  </Frame>;
}

export function PayloadRangeDiagram() {
  return <Frame title="Payload-range trade-off" viewBox="0 0 640 260"
    caption="Conceptual shape only (no aircraft data): A max payload limited by MZFW; B MTOW reached - trade payload for fuel; C fuel tanks full; D ferry range.">
    <Defs />
    <g stroke={NAVY} strokeWidth={1.5}><line x1="60" y1="220" x2="600" y2="220" markerEnd="url(#arr)" /><line x1="60" y1="220" x2="60" y2="20" markerEnd="url(#arr)" /></g>
    <polyline points="60,60 300,60 470,120 560,220" fill="none" stroke={CYAN} strokeWidth={3} />
    <g fontSize={12} fill={NAVY}><text x="300" y="245" textAnchor="middle">Range →</text><text x="20" y="30">Payload</text>
      <text x="300" y="52" textAnchor="middle">A: max payload (MZFW)</text><text x="395" y="85">B: at MTOW, payload ↔ fuel</text>
      <text x="480" y="140">C: tanks full</text><text x="540" y="212" textAnchor="end">D: ferry</text></g>
  </Frame>;
}

export function FlightPhasesDiagram() {
  const phases = ["Taxi-out", "Takeoff", "Climb", "Cruise", "Descent", "Landing", "Taxi-in"];
  return <Frame title="Flight phases and block time" viewBox="0 0 640 220"
    caption="Block time runs from off-block (taxi-out starts) to on-block (taxi-in ends); airborne time runs from lift-off to touchdown.">
    <polyline points="20,180 90,180 120,180 230,50 430,50 540,170 570,180 620,180" fill="none" stroke={CYAN} strokeWidth={3} />
    <g fontSize={11} fill={NAVY} fontWeight={600} textAnchor="middle">
      {phases.map((p, i) => <text key={p} x={[55, 110, 175, 330, 485, 555, 600][i]} y={200}>{p}</text>)}</g>
    <line x1="20" y1="20" x2="620" y2="20" stroke={NAVY} /><text x="320" y="14" fontSize={12} textAnchor="middle" fill={NAVY}>Block time</text>
    <line x1="120" y1="35" x2="560" y2="35" stroke={GREY} /><text x="340" y="31" fontSize={11} textAnchor="middle" fill={GREY}>Airborne time</text>
  </Frame>;
}

export function UldDiagram() {
  return <Frame title="Containers and pallets (ULDs)" viewBox="0 0 640 200"
    caption="Contoured containers match the fuselage shape; pallets are flat bases with nets. Codes (e.g. AAY, AKH, LD3) identify standard types (IATA ULD regulations).">
    <g stroke={NAVY} strokeWidth={1.5}>
      <path d="M40 160 L40 70 L80 40 L200 40 L240 70 L240 160 Z" fill="#e2e8f0" />
      <path d="M300 160 L300 80 L330 60 L430 60 L430 160 Z" fill="#e2e8f0" />
      <rect x="480" y="150" width="130" height="10" fill={CYAN} /><path d="M485 150 Q545 70 605 150" fill="none" strokeDasharray="4 3" />
    </g>
    <g fontSize={12} fill={NAVY} fontWeight={600} textAnchor="middle">
      <text x="140" y="185">Main-deck contoured container</text><text x="365" y="185">Lower-deck container</text><text x="545" y="185">Pallet with net</text></g>
  </Frame>;
}

export function BodyCrossSection() {
  return <Frame title="Narrowbody vs widebody cross-section" viewBox="0 0 640 220" caption="A narrowbody has one aisle; a widebody has two. Wider fuselages fit larger main-deck ULDs side by side.">
    <g stroke={NAVY} strokeWidth={1.5} fill="#f1f5f9"><ellipse cx="160" cy="110" rx="80" ry="85" /><ellipse cx="460" cy="110" rx="130" ry="95" /></g>
    <g fill={CYAN}><rect x="155" y="60" width="10" height="70" /><rect x="400" y="60" width="10" height="70" /><rect x="510" y="60" width="10" height="70" /></g>
    <g fontSize={12} fill={NAVY} fontWeight={600} textAnchor="middle"><text x="160" y="215">Narrowbody (one aisle)</text><text x="460" y="215">Widebody (two aisles)</text></g>
  </Frame>;
}

export function P2FDiagram({ active = 0 }: { active?: number }) {
  const parts = [
    { x: 170, label: "Floor rebuilt / reinforced" }, { x: 230, label: "Main-deck cargo door" },
    { x: 360, label: "Windows plugged" }, { x: 480, label: "Rear doors deactivated" }, { x: 70, label: "9g barrier" },
  ];
  return <Frame title="Where a P2F conversion changes the aircraft" viewBox="0 0 640 220"
    caption="Based on the conversion work EFW lists for its P2F programmes (floor, frames, door, windows, doors, barrier). Schematic.">
    <path d="M30 120 Q20 95 60 90 L540 90 Q580 90 600 60 L620 60 L615 120 L600 140 L60 140 Q35 140 30 120 Z" fill="#e2e8f0" stroke={NAVY} strokeWidth={1.5} />
    <rect x="200" y="94" width="60" height="38" fill={active === 1 ? CYAN : "#cbd5e1"} stroke={NAVY} />
    <line x1="70" y1="130" x2="560" y2="130" stroke={active === 0 ? CYAN : GREY} strokeWidth={4} />
    {[300, 330, 360, 390, 420].map((x) => <circle key={x} cx={x} cy={105} r={5} fill={active === 2 ? CYAN : "#94a3b8"} />)}
    <rect x="470" y="96" width="18" height="32" fill={active === 3 ? CYAN : "#cbd5e1"} stroke={NAVY} />
    <line x1="95" y1="92" x2="95" y2="138" stroke={active === 4 ? CYAN : NAVY} strokeWidth={4} />
    <g fontSize={11} fill={NAVY} fontWeight={600} textAnchor="middle">{parts.map((p, i) =>
      <text key={p.label} x={p.x} y={[170, 185, 170, 185, 200][i]} fill={active === i ? CYAN : NAVY}>{p.label}</text>)}</g>
  </Frame>;
}

export function CostTaxonomyDiagram() {
  const box = (x: number, y: number, w: number, t: string, sub: string, fill: string) => <g>
    <rect x={x} y={y} width={w} height={46} rx={6} fill={fill} /><text x={x + w / 2} y={y + 20} textAnchor="middle" fontSize={13} fontWeight={700} fill="#fff">{t}</text>
    <text x={x + w / 2} y={y + 36} textAnchor="middle" fontSize={10} fill="#fff">{sub}</text></g>;
  return <Frame title="Project cost taxonomy" viewBox="0 0 640 200" caption="COC = direct variable + direct fixed + indirect; TOC = COC + depreciation; Total = TOC + financing (this project's convention).">
    {box(20, 20, 190, "Direct variable", "fuel, maintenance, charges", NAVY)}
    {box(225, 20, 190, "Direct fixed", "crew salaries, insurance, lease", NAVY)}
    {box(430, 20, 190, "Indirect", "admin, sales, G&A", NAVY)}
    {box(20, 80, 600, "Cash operating cost (COC)", "", CYAN)}
    {box(20, 140, 420, "+ Depreciation = TOC", "noncash", "#0f2a6b")}
    {box(450, 140, 170, "+ Financing = Total", "interest", "#0f2a6b")}
  </Frame>;
}

export const DIAGRAMS: Record<string, () => ReactNode> = {
  "weights-stack": () => <WeightStack oew={50} payload={25} fuel={25} mtow={100} conceptual />,
  "payload-range": PayloadRangeDiagram, turbofan: TurbofanDiagram, "flight-phases": FlightPhasesDiagram,
  uld: UldDiagram, "body-cross-section": BodyCrossSection, "p2f-steps": () => <P2FDiagram />, "cost-taxonomy": CostTaxonomyDiagram,
};
