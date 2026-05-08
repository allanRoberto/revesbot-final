#!/usr/bin/env python3
"""Mede o impacto das melhorias de inversão por zona (Melhoria 5)."""

import requests
import json
from collections import defaultdict

API_URL = "http://localhost:8081"
ENDPOINT = "/api/suggestion-snapshots/performance/rank-timeline"
ROULETTE_ID = "pragmatic-auto-roulette"

def fetch_data(limit=100):
    """Busca dados do endpoint."""
    url = f"{API_URL}{ENDPOINT}"
    params = {
        "roulette_id": ROULETTE_ID,
        "limit": limit,
        "include_all_configs": False
    }
    try:
        response = requests.get(url, params=params, timeout=10)
        return response.json() if response.status_code == 200 else None
    except Exception as e:
        print(f"❌ Erro ao buscar dados: {e}")
        return None

def analyze_improvements(data):
    """Analisa o impacto das melhorias."""
    if not data:
        return False

    items = data.get("items", [])
    strategy = data.get("strategy", {})

    print("\n" + "="*90)
    print("📊 ANÁLISE DE IMPACTO — MELHORIAS DE INVERSÃO")
    print("="*90)

    # ===== MÉTRICAS GERAIS =====
    print("\n" + "─"*90)
    print("1️⃣  MÉTRICAS GERAIS")
    print("─"*90)

    total_items = len(items)
    triggered_items = strategy.get("triggered_items", 0)
    hit_items = strategy.get("hits_in_ranking", 0)
    hit_rate = strategy.get("hit_rate_percent", 0)

    print(f"✓ Total de itens: {total_items}")
    print(f"✓ Itens ativados (inversão): {triggered_items} ({triggered_items/total_items*100:.1f}%)")
    print(f"✓ Itens com hit no ranking: {hit_items}")
    print(f"✓ 🎯 Hit Rate GERAL: {hit_rate:.2f}%")

    # ===== ANÁLISE POR PROFUNDIDADE =====
    print("\n" + "─"*90)
    print("2️⃣  ANÁLISE POR PROFUNDIDADE (Melhoria 4 & 6)")
    print("─"*90)

    feedback_by_depth = strategy.get("feedback_by_depth", {})
    depth_performance = {}

    for depth_str in ["5", "8", "10"]:
        depth_data = feedback_by_depth.get(depth_str, {})
        hits = depth_data.get("hits", 0)
        total = depth_data.get("total", 0)
        rate = depth_data.get("rate", 0)

        if total > 0:
            depth_performance[int(depth_str)] = {
                "hits": hits,
                "total": total,
                "rate": rate
            }
            status = "🟢" if rate > 0.5 else "🟡" if rate > 0.35 else "🔴"
            print(f"{status} Depth {depth_str:2d}: {hits:2d}/{total:2d} hits = {rate*100:5.1f}%")
        else:
            print(f"⚪ Depth {depth_str:2d}: sem dados")

    # ===== ANÁLISE POR ZONA (MELHORIA 5) =====
    print("\n" + "─"*90)
    print("3️⃣  ANÁLISE POR ZONA DE INVERSÃO (Melhoria 5 — NEW!)")
    print("─"*90)

    zone_stats = defaultdict(lambda: {"total": 0, "hits": 0, "inversions": 0})

    for item in items:
        zone = item.get("strategy_inversion_zone", "none")
        original_rank = item.get("hit_rank")
        strategy_rank = item.get("strategy_hit_rank")
        is_triggered = item.get("strategy_triggered", False)

        if isinstance(original_rank, int):
            zone_stats[zone]["total"] += 1

            # Hit = strategy conseguiu melhorar a posição
            if isinstance(strategy_rank, int) and strategy_rank < original_rank:
                zone_stats[zone]["hits"] += 1

            # Count inversions por zona
            if is_triggered:
                zone_stats[zone]["inversions"] += 1

    for zone in ["top", "middle", "bottom"]:
        stats = zone_stats[zone]
        total = stats["total"]
        hits = stats["hits"]
        inversions = stats["inversions"]

        if total > 0:
            zone_rate = hits / total * 100
            inversion_rate = inversions / total * 100

            zone_emoji = "🔴" if zone == "top" else "🟡" if zone == "middle" else "🟢"
            status = "🟢" if zone_rate > 40 else "🟡" if zone_rate > 20 else "🔴"

            print(f"\n{zone_emoji} ZONA {zone.upper():8s}")
            print(f"   Total items:     {total:3d}")
            print(f"   Hit rate:        {hits:2d}/{total:2d} = {zone_rate:5.1f}% {status}")
            print(f"   Inversions:      {inversions:2d} ({inversion_rate:5.1f}%)")
        else:
            print(f"\n⚪ ZONA {zone.upper():8s}: sem dados")

    # ===== ANÁLISE POR ZONA + PROFUNDIDADE =====
    print("\n" + "─"*90)
    print("4️⃣  ANÁLISE POR ZONA + PROFUNDIDADE (Interação)")
    print("─"*90)

    zone_depth_stats = defaultdict(lambda: defaultdict(lambda: {"hits": 0, "total": 0}))

    for item in items:
        zone = item.get("strategy_inversion_zone", "none")
        depth = item.get("strategy_invert_depth", 0)
        original_rank = item.get("hit_rank")
        strategy_rank = item.get("strategy_hit_rank")

        if isinstance(original_rank, int) and zone != "none" and depth > 0:
            zone_depth_stats[zone][depth]["total"] += 1
            if isinstance(strategy_rank, int) and strategy_rank < original_rank:
                zone_depth_stats[zone][depth]["hits"] += 1

    for zone in ["top", "middle", "bottom"]:
        if zone in zone_depth_stats and zone_depth_stats[zone]:
            print(f"\n{zone.upper()}:")
            for depth in sorted(zone_depth_stats[zone].keys()):
                stats = zone_depth_stats[zone][depth]
                hits = stats["hits"]
                total = stats["total"]
                if total > 0:
                    rate = hits / total * 100
                    print(f"  Depth {depth:2d}: {hits:2d}/{total:2d} = {rate:5.1f}%")

    # ===== TENDÊNCIA E VOLATILIDADE =====
    print("\n" + "─"*90)
    print("5️⃣  ANÁLISE DE TENDÊNCIA E VOLATILIDADE (Melhoria 1 & 3)")
    print("─"*90)

    trend_stats = defaultdict(int)
    volatility_values = []
    confidence_values = []

    for item in items:
        trend = item.get("strategy_trend_state", "unknown")
        volatility = item.get("strategy_volatility", 0)
        confidence = item.get("strategy_inversion_confidence", 0.5)

        trend_stats[trend] += 1
        if volatility > 0:
            volatility_values.append(volatility)
        if confidence > 0:
            confidence_values.append(confidence)

    print("\nDistribuição de Tendência:")
    for trend, count in sorted(trend_stats.items(), key=lambda x: -x[1]):
        pct = count / total_items * 100
        print(f"  {trend:10s}: {count:3d} ({pct:5.1f}%)")

    if volatility_values:
        avg_vol = sum(volatility_values) / len(volatility_values)
        min_vol = min(volatility_values)
        max_vol = max(volatility_values)
        print(f"\nVolatilidade:")
        print(f"  Mínima: {min_vol:.3f}")
        print(f"  Média:  {avg_vol:.3f}")
        print(f"  Máxima: {max_vol:.3f}")

    if confidence_values:
        avg_conf = sum(confidence_values) / len(confidence_values)
        print(f"\nConfiança de Inversão:")
        print(f"  Média: {avg_conf:.3f}")

    # ===== RESUMO FINAL =====
    print("\n" + "="*90)
    print("📈 RESUMO E RECOMENDAÇÕES")
    print("="*90)

    if hit_rate > 50:
        print(f"✅ Hit rate {hit_rate:.1f}% está BOM (acima de 50%)")
    elif hit_rate > 40:
        print(f"🟡 Hit rate {hit_rate:.1f}% está OK (40-50%)")
    else:
        print(f"❌ Hit rate {hit_rate:.1f}% está BAIXO (abaixo de 40%)")

    # Verificar qual zona está melhor
    best_zone = max(zone_stats.items(),
                    key=lambda x: x[1]["hits"]/x[1]["total"] if x[1]["total"] > 0 else 0)
    print(f"\n🏆 Zona com melhor performance: {best_zone[0].upper()}")

    # Verificar qual profundidade está melhor
    if depth_performance:
        best_depth = max(depth_performance.items(), key=lambda x: x[1]["rate"])
        print(f"🏆 Profundidade com melhor performance: {best_depth[0]}")

    print("\n" + "="*90)

    return True

def main():
    print("🔍 Medindo impacto das melhorias de inversão...")
    print(f"📡 Conectando a {API_URL}{ENDPOINT}")

    data = fetch_data(limit=100)

    if not data:
        print("❌ Não foi possível buscar dados")
        return 1

    analyze_improvements(data)

    # Salvar dados para análise posterior
    with open("improvements_analysis.json", "w") as f:
        json.dump(data, f, indent=2, default=str)
    print("\n💾 Dados completos salvos em: improvements_analysis.json")

    return 0

if __name__ == "__main__":
    import sys
    sys.exit(main())
