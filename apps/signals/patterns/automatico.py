"""
🎰 SISTEMA DE APOSTAS AUTOMATIZADO v1.0
Integrado com Analisador de Padrões v4

Features:
- Análise automática de padrões (números que se puxam)
- Filtro por nível de confiança
- Gerenciamento de banca com multiplicação progressiva
- Opção de esperar confirmação (green) antes de entrar
"""

import asyncio
import json
import requests
import aiohttp
import redis.asyncio as redis
from typing import List, Dict, Set, Optional, Tuple
from collections import Counter
from dataclasses import dataclass

# ============================
# CONFIGURAÇÕES
# ============================

BET_API_URL = "http://localhost:3000/api/bet"
REDIS_URL = "redis://:09T6iVOEmt7p0lEEXiRZATotvS70fPzK@45.179.88.134:6379"
RESULT_CHANNEL = "new_result"

# ============================
# ANALISADOR DE PADRÕES (v4 integrado)
# ============================

ROULETTE = [0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23, 10, 5, 24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26]
ROULETTE_INDEX = {n: i for i, n in enumerate(ROULETTE)}

ESPELHOS = {
    1: 10, 10: 1, 2: 20, 20: 2, 3: 30, 30: 3,
    6: 9, 9: 6, 12: 21, 21: 12, 13: 31, 31: 13,
    16: 19, 19: 16, 23: 32, 32: 23, 26: 29, 29: 26
}

def build_groups() -> Dict[str, Set[int]]:
    groups = {}
    groups["Dúzia 1"] = set(range(1, 13))
    groups["Dúzia 2"] = set(range(13, 25))
    groups["Dúzia 3"] = set(range(25, 37))
    groups["Coluna 1"] = {1, 4, 7, 10, 13, 16, 19, 22, 25, 28, 31, 34}
    groups["Coluna 2"] = {2, 5, 8, 11, 14, 17, 20, 23, 26, 29, 32, 35}
    groups["Coluna 3"] = {3, 6, 9, 12, 15, 18, 21, 24, 27, 30, 33, 36}
    groups["Tiers"] = {27, 13, 36, 11, 30, 8, 23, 10, 5, 24, 16, 33}
    groups["Orphelins"] = {1, 20, 14, 31, 9, 17, 34, 6}
    groups["Voisins"] = {22, 18, 29, 7, 28, 12, 35, 3, 26, 0, 32, 15, 19, 4, 21, 2, 25}
    red = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}
    black = {2, 4, 6, 8, 10, 11, 13, 15, 17, 20, 22, 24, 26, 28, 29, 31, 33, 35}
    groups["Vermelhos"] = red
    groups["Pretos"] = black
    groups["Baixos"] = set(range(1, 19))
    groups["Altos"] = set(range(19, 37))
    groups["Pares"] = {n for n in range(1, 37) if n % 2 == 0}
    groups["Ímpares"] = {n for n in range(1, 37) if n % 2 == 1}
    groups["Vermelhos Baixos"] = red & set(range(1, 19))
    groups["Vermelhos Altos"] = red & set(range(19, 37))
    groups["Pretos Baixos"] = black & set(range(1, 19))
    groups["Pretos Altos"] = black & set(range(19, 37))
    return groups

GROUPS = build_groups()


class RouletteAnalyzer:
    """Analisador de padrões simplificado para uso em tempo real"""
    
    def __init__(self):
        self.sequencia: List[int] = []
        self.peso_depois = 3.0
        self.peso_antes = 2.0
        self.peso_vizinho_1 = 1.5
        self.peso_vizinho_2 = 0.5
        self.peso_espelho = 2.0
        self.peso_sequencia = 1.0
        self.peso_posicao = [1.0, 0.85, 0.70, 0.55, 0.40]
        self.max_ocorrencias = 3
        self.janela_depois = 5
        self.janela_antes = 3
        self.groups = GROUPS
    
    def set_sequencia(self, sequencia: List[int]):
        print(sequencia, "HISTORICO")
        self.sequencia = sequencia
    
    def adicionar_numero(self, numero: int):
        self.sequencia.insert(0, numero)
        if len(self.sequencia) > 500:
            self.sequencia.pop()
    
    @staticmethod
    def get_vizinhos(n: int, distancia: int = 2) -> List[int]:
        if n not in ROULETTE_INDEX:
            return []
        idx = ROULETTE_INDEX[n]
        vizinhos = []
        for d in range(1, distancia + 1):
            vizinhos.append(ROULETTE[(idx - d) % 37])
            vizinhos.append(ROULETTE[(idx + d) % 37])
        return vizinhos
    
    @staticmethod
    def get_espelho(n: int) -> Optional[int]:
        return ESPELHOS.get(n, None)
    
    @staticmethod
    def get_sequencia_numerica(n: int) -> List[int]:
        return [x for x in [n-2, n-1, n+1, n+2] if 0 <= x <= 36]
    
    def encontrar_ocorrencias(self, base: int) -> List[int]:

        print(len(self.sequencia), "Sequencia em memória")
        return [i for i, n in enumerate(self.sequencia) if n == base]
    
    def extrair_numeros_depois(self, ocorrencias: List[int]) -> List[List[int]]:
        numeros_depois = []
        for pos in ocorrencias[1:self.max_ocorrencias + 1]:
            depois = self.sequencia[max(0, pos - self.janela_depois):pos][::-1]
            if depois:
                numeros_depois.append(depois[:self.janela_depois])
        return numeros_depois
    
    def extrair_numeros_antes(self, ocorrencias: List[int]) -> List[List[int]]:
        numeros_antes = []
        for pos in ocorrencias[1:self.max_ocorrencias + 1]:
            antes = self.sequencia[pos + 1:pos + 1 + self.janela_antes]
            if antes:
                numeros_antes.append(antes)
        return numeros_antes
    
    def analisar_grupos_gatilho(self, base: int, janela: int = 130) -> List[Dict]:
        W = self.sequencia[:janela]
        if len(W) < 50:
            return []
        
        group_score = {name: 0 for name in self.groups}
        group_triggers = {name: {} for name in self.groups}
        
        num_to_groups = {n: [] for n in range(37)}
        for g, nums in self.groups.items():
            for n in nums:
                if 0 <= n <= 36:
                    num_to_groups[n].append(g)
        
        def prox_weight(k):
            return 3 if k == 1 else 2 if k == 2 else 1
        
        for i in range(len(W) - 3):
            x = W[i]
            if x != base:
                continue
            
            for k in (1, 2, 3):
                if i + k >= len(W):
                    break
                y = W[i + k]
                if not (0 <= y <= 36):
                    continue
                
                pw = prox_weight(k)
                y_groups = num_to_groups.get(y, [])
                
                for g in y_groups:
                    group_score[g] += 2 * pw
                    trig = W[i + k - 1] if i + k - 1 >= 0 else x
                    group_triggers[g][trig] = group_triggers[g].get(trig, 0) + 3 * pw
        
        result = []
        for g, score in group_score.items():
            if score <= 0:
                continue
            trig_rank = sorted(group_triggers[g].items(), key=lambda x: x[1], reverse=True)
            top_triggers = [n for n, _ in trig_rank[:3]]
            result.append({'name': g, 'score': score, 'triggers': top_triggers, 'numbers': self.groups[g]})
        
        result.sort(key=lambda x: x['score'], reverse=True)
        return result[:15]
    
    def encontrar_grupos_do_gatilho(self, gatilho: int, min_grupos: int = 3, max_grupos: int = 4) -> Tuple[List[str], Set[int]]:
        grupos_analise = self.analisar_grupos_gatilho(gatilho)
        
        grupos_com_gatilho = [g for g in grupos_analise if gatilho in g['triggers']]
        
        if len(grupos_com_gatilho) < min_grupos:
            return [], set()
        
        top_grupos = grupos_com_gatilho[:max_grupos]
        nomes = [g['name'] for g in top_grupos]
        
        if len(top_grupos) >= 2:
            intersecao = top_grupos[0]['numbers'] & top_grupos[1]['numbers']
            if len(top_grupos) >= 3 and len(intersecao) > 5:
                intersecao = intersecao & top_grupos[2]['numbers']
            
            if len(intersecao) < 4:
                freq = {}
                for g in top_grupos:
                    for n in g['numbers']:
                        freq[n] = freq.get(n, 0) + 1
                intersecao = {n for n, f in freq.items() if f >= 2}
        else:
            intersecao = top_grupos[0]['numbers'] if top_grupos else set()
        
        return nomes, intersecao
    
    def calcular_candidatos(self, base: int) -> Dict[int, float]:
        ocorrencias = self.encontrar_ocorrencias(base)
        
        if len(ocorrencias) < 2:
            print(f"Não foram encontradas ocorrências suficientes do número {base}")
            return {}
        
        numeros_depois = self.extrair_numeros_depois(ocorrencias)
        numeros_antes = self.extrair_numeros_antes(ocorrencias)
        
        candidatos = {}
        
        def adicionar(num, score):
            candidatos[num] = candidatos.get(num, 0) + score
        
        for lista in numeros_depois:
            for pos, num in enumerate(lista):
                peso_pos = self.peso_posicao[pos] if pos < len(self.peso_posicao) else 0.3
                adicionar(num, self.peso_depois * peso_pos)
        
        for lista in numeros_antes:
            for num in lista:
                adicionar(num, self.peso_antes)
        
        todos_depois = []
        for nums in numeros_depois:
            todos_depois.extend(nums)
        freq = Counter(todos_depois)
        
        for num, f in freq.most_common(6):
            for v in self.get_vizinhos(num, 1):
                adicionar(v, f * self.peso_vizinho_1)
            for v in self.get_vizinhos(num, 2):
                if v not in self.get_vizinhos(num, 1):
                    adicionar(v, f * self.peso_vizinho_2)
        
        for num, f in freq.most_common(6):
            esp = self.get_espelho(num)
            if esp:
                adicionar(esp, f * self.peso_espelho)
        
        for num, f in freq.most_common(6):
            for s in self.get_sequencia_numerica(num):
                adicionar(s, f * self.peso_sequencia)
        
        if base in candidatos:
            del candidatos[base]
        
        return candidatos
    
    def aplicar_filtro_grupos(self, candidatos: Dict[int, float], base: int, boost: float = 2.0) -> Dict[int, float]:
        nomes_grupos, intersecao = self.encontrar_grupos_do_gatilho(base)
        
        if not intersecao:
            return candidatos
        
        candidatos_ajustados = {}
        for num, score in candidatos.items():
            if num in intersecao:
                candidatos_ajustados[num] = score * boost
            else:
                candidatos_ajustados[num] = score
        
        return candidatos_ajustados
    
    def backtesting(self, base: int, quantidade: int = 18) -> Dict:
        ocorrencias = self.encontrar_ocorrencias(base)
        
        if len(ocorrencias) < 5:
            return {'total_apostas': 0, 'acertos': 0, 'taxa_acerto': 0.0}
        
        acertos = 0
        total = 0
        
        for i, pos in enumerate(ocorrencias[1:-3]):
            sequencia_momento = self.sequencia[pos:]
            ocorr_momento = [j for j, n in enumerate(sequencia_momento) if n == base]
            
            if len(ocorr_momento) < 2:
                continue
            
            # Simula previsão
            candidatos = {}
            numeros_depois = []
            for p in ocorr_momento[1:4]:
                depois = sequencia_momento[max(0, p - 5):p][::-1]
                if depois:
                    numeros_depois.append(depois[:5])
            
            for lista in numeros_depois:
                for idx, num in enumerate(lista):
                    peso = self.peso_posicao[idx] if idx < len(self.peso_posicao) else 0.3
                    candidatos[num] = candidatos.get(num, 0) + self.peso_depois * peso
            
            if not candidatos:
                continue
            
            top = sorted(candidatos.items(), key=lambda x: x[1], reverse=True)
            previsao = [num for num, _ in top[:quantidade]]
            
            numero_real = self.sequencia[pos - 1] if pos > 0 else None
            
            if numero_real is not None and numero_real in previsao:
                acertos += 1
            total += 1
        
        taxa = (acertos / total * 100) if total > 0 else 0.0
        return {'total_apostas': total, 'acertos': acertos, 'taxa_acerto': taxa}
    
    def calcular_confianca(self, base: int, quantidade: int = 18) -> float:
        backtest = self.backtesting(base, quantidade)
        taxa_acerto = backtest['taxa_acerto']
        
        # Consistência
        ocorrencias = self.encontrar_ocorrencias(base)
        numeros_depois = self.extrair_numeros_depois(ocorrencias)
        
        if not numeros_depois:
            consistencia = 0.0
        else:
            aparicoes = {}
            for lista in numeros_depois:
                for num in set(lista):
                    aparicoes[num] = aparicoes.get(num, 0) + 1
            top_nums = sorted(aparicoes.items(), key=lambda x: x[1], reverse=True)[:10]
            if top_nums:
                media = sum(ap for _, ap in top_nums) / len(top_nums)
                consistencia = min((media / len(numeros_depois)) * 100, 100.0)
            else:
                consistencia = 0.0
        
        # Convergência
        candidatos = self.calcular_candidatos(base)
        if candidatos:
            scores = sorted(candidatos.values(), reverse=True)
            if len(scores) >= 18:
                top_score = scores[0]
                bottom_score = scores[17]
                convergencia = min(((top_score - bottom_score) / top_score * 100) if top_score > 0 else 0, 100.0)
            else:
                convergencia = 50.0
        else:
            convergencia = 0.0
        
        # Força grupos
        nomes, intersecao = self.encontrar_grupos_do_gatilho(base)
        if nomes:
            num_grupos = len(nomes)
            tamanho = len(intersecao)
            grupo_score = min(num_grupos / 5, 1.0) * 50
            if 6 <= tamanho <= 12:
                intersecao_score = 50
            elif tamanho < 6:
                intersecao_score = (tamanho / 6) * 50
            else:
                intersecao_score = max(0, 50 - (tamanho - 12) * 3)
            forca_grupos = grupo_score + intersecao_score
        else:
            forca_grupos = 0.0
        
        if backtest['total_apostas'] < 3:
            return (consistencia * 0.4 + convergencia * 0.3 + forca_grupos * 0.3)
        
        return (taxa_acerto * 0.40 + consistencia * 0.20 + convergencia * 0.20 + forca_grupos * 0.20)
    
    def prever(self, base: int, quantidade: int = 18) -> Tuple[List[int], float]:
        candidatos = self.calcular_candidatos(base)
        
        if not candidatos:
            return [], 0.0
        
        candidatos = self.aplicar_filtro_grupos(candidatos, base)
        confianca = self.calcular_confianca(base, quantidade)
        
        top = sorted(candidatos.items(), key=lambda x: x[1], reverse=True)
        numeros = [num for num, _ in top[:quantidade]]
        
        return numeros, confianca


# ============================
# GERENCIADOR DE BANCA
# ============================

@dataclass
class BankConfig:
    valor_ficha: float
    qtd_fichas: int
    multiplicacoes: int
    gales: int
    confianca_minima: float
    esperar_confirmacao: bool
    slug: str
    roulette_url: str


class BankManager:
    """Gerencia a banca com multiplicação progressiva"""
    
    def __init__(self, config: BankConfig):
        self.config = config
        self.valor_base = config.valor_ficha * config.qtd_fichas
        self.valor_atual = self.valor_base
        self.multiplicacao_atual = 0
        self.total_apostado = 0.0
        self.total_ganho = 0.0
        self.wins = 0
        self.losses = 0
        self.ciclos_completos = 0
    
    def get_valor_aposta(self) -> float:
        """Retorna o valor da próxima aposta"""
        return self.valor_atual
    
    def registrar_win(self):
        """Registra uma vitória e avança a multiplicação"""
        self.wins += 1
        ganho = self.valor_atual * 35  # Payout da roleta
        self.total_ganho += ganho
        
        self.multiplicacao_atual += 1
        
        if self.multiplicacao_atual >= self.config.multiplicacoes:
            # Ciclo completo, volta ao valor base
            self.ciclos_completos += 1
            self.multiplicacao_atual = 0
            self.valor_atual = self.valor_base
            return True, "CICLO_COMPLETO"
        else:
            # Dobra o valor
            self.valor_atual *= 2
            return True, "DOBROU"
    
    def registrar_loss(self):
        """Registra uma perda"""
        self.losses += 1
        self.total_apostado += self.valor_atual * (self.config.gales + 1)
        
        # Reinicia o ciclo
        self.multiplicacao_atual = 0
        self.valor_atual = self.valor_base
    
    def get_status(self) -> str:
        lucro = self.total_ganho - self.total_apostado
        return (
            f"💰 Valor Atual: R$ {self.valor_atual:.2f} | "
            f"Mult: {self.multiplicacao_atual + 1}/{self.config.multiplicacoes} | "
            f"W/L: {self.wins}/{self.losses} | "
            f"Lucro: R$ {lucro:.2f}"
        )


# ============================
# ENVIO DA APOSTA
# ============================

def enviar_aposta(bets: List[int], roulette_url: str, valor: float, gales: int = 3):
    """Envia a aposta para a API de betting."""
    
    payload = {
        "bets": bets,
        "attempts": gales + 1,
        "roulette_url": roulette_url,
        "gales": gales,
        "valor": valor
    }

    print(f"\n📡 Enviando aposta: {len(bets)} números | R$ {valor:.2f}")
    print(f"   Números: {sorted(bets)}")

    try:
        resp = requests.post(
            BET_API_URL,
            headers={"Content-Type": "application/json"},
            data=json.dumps(payload),
            timeout=10
        )

        print(f"✅ Resposta: {resp.status_code}")
        return True

    except requests.exceptions.RequestException as e:
        print(f"❌ Erro ao enviar aposta: {e}")
        return False


# ============================
# CONFIGURAÇÃO
# ============================

MESAS_DISPONIVEIS = [
    {"name": "Mega Roulette", "slug": "pragmatic-mega-roulette", "link": "https://lotogreen.bet.br/play/550"},
    {"name": "Brazilian Roulette", "slug": "pragmatic-brazilian-roulette", "link": "https://lotogreen.bet.br/play/450"},
    {"name": "Auto Roulette", "slug": "pragmatic-auto-roulette", "link": "https://lotogreen.bet.br/play/373"},
    {"name": "Speed Roulette 1", "slug": "pragmatic-speed-roulette-1", "link": "https://lotogreen.bet.br/play/556"},
    {"name": "Korean Roulette", "slug": "pragmatic-korean-roulette", "link": "https://lotogreen.bet.br/play/457"},
]


def coletar_configuracao() -> Optional[BankConfig]:
    """Coleta os dados de configuração do usuário."""
    
    print("\n" + "=" * 60)
    print("🎰 SISTEMA DE APOSTAS AUTOMATIZADO v1.0")
    print("   Análise inteligente de padrões + Gestão de banca")
    print("=" * 60)
    
    # Mesa
    print("\n📺 Qual roleta deseja monitorar?")
    for i, mesa in enumerate(MESAS_DISPONIVEIS, 1):
        print(f"   {i}. {mesa['name']}")
    print(f"   {len(MESAS_DISPONIVEIS) + 1}. Outra (digitar slug)")
    
    escolha = input("   > ").strip()
    
    if escolha.isdigit():
        idx = int(escolha) - 1
        if 0 <= idx < len(MESAS_DISPONIVEIS):
            mesa = MESAS_DISPONIVEIS[idx]
            slug = mesa['slug']
            roulette_url = mesa['link']
            print(f"   ✔ Mesa: {mesa['name']}")
        else:
            print("   Digite o slug da mesa:")
            slug = input("   > ").strip()
            print("   Digite a URL da mesa:")
            roulette_url = input("   > ").strip()
    else:
        slug = escolha
        print("   Digite a URL da mesa:")
        roulette_url = input("   > ").strip()
    
    # Valor da ficha
    print("\n💵 Qual valor da ficha? (ex: 0.50, 1, 5)")
    valor_input = input("   > ").strip().replace(",", ".")
    try:
        valor_ficha = float(valor_input)
    except ValueError:
        valor_ficha = 1.0
    print(f"   ✔ Valor da ficha: R$ {valor_ficha:.2f}")
    
    # Quantidade de fichas
    print("\n🎲 Quantas fichas por aposta? (ex: 1, 5, 10)")
    qtd_input = input("   > ").strip()
    qtd_fichas = int(qtd_input) if qtd_input.isdigit() else 1
    print(f"   ✔ Fichas por aposta: {qtd_fichas}")
    print(f"   💰 Valor inicial: R$ {valor_ficha * qtd_fichas:.2f}")
    
    # Multiplicações
    print("\n📈 Quantas vezes deseja dobrar até reiniciar o ciclo? (ex: 3)")
    print("   Exemplo: 3 = R$9 → R$18 → R$36 → R$72 → volta R$9")
    mult_input = input("   > ").strip()
    multiplicacoes = int(mult_input) if mult_input.isdigit() else 3
    print(f"   ✔ Multiplicações: {multiplicacoes}")
    
    # Simulação do ciclo
    valor = valor_ficha * qtd_fichas
    print(f"\n   📊 Simulação do ciclo:")
    for i in range(multiplicacoes + 1):
        if i < multiplicacoes:
            print(f"      Win {i+1}: R$ {valor:.2f} → dobra para R$ {valor*2:.2f}")
        else:
            print(f"      Win {i+1}: R$ {valor:.2f} → REINICIA para R$ {valor_ficha * qtd_fichas:.2f}")
        valor *= 2
    
    # Gales
    print("\n🔄 Quantos gales? (ex: 2)")
    gales_input = input("   > ").strip()
    gales = int(gales_input) if gales_input.isdigit() else 2
    print(f"   ✔ Gales: {gales} (total {gales + 1} tentativas)")
    
    # Confiança mínima
    print("\n📊 Confiança mínima para apostar? (ex: 50, 60, 70)")
    print("   Quanto maior, menos sinais mas mais assertivos")
    conf_input = input("   > ").strip()
    confianca_minima = float(conf_input) if conf_input.replace(".", "").isdigit() else 50.0
    print(f"   ✔ Confiança mínima: {confianca_minima}%")
    
    # Esperar confirmação
    print("\n⏳ Deseja esperar confirmação (green) antes de entrar?")
    print("   1. Não - Apostar imediatamente quando gatilho bater")
    print("   2. Sim - Esperar dar um green primeiro")
    esperar_input = input("   > ").strip()
    esperar_confirmacao = esperar_input == "2"
    print(f"   ✔ {'Esperar confirmação' if esperar_confirmacao else 'Apostar imediatamente'}")
    
    # Resumo
    print("\n" + "=" * 60)
    print("📋 RESUMO DA CONFIGURAÇÃO:")
    print(f"   Mesa:           {slug}")
    print(f"   URL:            {roulette_url}")
    print(f"   Valor inicial:  R$ {valor_ficha * qtd_fichas:.2f}")
    print(f"   Multiplicações: {multiplicacoes}")
    print(f"   Gales:          {gales}")
    print(f"   Confiança mín:  {confianca_minima}%")
    print(f"   Esperar green:  {'Sim' if esperar_confirmacao else 'Não'}")
    print("=" * 60)
    
    confirm = input("\n✅ Confirma? (s/n): ").strip().lower()
    
    if confirm != "s":
        print("❌ Configuração cancelada.")
        return None
    
    return BankConfig(
        valor_ficha=valor_ficha,
        qtd_fichas=qtd_fichas,
        multiplicacoes=multiplicacoes,
        gales=gales,
        confianca_minima=confianca_minima,
        esperar_confirmacao=esperar_confirmacao,
        slug=slug,
        roulette_url=roulette_url
    )


# ============================
# FETCH DO HISTÓRICO
# ============================

async def fetch_historico(slug: str) -> List[int]:
    """Busca histórico da API antes de iniciar"""
    url = f"https://api.revesbot.com.br/history/{slug}"
    
    print(f"\n📥 Buscando histórico: {url}")
    
    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    results = await resp.json()
                    data  = results["results"]
                    # Tenta extrair números do response
                    if isinstance(data, list):
                        numeros = [int(x) for x in data if str(x).isdigit()]
                    elif isinstance(data, dict):
                        # Pode vir como {"results": [...]} ou {"history": [...]}
                        numeros = []
                        for key in ['results', 'history', 'numbers', 'data']:
                            if key in data and isinstance(data[key], list):
                                numeros = [int(x) for x in data[key] if str(x).isdigit()]
                                break
                    else:
                        numeros = []
                    
                    if numeros:
                        print(f"✅ Histórico carregado: {len(numeros)} números")
                        print(f"   Últimos 10: {numeros[:10]}")
                        return numeros
                    else:
                        print(f"⚠️ Histórico vazio ou formato desconhecido")
                        return []
                else:
                    print(f"❌ Erro HTTP: {resp.status}")
                    return []
    except Exception as e:
        print(f"❌ Erro ao buscar histórico: {e}")
        return []


# ============================
# LISTENER DO REDIS
# ============================

async def listen_redis(config: BankConfig):
    """Escuta o canal Redis e gerencia apostas automaticamente."""
    
    # Inicializa componentes
    analyzer = RouletteAnalyzer()
    bank = BankManager(config)
    
    # ========== BUSCA HISTÓRICO PRIMEIRO ==========
    historico = await fetch_historico(config.slug)


    
    if historico:
        analyzer.set_sequencia(historico)
        print(f"✅ Analisador iniciado com {len(historico)} números")
    else:
        print(f"⚠️ Iniciando sem histórico - aguardando números...")
    
    # ========== CONECTA NO REDIS ==========
    print(f"\n👂 Conectando ao Redis...")
    
    r = await redis.from_url(REDIS_URL)
    pubsub = r.pubsub()
    await pubsub.subscribe(RESULT_CHANNEL)
    
    print(f"✅ Conectado! Canal: {RESULT_CHANNEL}")
    print(f"⏳ Aguardando números da mesa: {config.slug}")
    print("-" * 60)
    
    
    # Estado
    aposta_ativa = None  # {"numeros": [...], "gales_restantes": N, "gatilho": X}
    aguardando_confirmacao = None  # {"gatilho": X, "numeros": [...]}
    numeros_recebidos = 0
    max_reds_consecutivos = 3
    reds_consecutivos = 0
    
    try:
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            
            if message is None:
                continue
            
            try:
                data = json.loads(message["data"])
            except (json.JSONDecodeError, TypeError):
                continue
            
            slug = data.get("slug")
            number = data.get("result")
            
            if slug != config.slug or number is None:
                continue
            
            numeros_recebidos += 1
            analyzer.adicionar_numero(number)
            
            print(f"\n{'='*60}")
            print(f"🔢 [{numeros_recebidos}] Número: {number}")
            print(f"{bank.get_status()}")
            
            # ========== APOSTA ATIVA ==========
            if aposta_ativa:
                if number in aposta_ativa["numeros"]:
                    # WIN!
                    print(f"✅ GREEN! Número {number} estava na aposta!")
                    resultado, tipo = bank.registrar_win()
                    reds_consecutivos = 0
                    
                    if tipo == "CICLO_COMPLETO":
                        print(f"🎉 CICLO COMPLETO! Voltando para R$ {bank.valor_base:.2f}")
                    else:
                        print(f"📈 Próxima aposta: R$ {bank.valor_atual:.2f}")
                    
                    aposta_ativa = None
                else:
                    # RED
                    aposta_ativa["gales_restantes"] -= 1
                    
                    if aposta_ativa["gales_restantes"] > 0:
                        print(f"❌ RED - Gale {config.gales - aposta_ativa['gales_restantes'] + 1}/{config.gales}")
                    else:
                        print(f"💀 RED FINAL! Perdeu aposta")
                        bank.registrar_loss()
                        reds_consecutivos += 1
                        aposta_ativa = None
                        
                        if reds_consecutivos >= max_reds_consecutivos:
                            print(f"\n⛔ {max_reds_consecutivos} REDS CONSECUTIVOS!")
                            print("🛑 Encerrando por segurança...")
                            break
                
                continue
            
            # ========== AGUARDANDO CONFIRMAÇÃO ==========
            if aguardando_confirmacao:
                if number in aguardando_confirmacao["numeros"]:
                    print(f"✅ Confirmação recebida! Número {number} deu green")
                    print(f"🎯 Ativando aposta do gatilho {aguardando_confirmacao['gatilho']}")
                    
                    # Agora sim, envia a aposta
                    await asyncio.sleep(1)
                    enviar_aposta(
                        bets=aguardando_confirmacao["numeros"],
                        roulette_url=config.roulette_url,
                        valor=bank.get_valor_aposta(),
                        gales=config.gales
                    )
                    
                    aposta_ativa = {
                        "numeros": aguardando_confirmacao["numeros"],
                        "gales_restantes": config.gales + 1,
                        "gatilho": aguardando_confirmacao["gatilho"]
                    }
                    aguardando_confirmacao = None
                else:
                    print(f"⏳ Aguardando confirmação... ({number} não estava na lista)")
                
                continue
            
            # ========== ANÁLISE DE NOVO SINAL ==========
            if len(analyzer.sequencia) < 2:
                print(f"📊 Coletando histórico... ({len(analyzer.sequencia)}/2)")
                continue
            
            # Gera previsão
            numeros_previstos, confianca = analyzer.prever(number, quantidade=18)
            
            if not numeros_previstos:
                print(f"📊 Sem padrão identificado para {number}")
                continue
            
            # Classificação
            if confianca >= 70:
                emoji = "🟢"
                classe = "ALTA"
            elif confianca >= 50:
                emoji = "🟡"
                classe = "MÉDIA"
            else:
                emoji = "🔴"
                classe = "BAIXA"
            
            print(f"📊 Confiança: {confianca:.1f}% {emoji} {classe}")
            print(f"🎯 Previsão: {sorted(numeros_previstos)}")
            
            # Verifica se atende confiança mínima
            if confianca < config.confianca_minima:
                print(f"⏭️ Pulando... (confiança {confianca:.1f}% < {config.confianca_minima}%)")
                continue
            
            # Sinal aprovado!
            print(f"✅ SINAL APROVADO! Gatilho: {number}")
            
            if config.esperar_confirmacao:
                print(f"⏳ Aguardando confirmação (green) antes de apostar...")
                aguardando_confirmacao = {
                    "gatilho": number,
                    "numeros": numeros_previstos
                }
            else:
                # Aposta imediatamente
                await asyncio.sleep(1)
                enviar_aposta(
                    bets=numeros_previstos,
                    roulette_url=config.roulette_url,
                    valor=bank.get_valor_aposta(),
                    gales=config.gales
                )
                
                aposta_ativa = {
                    "numeros": numeros_previstos,
                    "gales_restantes": config.gales + 1,
                    "gatilho": number
                }
            
    except asyncio.CancelledError:
        print("\n🛑 Monitoramento cancelado.")
    except Exception as e:
        print(f"\n❌ Erro: {e}")
    finally:
        await pubsub.unsubscribe(RESULT_CHANNEL)
        await r.close()
        
        # Resumo final
        print("\n" + "=" * 60)
        print("📋 RESUMO FINAL")
        print(f"   Números recebidos: {numeros_recebidos}")
        print(f"   Wins: {bank.wins}")
        print(f"   Losses: {bank.losses}")
        print(f"   Ciclos completos: {bank.ciclos_completos}")
        print(f"   Total apostado: R$ {bank.total_apostado:.2f}")
        print(f"   Total ganho: R$ {bank.total_ganho:.2f}")
        print(f"   Lucro: R$ {bank.total_ganho - bank.total_apostado:.2f}")
        print("=" * 60)


# ============================
# MAIN
# ============================

async def main():
    config = coletar_configuracao()
    
    if config is None:
        return
    
    print("\n🚀 Iniciando sistema de apostas...")
    
    try:
        await listen_redis(config)
    except KeyboardInterrupt:
        print("\n👋 Encerrando...")


if __name__ == "__main__":
    asyncio.run(main())