import os
import json
import sys
import time
import threading
import itertools
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from pymongo import MongoClient
from pymongo.errors import PyMongoError

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

sys.stdout.reconfigure(encoding="utf-8")

# ========================= MAPAS DE APOSTAS ==================================
MAPA_3_NUMEROS = {
    4:  [0, 19,  4, 21],  5:  [0, 10,  5, 24],
    7:  [0, 29,  7, 28],  8:  [0, 30,  8, 23],
    14: [0, 20, 14, 31],  15: [0, 32, 15, 19],
    17: [0, 25, 17, 34],  18: [0, 22, 18, 29],
    24: [0,  5, 24, 16],  25: [0,  2, 25, 17],
    27: [0,  6, 27, 13],  28: [0,  7, 28, 12],
    34: [0, 17, 34,  6],  35: [0, 12, 35,  3],
}

MAPA_5_NUMEROS = {
    4:  [0, 15, 19,  4, 21,  2],  5:  [0, 23, 10,  5, 24, 16],
    7:  [0, 18, 29,  7, 28, 12],  8:  [0, 11, 30,  8, 23, 10],
    14: [0,  1, 20, 14, 31,  9],  15: [0, 26, 32, 15, 19,  4],
    17: [0,  2, 25, 17, 34,  6],  18: [0,  9, 22, 18, 29,  7],
    24: [0, 10,  5, 24, 16, 33],  25: [0, 21,  2, 25, 17, 34],
    27: [0, 34,  6, 27, 13, 36],  28: [0, 29,  7, 28, 12, 35],
    34: [0, 25, 17, 34,  6, 27],  35: [0, 28, 12, 35,  3, 26],
}

# URLs das mesas (baseado em Link.txt)
URLS_ROLETAS = {
    "pragmatic-brazilian-roulette": (
        ""
    ),
    "pragmatic-mega-roulette": (
        ""
    ),
    "pragmatic-mega-roulette-3000": (
        ""
    ),
    "pragmatic-french-roulette": (
        ""
    ),
}
URL_DEFAULT = ""

# ========================= CONFIGURAÇÕES =====================================
MONGO_URI = ""
DB_NAME = ""
COLECAO_RESULTADOS = ""
POLL_INTERVAL = 3          # segundos entre cada ciclo de varredura

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CAMINHO_APOSTAS = os.path.join(BASE_DIR, "APOSTAS")
CAMINHO_PROCESSADOS = os.path.join(BASE_DIR, "Logs", "Processados_Apostas")
PROCESSED_IDS_FILE = os.path.join(CAMINHO_PROCESSADOS, "apostas_processed.json")

VALOR_FICHA_DEFAULT = 5    # valor padrão da ficha em reais
USAR_MAPA_5 = False        # False = MAPA_3_NUMEROS (4 números) | True = MAPA_5_NUMEROS (6 números)

# Quantas rodadas de contagem_base5 devem RESTAR para disparar a aposta
RODADAS_ANTES_FIM_BASE5 = 4

# Gap máximo tolerado (segundos) entre dois spins consecutivos dentro da formação.
# Momento em que o bot foi iniciado (timezone-aware)
script_start_time = datetime.now(tz=timezone.utc)

# ===================== Conexão MongoDB =======================================
_mongo_client = None
_db = None


def conectar_mongo():
    global _mongo_client, _db
    _mongo_client = MongoClient(
        MONGO_URI,
        serverSelectionTimeoutMS=10000,
        connectTimeoutMS=10000,
        socketTimeoutMS=20000,
        retryReads=True,
    )
    _db = _mongo_client[DB_NAME]
    return _db


def obter_db():
    global _db
    if _db is None:
        conectar_mongo()
    return _db


def buscar_historico_mongo(nome_roleta: str, limit: int = 500) -> List[dict]:
    """
    Retorna os resultados em ordem NEWEST-FIRST (índice 0 = spin mais recente).
    Mesmo formato do catalogador_reposicao.py.
    """
    try:
        db = obter_db()
        cursor = (
            db[COLECAO_RESULTADOS]
            .find({"roleta_id": nome_roleta})
            .sort("timestamp_epoch", -1)
            .limit(limit)
        )
        resultado = []
        for doc in cursor:
            epoch = doc.get("timestamp_epoch", 0)
            ts_local = (
                datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()
                if epoch else ""
            )
            resultado.append({
                "numero":           doc.get("numero"),
                "chave":            str(doc["_id"]),
                "timestamp_epoch":  epoch,
                "timestamp_local":  ts_local,
            })
        return resultado
    except PyMongoError as e:
        print(f"\n[ERRO Mongo] buscar_historico_mongo({nome_roleta}): {e}")
        return []


def listar_roletas() -> List[str]:
    try:
        db = obter_db()
        return db[COLECAO_RESULTADOS].distinct("roleta_id")
    except PyMongoError as e:
        print(f"\n[ERRO Mongo] listar_roletas: {e}")
        return []


# ===================== IDs processados =======================================
def _load_processed_ids() -> set:
    try:
        if os.path.exists(PROCESSED_IDS_FILE):
            with open(PROCESSED_IDS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return set(data)
    except Exception:
        pass
    return set()


def _save_processed_id(fid: str) -> None:
    try:
        ids = _load_processed_ids()
        if fid in ids:
            return
        ids.add(fid)
        os.makedirs(CAMINHO_PROCESSADOS, exist_ok=True)
        with open(PROCESSED_IDS_FILE, "w", encoding="utf-8") as f:
            json.dump(sorted(list(ids)), f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ===================== Funções auxiliares ====================================
def is_terminal_valido(num) -> bool:
    """Terminal válido: 4, 5, 7 ou 8."""
    return isinstance(num, int) and num % 10 in {4, 5, 7, 8}


# ===================== LÓGICA PRINCIPAL DE DETECÇÃO ==========================
def processar_apostas(nome_roleta: str, bruto: List[dict]):
    """
    Varre o bruto (newest-first) em busca de formações onde o spin atual
    é exatamente o momento de trigger (restam RODADAS_ANTES_FIM_BASE5
    rodadas na fase contagem_base5).

    Estrutura do bruto (newest-first):
      bruto[0..4]          extras (mais recentes)
      bruto[5..idx_base5-1] contagem_base5
      bruto[idx_base5]     BASE5
      bruto[idx_base5+1..idx_base4-1] contagem_base4
      bruto[idx_base4]     BASE4
      ...
      bruto[idx_base3]     BASE3
      ...
      bruto[idx_base2]     BASE2
      ...
      bruto[idx_base1]     BASE1
      bruto[idx_base1+1..] pre_base1 / mais antigos

    Fórmula do trigger_idx:
      trigger_idx = idx_base5 - (base5_num - 1 - RODADAS_ANTES_FIM_BASE5)

    Exemplo de referência (JSON anexo)  — bruto newest-first (índice 0 = mais recente):
      extras[0..4] → contagem_base5[5..17] → BASE5[18] → contagem_base4[19..40]
      → BASE4[41] → entre_base3_base4[42..151] → BASE3[152] → ... → BASE1[202]

      BASE3=24 em i=152; BASE4 buscado range(151,-1,-1) → encontrado em 41
      idx_base5 = 41 - (24-1) = 18  ✓
      trigger_idx = 18 - (14-1-4) = 18-9 = 9  (spin numero=1) ✓
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
        #   No bruto newest-first, "mais recente" = índice MENOR que i (em direção ao topo)
        idx_base4 = None
        for j in range(i - 1, -1, -1):
            if isinstance(bruto[j], dict) and bruto[j].get("numero") == base3_num:
                idx_base4 = j
                break
        if idx_base4 is None:
            continue

        base4_num = base3_num  # BASE4 repete o número de BASE3

        # ── 5. BASE5 ─────────────────────────────────────────────────────────
        #   BASE5 é mais recente que BASE4 → índice MENOR no bruto (topo)
        #   Exemplo: BASE4=24 em idx=41 → idx_base5 = 41-(24-1) = 18  ✓
        idx_base5 = idx_base4 - (base4_num - 1)
        if idx_base5 < 0:
            continue
        base5_obj = bruto[idx_base5]
        base5_num = base5_obj.get("numero")
        if not is_terminal_valido(base5_num):
            continue

        # ── 6. Calcular índice do trigger ─────────────────────────────────────
        #   contagem_base5 é mais recente que BASE5 → índices menores no bruto
        #   Exemplo: BASE5=14 em idx=18, RODADAS=4
        #     trigger_idx = 18 - (14-1-4) = 18-9 = 9  (spin n=1) ✓
        trigger_idx = idx_base5 - (base5_num - 1 - RODADAS_ANTES_FIM_BASE5)
        if trigger_idx < 0 or trigger_idx >= n:
            continue

        trigger_spin = bruto[trigger_idx]
        trigger_ts_str = trigger_spin.get("timestamp_local", "")

        try:
            trigger_ts = datetime.fromisoformat(trigger_ts_str)
        except Exception:
            continue

        # Só dispara para eventos que ocorreram APÓS o bot ser iniciado
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

        # ── Concordância BASE1/BASE2 (lógica do analise_completa.py) ──────────
        base3_terminal = base3_num % 10
        mapa = MAPA_5_NUMEROS if USAR_MAPA_5 else MAPA_3_NUMEROS

        grupo1 = mapa.get(base1_num, [])
        grupo2 = mapa.get(base2_num, [])

        if not grupo1 or not grupo2:
            continue  # BASE1 ou BASE2 sem grupo no mapa

        compartilhados = set(grupo1) & set(grupo2) - {0}
        if compartilhados:
            continue  # Grupos compartilham números — formação inválida

        # BASE5 + 4 posteriores (mais recentes = índice menor no bruto newest-first)
        base5_rodadas = [
            bruto[idx_base5 - k].get("numero")
            for k in range(0, 5)
            if 0 <= idx_base5 - k < n
        ]
        grupo1_na_base5 = any(num in grupo1 and num != 0 for num in base5_rodadas if num is not None)
        grupo2_na_base5 = any(num in grupo2 and num != 0 for num in base5_rodadas if num is not None)

        if not grupo1_na_base5 and not grupo2_na_base5:
            continue  # Nenhum grupo em BASE5 — formação inválida
        if grupo1_na_base5 and grupo2_na_base5:
            continue  # Ambos os grupos em BASE5 — formação inválida

        # Grupo eliminado em BASE5; o grupo restante é direto o alvo
        if grupo1_na_base5:
            grupo_eliminado  = 'grupo1'
            alvos_eliminados = grupo1
            numeros_apostar  = grupo2
        else:
            grupo_eliminado  = 'grupo2'
            alvos_eliminados = grupo2
            numeros_apostar  = grupo1

        # Últimos 3 números da roleta (mais recentes)
        ultimos_3 = [entry.get("numero") for entry in bruto[:3] if isinstance(entry, dict)]
        ultimos_numeros_str = ", ".join(str(x) for x in ultimos_3)

        # URL da mesa
        url_roleta = URLS_ROLETAS.get(nome_roleta, URL_DEFAULT)

        # Timestamp de criação do arquivo
        now_str = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        timestamp_arquivo = datetime.now().strftime("%Y%m%d_%H%M%S")

        # ── Montar JSON de aposta (baseado em EXEMPLO.json) ───────────────────
        apostas_json = {
            # Campos do EXEMPLO.json
            "id_mesa":        nome_roleta,
            "url":            url_roleta,
            "ultimos_numeros": ultimos_numeros_str,
            "numeros":        numeros_apostar,
            "valor_ficha":    VALOR_FICHA_DEFAULT,

            # Concordância BASE1/BASE2
            "concordancia": {
                "base1_num":         base1_num,
                "grupo1":            grupo1,
                "base2_num":         base2_num,
                "grupo2":            grupo2,
                "grupo_eliminado":   grupo_eliminado,
                "alvos_eliminados":  alvos_eliminados,
                "base5_rodadas":     base5_rodadas,
                "alvos_finais":      numeros_apostar,
            },

            # Campos extras para rastreabilidade
            "datahora_trigger":         now_str,
            "rodadas_restantes_base5":  RODADAS_ANTES_FIM_BASE5,
            "bases": {
                "BASE1": {
                    "numero":   base1_num,
                    "terminal": base1_num % 10,
                    "chave":    base1_obj.get("chave"),
                },
                "BASE2": {
                    "numero":   base2_num,
                    "terminal": base2_num % 10,
                    "chave":    base2_obj.get("chave"),
                },
                "BASE3": {
                    "numero":   base3_num,
                    "terminal": base3_terminal,
                    "chave":    base3_obj.get("chave"),
                },
                "BASE4": {
                    "numero":   base4_num,
                    "terminal": base4_num % 10,
                    "chave":    bruto[idx_base4].get("chave"),
                },
                "BASE5": {
                    "numero":   base5_num,
                    "terminal": base5_num % 10,
                    "chave":    base5_obj.get("chave"),
                },
            },
            "trigger_spin": {
                "numero":     trigger_spin.get("numero"),
                "chave":      trigger_spin.get("chave"),
                "timestamp":  trigger_ts_str,
                "indice_bruto": trigger_idx,
            },
            "formacao_id": formacao_id,
        }

        # ── Salvar arquivo ────────────────────────────────────────────────────
        os.makedirs(CAMINHO_APOSTAS, exist_ok=True)
        nome_arquivo = f"{nome_roleta}_aposta_{timestamp_arquivo}.json"
        caminho_saida = os.path.join(CAMINHO_APOSTAS, nome_arquivo)
        with open(caminho_saida, "w", encoding="utf-8") as f:
            json.dump(apostas_json, f, indent=4, ensure_ascii=False)

        _save_processed_id(formacao_id)

        print("\r" + " " * 70 + "\r", end="")
        print(f"\n{'='*60}")
        print(f"  *** APOSTA CRIADA ***")
        print(f"  Roleta : {nome_roleta}")
        print(f"  Data   : {now_str}")
        print(f"{'='*60}")
        print(f"  BASE1  : {base1_num:>2}  |  terminal {base1_num % 10}  |  chave {base1_obj.get('chave')}")
        print(f"  BASE2  : {base2_num:>2}  |  terminal {base2_num % 10}  |  chave {base2_obj.get('chave')}")
        print(f"  BASE3  : {base3_num:>2}  |  terminal {base3_terminal}  |  chave {base3_obj.get('chave')}")
        print(f"  BASE4  : {base4_num:>2}  |  terminal {base4_num % 10}  |  chave {bruto[idx_base4].get('chave')}")
        print(f"  BASE5  : {base5_num:>2}  |  terminal {base5_num % 10}  |  chave {base5_obj.get('chave')}")
        print(f"{'─'*60}")
        print(f"  Trigger: número {trigger_spin.get('numero')}  |  chave {trigger_spin.get('chave')}  |  índice bruto {trigger_idx}")
        print(f"  Faltam : {RODADAS_ANTES_FIM_BASE5} rodadas p/ fim da contagem_base5")
        print(f"{'─'*60}")
        print(f"  Concordância:")
        print(f"    BASE1 ({base1_num}) → grupo1 {grupo1}")
        print(f"    BASE2 ({base2_num}) → grupo2 {grupo2}")
        print(f"    Elim. BASE5 : {grupo_eliminado} {alvos_eliminados}")
        print(f"    BASE5+4     : {base5_rodadas}")
        print(f"    Alvos        : {numeros_apostar}")
        print(f"{'─'*60}")
        print(f"  Alvos finais      : {numeros_apostar}")
        print(f"  Últimos números   : {ultimos_numeros_str}")
        print(f"  Arquivo           : {nome_arquivo}")
        print(f"{'='*60}\n")


# ===================== HEARTBEAT =============================================
def exibir_heartbeat():
    indicador = itertools.cycle(["|", "/", "-", "\\"])
    while True:
        print(f"\rMONITORANDO APOSTAS {next(indicador)}", end="", flush=True)
        time.sleep(0.2)


# ===================== LOOP DE POLLING =======================================
def loop_polling():
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
                    processar_apostas(nome_roleta, bruto)
                except Exception as e:
                    print(f"\n[ERRO] ao processar roleta '{nome_roleta}': {e}")
        except Exception as e:
            print(f"\n[ERRO] no loop principal: {e}")
            time.sleep(5)
            continue
        time.sleep(POLL_INTERVAL)


# ===================== PONTO DE ENTRADA ======================================
if __name__ == "__main__":
    os.makedirs(CAMINHO_APOSTAS, exist_ok=True)
    os.makedirs(CAMINHO_PROCESSADOS, exist_ok=True)

    print(f"[{datetime.now().strftime('%H:%M:%S')}] Conectando ao MongoDB...")
    conectar_mongo()
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Conexão estabelecida.")

    thread_heartbeat = threading.Thread(target=exibir_heartbeat, daemon=True)
    thread_heartbeat.start()

    print(f"[{datetime.now().strftime('%H:%M:%S')}] Monitor de Apostas iniciado.")
    print(
        f"[{datetime.now().strftime('%H:%M:%S')}] "
        f"Disparo: {RODADAS_ANTES_FIM_BASE5} rodadas antes do fim da contagem_base5."
    )
    print(
        f"[{datetime.now().strftime('%H:%M:%S')}] "
        f"Mapa: {'5 núm. (MAPA_5_NUMEROS)' if USAR_MAPA_5 else '3 núm. (MAPA_3_NUMEROS)'} "
        f"| Ficha: R${VALOR_FICHA_DEFAULT}\n"
    )

    try:
        loop_polling()
    except KeyboardInterrupt:
        print("\n[INFO] Encerrando o monitoramento de apostas...")

    print("[INFO] Monitor encerrado.")
