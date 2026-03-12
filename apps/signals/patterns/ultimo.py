from helpers.score import get_ranking, nivel_confianca
from collections import defaultdict 
import time

from datetime import datetime


state = {
    "active_signal": None,
    "attempts": 0,
    "wins": 0,
    "losses": 0
}   

contador = 0

def get_previous_rankings(numbers, window=5, top_n=18):
    rankings = []

    for i in range(1, window + 1):
        base = numbers[i]
        ranking, _ = get_ranking(numbers[i:], base, window_size=5, top_n=top_n)
        rankings.append(ranking)

    return rankings



def aggregate_rankings_by_frequency(rankings):
    freq = defaultdict(int)

    for ranking in rankings:
        for num, _ in ranking:
            freq[num] += 1

    # ordena por frequência
    aggregated = sorted(
        freq.items(),
        key=lambda x: x[1],
        reverse=True
    )

    return aggregated

def generate_signal(numbers):
    ranking, confianca = get_ranking(numbers, numbers[0], window_size=3, top_n=18)

    # top 5 do ranking
    top_numbers = [n for n, _ in ranking[:15]]

    # camada de tendência
    rankings = build_trend_window(numbers, window=5)
    trend_map = analyze_trends(rankings)
    heating = detect_heating_numbers(trend_map)

    heating_numbers = [h["number"] for h in heating[:3]]

    signal = set(top_numbers + heating_numbers)

    scores_only = [s for _, s in ranking]
    confianca = nivel_confianca(scores_only)

    return signal, ranking, confianca


def build_trend_window(numbers, window=5, top_n=18):
    rankings = []

    for i in range(window):
        base = numbers[i]
        ranking, _ = get_ranking(numbers[i:], base, window_size=5, top_n=top_n)
        rankings.append(ranking)

    return rankings


def analyze_trends(rankings):
    trend_map = {}

    for t, ranking in enumerate(rankings):
        for pos, (num, score) in enumerate(ranking):
            if num not in trend_map:
                trend_map[num] = {
                    "positions": [],
                    "scores": [],
                    "count": 0
                }

            trend_map[num]["positions"].append(pos + 1)  # posição humana
            trend_map[num]["scores"].append(score)
            trend_map[num]["count"] += 1

    return trend_map

def detect_heating_numbers(trend_map, min_presence=3):
    heating = []

    for num, data in trend_map.items():
        if data["count"] < min_presence:
            continue

        positions = data["positions"]

        # tendência de subida = posições menores com o tempo
        if positions[0] < positions[-1]:
            heating.append({
                "number": num,
                "count": data["count"],
                "best_pos": min(positions),
                "trend": positions
            })

    return sorted(heating, key=lambda x: (x["best_pos"], -x["count"]))

def process_roulette(roulette, numbers, full_results):


    slug = roulette['slug']

    if len(numbers) < 300:
        return None

    last_number = numbers[0]


    # 🔁 NÃO EXISTE SINAL ATIVO → CRIA
    if state["active_signal"] is None:
        signal, ranking, confianca = generate_signal(numbers)

        # 🔥 rankings anteriores
        prev_rankings = get_previous_rankings(numbers, window=5)
        aggregated = aggregate_rankings_by_frequency(prev_rankings)

        

        print("Ranking agregado (últimos 5 rankings):")
        bet = [num for num, _ in aggregated[:17]]
    
        state["active_signal"] = signal
        state["attempts"] = 0

        tem_comum = bool(set(numbers[:3]) & set(bet))

        bet = sorted(set(bet))

        # completa com aggregated até ter 18 números
        for n, _ in aggregated:
            if len(bet) >= 17:
                break
            if n not in bet:
                bet.append(n)

        iso_str = full_results[0]["timestamp_br"]

        dt = datetime.fromisoformat(iso_str)
        created_at = int(dt.timestamp())

        return {
        "roulette_id": slug,
        "roulette_name": roulette["name"],
        "roulette_url": roulette["url"],
        "pattern": "SCORE",
        "triggers": numbers[0],
        "targets": [*signal],
        "bets": [*signal],
        "status": "processing",
        "gales": 5,
        "passed_spins": 0,
        "spins_required": 0,
        "snapshot": numbers[:100],
        "score": confianca,
        "message": f"APOSTE AGORA",
        "tags": ["numeros_puxando", "parent"],
        "created_at" : created_at,
        "timestamp" : created_at,
        "temp_state": {
            "is_parent": True,
            "max_activations": 0,
            "max_spins": 0,
            "gales_per_child": 0,
            "current_activation": 0,
            "child_active": False,
            "active_child_id": None,
            "last_win_number": None,
            "children_ids": [],
            "total_wins": 0,
            "total_losses": 0,
        }
    }

    # 🎯 EXISTE SINAL → AVALIA
    state["attempts"] += 1

    print(f"Tentativa {state['attempts']} | número saiu: {last_number}")

    # ✅ WIN
    if last_number in state["active_signal"]:
        state["wins"] += 1

        print("✅ ACERTOU!")
        print(f"Placar → Wins: {state['wins']} | Losses: {state['losses']}")

        state["active_signal"] = None
        state["attempts"] = 0
        return

    # ❌ ESTOUROU 3 TENTATIVAS
    if state["attempts"] >= 3:
        state["losses"] += 1

        print("❌ ERROU (3 tentativas)")
        print(f"Placar → Wins: {state['wins']} | Losses: {state['losses']}")

        state["active_signal"] = None
        state["attempts"] = 0
        return

        