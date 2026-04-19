"""
DASHBOARD ALVOS SUBTRAÇÃO (MODO API)
=========================
Painel Streamlit ao vivo para o apostas_subtracao_api.py.
"""

import os
import json
import glob
import time
import atexit
import signal
import subprocess
import sys
import threading
from datetime import datetime

import streamlit as st
import plotly.graph_objects as go
from streamlit_autorefresh import st_autorefresh

# ========================= CAMINHOS ==========================================
BASE_DIR        = os.path.dirname(os.path.abspath(__file__))
STATE_FILE      = os.path.join(BASE_DIR, "Logs", "subtracao_api_estado.json")
RESULTS_DIR     = os.path.join(BASE_DIR, "Logs", "Resultados_Sub_Api")
CONFIG_FILE     = os.path.join(BASE_DIR, "Logs", "subtracao_api_config.json")
PID_FILE        = os.path.join(BASE_DIR, "Logs", "subtracao_api_pid.txt")
STDERR_LOG      = os.path.join(BASE_DIR, "Logs", "subtracao_api_stderr.log")
SCRIPT_APOSTAS  = os.path.join(BASE_DIR, "apostas_subtracao_api.py")

REFRESH_SEC     = 4

# ========================= DEFAULTS DE CONFIG ================================
_CONFIG_DEFAULTS = {
    "banca_inicial": 2500.0,
    "ficha_e1": 1.0,
    "ficha_e2": 1.0,
    "ficha_e3": 1.5,
    "ficha_e4": 2.5,
    "payout_bruto": 36.0,
    "poll_interval": 3,
    "stop_loss_pct": 20.0,
    "take_profit_pct": 20.0,
    "max_simultaneas": 4,
}

def carregar_config() -> dict:
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        cfg = {**_CONFIG_DEFAULTS, **data}
    except Exception:
        cfg = dict(_CONFIG_DEFAULTS)
    return cfg


def salvar_config(cfg: dict) -> None:
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


# ========================= CONTROLE DO PROCESSO ==============================
def _ler_pid() -> int | None:
    try:
        with open(PID_FILE, "r") as f:
            return int(f.read().strip())
    except Exception:
        return None

def _salvar_pid(pid: int) -> None:
    os.makedirs(os.path.dirname(PID_FILE), exist_ok=True)
    with open(PID_FILE, "w") as f:
        f.write(str(pid))

def _remover_pid() -> None:
    try:
        os.remove(PID_FILE)
    except FileNotFoundError:
        pass

def processo_ativo() -> bool:
    pid = _ler_pid()
    if pid is None: return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        _remover_pid()
        return False

def iniciar_script() -> str:
    if processo_ativo(): return "⚠️ Já está rodando."
    try:
        os.makedirs(os.path.dirname(STDERR_LOG), exist_ok=True)
        log_f = open(STDERR_LOG, "w", encoding="utf-8", buffering=1)
        proc = subprocess.Popen(
            [sys.executable, "-u", SCRIPT_APOSTAS],
            stdout=log_f, stderr=log_f, cwd=BASE_DIR,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        _salvar_pid(proc.pid)
        time.sleep(2.0)
        if proc.poll() is not None:
            log_f.flush()
            _remover_pid()
            try:
                with open(STDERR_LOG, "r", encoding="utf-8") as lf: tail = lf.read()[-1500:]
            except: tail = ""
            return f"❌ Erro inciando:\n\n{tail}"
        return f"✅ Iniciado (PID {proc.pid})"
    except Exception as e:
        return f"❌ Erro ao iniciar: {e}"

def parar_script() -> str:
    pid = _ler_pid()
    if pid is None: return "⚠️ Nenhum processo registrado."
    try:
        if sys.platform == "win32":
            subprocess.call(["taskkill", "/F", "/T", "/PID", str(pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            os.kill(pid, signal.SIGTERM)
        _remover_pid()
        return f"🛑 Processo {pid} encerrado."
    except Exception as e:
        _remover_pid()
        return f"⚠️ Processo encerrado: {e}"

def _encerrar_bot_no_exit():
    try:
        if processo_ativo(): parar_script()
    except: pass

def _signal_shutdown_handler(sig, frame):
    _encerrar_bot_no_exit()
    raise SystemExit(0)

if os.environ.get("SUBTR_API_DASH_EXIT_HOOKS") != "1":
    os.environ["SUBTR_API_DASH_EXIT_HOOKS"] = "1"
    atexit.register(_encerrar_bot_no_exit)
    try:
        if threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGINT, _signal_shutdown_handler)
            if hasattr(signal, "SIGTERM"): signal.signal(signal.SIGTERM, _signal_shutdown_handler)
    except: pass


# ========================= CARREGAMENTO DE DADOS =============================
@st.cache_data(ttl=REFRESH_SEC)
def carregar_estado() -> dict:
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

@st.cache_data(ttl=REFRESH_SEC)
def carregar_historico() -> list[dict]:
    arquivos = sorted(glob.glob(os.path.join(RESULTS_DIR, "*.json")), key=os.path.getmtime)
    rows = []
    for arq in arquivos:
        try:
            with open(arq, "r", encoding="utf-8") as f:
                rows.append(json.load(f))
        except: pass
    return rows


# ========================= RANKING POR ROLETA ================================
def calcular_ranking(historico: list[dict]) -> list[dict]:
    dados: dict[str, dict] = {}
    for res in historico:
        nome = res.get("roleta", "?").replace("pragmatic-", "")
        if nome not in dados:
            dados[nome] = {"green": 0, "red": 0, "anulado": 0, "variacao": 0.0}
        r = res.get("resultado", "")
        if r == "GREEN":
            dados[nome]["green"] += 1
            dados[nome]["variacao"] += res.get("variacao", 0) or 0
        elif r == "RED":
            dados[nome]["red"] += 1
            dados[nome]["variacao"] += res.get("variacao", 0) or 0
        elif r == "ANULAR":
            dados[nome]["anulado"] += 1

    linhas = []
    for nome, d in dados.items():
        total_gr  = d["green"] + d["red"]
        pct_green = d["green"] / total_gr * 100 if total_gr > 0 else 0.0
        linhas.append({
            "roleta":   nome,
            "green":    d["green"],
            "red":      d["red"],
            "anulado":  d["anulado"],
            "total":    total_gr,
            "pct":      pct_green,
            "variacao": d["variacao"],
        })

    return sorted(linhas, key=lambda x: (x["pct"], x["green"]), reverse=True)


# ========================= CSS ===============================================
CSS = """
<style>
.card {
    border-radius: 10px;
    padding: 14px 18px;
    margin-bottom: 10px;
    font-family: 'Courier New', monospace;
    font-size: 13px;
    line-height: 1.6;
    box-shadow: 0 1px 4px rgba(0,0,0,0.10);
}
.card-aposta   { background: #fff8e1; border-left: 4px solid #f9a825; }
.card-pausa    { background: #ffe0b2; border-left: 4px solid #f57c00; }
.card-green    { background: #e8f5e9; border-left: 4px solid #27ae60; }
.card-red      { background: #fdecea; border-left: 4px solid #e53935; }
.card-anulado  { background: #f5f5f5; border-left: 4px solid #9e9e9e; }

.badge-aposta  { color: #f9a825; font-weight: bold; font-size: 14px; }
.badge-pausa   { color: #f57c00; font-weight: bold; font-size: 14px; }
.badge-green   { color: #27ae60; font-weight: bold; font-size: 14px; }
.badge-red     { color: #e53935; font-weight: bold; font-size: 14px; }
.badge-anulado { color: #757575; font-weight: bold; font-size: 14px; }

.bases-row { color: #555577; font-size: 12px; margin-top: 4px; }
.grupo-tag { color: #333366; font-weight: bold; }
.roleta-tag{ color: #1565c0; font-size: 11px; font-weight: bold; }
.hora-tag  { color: #999; font-size: 11px; }

.num-alvo  { background: #c8f0d8; color: #1b5e20; border-radius: 3px; padding: 1px 5px; margin: 0 2px; font-weight: bold; }
.num-normal{ padding: 1px 5px; margin: 0 2px; color: #333; }
.num-gat   { background: #e3f2fd; color: #0d47a1; border-radius: 3px; padding: 1px 5px; margin: 0 2px; font-weight: bold; }

.metric-block { text-align: center; padding: 12px 6px; border-radius: 10px; background: #f0f4ff; border: 1px solid #dce3f5; box-shadow: 0 1px 3px rgba(0,0,0,0.07); }
.metric-val  { font-size: 28px; font-weight: bold; }
.metric-label{ font-size: 11px; color: #666; margin-top: 2px; }
</style>
"""


# ========================= COMPONENTES =======================================
def fmt_grupo(nums: list) -> str:
    partes = []
    for n in nums:
        if n == 0: partes.append(f'<span class="num-normal">0</span>')
        else: partes.append(f'<span class="num-alvo">{n}</span>')
    return " ".join(partes)

def render_operacao(op: dict) -> str:
    roleta = op.get("roleta", "?").replace("pragmatic-", "")
    pausa = op.get("pausa_restante", 0)
    gatilho = op.get("gatilho", "?")
    n_prev = op.get("n_prev", "?")
    alvos = op.get("alvos", [])
    grupo = op.get("grupo", "?")
    alvo_sub = op.get("alvo_sub", "?")
    
    # State badge
    if pausa > 0:
        cls_card = "card-pausa"
        badge = f'<span class="badge-pausa">⏸ PAUSA DE ESCADA/REPETIÇÃO ({pausa} rodadas)</span>'
    else:
        cls_card = "card-aposta"
        badge = f'<span class="badge-aposta">🟡 APOSTANDO (E{op.get("entradas_feitas", 0)+1}/4)</span>'
        
    return f"""
<div class="card {cls_card}">
  {badge}
  <div class="roleta-tag">{roleta}</div>
  <div class="bases-row">
    Gatilho: <span class="num-gat">{gatilho}</span> &nbsp; Num. Anterior: <b>{n_prev}</b>
  </div>
  <div style="margin-top:8px">
    <span class="grupo-tag">Subtração Alvo:</span> <b>{alvo_sub}</b> ({grupo})
  </div>
  <div><span class="grupo-tag">Alvos Apostados:</span> {fmt_grupo(alvos)}</div>
</div>
"""

def card_resultado(res: dict) -> str:
    resultado = res.get("resultado", "?")
    roleta = res.get("roleta", "?").replace("pragmatic-", "")
    hora = res.get("datahora", "?").replace("T", " ")[:19]
    gatilho = res.get("gatilho", "?")
    n_prev = res.get("n_anterior", "?")
    alvo_sub = res.get("alvo_sub", "?")
    
    if resultado == "ANULAR":
        return f"""<div class="card card-anulado"><span class="badge-anulado">■ ANULADO</span> &nbsp; <span class="hora-tag">{hora}</span><div class="roleta-tag">{roleta}</div></div>"""

    cor = "card-green" if resultado == "GREEN" else "card-red"
    badge = f'<span class="badge-green">✔ GREEN</span>' if resultado == "GREEN" else f'<span class="badge-red">✘ RED</span>'

    entrada = res.get("entrada_green")
    variacao = res.get("variacao", 0)
    banca = res.get("banca_atual", "?")

    ent_str = f"E{entrada}" if entrada else "—"
    var_str = f"+R$ {variacao:.2f}" if variacao >= 0 else f"-R$ {abs(variacao):.2f}"
    banca_str = f"R$ {banca:.2f}" if isinstance(banca, float) else "?"
    
    hist_pausas = res.get("historico_pausas", [])
    pausas_str = " | ".join(hist_pausas)
    
    hist_resultados = res.get("historico_resultados", [])
    if hist_resultados:
        nums_fmt = []
        if resultado == "GREEN":
            for n in hist_resultados[:-1]: nums_fmt.append(f"<span style='color:#555'>{n}</span>")
            nums_fmt.append(f"<span style='background:#d4edda; color:#155724; padding:0 4px; border-radius:3px; font-weight:bold;'>{hist_resultados[-1]}</span>")
        else:
            for n in hist_resultados: nums_fmt.append(f"<span style='color:#c0392b'>{n}</span>")
        numeros_str = " ➔ ".join(nums_fmt)
    else:
        numeros_str = "—"
    
    return f"""
<div class="card {cor}">
  {badge} &nbsp; <span class="hora-tag">{hora}</span>
  &nbsp; <b>{ent_str}</b> &nbsp; <b>{var_str}</b> &nbsp; <span class="grupo-tag">{banca_str}</span>
  <div class="roleta-tag">{roleta}</div>
  <div class="bases-row">Gatilho: <span class="num-gat">{gatilho}</span> &nbsp; Ant: <b>{n_prev}</b> &nbsp; Alvo Subtração: <b>{alvo_sub}</b></div>
  <div class="bases-row">Números sorteados durante as rodadas: {numeros_str}</div>
  <div style="font-size:11px; color:#888; font-style:italic">Eventos de Pausa: {pausas_str if pausas_str else "Nenhum"}</div>
</div>
"""


# ========================= LAYOUT PRINCIPAL ==================================
st.set_page_config(page_title="Subtração API — Painel", page_icon="🎯", layout="wide", initial_sidebar_state="expanded")
st.markdown(CSS, unsafe_allow_html=True)
st_autorefresh(interval=REFRESH_SEC * 1000, key="autorefresh")
carregar_estado.clear()
carregar_historico.clear()

cfg = carregar_config()

with st.sidebar:
    st.markdown("## ⚙️ Configurações (Modo API)")
    st.markdown("---")

    st.markdown("**🤖 Controle do Bot Async API**")
    ativo = processo_ativo()
    pid   = _ler_pid() if ativo else None
    status_cor   = "#2ecc71" if ativo else "#e74c3c"
    status_texto = f"🟢 RODANDO  (PID {pid})" if ativo else "🔴 PARADO"
    st.markdown(f"<div style='font-size:16px;font-weight:bold;color:{status_cor};padding:6px 10px;background:#f8f8f8;border-radius:6px;border:1px solid {status_cor};margin-bottom:8px'>{status_texto}</div>", unsafe_allow_html=True)
    col_on, col_off = st.columns(2)
    with col_on:
        if st.button("▶ INICIAR", use_container_width=True, type="primary", disabled=ativo):
            with st.spinner("Iniciando API..."): msg = iniciar_script()
            if msg.startswith("✅"): st.success(msg)
            else: st.error(msg)
            time.sleep(1.5)
            st.rerun()
    with col_off:
        if st.button("⏹ PARAR", use_container_width=True, disabled=not ativo):
            msg = parar_script()
            st.toast(msg)
            time.sleep(0.8)
            st.rerun()

    if os.path.exists(STDERR_LOG):
        with st.expander("📄 Log do script", expanded=False):
            try:
                with open(STDERR_LOG, "r", encoding="utf-8") as lf: st.code(lf.read()[-3000:] or "(vazio)", language="")  
            except Exception as ex: st.write(f"Erro: {ex}")
            if st.button("🗑 Limpar log", use_container_width=True):
                open(STDERR_LOG, "w").close()
                st.rerun()

    st.markdown("---")
    st.markdown("**🧹 Banco de Dados**")
    if st.button("🗑 Apagar Histórico", help="Limpa a banca e exclui todas as operações gravadas. O robô deve estar parado.", disabled=ativo, use_container_width=True):
        if os.path.exists(STATE_FILE):
            try: os.remove(STATE_FILE)
            except: pass
        for f in glob.glob(os.path.join(RESULTS_DIR, "*.json")):
            try: os.remove(f)
            except: pass
        carregar_estado.clear()
        carregar_historico.clear()
        st.success("Banco de dados apagado!")
        time.sleep(1)
        st.rerun()

    st.markdown("---")
    st.markdown("**💰 Fichas por Entrada (R$)**")
    
    sb_f1 = st.number_input("1ª Entrada", min_value=0.50, step=0.50, format="%.2f", value=float(cfg["ficha_e1"]))
    sb_f2 = st.number_input("2ª Entrada", min_value=0.50, step=0.50, format="%.2f", value=float(cfg["ficha_e2"]))
    sb_f3 = st.number_input("3ª Entrada", min_value=0.50, step=0.50, format="%.2f", value=float(cfg["ficha_e3"]))
    sb_f4 = st.number_input("4ª Entrada", min_value=0.50, step=0.50, format="%.2f", value=float(cfg["ficha_e4"]))
    sb_banca = st.number_input("Banca Inicial", min_value=0.0, step=100.0, format="%.2f", value=float(cfg["banca_inicial"]))
    sb_payout= st.number_input("Payout Bruto Pleno", min_value=0.0, step=1.0, format="%.2f", value=float(cfg["payout_bruto"]))

    st.markdown("---")
    st.markdown("**🛑 Limites e Geral**")
    sb_sl_pct = st.number_input("Stop Loss %", min_value=1.0, step=1.0, format="%.1f", value=float(cfg["stop_loss_pct"]))
    sb_tp_pct = st.number_input("Take Profit %", min_value=1.0, step=1.0, format="%.1f", value=float(cfg["take_profit_pct"]))
    sb_max_sim = st.number_input("Máx. Simultâneas", min_value=1, step=1, value=int(cfg["max_simultaneas"]))

    st.markdown("---")
    col_s1, col_s2 = st.columns(2)
    with col_s1: aplicar = st.button("💾 Salvar", use_container_width=True, type="primary")
    with col_s2: resetar = st.button("↩ Reset", use_container_width=True)

    if aplicar:
        nova_cfg = {
            "banca_inicial": sb_banca, "ficha_e1": sb_f1, "ficha_e2": sb_f2, "ficha_e3": sb_f3, "ficha_e4": sb_f4,
            "payout_bruto": sb_payout, "poll_interval": cfg["poll_interval"],
            "stop_loss_pct": sb_sl_pct, "take_profit_pct": sb_tp_pct, "max_simultaneas": sb_max_sim,
        }
        salvar_config(nova_cfg)
        cfg = nova_cfg
        st.success("Salvo!")
        st.rerun()
    if resetar:
        salvar_config(dict(_CONFIG_DEFAULTS))
        st.success("Restaurado.")
        st.rerun()

BANCA_INICIAL = cfg["banca_inicial"]
estado = carregar_estado()
historico = carregar_historico()

placar = estado.get("placar", {})
g, r = placar.get("green", 0), placar.get("red", 0)
total = g + r
pct_g = g / total * 100 if total > 0 else 0.0
banca = estado.get("banca_atual", BANCA_INICIAL)
variacao_total = banca - BANCA_INICIAL
ativas = estado.get("operacoes_ativas", {})
atualizado = estado.get("atualizado_em", "—")
limite_motivo = estado.get("limite_atingido", "")

if limite_motivo and processo_ativo():
    parar_script()
    st.toast(f"🛑 Bot encerrado automaticamente: {limite_motivo}", icon="⛔")

col_title, col_clock = st.columns([5, 1])
with col_title: st.markdown("## 🎯 Script de Subtração (Modo API Async) — Ao Vivo")
with col_clock: st.markdown(f"<div style='text-align:right;color:#666;font-size:12px;margin-top:18px'>Atualizado<br><b>{atualizado[11:19] if len(atualizado) > 10 else atualizado}</b></div>", unsafe_allow_html=True)

st.markdown("---")

if limite_motivo:
    is_sl = "STOP LOSS" in limite_motivo.upper()
    cor_bg, cor_borda, cor_texto, icone = ("#fdecea", "#e53935", "#b71c1c", "⛔") if is_sl else ("#e8f5e9", "#27ae60", "#1b5e20", "🎯")
    st.markdown(f"<div style='background:{cor_bg};border-left:6px solid {cor_borda};padding:14px 18px;border-radius:8px;margin-bottom:10px;font-size:15px;font-weight:bold;color:{cor_texto}'>{icone} SCRIPT ENCERRADO — {limite_motivo}</div>", unsafe_allow_html=True)

c1, c2, c3, c4, c5 = st.columns(5)
def m(col, val, label, color): col.markdown(f'<div class="metric-block"><div class="metric-val" style="color:{color}">{val}</div><div class="metric-label">{label}</div></div>', unsafe_allow_html=True)
m(c1, g, "GREEN", "#2ecc71")
m(c2, r, "RED", "#e74c3c")
m(c3, f"{pct_g:.1f}%", "% GREEN", "#2ecc71" if pct_g >= 50 else "#e74c3c")
m(c4, len(ativas), "Operações Ativas", "#f0b429")
sinal_b = "+" if variacao_total >= 0 else ""
m(c5, f"R${banca:,.2f}", f"Banca ({sinal_b}R${variacao_total:,.2f})", "#2ecc71" if variacao_total >= 0 else "#e74c3c")

st.markdown("<br>", unsafe_allow_html=True)

col_at, col_hist = st.columns([1, 1])
with col_at:
    st.markdown('<div class="section-title">📡 Mesas Ativas (Pausa / Apostando)</div>', unsafe_allow_html=True)
    if not ativas: st.info("Nenhuma formação ativa no momento...")
    else:
        for roleta, op in ativas.items():
            st.markdown(render_operacao(op), unsafe_allow_html=True)

with col_hist:
    st.markdown('<div class="section-title">📜 Últimos Resultados</div>', unsafe_allow_html=True)
    limit = 10
    recentes = sorted(historico, key=lambda x: x.get("datahora", ""), reverse=True)[:limit]
    if not recentes: st.info("Nenhum resultado registrado.")
    else:
        for r in recentes: st.markdown(card_resultado(r), unsafe_allow_html=True)

st.markdown("---")
st.markdown('<div class="section-title">📉 Evolução de Banca (% Green por Roleta)</div>', unsafe_allow_html=True)

col_grafico, col_ranking = st.columns([2, 1])
with col_grafico:
    hist_ord = sorted(historico, key=lambda x: x.get("datahora", ""))
    saldo = BANCA_INICIAL
    x_vals, y_vals, hover = [0], [saldo], ["Início"]
    for i, res in enumerate(hist_ord):
        saldo += res.get("variacao", 0)
        x_vals.append(i + 1)
        y_vals.append(saldo)
        hover.append(f"{res.get('roleta', '?').replace('pragmatic-', '')} ({res.get('resultado')})")

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=x_vals, y=y_vals, mode='lines+markers', name='Banca', text=hover, hoverinfo='text+y', line=dict(color='#2196F3', width=3), marker=dict(size=6, color='#1976D2')))
    fig.add_hline(y=BANCA_INICIAL, line_dash="dash", line_color="gray", annotation_text="Banca Inicial")
    fig.update_layout(margin=dict(l=20, r=20, t=20, b=20), height=350, yaxis_title="R$", paper_bgcolor="white", plot_bgcolor="#f9fafb")
    st.plotly_chart(fig, use_container_width=True)

with col_ranking:
    rank = calcular_ranking(historico)
    if rank:
        st.dataframe(
            rank,
            column_config={
                "roleta": "Roleta",
                "green": "G",
                "red": "R",
                "pct": st.column_config.ProgressColumn("% Win", format="%.1f%%", min_value=0, max_value=100),
                "variacao": st.column_config.NumberColumn("Var (R$)", format="%.2f")
            },
            hide_index=True,
            use_container_width=True
        )
    else:
        st.info("Sem dados para ranking")
