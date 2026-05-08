#!/usr/bin/env python3
"""Gera visualização da distribuição de rankings."""
import json
from pathlib import Path
from collections import defaultdict


def visualize_distribution(data: dict) -> None:
    """Cria visualização textual da distribuição."""
    summary = data.get('summary', {})
    overall = summary.get('overall_analysis', {})

    if 'statistics' not in overall:
        print("❌ Nenhuma estatística encontrada")
        return

    stats = overall['statistics']
    distribution = stats.get('distribution', {})

    if not distribution:
        print("❌ Distribuição não encontrada")
        return

    print("\n" + "=" * 100)
    print("VISUALIZAÇÃO DA DISTRIBUIÇÃO DE RANKINGS")
    print("=" * 100)

    total_hits = stats.get('total_hits', 0)

    # Calcular largura máxima da barra baseado no maior valor
    max_count = max(int(v) for v in distribution.values()) if distribution else 0
    max_bar_width = 50

    # Mostrar top 30
    ranks = sorted([int(k) for k in distribution.keys()])
    limit = min(30, len(ranks))

    for i, rank in enumerate(ranks[:limit]):
        count = distribution.get(str(rank), 0)
        percentage = (count / total_hits * 100) if total_hits > 0 else 0
        bar_width = int((count / max_count * max_bar_width)) if max_count > 0 else 0
        bar = "█" * bar_width

        print(f"Rank {rank:3d} │ {count:4d} hits ({percentage:5.1f}%) │ {bar}")

    print("=" * 100)
    print(f"\nResumo:")
    print(f"  Total de hits: {total_hits}")
    print(f"  Ranking médio: {stats.get('avg_rank', 'N/A'):.2f}" if isinstance(stats.get('avg_rank'), (int, float)) else f"  Ranking médio: {stats.get('avg_rank', 'N/A')}")
    print(f"  Ranking mediano: {stats.get('median_rank', 'N/A')}")
    print(f"  Min: {stats.get('min_rank', 'N/A')} | Max: {stats.get('max_rank', 'N/A')}")
    print(f"\nTaxa de acertos:")
    print(f"  Top 1: {stats.get('hits_in_top_5', 0)} ({stats.get('percentage_top_5', 0):.1f}%)")
    print(f"  Top 10: {stats.get('hits_in_top_10', 0)} ({stats.get('percentage_top_10', 0):.1f}%)")
    print(f"  Top 20: {stats.get('hits_in_top_20', 0)} ({stats.get('percentage_top_20', 0):.1f}%)")


def main():
    filepath = Path("suggestion_hits_3000_analysis.json")

    if not filepath.exists():
        print(f"❌ Arquivo {filepath} não encontrado")
        return

    with open(filepath, 'r') as f:
        data = json.load(f)

    visualize_distribution(data)


if __name__ == "__main__":
    main()
