'use client';

// Racetrack (pista oval) em SVG — geometria fiel à Pragmatic: pontas curvas
// com células em cunha, miolo com JEU ZERO (borda curva), VOISINS, ORPHELINS
// e TIERS (divisórias inclinadas).

const W = 920;
const H = 270;
const R = 135; // raio externo das pontas
const T = 52; // espessura do anel de números
const IR = R - T; // raio interno

const REDS = new Set([
  1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36,
]);
const fillOf = (n: number) =>
  n === 0 ? '#1e7c46' : REDS.has(n) ? '#b02633' : '#171a1f';

// Segmentos na ordem da roda.
const TOP = [32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30];
const BOTTOM = [35, 12, 28, 7, 29, 18, 22, 9, 31, 14, 20, 1, 33, 16, 24];
const RIGHT = [8, 23, 10, 5]; // ponta direita (topo → base)
const LEFT = [0, 26, 3]; // ponta esquerda (topo → base)

interface Cell {
  n: number;
  d: string;
  lx: number;
  ly: number;
}

function buildCells(): Cell[] {
  const cells: Cell[] = [];
  const sw = (W - 2 * R) / TOP.length; // largura das células retas

  TOP.forEach((n, i) => {
    const x = R + i * sw;
    cells.push({
      n,
      d: `M ${x} 0 H ${x + sw} V ${T} H ${x} Z`,
      lx: x + sw / 2,
      ly: T / 2,
    });
  });
  BOTTOM.forEach((n, i) => {
    const x = R + i * sw;
    cells.push({
      n,
      d: `M ${x} ${H - T} H ${x + sw} V ${H} H ${x} Z`,
      lx: x + sw / 2,
      ly: H - T / 2,
    });
  });

  // Cunhas da ponta direita (ângulo 0º no topo, sentido horário).
  const rp = (rad: number, deg: number): [number, number] => {
    const a = (deg * Math.PI) / 180;
    return [W - R + rad * Math.sin(a), H / 2 - rad * Math.cos(a)];
  };
  const segR = 180 / RIGHT.length;
  RIGHT.forEach((n, i) => {
    const a1 = i * segR;
    const a2 = (i + 1) * segR;
    const [ox1, oy1] = rp(R, a1);
    const [ox2, oy2] = rp(R, a2);
    const [ix1, iy1] = rp(IR, a1);
    const [ix2, iy2] = rp(IR, a2);
    const [lx, ly] = rp((R + IR) / 2, (a1 + a2) / 2);
    cells.push({
      n,
      d: `M ${ox1} ${oy1} A ${R} ${R} 0 0 1 ${ox2} ${oy2} L ${ix2} ${iy2} A ${IR} ${IR} 0 0 0 ${ix1} ${iy1} Z`,
      lx,
      ly,
    });
  });

  // Cunhas da ponta esquerda (espelhada).
  const lp = (rad: number, deg: number): [number, number] => {
    const a = (deg * Math.PI) / 180;
    return [R - rad * Math.sin(a), H / 2 - rad * Math.cos(a)];
  };
  const segL = 180 / LEFT.length;
  LEFT.forEach((n, i) => {
    const a1 = i * segL;
    const a2 = (i + 1) * segL;
    const [ox1, oy1] = lp(R, a1);
    const [ox2, oy2] = lp(R, a2);
    const [ix1, iy1] = lp(IR, a1);
    const [ix2, iy2] = lp(IR, a2);
    const [lx, ly] = lp((R + IR) / 2, (a1 + a2) / 2);
    cells.push({
      n,
      d: `M ${ox1} ${oy1} A ${R} ${R} 0 0 0 ${ox2} ${oy2} L ${ix2} ${iy2} A ${IR} ${IR} 0 0 1 ${ix1} ${iy1} Z`,
      lx,
      ly,
    });
  });

  return cells;
}

const CELLS = buildCells();

// Apostas anunciadas (call bets) do miolo.
const SECTIONS = [
  {
    label: 'JEU ZERO',
    numbers: [0, 3, 12, 15, 26, 32, 35],
    d: `M 135 52 A ${IR} ${IR} 0 0 0 135 218 L 252 218 Q 322 135 252 52 Z`,
    lx: 168,
    ly: 135,
  },
  {
    label: 'VOISINS',
    numbers: [0, 2, 3, 4, 7, 12, 15, 18, 19, 21, 22, 25, 26, 28, 29, 32, 35],
    d: 'M 252 52 Q 322 135 252 218 L 435 218 L 462 52 Z',
    lx: 352,
    ly: 135,
  },
  {
    label: 'ORPHELINS',
    numbers: [1, 6, 9, 14, 17, 20, 31, 34],
    d: 'M 462 52 L 435 218 L 640 218 L 590 52 Z',
    lx: 538,
    ly: 135,
  },
  {
    label: 'TIERS',
    numbers: [5, 8, 10, 11, 13, 16, 23, 24, 27, 30, 33, 36],
    d: `M 590 52 L 640 218 L 785 218 A ${IR} ${IR} 0 0 0 785 52 Z`,
    lx: 700,
    ly: 135,
  },
];

export default function RaceTrack({
  placed,
  lastResult,
  disabled,
  onNumber,
  onSection,
}: {
  placed: Record<number, number>;
  lastResult: number | null;
  disabled: boolean;
  onNumber: (n: number) => void;
  onSection: (numbers: number[]) => void;
}) {
  return (
    <svg
      className={`trk${disabled ? ' trk-off' : ''}`}
      viewBox={`0 0 ${W} ${H}`}
      xmlns="http://www.w3.org/2000/svg"
      role="group"
      aria-label="Pista de apostas (racetrack)"
    >
      {SECTIONS.map((s) => (
        <g
          key={s.label}
          className="trk-sec"
          onClick={() => !disabled && onSection(s.numbers)}
        >
          <path d={s.d} />
          <text x={s.lx} y={s.ly}>{s.label}</text>
        </g>
      ))}

      {CELLS.map((c) => (
        <g
          key={c.n}
          className={`trk-cell${lastResult === c.n ? ' trk-win' : ''}`}
          onClick={() => !disabled && onNumber(c.n)}
        >
          <path d={c.d} fill={fillOf(c.n)} />
          <text x={c.lx} y={c.ly}>{c.n}</text>
          {placed[c.n] ? (
            <>
              <circle className="trk-chip" cx={c.lx} cy={c.ly} r={13} />
              <text className="trk-chip-txt" x={c.lx} y={c.ly}>
                {placed[c.n]}
              </text>
            </>
          ) : null}
        </g>
      ))}
    </svg>
  );
}
