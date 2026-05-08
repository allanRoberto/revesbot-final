"""
Valida a TESE DA PERSISTÊNCIA:
"Quando uma sugestão acerta nas primeiras posições, ela 'já pagou'.
A próxima sugestão pode estar 'atrasada' esperando números que não virão.
Números que persistem no topo entre sugestões consecutivas são candidatos
'atrasados' e raramente serão o próximo número sorteado."

Estratégia:
1. Encontra o snapshot exato do usuário (sug com top: 3, 17, 15, 36, 22, 6, 23, 0...)
2. Pega os 2 snapshots consecutivos
3. Identifica números persistentes
4. Roda análise sistemática em 1000+ pares
"""
from __future__ import annotations

import statistics
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter, defaultdict

import certifi
from pymongo import MongoClient, ASCENDING, DESCENDING

ROULETTE_ID = "pragmatic-auto-roulette"


def _read_dotenv() -> str | None:
    env_path = Path(".env")
    if not env_path.exists():
        return None
    for line in env_path.read_text().splitlines():
        if line.startswith("MONGO_URL="):
            return line.split("=", 1)[1].strip()
    return None


# Sugestões dadas pelo usuário
SUGESTAO_1 = [3, 17, 15, 36, 22, 6, 23, 0, 1, 5, 11, 34, 26, 33, 19, 16, 32, 7, 29, 28, 24, 10, 30, 25, 2, 13, 21, 20, 12, 18, 14, 31, 27, 35, 4, 9, 8]
SUGESTAO_2 = [36, 2, 6, 28, 10, 8, 22, 34, 33, 30, 14, 4, 18, 17, 27, 19, 3, 16, 21, 7, 11, 35, 29, 24, 26, 15, 5, 31, 9, 1, 12, 20, 32, 23, 0, 25, 13]


def find_user_example(db) -> dict | None:
    """Procura o snapshot exato do usuário no banco"""
    print("Procurando snapshot do usuário no banco...")

    # Procura por anchor=0 (próximo veio o 12)
    cursor = db["suggestion_snapshots"].find(
        {"roulette_id": ROULETTE_ID, "anchor_number": 0}
    ).sort("created_at_utc", DESCENDING).limit(50)

    for snap in cursor:
        payload = snap.get("payload", {})
        ranking = payload.get("suggestion") or payload.get("list") or []
        if ranking == SUGESTAO_2:
            return snap

    return None


def analyze_pair(snap_n: dict, snap_n1: dict, ranking_n: list, ranking_n1: list, next_num: int):
    """Analisa um par consecutivo de sugestões"""
    top_n_size = 8

    top_n = set(ranking_n[:top_n_size])
    top_n1 = set(ranking_n1[:top_n_size])

    # Números que persistem no topo
    persistent = top_n & top_n1

    # next_num está em quais conjuntos?
    next_in_persistent = next_num in persistent
    next_in_top_n1 = next_num in top_n1

    # Posição do next em cada ranking
    pos_in_n1 = ranking_n1.index(next_num) + 1 if next_num in ranking_n1 else None

    return {
        "persistent_count": len(persistent),
        "persistent": sorted(persistent),
        "next_num": next_num,
        "next_in_persistent": next_in_persistent,
        "next_pos_in_n1": pos_in_n1,
    }


def main():
    url = _read_dotenv()
    client = MongoClient(url, tls=True, tlsCAFile=certifi.where())
    db = client["roleta_db"]

    print("="*80)
    print("VALIDAÇÃO DA TESE DA PERSISTÊNCIA")
    print("="*80 + "\n")

    # 1. Análise do exemplo concreto do usuário
    print("📍 PARTE 1: Exemplo concreto do usuário\n")

    top_n = 8
    top_sug1 = set(SUGESTAO_1[:top_n])
    top_sug2 = set(SUGESTAO_2[:top_n])
    persistent = sorted(top_sug1 & top_sug2)

    print(f"Top {top_n} da Sugestão 1 (anchor → 0): {sorted(top_sug1)}")
    print(f"Top {top_n} da Sugestão 2 (anchor 0 → ?): {sorted(top_sug2)}")
    print(f"\n🔁 Números PERSISTENTES no topo: {persistent}")
    print(f"   Total: {len(persistent)} números\n")

    # Onde está o 12 (next) na sugestão 2?
    pos_12 = SUGESTAO_2.index(12) + 1
    print(f"📌 Próximo número (12) está na posição {pos_12}/37 da Sugestão 2")
    print(f"   12 ∈ persistent? {12 in persistent}")
    print(f"   12 ∈ top {top_n}? {12 in top_sug2}\n")

    # Onde está o 0 (next anterior) na sugestão 1?
    pos_0 = SUGESTAO_1.index(0) + 1
    print(f"📌 Número anterior sorteado (0) estava na posição {pos_0}/37 da Sugestão 1\n")

    print("="*80)
    print("📊 PARTE 2: Validação sistemática em pares consecutivos\n")

    # Carrega snapshots ordenados cronologicamente
    print("Carregando snapshots e histórico...")
    all_snaps = list(
        db["suggestion_snapshots"]
        .find({"roulette_id": ROULETTE_ID})
        .sort("anchor_timestamp_utc", ASCENDING)
    )
    print(f"Total snapshots: {len(all_snaps)}")

    # Carrega histórico
    hist = list(
        db["history"]
        .find({"roulette_id": ROULETTE_ID})
        .sort("timestamp", ASCENDING)
    )
    ts_to_value = {h["timestamp"]: h["value"] for h in hist}
    sorted_ts = sorted(ts_to_value.keys())
    print(f"Total draws: {len(hist)}\n")

    # Para cada par consecutivo de snapshots, analisa
    pair_results = []
    persistent_was_next_count = 0
    persistent_total = 0

    print("Analisando pares consecutivos...")

    for i in range(len(all_snaps) - 1):
        if (i + 1) % 3000 == 0:
            print(f"  {i+1} pares processados...")

        snap_n = all_snaps[i]
        snap_n1 = all_snaps[i + 1]

        payload_n = snap_n.get("payload", {})
        payload_n1 = snap_n1.get("payload", {})

        ranking_n = payload_n.get("suggestion") or payload_n.get("list") or []
        ranking_n1 = payload_n1.get("suggestion") or payload_n1.get("list") or []

        if not ranking_n or not ranking_n1:
            continue

        # Encontra o próximo número (após snap_n1)
        anchor_n1_ts = snap_n1.get("anchor_timestamp_utc")
        if not anchor_n1_ts:
            continue

        # Busca next_ts > anchor_n1_ts
        idx_anchor = None
        for j, ts in enumerate(sorted_ts):
            if ts > anchor_n1_ts:
                idx_anchor = j
                break

        if idx_anchor is None:
            continue

        next_num = ts_to_value.get(sorted_ts[idx_anchor])
        if next_num is None:
            continue

        result = analyze_pair(snap_n, snap_n1, ranking_n, ranking_n1, int(next_num))
        pair_results.append(result)

        if result["next_in_persistent"]:
            persistent_was_next_count += 1
        persistent_total += 1

    print(f"\n✓ {len(pair_results)} pares analisados\n")

    # Estatísticas
    print("="*80)
    print("📈 RESULTADOS DA TESE\n")

    persistent_counts = [r["persistent_count"] for r in pair_results]
    avg_persistence = statistics.mean(persistent_counts)
    print(f"Persistência média (top {top_n}): {avg_persistence:.2f} números")
    print(f"  Min: {min(persistent_counts)}, Max: {max(persistent_counts)}")
    print(f"  Mediana: {statistics.median(persistent_counts):.0f}\n")

    pct_in_persistent = persistent_was_next_count / persistent_total * 100
    expected_pct = avg_persistence / 37 * 100  # Por chance aleatória

    print(f"🎯 Próximo número está nos PERSISTENTES?")
    print(f"   Casos: {persistent_was_next_count} / {persistent_total} ({pct_in_persistent:.2f}%)")
    print(f"   Esperado por chance: {expected_pct:.2f}%")
    print(f"   Diferença: {pct_in_persistent - expected_pct:+.2f}% vs aleatório\n")

    if pct_in_persistent < expected_pct - 1:
        print("✅ TESE VALIDADA: números persistentes são MENOS prováveis de sair!")
    elif pct_in_persistent > expected_pct + 1:
        print("❌ TESE REFUTADA: números persistentes são MAIS prováveis de sair!")
    else:
        print("⚪ NEUTRO: persistência não influencia o próximo número")

    # Análise por nível de persistência
    print("\n" + "="*80)
    print("📊 Análise por nível de persistência:\n")

    by_persistence = defaultdict(list)
    for r in pair_results:
        by_persistence[r["persistent_count"]].append(r)

    print(f"{'Persistente':>11} | {'Casos':>6} | {'Hit em persist':>15} | {'% hit':>8} | {'Pos média next':>14}")
    print("-" * 70)
    for persist_count in sorted(by_persistence.keys()):
        cases = by_persistence[persist_count]
        hits = sum(1 for c in cases if c["next_in_persistent"])
        pct = hits / len(cases) * 100
        positions = [c["next_pos_in_n1"] for c in cases if c["next_pos_in_n1"]]
        avg_pos = statistics.mean(positions) if positions else 0
        # Esperado por chance
        chance = persist_count / 37 * 100
        marker = ""
        if pct < chance - 1:
            marker = " ✅"
        elif pct > chance + 1:
            marker = " ❌"
        print(f"{persist_count:>11} | {len(cases):>6} | {hits:>15} | {pct:>7.2f}%{marker} | {avg_pos:>14.2f}")

    # Análise: quando o NEXT_PREV (anterior) acertou bem, qual a posição do NEXT atual?
    print("\n" + "="*80)
    print("📊 Tese 2: Quando sugestão anterior 'pagou bem', próxima fica atrasada?\n")

    # Agrupa por posição do next no ranking N (snapshot anterior)
    # Precisamos calcular a posição do número que entrou entre snap_n e snap_n1
    # Que é o anchor de snap_n1!

    by_prev_hit = defaultdict(list)
    for i in range(len(all_snaps) - 1):
        snap_n = all_snaps[i]
        snap_n1 = all_snaps[i + 1]

        # O anchor de snap_n1 é o próximo número após snap_n
        prev_hit = snap_n1.get("anchor_number")

        ranking_n = snap_n.get("payload", {}).get("suggestion") or []
        ranking_n1 = snap_n1.get("payload", {}).get("suggestion") or []

        if not ranking_n or not ranking_n1 or prev_hit is None:
            continue

        # Posição do prev_hit no snap_n
        try:
            prev_pos = ranking_n.index(int(prev_hit)) + 1
        except ValueError:
            continue

        # Próximo número (depois de snap_n1)
        anchor_n1_ts = snap_n1.get("anchor_timestamp_utc")
        if not anchor_n1_ts:
            continue
        idx = None
        for j, ts in enumerate(sorted_ts):
            if ts > anchor_n1_ts:
                idx = j
                break
        if idx is None:
            continue

        next_num = ts_to_value.get(sorted_ts[idx])
        if next_num is None:
            continue

        try:
            next_pos = ranking_n1.index(int(next_num)) + 1
        except ValueError:
            continue

        by_prev_hit[prev_pos].append(next_pos)

    print("Quando posição da sugestão anterior foi → posição da próxima é:\n")
    print(f"{'Pos prev':>10} | {'Casos':>6} | {'Pos next média':>14} | {'Mediana':>8}")
    print("-" * 50)
    # Agrupa em buckets
    buckets = {
        "1-5 (top)": [],
        "6-10 (alto)": [],
        "11-18 (médio)": [],
        "19-27 (baixo)": [],
        "28-37 (cauda)": [],
    }
    for prev_pos, next_positions in by_prev_hit.items():
        if 1 <= prev_pos <= 5:
            buckets["1-5 (top)"].extend(next_positions)
        elif 6 <= prev_pos <= 10:
            buckets["6-10 (alto)"].extend(next_positions)
        elif 11 <= prev_pos <= 18:
            buckets["11-18 (médio)"].extend(next_positions)
        elif 19 <= prev_pos <= 27:
            buckets["19-27 (baixo)"].extend(next_positions)
        elif 28 <= prev_pos <= 37:
            buckets["28-37 (cauda)"].extend(next_positions)

    for label, positions in buckets.items():
        if positions:
            avg = statistics.mean(positions)
            med = statistics.median(positions)
            print(f"{label:>14} | {len(positions):>6} | {avg:>14.2f} | {med:>8.0f}")

    print("\n💡 Se a tese estiver certa, sugestões que acertam no TOP")
    print("   deveriam levar a sugestões com pior posição na próxima.")

    print("\n" + "="*80)
    print("📊 Tese 3: Probabilidade do número 'atrasado' aparecer\n")

    # Conta quantas vezes cada número fica no top sem ser sorteado
    # Quanto MAIS um número fica no top, maior a chance de não vir?
    print("Calculando quantas sugestões consecutivas um número fica no top...")

    consecutive_top = defaultdict(list)  # number -> list of consecutive top streaks
    current_streak = defaultdict(int)

    for snap in all_snaps:
        ranking = snap.get("payload", {}).get("suggestion") or []
        if not ranking:
            continue
        top = set(ranking[:top_n])
        for n in range(37):
            if n in top:
                current_streak[n] += 1
            else:
                if current_streak[n] > 0:
                    consecutive_top[n].append(current_streak[n])
                    current_streak[n] = 0

    # Quão frequentemente um número fica no top por muitos snapshots?
    print(f"\nNúmeros com maiores 'streaks' no top {top_n}:")
    sorted_streaks = []
    for n, streaks in consecutive_top.items():
        if streaks:
            max_streak = max(streaks)
            avg_streak = statistics.mean(streaks)
            sorted_streaks.append((n, max_streak, avg_streak, len(streaks)))

    sorted_streaks.sort(key=lambda x: -x[1])
    print(f"\n{'Núm':>4} | {'Max streak':>10} | {'Avg streak':>10} | {'Total streaks':>13}")
    print("-" * 50)
    for n, max_s, avg_s, total in sorted_streaks[:10]:
        print(f"{n:>4} | {max_s:>10} | {avg_s:>10.2f} | {total:>13}")

if __name__ == "__main__":
    main()
