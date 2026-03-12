# helpers/utils/advanced_counter.py
"""
Módulo de contagem avançada para análise de padrões em tempo real.
Implementa regras de contagem baseadas em terminais, repetições e inversões.
"""
from typing import List, Optional, Dict, Set, Tuple
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class AdvancedCounter:
    """
    Contador avançado que analisa padrões de terminais e ocorrências
    para determinar o número de jogadas a aguardar antes da aposta.
    """
    
    def __init__(self):
        self.PRE_WINDOW_SIZE = 5  # Janela de análise pré-gatilho

        self.roulette_european_numbers = [
        0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23, 10, 5,
        24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26
    ]

    def get_neighbords(self, num) : 

        if(num == 32) : 
            return [15, 19]
        elif(num == 26) :
            return [3, 35]
        else :
            i = self.roulette_european_numbers.index(num)
        neighbors_left = self.roulette_european_numbers[(i - 1) % len(self.roulette_european_numbers)]
        neighbors_right = self.roulette_european_numbers[(i + 1) % len(self.roulette_european_numbers)]

        return [neighbors_left, neighbors_right]

    def get_neighbords_color(self, num) : 

        if(num == 32) : 
            return [3, 19]
        elif(num == 26) :
            return [15, 35]
        elif(num == 3) : 
            return [32, 12]
        elif(num == 15) : 
            return [4, 26]
        else :
            i = self.roulette_european_numbers.index(num)
        neighbors_left = self.roulette_european_numbers[(i - 2) % len(self.roulette_european_numbers)]
        neighbors_right = self.roulette_european_numbers[(i + 2) % len(self.roulette_european_numbers)]

        return [neighbors_left, neighbors_right]

        
    def get_terminal(self, number: int) -> int:
        """Retorna o terminal (último dígito) de um número."""
        return number % 10
    
    def add_simple_log(self, log_list: List[str], message: str):
        """Adiciona uma mensagem simples ao log com timestamp."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_list.append(f"[{timestamp}] {message}")

    def _is_number_hot(self, number: int, history: List[int], targets: List[int], 
                   simple_log: List[str] = None) -> bool:
        """
        Verifica se qualquer número está "quente" analisando ocorrências anteriores.
        Um número está quente quando os números que o precederam na última ocorrência
        são apostas diretas ou vizinhos das apostas.
        
        Args:
            number: O número a ser analisado
            history: Histórico completo de números
            targets: Lista de números da aposta
            simple_log: Lista para adicionar logs
            
        Returns:
            bool: True se o número está quente (deve interromper espera), False caso contrário
        """
        if simple_log is None:
            simple_log = []
        
        # Procura a próxima ocorrência do número no histórico
        # Começa do índice 1 pois o 0 é o número atual
        try:
            next_occurrence_index = history[1:].index(number)
        except ValueError:
            # Não há ocorrência anterior do número
            return False
        
        # Pega os 5 números que vieram antes dessa ocorrência
        if next_occurrence_index + 5 > len(history):
            # Não há números suficientes antes da ocorrência
            return False
        
        numbers_before = history[next_occurrence_index + 1:next_occurrence_index + 6]
        
        # Cria conjunto de apostas e seus vizinhos
        targets_set = set(targets)
        targets_with_neighbors = set(targets)
        
        # Adiciona vizinhos de cada aposta
        for target in targets:
            neighbors = self.get_neighbords(target)
            targets_with_neighbors.update(neighbors)
        
        # Conta quantos números antes da ocorrência são apostas ou vizinhos
        hits = 0
        hit_details = []
        
        for num in numbers_before:
            if num in targets_set:
                hits += 1
                hit_details.append(f"{num} (aposta direta)")
            elif num in targets_with_neighbors:
                hits += 1
                # Encontra de qual aposta é vizinho
                for target in targets:
                    if num in self.get_neighbords(target):
                        hit_details.append(f"{num} (vizinho de {target})")
                        break
        
        # Calcula a porcentagem de acertos
        hit_percentage = (hits / len(numbers_before)) * 100
        
        # Considera quente se 60% ou mais dos números são apostas/vizinhos
        is_hot = hit_percentage >= 50
        
        # Log apenas se o número está quente
        if is_hot:
            self.add_simple_log(simple_log, 
                f"🔥 Número {number} está QUENTE!")
            self.add_simple_log(simple_log, 
                f"   • Última ocorrência: {next_occurrence_index} jogadas atrás")
            self.add_simple_log(simple_log, 
                f"   • Números anteriores: {numbers_before}")
            self.add_simple_log(simple_log, 
                f"   • Acertos: {hits}/5 ({hit_percentage:.0f}%)")
            
            if hit_details:
                for detail in hit_details[:3]:  # Mostra apenas os 3 primeiros
                    self.add_simple_log(simple_log, f"   • {detail}")
            
            self.add_simple_log(simple_log, 
                f"   ➤ Interromper contagem e apostar imediatamente!")
        
        return is_hot

    def initial_wait_spins(self, history: List[int], targets: List[int], 
                          trigger: int, simple_log: List[str] = None) -> Tuple[int, Dict[str, any]]:
        """
        Calcula a contagem inicial quando o gatilho é ativado.
        
        Returns:
            Tuple[int, Dict]: (número de spins para aguardar, análise detalhada)
                             Retorna -1 se o gatilho deve ser cancelado
        """
        if simple_log is None:
            simple_log = []
            
        if len(history) < 1:
            self.add_simple_log(simple_log, "❌ Erro: Histórico vazio")
            return 0, {"error": "Histórico vazio"}
            
        # O gatilho está em history[0], os anteriores em history[1:6]
        analysis = {
            "trigger": trigger,
            "trigger_terminal": self.get_terminal(trigger),
            "pre_window": history[1:self.PRE_WINDOW_SIZE + 1] if len(history) > 1 else [],
            "inversions": [],
            "terminal_occurrences": [],
            "final_count": 0,
            "priority_rule": None,
            "cancelled": False
        }
        
        # Log do gatilho
        self.add_simple_log(simple_log, f"🎯 Gatilho {trigger} ativado! Terminal: {self.get_terminal(trigger)}")
        if analysis["pre_window"]:
            self.add_simple_log(simple_log, f"📊 Últimos 5 números: {analysis['pre_window']}")
        
        # 1. Verificar inversões (pode cancelar o gatilho)
        inversion_count = self._check_inversions(
            history[1:self.PRE_WINDOW_SIZE + 1], 
            targets, 
            analysis,
            simple_log
        )
        
        # 2. Verificar terminais colados
        terminal_count = self._check_terminal_occurrences(
            history[:self.PRE_WINDOW_SIZE + 1],
            trigger,
            analysis,
            simple_log
        )

        # 3. Verificar alternância de terminais (só se não houver outras ocorrências)
        alternation_count = 0
        if inversion_count == 0 and terminal_count == 0:
            alternation_count = self._check_terminal_alternation(
                history[1:self.PRE_WINDOW_SIZE + 1],
                trigger,
                analysis,
                simple_log
            )
        
        # 4. Verificar sequência alternada de números (menor prioridade de todas)
        number_alternation_count = 0
        if inversion_count == 0 and terminal_count == 0:
            number_alternation_count = self._check_number_alternation(
                history[1:self.PRE_WINDOW_SIZE + 1],
                trigger,
                analysis,
                simple_log
            )

        # 5. Decidir qual regra aplicar
        if inversion_count > 0 and terminal_count > 0:
            # Terminal colado tem prioridade por estar mais próximo
            analysis["final_count"] = terminal_count
            analysis["priority_rule"] = "terminal"
            self.add_simple_log(simple_log, 
                f"⚡ Sequência ou repetição de  Terminal tem prioridade sobre inversão com o gatilho")
            self.add_simple_log(simple_log, f"⏳ Aguardar {terminal_count} jogadas")
        elif terminal_count > 0:
            analysis["final_count"] = terminal_count
            analysis["priority_rule"] = "terminal"
            self.add_simple_log(simple_log, f"⏳ Aguardar {terminal_count} jogadas por terminal colado")
        elif inversion_count > 0:
            analysis["final_count"] = inversion_count
            analysis["priority_rule"] = "inversion"
            self.add_simple_log(simple_log, f"⏳ Aguardar {inversion_count} jogadas por inversão")
        elif alternation_count > 0:
            analysis["final_count"] = alternation_count
            analysis["priority_rule"] = "inversion"
            self.add_simple_log(simple_log, f"⏳ Aguardar {alternation_count} jogadas por inversão")
        elif number_alternation_count > 0:
            # Sequência alternada tem a menor prioridade
            analysis["final_count"] = number_alternation_count
            analysis["priority_rule"] = "number_alternation"
            self.add_simple_log(simple_log, f"⏳ Aguardar {number_alternation_count} jogadas por sequência alternada")
        else:
            analysis["final_count"] = 0
            analysis["priority_rule"] = "none"
            self.add_simple_log(simple_log, "✅ Apostar imediatamente - sem ocorrências ou inversões")


        
        
        return analysis["final_count"], analysis
    
    def _check_inversions(self, pre_window: List[int], targets: List[int], 
                         analysis: Dict, simple_log: List[str]) -> int:
        """
        Verifica inversões: quando um alvo aparece antes do gatilho.
        Se houver 2 ou mais inversões, retorna -1 para cancelar o gatilho.
        """
        if not pre_window or not targets:
            return 0
        
        targets_set = set(targets)
        targets_set.discard(0)

        closest_inversion_pos = None
        inversions_found = []
        
        # Procura inversões
        for i, num in enumerate(pre_window):
            if num in targets_set:
                position = i + 1  # P1=1, P2=2, etc.
                count = position + 1 if position <= 2 else position
                inversions_found.append((num, position, count))
                
                # Guarda a mais próxima
                if closest_inversion_pos is None:
                    closest_inversion_pos = i
                    
                analysis["inversions"].append({
                    "number": num,
                    "position": f"P{position}",
                    "count": count
                })
        
        # Verifica se deve cancelar o gatilho
        if len(inversions_found) >= 30:
            self.add_simple_log(simple_log, 
                f"❌ GATILHO CANCELADO: {len(inversions_found)} inversões encontradas")
            self.add_simple_log(simple_log, 
                f"   • Alvos {[inv[0] for inv in inversions_found]} apareceram antes do gatilho")
            self.add_simple_log(simple_log, 
                f"   • Aguardando próximo gatilho...")
            return -1  # Sinal especial para cancelar
        
        # Log das inversões normais (apenas 1)
        if inversions_found:
            self.add_simple_log(simple_log, f"🔄 Inversão encontrada (alvo {inversions_found[0][0]} antes do gatilho):")
            for num, pos, count in inversions_found:
                self.add_simple_log(simple_log, f"   • Número {num} na posição P{pos} = {count} jogadas")
            
            # Retorna a contagem da inversão mais próxima
            closest_pos = closest_inversion_pos + 1
            final_count = 2 if closest_pos <= 2 else closest_pos
            self.add_simple_log(simple_log, f"   ➤ Usando a mais próxima: P{closest_pos} - Aguardar {final_count} - {closest_inversion_pos}")
            return final_count
            
        return 0
    
    def _check_terminal_occurrences(self, window: List[int], trigger: int,
                                   analysis: Dict, simple_log: List[str]) -> int:
        """
        Verifica ocorrências de terminais coladas ao gatilho.
        Inclui: repetições, sequências crescentes e decrescentes.
        """
        if len(window) < 2:
            return 0
            
        trigger_terminal = self.get_terminal(trigger)
        terminals = [self.get_terminal(n) for n in window]
        
        # Inicializa count como 0
        count = 0
        
        # 1. Verifica repetições de terminal
        if len(terminals) > 1 and terminals[1] == trigger_terminal:
            positions = ["P0", "P1"]
            numbers = [window[0], window[1]]
            count = 2
            
            # Verifica P2, P3, etc.
            for i in range(2, min(len(terminals), 6)):
                if terminals[i] == trigger_terminal:
                    positions.append(f"P{i}")
                    numbers.append(window[i])
                    count += 1
                else:
                    break
                    
            analysis["terminal_occurrences"].append({
                "terminal": trigger_terminal,
                "positions": positions,
                "count": count,
                "type": "repetition"
            })
            
            self.add_simple_log(simple_log, 
                f"🔢 Terminal {trigger_terminal} repetido em sequência:")
            self.add_simple_log(simple_log, 
                f"   • Números: {numbers} nas posições {positions}")
            self.add_simple_log(simple_log, 
                f"   • Total: {count} posições = {count} jogadas")
            
            return count
        
        # 2. Verifica se há alguma sequência que inclua P0 ou comece em P1
        # Primeiro, verifica se P0 e P1 formam uma sequência
        if len(terminals) > 1:
            diff = (terminals[1] - trigger_terminal) % 10
            is_crescente = diff == 1
            is_decrescente = diff == 9  # 9 é -1 em módulo 10
            
            if is_crescente or is_decrescente:
                # P0 e P1 formam sequência, verifica extensão
                sequence_type = "crescente" if is_crescente else "decrescente"
                positions = ["P0", "P1"]
                numbers = [window[0], window[1]]
                count = 2
                
                # Verifica continuação da sequência
                for i in range(2, min(len(terminals), 3)):
                    expected_terminal = terminals[i-1] + (1 if is_crescente else -1)
                    expected_terminal = expected_terminal % 10
                    
                    if terminals[i] == expected_terminal:
                        positions.append(f"P{i}")
                        numbers.append(window[i])
                        count += 1
                    else:
                        break
                
                analysis["terminal_occurrences"].append({
                    "terminals": [terminals[j] for j in range(count)],
                    "positions": positions,
                    "count": count,
                    "type": sequence_type
                })
                
                self.add_simple_log(simple_log, 
                    f"📈 Sequência {sequence_type} de terminais:")
                self.add_simple_log(simple_log, 
                    f"   • Números: {numbers} nas posições {positions}")
                self.add_simple_log(simple_log, 
                    f"   • Terminais: {[terminals[j] for j in range(count)]}")
                self.add_simple_log(simple_log, 
                    f"   • Total: {count} posições = {count} jogadas")
                
                return count
        
        # 3. Verifica se P1-P2 formam sequência (colada ao gatilho)
        if len(terminals) > 2:
            diff = (terminals[2] - terminals[1]) % 10
            is_crescente = diff == 1
            is_decrescente = diff == 9
            
            if is_crescente or is_decrescente:
                sequence_type = "crescente" if is_crescente else "decrescente"
                positions = ["P1", "P2"]
                numbers = [window[1], window[2]]
                count = 2
                
                # Verifica se P0 também faz parte da sequência
                diff_p0 = (terminals[1] - trigger_terminal) % 10
                if (is_crescente and diff_p0 == 1) or (is_decrescente and diff_p0 == 9):
                    # P0 faz parte da sequência
                    positions.insert(0, "P0")
                    numbers.insert(0, window[0])
                    count += 1
                
                # Verifica continuação após P2
                start_idx = 1 if "P0" not in positions else 0
                for i in range(3, min(len(terminals), 6)):
                    expected_terminal = terminals[i-1] + (1 if is_crescente else -1)
                    expected_terminal = expected_terminal % 10
                    
                    if terminals[i] == expected_terminal:
                        positions.append(f"P{i}")
                        numbers.append(window[i])
                        count += 1
                    else:
                        break
                
                # Só conta se incluir P0 ou começar em P1
                if "P0" in positions or positions[0] == "P1":
                    analysis["terminal_occurrences"].append({
                        "terminals": [self.get_terminal(n) for n in numbers],
                        "positions": positions,
                        "count": count,
                        "type": sequence_type
                    })
                    
                    self.add_simple_log(simple_log, 
                        f"📈 Sequência {sequence_type} de terminais:")
                    self.add_simple_log(simple_log, 
                        f"   • Números: {numbers} nas posições {positions}")
                    self.add_simple_log(simple_log, 
                        f"   • Terminais: {[self.get_terminal(n) for n in numbers]}")
                    self.add_simple_log(simple_log, 
                        f"   • Total: {count} posições = {count} jogadas")
                    
                    return count
            
        return count
    

    def _check_terminal_alternation(self, pre_window: List[int], trigger: int,
                               analysis: Dict, simple_log: List[str]) -> int:
        """
        Verifica alternância de terminais antes do gatilho.
        Exemplo: gatilho 2, sequência anterior: 5, 18, 35
        Terminais: 2 (gatilho), 5, 8, 5 - há alternância entre 5→8→5
        
        Retorna 2 jogadas se houver alternância, 0 caso contrário.
        Esta regra só é aplicada quando não há outras ocorrências.
        """
        if len(pre_window) < 3:  # Precisa de pelo menos 3 números para verificar alternância
            return 0
        
        # Pega os terminais dos primeiros 3 números antes do gatilho
        terminal_p1 = self.get_terminal(pre_window[0])  # P1
        terminal_p2 = self.get_terminal(pre_window[1])  # P2
        terminal_p3 = self.get_terminal(pre_window[2])  # P3
        
        # Verifica se há alternância: P1 ≠ P2 e P1 = P3
        if terminal_p1 != terminal_p2 and terminal_p1 == terminal_p3:
            analysis["terminal_alternation"] = {
                "positions": ["P1", "P2", "P3"],
                "numbers": [pre_window[0], pre_window[1], pre_window[2]],
                "terminals": [terminal_p1, terminal_p2, terminal_p3],
                "pattern": f"{terminal_p1}→{terminal_p2}→{terminal_p1}"
            }
            
            self.add_simple_log(simple_log, 
                f"🔄 Alternância de terminais detectada:")
            self.add_simple_log(simple_log, 
                f"   • Números: {[pre_window[0], pre_window[1], pre_window[2]]} nas posições P1, P2, P3")
            self.add_simple_log(simple_log, 
                f"   • Padrão de terminais: {terminal_p1}→{terminal_p2}→{terminal_p1}")
            self.add_simple_log(simple_log, 
                f"   • Total: 2 jogadas de espera")
            
            return 2
        
        # Também verifica o padrão inverso: P1 = P2 e P2 ≠ P3 e P1 = P3
        # Isso cobre casos como: 5, 5, 8 (terminais 5→5→8 onde P2=P3 mas diferente de P1)
        # Na verdade, vamos verificar se P2 é diferente de P1 e P3, mas P1 = P3
        # Isso já está coberto acima
        
        return 0
    
    def _check_number_alternation(self, pre_window: List[int], trigger: int,
                             analysis: Dict, simple_log: List[str]) -> int:
        """
        Verifica sequência alternada de números completos antes do gatilho.
        Exemplo: gatilho 2, sequência anterior: 11, 34, 22
        Números: 2 (gatilho), 11, 34, 22 - há alternância entre 11→34→22
        onde o terminal de 11 (1) + terminal de 34 (4) = 5, e 22 tem terminal 2
        Mas o importante é que 11 e 22 formam uma sequência (1→2 nos terminais)
        
        Retorna 2 jogadas se houver sequência alternada, 0 caso contrário.
        Esta regra só é aplicada quando não há outras ocorrências.
        """
        if len(pre_window) < 3:  # Precisa de pelo menos 3 números
            return 0
        
        # Pega os números e terminais
        num_p1 = pre_window[0]  # P1
        num_p2 = pre_window[1]  # P2
        num_p3 = pre_window[2]  # P3
        
        terminal_p1 = self.get_terminal(num_p1)
        terminal_p2 = self.get_terminal(num_p2)
        terminal_p3 = self.get_terminal(num_p3)
        
        # Verifica se P1 e P3 formam uma sequência crescente ou decrescente de terminais
        # E se P2 é diferente (alternância)
        diff_p1_p3 = (terminal_p3 - terminal_p1) % 10
        
        # Verifica sequência crescente entre P1 e P3
        if diff_p1_p3 == 1 and terminal_p2 != terminal_p1 and terminal_p2 != terminal_p3:
            analysis["number_alternation"] = {
                "positions": ["P1", "P2", "P3"],
                "numbers": [num_p1, num_p2, num_p3],
                "terminals": [terminal_p1, terminal_p2, terminal_p3],
                "pattern": f"{num_p1}→{num_p2}→{num_p3}",
                "sequence_type": "crescente"
            }
            
            self.add_simple_log(simple_log, 
                f"🔀 Sequência alternada crescente detectada:")
            self.add_simple_log(simple_log, 
                f"   • Números: [{num_p1}, {num_p2}, {num_p3}] nas posições P1, P2, P3")
            self.add_simple_log(simple_log, 
                f"   • Sequência de terminais: {terminal_p1}→{terminal_p3} (crescente)")
            self.add_simple_log(simple_log, 
                f"   • Número alternado no meio: {num_p2} (terminal {terminal_p2})")
            self.add_simple_log(simple_log, 
                f"   • Total: 2 jogadas de espera")
            
            return 2
    
        # Verifica sequência decrescente entre P1 e P3
        elif diff_p1_p3 == 9 and terminal_p2 != terminal_p1 and terminal_p2 != terminal_p3:  # 9 = -1 em módulo 10
            analysis["number_alternation"] = {
                "positions": ["P1", "P2", "P3"],
                "numbers": [num_p1, num_p2, num_p3],
                "terminals": [terminal_p1, terminal_p2, terminal_p3],
                "pattern": f"{num_p1}→{num_p2}→{num_p3}",
                "sequence_type": "decrescente"
            }
            
            self.add_simple_log(simple_log, 
                f"🔀 Sequência alternada decrescente detectada:")
            self.add_simple_log(simple_log, 
                f"   • Números: [{num_p1}, {num_p2}, {num_p3}] nas posições P1, P2, P3")
            self.add_simple_log(simple_log, 
                f"   • Sequência de terminais: {terminal_p1}→{terminal_p3} (decrescente)")
            self.add_simple_log(simple_log, 
                f"   • Número alternado no meio: {num_p2} (terminal {terminal_p2})")
            self.add_simple_log(simple_log, 
                f"   • Total: 2 jogadas de espera")
            
            return 2
        
        return 0
    def update_wait_spins(self, current_wait: int, history: List[int], 
                        targets: List[int], new_number: int, 
                        trigger_position: int = None,
                        simple_log: List[str] = None,
                        previous_analysis: Dict = None) -> Tuple[int, Dict[str, any]]:
        """
        Atualiza a contagem após um novo spin.
        NOVO: Mantém memória do modo quente e pode retornar à contagem original.
        
        Args:
            previous_analysis: Análise do spin anterior para manter estado
        """
        if simple_log is None:
            simple_log = []
            
        analysis = {
            "previous_count": current_wait,
            "new_number": new_number,
            "new_occurrences": [],
            "adjustment": 0,
            "final_count": max(0, current_wait - 1),
            "hot_number": False,
            "hot_mode_active": False,
            "original_hot_count": None
        }
        
        # Preserva informações do modo quente se existirem
        if previous_analysis and previous_analysis.get("hot_mode_active"):
            analysis["hot_mode_active"] = True
            analysis["original_hot_count"] = previous_analysis.get("original_hot_count")
        
        # Log do novo número
        self.add_simple_log(simple_log, 
            f"🎰 Novo número: {new_number} (terminal {self.get_terminal(new_number)})")
        
        # Verifica se estamos em modo quente e a aposta falhou
        if analysis["hot_mode_active"] and current_wait == 0:
            # Verifica se o número atual é uma aposta (ganhou)
            if new_number in targets:
                self.add_simple_log(simple_log, "✅ Aposta em modo quente ACERTOU!")
                analysis["hot_mode_active"] = False  # Reseta o modo quente
                return 0, analysis
            else:
                # Aposta falhou, retorna à contagem original
                original_count = analysis["original_hot_count"]
                if original_count and original_count > 0:
                    analysis["final_count"] = original_count - 1  # Diminui 1 da contagem original
                    analysis["hot_mode_active"] = False  # Reseta o modo quente
                    
                    self.add_simple_log(simple_log, 
                        f"❌ Aposta em modo quente falhou!")
                    self.add_simple_log(simple_log, 
                        f"🔄 Retornando à contagem original: {original_count} → {analysis['final_count']}")
                    self.add_simple_log(simple_log, 
                        f"⏳ Aguardar mais {analysis['final_count']} jogada(s)")
                    
                    return analysis["final_count"], analysis
        
        # Se já zerou e não está em modo quente, mantém zero
        if current_wait <= 0 and not analysis["hot_mode_active"]:
            self.add_simple_log(simple_log, "✅ Contagem já zerada - continue apostando")
            return 0, analysis
        
        # Verifica se o número está quente ANTES de decrementar
        if current_wait > 0 and self._is_number_hot(new_number, history, targets, simple_log):
            analysis["hot_number"] = True
            analysis["hot_mode_active"] = True
            analysis["original_hot_count"] = current_wait  # Salva a contagem atual
            analysis["final_count"] = 0
            
            self.add_simple_log(simple_log, 
                f"🔥 Contagem de {current_wait} jogadas SUSPENSA por número quente!")
            self.add_simple_log(simple_log, 
                f"💾 Contagem original salva: {current_wait} jogadas")
            self.add_simple_log(simple_log, "🎯 APOSTAR AGORA!")
            
            return 0, analysis
        
        # Se não está quente e temos contagem, continua com a lógica normal
        if current_wait > 0:
            # Decrementa a contagem
            new_count = current_wait - 1
            self.add_simple_log(simple_log, f"📉 Contagem: {current_wait} → {new_count}")
            
            # Verifica ocorrências apenas dos 2 últimos números
            if len(history) >= 2:
                current_num = history[0]
                previous_num = history[1]
                
                current_terminal = self.get_terminal(current_num)
                previous_terminal = self.get_terminal(previous_num)
                
                # Verifica repetição de terminal
                if current_terminal == previous_terminal:
                    analysis["adjustment"] = 2
                    analysis["final_count"] = new_count + 2
                    
                    self.add_simple_log(simple_log, 
                        f"⚠️ Repetição de terminal {current_terminal} detectada:")
                    self.add_simple_log(simple_log, 
                        f"   • Números: [{current_num}, {previous_num}] = +2 jogadas")
                    self.add_simple_log(simple_log, 
                        f"📈 Contagem ajustada: {new_count} + 2 = {analysis['final_count']} jogadas")
                        
                # Verifica sequência crescente
                elif (current_terminal - previous_terminal) % 10 == 1:
                    analysis["adjustment"] = 2
                    analysis["final_count"] = new_count + 2
                    
                    self.add_simple_log(simple_log, 
                        f"⚠️ Sequência crescente detectada:")
                    self.add_simple_log(simple_log, 
                        f"   • Números: [{previous_num}, {current_num}]")
                    self.add_simple_log(simple_log, 
                        f"   • Terminais: {previous_terminal}→{current_terminal} = +2 jogadas")
                    self.add_simple_log(simple_log, 
                        f"📈 Contagem ajustada: {new_count} + 2 = {analysis['final_count']} jogadas")
                        
                # Verifica sequência decrescente
                elif (previous_terminal - current_terminal) % 10 == 1:
                    analysis["adjustment"] = 2
                    analysis["final_count"] = new_count + 2
                    
                    self.add_simple_log(simple_log, 
                        f"⚠️ Sequência decrescente detectada:")
                    self.add_simple_log(simple_log, 
                        f"   • Números: [{current_num}, {previous_num}]")
                    self.add_simple_log(simple_log, 
                        f"   • Terminais: {current_terminal}→{previous_terminal} = +2 jogadas")
                    self.add_simple_log(simple_log, 
                        f"📈 Contagem ajustada: {new_count} + 2 = {analysis['final_count']} jogadas")
                else:
                    # Nenhuma ocorrência - apenas decrementa
                    analysis["final_count"] = new_count
            else:
                # Histórico insuficiente - apenas decrementa
                analysis["final_count"] = new_count
        
        # Log final
        if analysis["final_count"] == 0:
            self.add_simple_log(simple_log, "🎯 Contagem zerada - APOSTAR AGORA!")
        else:
            self.add_simple_log(simple_log, f"⏳ Aguardar mais {analysis['final_count']} jogada(s)")
                
        return analysis["final_count"], analysis
        
        # Log final
        if analysis["final_count"] == 0:
            self.add_simple_log(simple_log, "🎯 Contagem zerada - APOSTAR AGORA!")
        else:
            self.add_simple_log(simple_log, f"⏳ Aguardar mais {analysis['final_count']} jogada(s)")
                
        return analysis["final_count"], analysis
   
    def _check_new_occurrences(self, history: List[int], analysis: Dict, 
                           simple_log: List[str], active_trigger : bool = True) -> int:
        """
        Verifica se o NOVO número (history[0]) forma alguma ocorrência
        com os números imediatamente anteriores.
        """
        if len(history) < 2:
            return 0
        
        # O novo número está em history[0]
        new_terminal = self.get_terminal(history[0])
        prev_terminal = self.get_terminal(history[1])
        
        # 1. Verifica repetição de terminal com o número anterior
        if new_terminal == prev_terminal:
            numbers = [history[0], history[1]]
            occurrence_count = 2
            
            analysis["new_occurrences"].append({
                "terminal": new_terminal,
                "positions": ["P0", "P1"],
                "count": occurrence_count,
                "type": "repetition"
            })
            
            self.add_simple_log(simple_log, 
                f"⚠️ Nova repetição de terminal {new_terminal} detectada:")
            self.add_simple_log(simple_log, 
                f"   • Números: {numbers} = +{occurrence_count} jogadas")
            
            return occurrence_count
        
        # 2. Verifica sequência crescente ou decrescente
        diff = (new_terminal - prev_terminal) % 10
        
        if diff == 1:  # Sequência crescente
            numbers = [history[1], history[0]]  # Na ordem crescente
            occurrence_count = 2
            
            analysis["new_occurrences"].append({
                "terminals": [prev_terminal, new_terminal],
                "positions": ["P1", "P0"],
                "count": occurrence_count,
                "type": "crescente"
            })
            
            self.add_simple_log(simple_log, 
                f"⚠️ Nova sequência crescente detectada:")
            self.add_simple_log(simple_log, 
                f"   • Números: {numbers}")
            self.add_simple_log(simple_log, 
                f"   • Terminais: {prev_terminal}→{new_terminal} = +{occurrence_count} jogadas")
            
            if active_trigger :
                return occurrence_count
            else :
                return 0
            
        elif diff == 9:  # Sequência decrescente (9 é -1 em módulo 10)
            numbers = [history[1], history[0]]  # Na ordem decrescente
            occurrence_count = 0
            
            analysis["new_occurrences"].append({
                "terminals": [prev_terminal, new_terminal],
                "positions": ["P1", "P0"],
                "count": occurrence_count,
                "type": "decrescente"
            })
            
            self.add_simple_log(simple_log, 
                f"⚠️ Nova sequência decrescente detectada:")
            self.add_simple_log(simple_log, 
                f"   • Números: {numbers}")
            self.add_simple_log(simple_log, 
                f"   • Terminais: {prev_terminal}→{new_terminal} = +{occurrence_count} jogadas")
            
            return occurrence_count
        
        # Nenhuma ocorrência encontrada
        return 0

class Counter:
    """
    Classe wrapper simplificada com memória de análise.
    """
    def __init__(self):
        self.advanced = AdvancedCounter()
        self.last_analysis = None  # Guarda a última análise
        
    def initial_wait_spins(self, history: List[int], targets: List[int] = None, 
                          signal_log: List[str] = None) -> int:
        """
        Interface simplificada para cálculo inicial.
        """
        if not history:
            return 0
            
        trigger = history[0]
        if targets is None:
            targets = []
        
        temp_log = []
        count, analysis = self.advanced.initial_wait_spins(
            history, targets, trigger, temp_log
        )
        
        self.last_analysis = analysis  # Salva a análise
        
        if signal_log is not None:
            signal_log.extend(temp_log)
        
        logger.info(f"Contagem inicial: {count} jogadas")
        
        return count
    
    def update_wait_spins(self, current_wait: int, history: List[int], 
                         new_number: int, targets: List[int] = None,
                         signal_log: List[str] = None) -> int:
        """
        Interface simplificada com memória de análise.
        """
        if targets is None:
            targets = []
            
        temp_log = []
        count, analysis = self.advanced.update_wait_spins(
            current_wait, history, targets, new_number, None, temp_log,
            self.last_analysis  # Passa a análise anterior
        )
        
        self.last_analysis = analysis  # Atualiza a análise
        
        if signal_log is not None:
            signal_log.extend(temp_log)
            
        return count