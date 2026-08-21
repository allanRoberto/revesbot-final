'use client';

// Contador circular com anel de progresso (estilo Pragmatic): número grande no
// centro, arco que esvazia conforme o tempo acaba. Fica verde e vira vermelho
// nos últimos segundos.

interface Props {
  seconds: number;
  total: number;
  alert?: boolean;
}

const R = 34; // raio do anel
const C = 2 * Math.PI * R; // circunferência

export default function CountdownRing({ seconds, total, alert = false }: Props) {
  const frac = total > 0 ? Math.max(0, Math.min(1, seconds / total)) : 0;
  const urgent = alert || seconds <= 5;
  const ringColor = urgent ? '#e5342f' : '#3ddc84';

  return (
    <div className="cd-ring" aria-label={`${seconds} segundos`}>
      <svg viewBox="0 0 80 80" width="80" height="80">
        <circle cx="40" cy="40" r={R} className="cd-track" />
        <circle
          cx="40"
          cy="40"
          r={R}
          className="cd-prog"
          stroke={ringColor}
          strokeDasharray={C}
          strokeDashoffset={C * (1 - frac)}
          transform="rotate(-90 40 40)"
        />
      </svg>
      <span className="cd-num" style={{ color: urgent ? '#ff6b66' : '#fff' }}>
        {Math.max(0, seconds)}
      </span>
    </div>
  );
}
