"""
Investiga POR QUE o algoritmo aplica invertedInFinal em alguns casos vs outros.

Comparando Cenário A (in_inverted, NOT in_final) vs Cenário C (in_inverted, AND in_final)
"""
from __future__ import annotations

import csv
import statistics
from collections import defaultdict

csv_path = "_validation_results.csv"
data = []
with open(csv_path) as f:
    reader = csv.DictReader(f)
    for row in reader:
        row['pos'] = int(row['pos'])
        row['confidence_score'] = int(row['confidence_score']) if row['confidence_score'] else None
        data.append(row)

# Separa os dois cenários
scenario_a = [r for r in data if r['in_inverted_numbers'] == 'True' and r['in_inverted_in_final'] == 'False']
scenario_c = [r for r in data if r['in_inverted_numbers'] == 'True' and r['in_inverted_in_final'] == 'True']

print(f"Cenário A (in_inverted, NOT in_final): {len(scenario_a)}")
print(f"Cenário C (in_inverted, AND in_final): {len(scenario_c)}\n")

# HIPÓTESE 1: Confidence score
print("="*70)
print("HIPÓTESE 1: Confidence Score diferencia os casos?\n")

conf_a = [r['confidence_score'] for r in scenario_a if r['confidence_score']]
conf_c = [r['confidence_score'] for r in scenario_c if r['confidence_score']]

print(f"Cenário A: mean={statistics.mean(conf_a):.1f}, median={statistics.median(conf_a):.1f}, stdev={statistics.stdev(conf_a):.1f}")
print(f"Cenário C: mean={statistics.mean(conf_c):.1f}, median={statistics.median(conf_c):.1f}, stdev={statistics.stdev(conf_c):.1f}")

# Distribuição por faixa de confiança
print("\nDistribuição por confidence_score:")
for threshold in [60, 65, 70, 75]:
    a_count = sum(1 for r in scenario_a if r['confidence_score'] >= threshold)
    c_count = sum(1 for r in scenario_c if r['confidence_score'] >= threshold)
    print(f"  ≥{threshold}: A={a_count/len(scenario_a)*100:.1f}%, C={c_count/len(scenario_c)*100:.1f}%")

# HIPÓTESE 2: Posição do "next" antes da inversão ser aplicada
# Vamos estimar: se confidence é Alta (71) vs Média (64), talvez o algoritmo
# use a confiança para decidir se inverte. Se confiança é alta no cenário A,
# talvez não inverta porque confia que o número está bem posicionado.

print("\n" + "="*70)
print("HIPÓTESE 2: Relação com confidence_label\n")

for label in ['Alta', 'Média']:
    a_conf = [r for r in scenario_a if r['confidence_label'] == label]
    c_conf = [r for r in scenario_c if r['confidence_label'] == label]

    a_pct = len(a_conf) / len(scenario_a) * 100 if a_conf else 0
    c_pct = len(c_conf) / len(scenario_c) * 100 if c_conf else 0

    print(f"{label:>6}: A={a_pct:>6.1f}% (n={len(a_conf)}), C={c_pct:>6.1f}% (n={len(c_conf)})")

# HIPÓTESE 3: Em_pulled_numbers / em_pulled_in_final
# Talvez quando o número está em pulled_numbers mas NÃO em pulled_in_final,
# o algoritmo o marca para inversão?

print("\n" + "="*70)
print("HIPÓTESE 3: Padrão em pulledNumbers vs pulledInFinal\n")

def analyze_pulled(scenario, name):
    in_pulled = sum(1 for r in scenario if r['in_pulled_numbers'] == 'True')
    in_pulled_final = sum(1 for r in scenario if r['in_pulled_in_final'] == 'True')

    print(f"{name}:")
    print(f"  in_pulled_numbers: {in_pulled/len(scenario)*100:.1f}%")
    print(f"  in_pulled_in_final: {in_pulled_final/len(scenario)*100:.1f}%")

    # Matriz
    both = sum(1 for r in scenario if r['in_pulled_numbers'] == 'True' and r['in_pulled_in_final'] == 'True')
    pulled_not_final = sum(1 for r in scenario if r['in_pulled_numbers'] == 'True' and r['in_pulled_in_final'] == 'False')
    not_pulled_final = sum(1 for r in scenario if r['in_pulled_numbers'] == 'False' and r['in_pulled_in_final'] == 'True')
    neither = sum(1 for r in scenario if r['in_pulled_numbers'] == 'False' and r['in_pulled_in_final'] == 'False')

    total = len(scenario)
    print(f"  both: {both/total*100:.1f}%, pulled_not_final: {pulled_not_final/total*100:.1f}%, not_pulled_final: {not_pulled_final/total*100:.1f}%, neither: {neither/total*100:.1f}%")

analyze_pulled(scenario_a, "Cenário A (NOT penalizado)")
analyze_pulled(scenario_c, "Cenário C (SIM penalizado)")

# HIPÓTESE 4: Distribuição de rankings (pos)
print("\n" + "="*70)
print("HIPÓTESE 4: Onde esses números rankam normalmente?\n")

pos_a = [r['pos'] for r in scenario_a]
pos_c = [r['pos'] for r in scenario_c]

print(f"Cenário A (não penalizado): mean={statistics.mean(pos_a):.1f}, median={statistics.median(pos_a):.1f}")
print(f"  Quartis: 25%={sorted(pos_a)[len(pos_a)//4]}, 50%={sorted(pos_a)[len(pos_a)//2]}, 75%={sorted(pos_a)[3*len(pos_a)//4]}")

print(f"\nCenário C (penalizado): mean={statistics.mean(pos_c):.1f}, median={statistics.median(pos_c):.1f}")
print(f"  Quartis: 25%={sorted(pos_c)[len(pos_c)//4]}, 50%={sorted(pos_c)[len(pos_c)//2]}, 75%={sorted(pos_c)[3*len(pos_c)//4]}")

# INSIGHT: Talvez o algoritmo PENSE que em Cenário C, o número estava muito alto
# (por isso aplica penalidade), mas estava errado.

print("\n" + "="*70)
print("HIPÓTESE 5: Proporção de números quentes (múltiplos em invertedNumbers)\n")

# Conta quantos números tem invertedNumbers != empty
snap_with_inverted = defaultdict(int)
snap_total_inverted = defaultdict(int)

# Precisamos dos snapshots originais
from pymongo import MongoClient
import certifi
from pathlib import Path

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

# Pega alguns snapshots de cada cenário para inspecionar
print("\nExemplos de Cenário A (bom, não penalizado):")
sample_a_ids = [r['snapshot_id'] for r in scenario_a[:3]]
for snap_id in sample_a_ids:
    snap = db['suggestion_snapshots'].find_one({'snapshot_id': snap_id})
    if snap:
        payload = snap.get('payload', {})
        inv_nums = payload.get('invertedNumbers', [])
        inv_final = payload.get('invertedInFinal', [])
        inv_removed = payload.get('invertedRemoved', [])
        print(f"\n  {snap_id[:20]}...")
        print(f"    invertedNumbers: {len(inv_nums)} números → {inv_nums[:6]}...")
        print(f"    invertedInFinal: {len(inv_final)} → {inv_final}")
        print(f"    invertedRemoved: {len(inv_removed)}")

print("\n\nExemplos de Cenário C (ruim, penalizado):")
sample_c_ids = [r['snapshot_id'] for r in scenario_c[:3]]
for snap_id in sample_c_ids:
    snap = db['suggestion_snapshots'].find_one({'snapshot_id': snap_id})
    if snap:
        payload = snap.get('payload', {})
        inv_nums = payload.get('invertedNumbers', [])
        inv_final = payload.get('invertedInFinal', [])
        inv_removed = payload.get('invertedRemoved', [])
        print(f"\n  {snap_id[:20]}...")
        print(f"    invertedNumbers: {len(inv_nums)} números → {inv_nums[:6]}...")
        print(f"    invertedInFinal: {len(inv_final)} → {inv_final}")
        print(f"    invertedRemoved: {len(inv_removed)}")

print("\n" + "="*70)
print("\n📊 PADRÃO ESPERADO:\n")
print("Se o algoritmo usa X critério para decidir se inverte:")
print("  Cenário A deveria ter [padrão X1]")
print("  Cenário C deveria ter [padrão X2, diferente]")
print("\nMas parecem ser MUITO SIMILARES → a decisão é ALEATÓRIA ou BASEADA em algo sutilmente diferente")

