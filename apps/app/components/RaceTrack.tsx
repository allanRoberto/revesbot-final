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

// Quanto as células de canto "dobram" para dentro da curva. Na Pragmatic as
// dobras são assimétricas: à esquerda (32/35) o corte desce até ~45º (o 0 fica
// centrado a ~60º, bem abaixo do 32); à direita (30/24) o corte é menor (~22º)
// porque a curva comporta 4 números (8/23/10/5) em vez de 3.
const BETA_L = 45;
const BETA_R = 22;
// Raio dos rótulos nas curvas — levemente puxado para o lado interno do anel,
// como na referência.
const LR = 100;

function buildCells(): Cell[] {
  const cells: Cell[] = [];
  const sw = (W - 2 * R) / TOP.length; // largura das células retas

  // Pontos nas pontas: ângulo 0º no topo (12h), crescendo em direção à base.
  // Coordenadas arredondadas (2 casas) — precisão total de float diverge entre
  // Node e browser na última casa e causa hydration mismatch.
  const rnd = (v: number) => Math.round(v * 100) / 100;
  const rp = (rad: number, deg: number): [number, number] => {
    const a = (deg * Math.PI) / 180;
    return [rnd(W - R + rad * Math.sin(a)), rnd(H / 2 - rad * Math.cos(a))];
  };
  const lp = (rad: number, deg: number): [number, number] => {
    const a = (deg * Math.PI) / 180;
    return [rnd(R - rad * Math.sin(a)), rnd(H / 2 - rad * Math.cos(a))];
  };
  const j = (p: [number, number]) => `${p[0]} ${p[1]}`;

  TOP.forEach((n, i) => {
    const x = R + i * sw;
    if (i === 0) {
      // 32: retângulo + cunha 0..BETA_L da curva esquerda (corte diagonal).
      cells.push({
        n,
        d: `M ${j(lp(R, BETA_L))} A ${R} ${R} 0 0 1 ${R} 0 H ${x + sw} V ${T} H ${R} A ${IR} ${IR} 0 0 0 ${j(lp(IR, BETA_L))} Z`,
        lx: 118,
        ly: 38,
      });
      return;
    }
    if (i === TOP.length - 1) {
      // 30: retângulo + cunha 0..BETA_R da curva direita.
      cells.push({
        n,
        d: `M ${x} 0 H ${W - R} A ${R} ${R} 0 0 1 ${j(rp(R, BETA_R))} L ${j(rp(IR, BETA_R))} A ${IR} ${IR} 0 0 0 ${W - R} ${T} H ${x} Z`,
        lx: x + sw / 2,
        ly: T / 2,
      });
      return;
    }
    cells.push({
      n,
      d: `M ${x} 0 H ${x + sw} V ${T} H ${x} Z`,
      lx: x + sw / 2,
      ly: T / 2,
    });
  });

  BOTTOM.forEach((n, i) => {
    const x = R + i * sw;
    if (i === 0) {
      // 35: retângulo + cunha (180-BETA_L)..180 da curva esquerda.
      cells.push({
        n,
        d: `M ${j(lp(R, 180 - BETA_L))} A ${R} ${R} 0 0 0 ${R} ${H} H ${x + sw} V ${H - T} H ${R} A ${IR} ${IR} 0 0 1 ${j(lp(IR, 180 - BETA_L))} Z`,
        lx: 118,
        ly: H - 38,
      });
      return;
    }
    if (i === BOTTOM.length - 1) {
      // 24: retângulo + cunha (180-BETA_R)..180 da curva direita.
      cells.push({
        n,
        d: `M ${x} ${H - T} H ${W - R} A ${IR} ${IR} 0 0 1 ${j(rp(IR, 180 - BETA_R))} L ${j(rp(R, 180 - BETA_R))} A ${R} ${R} 0 0 1 ${W - R} ${H} H ${x} Z`,
        lx: x + sw / 2,
        ly: H - T / 2,
      });
      return;
    }
    cells.push({
      n,
      d: `M ${x} ${H - T} H ${x + sw} V ${H} H ${x} Z`,
      lx: x + sw / 2,
      ly: H - T / 2,
    });
  });

  // Cunhas da ponta direita (entre as dobras do 30 e do 24).
  const segR = (180 - 2 * BETA_R) / RIGHT.length;
  RIGHT.forEach((n, i) => {
    const a1 = BETA_R + i * segR;
    const a2 = BETA_R + (i + 1) * segR;
    const [lx, ly] = rp(LR, (a1 + a2) / 2);
    cells.push({
      n,
      d: `M ${j(rp(R, a1))} A ${R} ${R} 0 0 1 ${j(rp(R, a2))} L ${j(rp(IR, a2))} A ${IR} ${IR} 0 0 0 ${j(rp(IR, a1))} Z`,
      lx,
      ly,
    });
  });

  // Cunhas da ponta esquerda (0 centrado a ~60º, abaixo do corte do 32).
  const segL = (180 - 2 * BETA_L) / LEFT.length;
  LEFT.forEach((n, i) => {
    const a1 = BETA_L + i * segL;
    const a2 = BETA_L + (i + 1) * segL;
    const [lx, ly] = lp(LR, (a1 + a2) / 2);
    cells.push({
      n,
      d: `M ${j(lp(R, a1))} A ${R} ${R} 0 0 0 ${j(lp(R, a2))} L ${j(lp(IR, a2))} A ${IR} ${IR} 0 0 1 ${j(lp(IR, a1))} Z`,
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
