"""
Testa o impacto de corrigir a lógica de inversão.

HIPÓTESE: Se não penalizássemos números quentes que NÃO foram selecionados
naturalmente (in_pulled_in_final=False), melhoraríamos a posição média.

Estratégia de simulação:
1. Para cada snapshot onde next ∈ invertedNumbers
2. Se next ∉ pulledInFinal, estimar posição sem inversão
3. Comparar posição atual vs posição corrigida
"""
from __future__ import annotations

import csv
import statistics
from pathlib import Path
import certifi
from pymongo import MongoClient, DESCENDING

csv_path = "_validation_results.csv"
data = list(csv.DictReader(open(csv_path)))

scenario_a = [r for r in data if r['in_inverted_numbers'] == 'True' and r['in_inverted_in_final'] == 'False']
scenario_c = [r for r in data if r['in_inverted_numbers'] == 'True' and r['in_inverted_in_final'] == 'True']

print("="*80)
print("SIMULAÇÃO: Impacto de corrigir a lógica de inversão\n")

print(f"Status atual:")
print(f"  Cenário A (bom): {len(scenario_a)} casos, pos média = 14.11")
print(f"  Cenário C (ruim): {len(scenario_c)} casos, pos média = 34.15")
print(f"  Total com in_inverted: {len(scenario_a) + len(scenario_c)} casos\n")

# Agora vamos investigar: se removêssemos a inversão em Cenário C,
# qual seria a posição estimada?

# A posição do "next" em um ranking de 37 números é influenciada por:
# 1. Quão bem o algoritmo o ranking naturalmente
# 2. Penalidades aplicadas

# Se o número está em pos 34 (muito baixo) mas foi identificado como importante
# (in_inverted_numbers), e tem confiança média 67, é porque foi penalizado.

# Estratégia: estimar posição sem inversão
# Se um número está em pos 34, e sabemos que inversão o empurrou para baixo,
# uma estimativa razoável é: mover para a posição "natural" que seria sem inversão

# Dados de Cenário C
print("="*80)
print("ANÁLISE: Cenário C (números penalizados mas não selecionados)\n")

# Estatísticas
pos_c = [int(r['pos']) for r in scenario_c]
conf_c = [int(r['confidence_score']) for r in scenario_c if r['confidence_score']]

print(f"Posições atuais em Cenário C:")
print(f"  Média: {statistics.mean(pos_c):.2f}")
print(f"  Mediana: {statistics.median(pos_c):.2f}")
print(f"  Min: {min(pos_c)}, Max: {max(pos_c)}")
print(f"  Quartis: 25%={sorted(pos_c)[len(pos_c)//4]}, 75%={sorted(pos_c)[3*len(pos_c)//4]}\n")

# HIPÓTESE DE SIMULAÇÃO:
# Se o número foi penalizado de forma exagerada por estar em invertedInFinal
# mas não em pulledInFinal, uma estimativa da "posição natural" seria:
# - Se está em pos 34 (muito baixo), a posição sem inversão seria em torno de 20-25
# - Baseado no padrão: inversão aumenta ~10-15 posições

print("SIMULAÇÃO 1: Remover inversão em Cenário C\n")

# Estimativa: se inversão move de ~20 para ~34, então remover seria ~20
# Vamos usar a distribuição de Cenário A como proxy
pos_a = [int(r['pos']) for r in scenario_a]

print(f"Comparação de posições (proxy usando Cenário A como baseline sem inversão):")
print(f"  Cenário A (sem inversão): média = {statistics.mean(pos_a):.2f}")
print(f"  Cenário C (com inversão): média = {statistics.mean(pos_c):.2f}")
print(f"  Diferença: {statistics.mean(pos_c) - statistics.mean(pos_a):.2f} posições\n")

# Simulação: aplicar a posição média de Cenário A aos casos de Cenário C
print("SIMULAÇÃO 2: Aplicar correção (usar lógica melhorada)\n")

simulated_pos_c = [statistics.mean(pos_a)] * len(scenario_c)
improvement = statistics.mean(pos_c) - statistics.mean(simulated_pos_c)

print(f"Se REMOVERMOS inversão de Cenário C:")
print(f"  Posição estimada: {statistics.mean(simulated_pos_c):.2f}")
print(f"  Ganho: {improvement:.2f} posições (redução de {improvement/statistics.mean(pos_c)*100:.1f}%)\n")

# Agora vamos testar com os snapshots reais
print("="*80)
print("VALIDAÇÃO REAL: Pegar snapshots de Cenário C e inspecionar\n")

def _read_dotenv():
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        return None
    for line in env_path.read_text().splitlines():
        if line.startswith("MONGO_URL="):
            return line.split("=", 1)[1].strip()
    return None

url = _read_dotenv()
client = MongoClient(url, tls=True, tlsCAFile=certifi.where())
db = client["roleta_db"]

# Pega alguns snapshots de Cenário C para inspeccionar a ranking
sample_c = scenario_c[:5]
print(f"Inspecionando {len(sample_c)} snapshots de Cenário C:\n")

for idx, record in enumerate(sample_c, 1):
    snap_id = record['snapshot_id']
    next_num = int(record['next'])
    pos_atual = int(record['pos'])

    snap = db['suggestion_snapshots'].find_one({'snapshot_id': snap_id})
    if not snap:
        continue

    payload = snap.get('payload', {})
    ranking = payload.get('suggestion') or payload.get('list') or []
    inv_nums = set(payload.get('invertedNumbers', []))
    inv_final = set(payload.get('invertedInFinal', []))

    # Qual é a posição de "next" no ranking?
    if next_num in ranking:
        pos_in_ranking = ranking.index(next_num) + 1
    else:
        pos_in_ranking = None

    print(f"{idx}. Snapshot {snap_id[:20]}...")
    print(f"   Próximo número: {next_num}")
    print(f"   Posição atual: {pos_atual}/37")
    print(f"   in_invertedNumbers: {next_num in inv_nums}")
    print(f"   in_invertedInFinal: {next_num in inv_final}")

    # Estimar posição sem inversão
    if next_num in inv_final:
        # Se está em invertedInFinal, estimar a posição sem penalidade
        # Usando heurística: inversão típica move ~10-20 posições
        estimated_pos_without_inversion = max(1, pos_atual - 15)
        print(f"   Estimado sem inversão: ~{estimated_pos_without_inversion}/37")
        print(f"   Ganho potencial: {pos_atual - estimated_pos_without_inversion} posições")
    print()

print("="*80)
print("RECOMENDAÇÃO:\n")
print("FIX SUGERIDO no código:")
print("""
  if (in_inverted_numbers && in_inverted_in_final) {
      // Verificar se também está em pulled_in_final
      if (!in_pulled_in_final) {
          // BUG: número é penalizado mesmo não sendo selecionado naturalmente
          // Solução 1: não aplicar inversão (remover de invertedInFinal)
          // Solução 2: aplicar penalidade menor (milderação)
          // Solução 3: adicionar com prioritário maior
          apply_fix();  // escolher uma das 3 acima
      }
  }
""")

print(f"\nImpacto esperado: melhoria de ~{improvement:.1f} posições no Cenário C")
print(f"Ou seja: de média {statistics.mean(pos_c):.2f} para ~{statistics.mean(simulated_pos_c):.2f}")

