(() => {
  const patternKey = document.body.dataset.patternKey;
  let definition = null;
  let bankrollChart = null;

  const money = value => new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(Number(value || 0));
  const percent = value => `${(Number(value || 0) * 100).toFixed(2)}%`;
  const dateTime = value => value ? new Date(value).toLocaleString('pt-BR') : '—';
  const escapeHtml = value => String(value ?? '').replace(/[&<>'"]/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char]));
  const badge = status => `<span class="badge ${escapeHtml(status)}">${escapeHtml({active:'ATIVO',won:'GREEN',lost:'RED',cancelled_gap:'BURACO',skipped_outside_schedule:'FORA DO HORÁRIO'}[status] || status)}</span>`;
  const numbers = values => `<div class="numbers">${(values || []).map(value => `<span class="number">${value}</span>`).join('')}</div>`;

  async function jsonFetch(url, options) {
    const response = await fetch(url, options);
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || `Erro HTTP ${response.status}`);
    return payload;
  }

  function setFinancialClass(element, value) {
    element.classList.remove('positive', 'negative');
    element.classList.add(Number(value) >= 0 ? 'positive' : 'negative');
  }

  async function loadDefinition() {
    const payload = await jsonFetch('/api/patterns');
    definition = (payload.patterns || []).find(item => item.key === patternKey);
    if (!definition) throw new Error('Pattern não cadastrado. Inicie o processo correspondente.');
    document.getElementById('pattern-name').textContent = definition.name;
    document.getElementById('pattern-description').textContent = `${definition.description} · versão ${definition.version}`;
    const accent = definition.ui_schema?.accent;
    if (accent) document.documentElement.style.setProperty('--accent', accent);
    const roulettes = definition.roulette_ids || [];
    for (const selectId of ['roulette-filter', 'simulation-roulette']) {
      const select = document.getElementById(selectId);
      roulettes.forEach(roulette => {
        const option = document.createElement('option');
        option.value = roulette;
        option.textContent = roulette.replace('pragmatic-', '').replaceAll('-', ' ');
        select.appendChild(option);
      });
    }
    const inputs = document.getElementById('attempt-inputs');
    inputs.innerHTML = (definition.default_chip_profile || []).map((value, index) => `
      <label>T${index + 1}<input class="attempt-value" type="number" min="0.01" step="0.01" value="${value}"></label>
    `).join('');
    for (const selectId of ['bet-count-filter', 'simulation-bet-count']) {
      const select = document.getElementById(selectId);
      for (let count = 1; count <= 20; count++) {
        const option = document.createElement('option');
        option.value = String(count); option.textContent = `${count} números`;
        select.appendChild(option);
      }
    }
    const hourSelect = document.getElementById('hour-filter');
    for (let hour = 0; hour < 24; hour++) {
      const option = document.createElement('option');
      option.value = String(hour); option.textContent = `${String(hour).padStart(2, '0')}:00`;
      hourSelect.appendChild(option);
    }
  }

  function renderActive(signals) {
    const target = document.getElementById('active-signals');
    if (!signals?.length) {
      target.innerHTML = '<div class="empty">Nenhuma jogada atual.</div>';
      return;
    }
    target.innerHTML = signals.map(signal => `
      <article class="play">
        <div class="play-head"><strong>${escapeHtml(signal.roulette_id)}</strong>${badge(signal.status)}</div>
        <div class="muted">${dateTime(signal.created_at)} · ${escapeHtml(signal.phase || '')}</div>
        <p><strong>${escapeHtml(signal.target_name || '')}</strong> · ${signal.attempts?.length || 0}/${signal.max_attempts} tentativas</p>
        ${numbers(signal.bet_numbers)}
      </article>
    `).join('');
  }

  async function loadDashboard(force = false) {
    const payload = await jsonFetch(`/api/patterns/${encodeURIComponent(patternKey)}/dashboard${force ? '?refresh=true' : ''}`);
    const runtime = payload.runtime || {};
    const online = runtime.status === 'online' && (!runtime.lease_expires_at || new Date(runtime.lease_expires_at) > new Date());
    const runtimeEl = document.getElementById('runtime-status');
    runtimeEl.textContent = online ? 'ONLINE' : 'OFFLINE';
    runtimeEl.className = online ? 'positive' : 'negative';
    document.getElementById('active-count').textContent = payload.counts?.active ?? 0;
    document.getElementById('resolved-count').textContent = payload.counts?.resolved ?? 0;
    document.getElementById('accuracy').textContent = percent(payload.assertiveness);
    const profitEl = document.getElementById('default-profit');
    profitEl.textContent = money(payload.profit);
    setFinancialClass(profitEl, payload.profit);
    const roiEl = document.getElementById('default-roi');
    roiEl.textContent = percent(payload.roi_on_wagered);
    setFinancialClass(roiEl, payload.roi_on_wagered);
    document.getElementById('dashboard-source').textContent = `Fonte da tela: ${payload.source === 'redis' ? 'Redis' : 'MongoDB'}`;
    renderActive(payload.active_signals || []);
    const breakdown = document.getElementById('roulette-breakdown');
    const rows = Object.entries(payload.by_roulette || {}).sort((a, b) => a[0].localeCompare(b[0]));
    breakdown.innerHTML = rows.length ? rows.map(([roulette, stats]) => `
      <tr><td>${escapeHtml(roulette)}</td><td>${stats.active || 0}</td><td>${stats.resolved || 0}</td><td>${stats.won || 0}</td>
      <td>${percent(stats.assertiveness)}</td><td class="${Number(stats.profit || 0) >= 0 ? 'positive' : 'negative'}">${money(stats.profit)}</td>
      <td class="${Number(stats.roi_on_wagered || 0) >= 0 ? 'positive' : 'negative'}">${percent(stats.roi_on_wagered)}</td></tr>
    `).join('') : '<tr><td colspan="7" class="empty">Aguardando sinais…</td></tr>';
  }

  function renderAttempts(items) {
    return `<div class="attempts">${(items || []).map(item => `<span class="attempt ${item.hit ? 'hit' : 'miss'}">T${item.attempt_number}: ${item.value}</span>`).join('')}</div>`;
  }

  async function loadSignals() {
    const roulette = document.getElementById('roulette-filter').value;
    const status = document.getElementById('status-filter').value;
    const eligible = document.getElementById('eligible-filter').value;
    const params = new URLSearchParams({ limit: '200', status, eligible_only: eligible });
    if (roulette) params.set('roulette_id', roulette);
    const betCount = document.getElementById('bet-count-filter').value;
    const hour = document.getElementById('hour-filter').value;
    const startDate = document.getElementById('start-date-filter').value;
    const endDate = document.getElementById('end-date-filter').value;
    if (betCount) params.set('bet_count', betCount);
    if (hour) params.set('trigger_hour', hour);
    if (startDate) params.set('start_date', startDate);
    if (endDate) params.set('end_date', endDate);
    const payload = await jsonFetch(`/api/patterns/${encodeURIComponent(patternKey)}/signals?${params}`);
    document.getElementById('signal-total').textContent = `${payload.total} sinais`;
    const body = document.getElementById('signals-body');
    if (!payload.signals?.length) {
      body.innerHTML = '<tr><td colspan="7" class="empty">Nenhum sinal encontrado.</td></tr>';
      return;
    }
    body.innerHTML = payload.signals.map(signal => `
      <tr>
        <td>${dateTime(signal.created_at)}</td>
        <td>${escapeHtml(signal.roulette_id)}</td>
        <td>${badge(signal.status)}</td>
        <td>${signal.trigger_number ?? '—'}<br><small>${escapeHtml(signal.target_name || '')}</small></td>
        <td>${numbers(signal.bet_numbers)}<small>${signal.bet_count} números</small></td>
        <td>${renderAttempts(signal.attempts)}</td>
        <td class="${Number(signal.financial?.net_profit || 0) >= 0 ? 'positive' : 'negative'}">${signal.status === 'won' || signal.status === 'lost' ? money(signal.financial?.net_profit) : '—'}</td>
      </tr>
    `).join('');
  }

  function renderSimulationStats(data) {
    document.getElementById('simulation-stats').innerHTML = `
      <div class="stat"><span>Saldo final</span><strong class="${data.profit >= 0 ? 'positive' : 'negative'}">${money(data.ending_bankroll)}</strong></div>
      <div class="stat"><span>Lucro</span><strong class="${data.profit >= 0 ? 'positive' : 'negative'}">${money(data.profit)}</strong></div>
      <div class="stat"><span>ROI apostado</span><strong>${percent(data.roi_on_wagered)}</strong></div>
      <div class="stat"><span>Drawdown</span><strong class="negative">${money(data.max_drawdown)}</strong></div>
      <div class="stat"><span>Assertividade</span><strong>${percent(data.assertiveness)}</strong></div>
      <div class="stat"><span>Acertos / erros</span><strong>${data.wins} / ${data.losses}</strong></div>
    `;
  }

  function renderChart(data) {
    if (bankrollChart) bankrollChart.destroy();
    const points = data.points || [];
    bankrollChart = new Chart(document.getElementById('bankroll-chart'), {
      type: 'line',
      data: {
        labels: points.map(point => point.index === 0 ? 'Início' : `#${point.index}`),
        datasets: [{
          label: 'Banca', data: points.map(point => point.bankroll), fill: true,
          borderColor: getComputedStyle(document.documentElement).getPropertyValue('--accent').trim() || '#177a5b',
          backgroundColor: 'rgba(23,122,91,.08)', tension: .14, borderWidth: 2,
          pointRadius: points.length > 180 ? 1 : 3,
          pointBackgroundColor: points.map(point => point.status === 'won' ? '#18794e' : point.status === 'lost' ? '#b4232d' : '#68756f')
        }]
      },
      options: { responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false }, scales: { x: { ticks: { maxTicksLimit: 12 } } } }
    });
  }

  async function simulate() {
    const attemptValues = [...document.querySelectorAll('.attempt-value')].map(input => Number(input.value));
    const payload = await jsonFetch(`/api/patterns/${encodeURIComponent(patternKey)}/simulation`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        starting_bankroll: Number(document.getElementById('starting-bankroll').value),
        attempt_values: attemptValues,
        roulette_id: document.getElementById('simulation-roulette').value || null,
        bet_count: Number(document.getElementById('simulation-bet-count').value) || null
      })
    });
    renderSimulationStats(payload);
    renderChart(payload);
  }

  async function refresh(force = false) {
    try { await Promise.all([loadDashboard(force), loadSignals()]); }
    catch (error) { console.error(error); alert(error.message); }
  }

  document.getElementById('refresh').addEventListener('click', () => refresh(true));
  document.getElementById('apply-filters').addEventListener('click', loadSignals);
  document.getElementById('simulate').addEventListener('click', () => simulate().catch(error => alert(error.message)));

  (async () => {
    try {
      await loadDefinition();
      await refresh();
      await simulate();
      setInterval(() => loadDashboard().catch(console.error), 5000);
    } catch (error) {
      alert(error.message);
    }
  })();
})();
