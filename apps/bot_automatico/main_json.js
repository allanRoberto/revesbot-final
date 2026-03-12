// main.js
require("dotenv").config();
const express = require("express");
const axios = require("axios");
const WebSocket = require("ws");
const puppeteer = require("puppeteer");
const fs = require("fs");

// =========================
// CONFIG
// =========================

const AUTH_BASE_URL = process.env.AUTH_BASE_URL || "https://auth.revesbot.com.br";
const AUTH_EMAIL = process.env.AUTH_EMAIL;
const AUTH_PASSWORD = process.env.AUTH_PASSWORD;
const API_PORT = process.env.API_PORT || 3000;
const DEBUG_MODE = process.env.DEBUG_MODE === "true";

const BET_SEQUENCE = [0.5, 0.5, 1.0];

// =========================
// UTIL PARSE
// =========================

function detectMessageFormat(text) {
  const t = text.trim();
  if (t.startsWith("{")) return "json";
  if (t.startsWith("<")) return "xml";
  return "unknown";
}

function safeJSONParse(text) {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

function parseWinningNumber(data) {
  const text = data.toString();
  const type = detectMessageFormat(text);

  if (type === "xml") {
    const m = text.match(/gameresult[^>]*score="(\d+)"/);
    return m ? Number(m[1]) : null;
  }

  if (type === "json") {
    const obj = safeJSONParse(text);
    return obj?.gameResult?.score ?? null;
  }

  return null;
}

// =========================
// LOGIN
// =========================

async function loginAndGetToken() {
  const { data, headers } = await axios.post(
    `${AUTH_BASE_URL}/api/auth/login`,
    { email: AUTH_EMAIL, password: AUTH_PASSWORD }
  );

  const cookie = headers["set-cookie"]?.find(c =>
    c.startsWith("bookmaker_token=")
  );

  if (!cookie) {
    throw new Error("Token não encontrado");
  }

  return cookie.split(";")[0].split("=")[1];
}

// =========================
// WS CAPTURE (CORRIGIDO)
// =========================

async function getWebSocketUrlWithPuppeteer(gameLink) {
  const browser = await puppeteer.launch({
    headless: true,
    args: ["--no-sandbox"]
  });

  try {
    const page = await browser.newPage();
    await page.setUserAgent(
      "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    );

    await page.evaluateOnNewDocument(() => {
      const WS = window.WebSocket;
      window.__wsUrls = [];
      window.WebSocket = function (url, ...args) {
        window.__wsUrls.push(url);
        return new WS(url, ...args);
      };
    });

    await page.goto(gameLink, { waitUntil: "domcontentloaded" });

    const start = Date.now();
    let wsUrl;

    while (Date.now() - start < 20000) {
      const urls = await page.evaluate(() => window.__wsUrls || []);
      wsUrl = urls.find(u => u.startsWith("wss://") && u.includes("game"));
      if (wsUrl) break;
      await new Promise(r => setTimeout(r, 300));
    }

    if (!wsUrl) {
      throw new Error("WebSocket não capturado via Puppeteer");
    }

    return wsUrl;
  } finally {
    await browser.close();
  }
}

async function getGameWebSocketUrl(gameId, token) {
  const { data } = await axios.get(
    `${AUTH_BASE_URL}/api/start-game/${gameId}`,
    { headers: { Cookie: `bookmaker_token=${token}` } }
  );

  if (!data?.link) {
    throw new Error("Link do jogo inválido");
  }

  return await getWebSocketUrlWithPuppeteer(data.link);
}

// =========================
// TABLE MANAGER
// =========================

class TableManager {
  constructor(gameId, name, authToken) {
    this.gameId = gameId;
    this.name = name;
    this.authToken = authToken;

    this.wsUrl = null;
    this.ws = null;
    this.gameInfo = { game: null, table: null };
  }

  async initialize() {
    this.wsUrl = await getGameWebSocketUrl(this.gameId, this.authToken);

    if (!this.wsUrl || !this.wsUrl.startsWith("wss://")) {
      throw new Error(`WebSocket URL inválida: ${this.wsUrl}`);
    }

    await this.connect();
  }

  async connect() {
    this.ws = new WebSocket(this.wsUrl);

    this.ws.on("message", data => {
      const text = data.toString();
      const type = detectMessageFormat(text);

      if (type === "xml") {
        const game = text.match(/<game id="([^"]+)"/)?.[1];
        const table = text.match(/tableId="([^"]+)"/)?.[1];
        if (game) this.gameInfo.game = game;
        if (table) this.gameInfo.table = table;
      }

      if (type === "json") {
        const obj = safeJSONParse(text);
        if (obj?.game?.id) this.gameInfo.game = obj.game.id;
        if (obj?.table?.id) this.gameInfo.table = obj.table.id;
      }
    });

    this.ws.on("open", () => {
      console.log(`✅ ${this.name} conectada`);
    });

    this.ws.on("error", err => {
      console.error(`❌ WS erro ${this.name}`, err.message);
    });
  }
}

// =========================
// START
// =========================

(async () => {
  const token = await loginAndGetToken();

  const config = JSON.parse(fs.readFileSync("./tables-config.json", "utf8"));
  for (const t of config.tables.filter(t => t.enabled)) {
    const manager = new TableManager(String(t.gameId), t.name, token);
    await manager.initialize();
  }

  console.log("🚀 Sistema iniciado");
})();