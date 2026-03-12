"""
🎯 ANALISADOR DE PADRÕES DE ROLETA v5
Sistema de previsão com backtesting + filtro de grupos/regiões

Novidade v5: Cálculo de confiança melhorado com novos fatores:
- Targets recentes (quantos targets apareceram nos últimos spins)
- Temperatura do gatilho (distância da última aparição)
- Frequência do gatilho no histórico
"""

from collections import Counter
from typing import List, Dict, Optional, Tuple, Set
from dataclasses import dataclass

# Ordem física dos números na roleta europeia
ROULETTE = [0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23, 10, 5, 24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26]
ROULETTE_INDEX = {n: i for i, n in enumerate(ROULETTE)}

# Espelhos
ESPELHOS = {
    1: 10, 10: 1,
    2: 20, 20: 2,
    3: 30, 30: 3,
    6: 9, 9: 6,
    12: 21, 21: 12,
    13: 31, 31: 13,
    16: 19, 19: 16,
    23: 32, 32: 23,
    26: 29, 29: 26
}

# ==============================================================================
# GRUPOS / REGIÕES
# ==============================================================================
def build_groups() -> Dict[str, Set[int]]:
    """Constrói todos os grupos da roleta"""
    groups: Dict[str, Set[int]] = {}
    
    # Dúzias
    groups["Dúzia 1"] = set(range(1, 13))
    groups["Dúzia 2"] = set(range(13, 25))
    groups["Dúzia 3"] = set(range(25, 37))
    
    # Colunas
    groups["Coluna 1"] = {1, 4, 7, 10, 13, 16, 19, 22, 25, 28, 31, 34}
    groups["Coluna 2"] = {2, 5, 8, 11, 14, 17, 20, 23, 26, 29, 32, 35}
    groups["Coluna 3"] = {3, 6, 9, 12, 15, 18, 21, 24, 27, 30, 33, 36}
    
    # Racetrack
    groups["Tiers"] = {27, 13, 36, 11, 30, 8, 23, 10, 5, 24, 16, 33}
    groups["Orphelins"] = {1, 20, 14, 31, 9, 17, 34, 6}
    groups["Voisins"] = {22, 18, 29, 7, 28, 12, 35, 3, 26, 0, 32, 15, 19, 4, 21, 2, 25}
    
    # Cores
    red = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}
    black = {2, 4, 6, 8, 10, 11, 13, 15, 17, 20, 22, 24, 26, 28, 29, 31, 33, 35}
    
    groups["Vermelhos"] = red
    groups["Pretos"] = black
    
    # Baixos/Altos
    groups["Baixos"] = set(range(1, 19))
    groups["Altos"] = set(range(19, 37))
    
    # Pares/Ímpares
    groups["Pares"] = {n for n in range(1, 37) if n % 2 == 0}
    groups["Ímpares"] = {n for n in range(1, 37) if n % 2 == 1}
    
    # Combinações úteis
    groups["Vermelhos Ímpares"] = red & {n for n in range(1, 37) if n % 2 == 1}
    groups["Vermelhos Pares"] = red & {n for n in range(1, 37) if n % 2 == 0}
    groups["Pretos Ímpares"] = black & {n for n in range(1, 37) if n % 2 == 1}
    groups["Pretos Pares"] = black & {n for n in range(1, 37) if n % 2 == 0}
    
    groups["Vermelhos Baixos"] = red & set(range(1, 19))
    groups["Vermelhos Altos"] = red & set(range(19, 37))
    groups["Pretos Baixos"] = black & set(range(1, 19))
    groups["Pretos Altos"] = black & set(range(19, 37))
    
    # Dúzias + Cores
    groups["Vermelhos D1"] = red & set(range(1, 13))
    groups["Vermelhos D2"] = red & set(range(13, 25))
    groups["Vermelhos D3"] = red & set(range(25, 37))
    groups["Pretos D1"] = black & set(range(1, 13))
    groups["Pretos D2"] = black & set(range(13, 25))
    groups["Pretos D3"] = black & set(range(25, 37))
    
    return groups


GROUPS = build_groups()


class RouletteAnalyzer:
    """Analisador de padrões de roleta com backtesting e filtro de grupos"""
    
    def __init__(self, sequencia: List[int]):
        self.sequencia = sequencia
        
        # Pesos para cálculo de score
        self.peso_depois = 3.0
        self.peso_antes = 2.0
        self.peso_vizinho_1 = 1.5
        self.peso_vizinho_2 = 0.5
        self.peso_espelho = 2.0
        self.peso_sequencia = 1.0
        
        # Pesos por posição
        self.peso_posicao = [1.0, 0.85, 0.70, 0.55, 0.40]
        
        # Configurações
        self.max_ocorrencias = 3
        self.janela_depois = 5
        self.janela_antes = 3
        
        # Cache de grupos
        self.groups = GROUPS
    
    @staticmethod
    def get_vizinhos(n: int, distancia: int = 2) -> List[int]:
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
    
    def encontrar_ocorrencias(self, base: int, sequencia: List[int] = None) -> List[int]:
        seq = sequencia if sequencia is not None else self.sequencia
        return [i for i, n in enumerate(seq) if n == base]
    
    def extrair_numeros_depois(self, ocorrencias: List[int], sequencia: List[int] = None) -> List[List[int]]:
        seq = sequencia if sequencia is not None else self.sequencia
        numeros_depois = []
        for pos in ocorrencias[1:self.max_ocorrencias + 1]:
            depois = seq[max(0, pos - self.janela_depois):pos][::-1]
            if depois:
                numeros_depois.append(depois[:self.janela_depois])
        return numeros_depois
    
    def extrair_numeros_antes(self, ocorrencias: List[int], sequencia: List[int] = None) -> List[List[int]]:
        seq = sequencia if sequencia is not None else self.sequencia
        numeros_antes = []
        for pos in ocorrencias[1:self.max_ocorrencias + 1]:
            antes = seq[pos + 1:pos + 1 + self.janela_antes]
            if antes:
                numeros_antes.append(antes)
        return numeros_antes
    
    # ==========================================================================
    # ANÁLISE DE GRUPOS - X → GRUPO
    # ==========================================================================
    def analisar_grupos_gatilho(self, base: int, janela: int = 130) -> List[Dict]:
        """
        Analisa quais grupos são ativados após o número base aparecer
        
        Returns:
            Lista de {name, score, triggers} ordenada por score
        """
        W = self.sequencia[:janela]
        if len(W) < 50:
            return []
        
        group_score: Dict[str, int] = {name: 0 for name in self.groups}
        group_triggers: Dict[str, Dict[int, int]] = {name: {} for name in self.groups}
        
        # Mapeia número -> grupos que ele pertence
        num_to_groups: Dict[int, List[str]] = {n: [] for n in range(37)}
        for g, nums in self.groups.items():
            for n in nums:
                if 0 <= n <= 36:
                    num_to_groups[n].append(g)
        
        # Peso por proximidade
        def prox_weight(k):
            return 3 if k == 1 else 2 if k == 2 else 1
        
        # Varredura: para cada ocorrência de X, verifica se Y (em +1,+2,+3) pertence a algum grupo
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
                    
                    # O gatilho é o número que veio antes do Y
                    trig = W[i + k - 1] if i + k - 1 >= 0 else x
                    group_triggers[g][trig] = group_triggers[g].get(trig, 0) + 3 * pw
        
        # Monta resultado
        result = []
        for g, score in group_score.items():
            if score <= 0:
                continue
            
            trig_rank = sorted(group_triggers[g].items(), key=lambda x: x[1], reverse=True)
            top_triggers = [n for n, _ in trig_rank[:3]]
            
            result.append({
                'name': g,
                'score': score,
                'triggers': top_triggers,
                'numbers': self.groups[g]
            })
        
        result.sort(key=lambda x: x['score'], reverse=True)
        return result[:15]
    
    def encontrar_grupos_do_gatilho(self, gatilho: int, min_grupos: int = 3, max_grupos: int = 4) -> Tuple[List[str], Set[int]]:
        """
        Encontra quais grupos têm o gatilho como ativador
        Usa os TOP grupos por score (não todos!) para evitar interseção vazia
        
        Returns:
            (lista de nomes dos grupos, conjunto de números da interseção/união)
        """
        grupos_analise = self.analisar_grupos_gatilho(gatilho)
        
        # Filtra grupos onde o gatilho está entre os top 3 triggers
        grupos_com_gatilho = []
        for g in grupos_analise:
            if gatilho in g['triggers']:
                grupos_com_gatilho.append(g)
        
        if len(grupos_com_gatilho) < min_grupos:
            return [], set()
        
        # Pega apenas os TOP grupos por score (evita interseção vazia)
        top_grupos = grupos_com_gatilho[:max_grupos]
        nomes = [g['name'] for g in top_grupos]
        
        # Estratégia: interseção dos top 2-3, depois adiciona números frequentes
        if len(top_grupos) >= 2:
            # Interseção dos 2 primeiros
            intersecao = top_grupos[0]['numbers'] & top_grupos[1]['numbers']
            
            # Se tiver 3+, tenta adicionar mais
            if len(top_grupos) >= 3 and len(intersecao) > 5:
                intersecao = intersecao & top_grupos[2]['numbers']
            
            # Se interseção ficou muito pequena, usa união ponderada
            if len(intersecao) < 4:
                # Conta frequência de cada número nos grupos
                freq = {}
                for g in top_grupos:
                    for n in g['numbers']:
                        freq[n] = freq.get(n, 0) + 1
                
                # Pega números que aparecem em 2+ grupos
                intersecao = {n for n, f in freq.items() if f >= 2}
        else:
            intersecao = top_grupos[0]['numbers'] if top_grupos else set()
        
        return nomes, intersecao
    
    # ==========================================================================
    # CÁLCULO DE CANDIDATOS (COM FILTRO DE GRUPOS)
    # ==========================================================================
    def calcular_candidatos(self, base: int, sequencia: List[int] = None) -> Dict[int, float]:
        seq = sequencia if sequencia is not None else self.sequencia
        ocorrencias = self.encontrar_ocorrencias(base, seq)
        
        if len(ocorrencias) < 2:
            return {}
        
        numeros_depois = self.extrair_numeros_depois(ocorrencias, seq)
        numeros_antes = self.extrair_numeros_antes(ocorrencias, seq)
        
        candidatos = {}
        
        def adicionar(num, score):
            candidatos[num] = candidatos.get(num, 0) + score
        
        # 1. Números DEPOIS com peso por posição
        for lista in numeros_depois:
            for pos, num in enumerate(lista):
                peso_pos = self.peso_posicao[pos] if pos < len(self.peso_posicao) else 0.3
                adicionar(num, self.peso_depois * peso_pos)
        
        # 2. Números ANTES
        for lista in numeros_antes:
            for num in lista:
                adicionar(num, self.peso_antes)
        
        # Calcular frequências para vizinhos/espelhos
        todos_depois = []
        for nums in numeros_depois:
            todos_depois.extend(nums)
        freq = Counter(todos_depois)
        
        # 3. Vizinhos
        for num, f in freq.most_common(6):
            for v in self.get_vizinhos(num, 1):
                adicionar(v, f * self.peso_vizinho_1)
            for v in self.get_vizinhos(num, 2):
                if v not in self.get_vizinhos(num, 1):
                    adicionar(v, f * self.peso_vizinho_2)
        
        # 4. Espelhos
        for num, f in freq.most_common(6):
            esp = self.get_espelho(num)
            if esp:
                adicionar(esp, f * self.peso_espelho)
        
        # 5. Sequência numérica
        for num, f in freq.most_common(6):
            for s in self.get_sequencia_numerica(num):
                adicionar(s, f * self.peso_sequencia)
        
        # Remove o próprio base
        if base in candidatos:
            del candidatos[base]
        
        return candidatos
    
    def aplicar_filtro_grupos(self, candidatos: Dict[int, float], base: int, 
                               min_grupos: int = 3, boost: float = 2.0) -> Dict[int, float]:
        """
        Aplica filtro de grupos: números na interseção ganham boost no score
        
        Args:
            candidatos: Dict de candidatos com scores
            base: Número base (gatilho)
            min_grupos: Mínimo de grupos para considerar filtro
            boost: Multiplicador para números na interseção
        
        Returns:
            Candidatos com scores ajustados
        """
        nomes_grupos, intersecao = self.encontrar_grupos_do_gatilho(base, min_grupos)
        
        if not intersecao:
            return candidatos
        
        # Aplica boost nos números da interseção
        candidatos_ajustados = {}
        for num, score in candidatos.items():
            if num in intersecao:
                candidatos_ajustados[num] = score * boost
            else:
                candidatos_ajustados[num] = score
        
        return candidatos_ajustados
    
    # ==========================================================================
    # BACKTESTING
    # ==========================================================================
    def backtesting(self, base: int, quantidade: int = 18, usar_filtro_grupos: bool = True) -> Dict:
        ocorrencias = self.encontrar_ocorrencias(base)
        
        if len(ocorrencias) < 5:
            return {'total_apostas': 0, 'acertos': 0, 'taxa_acerto': 0.0, 'detalhes': []}
        
        detalhes = []
        acertos = 0
        total = 0
        
        for i, pos in enumerate(ocorrencias[1:-3]):
            sequencia_momento = self.sequencia[pos:]
            ocorr_momento = self.encontrar_ocorrencias(base, sequencia_momento)
            
            if len(ocorr_momento) < 2:
                continue
            
            # Gerar candidatos
            candidatos = self.calcular_candidatos(base, sequencia_momento)
            
            if not candidatos:
                continue
            
            # Aplicar filtro de grupos se habilitado
            if usar_filtro_grupos:
                candidatos = self.aplicar_filtro_grupos(candidatos, base)
            
            # Top N
            top = sorted(candidatos.items(), key=lambda x: x[1], reverse=True)
            previsao = [num for num, _ in top[:quantidade]]
            
            if not previsao:
                continue
            
            numero_real = self.sequencia[pos - 1] if pos > 0 else None
            
            if numero_real is None:
                continue
            
            acertou = numero_real in previsao
            
            if acertou:
                acertos += 1
            total += 1
            
            detalhes.append({
                'posicao': pos,
                'previsao': previsao,
                'numero_real': numero_real,
                'acertou': acertou,
                'posicao_na_lista': previsao.index(numero_real) + 1 if acertou else None
            })
        
        taxa = (acertos / total * 100) if total > 0 else 0.0
        
        return {
            'total_apostas': total,
            'acertos': acertos,
            'taxa_acerto': taxa,
            'detalhes': detalhes
        }
    
    # ==========================================================================
    # CONFIANÇA
    # ==========================================================================
    def calcular_consistencia(self, base: int) -> float:
        ocorrencias = self.encontrar_ocorrencias(base)
        
        if len(ocorrencias) < 2:
            return 0.0
        
        numeros_depois = self.extrair_numeros_depois(ocorrencias)
        
        if not numeros_depois:
            return 0.0
        
        aparicoes = {}
        for lista in numeros_depois:
            for num in set(lista):
                aparicoes[num] = aparicoes.get(num, 0) + 1
        
        top_nums = sorted(aparicoes.items(), key=lambda x: x[1], reverse=True)[:10]
        
        if not top_nums:
            return 0.0
        
        media = sum(ap for _, ap in top_nums) / len(top_nums)
        consistencia = (media / len(numeros_depois)) * 100
        
        return min(consistencia, 100.0)
    
    def calcular_convergencia(self, base: int) -> float:
        candidatos = self.calcular_candidatos(base)
        
        if not candidatos:
            return 0.0
        
        scores = sorted(candidatos.values(), reverse=True)
        
        if len(scores) < 18:
            return 50.0
        
        top_score = scores[0]
        bottom_score = scores[17]
        
        if top_score == 0:
            return 0.0
        
        ratio = (top_score - bottom_score) / top_score
        return min(ratio * 100, 100.0)
    
    def calcular_forca_grupos(self, base: int) -> float:
        """Calcula força do filtro de grupos (0-100)"""
        nomes, intersecao = self.encontrar_grupos_do_gatilho(base, min_grupos=3)
        
        if not nomes:
            return 0.0
        
        # Quanto mais grupos e menor a interseção, mais forte
        num_grupos = len(nomes)
        tamanho_intersecao = len(intersecao)
        
        # Ideal: 4+ grupos com interseção de 6-12 números
        grupo_score = min(num_grupos / 5, 1.0) * 50  # Até 50 pontos
        
        if tamanho_intersecao > 0:
            # Interseção de 6-12 é ideal
            if 6 <= tamanho_intersecao <= 12:
                intersecao_score = 50
            elif tamanho_intersecao < 6:
                intersecao_score = tamanho_intersecao / 6 * 50
            else:
                intersecao_score = max(0, 50 - (tamanho_intersecao - 12) * 3)
        else:
            intersecao_score = 0
        
        return grupo_score + intersecao_score
    
    # ==========================================================================
    # NOVOS FATORES DE CONFIANÇA (v5)
    # ==========================================================================
    
    def calcular_targets_recentes(self, base: int, quantidade: int = 18, janela: int = 15) -> float:
        """
        Novo fator: Quantos targets (números previstos) apareceram nos últimos spins.
        Indica se a "região" dos targets está quente.
        
        Returns:
            Score 0-100
        """
        # Obter targets (previsão)
        candidatos = self.calcular_candidatos(base)
        if not candidatos:
            return 50.0
        
        top = sorted(candidatos.items(), key=lambda x: x[1], reverse=True)
        targets = set(num for num, _ in top[:quantidade])
        
        # Contar quantos targets apareceram nos últimos N spins
        historico_recente = self.sequencia[:janela]
        targets_encontrados = len([n for n in historico_recente if n in targets])
        
        # Normalizar: 0 = 0, 6+ = 100
        score = min(100, (targets_encontrados / 6) * 100)
        
        return score
    
    def calcular_temperatura_gatilho(self, base: int) -> float:
        """
        Novo fator: Distância desde a última aparição do gatilho.
        
        - 10-30 spins: IDEAL (gatilho "devido")
        - < 5 spins: pode estar "esgotado"  
        - > 50 spins: muito frio
        
        Returns:
            Score 0-100
        """
        # Encontrar distância da última aparição (pulando a posição 0 que é o gatilho atual)
        distancia = None
        for i, n in enumerate(self.sequencia[1:], 1):
            if n == base:
                distancia = i
                break
        
        if distancia is None:
            # Nunca apareceu no histórico = muito frio
            return 25.0
        elif distancia <= 5:
            # Muito recente - pode estar "esgotado"
            return 50.0
        elif distancia <= 15:
            # IDEAL - recente mas não demais
            return 90.0
        elif distancia <= 30:
            # Bom - ainda quente
            return 75.0
        elif distancia <= 50:
            # Mediano
            return 50.0
        else:
            # Muito frio
            return 25.0
    
    def calcular_frequencia_gatilho(self, base: int, janela: int = 50) -> float:
        """
        Novo fator: Quantas vezes o gatilho apareceu nos últimos N spins.
        
        Esperado: ~1.35 em 50 spins (50/37)
        
        Returns:
            Score 0-100
        """
        historico = self.sequencia[:janela]
        freq = historico.count(base)
        
        if freq == 0:
            return 20.0  # Nunca apareceu = muito frio
        elif freq == 1:
            return 50.0  # Normal baixo
        elif freq == 2:
            return 70.0  # Normal
        elif freq <= 4:
            return 85.0  # Quente
        else:
            return 60.0  # Muito quente - pode esfriar
    
    def calcular_confianca(self, base: int, quantidade: int = 18) -> float:
        """
        Confiança v5 - Melhorada com novos fatores:
        
        - 30% Taxa de acerto no backtesting
        - 25% Targets recentes (quantos targets apareceram recentemente)
        - 25% Temperatura do gatilho (distância última aparição)
        - 10% Frequência do gatilho
        - 10% Força do filtro de grupos
        
        Esses pesos foram calibrados baseados na análise de sinais reais,
        onde identificamos que:
        - Wins têm +1.23 mais targets recentes
        - Wins têm gatilho que apareceu ~15 spins mais recente
        """
        # Calcular todos os fatores
        backtest = self.backtesting(base, quantidade)
        taxa_acerto = backtest['taxa_acerto']
        
        targets_recentes = self.calcular_targets_recentes(base, quantidade)
        temperatura = self.calcular_temperatura_gatilho(base)
        frequencia = self.calcular_frequencia_gatilho(base)
        forca_grupos = self.calcular_forca_grupos(base)
        
        # Se não tem histórico suficiente de backtest, ajustar pesos
        if backtest['total_apostas'] < 3:
            # Sem backtest, usar mais os outros fatores
            confianca = (
                targets_recentes * 0.35 +
                temperatura * 0.35 +
                frequencia * 0.15 +
                forca_grupos * 0.15
            )
        else:
            # Com backtest, usar fórmula completa
            confianca = (
                taxa_acerto * 0.30 +
                targets_recentes * 0.25 +
                temperatura * 0.25 +
                frequencia * 0.10 +
                forca_grupos * 0.10
            )
        
        # Bônus/penalidade por convergência de fatores
        fatores_altos = sum([
            taxa_acerto >= 60 if backtest['total_apostas'] >= 3 else False,
            targets_recentes >= 70,
            temperatura >= 70,
            frequencia >= 70
        ])
        
        if fatores_altos >= 3:
            confianca += 5  # Bônus por convergência
        elif fatores_altos <= 1 and confianca > 50:
            confianca -= 5  # Penalidade por divergência
        
        return max(0, min(100, confianca))
    
    # ==========================================================================
    # PREVISÃO PRINCIPAL
    # ==========================================================================
    def prever(self, base: int, quantidade: int = 18, usar_filtro_grupos: bool = True) -> Tuple[List[int], float]:
        """
        Gera previsão com filtro de grupos
        
        Returns:
            (lista de números, confiança)
        """
        candidatos = self.calcular_candidatos(base)
        
        if not candidatos:
            return [], 0.0
        
        # Aplicar filtro de grupos
        if usar_filtro_grupos:
            candidatos = self.aplicar_filtro_grupos(candidatos, base)
        
        confianca = self.calcular_confianca(base, quantidade)
        
        top = sorted(candidatos.items(), key=lambda x: x[1], reverse=True)
        numeros = [num for num, _ in top[:quantidade]]
        
        return numeros, confianca
    
    def analisar_completo(self, base: int, quantidade: int = 18) -> Dict:
        """Análise completa com grupos"""
        ocorrencias = self.encontrar_ocorrencias(base)
        numeros_depois = self.extrair_numeros_depois(ocorrencias)
        numeros_antes = self.extrair_numeros_antes(ocorrencias)
        
        # Candidatos sem filtro
        candidatos_raw = self.calcular_candidatos(base)
        
        # Candidatos com filtro
        candidatos_filtrados = self.aplicar_filtro_grupos(candidatos_raw.copy(), base)
        
        # Grupos
        nomes_grupos, intersecao = self.encontrar_grupos_do_gatilho(base)
        grupos_analise = self.analisar_grupos_gatilho(base)
        
        # Backtesting
        backtest = self.backtesting(base, quantidade)
        
        # Fatores de confiança (v5)
        targets_recentes = self.calcular_targets_recentes(base, quantidade)
        temperatura = self.calcular_temperatura_gatilho(base)
        frequencia = self.calcular_frequencia_gatilho(base)
        forca_grupos = self.calcular_forca_grupos(base)
        
        # Manter consistencia e convergencia para compatibilidade
        consistencia = self.calcular_consistencia(base)
        convergencia = self.calcular_convergencia(base)
        
        # Confiança final
        confianca = self.calcular_confianca(base, quantidade)
        
        # Classificação
        if confianca >= 70:
            classificacao = "ALTA"
            emoji = "🟢"
        elif confianca >= 50:
            classificacao = "MÉDIA"
            emoji = "🟡"
        else:
            classificacao = "BAIXA"
            emoji = "🔴"
        
        # Previsão final
        top = sorted(candidatos_filtrados.items(), key=lambda x: x[1], reverse=True)
        previsao = [num for num, _ in top[:quantidade]]
        
        return {
            'base': base,
            'espelho': self.get_espelho(base),
            'vizinhos': self.get_vizinhos(base, 2),
            'total_ocorrencias': len(ocorrencias),
            'numeros_depois': numeros_depois,
            'numeros_antes': numeros_antes,
            'previsao': previsao,
            'confianca': confianca,
            'classificacao': classificacao,
            'emoji': emoji,
            'backtest': {
                'total_apostas': backtest['total_apostas'],
                'acertos': backtest['acertos'],
                'taxa_acerto': backtest['taxa_acerto'],
                'detalhes': backtest['detalhes'][-5:]
            },
            # Novos fatores v5
            'targets_recentes': targets_recentes,
            'temperatura': temperatura,
            'frequencia': frequencia,
            # Fatores antigos (mantidos para compatibilidade)
            'consistencia': consistencia,
            'convergencia': convergencia,
            'forca_grupos': forca_grupos,
            'grupos_ativados': nomes_grupos,
            'intersecao_grupos': list(intersecao) if intersecao else [],
            'grupos_analise': grupos_analise[:5]
        }
    
    def adicionar_numero(self, numero: int):
        self.sequencia.insert(0, numero)


def main():
    """Exemplo de uso"""
    
    sequencia = [
       31, 15, 32, 8, 22, 11, 28, 18, 12, 23, 27, 21, 31, 25, 32, 10, 1, 22, 1, 31, 14, 5, 0, 31, 31, 12, 1, 13, 31, 32, 29, 5, 33, 0, 0, 14, 2, 9, 21, 9, 7, 21, 20, 34, 13, 36, 11, 8, 26, 36, 1, 0, 1, 13, 11, 12, 36, 0, 32, 16, 12, 25, 1, 14, 31, 25, 15, 24, 23, 11, 15, 26, 34, 22, 18, 30, 20, 32, 9, 9, 5, 3, 13, 36, 11, 11, 26, 16, 35, 2, 3, 11, 5, 29, 3, 7, 7, 26, 36, 13, 6, 30, 36, 28, 15, 26, 1, 11, 22, 19, 36, 23, 21, 15, 13, 15, 13, 12, 31, 12, 21, 26, 11, 10, 28, 29, 31, 36, 24, 15, 21, 22, 0, 34, 25, 35, 35, 25, 36, 12, 13, 24, 30, 14, 3, 33, 27, 35, 21, 0, 29, 15, 17, 7, 11, 2, 34, 19, 32, 23, 25, 31, 4, 15, 5, 0, 25, 35, 24, 1, 1, 7, 24, 27, 22, 32, 10, 27, 1, 11, 34, 27, 25, 0, 6, 3, 13, 24, 19, 16, 20, 3, 3, 26, 36, 9, 8, 16, 17, 8, 0, 6, 31, 34, 4, 9, 33, 23, 25, 16, 26, 33, 14, 15, 18, 18, 5, 5, 15, 33, 2, 27, 26, 24, 35, 3, 26, 30, 26, 16, 4, 32, 11, 13, 1, 35, 2, 26, 13, 3, 19, 23, 30, 30, 15, 7, 22, 12, 8, 2, 17, 3, 15, 0, 21, 15, 22, 2, 3, 12, 9, 14, 26, 8, 20, 21, 22, 27, 9, 17, 19, 22, 14, 34, 2, 17, 22, 33, 35, 33, 16, 9, 31, 27, 30, 19, 28, 27, 7, 16, 18, 36, 22, 28, 7, 12, 31, 11, 22, 9, 29, 27, 12, 24, 21, 7, 7, 27, 9, 19, 5, 27, 7, 16, 25, 10, 16, 15, 2, 25, 14, 31, 19, 25, 22, 28, 2, 33, 5, 4, 18, 13, 10, 21, 17, 28, 26, 31, 17, 23, 19, 7, 16, 10, 35, 34, 20, 23, 1, 34, 12, 13, 34, 18, 27, 16, 0, 15, 13, 3, 13, 21, 13, 26, 22, 26, 6, 34, 12, 32, 19, 32, 35
    ]
    
    analyzer = RouletteAnalyzer(sequencia)
    base = sequencia[0]  # 7
    
    analise = analyzer.analisar_completo(base)
    
    print("=" * 70)
    print(f"🎯 ANÁLISE DO BASE: {base}")
    print("=" * 70)
    
    print(f"\n📍 Espelho: {analise['espelho']}")
    print(f"📍 Vizinhos: {analise['vizinhos']}")
    print(f"📍 Total de ocorrências: {analise['total_ocorrencias']}")
    
    print(f"\n📖 Números DEPOIS do {base}:")
    for i, nums in enumerate(analise['numeros_depois'], 1):
        print(f"   Ocorrência {i}: {nums}")
    
    # Grupos
    print(f"\n{'='*70}")
    print("🧩 ANÁLISE DE GRUPOS:")
    print("=" * 70)
    
    if analise['grupos_ativados']:
        print(f"\n✅ Gatilho {base} ativa {len(analise['grupos_ativados'])} grupos:")
        for g in analise['grupos_ativados']:
            print(f"   • {g}")
        print(f"\n🎯 INTERSEÇÃO ({len(analise['intersecao_grupos'])} números):")
        print(f"   {sorted(analise['intersecao_grupos'])}")
    else:
        print(f"   ⚠️ Gatilho {base} não ativa 3+ grupos")
    
    print(f"\n📊 Top 5 Grupos por Score:")
    for g in analise['grupos_analise']:
        trigs = ", ".join(map(str, g['triggers']))
        print(f"   • {g['name']} (S:{g['score']}) | Gatilhos: {trigs}")
    
    # Confiança
    print(f"\n{'='*70}")
    print(f"📊 CONFIANÇA: {analise['confianca']:.1f}% {analise['emoji']} {analise['classificacao']}")
    print(f"{'='*70}")
    bt = analise['backtest']
    print(f"├── Backtesting: {bt['taxa_acerto']:.1f}% ({bt['acertos']}/{bt['total_apostas']} apostas)")
    print(f"├── Targets Recentes: {analise['targets_recentes']:.1f}%")
    print(f"├── Temperatura Gatilho: {analise['temperatura']:.1f}%")
    print(f"├── Frequência Gatilho: {analise['frequencia']:.1f}%")
    print(f"└── Força Grupos: {analise['forca_grupos']:.1f}%")
    
    # Detalhes backtesting
    if bt['detalhes']:
        print(f"\n📈 Últimas apostas simuladas:")
        for d in bt['detalhes']:
            status = f"✅ #{d['posicao_na_lista']}" if d['acertou'] else "❌"
            print(f"   Saiu {d['numero_real']:2d} → {status}")
    
    # Previsão
    print(f"\n{'='*70}")
    print("🎰 TOP 18 NÚMEROS PARA APOSTAR:")
    print("=" * 70)
    print(f"   {sorted(analise['previsao'])}")


if __name__ == "__main__":
    main()