(() => {
  "use strict";

  const API_URL = "/api/ranking-similaridade-contextual";
  const POLL_MS = 3000;
  const TAB_KEY = "revesbot-contextual-ranking-tab";
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

  function formatTime(value, withDay = false) {
    if (!value) return "—";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? "—" : (withDay ? dayClock : clock).format(date);
  }

  function percent(hits, total) {
    if (!total) return "nenhum sinal encerrado ainda";
    return `${(hits / total * 100).toLocaleString("pt-BR", { maximumFractionDigits: 1 })}% de acerto nos encerrados`;
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
      const mark = item.hit === true ? ["✓", "mark-hit", "acertou"]
        : item.hit === false ? ["✗", "mark-miss", "errou"] : ["–", "mark-none", "sem ranking no ar"];
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
    $("attempts-limit").textContent = String(limit);
    $("recent-hits").textContent = recent.total ? `${recent.hits}/${recent.total}` : "—";
    $("recent-rate").textContent = percent(recent.hits, recent.total);
    $("total-hits").textContent = total.total ? `${total.hits.toLocaleString("pt-BR")}/${total.total.toLocaleString("pt-BR")}` : "—";
    $("total-rate").textContent = percent(total.hits, total.total);
    $("open-count").textContent = String(data.summary.open ?? 0);

    const body = $("history-rows");
    body.replaceChildren();
    if (!data.history.length) {
      const row = body.insertRow();
      const cell = row.insertCell();
      cell.colSpan = 4;
      cell.className = "empty";
      cell.textContent = "Nenhum sinal registrado ainda.";
      return;
    }
    data.history.forEach((signal) => {
      const row = body.insertRow();
      if (signal.status === "open") row.className = "signal-open";
      const hitNumber = signal.checks.find((check) => check.hit)?.number;
      const origin = node("div", "signal-origin");
      const after = node("span", "signal-after");
      after.append(node("small", "muted", "após"), chip(signal.built_after.number));
      origin.append(node("span", "signal-time", formatTime(signal.built_after?.timestamp || signal.created_at, true)), after);
      row.insertCell().append(origin);
      row.insertCell().append(signalBadge(signal, limit));
      row.insertCell().append(chipList(signal.top_numbers, (number) => (number === hitNumber ? "hit" : "")));
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
