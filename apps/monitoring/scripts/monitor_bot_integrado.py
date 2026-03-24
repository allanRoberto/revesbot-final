"""
Monitor de Apostas Integrado com Bot Automático

Este arquivo estende o monitor_bot.py original, adicionando integração
com o bot de apostas automáticas (main.js) sem modificar a lógica de detecção.

Uso:
    python monitor_bot_integrado.py

Requisitos:
    - Bot automático rodando em http://localhost:3000
    - MongoDB configurado
    - requests instalado (pip install requests)
"""

import os
import json
import sys
import time
import threading
import itertools
from pathlib import Path
import requests
from datetime import datetime, timezone
from typing import List, Optional

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Importa tudo do monitor original
from apps.monitoring.scripts.monitor_bot import (
    # Funções de MongoDB
    conectar_mongo,
    obter_db,
    buscar_historico_mongo,
    listar_roletas,

    # Funções auxiliares
    is_terminal_valido,
    _load_processed_ids,
    _save_processed_id,

    # Constantes
    MAPA_3_NUMEROS,
    MAPA_5_NUMEROS,
    URLS_ROLETAS,
    URL_DEFAULT,
    POLL_INTERVAL,
    CAMINHO_APOSTAS,
    CAMINHO_PROCESSADOS,
    VALOR_FICHA_DEFAULT,
    USAR_MAPA_5,
    RODADAS_ANTES_FIM_BASE5,
    script_start_time,
)

# ========================= CONFIGURAÇÕES DO BOT AUTOMÁTICO ===================

BOT_API_URL = "http://localhost:3000/api/bet"
BOT_HEALTH_URL = "http://localhost:3000/health"

# Mapeamento de roleta_id para gameId (usado pelo bot)
ROLETA_TO_GAME_ID = {
    "pragmatic-brazilian-roulette": "450",
    "pragmatic-speed-roulette-1": "556",
    "pragmatic-speed-roulette-2": "557",
    "pragmatic-speed-auto-roulette": "481",
    "pragmatic-korean-roulette": "457",
    "pragmatic-auto-roulette": "373",
    "pragmatic-mega-roulette-brazilian": "6478",
    "pragmatic-mega-roulette": "550",
    "pragmatic-auto-mega-roulette": "543",
    "pragmatic-immersive-roulette-deluxe": "8261",
    "pragmatic-roulette-macao": "552",
    "pragmatic-roulette-1": "473",
}

# Configurações de aposta
GALES_DEFAULT = 3          # Número de tentativas (gales)
VALOR_APOSTA = 0.5         # Valor da ficha em reais
ENVIAR_PARA_BOT = True     # True = envia para bot, False = apenas salva arquivo

# ========================= FUNÇÕES DE INTEGRAÇÃO =============================

def verificar_bot_online() -> bool:
    """Verifica se o bot automático está online."""
    try:
        response = requests.get(BOT_HEALTH_URL, timeout=3)
        if response.status_code == 200:
            data = response.json()
            return data.get("status") == "ok"
    except Exception:
        pass
    return False


def enviar_aposta_para_bot(
    nome_roleta: str,
    numeros: List[int],
    valor: float = VALOR_APOSTA,
    gales: int = GALES_DEFAULT
) -> dict:
    """
    Envia a aposta para o bot automático.

    Args:
        nome_roleta: ID da roleta (ex: "pragmatic-brazilian-roulette")
        numeros: Lista de números para apostar
        valor: Valor da ficha
        gales: Número de tentativas

    Returns:
        dict com resultado da operação
    """
    game_id = ROLETA_TO_GAME_ID.get(nome_roleta)

    if not game_id:
        return {
            "success": False,
            "error": f"Roleta '{nome_roleta}' não mapeada para gameId"
        }

    roulette_url = f"https://lotogreen.bet.br/play/{game_id}"

    payload = {
        "bets": numeros,
        "roulette_url": roulette_url,
        "gales": gales,
        "valor": valor
    }

    try:
        response = requests.post(
            BOT_API_URL,
            json=payload,
            timeout=10
        )

        if response.status_code == 200:
            result = response.json()
            return {
                "success": True,
                "response": result,
                "payload": payload
            }
        else:
            return {
                "success": False,
                "error": f"HTTP {response.status_code}: {response.text}",
                "payload": payload
            }

    except requests.exceptions.ConnectionError:
        return {
            "success": False,
            "error": "Bot offline - não foi possível conectar",
            "payload": payload
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "payload": payload
        }


# ========================= LÓGICA PRINCIPAL (ESTENDIDA) ======================

def processar_apostas_integrado(nome_roleta: str, bruto: List[dict]):
    """
    Versão estendida do processar_apostas que também envia para o bot.
    A lógica de detecção é IDÊNTICA ao original.
    """
    n = len(bruto)
    processed_ids = _load_processed_ids()

    for i in range(n):
        # ── 1. Candidato BASE3 ──────────────────────────────────────────────
        base3_obj = bruto[i]
        if not isinstance(base3_obj, dict):
            continue
        base3_num = base3_obj.get("numero")
        if not is_terminal_valido(base3_num):
            continue

        # ── 2. BASE2 ─────────────────────────────────────────────────────────
        idx_base2 = i + (base3_num - 1)
        if idx_base2 >= n:
            continue
        base2_obj = bruto[idx_base2]
        base2_num = base2_obj.get("numero")
        if not is_terminal_valido(base2_num):
            continue

        # ── 3. BASE1 ─────────────────────────────────────────────────────────
        idx_base1 = idx_base2 + (base2_num - 1)
        if idx_base1 >= n:
            continue
        base1_obj = bruto[idx_base1]
        base1_num = base1_obj.get("numero")
        if not is_terminal_valido(base1_num):
            continue

        # ── 4. BASE4: primeira re-ocorrência de base3_num MAIS RECENTE que BASE3 ─
        idx_base4 = None
        for j in range(i - 1, -1, -1):
            if isinstance(bruto[j], dict) and bruto[j].get("numero") == base3_num:
                idx_base4 = j
                break
        if idx_base4 is None:
            continue

        base4_num = base3_num

        # ── 5. BASE5 ─────────────────────────────────────────────────────────
        idx_base5 = idx_base4 - (base4_num - 1)
        if idx_base5 < 0:
            continue
        base5_obj = bruto[idx_base5]
        base5_num = base5_obj.get("numero")
        if not is_terminal_valido(base5_num):
            continue

        # ── 6. Calcular índice do trigger ─────────────────────────────────────
        trigger_idx = idx_base5 - (base5_num - 1 - RODADAS_ANTES_FIM_BASE5)
        if trigger_idx < 0 or trigger_idx >= n:
            continue

        trigger_spin = bruto[trigger_idx]
        trigger_ts_str = trigger_spin.get("timestamp_local", "")

        try:
            trigger_ts = datetime.fromisoformat(trigger_ts_str)
        except Exception:
            continue

        if trigger_ts <= script_start_time:
            continue

        # ── 7. Verificar se já foi processado ─────────────────────────────────
        formacao_id = (
            f"APOSTAS_{base3_obj['chave']}_"
            f"{base2_obj['chave']}_"
            f"{base1_obj['chave']}"
        )
        if formacao_id in processed_ids:
            continue

        # ══════════════════ TRIGGER CONFIRMADO ═══════════════════════════════

        # ── Concordância BASE1/BASE2 ──────────────────────────────────────────
        base3_terminal = base3_num % 10
        mapa = MAPA_5_NUMEROS if USAR_MAPA_5 else MAPA_3_NUMEROS

        grupo1 = mapa.get(base1_num, [])
        grupo2 = mapa.get(base2_num, [])

        if not grupo1 or not grupo2:
            continue

        compartilhados = set(grupo1) & set(grupo2) - {0}
        if compartilhados:
            continue

        base5_rodadas = [
            bruto[idx_base5 - k].get("numero")
            for k in range(0, 5)
            if 0 <= idx_base5 - k < n
        ]
        grupo1_na_base5 = any(num in grupo1 and num != 0 for num in base5_rodadas if num is not None)
        grupo2_na_base5 = any(num in grupo2 and num != 0 for num in base5_rodadas if num is not None)

        if not grupo1_na_base5 and not grupo2_na_base5:
            continue
        if grupo1_na_base5 and grupo2_na_base5:
            continue

        if grupo1_na_base5:
            grupo_eliminado = 'grupo1'
            alvos_eliminados = grupo1
            numeros_apostar = grupo2
        else:
            grupo_eliminado = 'grupo2'
            alvos_eliminados = grupo2
            numeros_apostar = grupo1

        ultimos_3 = [entry.get("numero") for entry in bruto[:3] if isinstance(entry, dict)]
        ultimos_numeros_str = ", ".join(str(x) for x in ultimos_3)

        url_roleta = URLS_ROLETAS.get(nome_roleta, URL_DEFAULT)
        now_str = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        timestamp_arquivo = datetime.now().strftime("%Y%m%d_%H%M%S")

        # ── Montar JSON de aposta ─────────────────────────────────────────────
        apostas_json = {
            "id_mesa": nome_roleta,
            "url": url_roleta,
            "ultimos_numeros": ultimos_numeros_str,
            "numeros": numeros_apostar,
            "valor_ficha": VALOR_FICHA_DEFAULT,
            "concordancia": {
                "base1_num": base1_num,
                "grupo1": grupo1,
                "base2_num": base2_num,
                "grupo2": grupo2,
                "grupo_eliminado": grupo_eliminado,
                "alvos_eliminados": alvos_eliminados,
                "base5_rodadas": base5_rodadas,
                "alvos_finais": numeros_apostar,
            },
            "datahora_trigger": now_str,
            "rodadas_restantes_base5": RODADAS_ANTES_FIM_BASE5,
            "bases": {
                "BASE1": {
                    "numero": base1_num,
                    "terminal": base1_num % 10,
                    "chave": base1_obj.get("chave"),
                },
                "BASE2": {
                    "numero": base2_num,
                    "terminal": base2_num % 10,
                    "chave": base2_obj.get("chave"),
                },
                "BASE3": {
                    "numero": base3_num,
                    "terminal": base3_terminal,
                    "chave": base3_obj.get("chave"),
                },
                "BASE4": {
                    "numero": base4_num,
                    "terminal": base4_num % 10,
                    "chave": bruto[idx_base4].get("chave"),
                },
                "BASE5": {
                    "numero": base5_num,
                    "terminal": base5_num % 10,
                    "chave": base5_obj.get("chave"),
                },
            },
            "trigger_spin": {
                "numero": trigger_spin.get("numero"),
                "chave": trigger_spin.get("chave"),
                "timestamp": trigger_ts_str,
                "indice_bruto": trigger_idx,
            },
            "formacao_id": formacao_id,
        }

        # ── Salvar arquivo (comportamento original) ───────────────────────────
        os.makedirs(CAMINHO_APOSTAS, exist_ok=True)
        nome_arquivo = f"{nome_roleta}_aposta_{timestamp_arquivo}.json"
        caminho_saida = os.path.join(CAMINHO_APOSTAS, nome_arquivo)
        with open(caminho_saida, "w", encoding="utf-8") as f:
            json.dump(apostas_json, f, indent=4, ensure_ascii=False)

        _save_processed_id(formacao_id)

        # ══════════════════ INTEGRAÇÃO COM BOT ════════════════════════════════

        bot_result = None
        if ENVIAR_PARA_BOT:
            bot_result = enviar_aposta_para_bot(
                nome_roleta=nome_roleta,
                numeros=numeros_apostar,
                valor=VALOR_APOSTA,
                gales=GALES_DEFAULT
            )

        # ── Exibir resultado ──────────────────────────────────────────────────
        print("\r" + " " * 70 + "\r", end="")
        print(f"\n{'='*70}")
        print(f"  *** APOSTA DETECTADA {'E ENVIADA' if bot_result and bot_result.get('success') else ''} ***")
        print(f"  Roleta : {nome_roleta}")
        print(f"  Data   : {now_str}")
        print(f"{'='*70}")
        print(f"  BASE1  : {base1_num:>2}  |  terminal {base1_num % 10}  |  chave {base1_obj.get('chave')}")
        print(f"  BASE2  : {base2_num:>2}  |  terminal {base2_num % 10}  |  chave {base2_obj.get('chave')}")
        print(f"  BASE3  : {base3_num:>2}  |  terminal {base3_terminal}  |  chave {base3_obj.get('chave')}")
        print(f"  BASE4  : {base4_num:>2}  |  terminal {base4_num % 10}  |  chave {bruto[idx_base4].get('chave')}")
        print(f"  BASE5  : {base5_num:>2}  |  terminal {base5_num % 10}  |  chave {base5_obj.get('chave')}")
        print(f"{'─'*70}")
        print(f"  Trigger: número {trigger_spin.get('numero')}  |  índice bruto {trigger_idx}")
        print(f"  Faltam : {RODADAS_ANTES_FIM_BASE5} rodadas p/ fim da contagem_base5")
        print(f"{'─'*70}")
        print(f"  Concordância:")
        print(f"    BASE1 ({base1_num}) → grupo1 {grupo1}")
        print(f"    BASE2 ({base2_num}) → grupo2 {grupo2}")
        print(f"    Elim. BASE5 : {grupo_eliminado} {alvos_eliminados}")
        print(f"    BASE5+4     : {base5_rodadas}")
        print(f"{'─'*70}")
        print(f"  NÚMEROS PARA APOSTAR: {numeros_apostar}")
        print(f"  Últimos números     : {ultimos_numeros_str}")
        print(f"  Arquivo salvo       : {nome_arquivo}")
        print(f"{'─'*70}")

        # Status do envio para o bot
        if ENVIAR_PARA_BOT:
            if bot_result and bot_result.get("success"):
                print(f"  🤖 BOT: Aposta ENVIADA com sucesso!")
                print(f"     Números: {numeros_apostar}")
                print(f"     Valor: R${VALOR_APOSTA} | Gales: {GALES_DEFAULT}")
            else:
                error_msg = bot_result.get("error", "Erro desconhecido") if bot_result else "Bot desabilitado"
                print(f"  ⚠️  BOT: Falha ao enviar - {error_msg}")
                print(f"     Aposta salva em arquivo para envio manual")
        else:
            print(f"  ℹ️  BOT: Envio automático DESABILITADO")
            print(f"     Configure ENVIAR_PARA_BOT=True para ativar")

        print(f"{'='*70}\n")


# ========================= HEARTBEAT =========================================

def exibir_heartbeat():
    """Exibe indicador de atividade com status do bot."""
    indicador = itertools.cycle(["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"])
    bot_status = "?"
    last_check = 0

    while True:
        # Verifica status do bot a cada 10 segundos
        now = time.time()
        if now - last_check > 10:
            bot_status = "🟢" if verificar_bot_online() else "🔴"
            last_check = now

        print(f"\rMONITORANDO {next(indicador)} | Bot: {bot_status} | Envio: {'ON' if ENVIAR_PARA_BOT else 'OFF'}", end="", flush=True)
        time.sleep(0.15)


# ========================= LOOP DE POLLING ===================================

def loop_polling():
    """Loop principal de polling - usa a função integrada."""
    print(
        f"[{datetime.now().strftime('%H:%M:%S')}] "
        f"Loop de polling iniciado (intervalo: {POLL_INTERVAL}s)"
    )
    while True:
        try:
            roletas = listar_roletas()
            for nome_roleta in roletas:
                try:
                    bruto = buscar_historico_mongo(nome_roleta, limit=500)
                    if not bruto or len(bruto) < 50:
                        continue
                    # Usa a versão integrada
                    processar_apostas_integrado(nome_roleta, bruto)
                except Exception as e:
                    print(f"\n[ERRO] ao processar roleta '{nome_roleta}': {e}")
        except Exception as e:
            print(f"\n[ERRO] no loop principal: {e}")
            time.sleep(5)
            continue
        time.sleep(POLL_INTERVAL)


# ========================= PONTO DE ENTRADA ==================================

if __name__ == "__main__":
    os.makedirs(CAMINHO_APOSTAS, exist_ok=True)
    os.makedirs(CAMINHO_PROCESSADOS, exist_ok=True)

    print(f"\n{'='*70}")
    print(f"  MONITOR DE APOSTAS INTEGRADO")
    print(f"{'='*70}")

    print(f"[{datetime.now().strftime('%H:%M:%S')}] Conectando ao MongoDB...")
    conectar_mongo()
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Conexão estabelecida.")

    # Verificar status do bot
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Verificando bot automático...")
    if verificar_bot_online():
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ Bot online em {BOT_API_URL}")
    else:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️  Bot OFFLINE - apostas serão apenas salvas em arquivo")
        print(f"[{datetime.now().strftime('%H:%M:%S')}]    Inicie o bot com: cd src/bot-automatico && node main.js")

    thread_heartbeat = threading.Thread(target=exibir_heartbeat, daemon=True)
    thread_heartbeat.start()

    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Configurações:")
    print(f"    Disparo: {RODADAS_ANTES_FIM_BASE5} rodadas antes do fim")
    print(f"    Mapa: {'5 núm. (MAPA_5_NUMEROS)' if USAR_MAPA_5 else '3 núm. (MAPA_3_NUMEROS)'}")
    print(f"    Valor ficha: R${VALOR_APOSTA}")
    print(f"    Gales: {GALES_DEFAULT}")
    print(f"    Envio automático: {'ATIVADO' if ENVIAR_PARA_BOT else 'DESATIVADO'}")
    print(f"{'='*70}\n")

    try:
        loop_polling()
    except KeyboardInterrupt:
        print("\n[INFO] Encerrando o monitoramento...")

    print("[INFO] Monitor encerrado.")
