# Sistema Simples de Ranking para Pendência de Pagamento

def get_sum(number):
    """Calcula a soma dos dígitos de um número"""
    if number == 0:
        return 0
    total = sum(int(digit) for digit in str(number))
    # Se maior que 10, soma novamente
    while total > 10:
        total = sum(int(digit) for digit in str(total))
    return total


def get_numbers_with_sum(target_sum):
    """Retorna todos os números da roleta com a soma especificada"""
    return [num for num in range(37) if get_sum(num) == target_sum]


# Dicionário global para manter os scores
sum_scores = {i: 0.0 for i in range(11)}  # Somas de 0 a 10


def update_ranking(numbers):
    """
    Atualiza o ranking baseado nos números
    
    Args:
        numbers: Lista de números (mais recente primeiro)
    
    Returns:
        Dict com sinal se alguma soma estiver quente, None caso contrário
    """
    global sum_scores
    
    if len(numbers) < 50:
        return None
    
    # Número que acabou de sair
    current = numbers[0]
    current_sum = get_sum(current)
    
    # Remove 1 ponto da soma que saiu (foi pago)
    sum_scores[current_sum] -= 1
    
    # Procura pendências do número atual
    for i in range(10, 50):  # Busca de 10 a 50 posições atrás
        if numbers[i] == current:
            # Achou o número, vê qual estava antes dele
            if i + 1 < len(numbers):
                paired = numbers[i + 1]
                paired_sum = get_sum(paired)
                
                # Adiciona 1 ponto para essa soma (pendência)
                sum_scores[paired_sum] += 1
                
                # Se encontrou uma pendência, para
                break
    
    # Verifica se alguma soma está muito quente (>= 3 pontos)
    for soma, score in sum_scores.items():
        if score >= 3:
            # Gera o sinal
            signal = {
                'trigger_sum': soma,
                'score': score,
                'targets': get_numbers_with_sum(soma),
                'confidence': min(0.6 + score * 0.1, 0.95)
            }
            
            # Reduz o score pela metade após gerar sinal
            sum_scores[soma] = score / 2
            
            return signal
    
    return None


def process_roulette(roulette, numbers):
    """
    Versão simplificada com ranking automático
    
    Args:
        roulette: Objeto da roleta
        numbers: Lista de números do mais recente para o mais antigo
    
    Returns:
        Dict com o sinal ou None
    """
    # Atualiza o ranking e verifica se há sinal
    signal = update_ranking(numbers)

    print(signal)
    
    if signal:
        return {
            'pattern_name': 'PENDENCIA_RANKING_AUTO',
            'targets': signal['targets'],
            'confidence': signal['confidence'],
            'score': signal['score'],
            'trigger_sum': signal['trigger_sum'],
            'description': f"Soma {signal['trigger_sum']} está quente! Score: {signal['score']:.1f}"
        }
    
    return None


def get_current_ranking():
    """Retorna o ranking atual das somas"""
    global sum_scores
    ranking = [(soma, score) for soma, score in sum_scores.items() if score > 0]
    ranking.sort(key=lambda x: x[1], reverse=True)
    return ranking


# Teste simples
if __name__ == "__main__":
    print("TESTE DO SISTEMA SIMPLES DE RANKING")
    print("=" * 40)
    
    # Simula sequência onde 29 sempre vem com números de soma 5
    test_numbers = []
    
    # Adiciona padrão repetitivo
    for _ in range(3):
        test_numbers.extend([32, 29])  # 32 tem soma 5
        test_numbers.extend([10, 18, 24, 35, 12])  # Números aleatórios
    
    # Adiciona mais números para completar
    test_numbers.extend([15, 7, 11, 22, 8, 13, 19, 25, 30])
    
    # Inverte para ficar mais recente primeiro
    test_numbers.reverse()
    
    print(f"Sequência de teste ({len(test_numbers)} números)")
    print(f"Últimos 10: {test_numbers[:10]}")
    
    # Testa o processo
    print("\nProcessando números um por um...")
    
    for i in range(len(test_numbers) - 1, 10, -1):
        current_sequence = test_numbers[:i]
        
        # Processa
        result = process_roulette(None, current_sequence)
        
        if result:
            print(f"\n🎯 SINAL DETECTADO!")
            print(f"   Soma {result['trigger_sum']} com score {result['score']:.1f}")
            print(f"   Apostar em: {result['targets']}")
            print(f"   Confiança: {result['confidence']:.2%}")
            break
    
    # Mostra ranking final
    print("\nRanking final das somas:")
    ranking = get_current_ranking()
    for soma, score in ranking[:5]:
        if score > 0:
            print(f"  Soma {soma}: {score:.1f} pontos - Números: {get_numbers_with_sum(soma)}")