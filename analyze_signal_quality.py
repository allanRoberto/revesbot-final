#!/usr/bin/env python3
"""Analisa diferenças entre sinais bons (top 12) e ruins (ranking > 12)."""
import json
from pathlib import Path
from collections import defaultdict
import statistics


def load_data():
    """Carrega os dados da análise."""
    filepath = Path("suggestion_hits_3000_analysis.json")
    if not filepath.exists():
        print(f"❌ Arquivo {filepath} não encontrado")
        return None

    with open(filepath, 'r') as f:
        return json.load(f)


def separate_signals(items):
    """Separa sinais em bons (top 12) e ruins (> 12)."""
    good_signals = []
    bad_signals = []

    for item in items:
        hit_rank = item.get('hit_rank', 0)
        if hit_rank <= 12:
            good_signals.append(item)
        else:
            bad_signals.append(item)

    return good_signals, bad_signals


def analyze_ranking_distribution(items):
    """Analisa distribuição dos rankings nos itens."""
    if not items:
        return {}

    ranks = [item.get('hit_rank', 0) for item in items]

    return {
        'count': len(items),
        'avg_rank': statistics.mean(ranks) if ranks else 0,
        'median_rank': statistics.median(ranks) if ranks else 0,
        'std_dev': statistics.stdev(ranks) if len(ranks) > 1 else 0,
        'min_rank': min(ranks) if ranks else 0,
        'max_rank': max(ranks) if ranks else 0,
    }


def analyze_roulette_distribution(items):
    """Analisa distribuição por roleta."""
    dist = defaultdict(int)
    for item in items:
        roulette = item.get('roulette_id', 'unknown')
        dist[roulette] += 1
    return dict(dist)


def analyze_number_distribution(items):
    """Analisa quais números saem mais frequentemente."""
    dist = defaultdict(int)
    for item in items:
        number = item.get('next_number')
        if number is not None:
            dist[number] += 1

    # Top 10 números
    sorted_nums = sorted(dist.items(), key=lambda x: x[1], reverse=True)
    return {
        'total_unique_numbers': len(dist),
        'top_10_numbers': sorted_nums[:10],
        'distribution': dict(sorted_nums)
    }


def analyze_ranking_position(items):
    """Analisa a posição no ranking sugerido."""
    positions = defaultdict(int)
    for item in items:
        rank = item.get('hit_rank', 0)
        positions[rank] += 1

    # Distribuição
    return {
        'distribution': dict(sorted(positions.items())),
        'most_common_ranks': sorted(positions.items(), key=lambda x: x[1], reverse=True)[:5]
    }


def analyze_anchor_numbers(items):
    """Analisa os números âncora (anterior)."""
    dist = defaultdict(int)
    for item in items:
        anchor = item.get('anchor_number')
        if anchor is not None:
            dist[anchor] += 1

    sorted_anchors = sorted(dist.items(), key=lambda x: x[1], reverse=True)
    return {
        'total_unique_anchors': len(dist),
        'top_anchors': sorted_anchors[:10],
    }


def analyze_ranking_size(items):
    """Analisa o tamanho do ranking sugerido."""
    sizes = [item.get('ranking_size', 0) for item in items]

    if not sizes:
        return {}

    return {
        'avg_size': statistics.mean(sizes),
        'median_size': statistics.median(sizes),
        'min_size': min(sizes),
        'max_size': max(sizes),
    }


def analyze_temporal_patterns(items):
    """Analisa padrões temporais."""
    hour_distribution = defaultdict(int)

    for item in items:
        ts = item.get('next_timestamp_utc', '')
        if 'T' in ts:
            time_part = ts.split('T')[1]
            if ':' in time_part:
                hour = int(time_part.split(':')[0])
                hour_distribution[hour] += 1

    if not hour_distribution:
        return {}

    sorted_hours = sorted(hour_distribution.items(), key=lambda x: x[1], reverse=True)

    return {
        'total_hours': len(hour_distribution),
        'peak_hours': sorted_hours[:5],
        'distribution': dict(sorted(hour_distribution.items()))
    }


def generate_comparison_report(data):
    """Gera relatório comparativo."""
    items = data.get('items', [])
    good_signals, bad_signals = separate_signals(items)

    report = []
    report.append("\n" + "═" * 100)
    report.append("ANÁLISE COMPARATIVA: BONS SINAIS (TOP 12) vs PIORES SINAIS (RANKING > 12)".center(100))
    report.append("═" * 100 + "\n")

    # Resumo geral
    report.append("📊 RESUMO GERAL:")
    report.append("-" * 100)
    report.append(f"\nBONS SINAIS (Top 12):")
    report.append(f"  Total: {len(good_signals):,}")
    report.append(f"  Percentual: {(len(good_signals) / len(items) * 100):.1f}% do total")

    report.append(f"\nPIORES SINAIS (Ranking > 12):")
    report.append(f"  Total: {len(bad_signals):,}")
    report.append(f"  Percentual: {(len(bad_signals) / len(items) * 100):.1f}% do total")

    # Análise de rankings
    report.append(f"\n\n📈 ANÁLISE DE RANKINGS:")
    report.append("-" * 100)

    good_rank_analysis = analyze_ranking_distribution(good_signals)
    bad_rank_analysis = analyze_ranking_distribution(bad_signals)

    report.append(f"\nBONS SINAIS:")
    report.append(f"  Ranking médio: {good_rank_analysis['avg_rank']:.2f}")
    report.append(f"  Ranking mediano: {good_rank_analysis['median_rank']:.0f}")
    report.append(f"  Desvio padrão: {good_rank_analysis['std_dev']:.2f}")
    report.append(f"  Range: {good_rank_analysis['min_rank']:.0f} - {good_rank_analysis['max_rank']:.0f}")

    report.append(f"\nPIORES SINAIS:")
    report.append(f"  Ranking médio: {bad_rank_analysis['avg_rank']:.2f}")
    report.append(f"  Ranking mediano: {bad_rank_analysis['median_rank']:.0f}")
    report.append(f"  Desvio padrão: {bad_rank_analysis['std_dev']:.2f}")
    report.append(f"  Range: {bad_rank_analysis['min_rank']:.0f} - {bad_rank_analysis['max_rank']:.0f}")

    # Distribuição por roleta
    report.append(f"\n\n🎰 DISTRIBUIÇÃO POR ROLETA:")
    report.append("-" * 100)

    good_roulette = analyze_roulette_distribution(good_signals)
    bad_roulette = analyze_roulette_distribution(bad_signals)

    for roulette in good_roulette.keys():
        good_count = good_roulette.get(roulette, 0)
        bad_count = bad_roulette.get(roulette, 0)
        total = good_count + bad_count
        good_pct = (good_count / total * 100) if total > 0 else 0

        report.append(f"\n{roulette}")
        report.append(f"  Bons: {good_count:,} ({good_pct:.1f}%)")
        report.append(f"  Ruins: {bad_count:,} ({100-good_pct:.1f}%)")

    # Números mais frequentes
    report.append(f"\n\n🔢 NÚMEROS MAIS FREQUENTES:")
    report.append("-" * 100)

    good_nums = analyze_number_distribution(good_signals)
    bad_nums = analyze_number_distribution(bad_signals)

    report.append(f"\nBONS SINAIS - Top 10 números que saem:")
    for num, count in good_nums['top_10_numbers']:
        pct = (count / len(good_signals) * 100) if good_signals else 0
        report.append(f"  {num:2d}: {count:3d} ocorrências ({pct:.1f}%)")

    report.append(f"\nPIORES SINAIS - Top 10 números que saem:")
    for num, count in bad_nums['top_10_numbers']:
        pct = (count / len(bad_signals) * 100) if bad_signals else 0
        report.append(f"  {num:2d}: {count:3d} ocorrências ({pct:.1f}%)")

    # Números âncora
    report.append(f"\n\n⚓ NÚMEROS ÂNCORA (anterior ao sorteio):")
    report.append("-" * 100)

    good_anchors = analyze_anchor_numbers(good_signals)
    bad_anchors = analyze_anchor_numbers(bad_signals)

    report.append(f"\nBONS SINAIS - Top 10 âncoras:")
    for anchor, count in good_anchors['top_anchors']:
        pct = (count / len(good_signals) * 100) if good_signals else 0
        report.append(f"  {anchor:2d}: {count:3d} vezes ({pct:.1f}%)")

    report.append(f"\nPIORES SINAIS - Top 10 âncoras:")
    for anchor, count in bad_anchors['top_anchors']:
        pct = (count / len(bad_signals) * 100) if bad_signals else 0
        report.append(f"  {anchor:2d}: {count:3d} vezes ({pct:.1f}%)")

    # Tamanho do ranking
    report.append(f"\n\n📏 TAMANHO DO RANKING SUGERIDO:")
    report.append("-" * 100)

    good_size = analyze_ranking_size(good_signals)
    bad_size = analyze_ranking_size(bad_signals)

    report.append(f"\nBONS SINAIS:")
    report.append(f"  Tamanho médio: {good_size.get('avg_size', 0):.1f}")
    report.append(f"  Tamanho mediano: {good_size.get('median_size', 0):.0f}")

    report.append(f"\nPIORES SINAIS:")
    report.append(f"  Tamanho médio: {bad_size.get('avg_size', 0):.1f}")
    report.append(f"  Tamanho mediano: {bad_size.get('median_size', 0):.0f}")

    # Padrões temporais
    report.append(f"\n\n⏰ PADRÕES TEMPORAIS (horários com mais ocorrências):")
    report.append("-" * 100)

    good_temporal = analyze_temporal_patterns(good_signals)
    bad_temporal = analyze_temporal_patterns(bad_signals)

    if good_temporal and good_temporal.get('peak_hours'):
        report.append(f"\nBONS SINAIS - Horários de pico:")
        for hour, count in good_temporal['peak_hours'][:5]:
            pct = (count / len(good_signals) * 100) if good_signals else 0
            report.append(f"  {hour:02d}:00 - {count:3d} ocorrências ({pct:.1f}%)")

    if bad_temporal and bad_temporal.get('peak_hours'):
        report.append(f"\nPIORES SINAIS - Horários de pico:")
        for hour, count in bad_temporal['peak_hours'][:5]:
            pct = (count / len(bad_signals) * 100) if bad_signals else 0
            report.append(f"  {hour:02d}:00 - {count:3d} ocorrências ({pct:.1f}%)")

    # Insights
    report.append(f"\n\n💡 INSIGHTS E PADRÕES IDENTIFICADOS:")
    report.append("-" * 100)

    report.append(f"\n1. CONCENTRAÇÃO TEMPORAL:")
    if good_temporal and bad_temporal:
        good_peak = good_temporal['peak_hours'][0] if good_temporal['peak_hours'] else (0, 0)
        bad_peak = bad_temporal['peak_hours'][0] if bad_temporal['peak_hours'] else (0, 0)
        if good_peak[0] != bad_peak[0]:
            report.append(f"   ✓ Bons sinais concentram-se em {good_peak[0]:02d}:00")
            report.append(f"   ✓ Piores sinais concentram-se em {bad_peak[0]:02d}:00")
            report.append(f"   → OPORTUNIDADE: Filtrar por horário pode melhorar sinais")

    report.append(f"\n2. DIFERENÇA DE RANKINGS:")
    rank_diff = bad_rank_analysis['avg_rank'] - good_rank_analysis['avg_rank']
    report.append(f"   • Bons sinais têm ranking {rank_diff:.2f} posições melhor")
    report.append(f"   • Desvio padrão dos bons: {good_rank_analysis['std_dev']:.2f}")
    report.append(f"   • Desvio padrão dos ruins: {bad_rank_analysis['std_dev']:.2f}")

    report.append(f"\n3. PADRÃO DE NÚMEROS:")
    # Verificar se os números que saem em bons sinais são diferentes
    good_top_nums = [num for num, _ in good_nums['top_10_numbers'][:5]]
    bad_top_nums = [num for num, _ in bad_nums['top_10_numbers'][:5]]
    overlap = len(set(good_top_nums) & set(bad_top_nums))
    report.append(f"   • Top 5 números bons: {good_top_nums}")
    report.append(f"   • Top 5 números ruins: {bad_top_nums}")
    report.append(f"   • Sobreposição: {overlap}/5")

    report.append(f"\n4. DISTRIBUIÇÃO POR ROLETA:")
    for roulette in good_roulette.keys():
        good_count = good_roulette.get(roulette, 0)
        bad_count = bad_roulette.get(roulette, 0)
        total = good_count + bad_count
        good_pct = (good_count / total * 100) if total > 0 else 0
        report.append(f"   • {roulette}: {good_pct:.1f}% bons sinais")

    report.append("\n" + "═" * 100 + "\n")

    return "\n".join(report)


def main():
    data = load_data()
    if not data:
        return

    report = generate_comparison_report(data)
    print(report)

    # Salvar relatório
    with open("ANALISE_SINAIS_COMPARATIVA.txt", "w", encoding='utf-8') as f:
        f.write(report)

    print("✅ Análise salva em ANALISE_SINAIS_COMPARATIVA.txt")


if __name__ == "__main__":
    main()
