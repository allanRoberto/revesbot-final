(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const red = new Set([1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36]);
  const integer = new Intl.NumberFormat("pt-BR");
  const time = new Intl.DateTimeFormat("pt-BR", { timeZone: "America/Sao_Paulo", hour: "2-digit", minute: "2-digit", second: "2-digit" });
  let token = sessionStorage.getItem("triple-context-live-token") || "";
  let timer = null;

  function ball(number, extra = "") {
    const color = number === 0 ? "green" : red.has(number) ? "red" : "black";
    return `<span class="ball ${color} ${extra}">${number}</span>`;
  }

  function statusLabel(status) {
    return { won: "VITÓRIA", lost: "DERROTA", pending: "EM JOGO", skipped: "IGNORADO" }[status] || status;
  }

  function render(data) {
    $("worker-label").textContent = data.worker.status === "online" ? "Worker online" : "Worker sem resposta";
    $("worker-dot").className = data.worker.status;
    $("hit-rate").textContent = data.summary.hit_rate == null ? "—" : `${data.summary.hit_rate.toFixed(2).replace(".", ",")}%`;
    $("completed-count").textContent = `${integer.format(data.summary.completed)} entradas concluídas`;
    $("wins").textContent = integer.format(data.summary.won);
    $("losses").textContent = integer.format(data.summary.lost);
    $("skipped").textContent = integer.format(data.summary.skipped);
    $("last-update").textContent = `Atualizado às ${time.format(new Date(data.generated_at))}. Próxima atualização automática em 5 segundos.`;

    const current = data.current;
    $("current-empty").hidden = Boolean(current);
    $("current-signal").hidden = !current;
    if (current) {
      $("current-title").textContent = "Aguardando o próximo giro";
      $("current-status").textContent = "1 TENTATIVA";
      $("current-status").className = "status-pill pending";
      $("current-trio").innerHTML = current.trio.map((number) => ball(number)).join("<i>→</i>");
      $("current-ranking").innerHTML = current.ranking.map((row) => ball(row.number, row.position <= 3 ? "leading" : "")).join("");
      $("current-occurrences").textContent = `${integer.format(current.occurrences)} ocorrências do trio`;
      $("current-events").textContent = `${integer.format(current.context_events)} contextos à frente`;
    } else {
      const collected = data.worker.results_in_window;
      $("current-title").textContent = "Aguardando uma janela válida";
      $("current-status").textContent = `${collected}/3 NA JANELA`;
      $("current-status").className = "status-pill";
      $("collector-message").textContent = collected >= 3 ? "Os três resultados mais recentes não formaram uma entrada válida. O próximo giro deslocará a janela." : collected ? `${collected} resultado${collected > 1 ? "s" : ""} disponível${collected > 1 ? "is" : ""} na janela.` : "Aguardando resultados para completar a janela.";
    }

    $("history-body").innerHTML = data.history.map((row) => {
      const top = row.ranking.map((rank) => ball(rank.number)).join("");
      const result = row.result ? ball(row.result.number) : "—";
      const reason = row.skip_reason === "repeated_numbers" ? "números repetidos" : "sem evidência";
      return `<tr><td>${time.format(new Date(row.created_at))}</td><td><div class="mini-numbers">${row.trio.map((n) => ball(n)).join("")}</div></td><td><div class="mini-numbers">${top || `<small>${reason}</small>`}</div></td><td>${result}</td><td><span class="table-status ${row.status}">${statusLabel(row.status)}</span></td></tr>`;
    }).join("");
    $("history-empty").hidden = data.history.length > 0;
  }

  async function load() {
    if (!token) return;
    try {
      const response = await fetch("/api/patterns/triple-context-live?limit=80", { headers: { "X-Live-Dashboard-Token": token, Accept: "application/json" }, cache: "no-store" });
      if (response.status === 401) {
        sessionStorage.removeItem("triple-context-live-token"); token = ""; $("dashboard").hidden = true; $("access-panel").hidden = false; $("access-error").textContent = "Token inválido. Confira e tente novamente."; return;
      }
      if (!response.ok) throw new Error("Monitor temporariamente indisponível.");
      render(await response.json());
      $("access-panel").hidden = true;
      $("dashboard").hidden = false;
      $("access-error").textContent = "";
    } catch (error) {
      $("worker-label").textContent = error.message;
      $("worker-dot").className = "offline";
    } finally {
      window.clearTimeout(timer);
      if (token) timer = window.setTimeout(load, 5000);
    }
  }

  $("access-form").addEventListener("submit", (event) => {
    event.preventDefault();
    token = $("access-token").value.trim();
    if (!token) return;
    sessionStorage.setItem("triple-context-live-token", token);
    load();
  });
  $("refresh-button").addEventListener("click", load);
  if (token) load();
})();
