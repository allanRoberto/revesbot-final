"""
ler_puxadas.py

Script para extrair lista de números puxados do JSON gerado
"""

import json
from typing import List, Optional

import os
print(os.getcwd())  # Mostra onde você está
print(os.listdir('.'))


def carregar_analise(arquivo: str = "patterns/analise_puxadas_completa.json") -> dict:
    """
    Carrega o arquivo JSON de análise
    
    Args:
        arquivo: Caminho do arquivo JSON
    
    Returns:
        Dicionário com a análise completa
    """
    with open(arquivo, 'r', encoding='utf-8') as f:
        return json.load(f)


def get_top_puxados(numero_gatilho: int, top_n: int = 18, arquivo: str = "patterns/analise_puxadas_completa.json") -> Optional[List[int]]:
    """
    Retorna a lista dos top N números puxados por um número gatilho
    
    Args:
        numero_gatilho: Número que queremos analisar (0-36)
        top_n: Quantidade de números a retornar (padrão: 18)
        arquivo: Caminho do arquivo JSON
    
    Returns:
        Lista de números ou None se não encontrar
    
    Example:
        >>> puxados = get_top_puxados(1, 18)
        >>> print(puxados)
        [12, 2, 8, 20, 6, 16, 29, ...]
    """
    try:
        # Carrega o JSON
        dados = carregar_analise(arquivo)
        
        # Converte número para string (chave do JSON)
        chave = str(numero_gatilho)
        
        # Verifica se o número existe na análise
        if chave not in dados.get('analise_por_numero', {}):
            print(f"❌ Número {numero_gatilho} não encontrado na análise")
            return None
        
        # Pega a análise do número
        analise = dados['analise_por_numero'][chave]
        
        # Extrai apenas os números (não o objeto completo)
        top_puxados = analise.get('top_puxados', [])
        
        # Retorna lista de números limitada ao top_n
        lista_numeros = [item['numero'] for item in top_puxados[:top_n]]
        
        return lista_numeros
    
    except FileNotFoundError:
        print(f"❌ Arquivo {arquivo} não encontrado")
        return None
    except Exception as e:
        print(f"❌ Erro ao ler arquivo: {e}")
        return None


def get_top_puxados_com_info(numero_gatilho: int, top_n: int = 18, arquivo: str = "analise_puxadas_completa.json") -> Optional[List[dict]]:
    """
    Retorna a lista dos top N números puxados COM informações completas
    
    Args:
        numero_gatilho: Número que queremos analisar (0-36)
        top_n: Quantidade de números a retornar (padrão: 18)
        arquivo: Caminho do arquivo JSON
    
    Returns:
        Lista de dicionários com informações completas
    
    Example:
        >>> puxados = get_top_puxados_com_info(1, 5)
        >>> print(puxados)
        [
            {'numero': 12, 'vezes': 261, 'lift': 1.11, 'prob': 14.6},
            {'numero': 2, 'vezes': 257, 'lift': 1.09, 'prob': 14.3},
            ...
        ]
    """
    try:
        dados = carregar_analise(arquivo)
        chave = str(numero_gatilho)
        
        if chave not in dados.get('analise_por_numero', {}):
            print(f"❌ Número {numero_gatilho} não encontrado na análise")
            return None
        
        analise = dados['analise_por_numero'][chave]
        top_puxados = analise.get('top_puxados', [])[:top_n]
        
        return top_puxados
    
    except FileNotFoundError:
        print(f"❌ Arquivo {arquivo} não encontrado")
        return None
    except Exception as e:
        print(f"❌ Erro ao ler arquivo: {e}")
        return None


def get_todos_puxados() -> dict:
    """
    Retorna todos os números e seus puxados em formato de dicionário
    
    Returns:
        Dict {numero_gatilho: [lista_puxados]}
    
    Example:
        >>> todos = get_todos_puxados()
        >>> print(todos[1])
        [12, 2, 8, 20, 6, 16, 29, ...]
    """
    try:
        dados = carregar_analise()
        resultado = {}
        
        for chave, analise in dados.get('analise_por_numero', {}).items():
            numero = int(chave)
            puxados = [item['numero'] for item in analise.get('top_puxados', [])]
            resultado[numero] = puxados
        
        return resultado
    
    except Exception as e:
        print(f"❌ Erro ao ler arquivo: {e}")
        return {}


# ==========================================
# EXEMPLOS DE USO
# ==========================================

def process_roulette(roulette, numbers) :
    puxados_1 = get_top_puxados(numbers[0], 18);
    return {
            "roulette_id": roulette['slug'],
            "roulette_name" : roulette["name"],
            "roulette_url" : roulette["url"],
            "pattern" : "PUXADOS",
            "triggers": numbers[0],
            "targets":puxados_1,
            "bets": puxados_1,
            "passed_spins" : 0,
            "spins_required" : 0,
            "spins_count": 0,
            "gales" : 2,
            "score" : 0,
            "snapshot":numbers[:10],
            "status":"processing",
            "message" : "Gatilho encontrado!",
            "tags" : [],
            }




if __name__ == "__main__":
    print("🎯 Exemplos de uso do extrator de puxadas\n")
    
    # Exemplo 1: Pegar top 18 do número 1
    print("📋 Exemplo 1: Top 18 números puxados pelo 1")
    puxados_1 = get_top_puxados(1, 18)
    if puxados_1:
        print(f"   Números: {puxados_1}")
        print(f"   Quantidade: {len(puxados_1)}\n")
    
    # Exemplo 2: Pegar top 10 do número 0
    print("📋 Exemplo 2: Top 10 números puxados pelo 0")
    puxados_0 = get_top_puxados(0, 10)
    if puxados_0:
        print(f"   Números: {puxados_0}\n")
    
    # Exemplo 3: Pegar com informações completas
    print("📋 Exemplo 3: Top 5 do número 1 com informações")
    puxados_info = get_top_puxados_com_info(1, 5)
    if puxados_info:
        for item in puxados_info:
            print(f"   {item['numero']}: lift={item['lift']}x, prob={item['prob']}%, vezes={item['vezes']}")
        print()
    
    # Exemplo 4: Testar vários números
    print("📋 Exemplo 4: Top 18 de vários números")
    for num in [1, 7, 13, 27]:
        puxados = get_top_puxados(num, 18)
        if puxados:
            print(f"   Número {num}: {puxados[:5]}... ({len(puxados)} total)")
    
    print("\n" + "="*70)
    print("💡 Uso rápido:")
    print("   puxados = get_top_puxados(1, 18)")
    print("   print(puxados)  # [12, 2, 8, 20, 6, ...]")
    print("="*70)