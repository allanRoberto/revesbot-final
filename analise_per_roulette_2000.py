#!/usr/bin/env python3
"""
Estratégia diferenciada por roleta:
  - Brazilian: ativação < 7, 3 frios, aposta 14, 4 tentativas
  - Auto: ativação < 20, 3 frios, aposta 14, 4 tentativas
Analisa 2000 itens por roleta.
"""
import json
from collections import defaultdict
from pathlib import Path

DATA_FILE = "suggestion_hits_2000_per_roulette.json"

with open(DATA_FILE) as f:
    data = json.load(f)

items = data['items'] if isinstance(data, dict) and 'items' in data else data
print(f"Loaded {len(items)} items\n")

# Per-roulette strategy
STRATEGIES = {
    "pragmatic-brazilian-roulette": {
        "activation_rank": 7,    # < 7
        "label": "Brazilian (ativação < 7)",
    },
    "pragmatic-auto-roulette": {
        "activation_rank": 20,   # < 20
        "label": "Auto (ativação < 20)",
    },
}

COLD_THRESHOLD = 12      # Frios = hit_rank > 12
COLD_COUNT = 3
BET_THRESHOLD = 14
MAX_ATTEMPTS = 4


def simulate(items_chrono, activation_rank: int):
    bets = []
    state = 'WAITING'
    frio_count = 0
    activation_item = None
    frio_items = []

    for idx, item in enumerate(items_chrono):
        rank = item['hit_rank']

        if state == 'WAITING':
            if rank < activation_rank:
                state = 'COUNTING_FRIOS'
                frio_count = 0
                activation_item = item
                frio_items = []

        elif state == 'COUNTING_FRIOS':
            if rank > COLD_THRESHOLD:
                frio_count += 1
                frio_items.append(item)
                if frio_count >= COLD_COUNT:
                    state = 'READY_TO_BET'
            else:
                if rank < activation_rank:
                    state = 'COUNTING_FRIOS'
                    frio_count = 0
                    activation_item = item
                    frio_items = []
                else:
                    state = 'WAITING'
                    frio_count = 0
                    activation_item = None
                    frio_items = []

        elif state == 'READY_TO_BET':
            attempt_ranks = [rank]
            won = rank <= BET_THRESHOLD
            won_on = 1 if won else None
            if not won:
                for j in range(1, MAX_ATTEMPTS):
                    if idx + j >= len(items_chrono):
                        break
                    next_rank = items_chrono[idx + j]['hit_rank']
                    attempt_ranks.append(next_rank)
                    if next_rank <= BET_THRESHOLD:
                        won = True
                        won_on = j + 1
                        break

            bets.append({
                'snapshot_id': item['snapshot_id'],
                'roulette_id': item['roulette_id'],
                'timestamp': item.get('anchor_timestamp_utc'),
                'attempt_ranks': attempt_ranks,
                'attempts_used': len(attempt_ranks),
                'win': won,
                'won_on': won_on,
                'first_attempt_win': won_on == 1,
                'activation_rank': activation_item['hit_rank'] if activation_item else None,
                'frio_ranks': [f['hit_rank'] for f in frio_items],
            })
            state = 'WAITING'
            frio_count = 0
            activation_item = None
            frio_items = []

    return bets


# Group by roulette and sort chronologically
by_roulette = defaultdict(list)
for item in items:
    if item.get('hit_rank') is None:
        continue
    by_roulette[item.get('roulette_id', 'unknown')].append(item)

for roulette in by_roulette:
    by_roulette[roulette].sort(key=lambda x: x.get('anchor_timestamp_utc', ''))

print("Itens por roleta:")
for r, lst in by_roulette.items():
    print(f"  {r}: {len(lst)}")
print()

# Run per-roulette strategies
all_results = {}
for roulette, items_chrono in by_roulette.items():
    cfg = STRATEGIES.get(roulette)
    if not cfg:
        print(f"⚠️  Sem estratégia para {roulette}")
        continue

    print(f"=" * 80)
    print(f"ESTRATÉGIA: {cfg['label']}")
    print(f"  3 frios (>{COLD_THRESHOLD}), aposta ≤ {BET_THRESHOLD}, até {MAX_ATTEMPTS} tentativas")
    print(f"  Itens analisados: {len(items_chrono)}")
    print("=" * 80)

    bets = simulate(items_chrono, cfg["activation_rank"])
    n = len(bets)
    wins = sum(1 for b in bets if b['win'])
    losses = n - wins
    rate = (wins / n * 100) if n else 0
    first_attempt_wins = sum(1 for b in bets if b['first_attempt_win'])

    by_attempt = defaultdict(int)
    for b in bets:
        if b['win']:
            by_attempt[b['won_on']] += 1
        else:
            by_attempt['perdeu'] += 1

    print(f"\n📊 Apostas: {n}")
    print(f"   Acertos: {wins}")
    print(f"   Taxa: {rate:.1f}%")
    print(f"   Taxa 1ª tentativa: {(first_attempt_wins/n*100) if n else 0:.1f}%")
    print(f"\n🎯 Distribuição de tentativas vitoriosas:")
    for k in [1, 2, 3, 4, 'perdeu']:
        cnt = by_attempt[k]
        pct = cnt / n * 100 if n else 0
        label = f"{k}ª tentativa" if isinstance(k, int) else "PERDEU (4 falhas)"
        bar = '█' * int(pct / 2)
        print(f"   {label:>20}: {cnt:>4} ({pct:.1f}%) {bar}")

    all_results[roulette] = {
        'strategy': cfg['label'],
        'items_analyzed': len(items_chrono),
        'apostas': n,
        'acertos': wins,
        'perdas': losses,
        'taxa': rate,
        'taxa_primeira_tentativa': (first_attempt_wins/n*100) if n else 0,
        'distribuicao_tentativas': {str(k): by_attempt[k] for k in [1,2,3,4,'perdeu']},
        'sample_bets': bets[:30],
    }
    print()

# Combined
total_n = sum(r['apostas'] for r in all_results.values())
total_w = sum(r['acertos'] for r in all_results.values())
print("=" * 80)
print("COMBINADO (Brazilian + Auto com estratégias diferentes)")
print("=" * 80)
print(f"Total apostas: {total_n}")
print(f"Total acertos: {total_w}")
print(f"Taxa combinada: {(total_w/total_n*100) if total_n else 0:.1f}%")

with open("analise_per_roulette_2000.json", "w") as f:
    json.dump({
        "config": {
            "cold_threshold": COLD_THRESHOLD,
            "cold_count": COLD_COUNT,
            "bet_threshold": BET_THRESHOLD,
            "max_attempts": MAX_ATTEMPTS,
            "strategies": STRATEGIES,
        },
        "results": all_results,
        "combined": {
            "apostas": total_n,
            "acertos": total_w,
            "taxa": (total_w/total_n*100) if total_n else 0,
        },
    }, f, indent=2)

print(f"\n✅ Salvo em: analise_per_roulette_2000.json")
