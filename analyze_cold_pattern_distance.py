#!/usr/bin/env python3
import json
import sys
from collections import defaultdict
from statistics import mean, stdev

# Load data
with open('suggestion_hits_with_outcomes.json') as f:
    data = json.load(f)

# Extract items array - could be nested in different ways
if isinstance(data, dict) and 'items' in data:
    items = data['items']
elif isinstance(data, list):
    items = data
else:
    print("Warning: unexpected data structure")
    items = []

print(f"Loaded {len(items)} items\n")

# Strategy: 2 frios (numbers > 12) + threshold 14
COLD_THRESHOLD = 12
APOSTA_THRESHOLD = 14
COLD_COUNT = 3

def get_pattern_type(nums):
    """Classify pattern: crescente, decrescente, or estável"""
    if len(nums) < 2:
        return "unknown"

    is_increasing = all(nums[i] < nums[i+1] for i in range(len(nums)-1))
    is_decreasing = all(nums[i] > nums[i+1] for i in range(len(nums)-1))

    if is_increasing:
        return "crescente"
    elif is_decreasing:
        return "decrescente"
    else:
        return "estável"

def get_depth_category(nums):
    """Classify how deep into cold zone (0-infinity where 12 is boundary)"""
    # Distance from threshold: how much > 12
    distances = [n - COLD_THRESHOLD for n in nums if n > COLD_THRESHOLD]
    if not distances:
        return "none"

    avg_distance = mean(distances)
    max_distance = max(distances)

    if avg_distance <= 5:
        return "shallow"  # 13-17 range
    elif avg_distance <= 10:
        return "medium"   # 13-22 range
    else:
        return "deep"     # 23+ range

def analyze_cold_sequence(ranking_full):
    """
    Find sequences of 3+ consecutive frios (>12)
    Return list of (positions, pattern, depth, distance_min, distance_max)
    """
    sequences = []
    cold_sequence = []

    for i, rank in enumerate(ranking_full):
        if rank > COLD_THRESHOLD:
            cold_sequence.append((i, rank))
        else:
            if len(cold_sequence) >= COLD_COUNT:
                positions = [r for _, r in cold_sequence]
                sequences.append({
                    'positions': positions,
                    'pattern': get_pattern_type(positions),
                    'depth': get_depth_category(positions),
                    'distance_min': min(p - COLD_THRESHOLD for p in positions),
                    'distance_max': max(p - COLD_THRESHOLD for p in positions),
                    'distance_mean': mean(p - COLD_THRESHOLD for p in positions),
                })
            cold_sequence = []

    if len(cold_sequence) >= COLD_COUNT:
        positions = [r for _, r in cold_sequence]
        sequences.append({
            'positions': positions,
            'pattern': get_pattern_type(positions),
            'depth': get_depth_category(positions),
            'distance_min': min(p - COLD_THRESHOLD for p in positions),
            'distance_max': max(p - COLD_THRESHOLD for p in positions),
            'distance_mean': mean(p - COLD_THRESHOLD for p in positions),
        })

    return sequences

# Analyze all items
stats = defaultdict(lambda: {'hits': 0, 'total': 0, 'first_attempt': 0})
pattern_stats = defaultdict(lambda: {'hits': 0, 'total': 0, 'first_attempt': 0})
depth_stats = defaultdict(lambda: {'hits': 0, 'total': 0, 'first_attempt': 0})
distance_buckets = defaultdict(lambda: {'hits': 0, 'total': 0, 'first_attempt': 0})

valid_items = 0
items_with_sequences = 0

for item in items:
    try:
        ranking_full = item.get('ranking_full', [])
        hit_rank = item.get('hit_rank')
        roulette = item.get('roulette_id', 'unknown')

        if not ranking_full or hit_rank is None:
            continue

        sequences = analyze_cold_sequence(ranking_full)

        if not sequences:
            continue

        valid_items += 1
        items_with_sequences += 1

        # Check if bet would succeed (hit_rank <= APOSTA_THRESHOLD)
        hit = hit_rank <= APOSTA_THRESHOLD
        first_attempt = hit_rank == 1

        for seq in sequences:
            pattern = seq['pattern']
            depth = seq['depth']
            distance_bucket = f"{int(seq['distance_mean'])}"

            # Aggregate stats
            stats['overall']['hits'] += hit
            stats['overall']['total'] += 1
            stats['overall']['first_attempt'] += first_attempt

            pattern_stats[pattern]['hits'] += hit
            pattern_stats[pattern]['total'] += 1
            pattern_stats[pattern]['first_attempt'] += first_attempt

            depth_stats[depth]['hits'] += hit
            depth_stats[depth]['total'] += 1
            depth_stats[depth]['first_attempt'] += first_attempt

            distance_buckets[distance_bucket]['hits'] += hit
            distance_buckets[distance_bucket]['total'] += 1
            distance_buckets[distance_bucket]['first_attempt'] += first_attempt

    except Exception as e:
        print(f"Error processing item: {e}")
        continue

print(f"Valid items: {valid_items}")
print(f"Items with 3+ consecutive frios: {items_with_sequences}\n")

# Results by pattern type
print("=" * 70)
print("ANÁLISE POR TIPO DE PADRÃO (Pattern of 3 cold numbers)")
print("=" * 70)
for pattern in ['crescente', 'decrescente', 'estável']:
    s = pattern_stats[pattern]
    if s['total'] > 0:
        win_rate = (s['hits'] / s['total']) * 100
        first_rate = (s['first_attempt'] / s['total']) * 100
        print(f"\n{pattern.upper()}:")
        print(f"  Apostas: {s['total']}")
        print(f"  Acertos: {s['hits']}")
        print(f"  Taxa: {win_rate:.1f}%")
        print(f"  1º Tentativa: {first_rate:.1f}%")

# Results by depth
print("\n" + "=" * 70)
print("ANÁLISE POR PROFUNDIDADE (Distance from threshold 12)")
print("=" * 70)
for depth in ['shallow', 'medium', 'deep']:
    s = depth_stats[depth]
    if s['total'] > 0:
        win_rate = (s['hits'] / s['total']) * 100
        first_rate = (s['first_attempt'] / s['total']) * 100
        print(f"\n{depth.upper()} (avg distance {12 + (5 if depth == 'shallow' else 10 if depth == 'medium' else 20)}):")
        print(f"  Apostas: {s['total']}")
        print(f"  Acertos: {s['hits']}")
        print(f"  Taxa: {win_rate:.1f}%")
        print(f"  1º Tentativa: {first_rate:.1f}%")

# Results by exact distance
print("\n" + "=" * 70)
print("ANÁLISE POR DISTÂNCIA EXATA (Mean distance of 3 cold numbers from rank 12)")
print("=" * 70)
sorted_distances = sorted(distance_buckets.keys(), key=lambda x: float(x))
for distance in sorted_distances:
    s = distance_buckets[distance]
    if s['total'] >= 3:  # Only show if at least 3 samples
        win_rate = (s['hits'] / s['total']) * 100
        first_rate = (s['first_attempt'] / s['total']) * 100
        print(f"\nDistância média {distance}:")
        print(f"  Apostas: {s['total']}")
        print(f"  Acertos: {s['hits']}")
        print(f"  Taxa: {win_rate:.1f}%")
        print(f"  1º Tentativa: {first_rate:.1f}%")

# Overall
print("\n" + "=" * 70)
print("RESUMO GERAL")
print("=" * 70)
s = stats['overall']
if s['total'] > 0:
    win_rate = (s['hits'] / s['total']) * 100
    first_rate = (s['first_attempt'] / s['total']) * 100
    print(f"Total de apostas analisadas: {s['total']}")
    print(f"Acertos: {s['hits']}")
    print(f"Taxa geral: {win_rate:.1f}%")
    print(f"Taxa 1º tentativa: {first_rate:.1f}%")

print("\nCONCLUSÃO:")
print("Analisa se números frios CAINDO, SUBINDO ou ESTÁVEIS")
print("e se mais profundos (>20) vs rasos (13-17) afetam acertos.")
print("Resultado: identifica qual padrão/profundidade é MELHOR para apostar")
