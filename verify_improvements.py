#!/usr/bin/env python3
"""Verifica se as melhorias de inversão estão funcionando."""

import requests
import json
import sys

# Configuração
API_URL = "http://localhost:8000"
ENDPOINT = "/api/suggestion-snapshots/performance/rank-timeline"
ROULETTE_ID = "pragmatic-auto-roulette"

def check_server():
    """Verifica se o servidor está rodando."""
    try:
        response = requests.get(f"{API_URL}/docs", timeout=2)
        return response.status_code == 200
    except:
        return False

def fetch_timeline():
    """Busca dados da timeline."""
    url = f"{API_URL}{ENDPOINT}"
    params = {
        "roulette_id": ROULETTE_ID,
        "limit": 50,
        "include_all_configs": False
    }

    try:
        response = requests.get(url, params=params, timeout=10)
        return response.json() if response.status_code == 200 else None
    except Exception as e:
        print(f"❌ Erro ao buscar dados: {e}")
        return None

def analyze_response(data):
    """Analisa a resposta para verificar as melhorias."""
    if not data:
        return False

    print("\n" + "="*80)
    print("📊 VERIFICAÇÃO DAS MELHORIAS DE INVERSÃO")
    print("="*80)

    # Verificar estrutura básica
    items = data.get("items", [])
    strategy = data.get("strategy", {})

    print(f"\n✓ Dados recebidos: {len(items)} itens")
    print(f"✓ Strategy info: {strategy.get('name', 'N/A')}")

    # Verificar novos campos
    print("\n" + "-"*80)
    print("🔍 VERIFICANDO NOVOS CAMPOS:")
    print("-"*80)

    has_trend_state = False
    has_volatility = False
    trend_states = set()
    volatilities = []

    for i, item in enumerate(items[:10]):  # Verificar primeiros 10
        if "strategy_trend_state" in item:
            has_trend_state = True
            trend_states.add(item["strategy_trend_state"])

        if "strategy_volatility" in item:
            has_volatility = True
            volatilities.append(item["strategy_volatility"])

    # Relatório de campos
    if has_trend_state:
        print(f"✅ strategy_trend_state: PRESENTE")
        print(f"   Valores encontrados: {sorted(trend_states)}")
    else:
        print(f"❌ strategy_trend_state: NÃO ENCONTRADO")

    if has_volatility:
        print(f"✅ strategy_volatility: PRESENTE")
        if volatilities:
            min_vol = min(volatilities)
            max_vol = max(volatilities)
            avg_vol = sum(volatilities) / len(volatilities)
            print(f"   Range: {min_vol:.3f} - {max_vol:.3f}")
            print(f"   Média: {avg_vol:.3f}")
    else:
        print(f"❌ strategy_volatility: NÃO ENCONTRADO")

    # Verificar métricas de strategy
    print("\n" + "-"*80)
    print("📈 MÉTRICAS DE STRATEGY:")
    print("-"*80)

    hit_rate = strategy.get("hit_rate_percent", 0)
    triggered = strategy.get("triggered_items", 0)
    top_hits = strategy.get("top_3_hits", 0)
    top_10 = strategy.get("top_10_hits", 0)

    print(f"✓ Hit Rate: {hit_rate:.2f}%")
    print(f"✓ Itens ativados (com inversão): {triggered}")
    print(f"✓ Top 3 hits: {top_hits}")
    print(f"✓ Top 10 hits: {top_10}")

    # Verificar profundidades
    print("\n" + "-"*80)
    print("🎯 PROFUNDIDADES DE INVERSÃO:")
    print("-"*80)

    depth_counts = strategy.get("depth_counts", {})
    for depth, count in sorted(depth_counts.items()):
        if count > 0:
            pct = (count / triggered * 100) if triggered > 0 else 0
            print(f"  Depth {depth}: {count} ocorrências ({pct:.1f}%)")

    # Resultado final
    print("\n" + "="*80)
    if has_trend_state and has_volatility:
        print("✅ TODAS AS MELHORIAS ESTÃO FUNCIONANDO!")
        print("="*80)
        return True
    else:
        print("⚠️  ALGUMAS MELHORIAS PODEM NÃO ESTAR ATIVAS")
        print("="*80)
        return False

def main():
    print("🔍 Verificando se o servidor está rodando...")

    if not check_server():
        print("❌ Servidor não está respondendo em http://localhost:8000")
        print("\nInicie o servidor com:")
        print("  uvicorn apps.api.main:app --reload --host 0.0.0.0 --port 8000")
        return 1

    print("✅ Servidor está rodando!\n")

    print(f"📡 Buscando dados de {ROULETTE_ID}...")
    data = fetch_timeline()

    if not data:
        print("❌ Não foi possível buscar dados do endpoint")
        return 1

    success = analyze_response(data)

    # Salvar resposta para análise
    with open("verify_response.json", "w") as f:
        json.dump(data, f, indent=2, default=str)
    print("\n💾 Resposta completa salva em: verify_response.json")

    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())
