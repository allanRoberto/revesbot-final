// Contrato isolado para a futura conexão com a central de sinais.
// Nesta etapa não há consumo de Redis: o módulo apenas valida o evento que será
// entregue ao orquestrador, evitando acoplar o executor ao formato bruto.

const SUPPORTED_ROULETTES = new Set([
  'pragmatic-brazilian-roulette',
  'pragmatic-auto-roulette',
  'pragmatic-immersive-roulette-deluxe',
]);

function normalizeAutomaticSignal(payload) {
  if (!payload || typeof payload !== 'object') {
    throw new Error('signal_payload_invalid');
  }
  const signalId = String(payload.signalId || payload.signal_id || payload.id || '').trim();
  const rouletteId = String(
    payload.rouletteId || payload.roulette_id || payload.roulette_slug || '',
  ).trim();
  const rawNumbers = payload.numbers || payload.bet || payload.targets || [];
  const numbers = [...new Set(
    (Array.isArray(rawNumbers) ? rawNumbers : [])
      .map(Number)
      .filter((number) => Number.isInteger(number) && number >= 0 && number <= 36),
  )];
  if (!signalId) throw new Error('signal_id_required');
  if (!SUPPORTED_ROULETTES.has(rouletteId)) throw new Error('roulette_not_supported');
  if (numbers.length === 0) throw new Error('signal_numbers_required');

  const createdAt = new Date(
    payload.createdAt || payload.created_at || payload.timestamp || Date.now(),
  );
  const expiresAt = new Date(
    payload.expiresAt ||
      payload.expires_at ||
      createdAt.getTime() + 90 * 1000,
  );
  if (!Number.isFinite(createdAt.getTime()) || !Number.isFinite(expiresAt.getTime())) {
    throw new Error('signal_timestamp_invalid');
  }

  return {
    signalId,
    rouletteId,
    numbers,
    confidence: payload.confidence || null,
    createdAt: createdAt.toISOString(),
    expiresAt: expiresAt.toISOString(),
  };
}

module.exports = {
  SUPPORTED_ROULETTES,
  normalizeAutomaticSignal,
};

