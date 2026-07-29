'use client';

import { useState, FormEvent } from 'react';
import { useRouter } from 'next/navigation';
import { HOUSES, DEFAULT_HOUSE, houseName } from '@/lib/houses';

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [house, setHouse] = useState(DEFAULT_HOUSE);
  const [autoReconnect, setAutoReconnect] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ email, password, autoReconnect, house }),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data.error ?? 'Não foi possível entrar.');
        return;
      }
      router.replace('/automatico');
      router.refresh();
    } catch {
      setError('Erro de conexão. Tente novamente.');
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="auth-wrap">
      <div className="auth-card">
        <div className="auth-brand">
          <div className="logo">REVESBOT</div>
          <div className="sub">Entre com sua conta da {houseName(house)}</div>
        </div>

        <form onSubmit={handleSubmit}>
          {error && <div className="auth-error">{error}</div>}

          <div className="field">
            <label>Casa de apostas</label>
            <div className="house-picker" role="radiogroup" aria-label="Casa de apostas">
              {HOUSES.map((h) => (
                <button
                  key={h.id}
                  type="button"
                  role="radio"
                  aria-checked={house === h.id}
                  className={`house-opt${house === h.id ? ' on' : ''}`}
                  onClick={() => setHouse(h.id)}
                >
                  <span className="house-opt-badge">{h.name.charAt(0)}</span>
                  <span className="house-opt-name">{h.name}</span>
                  <span className="house-opt-domain">{h.domain}</span>
                </button>
              ))}
            </div>
          </div>

          <div className="field">
            <label htmlFor="email">E-mail</label>
            <input
              id="email"
              type="email"
              autoComplete="username"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>

          <div className="field">
            <label htmlFor="password">Senha</label>
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>

          <label className="switch">
            <input
              type="checkbox"
              checked={autoReconnect}
              onChange={(e) => setAutoReconnect(e.target.checked)}
            />
            <span>Reconectar automaticamente na {houseName(house)}</span>
          </label>

          <button className="btn-primary" type="submit" disabled={loading}>
            {loading ? 'Entrando...' : 'Entrar'}
          </button>
        </form>
      </div>
    </main>
  );
}
