'use client';

import { useState } from 'react';

interface Plan {
  id: string;
  name: string;
  priceCents: number;
  durationDays: number;
  highlight?: boolean;
}

interface PixData {
  planName: string;
  amountCents: number;
  orderRef: string;
  pixCode: string | null;
  pixQr: string | null;
}

const brl = (cents: number) =>
  new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(
    cents / 100,
  );

export default function PaywallModal({
  plans,
  onClose,
}: {
  plans: Plan[];
  onClose?: () => void;
}) {
  const [loadingId, setLoadingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pix, setPix] = useState<PixData | null>(null);
  const [copied, setCopied] = useState(false);

  async function subscribe(planId: string) {
    setError(null);
    setLoadingId(planId);
    try {
      const res = await fetch('/api/subscription/checkout', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ planId }),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data.error ?? 'Não foi possível gerar o pagamento.');
        return;
      }
      setPix(data);
    } catch {
      setError('Erro de conexão. Tente novamente.');
    } finally {
      setLoadingId(null);
    }
  }

  function copyCode() {
    if (!pix?.pixCode) return;
    navigator.clipboard?.writeText(pix.pixCode);
    setCopied(true);
    setTimeout(() => setCopied(false), 1800);
  }

  return (
    <div className="paywall-overlay">
      <div className="paywall-card">
        {onClose && (
          <button className="paywall-close" onClick={onClose} aria-label="Fechar">
            ✕
          </button>
        )}

        {!pix ? (
          <>
            <div className="paywall-head">
              <div className="logo-sm">REVESBOT</div>
              <h2>Assine para liberar as sugestões</h2>
              <p>Escolha um plano e pague via PIX. Acesso liberado após a confirmação.</p>
            </div>

            {error && <div className="auth-error">{error}</div>}

            <div className="plan-list">
              {plans.map((p) => (
                <div key={p.id} className={`plan-card${p.highlight ? ' featured' : ''}`}>
                  <div className="plan-name">{p.name}</div>
                  <div className="plan-price">{brl(p.priceCents)}</div>
                  <div className="plan-days">{p.durationDays} dias</div>
                  <button
                    className="btn-primary"
                    onClick={() => subscribe(p.id)}
                    disabled={loadingId !== null}
                  >
                    {loadingId === p.id ? 'Gerando…' : 'Assinar'}
                  </button>
                </div>
              ))}
            </div>
          </>
        ) : (
          <div className="pix-step">
            <h2>Pague com PIX</h2>
            <p className="pix-plan">
              {pix.planName} · <strong>{brl(pix.amountCents)}</strong>
            </p>

            {pix.pixQr ? (
              <>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img className="pix-qr" src={pix.pixQr} alt="QR Code PIX" />
                <div className="pix-code">{pix.pixCode}</div>
                <button className="btn-primary" onClick={copyCode}>
                  {copied ? 'Copiado!' : 'Copiar código PIX'}
                </button>
              </>
            ) : (
              <div className="auth-error">
                PIX ainda não configurado. Fale com o suporte para concluir o pagamento.
              </div>
            )}

            <p className="pix-note">
              Após o pagamento, seu acesso é liberado em alguns minutos. Guarde o
              comprovante. Ref: <strong>{pix.orderRef}</strong>
            </p>
            {onClose && (
              <button className="logout-sm" onClick={onClose}>
                Fechar
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
