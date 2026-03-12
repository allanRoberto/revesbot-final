"""
Padrão Soma Retorno - Análise completa a cada chamada
"""

# Configurações
MIN_ROUNDS = 15
MIN_CONFIRMATIONS = 2

def get_digit_sum(number):
    """Soma dígitos até ficar um único dígito"""
    digit_sum = sum(int(d) for d in str(number))
    while digit_sum >= 10:
        digit_sum = sum(int(d) for d in str(digit_sum))
    return digit_sum

def get_numbers_for_sum(target_sum):
    """Retorna números que têm a soma igual ao target"""
    return [num for num in range(37) if get_digit_sum(num) == target_sum]

def process_roulette(roulette, numbers):
    """
    Analisa TODO o histórico e identifica gatilhos pendentes
    """
    if len(numbers) < 20:
        return None
    
    # Analisa o histórico completo e identifica todos os gatilhos
    gatilhos = {}
    
    # Para cada número no histórico, verifica se ele apareceu antes
    for i in range(len(numbers)):
        current_num = numbers[i]
        
        # Procura a ocorrência anterior deste número
        for j in range(i + 1, len(numbers) - 1):
            if numbers[j] == current_num:
                # Encontrou ocorrência anterior, pega o número que estava atrás
                behind = numbers[j + 1]
                digit_sum = get_digit_sum(behind)
                target_numbers = get_numbers_for_sum(digit_sum)
                
                key = f"{current_num}_{digit_sum}"
                
                # Se ainda não registrou este gatilho
                if key not in gatilhos:
                    gatilhos[key] = {
                        'targets': target_numbers,
                        'first_position': j,  # Posição onde foi ativado
                        'confirmations': 0,
                        'paid': False,
                        'paid_at': None
                    }
                
                # Adiciona confirmação
                gatilhos[key]['confirmations'] += 1
                
                # Verifica se foi pago entre a posição j e i
                for k in range(j - 1, i, -1):
                    if k >= 0 and numbers[k] in target_numbers:
                        gatilhos[key]['paid'] = True
                        gatilhos[key]['paid_at'] = k
                        break
                
                break  # Só precisa da primeira ocorrência anterior
    
    # Filtra apenas gatilhos NÃO pagos e calcula rodadas pendentes
    gatilhos_pendentes = {}
    for key, info in gatilhos.items():
        if not info['paid']:
            # Calcula há quantas rodadas está pendente (desde a primeira ativação)
            rounds_pending = info['first_position']
            
            if rounds_pending >= MIN_ROUNDS and info['confirmations'] >= MIN_CONFIRMATIONS:
                gatilhos_pendentes[key] = {
                    'targets': info['targets'],
                    'rounds': rounds_pending,
                    'confirmations': info['confirmations'],
                    'score': rounds_pending * info['confirmations']
                }
    
    # Se não há gatilhos pendentes quentes, retorna None
    if not gatilhos_pendentes:
        return None
    
    # Ordena por score e pega o MELHOR gatilho
    sorted_triggers = sorted(gatilhos_pendentes.items(), key=lambda x: x[1]['score'], reverse=True)
    best_trigger_key, best_trigger_info = sorted_triggers[0]
    
    # Extrai o número do gatilho (antes do _)
    trigger_number = int(best_trigger_key.split('_')[0])
    
    # Usa APENAS os números da soma do melhor gatilho (sempre 4 números)
    targets = best_trigger_info['targets']
    
    # Monta o sinal
    signal = {
        'roulette_id': roulette['slug'],
        'roulette_name': roulette['name'],
        'roulette_url': roulette['url'],
        'triggers': [trigger_number],  # O NÚMERO que ativa o gatilho
        'targets': targets,
        'bets': targets,
        'snapshot': numbers[:50],
        'status': 'processing',
        'pattern': 'SOMA_RETORNO',
        'passed_spins': best_trigger_info['rounds'],
        'spins_required': 3,
        'message': f"Quando sair {trigger_number}, aposte nos números de soma {best_trigger_key.split('_')[1]} - Pendente há {best_trigger_info['rounds']} rodadas",
        'tags': ['soma_digitos', 'gatilho_quente']
    }
    
    print(f"🔥 SINAL DETECTADO: {best_trigger_key} - {len(targets)} números")
    return signal