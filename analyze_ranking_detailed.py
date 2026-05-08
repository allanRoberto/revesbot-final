#!/usr/bin/env python3
"""Análise detalhada da distribuição de ranking de sugestões."""
import json
from pathlib import Path
from collections import defaultdict, Counter
from statistics import mean, median, stdev


def load_analysis_file(filepath: str) -> dict:
    """Carrega o arquivo de análise."""
    with open(filepath, 'r') as f:
        return json.load(f)


def generate_detailed_report(data: dict) -> str:
    """Gera relatório detalhado da análise."""
    summary = data.get('summary', {})
    items = data.get('items', [])

    report = []
    report.append("=" * 80)
    report.append("ANÁLISE DETALHADA DE RANKING DE SUGESTÕES")
    report.append("=" * 80)
    report.append("")

    # Resumo geral
    report.append("📊 RESUMO GERAL")
    report.append("-" * 80)
    report.append(f"Total de sugestões analisadas: {summary.get('total_items', 0)}")
    report.append("")

    # Por roleta
    for roulette, data_info in summary.get('by_roulette', {}).items():
        report.append(f"\n🎰 {roulette}")
        report.append(f"   Total de hits: {data_info.get('count', 0)}")

        if 'analysis' in data_info and 'statistics' in data_info['analysis']:
            stats = data_info['analysis']['statistics']
            report.append(f"   Ranking mínimo: {stats.get('min_rank', 'N/A')}")
            report.append(f"   Ranking máximo: {stats.get('max_rank', 'N/A')}")
            report.append(f"   Média: {stats.get('avg_rank', 'N/A'):.2f}" if isinstance(stats.get('avg_rank'), (int, float)) else f"   Média: {stats.get('avg_rank', 'N/A')}")
            report.append(f"   Mediana: {stats.get('median_rank', 'N/A')}")
            report.append(f"   Top 5: {stats.get('hits_in_top_5', 0)} ({stats.get('percentage_top_5', 0):.1f}%)")
            report.append(f"   Top 10: {stats.get('hits_in_top_10', 0)} ({stats.get('percentage_top_10', 0):.1f}%)")
            report.append(f"   Top 20: {stats.get('hits_in_top_20', 0)} ({stats.get('percentage_top_20', 0):.1f}%)")

    # Análise geral
    overall = summary.get('overall_analysis', {})
    if 'statistics' in overall:
        report.append(f"\n\n📈 ANÁLISE GERAL")
        report.append("-" * 80)
        stats = overall['statistics']
        report.append(f"Ranking mínimo: {stats.get('min_rank', 'N/A')}")
        report.append(f"Ranking máximo: {stats.get('max_rank', 'N/A')}")
        report.append(f"Média: {stats.get('avg_rank', 'N/A'):.2f}" if isinstance(stats.get('avg_rank'), (int, float)) else f"Média: {stats.get('avg_rank', 'N/A')}")
        report.append(f"Mediana: {stats.get('median_rank', 'N/A')}")
        report.append(f"Total de hits que batem no ranking: {stats.get('total_hits', 0)}")
        report.append(f"Top 5: {stats.get('hits_in_top_5', 0)} hits ({stats.get('percentage_top_5', 0):.1f}%)")
        report.append(f"Top 10: {stats.get('hits_in_top_10', 0)} hits ({stats.get('percentage_top_10', 0):.1f}%)")
        report.append(f"Top 20: {stats.get('hits_in_top_20', 0)} hits ({stats.get('percentage_top_20', 0):.1f}%)")

        # Distribuição
        if 'distribution' in stats:
            report.append(f"\n📊 Distribuição de Rankings (Top 20):")
            dist = stats['distribution']
            sorted_ranks = sorted([int(k) for k in dist.keys()])[:20]
            for rank in sorted_ranks:
                count = dist.get(str(rank), 0)
                percentage = (count / stats.get('total_hits', 1)) * 100
                bar_length = int(percentage / 2)
                bar = "█" * bar_length
                report.append(f"   Rank {rank:3d}: {count:4d} ({percentage:5.1f}%) {bar}")

    report.append("\n" + "=" * 80)
    return "\n".join(report)


def main():
    filepath = Path("suggestion_hits_3000_analysis.json")

    if not filepath.exists():
        print(f"❌ Arquivo {filepath} não encontrado")
        print("Execute fetch_3000_suggestions_analysis.py primeiro")
        return

    data = load_analysis_file(filepath)
    report = generate_detailed_report(data)

    print(report)

    # Salvar relatório
    report_path = Path("suggestion_ranking_detailed_report.txt")
    with open(report_path, 'w') as f:
        f.write(report)

    print(f"\n✅ Relatório salvo em {report_path}")


if __name__ == "__main__":
    main()
