#!/usr/bin/env python3
"""Script para buscar os últimos 1000 números de uma roleta do MongoDB"""

import os
import json
from dotenv import load_dotenv
from pymongo import MongoClient
import certifi

load_dotenv()

# Configuração de conexão
MONGO_URL = os.getenv("MONGO_URL", "mongodb+srv://revesbot:DlBnGmlimRZpIblr@cluster0.c14fnit.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0")
DB_NAME = os.getenv("MONGO_DB", "roleta_db")
ROULETTE_SLUG = "pragmatic-auto-roulette"

print(f"Conectando ao MongoDB...")

mongo_client = MongoClient(MONGO_URL, tls=True, tlsCAFile=certifi.where())
mongo_db = mongo_client[DB_NAME]

# Pegar a collection de histórico
history_collection = mongo_db["history"]

# Buscar os últimos 1000 números da roleta
print(f"Buscando últimos 1000 números da roleta: {ROULETTE_SLUG}")

numbers = list(
    history_collection.find(
        {"roulette_id": ROULETTE_SLUG},
        {"value": 1, "timestamp": 1, "roulette_id": 1, "_id": 0}
    )
    .sort("timestamp", -1)
    .limit(1000)
)

# Reverter para ordem cronológica (mais antigos primeiro)
numbers.reverse()

print(f"Total de números encontrados: {len(numbers)}")

# Separar em dois grupos de 500
first_500 = numbers[:500]
next_500 = numbers[500:1000]

print(f"Primeiros 500: de {first_500[0]['timestamp']} até {first_500[-1]['timestamp']}")
print(f"Próximos 500: de {next_500[0]['timestamp']} até {next_500[-1]['timestamp']}")

# Extrair apenas os valores
first_500_values = [num['value'] for num in first_500]
next_500_values = [num['value'] for num in next_500]

# Salvar ambos os conjuntos
with open("pragmatic_auto_roulette_first_500.json", "w") as f:
    json.dump(first_500, f, indent=2, default=str)
    print("\n✅ Primeiros 500 salvos em: pragmatic_auto_roulette_first_500.json")

with open("pragmatic_auto_roulette_next_500.json", "w") as f:
    json.dump(next_500, f, indent=2, default=str)
    print("✅ Próximos 500 salvos em: pragmatic_auto_roulette_next_500.json")

# Fazer ranking rápido dos próximos 500
print("\n" + "="*80)
print("RANKING DOS PRÓXIMOS 500 NÚMEROS")
print("="*80 + "\n")

frequency_next = {}
for num in range(37):
    frequency_next[num] = next_500_values.count(num)

ranked_next = sorted(frequency_next.items(), key=lambda x: x[1], reverse=True)

print(f"{'Rank':<6} {'Número':<10} {'Saídas':<15} {'%':<10}")
print("-" * 80)

for rank, (num, count) in enumerate(ranked_next[:15], 1):
    percentage = (count / len(next_500_values)) * 100
    bar = "█" * int(count / 1.5)
    print(f"{rank:<6} {num:<10} {count:<15} {percentage:>6.2f}% {bar}")

mongo_client.close()
