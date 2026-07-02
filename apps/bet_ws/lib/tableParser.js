// Parse das mensagens da mesa (Pragmatic).
// A mesa nova (Roleta Brasileira etc.) fala JSON v3 (type=json&version=3);
// mesas antigas falam XML. Suportamos os dois: tentamos JSON primeiro e,
// se não for JSON, caímos no parse por regex de XML.

function tryJson(message) {
  const text = message.toString();
  if (text[0] !== '{') return null;
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

// { betsopen: { game, table } } | <betsOpen game table/>
function parseBetsOpen(message) {
  const j = tryJson(message);
  if (j) {
    const o = j.betsopen || j.betsOpen;
    if (o && (o.game || o.table)) {
      return { game: String(o.game || ''), table: String(o.table || '') };
    }
    return null;
  }
  const text = message.toString();
  if (!/<betsopen/i.test(text)) return null;
  const game = text.match(/game="([^"]+)"/);
  const table = text.match(/table="([^"]+)"/);
  return game && table ? { game: game[1], table: table[1] } : null;
}

function isBetsClosingSoon(message) {
  const j = tryJson(message);
  if (j) return !!(j.betsclosingsoon || j.betsClosingSoon);
  return /<betsclosingsoon/i.test(message.toString());
}

function isBetsClosed(message) {
  const j = tryJson(message);
  if (j) return !!(j.betsclosed || j.betsClosed);
  return /<betsclosed/i.test(message.toString());
}

// Número sorteado. JSON: { gameresult: { score } } ou { sc: { gameresult: { score } } }.
function parseWinningNumber(message) {
  const j = tryJson(message);
  if (j) {
    const gr = j.gameresult || j.gameResult || (j.sc && (j.sc.gameresult || j.sc.gameResult));
    if (gr && gr.score !== undefined && String(gr.pre) !== 'true') {
      const n = parseInt(gr.score, 10);
      return Number.isNaN(n) ? null : n;
    }
    return null;
  }
  const text = message.toString();
  let m = text.match(/<gameresult[^>]*score="(\d+)"/i);
  if (m) return parseInt(m[1], 10);
  m = text.match(/<winning[^>]*number="(\d+)"/i);
  if (m) return parseInt(m[1], 10);
  return null;
}

// Segundos restantes de aposta. JSON: { timer: { value } } (type auto) ou
// betsopen/betsclosingsoon com atributo time. XML: tenta atributos comuns.
function parseCountdownSeconds(message) {
  const j = tryJson(message);
  if (j) {
    const t = j.timer;
    if (t && t.value !== undefined) {
      let v = parseInt(t.value, 10);
      if (v > 1000) v = Math.round(v / 1000);
      if (v >= 0 && v <= 120) return v;
    }
    const o = j.betsopen || j.betsOpen;
    if (o && o.time !== undefined) {
      let v = parseInt(o.time, 10);
      if (v > 1000) v = Math.round(v / 1000);
      if (v >= 0 && v <= 120) return v;
    }
    return null;
  }
  const text = message.toString();
  const attrs = ['bettime', 'bet_time', 'time', 'seconds', 'secs', 'sec',
    'duration', 'remaining', 'timeleft', 'time_left', 'countdown'];
  for (const a of attrs) {
    const m = text.match(new RegExp(`${a}="?(\\d+)"?`, 'i'));
    if (m) {
      let v = parseInt(m[1], 10);
      if (v > 1000) v = Math.round(v / 1000);
      if (v > 0 && v <= 120) return v;
    }
  }
  return null;
}

// Histórico de números já sorteados (mais recente primeiro), quando a mesa
// manda o snapshot inicial: { StatisticHistory: { history: [{ gr }, ...] } }.
function parseHistory(message) {
  const j = tryJson(message);
  const h = j && (j.StatisticHistory || j.statisticHistory);
  if (!h || !Array.isArray(h.history)) return null;
  const nums = h.history
    .map((x) => parseInt(x.gr, 10))
    .filter((n) => Number.isInteger(n) && n >= 0 && n <= 36);
  return nums.length ? nums : null;
}

// True se a mensagem é apenas ruído (contagem de jogadores, zoom, etc.) —
// usado só para não poluir o log ao vivo.
function isNoise(message) {
  const j = tryJson(message);
  if (!j) return false;
  const k = Object.keys(j)[0];
  return ['playersCount', 'zoomIn', 'zoomOut', 'winners', 'dealer', 'chat'].includes(k);
}

// Retorna a fase/segundos derivados de UMA mensagem (ou null se não muda estado).
function parsePhase(message) {
  const open = parseBetsOpen(message);
  if (open) return { phase: 'open', gameInfo: open, seconds: parseCountdownSeconds(message) };
  if (isBetsClosingSoon(message)) return { phase: 'closing', seconds: 0 };
  if (isBetsClosed(message)) return { phase: 'closed', seconds: null };
  return null;
}

// Classifica uma mensagem num rótulo humano curto (para o log ao vivo).
function classify(message) {
  const open = parseBetsOpen(message);
  if (open) {
    const s = parseCountdownSeconds(message);
    return { kind: 'open', label: s ? `Apostas abertas (${s}s)` : 'Apostas abertas', seconds: s };
  }
  if (isBetsClosingSoon(message)) return { kind: 'closing', label: 'Encerrando…', seconds: null };
  if (isBetsClosed(message)) return { kind: 'closed', label: 'Apostas fechadas', seconds: null };
  const n = parseWinningNumber(message);
  if (n !== null && !Number.isNaN(n)) return { kind: 'result', label: `Resultado: ${n}`, seconds: null, number: n };
  return null;
}

module.exports = {
  parseWinningNumber,
  parseBetsOpen,
  isBetsClosingSoon,
  isBetsClosed,
  parseCountdownSeconds,
  parseHistory,
  parsePhase,
  isNoise,
  classify,
};
