// Helpers compartilhados do app de sinais.

// ---- Auth (Clerk) ----
async function getToken() {
  if (!window.Clerk || !window.Clerk.session) return null;
  try { return await window.Clerk.session.getToken(); } catch (e) { return null; }
}

async function authedFetch(url, opts = {}) {
  const token = await getToken();
  const headers = Object.assign({ "Content-Type": "application/json" }, opts.headers || {});
  if (token) headers["Authorization"] = "Bearer " + token;
  return fetch(url, Object.assign({}, opts, { headers }));
}

// ---- Clerk readiness ----
window.__clerkCallbacks = [];
window.__clerkReady = false;

window.onClerkReady = function (cb) {
  if (window.__clerkDisabled) return;
  if (window.__clerkReady) cb(window.Clerk);
  else window.__clerkCallbacks.push(cb);
};

window.__onClerkLoaded = async function () {
  try {
    await window.Clerk.load();
    window.__clerkReady = true;
    mountUserButton();
    refreshCredits();
    window.__clerkCallbacks.forEach(function (cb) { cb(window.Clerk); });
  } catch (e) {
    console.error("Clerk load error", e);
  }
};

function mountUserButton() {
  const el = document.getElementById("user-button");
  if (el && window.Clerk && window.Clerk.user) {
    try { window.Clerk.mountUserButton(el); } catch (e) {}
  }
}

async function refreshCredits() {
  const badge = document.getElementById("credits-badge");
  if (!badge) return;
  try {
    const r = await authedFetch("/api/me");
    if (!r.ok) return;
    const d = await r.json();
    badge.textContent = d.available + " créditos · " + d.pending + " pendente";
    badge.classList.remove("hidden");
  } catch (e) {}
}

// ---- Números / cores ----
const RED_NUMBERS = new Set([1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36]);

function colorClass(n) {
  return n === 0 ? "green" : (RED_NUMBERS.has(n) ? "red" : "black");
}

function chip(n) {
  return '<span class="chip ' + colorClass(n) + '">' + n + "</span>";
}

function statusLabel(s) {
  if (s === "win") return "WIN";
  if (s === "lost") return "LOST";
  return "Aguardando";
}
