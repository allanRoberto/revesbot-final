(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const form = $("ranking-form");
  const inputs = [$("number-latest"), $("number-previous"), $("number-oldest")];
  const redNumbers = new Set([1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36]);
  const integer = new Intl.NumberFormat("pt-BR");
  const points = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 4 });
  const date = new Intl.DateTimeFormat("pt-BR", {
    dateStyle: "short", timeStyle: "short", timeZone: "America/Sao_Paulo",
  });
  let activeController = null;
  let requestId = 0;

  function setState(label, state = "") {
    $("result-state").textContent = label;
    $("result-state").dataset.state = state;
  }

  function setBusy(busy) {
    $("results-region").setAttribute("aria-busy", String(busy));
    $("submit-button").disabled = busy;
    $("submit-label").textContent = busy ? "Consultando…" : "Consultar ranking";
    $("submit-icon").textContent = busy ? "···" : "→";
  }

  function updatePreview() {
    ["preview-latest", "preview-previous", "preview-oldest"].forEach((id, index) => {
      const value = inputs[index].value.trim();
      $(id).textContent = /^\d{1,2}$/.test(value) && Number(value) <= 36 ? String(Number(value)) : "—";
    });
  }

  function resetValidation() {
    $("form-error").hidden = true;
    $("form-error").textContent = "";
    inputs.forEach((input) => input.removeAttribute("aria-invalid"));
  }

  function readNumbers() {
    const values = inputs.map((input) => input.value.trim());
    const invalid = values.map((value) => !/^\d{1,2}$/.test(value) || Number(value) > 36);
    const numbers = values.map(Number);
    let message = "";
    if (invalid.some(Boolean)) {
      message = "Preencha os três campos com números inteiros de 0 a 36.";
    } else if (new Set(numbers).size !== 3) {
      message = "Use três números distintos. Este catálogo não inclui trios com números repetidos.";
      numbers.forEach((number, index) => { invalid[index] = numbers.filter((value) => value === number).length > 1; });
    }
    if (message) {
      $("form-error").textContent = message;
      $("form-error").hidden = false;
      inputs.forEach((input, index) => input.setAttribute("aria-invalid", String(invalid[index])));
      inputs[invalid.findIndex(Boolean)].focus();
      return null;
    }
    return numbers;
  }

  function invalidateResults() {
    requestId += 1;
    if (activeController) activeController.abort();
    activeController = null;
    setBusy(false);
    resetValidation();
    updatePreview();
    $("ranking-results").hidden = true;
    $("error-state").hidden = true;
    $("empty-state").hidden = false;
    $("query-status").textContent = "Configuração alterada. Consulte para ver o novo ranking.";
    setState("Consulta pendente");
  }

  function node(tag, className, content) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (content !== undefined) element.textContent = content;
    return element;
  }

  function validateResponse(data, query) {
    const nonnegativeInteger = (value) => Number.isInteger(value) && value >= 0;
    if (!data || data.direction !== query.direction || data.ordered !== query.ordered
        || data.roulette_id !== "pragmatic-auto-roulette" || data.input_order !== "latest_first"
        || JSON.stringify(data.requested_numbers) !== JSON.stringify(query.numbers)
        || !Array.isArray(data.combination) || data.combination.length !== 3
        || !Array.isArray(data.ranking) || data.ranking.length !== 37
        || new Set(data.ranking.map((row) => row.number)).size !== 37
        || !data.ranking.every((row, index) => row.position === index + 1
          && nonnegativeInteger(row.number) && row.number <= 36
          && Number.isFinite(row.score) && row.score >= 0 && nonnegativeInteger(row.direct_hits))
        || typeof data.has_evidence !== "boolean"
        || !nonnegativeInteger(data.occurrences) || !nonnegativeInteger(data.context_events)
        || !nonnegativeInteger(data.complete_occurrences)
        || data.depth !== (query.direction === "forward" ? 20 : 10)
        || !data.source || !nonnegativeInteger(data.source.records)
        || !Number.isFinite(Date.parse(data.source.first_timestamp))
        || !Number.isFinite(Date.parse(data.source.last_timestamp))
        || typeof data.build_id !== "string") {
      throw new Error("A consulta retornou dados incompletos. Tente novamente.");
    }
    return data;
  }

  function render(data) {
    const before = data.direction === "backward";
    $("result-query").textContent = data.ordered
      ? data.combination.join(" → ") + " · ordem exata"
      : data.combination.join(" · ") + " · qualquer ordem";
    $("result-direction").textContent = `${before ? "Atrás" : "À frente"} · até ${data.depth} giros ${before ? "antes" : "depois"}`;
    $("metric-occurrences").textContent = integer.format(data.occurrences);
    $("metric-events").textContent = integer.format(data.context_events);
    $("metric-depth").textContent = `Até ${data.depth} por ocorrência`;
    $("metric-complete").textContent = integer.format(data.complete_occurrences);
    $("no-evidence").hidden = data.has_evidence;
    const largestScore = Math.max(...data.ranking.map((row) => row.score));
    const cards = document.createDocumentFragment();
    data.ranking.forEach((row) => {
      const leading = data.has_evidence && row.position <= 3 && row.score > 0;
      const card = node("li", "rank-card" + (leading ? " is-leading" : ""));
      const top = node("div", "rank-top");
      const color = row.number === 0 ? " is-green" : redNumbers.has(row.number) ? " is-red" : "";
      const number = node("span", "roulette-number" + color, String(row.number));
      number.setAttribute("aria-label", `Número ${row.number}`);
      const position = node("span", "rank-position", `#${String(row.position).padStart(2, "0")}`);
      position.setAttribute("aria-label", `Posição ${row.position}`);
      top.append(number, position);
      const score = node("p", "rank-score", points.format(row.score));
      score.append(node("small", "", "pontos"));
      const bar = node("div", "rank-bar");
      bar.setAttribute("aria-hidden", "true");
      const fill = node("div", "rank-bar-fill");
      fill.style.width = `${largestScore > 0 ? row.score / largestScore * 100 : 0}%`;
      bar.append(fill);
      const hits = node("p", "rank-hits", `${integer.format(row.direct_hits)} ${row.direct_hits === 1 ? "ocorrência direta" : "ocorrências diretas"}`);
      card.append(top, score, bar, hits);
      cards.append(card);
    });
    $("ranking-list").replaceChildren(cards);
    $("source-records").textContent = integer.format(data.source.records);
    $("source-period").textContent = `${date.format(new Date(data.source.first_timestamp))} — ${date.format(new Date(data.source.last_timestamp))}`;
    $("source-build").textContent = data.build_id;
    $("empty-state").hidden = true;
    $("ranking-results").hidden = false;
    $("query-status").textContent = data.has_evidence
      ? `Consulta concluída. ${integer.format(data.occurrences)} ocorrências do trio e 37 números no ranking.`
      : "Consulta concluída. Não há evidência para a direção escolhida.";
    setState(data.has_evidence ? "Consulta concluída" : "Sem evidência", data.has_evidence ? "ready" : "");
  }

  async function consult(event) {
    if (event) event.preventDefault();
    resetValidation();
    const numbers = readNumbers();
    if (!numbers) return;
    if (activeController) activeController.abort();
    const currentId = ++requestId;
    const controller = new AbortController();
    activeController = controller;
    const query = {
      numbers,
      direction: form.elements.direction.value,
      ordered: form.elements.ordered.value === "true",
    };
    const params = new URLSearchParams({
      numbers: numbers.join(","), direction: query.direction, ordered: String(query.ordered),
      input_order: "latest_first", roulette_id: "pragmatic-auto-roulette",
    });
    let timedOut = false;
    const timer = window.setTimeout(() => { timedOut = true; controller.abort(); }, 10000);
    $("ranking-results").hidden = true;
    $("error-state").hidden = true;
    $("empty-state").hidden = true;
    $("query-status").textContent = "Consultando o contexto do trio no catálogo…";
    setState("Consultando");
    setBusy(true);
    try {
      const response = await fetch(`/api/triple-context-ranking?${params}`, {
        method: "GET", headers: { Accept: "application/json" }, signal: controller.signal,
      });
      if (!response.ok) {
        const messages = {
          404: "Nenhum catálogo foi publicado para esta roleta. Tente novamente mais tarde.",
          422: "Não foi possível validar a combinação. Use três números distintos de 0 a 36.",
          503: "O catálogo está temporariamente indisponível. Tente novamente em instantes.",
        };
        throw new Error(messages[response.status] || "Não foi possível consultar o catálogo. Tente novamente em instantes.");
      }
      const data = validateResponse(await response.json(), query);
      if (currentId !== requestId) return;
      render(data);
    } catch (error) {
      if (currentId !== requestId) return;
      $("error-message").textContent = timedOut
        ? "A consulta demorou mais que o esperado. Tente novamente."
        : error instanceof TypeError ? "Não foi possível conectar à API. Verifique sua conexão e tente novamente."
          : error instanceof SyntaxError ? "A API retornou uma resposta inválida. Tente novamente."
            : error.message;
      $("error-state").hidden = false;
      $("query-status").textContent = "";
      setState("Consulta indisponível", "error");
    } finally {
      window.clearTimeout(timer);
      if (currentId === requestId) {
        activeController = null;
        setBusy(false);
      }
    }
  }

  form.addEventListener("submit", consult);
  form.addEventListener("input", invalidateResults);
  $("retry-button").addEventListener("click", () => form.requestSubmit());
  updatePreview();
  // Open with a real catalog query for the example already visible in the fields.
  consult();
})();
