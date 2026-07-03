'use client';

// Overlay de resultado estilo Pragmatic: leque de 3 cunhas convergindo para a
// bolinha embaixo. Centro = número vencedor (o mais LARGO e alto, na cor dele);
// laterais = vizinhos imediatos na roda, mais estreitos. Ex.: 15 | 19 | 4.

interface Props {
  cells: { n: number; color: 'r' | 'b' | 'g' }[]; // [vizinho esq, vencedor, vizinho dir]
}

const FILL: Record<string, string> = {
  r: '#c1121f',
  b: '#1a1d24',
  g: '#1e7a3c',
};

// Geometria polar: cunhas irradiando de um ponto perto do rodapé (a bolinha).
const CX = 200;
const CY = 252;
const R0 = 46; // raio interno (junto da bolinha)
const rad = (deg: number) => (deg * Math.PI) / 180;
const pt = (a: number, r: number) => [CX + r * Math.cos(rad(a)), CY + r * Math.sin(rad(a))];

// Ângulos (graus, -90 = topo). O CENTRO é o mais largo; laterais recuam.
// Pequenos vãos (2°) entre as cunhas.
const SEGS = [
  { a0: -140, a1: -109, r1: 176 }, // esquerda (vizinho)
  { a0: -107, a1: -73, r1: 220 }, // centro (vencedor) — mais largo e alto
  { a0: -71, a1: -40, r1: 176 }, // direita (vizinho)
];

function wedgePath(a0: number, a1: number, r1: number) {
  const [x1, y1] = pt(a0, R0);
  const [x2, y2] = pt(a0, r1);
  const [x3, y3] = pt(a1, r1);
  const [x4, y4] = pt(a1, R0);
  return `M ${x1.toFixed(1)} ${y1.toFixed(1)} L ${x2.toFixed(1)} ${y2.toFixed(1)} A ${r1} ${r1} 0 0 1 ${x3.toFixed(1)} ${y3.toFixed(1)} L ${x4.toFixed(1)} ${y4.toFixed(1)} A ${R0} ${R0} 0 0 0 ${x1.toFixed(1)} ${y1.toFixed(1)} Z`;
}

export default function ResultFan({ cells }: Props) {
  return (
    <div className="st-result" role="status" aria-label={`Resultado ${cells[1]?.n}`}>
      <svg viewBox="0 0 400 270" width="100%" height="100%">
        {SEGS.map((s, i) => {
          const cell = cells[i];
          if (!cell) return null;
          const center = i === 1;
          const mid = (s.a0 + s.a1) / 2;
          const [lx, ly] = pt(mid, center ? 150 : 130);
          const fill = FILL[cell.color];
          return (
            <g key={i}>
              <path
                d={wedgePath(s.a0, s.a1, s.r1)}
                fill={fill}
                stroke={fill}
                strokeWidth={10}
                strokeLinejoin="round"
              />
              <text
                x={lx.toFixed(1)}
                y={ly.toFixed(1)}
                textAnchor="middle"
                dominantBaseline="central"
                fill="#fff"
                fontWeight="800"
                fontSize={center ? 52 : 28}
                style={{ textShadow: '0 2px 5px rgba(0,0,0,0.6)' }}
              >
                {cell.n}
              </text>
            </g>
          );
        })}
        {/* bolinha branca no ponto de convergência */}
        <circle cx={CX} cy={CY - R0 + 18} r="18" fill="url(#ballShine)" stroke="rgba(0,0,0,0.25)" strokeWidth="1" />
        <defs>
          <radialGradient id="ballShine" cx="0.38" cy="0.30" r="0.85">
            <stop offset="0%" stopColor="#fff" />
            <stop offset="65%" stopColor="#eaeaea" />
            <stop offset="100%" stopColor="#b4b4b4" />
          </radialGradient>
        </defs>
      </svg>
    </div>
  );
}
