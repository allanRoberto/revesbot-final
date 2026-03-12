#!/usr/bin/env python3
"""
Padrão de Machine Learning - Triangulação
Integração direta com o modelo treinado (sem API)
"""

import numpy as np
import pandas as pd
import joblib
import json
import logging
from typing import List, Dict, Optional
from datetime import datetime
import os

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========================================
# VARIÁVEIS GLOBAIS PARA O MODELO
# ========================================
ML_MODEL = None
ML_ENCODER = None
ML_CONFIG = None
ML_PREPARADOR = None
MODEL_LOADED = False

# Configurações
CONFIANCA_MINIMA = 0.70  # Mínimo 70% para gerar sinal
CONFIANCA_PREMIUM = 0.80  # 80%+ para sinal premium
MIN_HISTORICO = 500  # Mínimo de resultados necessários

# ========================================
# CLASSE PREPARADOR DE DADOS
# ========================================
class PreparadorDadosTriangulacao:
    """Prepara dados para o modelo ML"""
    
    def extrair_features_triangulacao(self, historico: List[int], posicao_atual: int) -> Optional[Dict]:
        """Extrai features do padrão de triangulação"""
        
        if posicao_atual >= len(historico):
            return None
            
        numero_atual = historico[posicao_atual]
        
        # Encontrar 2ª e 3ª ocorrências
        ocorrencias = []
        for i in range(posicao_atual, len(historico)):
            if historico[i] == numero_atual:
                ocorrencias.append(i)
                if len(ocorrencias) == 3:
                    break
        
        if len(ocorrencias) < 3:
            return None
        
        N1_pos = posicao_atual
        N2_pos = ocorrencias[1]
        N3_pos = ocorrencias[2]
        
        # Números A e B
        if N3_pos >= 2:
            numero_A = historico[N3_pos - 1]
            numero_B = historico[N3_pos - 2]
        else:
            return None
        
        # Verificar janela expandida (6-15)
        resultado_janela = self.analisar_janela(historico, N1_pos, numero_A, numero_B)
        
        # Calcular features
        features = {
            # Identificadores
            'numero_gatilho': numero_atual,
            'numero_A': numero_A,
            'numero_B': numero_B,
            
            # Distâncias
            'distancia_N1_N2': N2_pos - N1_pos,
            'distancia_N2_N3': N3_pos - N2_pos,
            'distancia_total': N3_pos - N1_pos,
            'razao_distancias': (N2_pos - N1_pos) / (N3_pos - N2_pos) if (N3_pos - N2_pos) > 0 else 0,
            
            # Frequências
            'freq_A_ultimos_30': self.contar_frequencia(historico, numero_A, N1_pos, 30),
            'freq_B_ultimos_30': self.contar_frequencia(historico, numero_B, N1_pos, 30),
            'freq_A_ultimos_100': self.contar_frequencia(historico, numero_A, N1_pos, 100),
            'freq_B_ultimos_100': self.contar_frequencia(historico, numero_B, N1_pos, 100),
            
            # Proximidade
            'diferenca_A_gatilho': abs(numero_A - numero_atual),
            'diferenca_B_gatilho': abs(numero_B - numero_atual),
            'diferenca_A_B': abs(numero_A - numero_B),
            
            # Ciclos
            'ciclo_gatilho': self.calcular_ciclo(historico, numero_atual, N1_pos),
            'ciclo_A': self.calcular_ciclo(historico, numero_A, N1_pos),
            'ciclo_B': self.calcular_ciclo(historico, numero_B, N1_pos),
            
            # Contexto
            'numeros_unicos_20': len(set(historico[max(0, N1_pos-20):N1_pos])) if N1_pos > 0 else 0,
            'tendencia_repeticao': self.calcular_tendencia(historico, N1_pos),
        }
        
        # Adicionar informações do resultado para uso posterior
        features['_resultado_janela'] = resultado_janela
        
        return features
    
    def analisar_janela(self, historico: List[int], pos_N1: int, 
                        numero_A: int, numero_B: int) -> Dict:
        """Analisa janela expandida 6-15"""
        resultado = {
            'apareceu_A': False,
            'apareceu_B': False,
            'posicao_primeiro': 99,
            'classificacao': 'NENHUM'
        }
        
        for i in range(6, min(16, pos_N1)):
            if pos_N1 - i < 0:
                break
            
            num = historico[pos_N1 - i]
            
            if num == numero_A and not resultado['apareceu_A']:
                resultado['apareceu_A'] = True
                if resultado['posicao_primeiro'] == 99:
                    resultado['posicao_primeiro'] = i
                    
            if num == numero_B and not resultado['apareceu_B']:
                resultado['apareceu_B'] = True
                if resultado['posicao_primeiro'] == 99:
                    resultado['posicao_primeiro'] = i
        
        # Classificar resultado
        if resultado['apareceu_A'] and resultado['apareceu_B']:
            resultado['classificacao'] = 'AMBOS'
        elif resultado['apareceu_A']:
            resultado['classificacao'] = 'A'
        elif resultado['apareceu_B']:
            resultado['classificacao'] = 'B'
        else:
            resultado['classificacao'] = 'NENHUM'
        
        return resultado
    
    def contar_frequencia(self, historico: List[int], numero: int, 
                         posicao: int, janela: int) -> int:
        """Conta frequência de um número em uma janela"""
        inicio = max(0, posicao - janela)
        return historico[inicio:posicao].count(numero)
    
    def calcular_ciclo(self, historico: List[int], numero: int, 
                      posicao: int, max_back: int = 200) -> float:
        """Calcula ciclo médio de aparição"""
        posicoes = []
        look_back = min(posicao, max_back)
        
        for i in range(max(0, posicao - look_back), posicao):
            if historico[i] == numero:
                posicoes.append(i)
        
        if len(posicoes) < 2:
            return 50.0
        
        distancias = [posicoes[i] - posicoes[i-1] for i in range(1, len(posicoes))]
        return float(np.mean(distancias)) if distancias else 50.0
    
    def calcular_tendencia(self, historico: List[int], posicao: int) -> int:
        """Calcula tendência de repetições"""
        if posicao < 60:
            return 0
        
        recente = historico[posicao-30:posicao]
        anterior = historico[posicao-60:posicao-30]
        
        rep_recente = len(recente) - len(set(recente))
        rep_anterior = len(anterior) - len(set(anterior))
        
        return rep_recente - rep_anterior

# ========================================
# FUNÇÕES DE INICIALIZAÇÃO
# ========================================
def init_ml(model_path: str = None):
    """
    Inicializa o modelo ML
    Deve ser chamada no início do main.py
    
    Args:
        model_path: Caminho para os arquivos do modelo (sem extensão)
                   Ex: 'modelo_pragmatic-brazilian-roulette'
    """
    global ML_MODEL, ML_ENCODER, ML_CONFIG, ML_PREPARADOR, MODEL_LOADED
    
    try:
        # Usar caminho padrão se não fornecido
        if not model_path:
            # Tenta encontrar modelo no diretório patterns/machine/
            base_dir = os.path.dirname(os.path.abspath(__file__))
            model_path = os.path.join(base_dir, 'modelo_pragmatic-brazilian-roulette')
        
        # Remover extensão se fornecida
        model_path = model_path.replace('.pkl', '').replace('.json', '')
        
        print(f"[ML] Carregando modelo de: {model_path}")
        
        # Carregar modelo Random Forest
        rf_path = f'{model_path}_rf.pkl'
        if os.path.exists(rf_path):
            ML_MODEL = joblib.load(rf_path)
            print(f"[ML] ✅ Modelo RF carregado")
        else:
            # Tentar modelo XGBoost como fallback
            xgb_path = f'{model_path}_xgb.pkl'
            if os.path.exists(xgb_path):
                ML_MODEL = joblib.load(xgb_path)
                print(f"[ML] ✅ Modelo XGB carregado")
            else:
                raise FileNotFoundError(f"Modelo não encontrado: {rf_path}")
        
        # Carregar encoder
        ML_ENCODER = joblib.load(f'{model_path}_encoder.pkl')
        print(f"[ML] ✅ Encoder carregado")
        
        # Carregar configuração
        with open(f'{model_path}_config.json', 'r') as f:
            ML_CONFIG = json.load(f)
        print(f"[ML] ✅ Configuração carregada")
        
        # Criar preparador
        ML_PREPARADOR = PreparadorDadosTriangulacao()
        print(f"[ML] ✅ Preparador inicializado")
        
        MODEL_LOADED = True
        
        # Mostrar métricas do modelo
        if 'metricas' in ML_CONFIG:
            metricas = ML_CONFIG['metricas']
            print(f"[ML] 📊 Métricas do modelo:")
            print(f"     - Acurácia treino: {metricas.get('rf_train', 0)*100:.1f}%")
            print(f"     - Acurácia teste: {metricas.get('rf_test', 0)*100:.1f}%")
        
        print(f"[ML] ✅ Sistema ML inicializado com sucesso!")
        return True
        
    except Exception as e:
        print(f"[ML] ❌ Erro ao carregar modelo: {e}")
        import traceback
        traceback.print_exc()
        MODEL_LOADED = False
        return False

# ========================================
# FUNÇÃO DE PREVISÃO
# ========================================
def fazer_previsao_ml(historico: List[int], posicao: int) -> Optional[Dict]:
    """
    Faz previsão usando o modelo carregado
    
    Args:
        historico: Lista de números em ordem cronológica
        posicao: Posição do gatilho
        
    Returns:
        Dict com previsão ou None
    """
    global ML_MODEL, ML_ENCODER, ML_CONFIG, ML_PREPARADOR
    
    if not MODEL_LOADED:
        return None
    
    try:
        # Extrair features
        features = ML_PREPARADOR.extrair_features_triangulacao(historico, posicao)
        
        if not features:
            return None
        
        # Guardar informações extras
        numero_A = features['numero_A']
        numero_B = features['numero_B']
        numero_gatilho = features['numero_gatilho']
        
        # Preparar features para o modelo (remover campos não usados no treino)
        features_model = {k: v for k, v in features.items() 
                         if not k.startswith('_') and k not in ['numero_gatilho', 'numero_A', 'numero_B']}
        
        # Criar DataFrame com as features na ordem correta
        features_columns = ML_CONFIG['features_columns']
        X = pd.DataFrame([features_model])[features_columns]
        
        # Fazer previsão
        predicao = ML_MODEL.predict(X)[0]
        resultado = ML_ENCODER.inverse_transform([predicao])[0]
        
        # Calcular probabilidades (se disponível)
        try:
            probs = ML_MODEL.predict_proba(X)[0]
            confianca = float(max(probs))
            probabilidades = {}
            for i, classe in enumerate(ML_ENCODER.classes_):
                probabilidades[classe] = float(probs[i])
        except:
            # Se o modelo não tem predict_proba, usar confiança fixa
            confianca = 0.75
            probabilidades = {resultado: confianca}
        
        return {
            'previsao': resultado,
            'confianca': confianca,
            'probabilidades': probabilidades,
            'numero_gatilho': numero_gatilho,
            'numero_A': numero_A,
            'numero_B': numero_B
        }
        
    except Exception as e:
        logger.error(f"Erro na previsão ML: {e}")
        return None

# ========================================
# FUNÇÃO PRINCIPAL DO PADRÃO
# ========================================
def process_roulette(roulette: Dict, numbers: List[int]) -> Optional[Dict]:
    """
    Processa padrão de triangulação com ML
    
    Args:
        roulette: Dict com slug, name e url da roleta
        numbers: Lista de números (mais recente primeiro)
        
    Returns:
        Dict com sinal formatado ou None
    """
    
    # Verificar se modelo está carregado
    if not MODEL_LOADED:
        # Tentar carregar modelo se ainda não foi carregado
        if not init_ml():
            return None
    
    # Verificar se temos dados suficientes
    if len(numbers) < MIN_HISTORICO:
        return None
    
    # Converter para ordem cronológica (mais antigo primeiro)
    historico = list(reversed(numbers))
    
    # Buscar melhor gatilho (testar últimas 3 posições)
    melhor_resultado = None
    melhor_confianca = 0
    
    for offset in range(min(3, len(historico))):
        posicao = len(historico) - 1 - offset
        
        if posicao < MIN_HISTORICO:
            continue
        
        resultado = fazer_previsao_ml(historico, posicao)
        
        if resultado and resultado['confianca'] > melhor_confianca:
            melhor_confianca = resultado['confianca']
            melhor_resultado = resultado
            melhor_resultado['offset'] = offset
    
    # Verificar se encontrou sinal válido
    if not melhor_resultado or melhor_confianca < CONFIANCA_MINIMA:
        return None
    
    # Gerar sinal no formato esperado pelo sistema
    return gerar_sinal_formatado(melhor_resultado, roulette, numbers)

def gerar_sinal_formatado(resultado_ml: Dict, roulette: Dict, numbers: List[int]) -> Dict:
    """
    Formata o sinal no padrão esperado pelo sistema
    
    Args:
        resultado_ml: Resultado da previsão ML
        roulette: Dados da roleta
        numbers: Lista de números originais
        
    Returns:
        Dict com sinal formatado
    """
    
    confianca = resultado_ml['confianca']
    previsao = resultado_ml['previsao']
    numero_A = resultado_ml['numero_A']
    numero_B = resultado_ml['numero_B']
    
    # Determinar números para apostar
    if previsao == 'A':
        targets = [numero_A]
    elif previsao == 'B':
        targets = [numero_B]
    elif previsao == 'AMBOS':
        targets = [numero_A, numero_B]
    else:
        return None  # NENHUM não gera sinal
    
    # Determinar força do sinal
    if confianca >= CONFIANCA_PREMIUM:
        nivel = 'PREMIUM'
        gales = 3
        emoji = '💎'
        tags = ['ML', 'PREMIUM', 'TRIANGULACAO']
    elif confianca >= 0.75:
        nivel = 'FORTE'
        gales = 2
        emoji = '🔥'
        tags = ['ML', 'FORTE', 'TRIANGULACAO']
    else:
        nivel = 'MODERADO'
        gales = 1
        emoji = '✅'
        tags = ['ML', 'MODERADO', 'TRIANGULACAO']
    
    # Criar mensagem
    message = f"{emoji} ML Triangulação {nivel}\n"
    message += f"Confiança: {confianca*100:.0f}%\n"
    message += f"Apostar: {', '.join(map(str, targets))}\n"
    message += f"Janela: 6-15 giros"
    
    # Snapshot dos últimos números
    snapshot = numbers[:20] if len(numbers) >= 20 else numbers
    
    # Retornar sinal no formato esperado
    return {
        "roulette_id": roulette["slug"],
        "roulette_name": roulette["name"],
        "roulette_url": roulette.get("url", ""),
        "triggers": [resultado_ml['numero_gatilho']],  # Gatilho que ativou o sinal
        "targets": targets,  # Números para apostar
        "bets": targets,  # Mesmo que targets
        "snapshot": snapshot,  # Últimos números
        "status": "waiting",
        "pattern": "ML_TRIANGULACAO",
        "passed_spins": 0,
        "spins_required": 15,  # Janela máxima
        "gales": gales,  # Número de tentativas
        "message": message,
        "tags": tags,
        "metadata": {
            "confianca": confianca,
            "nivel": nivel,
            "previsao": previsao,
            "numero_A": numero_A,
            "numero_B": numero_B,
            "probabilidades": resultado_ml.get('probabilidades', {})
        }
    }

# ========================================
# TESTE STANDALONE
# ========================================
if __name__ == "__main__":
    # Teste do módulo
    print("=" * 60)
    print("TESTE DO MÓDULO MACHINE LEARNING")
    print("=" * 60)
    
    # Inicializar modelo
    if init_ml():
        # Simular dados de teste
        test_numbers = [22, 15, 3, 28, 9, 31, 14, 7, 22, 33] + list(range(500))
        
        test_roulette = {
            "slug": "pragmatic-brazilian-roulette",
            "name": "Brazilian Roulette",
            "url": "https://example.com"
        }
        
        # Processar
        signal = process_roulette(test_roulette, test_numbers)
        
        if signal:
            print("\n✅ SINAL GERADO:")
            print(json.dumps(signal, indent=2, ensure_ascii=False))
        else:
            print("\n❌ Nenhum sinal gerado")
    else:
        print("❌ Falha ao inicializar modelo")