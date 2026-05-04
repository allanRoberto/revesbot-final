#!/usr/bin/env python3
"""Script para buscar os últimos 500 números de uma roleta do MongoDB"""

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

# Conectar ao MongoDB
print(f"Conectando ao MongoDB: {MONGO_URL.split('@')[0]}***")
print(f"Database: {DB_NAME}")

mongo_client = MongoClient(MONGO_URL, tls=True, tlsCAFile=certifi.where())
mongo_db = mongo_client[DB_NAME]

# Pegar a collection de histórico
history_collection = mongo_db["history"]

# Buscar os últimos 500 números da roleta
print(f"\nBuscando últimos 500 números da roleta: {ROULETTE_SLUG}")

numbers = list(
    history_collection.find(
        {"roulette_id": ROULETTE_SLUG},
        {"value": 1, "timestamp": 1, "roulette_id": 1, "_id": 0}
    )
    .sort("timestamp", -1)
    .limit(500)
)

# Reverter para ordem cronológica (mais antigos primeiro)
numbers.reverse()

print(f"Total de números encontrados: {len(numbers)}")
print("\n" + "="*80)
print(f"Primeiros 10 números:")
for i, num in enumerate(numbers[:10], 1):
    print(f"{i}. Valor: {num['value']:2d} | Timestamp: {num['timestamp']}")

print(f"\n...últimos 10 números:")
for i, num in enumerate(numbers[-10:], len(numbers)-9):
    print(f"{i}. Valor: {num['value']:2d} | Timestamp: {num['timestamp']}")

# Salvar em JSON para análise posterior
output_file = f"pragmatic_auto_roulette_500_numbers.json"
with open(output_file, "w") as f:
    json.dump(numbers, f, indent=2, default=str)
print(f"\n✅ Dados salvos em: {output_file}")

# Extrair apenas os valores em uma lista
values_only = [num['value'] for num in numbers]
print(f"\nSequência de valores: {values_only}")
print(f"Total: {len(values_only)} números")

mongo_client.close()
