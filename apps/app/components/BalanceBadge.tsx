'use client';

import { useEffect, useRef, useState } from 'react';
import { formatBRL } from '@/lib/format';

const POLL_MS = 15000;

export default function BalanceBadge({
  initial,
}: {
  initial: number | null;
}) {
  const [balance, setBalance] = useState<number | null>(initial);
  const [pulse, setPulse] = useState(false);
  const prev = useRef<number | null>(initial);

  useEffect(() => {
    let active = true;

    async function refresh() {
      try {
        const res = await fetch('/api/me', { cache: 'no-store' });
        if (!res.ok || !active) return;
        const data = await res.json();
        if (typeof data.balance === 'number') {
          if (prev.current !== null && data.balance !== prev.current) {
            setPulse(true);
            setTimeout(() => active && setPulse(false), 800);
          }
          prev.current = data.balance;
          setBalance(data.balance);
        }
      } catch {
        /* mantém último valor em caso de falha */
      }
    }

    const id = setInterval(refresh, POLL_MS);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, []);

  return (
    <div className={`balance${pulse ? ' balance-pulse' : ''}`} title="Saldo na LotoGreen">
      <span className="balance-label">Saldo</span>
      <span className="balance-value">
        {typeof balance === 'number' ? formatBRL(balance) : '—'}
      </span>
    </div>
  );
}
