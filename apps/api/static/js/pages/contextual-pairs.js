(() => {
  "use strict";

  const API_URL = "/api/ranking-similaridade-pares";
  const POLL_MS = 3000;
  const TAB_KEY = "revesbot-contextual-pairs-tab";
  const RED = new Set([1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36]);
  const clock = new Intl.DateTimeFormat("pt-BR", {
    timeZone: "America/Sao_Paulo", hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
  const dayClock = new Intl.DateTimeFormat("pt-BR", {
    timeZone: "America/Sao_Paulo", day: "2-digit", month: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
  const WORKER_LABELS = {
    online: ["Worker online", "badge-won"],
    atrasado: ["Worker atrasado", "badge-warn"],
    offline: ["Worker offline", "badge-lost"],
    configuracao_pendente: ["Configuração pendente", "badge-warn"],
  };
  const SEARCH_STATUS = {
    failed: "A busca deste número falhou; será refeita no próximo resultado.",
    insufficient_history: "Ainda não havia 9 resultados até este número.",
  };
  // Etiquetas de qualidade (apps/contextual_pairs/quality.py). "base" = acertos/sinais da leitura dos 1.070 sinais de
  // 16 e 17/11/2026 em que as regras foram achadas; os quadros contam só os sinais abertos depois das etiquetas.
  const TAGS = {
    high_quality: { label: "★ Alta qualidade", badge: "badge-quality", prefix: "quality", base: [82, 84] },
    watch_12_15_exact_near: { label: "Monitorando 12–15", badge: "badge-watch", prefix: "watch", base: [278, 285] },
    // Teste ao vivo fixado em 24/11/2026: soma dos 7 números do ranking reduzida a 5, 6 ou 7 e aposta de 9–11, 14 ou
    // 19–22 fichas; joga até a 2ª (5 e 6) ou só a 1ª (7). Base: 1.081 sinais de 16 a 24/11, +14,2% com R$ 1 por número.
    supremo: { label: "◆ Supremo", badge: "badge-supremo", prefix: "supremo", base: [642, 1081] },
  };
  const SCREEN_TEXT = {
    opened: "Sinal aberto com este par.",
    active: "Este par já tem um sinal em andamento; só um par diferente abre outro.",
    no_intersection: "Par sem interseção: nenhuma aposta neste ranking.",
    waiting: "Aguardando o worker…",
  };

  let renderedVersion = null;
  let timer = null;
  let controller = null;

  const $ = (id) => document.getElementById(id);

  function node(tag, className = "", text = null) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== null) element.textContent = String(text);
    return element;
  }

  function chip(number, extra = "") {
    const color = number === 0 ? "green" : RED.has(number) ? "red" : "black";
    const element = node("span", `num-chip roulette-${color} ${extra}`.trim(), number);
    element.setAttribute("aria-label", `Número ${number}`);
    return element;
  }

  function chipList(numbers, decorate = () => "") {
    const list = node("span", "chip-list");
    if (!Array.isArray(numbers)) {
      list.textContent = "—";
      return list;
    }
    numbers.forEach((number) => list.append(chip(number, decorate(number))));
    return list;
  }

  // The pair, e.g. "3 · 7".
  function pairView(pair) {
    const view = node("span", "pair-numbers");
    if (!Array.isArray(pair) || pair.length !== 2) {
      view.textContent = "—";
      return view;
    }
    view.append(chip(pair[0]), node("span", "pair-dot", "·"), chip(pair[1]));
    return view;
  }

  // The numbers the protection rule added to the bet (the ones between the two groups), or a dash.
  function protectionView(numbers) {
    if (!Array.isArray(numbers) || !numbers.length) return node("span", "muted", "—");
    return chipList(numbers, () => "protection");
  }

  // The bet in runs of adjacent pockets of the wheel; full chips are the intersection, light ones the neighbors,
  // the gold outline marks the two numbers of the pair (always in the bet, without their neighbors) and the
  // purple outline marks the protection numbers.
  function arcsView(arcs, kept, hitNumber = null, pair = [], protection = []) {
    const keptNumbers = new Set(kept || []);
    const pairNumbers = new Set(pair || []);
    const protectionNumbers = new Set(protection || []);
    const wrapper = node("span", "arc-list");
    if (!Array.isArray(arcs) || !arcs.length) {
      wrapper.textContent = "—";
      return wrapper;
    }
    arcs.forEach((arc) => {
      const group = node("span", "arc");
      arc.forEach((number) => {
        const classes = [
          keptNumbers.has(number) || pairNumbers.has(number) || protectionNumbers.has(number) ? "" : "neighbor",
          pairNumbers.has(number) ? "base" : "",
          protectionNumbers.has(number) ? "protection" : "",
          number === hitNumber ? "hit" : "",
        ].filter(Boolean);
        group.append(chip(number, classes.join(" ")));
      });
      wrapper.append(group);
    });
    return wrapper;
  }

  function formatTime(value, withDay = false) {
    if (!value) return "—";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? "—" : (withDay ? dayClock : clock).format(date);
  }

  function percentText(hits, total) {
    return `${(hits / total * 100).toLocaleString("pt-BR", { maximumFractionDigits: 1 })}%`;
  }

  function percent(hits, total) {
    if (!total) return "nenhum sinal encerrado ainda";
    return `${percentText(hits, total)} de acerto nos encerrados`;
  }

  // Why a signal carries its tag: the size of the bet and how long ago a number of it came out before the signal.
  function tagTitle(signal) {
    const context = signal && signal.entry_context;
    if (!context) return "";
    const distance = context.last_exact_distance;
    const when = distance === null || distance === undefined
      ? "nenhum número da aposta nos 10 últimos resultados"
      : distance === 1 ? "o resultado que abriu o sinal estava na aposta"
        : `o último número da aposta saiu ${distance} resultados atrás (o que abriu o sinal conta como 1)`;
    return `Aposta de ${context.chips} fichas · ${when}`;
  }

  // Até onde um sinal Supremo é jogado: até a 2ª (soma 5 ou 6) ou só a 1ª (soma 7).
  function supremoPlay(context) {
    return context && context.play_until === 2 ? "jogar até a 2ª" : "jogar só a 1ª";
  }

  function supremoTitle(signal) {
    const context = signal && signal.supremo;
    if (!context) return "";
    return `Soma do ranking ${context.rank_sum} → ${context.rank_root} · aposta de ${context.chips} fichas · ${supremoPlay(context)}`;
  }

  // Resultado do Supremo: só vale o acerto até a rodada que a regra joga; um acerto depois disso é erro para ele.
  function supremoLabel(signal) {
    const context = signal && signal.supremo;
    if (!context) return TAGS.supremo.label;
    const play = supremoPlay(context);
    if (signal.status === "open") return `${TAGS.supremo.label} · ${play}`;
    const won = signal.status === "hit" && signal.hit_attempt <= context.play_until;
    return `${TAGS.supremo.label} · ${won ? "✓" : "✗"} ${play}`;
  }

  function tagBadges(tags, signal = null) {
    const list = node("span", "tag-list");
    (Array.isArray(tags) ? tags : []).forEach((tag) => {
      const info = TAGS[tag];
      if (!info) return;
      const supremo = tag === "supremo";
      const badge = node("span", `badge ${info.badge}`, supremo ? supremoLabel(signal) : info.label);
      const title = supremo ? supremoTitle(signal) : tagTitle(signal);
      if (title) badge.title = title;
      list.append(badge);
    });
    return list;
  }

  function money(value) {
    const sign = value > 0 ? "+" : value < 0 ? "−" : "";
    return `${sign}R$ ${Math.abs(value).toLocaleString("pt-BR")}`;
  }

  function knownTags(tags) {
    return Array.isArray(tags) ? tags.filter((tag) => TAGS[tag]) : [];
  }

  // Closed signals that carried each tag since the tags went live, next to the rate they had where they were found.
  function renderTagStats(counters) {
    const tags = counters || {};
    $("tags-since").textContent = tags.since ? ` · contagem desde ${formatTime(tags.since, true)}` : "";
    Object.entries(TAGS).forEach(([tag, info]) => {
      const counter = tags[tag] || { hits: 0, total: 0 };
      const base = `base ${percentText(info.base[0], info.base[1])} (${info.base[0]}/${info.base[1]})`;
      $(`${info.prefix}-hits`).textContent = counter.total ? `${counter.hits}/${counter.total}` : "—";
      $(`${info.prefix}-rate`).textContent = counter.total
        ? `${percentText(counter.hits, counter.total)} de acerto · ${base}` : `nenhum encerrado ainda · ${base}`;
    });
  }

  // Supremo: acerto dentro das rodadas jogadas e resultado com R$ 1 por número, desde que a etiqueta entrou no ar.
  function renderSupremo(supremo) {
    const data = supremo || {};
    $("supremo-since").textContent = data.since ? ` · contagem desde ${formatTime(data.since, true)}` : "";
    const staked = data.staked || 0;
    const net = data.net || 0;
    $("supremo-money").textContent = staked ? money(net) : "—";
    $("supremo-money-sub").textContent = staked
      ? `${(net / staked * 100).toLocaleString("pt-BR", { maximumFractionDigits: 1, signDisplay: "exceptZero" })}% de ${money(staked).replace("+", "")} apostados · base +14,2%`
      : "nenhum encerrado ainda · base +14,2% (+R$ 2.865 em 1.081 sinais)";
  }

  function renderWorker(data) {
    const [label, badgeClass] = WORKER_LABELS[data.worker.status] || WORKER_LABELS.offline;
    const badge = $("worker-badge");
    badge.textContent = label;
    badge.className = `badge ${badgeClass}`;
    if (data.worker.detail) badge.title = data.worker.detail;
    else badge.removeAttribute("title");
    $("updated-at").textContent = data.updated_at ? `Ranking de ${formatTime(data.updated_at)}` : "";
  }

  function renderRanking(data) {
    const list = $("ranking-numbers");
    list.replaceChildren();
    const top = data.ranking.top || [];
    if (!top.length) {
      list.append(node("li", "placeholder", "Aguardando o worker…"));
      return;
    }
    top.forEach((row) => {
      const item = node("li", "ranking-item");
      item.append(chip(row.number, "chip-xl"), node("small", "", `${row.position}º`));
      item.title = `${row.points} pontos · ${row.exact} exatas · ${row.neighbor} como vizinho`;
      list.append(item);
    });
  }

  // What the ranking on screen did: opened a signal, was blocked by an open signal of the same pair, or was ignored.
  function renderScreen(data) {
    const screen = data.screen || {};
    const state = screen.state || "waiting";
    const bases = screen.bases || [];
    let message = SCREEN_TEXT[state] || SCREEN_TEXT.waiting;
    if (state === "no_pair") message = `Sem par: o ranking tem ${bases.length} número(s) de 0 a 9.`;
    if (state === "too_many") message = `Ignorado: o ranking tem ${bases.length} números de 0 a 9 (${bases.join(", ")}).`;
    if (state === "ignored") message = `Par ${(screen.pair || []).join(" e ")} ignorado: é uma exceção da estratégia.`;
    const text = $("pair-state");
    text.textContent = message;
    text.dataset.state = state;

    const hasPair = Array.isArray(screen.pair) && screen.pair.length === 2;
    const hasBet = Array.isArray(screen.arcs) && screen.arcs.length > 0;
    $("pair-detail").hidden = !(hasPair || hasBet);
    $("pair-numbers-block").hidden = !hasPair;
    $("pair-bet-block").hidden = !hasBet;
    $("pair-numbers").replaceChildren(...(hasPair ? [pairView(screen.pair)] : []));
    $("pair-bet").replaceChildren(...(hasBet ? [arcsView(screen.arcs, screen.kept, null, screen.pair, screen.protection)] : []));
    const hasProtection = hasBet && Array.isArray(screen.protection) && screen.protection.length > 0;
    $("pair-protection-block").hidden = !hasProtection;
    $("pair-protection").replaceChildren(...(hasProtection ? [protectionView(screen.protection)] : []));

    const tags = knownTags(screen.tags);
    $("pair-tags").hidden = !tags.length;
    $("pair-tags").replaceChildren(...(tags.length ? [tagBadges(tags)] : []));
  }

  function renderLastNumbers(data) {
    const list = $("last-numbers");
    list.replaceChildren();
    const items = data.last_numbers || [];
    if (!items.length) {
      list.append(node("li", "placeholder", "—"));
      return;
    }
    items.forEach((item, index) => {
      const entry = node("li", "last-item");
      const mark = item.hit === true ? ["✓", "mark-hit", "estava na aposta do par"]
        : item.hit === false ? ["✗", "mark-miss", "fora da aposta do par"] : ["–", "mark-none", "sem aposta no ar"];
      const verdict = node("span", `mark ${mark[1]}`, mark[0]);
      verdict.setAttribute("aria-label", mark[2]);
      entry.append(chip(item.number, "chip-lg"), verdict, node("small", "", index === 0 ? "mais recente" : formatTime(item.timestamp)));
      list.append(entry);
    });
  }

  function signalBadge(signal, limit) {
    if (signal.status === "hit") return node("span", "badge badge-won", `Acertou na ${signal.hit_attempt}ª`);
    if (signal.status === "miss") return node("span", "badge badge-lost", "Errou");
    return node("span", "badge badge-monitoring", `Em andamento · ${signal.checks.length}/${limit}`);
  }

  function renderHistory(data) {
    const limit = data.attempts_limit || 7;
    const recent = data.summary.recent;
    const total = data.summary.all_time;
    const rankings = data.summary.rankings || {};
    $("attempts-limit").textContent = String(limit);
    $("recent-hits").textContent = recent.total ? `${recent.hits}/${recent.total}` : "—";
    $("recent-rate").textContent = percent(recent.hits, recent.total);
    $("total-hits").textContent = total.total ? `${total.hits.toLocaleString("pt-BR")}/${total.total.toLocaleString("pt-BR")}` : "—";
    $("total-rate").textContent = percent(total.hits, total.total);
    $("open-count").textContent = String(data.summary.open ?? 0);
    renderTagStats(data.summary.tags);
    renderSupremo(data.summary.supremo);
    const openPairs = data.history.filter((signal) => signal.status === "open").map((signal) => signal.pair.join(" · "));
    $("open-pairs").textContent = openPairs.length ? `pares: ${openPairs.join(", ")}` : "nenhum par em andamento";
    $("ranking-counters").textContent = rankings.total
      ? `${rankings.total.toLocaleString("pt-BR")} rankings analisados desde o início: ${rankings.opened} abriram sinal · ${rankings.active} com o par já em andamento · ${rankings.ignored || 0} com par ignorado · ${rankings.no_pair} sem par · ${rankings.too_many} com 3 ou mais números de 0 a 9 · ${rankings.no_intersection} com par sem interseção.`
      : "";

    const body = $("history-rows");
    body.replaceChildren();
    if (!data.history.length) {
      const row = body.insertRow();
      const cell = row.insertCell();
      cell.colSpan = 7;
      cell.className = "empty";
      cell.textContent = "Nenhum sinal registrado ainda.";
      return;
    }
    data.history.forEach((signal) => {
      const row = body.insertRow();
      if (signal.status === "open") row.classList.add("signal-open");
      if (knownTags(signal.tags).includes("high_quality")) row.classList.add("signal-quality");
      if (knownTags(signal.tags).includes("supremo")) row.classList.add("signal-supremo");
      const origin = node("div", "signal-origin");
      const after = node("span", "signal-after");
      after.append(node("small", "muted", "após"), chip(signal.built_after.number));
      origin.append(node("span", "signal-time", formatTime(signal.built_after?.timestamp || signal.created_at, true)), after);
      row.insertCell().append(origin);
      const status = node("div", "signal-status");
      status.append(signalBadge(signal, limit));
      const signalTags = knownTags(signal.tags);
      if (signalTags.length) status.append(tagBadges(signalTags, signal));
      row.insertCell().append(status);
      row.insertCell().append(pairView(signal.pair));
      row.insertCell().append(chipList(signal.top_numbers));
      row.insertCell().append(arcsView(signal.bet_arcs, signal.kept, signal.hit_number, signal.pair, signal.protection));
      row.insertCell().append(protectionView(signal.protection));
      const rounds = node("span", "rounds");
      const checked = node("span", "chip-list");
      signal.checks.forEach((check) => checked.append(chip(check.number, check.hit ? "hit" : "")));
      rounds.append(checked, node("small", "muted", `${signal.checks.length}/${limit}`));
      row.insertCell().append(rounds);
    });
  }

  function occurrenceStatus(occurrence) {
    if (occurrence.preceding === null) return "Anterior indisponível";
    return occurrence.approved ? "Aprovada" : "Abaixo do corte";
  }

  function renderSearch(search) {
    const block = node("article", "search-block");
    const header = node("header", "search-header");
    const title = node("div", "search-title");
    title.append(node("span", "", "Número"), chip(search.trigger.number), node("small", "muted", `às ${formatTime(search.trigger.timestamp)}`));
    header.append(title);

    const meta = node("div", "search-meta");
    const live = new Set(search.live_numbers || []);
    const context = new Set(search.current_context || []);
    const sequence = new Set(search.sequence || []);
    const liveClass = (number) => (live.has(number) ? "live" : "");
    const addMeta = (label, numbers, decorate) => {
      const group = node("span", "meta-group");
      group.append(node("small", "muted", label), chipList(numbers, decorate));
      meta.append(group);
    };
    addMeta("Contexto anterior", search.current_context, liveClass);
    addMeta("Sequência buscada", search.sequence, liveClass);
    if (live.size) addMeta("Saíram depois", search.live_numbers, () => "live");
    header.append(meta);
    block.append(header);

    if (search.status !== "ok") {
      block.append(node("p", "empty", search.error ? `${SEARCH_STATUS[search.status] || ""} ${search.error}`.trim() : SEARCH_STATUS[search.status] || "Busca indisponível."));
      return block;
    }
    if (!search.occurrences.length) {
      block.append(node("p", "empty", "A busca não encontrou ocorrências para este número."));
      return block;
    }
    const wrap = node("div", "table-wrap");
    const table = node("table", "strength-table");
    const head = table.createTHead().insertRow();
    ["Pos.", "Anterior", "Sequência", "Posterior", "Exatas", "Vizinhas", "Similaridade", "Status"]
      .forEach((label) => head.append(node("th", "", label)));
    const body = table.createTBody();
    search.occurrences.forEach((occurrence) => {
      const row = body.insertRow();
      row.insertCell().textContent = `${occurrence.position}º`;
      row.insertCell().append(chipList(occurrence.preceding,
        (number) => `${context.has(number) ? "match" : ""} ${liveClass(number)}`));
      row.insertCell().append(chipList(occurrence.context,
        (number) => `${sequence.has(number) ? "match" : ""} ${liveClass(number)}`));
      row.insertCell().append(chipList(occurrence.following, liveClass));
      row.insertCell().textContent = occurrence.exact ?? "—";
      row.insertCell().textContent = occurrence.neighbor ?? "—";
      row.insertCell().textContent = occurrence.similarity == null
        ? "—" : `${Number(occurrence.similarity).toLocaleString("pt-BR", { maximumFractionDigits: 1 })}%`;
      row.insertCell().textContent = occurrenceStatus(occurrence);
    });
    wrap.append(table);
    block.append(wrap, node("small", "muted", `${search.total_matches} ocorrência(s) encontradas na busca`));
    return block;
  }

  function renderAnalysis(data) {
    const list = $("analysis-list");
    list.replaceChildren();
    if (!data.analysis.length) {
      list.append(node("p", "empty", "Aguardando o worker…"));
      return;
    }
    data.analysis.forEach((search) => list.append(renderSearch(search)));
  }

  async function refresh() {
    controller?.abort();
    controller = new AbortController();
    try {
      const response = await fetch(API_URL, {
        headers: { Accept: "application/json" }, cache: "no-store", signal: controller.signal,
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      renderWorker(data);
      if (data.version !== renderedVersion) {
        renderRanking(data);
        renderScreen(data);
        renderLastNumbers(data);
        renderHistory(data);
        renderAnalysis(data);
        renderedVersion = data.version;
      }
    } catch (error) {
      if (error.name === "AbortError") return;
      const badge = $("worker-badge");
      badge.textContent = "Sem conexão com a API";
      badge.className = "badge badge-lost";
    } finally {
      schedule();
    }
  }

  function schedule() {
    clearTimeout(timer);
    timer = document.hidden ? null : setTimeout(refresh, POLL_MS);
  }

  function selectTab(name, focus = false) {
    ["history", "analysis"].forEach((tabName) => {
      const active = tabName === name;
      const tab = $(`tab-${tabName}`);
      tab.classList.toggle("active", active);
      tab.setAttribute("aria-selected", String(active));
      tab.tabIndex = active ? 0 : -1;
      $(`panel-${tabName}`).hidden = !active;
      if (active && focus) tab.focus();
    });
    try { localStorage.setItem(TAB_KEY, name); } catch (_) { /* opcional */ }
  }

  document.querySelectorAll('[role="tab"]').forEach((tab) => {
    tab.addEventListener("click", () => selectTab(tab.id.replace("tab-", "")));
    tab.addEventListener("keydown", (event) => {
      if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
      event.preventDefault();
      selectTab(tab.id === "tab-history" ? "analysis" : "history", true);
    });
  });
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) clearTimeout(timer);
    else refresh();
  });

  let savedTab = "history";
  try { savedTab = localStorage.getItem(TAB_KEY) === "analysis" ? "analysis" : "history"; } catch (_) { /* opcional */ }
  selectTab(savedTab);
  refresh();
})();
