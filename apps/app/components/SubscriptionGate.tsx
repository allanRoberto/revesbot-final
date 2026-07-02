'use client';

import { useEffect, useState } from 'react';
import PaywallModal from './PaywallModal';

interface Plan {
  id: string;
  name: string;
  priceCents: number;
  durationDays: number;
  highlight?: boolean;
}

// Verifica a assinatura ao montar; se não houver plano ativo, exibe o paywall.
export default function SubscriptionGate() {
  const [open, setOpen] = useState(false);
  const [plans, setPlans] = useState<Plan[]>([]);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const res = await fetch('/api/subscription', { cache: 'no-store' });
        if (!res.ok || !active) return;
        const data = await res.json();
        if (!data.active) {
          setPlans(Array.isArray(data.plans) ? data.plans : []);
          setOpen(true);
        }
      } catch {
        /* silencioso */
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  if (!open) return null;
  return <PaywallModal plans={plans} onClose={() => setOpen(false)} />;
}
