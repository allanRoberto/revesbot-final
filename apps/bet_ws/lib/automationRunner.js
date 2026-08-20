// Piloto automático vinculado a uma Session do bet_ws.
// A estratégia continua no app Next.js; este runner apenas busca a sugestão,
// envia uma aposta por rodada e liquida o resultado no livro-caixa do app.

const APP_URL = (process.env.AUTOMATION_APP_URL || 'http://127.0.0.1:3000').replace(/\/$/, '');
const INTERNAL_TOKEN = process.env.AUTOMATION_INTERNAL_TOKEN || process.env.BET_WS_TOKEN || '';

async function delay(ms) {
  await new Promise((resolve) => setTimeout(resolve, ms));
}

class AutomationRunner {
  constructor(session, config) {
    this.session = session;
    this.runId = config.runId;
    this.gameId = config.gameId;
    this.targetProfitCents = Number(config.targetProfitCents);
    this.maxLossCents = Number(config.maxLossCents);
    this.chipValueCents = Number(config.chipValueCents);
    this.status = 'running';
    this.netProfitCents = 0;
    this.roundsSettled = 0;
    this.pendingBet = null;
    this.lastRoundId = null;
    this.busy = false;
    this.stopAfterSettlementReason = null;
    // Se o usuário liga durante uma rodada aberta, começamos somente na
    // próxima. Assim não substituímos um slip manual que já esteja na mesa.
    if (session.betsOpen && session.gameInfo?.game) {
      this.lastRoundId = String(session.gameInfo.game);
    }
  }

  state() {
    return {
      runId: this.runId,
      status: this.status,
      netProfitCents: this.netProfitCents,
      targetProfitCents: this.targetProfitCents,
      maxLossCents: this.maxLossCents,
      roundsSettled: this.roundsSettled,
      pendingRoundId: this.pendingBet?.roundId || null,
    };
  }

  async postEvent(event, data) {
    if (!INTERNAL_TOKEN) throw new Error('AUTOMATION_INTERNAL_TOKEN não configurado.');
    let lastError = null;
    for (let attempt = 1; attempt <= 3; attempt += 1) {
      try {
        const res = await fetch(`${APP_URL}/api/internal/automation/events`, {
          method: 'POST',
          headers: {
            'content-type': 'application/json',
            'x-automation-token': INTERNAL_TOKEN,
          },
          body: JSON.stringify({ event, runId: this.runId, ...data }),
        });
        const body = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(body.error || `callback respondeu ${res.status}`);
        return body;
      } catch (error) {
        lastError = error;
        if (attempt < 3) await delay(attempt * 250);
      }
    }
    throw lastError || new Error('Falha ao persistir evento da automação.');
  }

  async suggestion() {
    if (!INTERNAL_TOKEN) throw new Error('AUTOMATION_INTERNAL_TOKEN não configurado.');
    const url = new URL(`${APP_URL}/api/internal/automation/suggestion`);
    url.searchParams.set('gameId', this.gameId);
    const res = await fetch(url, {
      headers: { 'x-automation-token': INTERNAL_TOKEN },
      cache: 'no-store',
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.error || `sugestão respondeu ${res.status}`);
    const numbers = Array.isArray(body.numbers) ? body.numbers : [];
    return [...new Set(numbers.map(Number))]
      .filter((n) => Number.isInteger(n) && n >= 0 && n <= 36);
  }

  async onBetsOpen() {
    if (this.status !== 'running' || this.busy || this.pendingBet) return;
    const roundId = String(this.session.gameInfo?.game || '');
    if (!roundId || roundId === this.lastRoundId) return;

    this.busy = true;
    try {
      const numbers = await this.suggestion();
      if (numbers.length === 0) {
        this.session.emit('log', {
          at: Date.now(),
          kind: 'automation',
          label: 'Automático: rodada sem sinal',
        });
        this.lastRoundId = roundId;
        return;
      }

      const chipValue = this.chipValueCents / 100;
      const bets = Object.fromEntries(numbers.map((number) => [number, chipValue]));
      const betsCents = Object.fromEntries(numbers.map((number) => [number, this.chipValueCents]));
      const totalStakeCents = numbers.length * this.chipValueCents;

      this.session.bet(bets);
      this.pendingBet = { roundId, betsCents, totalStakeCents };
      this.lastRoundId = roundId;
      this.session.emit('log', {
        at: Date.now(),
        kind: 'automation',
        label: `Automático: ${numbers.length} números · R$ ${(totalStakeCents / 100).toFixed(2)}`,
      });
      this.session.emitState();
    } catch (error) {
      await this.fail(error);
    } finally {
      this.busy = false;
    }
  }

  async onResult(winningNumber) {
    if (!this.pendingBet || this.busy) return;
    const pending = this.pendingBet;
    this.busy = true;
    try {
      const winningStakeCents = Number(pending.betsCents[String(winningNumber)] || 0);
      // Aposta cheia: retorno bruto 36x (35x de prêmio + devolução da ficha).
      const payoutCents = winningStakeCents * 36;
      const netProfitCents = payoutCents - pending.totalStakeCents;

      await this.postEvent('round_settled', {
        roundId: pending.roundId,
        betsCents: pending.betsCents,
        totalStakeCents: pending.totalStakeCents,
        winningNumber,
        payoutCents,
        netProfitCents,
        settledAt: new Date().toISOString(),
      });

      this.netProfitCents += netProfitCents;
      this.roundsSettled += 1;
      this.pendingBet = null;
      this.session.emitState();

      let reason = this.stopAfterSettlementReason;
      if (!reason && this.netProfitCents >= this.targetProfitCents) reason = 'target_reached';
      if (!reason && this.netProfitCents <= -this.maxLossCents) reason = 'max_loss';
      if (reason) await this.finish(reason);
    } catch (error) {
      await this.fail(error);
    } finally {
      this.busy = false;
    }
  }

  async stop(reason = 'user_stop') {
    if (this.status === 'stopped' || this.status === 'error') return this.state();
    if (this.pendingBet) {
      this.status = 'stopping';
      this.stopAfterSettlementReason = reason;
      this.session.emitState();
      return this.state();
    }
    await this.finish(reason);
    return this.state();
  }

  async finish(reason) {
    if (this.status === 'stopped') return;
    this.status = 'stopped';
    await this.postEvent('run_stopped', { reason });
    this.session.emit('log', {
      at: Date.now(),
      kind: 'automation',
      label: reason === 'target_reached'
        ? 'Automático: meta atingida'
        : reason === 'max_loss'
          ? 'Automático: limite de perda atingido'
          : 'Automático desligado',
    });
    this.session.emitState();
  }

  async fail(error) {
    const message = error instanceof Error ? error.message : String(error);
    this.status = 'error';
    try {
      await this.postEvent('run_error', { message });
    } catch (callbackError) {
      console.error(`[${this.runId}] callback de erro falhou:`, callbackError.message);
    }
    this.session.emit('log', {
      at: Date.now(),
      kind: 'error',
      label: `Automático pausado: ${message}`,
    });
    this.session.emitState();
  }
}

module.exports = { AutomationRunner };
