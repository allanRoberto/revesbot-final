from helpers.utils.get_figure import get_figure
from helpers.utils.filters import first_index_after, soma_digitos


def get_all_numbers_with_sum(target_sum):
    """
    Retorna todos os números da roleta (0-36) que têm a soma dos dígitos igual ao target_sum
    """
    numbers = []
    for num in range(37):  # 0 a 36
        if get_figure(num) == target_sum:
            numbers.append(num)
    return numbers


def check_if_paid(numbers, start_idx, end_idx, target_numbers):
    """
    Verifica se algum dos números alvo já apareceu entre start_idx e end_idx
    Retorna True se já foi pago, False caso contrário
    """
    for i in range(start_idx, min(end_idx, len(numbers))):
        if numbers[i] in target_numbers:
            return True
    return False


def calculate_heat_level(distance):
    """
    Calcula o nível de "calor" do sinal baseado na distância
    Quanto maior a distância sem pagamento, mais quente está o sinal
    """
    if distance <= 5:
        return 1  # Frio
    elif distance <= 10:
        return 2  # Morno
    elif distance <= 15:
        return 3  # Quente
    else:
        return 4  # Muito quente


def get_sum_pending(number, history) :
    figure = soma_digitos(number);
    targets = get_figure(figure);


def check_pending_paid(numbers, start, end, target) :

        results = 0

        for i in range(start, min(end, len(numbers))):

            second_confirmation = first_index_after(numbers, numbers[i], start)
            
            if second_confirmation + 1 < len(numbers):
                number_paired = numbers[second_confirmation + 1]
            else :
                continue
            
            target_second_sum = get_figure(soma_digitos(number_paired))

            if(target_second_sum == target) :
                paid = check_if_paid(numbers, 0, i, target_second_sum)


                if(paid) :
                    continue
                else :
                    results += 1
                
            else : 
                continue
            
        return results

def process_roulette(roulette, numbers):
    """
    Detecta o padrão de pendência de pagamento no retorno do número
    
    Lógica do padrão:
    1. Pega o número na posição p9 (10º mais recente)
    2. Busca quando esse número apareceu anteriormente
    3. Identifica qual número veio junto com ele naquela vez
    4. Calcula a soma dos dígitos desse número pareado
    5. Verifica se DEPOIS do p9 (posições 0-8) já apareceu algum número com essa soma
    6. Se não apareceu, há uma pendência de pagamento
    
    Args:
        roulette: Objeto da roleta
        numbers: Lista de números do mais recente para o mais antigo
    
    Returns:
        Dict com o sinal ou None se não houver padrão
    """
    idxs = (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10)
    
    # Pego os últimos 11 números (0 é o mais recente)
    recent_numbers = [numbers[i] for i in idxs if i < len(numbers)]
    
    if len(recent_numbers) < 11:
        return None
    
    p0, p1, p2, p3, p4, p5, p6, p7, p8, p9, p10 = recent_numbers
    
    # Busco a segunda ocorrência do número p9 (10º número mais recente)
    # Começando da posição 10 (após o p9) até 50 números atrás
    second_index = first_index_after(numbers, p9, 10)

    # Se não encontrou segunda ocorrência ou está muito longe
    if second_index is None or second_index >= 49:
        return None
    
    # Pego o número que veio ANTES do p9 na sua ocorrência anterior
    if second_index + 1 < len(numbers):
        number_paired_with_p9 = numbers[second_index + 1]
    else:
        return None
    

    if(number_paired_with_p9 == 0 or number_paired_with_p9 == 29) :
        return None
    # Calculo a soma dos dígitos do número pareado
    target_sum = get_figure(soma_digitos(number_paired_with_p9))

    results = check_pending_paid(numbers, 8, 50, target_sum)

    if results >= 1:

        
    
        # Pego todos os números que têm essa mesma soma
        target_numbers = [*target_sum, number_paired_with_p9]

        triggers = []

        for i in target_numbers :
            trigger_index = first_index_after(numbers, i, 8);

            if (numbers[trigger_index - 1] in target_numbers) :
                return None
            else :
                triggers.insert(0, numbers[trigger_index - 1])
      
        return {
                "roulette_id": roulette['slug'],
                "roulette_name" : roulette["name"],
                "roulette_url" : roulette["url"],
                "pattern" : "SOMA_PENDENTE",
                "triggers":[*triggers],
                "targets":[*target_numbers],
                "bets":[*target_numbers],
                "passed_spins" : 0,
                "spins_required" : 0,
                "spins_count": 0,
                "snapshot":numbers[:50],
                "status":"waiting",
                "message": "Gatilho encontrado!",
                "tags": [],  # Adicionando as tags coletadas
        }



def analyze_pending_payments(numbers, depth=10):
    """
    Analisa múltiplas pendências de pagamento em uma janela de números
    
    Args:
        numbers: Lista de números históricos
        depth: Quantos números analisar (começando do índice 9)
    
    Returns:
        Lista de sinais pendentes ordenados por prioridade
    """
    pending_signals = []
    
    # Começamos do índice 9 para ter espaço para verificar pagamentos
    for i in range(9, min(9 + depth, len(numbers) - 1)):
        # Para cada número na posição i, verifico se ele tem pendência
        current_number = numbers[i]
        
        # Busco ocorrência anterior deste número
        previous_index = first_index_after(numbers, current_number, i + 1, 100)
        
        if previous_index is None or previous_index >= 99:
            continue
            
        # Verifico o número que estava pareado na ocorrência anterior
        if previous_index + 1 < len(numbers):
            paired_number = numbers[previous_index + 1]
            target_sum = get_figure(paired_number)
            target_numbers = get_all_numbers_with_sum(target_sum)
            
            # Verifico se ainda não foi pago DEPOIS do número atual (índices 0 até i-1)
            if not check_if_paid(numbers, 0, i, target_numbers):
                heat_level = calculate_heat_level(i)
                
                signal = {
                    'pattern_name': 'PENDENCIA_PAGAMENTO_RETORNO',
                    'trigger': current_number,
                    'targets': target_numbers,
                    'heat_level': heat_level,
                    'distance_without_payment': i,  # Quantos números vieram depois sem pagar
                    'original_paired_number': paired_number,
                    'target_sum': target_sum,
                    'confidence': min(0.5 + (heat_level * 0.1), 0.9),
                    'priority': heat_level * i,  # Prioridade baseada em calor e distância
                    'position': i,
                    'description': f"Pendência: {current_number} (pos {i}) veio com {paired_number} há {previous_index} rodadas"
                }
                pending_signals.append(signal)
    
    # Ordeno por prioridade (maior prioridade primeiro)
    pending_signals.sort(key=lambda x: x['priority'], reverse=True)
    
    return pending_signals


