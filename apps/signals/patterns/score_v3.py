from collections import defaultdict, Counter
import asyncio
import math

from core.api import RouletteAPI


from score_v4 import RouletteAnalyzer


import requests
import json

BET_API_URL = "http://localhost:3000/api/bet"


def perguntar_e_enviar_bet(bets, attempts, roulette_url, gales):
    resposta = input("Deseja enviar a aposta para a API? (s/n): ").strip().lower()

    if resposta != "s":
        print("❌ Aposta não enviada.")
        return

    payload = {
        "bets": bets,
        "attempts": attempts,
        "roulette_url": roulette_url,
        "gales": gales
    }

    print("📡 Enviando aposta...")

    try:
        resp = requests.post(
            BET_API_URL,
            headers={"Content-Type": "application/json"},
            data=json.dumps(payload),
            timeout=10000
        )

        print("✅ Resposta da API:")
        print(f"Status: {resp.status_code}")

        try:
            print(resp.json())
        except Exception:
            print(resp.text)

    except requests.exceptions.RequestException as e:
        print("❌ Erro ao enviar aposta:")
        print(e)


# ============================
# ORDEM DA ROLETA
# ============================

ROULETTE = [
    0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8,
    23, 10, 5, 24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28,
    12, 35, 3, 26
]

NEIGHBORS = {
    n: (
        ROULETTE[(i - 1) % len(ROULETTE)],
        ROULETTE[(i + 1) % len(ROULETTE)]
    )
    for i, n in enumerate(ROULETTE)
}

# Índice de posição na roleta para cálculos de distância
ROULETTE_INDEX = {n: i for i, n in enumerate(ROULETTE)}


# ============================
# CORE DO SCORE (INALTERADO)
# ============================

def extract_windows(history, base, window_size=5):
    """
    Extrai janelas DEPOIS do base cronologicamente (números que saíram após o base)
    
    history[0] = número mais recente
    history[n] = número mais antigo
    
    Se base está na posição i, os números que saíram DEPOIS estão em history[0:i]
    (mais recentes que o base)
    """
    windows = []

    for i, n in enumerate(history):
        if n != base:
            continue

        # Números que saíram DEPOIS do base (posições menores = mais recentes)
        start = max(0, i - window_size)
        end = i

        if end - start >= 1:  # Precisa ter pelo menos 1 número
            # Inverte para que o primeiro após o base venha primeiro
            window = history[start:end][::-1]
            windows.append(window)

    return windows


def extract_windows_before(history, base, window_size=5, min_size=1):
    """
    Extrai janelas ANTES do base cronologicamente (números que saíram antes do base)
    Esses números tendem a "pular pra frente" na próxima ocorrência
    
    history[0] = número mais recente
    history[n] = número mais antigo
    
    Se base está na posição i, os números que saíram ANTES estão em history[i+1:]
    (mais antigos que o base)
    
    Retorna na ordem: [mais próximo do base cronologicamente, ..., mais distante]
    
    Args:
        min_size: tamanho mínimo da janela (default=1 para não perder dados)
    """
    windows = []

    for i, n in enumerate(history):
        if n != base:
            continue

        # Números que saíram ANTES do base (posições maiores = mais antigos)
        start = i + 1
        end = min(start + window_size, len(history))

        if end - start >= min_size:
            window = history[start:end]
            windows.append(window)

    return windows


def compute_score(windows_after, windows_before=None, neighbor_weight=0.5, position_decay=0.7, before_weight=0.8):
    """
    Calcula score com:
    - Peso temporal (janelas mais recentes valem mais)
    - Peso posicional (números que saíram primeiro após o base valem mais)
    - Números que vieram ANTES do base (tendem a pular pra frente)
    
    Args:
        windows_after: janelas de números DEPOIS do base
        windows_before: janelas de números ANTES do base
        neighbor_weight: peso dos vizinhos (0.5 = 50% do peso do número)
        position_decay: fator de decaimento por posição na janela
        before_weight: peso base para números que vieram antes (0.8 = 80% do peso normal)
                       
    Exemplo com position_decay=0.7 e janela de 5:
        posição 0 (primeiro após base): peso = 1.0
        posição 1: peso = 0.7
        posição 2: peso = 0.49
        posição 3: peso = 0.34
        posição 4: peso = 0.24
    """
    score = defaultdict(float)

    # === SCORE DOS NÚMEROS QUE VIERAM DEPOIS DO BASE ===
    for idx, window in enumerate(windows_after):
        temporal_weight = idx + 1

        for pos, n in enumerate(window):
            position_weight = position_decay ** pos
            final_weight = temporal_weight * position_weight

            score[n] += final_weight

            for neighbor in NEIGHBORS[n]:
                score[neighbor] += final_weight * neighbor_weight

    # === SCORE DOS NÚMEROS QUE VIERAM ANTES DO BASE ===
    # Esses números tendem a "pular pra frente" na próxima ocorrência
    if windows_before:
        for idx, window in enumerate(windows_before):
            temporal_weight = idx + 1
            
            for pos, n in enumerate(window):
                # Números mais próximos do base (antes) têm mais chance de pular
                position_weight = position_decay ** pos
                final_weight = temporal_weight * position_weight * before_weight

                score[n] += final_weight

                # Vizinhos também podem "representar" o número original
                for neighbor in NEIGHBORS[n]:
                    score[neighbor] += final_weight * neighbor_weight

    return score


def rank_scores(score, top_n=18):
    return sorted(score.items(), key=lambda x: x[1], reverse=True)[:top_n]


# ============================
# SISTEMA DE CONFIANÇA AVANÇADO
# ============================

class ConfidenceAnalyzer:
    """
    Analisa múltiplos fatores para gerar um nível de confiança mais preciso
    """
    
    def __init__(self, history, ranking, base_number):
        self.history = history
        self.ranking = ranking
        self.base_number = base_number
        self.top_numbers = [n for n, _ in ranking]
        self.top_scores = [s for _, s in ranking]
        
    def analyze(self):
        """
        Retorna análise completa com score de confiança final
        """
        metrics = {
            "frequencia_recente": self._frequencia_recente(),
            "taxa_acerto_historico": self._taxa_acerto_historico(),
            "temperatura": self._analise_temperatura(),
            "dispersao_score": self._dispersao_score(),
            "cobertura_vizinhos": self._cobertura_vizinhos(),
            "consistencia_temporal": self._consistencia_temporal(),
        }
        
        # Pesos para cada métrica (ajustáveis)
        pesos = {
            "frequencia_recente": 0.15,
            "taxa_acerto_historico": 0.25,
            "temperatura": 0.15,
            "dispersao_score": 0.15,
            "cobertura_vizinhos": 0.10,
            "consistencia_temporal": 0.20,
        }
        
        # Score final ponderado (0-100)
        score_final = sum(
            metrics[k]["score"] * pesos[k] 
            for k in pesos
        )
        
        return {
            "score_final": round(score_final, 1),
            "nivel": self._classificar_nivel(score_final),
            "metricas": metrics,
            "recomendacao": self._gerar_recomendacao(score_final, metrics)
        }
    
    def _frequencia_recente(self, janela=50):
        """
        Analisa com que frequência os números sugeridos apareceram recentemente
        """
        recentes = self.history[:janela]
        contador = Counter(recentes)
        
        # Frequência esperada: janela / 37 números
        freq_esperada = janela / 37
        
        # Quantos dos top números estão acima da frequência esperada
        acima_esperado = sum(
            1 for n in self.top_numbers 
            if contador.get(n, 0) > freq_esperada
        )
        
        # Frequência média dos top números
        freq_media = sum(contador.get(n, 0) for n in self.top_numbers) / len(self.top_numbers)
        
        # Score: baseado na proporção acima do esperado
        score = min(100, (acima_esperado / len(self.top_numbers)) * 100 + 
                    (freq_media / freq_esperada - 1) * 20)
        score = max(0, score)
        
        return {
            "score": round(score, 1),
            "acima_esperado": acima_esperado,
            "total_analisados": len(self.top_numbers),
            "freq_media": round(freq_media, 2),
            "freq_esperada": round(freq_esperada, 2)
        }
    
    def _taxa_acerto_historico(self):
        """
        Simula: se tivéssemos apostado nos top números nas últimas N ocorrências
        do base_number, quantas vezes teríamos acertado?
        """
        history_reversed = self.history[::-1]
        acertos = 0
        tentativas = 0
        acertos_por_gale = {1: 0, 2: 0, 3: 0}  # Acertos em cada tentativa
        
        for i, n in enumerate(history_reversed):
            if n != self.base_number:
                continue
            
            # Pega os próximos 3 números (simulando 3 gales)
            proximos = history_reversed[i+1:i+4]
            
            if len(proximos) < 3:
                continue
                
            tentativas += 1
            
            for gale_idx, numero_saiu in enumerate(proximos, 1):
                if numero_saiu in self.top_numbers:
                    acertos += 1
                    acertos_por_gale[gale_idx] += 1
                    break
        
        if tentativas == 0:
            return {"score": 50, "taxa": 0, "tentativas": 0, "acertos": 0, "por_gale": {}}
        
        taxa = acertos / tentativas
        
        # Score baseado na taxa de acerto (expectativa ~48% com 18 números em 3 gales)
        # 48% = neutro (50 pontos), acima = bom, abaixo = ruim
        score = 50 + (taxa - 0.48) * 150
        score = max(0, min(100, score))
        
        return {
            "score": round(score, 1),
            "taxa": round(taxa * 100, 1),
            "tentativas": tentativas,
            "acertos": acertos,
            "por_gale": acertos_por_gale
        }
    
    def _analise_temperatura(self, janela_quente=30, janela_fria=100):
        """
        Analisa se os números sugeridos estão quentes ou frios
        Números muito frios podem ser oportunidade ou armadilha
        """
        recentes = self.history[:janela_quente]
        historico = self.history[:janela_fria]
        
        contador_recente = Counter(recentes)
        contador_historico = Counter(historico)
        
        temperaturas = []
        
        for n in self.top_numbers:
            freq_recente = contador_recente.get(n, 0)
            freq_historico = contador_historico.get(n, 0)
            
            # Normaliza para comparação
            norm_recente = freq_recente / janela_quente
            norm_historico = freq_historico / janela_fria
            
            if norm_historico > 0:
                temp = norm_recente / norm_historico
            else:
                temp = 0.5 if freq_recente == 0 else 2.0
            
            temperaturas.append(temp)
        
        # Média de temperatura (1.0 = neutro, >1 = quente, <1 = frio)
        temp_media = sum(temperaturas) / len(temperaturas) if temperaturas else 1.0
        
        # Preferimos números levemente quentes (1.0-1.5)
        # Muito quentes (>2) ou muito frios (<0.5) são menos confiáveis
        if 0.8 <= temp_media <= 1.5:
            score = 80 + (1.0 - abs(temp_media - 1.15)) * 40
        elif temp_media > 1.5:
            score = 60 - (temp_media - 1.5) * 20
        else:
            score = 60 - (0.8 - temp_media) * 40
        
        score = max(0, min(100, score))
        
        # Conta quantos estão em cada faixa
        quentes = sum(1 for t in temperaturas if t > 1.2)
        frios = sum(1 for t in temperaturas if t < 0.8)
        neutros = len(temperaturas) - quentes - frios
        
        return {
            "score": round(score, 1),
            "temp_media": round(temp_media, 2),
            "quentes": quentes,
            "frios": frios,
            "neutros": neutros
        }
    
    def _dispersao_score(self):
        """
        Analisa a dispersão dos scores
        Scores muito concentrados no topo = mais confiança
        """
        if len(self.top_scores) < 2:
            return {"score": 50, "desvio_padrao": 0, "coef_variacao": 0}
        
        media = sum(self.top_scores) / len(self.top_scores)
        
        if media == 0:
            return {"score": 50, "desvio_padrao": 0, "coef_variacao": 0}
        
        variancia = sum((s - media) ** 2 for s in self.top_scores) / len(self.top_scores)
        desvio = math.sqrt(variancia)
        
        # Coeficiente de variação
        cv = desvio / media
        
        # Razão entre primeiro e último score
        razao_top = self.top_scores[0] / self.top_scores[-1] if self.top_scores[-1] > 0 else 1
        
        # Alta dispersão (CV alto) com razão alta = bom (destaques claros)
        # Baixa dispersão = todos parecidos = menos confiança
        if razao_top > 2 and cv > 0.3:
            score = 70 + min(30, razao_top * 5)
        elif razao_top > 1.5:
            score = 60 + razao_top * 5
        else:
            score = 40 + cv * 30
        
        score = max(0, min(100, score))
        
        return {
            "score": round(score, 1),
            "desvio_padrao": round(desvio, 2),
            "coef_variacao": round(cv, 2),
            "razao_top_bottom": round(razao_top, 2)
        }
    
    def _cobertura_vizinhos(self):
        """
        Analisa quantos dos top números são vizinhos entre si
        Alta cobertura de vizinhos = aposta mais segura (setor da roleta)
        """
        vizinhos_cobertos = 0
        pares_vizinhos = 0
        
        for n in self.top_numbers:
            esq, dir = NEIGHBORS[n]
            if esq in self.top_numbers:
                vizinhos_cobertos += 1
                pares_vizinhos += 1
            if dir in self.top_numbers:
                vizinhos_cobertos += 1
        
        # Evita contar duas vezes
        pares_vizinhos = pares_vizinhos // 2
        
        # Porcentagem de números que têm pelo menos um vizinho coberto
        cobertura = vizinhos_cobertos / (len(self.top_numbers) * 2)
        
        # Boa cobertura = 30-60% (cobre setores mas não é aleatório)
        if 0.25 <= cobertura <= 0.6:
            score = 70 + (0.4 - abs(cobertura - 0.4)) * 75
        else:
            score = 50 + cobertura * 30
        
        score = max(0, min(100, score))
        
        return {
            "score": round(score, 1),
            "cobertura": round(cobertura * 100, 1),
            "pares_vizinhos": pares_vizinhos
        }
    
    def _consistencia_temporal(self):
        """
        Analisa se o padrão é consistente ao longo do tempo
        Divide o histórico em partes e verifica se os mesmos números aparecem
        """
        # Divide histórico em 3 partes
        tamanho_parte = len(self.history) // 3
        partes = [
            self.history[:tamanho_parte],
            self.history[tamanho_parte:tamanho_parte*2],
            self.history[tamanho_parte*2:]
        ]
        
        # Para cada parte, calcula os top números
        rankings_por_parte = []
        
        for parte in partes:
            windows_after = extract_windows(parte, self.base_number, window_size=5)
            windows_before = extract_windows_before(parte, self.base_number, window_size=5)
            if windows_after or windows_before:
                score = compute_score(windows_after, windows_before)
                ranking = rank_scores(score, len(self.top_numbers))
                rankings_por_parte.append(set(n for n, _ in ranking))
            else:
                rankings_por_parte.append(set())
        
        # Calcula interseção entre as partes
        intersecao_total = set()
        if all(rankings_por_parte):
            intersecao_total = rankings_por_parte[0] & rankings_por_parte[1] & rankings_por_parte[2]
            intersecao_pares = (
                len(rankings_por_parte[0] & rankings_por_parte[1]) +
                len(rankings_por_parte[1] & rankings_por_parte[2]) +
                len(rankings_por_parte[0] & rankings_por_parte[2])
            ) / 3
            
            consistencia = len(intersecao_total) / len(self.top_numbers)
            consistencia_pares = intersecao_pares / len(self.top_numbers)
            
            score = consistencia * 60 + consistencia_pares * 40
        else:
            consistencia = 0
            score = 30  # Dados insuficientes
        
        return {
            "score": round(score, 1),
            "consistencia_total": round(consistencia * 100, 1),
            "numeros_consistentes": len(intersecao_total) if all(rankings_por_parte) else 0
        }
    
    def _classificar_nivel(self, score):
        """
        Classifica o nível de confiança
        """
        if score >= 80:
            return "🟢 ALTO"
        elif score >= 65:
            return "🟡 MÉDIO-ALTO"
        elif score >= 50:
            return "🟠 MÉDIO"
        elif score >= 35:
            return "🔴 MÉDIO-BAIXO"
        else:
            return "⚫ BAIXO"
    
    def _gerar_recomendacao(self, score, metrics):
        """
        Gera recomendação baseada na análise
        """
        alertas = []
        pontos_fortes = []
        
        # Analisa cada métrica
        if metrics["taxa_acerto_historico"]["score"] < 40:
            alertas.append("⚠️ Taxa de acerto histórico baixa")
        elif metrics["taxa_acerto_historico"]["score"] > 70:
            pontos_fortes.append("✅ Bom histórico de acertos")
        
        if metrics["temperatura"]["temp_media"] > 1.8:
            alertas.append("⚠️ Números muito quentes (possível reversão)")
        elif metrics["temperatura"]["temp_media"] < 0.6:
            alertas.append("⚠️ Números muito frios")
        
        if metrics["dispersao_score"]["razao_top_bottom"] < 1.3:
            alertas.append("⚠️ Scores muito próximos (pouca diferenciação)")
        elif metrics["dispersao_score"]["razao_top_bottom"] > 2:
            pontos_fortes.append("✅ Destaques claros no ranking")
        
        if metrics["consistencia_temporal"]["score"] > 60:
            pontos_fortes.append("✅ Padrão consistente no tempo")
        elif metrics["consistencia_temporal"]["score"] < 30:
            alertas.append("⚠️ Padrão inconsistente")
        
        # Recomendação final
        if score >= 70 and len(alertas) == 0:
            rec = "🎯 APOSTAR - Condições favoráveis"
        elif score >= 55 and len(alertas) <= 1:
            rec = "🎲 APOSTAR COM CAUTELA - Condições moderadas"
        elif score >= 40:
            rec = "⏸️ AGUARDAR - Condições não ideais"
        else:
            rec = "❌ NÃO APOSTAR - Condições desfavoráveis"
        
        return {
            "acao": rec,
            "alertas": alertas,
            "pontos_fortes": pontos_fortes
        }


def nivel_confianca_avancado(history, ranking, base_number):
    """
    Interface principal para o sistema de confiança avançado
    """
    analyzer = ConfidenceAnalyzer(history, ranking, base_number)
    return analyzer.analyze()


# Mantém a função antiga para compatibilidade
def nivel_confianca(top_scores):
    return round(sum(top_scores), 2)


def get_ranking(history, base_number, window_size=5, top_n=18, before_weight=0.8):
    windows_after = extract_windows(history, base_number, window_size)
    windows_before = extract_windows_before(history, base_number, window_size)
    
    score = compute_score(
        windows_after=windows_after,
        windows_before=windows_before,
        before_weight=before_weight
    )
    ranking = rank_scores(score, top_n)

    top_scores = [s for _, s in ranking]
    confianca_simples = nivel_confianca(top_scores)

    return ranking, confianca_simples


# ============================
# INTEGRAÇÃO COM API
# ============================

async def fetch_numbers_from_api(api, slug, num_results=300):
    resp = await api.api(slug, num_results)

    if not resp or "results" not in resp:
        return []

    return [
        r["value"] if isinstance(r, dict) else r
        for r in resp["results"]
    ]


# ============================
# DISPLAY
# ============================

def print_analise_confianca(analise):
    """
    Exibe a análise de confiança de forma formatada
    """
    print("\n" + "=" * 50)
    print("📊 ANÁLISE DE CONFIANÇA AVANÇADA")
    print("=" * 50)
    
    print(f"\n🎯 SCORE FINAL: {analise['score_final']}/100 {analise['nivel']}")
    
    print(f"\n📋 RECOMENDAÇÃO: {analise['recomendacao']['acao']}")
    
    if analise['recomendacao']['pontos_fortes']:
        print("\n💪 Pontos Fortes:")
        for pf in analise['recomendacao']['pontos_fortes']:
            print(f"   {pf}")
    
    if analise['recomendacao']['alertas']:
        print("\n⚠️ Alertas:")
        for alerta in analise['recomendacao']['alertas']:
            print(f"   {alerta}")
    
    print("\n" + "-" * 50)
    print("📈 MÉTRICAS DETALHADAS:")
    print("-" * 50)
    
    m = analise['metricas']
    
    print(f"\n1️⃣ Frequência Recente: {m['frequencia_recente']['score']}/100")
    print(f"   → {m['frequencia_recente']['acima_esperado']}/{m['frequencia_recente']['total_analisados']} números acima do esperado")
    print(f"   → Freq. média: {m['frequencia_recente']['freq_media']} (esperado: {m['frequencia_recente']['freq_esperada']})")
    
    print(f"\n2️⃣ Taxa de Acerto Histórico: {m['taxa_acerto_historico']['score']}/100")
    print(f"   → {m['taxa_acerto_historico']['acertos']}/{m['taxa_acerto_historico']['tentativas']} acertos ({m['taxa_acerto_historico']['taxa']}%)")
    if m['taxa_acerto_historico']['por_gale']:
        print(f"   → Por gale: 1º={m['taxa_acerto_historico']['por_gale'].get(1,0)}, 2º={m['taxa_acerto_historico']['por_gale'].get(2,0)}, 3º={m['taxa_acerto_historico']['por_gale'].get(3,0)}")
    
    print(f"\n3️⃣ Temperatura: {m['temperatura']['score']}/100")
    print(f"   → Média: {m['temperatura']['temp_media']} (1.0 = neutro)")
    print(f"   → Quentes: {m['temperatura']['quentes']}, Frios: {m['temperatura']['frios']}, Neutros: {m['temperatura']['neutros']}")
    
    print(f"\n4️⃣ Dispersão do Score: {m['dispersao_score']['score']}/100")
    print(f"   → Razão top/bottom: {m['dispersao_score']['razao_top_bottom']}x")
    print(f"   → Coef. variação: {m['dispersao_score']['coef_variacao']}")
    
    print(f"\n5️⃣ Cobertura de Vizinhos: {m['cobertura_vizinhos']['score']}/100")
    print(f"   → {m['cobertura_vizinhos']['cobertura']}% de cobertura")
    print(f"   → {m['cobertura_vizinhos']['pares_vizinhos']} pares de vizinhos")
    
    print(f"\n6️⃣ Consistência Temporal: {m['consistencia_temporal']['score']}/100")
    print(f"   → {m['consistencia_temporal']['numeros_consistentes']} números consistentes nas 3 partes do histórico")
    
    print("\n" + "=" * 50)


# ============================
# EXECUÇÃO PRINCIPAL
# ============================

async def main():
    api = RouletteAPI()

    slug = "pragmatic-brazilian-roulette"
    num_results = 300

    numbers = await fetch_numbers_from_api(api, slug, num_results)

    if len(numbers) < 200:
        print("Histórico insuficiente")
        return

    base_number = numbers[0]

    ranking, confianca_simples = get_ranking(
        history=numbers,
        base_number=base_number,
        window_size=5,
        top_n=26
    )

    analyzer = RouletteAnalyzer(numbers)
    
    # Último número que saiu
    base = numbers[0]

    
    
    print("=" * 60)
    print(f"🎯 ANÁLISE DO BASE: {base}")
    print("=" * 60)
    
    # Análise detalhada

    numeros, confianca = analyzer.prever(base, 26)

    previsao = numeros
    bet = sorted(previsao)


    print("\n" + "=" * 60)
    print(f"🎰 TOP {len(bet)} NÚMEROS PARA APOSTAR:")
    print("=" * 60)
    
    print(f"\n📋 LISTA: {sorted(previsao)}")

    print("\n" + "=" * 60)
    print(f"🎰 CONFIANCA {confianca}")
    print("=" * 60)
    # Só pergunta se a recomendação for favorável
    perguntar_e_enviar_bet(
        bets=bet,
        attempts=1,
        roulette_url="https://lotogreen.bet.br/play/450",
        gales=1
    )
   


if __name__ == "__main__":
    asyncio.run(main())