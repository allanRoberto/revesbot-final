import pandas as pd
from collections import defaultdict
from datetime import datetime
from typing import List, Dict, Set, Tuple
import json

class RoulettePatternAnalyzer:
    def __init__(self):
        # Números da roleta europeia (0-36)
        self.roulette_numbers = set(range(37))
        
        # Mapeamento de soma de dígitos para números
        self.sum_digit_map = self._create_sum_digit_map()
        
        # Estado dos gatilhos pendentes
        self.pending_triggers = defaultdict(lambda: {
            'waiting_numbers': set(),  # Números esperando pagamento
            'rounds_pending': 0,        # Rodadas desde a primeira ativação
            'confirmations': 0,         # Número de reforços/confirmações
            'first_activation': None,   # Índice da primeira ativação
            'activation_history': []    # Histórico de ativações
        })
        
        # Histórico de pagamentos
        self.payment_history = []
        
        # Histórico completo da roleta
        self.full_history = []
        
        # Configurações de filtro
        self.hot_trigger_config = {
            'min_rounds': 20,      # Mínimo de rodadas pendente
            'min_confirmations': 3  # Mínimo de confirmações
        }
    
    def _create_sum_digit_map(self) -> Dict[int, Set[int]]:
        """Cria mapeamento de soma de dígitos para números da roleta"""
        sum_map = defaultdict(set)
        for num in self.roulette_numbers:
            digit_sum = sum(int(d) for d in str(num))
            # Reduz até ficar um único dígito
            while digit_sum >= 10:
                digit_sum = sum(int(d) for d in str(digit_sum))
            sum_map[digit_sum].add(num)
        return dict(sum_map)
    
    def _get_digit_sum(self, number: int) -> int:
        """Calcula a soma dos dígitos de um número até ficar um único dígito"""
        digit_sum = sum(int(d) for d in str(number))
        while digit_sum >= 10:
            digit_sum = sum(int(d) for d in str(digit_sum))
        return digit_sum
    
    def analyze_history(self, history: List[int]) -> Dict:
        """Analisa o histórico completo e identifica padrões"""
        self.full_history = history.copy()
        
        # Encontra todas as ocorrências de cada número
        number_occurrences = defaultdict(list)
        for idx, num in enumerate(history):
            number_occurrences[num].append(idx)
        
        # Para cada número que aparece mais de uma vez
        analysis_results = {}
        for num, occurrences in number_occurrences.items():
            if len(occurrences) >= 2:
                # Pega as duas últimas ocorrências
                last_idx = occurrences[-1]
                second_last_idx = occurrences[-2]
                
                # Verifica o número que estava atrás na penúltima ocorrência
                if second_last_idx < len(history) - 1:
                    behind_number = history[second_last_idx + 1]
                    digit_sum = self._get_digit_sum(behind_number)
                    target_numbers = self.sum_digit_map[digit_sum]
                    
                    analysis_results[num] = {
                        'last_occurrence': last_idx,
                        'second_last_occurrence': second_last_idx,
                        'behind_number': behind_number,
                        'digit_sum': digit_sum,
                        'target_numbers': list(target_numbers),
                        'paid': False
                    }
                    
                    # Verifica se foi pago após a última ocorrência
                    if last_idx < len(history) - 1:
                        numbers_after = history[last_idx + 1:]
                        for idx_after, num_after in enumerate(numbers_after):
                            if num_after in target_numbers:
                                analysis_results[num]['paid'] = True
                                analysis_results[num]['paid_number'] = num_after
                                analysis_results[num]['paid_after_rounds'] = idx_after + 1
                                break
        
        return analysis_results
    
    def process_roulette(self, history: List[int]) -> Dict:
        """Processa um novo número no histórico e atualiza gatilhos"""
        if len(history) <= len(self.full_history):
            # Não há novo número
            return self.get_current_status()
        
        # Identifica o novo número
        new_number = history[-1]
        self.full_history = history.copy()
        current_position = len(history) - 1
        
        # Atualiza rodadas pendentes
        for trigger_key in self.pending_triggers:
            if self.pending_triggers[trigger_key]['first_activation'] is not None:
                self.pending_triggers[trigger_key]['rounds_pending'] += 1
        
        # Verifica pagamentos
        paid_triggers = []
        for trigger_key, trigger_info in self.pending_triggers.items():
            if new_number in trigger_info['waiting_numbers']:
                # Gatilho foi pago!
                paid_triggers.append({
                    'trigger_key': trigger_key,
                    'paid_number': new_number,
                    'rounds_waited': trigger_info['rounds_pending'],
                    'confirmations': trigger_info['confirmations'],
                    'position': current_position
                })
        
        # Remove gatilhos pagos
        for paid in paid_triggers:
            self.payment_history.append(paid)
            del self.pending_triggers[paid['trigger_key']]
        
        # Analisa novas ativações de gatilhos
        self._check_new_triggers(history)
        
        return {
            'new_number': new_number,
            'paid_triggers': paid_triggers,
            'hot_triggers': self.get_hot_triggers(),
            'pending_triggers': self.get_pending_triggers_summary()
        }
    
    def _check_new_triggers(self, history: List[int]):
        """Verifica se o novo número ativa algum gatilho"""
        if len(history) < 3:
            return
        
        current_num = history[-1]
        
        # Procura ocorrências anteriores deste número
        previous_occurrences = []
        for i in range(len(history) - 2, -1, -1):
            if history[i] == current_num:
                previous_occurrences.append(i)
                if len(previous_occurrences) >= 1:
                    break
        
        if previous_occurrences:
            # Pega o número que estava atrás na ocorrência anterior
            prev_idx = previous_occurrences[0]
            if prev_idx < len(history) - 2:  # -2 porque não conta o número atual
                behind_number = history[prev_idx + 1]
                digit_sum = self._get_digit_sum(behind_number)
                target_numbers = self.sum_digit_map[digit_sum]
                
                # Cria chave única para este gatilho
                trigger_key = f"{current_num}_{digit_sum}"
                
                # Atualiza ou cria gatilho pendente
                if trigger_key not in self.pending_triggers:
                    self.pending_triggers[trigger_key]['first_activation'] = len(history) - 1
                    self.pending_triggers[trigger_key]['waiting_numbers'] = target_numbers
                    self.pending_triggers[trigger_key]['rounds_pending'] = 0
                
                self.pending_triggers[trigger_key]['confirmations'] += 1
                self.pending_triggers[trigger_key]['activation_history'].append({
                    'position': len(history) - 1,
                    'trigger_number': current_num,
                    'behind_number': behind_number
                })
    
    def get_hot_triggers(self) -> List[Dict]:
        """Retorna gatilhos que estão 'quentes' baseado nas configurações"""
        hot_triggers = []
        
        for trigger_key, trigger_info in self.pending_triggers.items():
            if (trigger_info['rounds_pending'] >= self.hot_trigger_config['min_rounds'] and
                trigger_info['confirmations'] >= self.hot_trigger_config['min_confirmations']):
                
                hot_triggers.append({
                    'trigger_key': trigger_key,
                    'target_numbers': list(trigger_info['waiting_numbers']),
                    'rounds_pending': trigger_info['rounds_pending'],
                    'confirmations': trigger_info['confirmations'],
                    'heat_score': trigger_info['rounds_pending'] * trigger_info['confirmations']
                })
        
        # Ordena por heat_score
        hot_triggers.sort(key=lambda x: x['heat_score'], reverse=True)
        return hot_triggers
    
    def get_pending_triggers_summary(self) -> List[Dict]:
        """Retorna resumo de todos os gatilhos pendentes"""
        summary = []
        for trigger_key, trigger_info in self.pending_triggers.items():
            summary.append({
                'trigger_key': trigger_key,
                'target_numbers': list(trigger_info['waiting_numbers']),
                'rounds_pending': trigger_info['rounds_pending'],
                'confirmations': trigger_info['confirmations']
            })
        return summary
    
    def get_statistics_report(self) -> Dict:
        """Gera relatório estatístico dos pagamentos"""
        if not self.payment_history:
            return {'message': 'Ainda não há pagamentos registrados'}
        
        df = pd.DataFrame(self.payment_history)
        
        stats = {
            'total_payments': len(self.payment_history),
            'avg_rounds_to_payment': df['rounds_waited'].mean(),
            'max_rounds_to_payment': df['rounds_waited'].max(),
            'min_rounds_to_payment': df['rounds_waited'].min(),
            'avg_confirmations': df['confirmations'].mean(),
            'payment_distribution': df['rounds_waited'].value_counts().to_dict(),
            'confirmation_distribution': df['confirmations'].value_counts().to_dict()
        }
        
        # Análise de padrões
        patterns = []
        
        # Padrão 1: Todos os gatilhos pagos após X rodadas
        min_rounds = df['rounds_waited'].min()
        if min_rounds > 0:
            patterns.append(f"Todos os gatilhos foram pagos após no mínimo {min_rounds} rodadas")
        
        # Padrão 2: Gatilhos com mínimo de confirmações
        min_confirmations = df['confirmations'].min()
        patterns.append(f"Todos os gatilhos pagos tiveram no mínimo {min_confirmations} confirmações")
        
        # Padrão 3: Média de espera
        avg_wait = df['rounds_waited'].mean()
        patterns.append(f"Em média, os gatilhos são pagos após {avg_wait:.1f} rodadas")
        
        stats['patterns'] = patterns
        
        return stats
    
    def set_hot_trigger_config(self, min_rounds: int, min_confirmations: int):
        """Configura os parâmetros para considerar um gatilho como 'quente'"""
        self.hot_trigger_config['min_rounds'] = min_rounds
        self.hot_trigger_config['min_confirmations'] = min_confirmations
    
    def get_current_status(self) -> Dict:
        """Retorna status atual do sistema"""
        return {
            'total_pending_triggers': len(self.pending_triggers),
            'hot_triggers': self.get_hot_triggers(),
            'pending_summary': self.get_pending_triggers_summary(),
            'total_payments': len(self.payment_history)
        }
    
    def suggest_play(self) -> Dict:
        """Sugere jogada baseada nos gatilhos mais quentes"""
        hot_triggers = self.get_hot_triggers()
        
        if not hot_triggers:
            return {'play': False, 'message': 'Nenhum gatilho quente no momento'}
        
        # Pega o gatilho mais quente
        hottest = hot_triggers[0]
        
        # Conta frequência dos números alvo em todos os gatilhos quentes
        number_frequency = defaultdict(int)
        for trigger in hot_triggers[:3]:  # Top 3 gatilhos mais quentes
            for num in trigger['target_numbers']:
                number_frequency[num] += 1
        
        # Ordena por frequência
        best_numbers = sorted(number_frequency.items(), key=lambda x: x[1], reverse=True)
        
        return {
            'play': True,
            'recommended_numbers': [num for num, _ in best_numbers[:5]],  # Top 5 números
            'confidence': hottest['heat_score'],
            'reason': f"Gatilho pendente há {hottest['rounds_pending']} rodadas com {hottest['confirmations']} confirmações"
        }


# Exemplo de uso
def main():
    # Histórico de exemplo fornecido
    history = [32, 0, 30, 26, 32, 35, 23, 36, 2, 8, 16, 8, 23, 34, 7, 24, 27, 25, 10, 17, 
               23, 36, 21, 28, 18, 26, 31, 7, 35, 26, 6, 8, 26, 8, 27, 27, 25, 6, 4, 25, 
               2, 13, 19, 24, 21, 34, 24, 35, 22, 17, 36, 23, 9, 10, 34, 0, 24, 0, 33, 5, 
               18, 4, 23, 27, 20, 16, 19, 2, 27, 27, 6, 33, 0, 3, 3, 17, 14, 11, 8, 11, 
               34, 2, 28, 19, 34, 19, 10, 12, 32, 21, 20, 34, 35, 1, 24, 16, 26, 15, 30, 
               29, 11, 20, 5, 27, 22, 1, 21, 27, 1, 21, 20, 0, 28, 23, 21, 19, 25, 8, 30, 
               36, 22, 6, 4, 3, 25, 23, 16, 35, 2, 29, 11, 4, 7, 0, 1, 24, 15, 14, 33, 28, 
               24, 5, 9, 12, 28]
    
    analyzer = RoulettePatternAnalyzer()
    
    # Configura parâmetros de gatilho quente
    analyzer.set_hot_trigger_config(min_rounds=15, min_confirmations=2)
    
    # Processa histórico inicial
    print("=== ANÁLISE INICIAL DO HISTÓRICO ===\n")
    initial_analysis = analyzer.analyze_history(history)
    
    # Simula processamento em tempo real
    for i in range(len(history)):
        current_history = history[:i+1]
        if i > 10:  # Começa após ter algum histórico
            result = analyzer.process_roulette(current_history)
            
            if result.get('hot_triggers'):
                print(f"\n🔥 GATILHOS QUENTES na rodada {i+1} (número {history[i]}):")
                for trigger in result['hot_triggers']:
                    print(f"  - Números alvo: {trigger['target_numbers']}")
                    print(f"    Esperando há {trigger['rounds_pending']} rodadas")
                    print(f"    {trigger['confirmations']} confirmações")
            
            if result.get('paid_triggers'):
                print(f"\n✅ PAGAMENTO na rodada {i+1}!")
                for paid in result['paid_triggers']:
                    print(f"  - Gatilho {paid['trigger_key']} pago com número {paid['paid_number']}")
                    print(f"    Esperou {paid['rounds_waited']} rodadas")
    
    # Relatório final
    print("\n\n=== RELATÓRIO ESTATÍSTICO ===\n")
    stats = analyzer.get_statistics_report()
    print(json.dumps(stats, indent=2, ensure_ascii=False))
    
    # Sugestão de jogada
    print("\n\n=== SUGESTÃO DE JOGADA ===\n")
    suggestion = analyzer.suggest_play()
    if suggestion['play']:
        print(f"✅ JOGAR nos números: {suggestion['recommended_numbers']}")
        print(f"Motivo: {suggestion['reason']}")
        print(f"Confiança: {suggestion['confidence']}")
    else:
        print(f"⏸ {suggestion['message']}")
    
    # Status atual
    print("\n\n=== STATUS ATUAL ===\n")
    status = analyzer.get_current_status()
    print(f"Total de gatilhos pendentes: {status['total_pending_triggers']}")
    print(f"Total de pagamentos realizados: {status['total_payments']}")
    
    if status['hot_triggers']:
        print(f"\nGatilhos quentes ativos: {len(status['hot_triggers'])}")
        for trigger in status['hot_triggers'][:3]:
            print(f"  - {trigger['trigger_key']}: {trigger['target_numbers'][:5]}...")


if __name__ == "__main__":
    main()