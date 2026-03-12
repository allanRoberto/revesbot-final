import numpy as np
from collections import Counter
from tensorflow.keras.models import load_model

# 🔹 Carregar o modelo treinado
MODEL_PATH = "model_onze_gale_v2.h5"
model = load_model(MODEL_PATH)

# 🔹 Definições auxiliares (iguais às do dataset)
vermelhos = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}

def get_dozen(n):
    if 1 <= n <= 12: return 1
    if 13 <= n <= 24: return 2
    if 25 <= n <= 36: return 3
    return 0

def get_column(n):
    if n == 0: return 0
    if n % 3 == 1: return 1
    if n % 3 == 2: return 2
    return 3

def extrair_features(janela, gatilho, bets, gale_atual=0, max_gales=7):
    """Extrai as MESMAS features do onze_dataset.py"""
    features = []

    # 1) Gale atual normalizado
    features.append(gale_atual / max_gales)

    # 2) Gatilho one-hot
    features.extend([
        1 if gatilho == 11 else 0,
        1 if gatilho == 22 else 0,
        1 if gatilho == 33 else 0
    ])

    # 3) Frequência últimos 50
    ultimos50 = janela[:50]
    contagem50 = Counter(ultimos50)
    freq = [contagem50.get(n, 0) / 50 for n in range(37)]
    features.extend(freq)

    # 4) Par/ímpar últimos 10
    ultimos10 = janela[:10]
    pares = sum(1 for n in ultimos10 if n % 2 == 0) / 10
    features.extend([pares, 1 - pares])

    # 5) Cor últimos 10
    vermelhos10 = sum(1 for n in ultimos10 if n in vermelhos) / 10
    features.extend([vermelhos10, 1 - vermelhos10])

    # 6) Dúzia últimos 10
    dezenas = [get_dozen(n) for n in ultimos10 if n > 0]
    for d in [1, 2, 3]:
        features.append(dezenas.count(d) / 10)

    # 7) Coluna últimos 10
    colunas = [get_column(n) for n in ultimos10 if n > 0]
    for c in [1, 2, 3]:
        features.append(colunas.count(c) / 10)

    # 8) Distância média até os alvos (últimos 10)
    distancias = []
    for n in ultimos10:
        distancias.append(min(abs(n - b) for b in bets))
    features.append(np.mean(distancias) if distancias else 0)

    # 9) Tempo desde o último gatilho (normalizado em 100 spins)
    spins_desde_gatilho = next((idx for idx, n in enumerate(janela) if n in [11,22,33]), len(janela))
    features.append(spins_desde_gatilho / 100)

    # 10) Hot numbers últimos 100 (one-hot dos top 5)
    ultimos100 = janela[:100]
    contagem100 = Counter(ultimos100)
    top5 = [n for n,_ in contagem100.most_common(5)]
    features.extend([1 if n in top5 else 0 for n in range(37)])

    return np.array(features, dtype=np.float32)


def prever_gale(numbers):
    """
    Recebe o histórico (mais recente primeiro).
    Retorna spins_required baseado na predição do modelo.
    """
    if len(numbers) < 100:
        return {"success": False, "error": "Histórico insuficiente (min 100 números)"}

    gatilho = numbers[0]
    bets = [0, 11, 22, 33, 16, 1, 18, 9, 36, 30]  # mesmo do onze.py

    # Extrair features (90 colunas)
    features = extrair_features(numbers, gatilho, bets)
    X = features.reshape(1, -1)  # (1, 90)

    # Predição
    probs = model.predict(X, verbose=0)[0]
    classe = int(np.argmax(probs))  # faixa predita (0-6 se 7 faixas)

    # spins_required = gale predito
    return {
        "success": True,
        "classe": classe,
        "spins_required": classe,   # esperar essa quantidade de gales
        "probabilidades": probs.tolist()
    }
