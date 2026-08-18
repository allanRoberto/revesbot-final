export class ResultsSocket {
  constructor({ slug, onResult, onStatus }) {
    this.slug = slug;
    this.onResult = onResult;
    this.onStatus = onStatus;
    this.socket = null;
    this.timer = null;
    this.attempt = 0;
    this.enabled = true;
  }

  connect() {
    if (!this.enabled) return;
    this.disconnect(false);
    this.onStatus("connecting");
    const protocol = location.protocol === "https:" ? "wss:" : "ws:";
    this.socket = new WebSocket(`${protocol}//${location.host}/ws?slug=${encodeURIComponent(this.slug)}`);
    this.socket.addEventListener("open", () => { this.attempt = 0; this.onStatus("online"); });
    this.socket.addEventListener("message", (event) => {
      try { this.onResult(JSON.parse(event.data)); } catch (_) { /* ignora eventos inválidos */ }
    });
    this.socket.addEventListener("close", () => { this.onStatus("offline"); this.reconnect(); });
    this.socket.addEventListener("error", () => this.socket?.close());
  }

  reconnect() {
    if (!this.enabled || this.timer) return;
    const wait = Math.min(30000, 1000 * (2 ** this.attempt++));
    this.timer = window.setTimeout(() => { this.timer = null; this.connect(); }, wait);
  }

  disconnect(disable = true) {
    if (disable) this.enabled = false;
    if (this.timer) window.clearTimeout(this.timer);
    this.timer = null;
    if (this.socket) {
      this.socket.onclose = null;
      this.socket.close();
      this.socket = null;
    }
  }

  resume() { this.enabled = true; this.connect(); }
}
