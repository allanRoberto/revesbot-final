// Gerencia N sessões de mesa simultâneas (uma por usuário/jogo).
// Cada sessão mantém uma conexão WebSocket própria com a mesa da Pragmatic,
// captura o estado (fase das apostas, últimos números) e envia apostas.
// Emite eventos ('state' e 'result') para os assinantes SSE.

const { randomUUID } = require('crypto');
const { EventEmitter } = require('events');
const WebSocket = require('ws');
const { captureGameWsUrl } = require('./capture');
const { AutomationRunner } = require('./automationRunner');
const {
  parseWinningNumber,
  parseBetsOpen,
  isBetsClosingSoon,
  isBetsClosed,
  parseCountdownSeconds,
  parseHistory,
  classify,
} = require('./tableParser');
const { buildBetMessage } = require('./wheel');

const RECONNECT_DELAY_MS = 2000;
const IDLE_TTL_MS = Number(process.env.SESSION_IDLE_TTL_MS || 30 * 60 * 1000);
const MAX_HISTORY = 30;

class Session extends EventEmitter {
  constructor(id, { gameWsUrl, rouletteId }) {
    super();
    this.setMaxListeners(0); // muitos assinantes SSE
    this.id = id;
    this.gameWsUrl = gameWsUrl;
    this.rouletteId = rouletteId || null;
    this.ws = null;
    this.gameInfo = null; // { game, table }
    this.phase = 'idle'; // idle | open | closing | closed
    this.secondsLeft = null; // segundos restantes na fase de aposta (se a mesa informar)
    this.phaseAt = Date.now(); // quando entrou na fase atual (p/ derivar countdown)
    this.lastResult = null;
    this.lastResultAt = 0;
    this.lastNumbers = []; // histórico (mais recente primeiro), até MAX_HISTORY
    this.lastActivity = Date.now();
    this.closedByUser = false;
    this.clientKey = null;
    this.kicked = false; // derrubado por conexão duplicada (não reconectar em loop)
    this.automation = null;
  }

  // Aposta é aceita enquanto ABERTA e também na janela de "encerrando" — o
  // Pragmatic ainda aceita bets durante o <betsClosingSoon> (mesmo comportamento
  // do bot_automatico, que só bloqueia no <betsClosed>).
  get betsOpen() {
    return this.phase === 'open' || this.phase === 'closing';
  }

  setPhase(phase, seconds) {
    this.phase = phase;
    this.phaseAt = Date.now();
    if (seconds !== undefined) this.secondsLeft = seconds;
  }

  touch() {
    this.lastActivity = Date.now();
  }

  connect() {
    this.ws = new WebSocket(this.gameWsUrl);
    this.ws.on('open', () => console.log(`[${this.id}] mesa conectada`));
    this.ws.on('message', (data) => this.handleMessage(data));
    this.ws.on('close', (code) => {
      console.log(`[${this.id}] mesa desconectada (code=${code})`);
      if (this.phase !== 'idle') { this.setPhase('closed', null); this.emitState(); }
      // Se foi kick por duplicação, NÃO reconectar (senão entra em loop de
      // expulsão com a outra conexão da mesma conta).
      if (!this.closedByUser && !this.kicked) {
        setTimeout(() => { if (!this.closedByUser && !this.kicked) this.connect(); }, RECONNECT_DELAY_MS);
      }
    });
    this.ws.on('error', (err) => console.error(`[${this.id}] erro no WS:`, err.message));
  }

  handleMessage(data) {
    const text = data.toString();

    // DEBUG temporário: dump de TODA mensagem crua (primeiros 200 chars) p/
    // descobrir o formato real do feed da mesa. Remover depois.
    if (process.env.DEBUG_RAW === '1') {
      console.log(`[${this.id}] RAW: ${text.slice(0, 200).replace(/\n/g, ' ')}`);
    }

    // Kick por conexão duplicada (mesma conta abriu a mesa em outro lugar).
    if (/duplicate connection|duplicated_connection|DOUBLE_SUBSCRIPTION/i.test(text)) {
      this.kicked = true;
      this.emit('log', { at: Date.now(), kind: 'closed', label: 'Conta conectada em outro lugar' });
      this.emitState();
      return;
    }

    // Log ao vivo: repassa toda mensagem reconhecida da mesa para os assinantes
    // (o front mostra "mesa aberta / segundos / encerrando / resultado").
    const info = classify(text);
    if (info) {
      this.emit('log', { at: Date.now(), kind: info.kind, label: info.label });
    }

    const open = parseBetsOpen(text);
    if (open) {
      this.gameInfo = open;
      // o timer (segundos) costuma chegar logo antes do betsopen — se o betsopen
      // não trouxer o tempo, preserva o que o timer já informou.
      const secs = parseCountdownSeconds(text);
      this.setPhase('open', secs !== null ? secs : this.secondsLeft);
      this.emitState();
      void this.automation?.onBetsOpen();
      return;
    }
    if (isBetsClosingSoon(text)) {
      // A Pragmatic costuma avisar "closing soon" quando ainda restam cerca
      // de 6 segundos. Preserva o último valor do timer para a interface
      // continuar a contagem até o fechamento efetivo das apostas.
      this.setPhase('closing');
      this.emitState();
      return;
    }
    if (isBetsClosed(text)) {
      this.setPhase('closed', null);
      this.emitState();
      return;
    }

    // Snapshot inicial do histórico (mesa JSON manda ao conectar).
    const hist = parseHistory(text);
    if (hist && this.lastNumbers.length === 0) {
      this.lastNumbers = hist.slice(0, MAX_HISTORY);
      if (this.lastResult === null) {
        this.lastResult = hist[0];
        this.lastResultAt = Date.now(); // dedupe do snapshot 'sc' que vem logo depois
      }
      this.emitState();
      return;
    }

    // Countdown ao vivo (mensagem timer type=auto): indica rodada de aposta
    // começando/em andamento. Abre a fase e atualiza os segundos.
    const secs = parseCountdownSeconds(text);
    if (secs !== null) {
      this.setPhase('open', secs);
      this.emitState();
      void this.automation?.onBetsOpen();
      return;
    }

    const n = parseWinningNumber(text);
    if (n !== null && !Number.isNaN(n)) {
      const now = Date.now();
      // dedupe: ignora repetição do mesmo número em janela curta (reconexão/replay)
      if (!(n === this.lastResult && now - this.lastResultAt < 5000)) {
        this.lastResult = n;
        this.lastResultAt = now;
        this.lastNumbers = [n, ...this.lastNumbers].slice(0, MAX_HISTORY);
        this.emit('result', n);
        this.emitState();
        void this.automation?.onResult(n);
      }
    }
  }

  emitState() {
    this.emit('state', this.state());
  }

  startAutomation(config) {
    if (this.automation && ['running', 'stopping'].includes(this.automation.status)) {
      throw new Error('O automático já está ligado nesta mesa.');
    }
    this.automation = new AutomationRunner(this, config);
    this.emitState();
    // Se a chamada aconteceu durante uma rodada já aberta, não espera a próxima.
    if (this.betsOpen) void this.automation.onBetsOpen();
    return this.automation.state();
  }

  async stopAutomation(reason = 'user_stop') {
    if (!this.automation) return null;
    return this.automation.stop(reason);
  }

  // bets: { numero: valor } — o slip completo com o valor acumulado por número.
  bet(bets) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      throw new Error('Conexão com a mesa ainda não está pronta. Aguarde alguns segundos.');
    }
    if (!this.betsOpen) {
      const motivo = this.phase === 'closed' ? 'As apostas já fecharam nesta rodada.'
        : this.phase === 'idle' ? 'Aguardando a próxima rodada abrir.'
        : 'As apostas não estão abertas no momento.';
      throw new Error(motivo);
    }
    const message = buildBetMessage(this.gameInfo, bets);
    if (process.env.DEBUG_RAW === '1') {
      console.log(`[${this.id}] BET SEND: ${message}`);
    }
    this.ws.send(message);
    this.touch();
    return { bets, gameInfo: this.gameInfo };
  }

  state() {
    return {
      sessionId: this.id,
      connected: !!this.ws && this.ws.readyState === WebSocket.OPEN,
      phase: this.phase,
      betsOpen: this.betsOpen,
      secondsLeft: this.secondsLeft,
      phaseAt: this.phaseAt,
      kicked: this.kicked,
      gameInfo: this.gameInfo,
      lastResult: this.lastResult,
      lastNumbers: this.lastNumbers,
      rouletteId: this.rouletteId,
      automation: this.automation?.state() || null,
    };
  }

  destroy() {
    this.closedByUser = true;
    this.emit('closed');
    this.removeAllListeners();
    try { if (this.ws) this.ws.close(); } catch (_) { /* noop */ }
    this.ws = null;
    if (this.automation && ['running', 'stopping'].includes(this.automation.status)) {
      void this.automation.stop('error');
    }
  }
}

class SessionManager {
  constructor() {
    this.sessions = new Map();
    setInterval(() => this.reapIdle(), 60 * 1000).unref();
  }

  async create({ gameLink, rouletteId, clientKey }) {
    if (!gameLink) throw new Error('gameLink é obrigatório.');

    // Uma conexão por conta/mesa: a Pragmatic derruba a sessão antiga se a mesma
    // conta abrir a mesa de novo (DOUBLE_SUBSCRIPTION). Então, se já temos uma
    // sessão viva para este clientKey, REUSA (não recaptura = não faz novo login).
    if (clientKey) {
      for (const s of this.sessions.values()) {
        if (s.clientKey !== clientKey) continue;
        if (s.ws && s.ws.readyState === WebSocket.OPEN) {
          s.touch();
          return s;
        }
        // sessão morta/zumbi para este cliente: descarta antes de recriar.
        s.destroy();
        this.sessions.delete(s.id);
        break;
      }
    }

    const { gameWsUrl } = await captureGameWsUrl(gameLink);
    const id = randomUUID();
    const session = new Session(id, { gameWsUrl, rouletteId });
    session.clientKey = clientKey || null;
    this.sessions.set(id, session);
    session.connect();
    return session;
  }

  get(id, clientKey) {
    const s = this.sessions.get(id);
    if (s && clientKey && s.clientKey !== clientKey) return null;
    if (s) s.touch();
    return s || null;
  }

  destroy(id) {
    const s = this.sessions.get(id);
    if (!s) return false;
    s.destroy();
    this.sessions.delete(id);
    return true;
  }

  destroyAll() {
    for (const id of [...this.sessions.keys()]) this.destroy(id);
  }

  reapIdle() {
    const now = Date.now();
    for (const [id, s] of this.sessions) {
      if (now - s.lastActivity > IDLE_TTL_MS) {
        console.log(`[${id}] sessão expirada por inatividade`);
        s.destroy();
        this.sessions.delete(id);
      }
    }
  }
}

module.exports = { SessionManager };
