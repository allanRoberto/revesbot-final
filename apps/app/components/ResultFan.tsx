'use client';

// Overlay de resultado estilo Pragmatic: leque de 3 cunhas convergindo para a
// bolinha embaixo. Centro = número vencedor (grande, na cor dele); laterais =
// vizinhos imediatos na roda. Ex.: 15 | 19 | 4.

interface Props {
  cells: { n: number; color: 'r' | 'b' | 'g' }[]; // [vizinho esq, vencedor, vizinho dir]
}

const FILL: Record<string, string> = {
  r: '#c1121f',
  b: '#14171c',
  g: '#1e7a3c',
};

// Geometria polar: cunhas irradiando de um ponto perto do rodapé (a bolinha).
const CX = 200;
const CY = 244;
const R0 = 54; // raio interno (junto da bolinha)
const R1 = 214; // raio externo
const rad = (deg: number) => (deg * Math.PI) / 180;
const pt = (a: number, r: number) => [CX + r * Math.cos(rad(a)), CY + r * Math.sin(rad(a))];

// Ângulos (graus, 0 = direita, -90 = topo). Leque largo: laterais recuadas,
// centro vertical projetando mais longe (o vencedor domina).
const SEGS = [
  { a0: -133, a1: -99 }, // esquerda
  { a0: -99, a1: -81 }, // centro (vencedor)
  { a0: -81, a1: -47 }, // direita
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
      <svg viewBox="0 0 400 260" width="100%" height="100%">
        {SEGS.map((s, i) => {
          const cell = cells[i];
          if (!cell) return null;
          const center = i === 1;
          const r1 = center ? R1 : R1 - 40; // centro projeta mais longe
          const mid = (s.a0 + s.a1) / 2;
          const [lx, ly] = pt(mid, center ? 150 : 138);
          return (
            <g key={i}>
              <path
                d={wedgePath(s.a0, s.a1, r1)}
                fill={FILL[cell.color]}
                stroke="rgba(0,0,0,0.55)"
                strokeWidth={center ? 0 : 1}
              />
              <text
                x={lx.toFixed(1)}
                y={ly.toFixed(1)}
                textAnchor="middle"
                dominantBaseline="central"
                fill="#fff"
                fontWeight="800"
                fontSize={center ? 46 : 26}
                style={{ textShadow: '0 2px 5px rgba(0,0,0,0.6)' }}
              >
                {cell.n}
              </text>
            </g>
          );
        })}
        {/* bolinha branca no ponto de convergência */}
        <circle cx={CX} cy={CY - R0 + 14} r="15" fill="#fff" />
        <circle cx={CX} cy={CY - R0 + 14} r="15" fill="url(#ballShine)" />
        <defs>
          <radialGradient id="ballShine" cx="0.38" cy="0.32" r="0.75">
            <stop offset="0%" stopColor="#fff" />
            <stop offset="70%" stopColor="#e6e6e6" />
            <stop offset="100%" stopColor="#b8b8b8" />
          </radialGradient>
        </defs>
      </svg>
    </div>
  );
}
