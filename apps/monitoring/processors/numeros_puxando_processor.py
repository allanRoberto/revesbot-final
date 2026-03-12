"""
Processor para o pattern NUMEROS_PUXANDO

Gerencia o ciclo de vida do SINAL PAI e cria SINAIS FILHOS quando necessário.

Regras:
1. PAI nunca é contabilizado como WIN/LOSS
2. Apenas 1 FILHO ativo por vez
3. Se pagamento do filho = gatilho, NÃO cria novo filho imediatamente
4. PAI expira em 30 spins OU 3 ativações
5. FILHO é criado via save_signal() e processado independentemente
"""

import logging
from datetime import datetime
from typing import Dict, Any, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)


class NumerosPuxandoProcessor:
    """
    Processor para sinais do tipo NUMEROS_PUXANDO.
    
    Diferencia entre PAI e FILHO e processa cada um adequadamente.
    """
    
    def __init__(self, redis_client, save_signal_func=None):
        """
        Args:
            redis_client: Cliente Redis para persistência
            save_signal_func: Função save_signal do core.redis para criar filhos
        """
        self.redis_client = redis_client
        self.save_signal = save_signal_func
    
    async def process_spin(self, signal, number: int) -> Dict[str, Any]:
        """
        Processa um spin para o pattern NUMEROS_PUXANDO.
        
        Detecta se é PAI ou FILHO e direciona para o método correto.
        """
        signal_type = self._get_signal_type(signal)
        
        if signal_type == "parent":
            return await self._process_parent(signal, number)
        elif signal_type == "child":
            return await self._process_child(signal, number)
        else:
            # Fallback: tratar como filho (compatibilidade)
            return await self._process_child(signal, number)
    
    # ══════════════════════════════════════════════════════════════════════════
    # PROCESSAMENTO DO PAI
    # ══════════════════════════════════════════════════════════════════════════
    
    async def _process_parent(self, signal, number: int) -> Dict[str, Any]:
        """
        Processa spin para SINAL PAI.
        
        O PAI:
        - Conta spins totais
        - Verifica se deve criar filho (gatilho apareceu)
        - Controla se há filho ativo
        - Finaliza quando atinge limites
        """
        temp_state = self._get_temp_state(signal)
        
        # Incrementar contador de spins
        temp_state["total_spins"] += 1
        total_spins = temp_state["total_spins"]
        
        # Atualizar histórico do pai
        self._update_history(signal, number)
        
        # ══════════════════════════════════════════════════════════════════
        # VERIFICAR SE DEVE FINALIZAR
        # ══════════════════════════════════════════════════════════════════
        if self._should_finalize_parent(temp_state):
            return self._finalize_parent(signal, temp_state)
        
        # ══════════════════════════════════════════════════════════════════
        # SE HÁ FILHO ATIVO, NÃO FAZ NADA (filho processa separadamente)
        # ══════════════════════════════════════════════════════════════════
        if temp_state.get("child_active", False):
            return {
                "action": "continue",
                "new_status": "waiting",
                "message": f"[PAI] Filho ativo, aguardando... (Spin {total_spins}/{temp_state['max_spins']})",
                "should_persist": True,
                "create_child": False
            }
        
        # ══════════════════════════════════════════════════════════════════
        # VERIFICAR SE É GATILHO
        # ══════════════════════════════════════════════════════════════════
        triggers = self._get_triggers(signal)
        
        if number in triggers:
            # É gatilho! Mas verificar se não é o número que pagou o último filho
            last_win = temp_state.get("last_win_number")
            
            if last_win is not None and number == last_win:
                # Este gatilho foi o pagamento do último filho
                # Resetar e esperar próximo gatilho
                temp_state["last_win_number"] = None
                
                self._log(signal, f"⏭️ Gatilho {number} ignorado (foi pagamento do filho anterior)")
                
                return {
                    "action": "continue",
                    "new_status": "waiting",
                    "message": f"[PAI] Gatilho {number} era pagamento, aguardando próximo... (Spin {total_spins})",
                    "should_persist": True,
                    "create_child": False
                }
            
            # Gatilho válido! Criar filho
            temp_state["last_win_number"] = None  # Resetar
            
            return await self._create_child(signal, number, temp_state)
        
        # Não é gatilho, continua esperando
        return {
            "action": "continue",
            "new_status": "waiting",
            "message": f"[PAI] Aguardando gatilho... (Spin {total_spins}/{temp_state['max_spins']})",
            "should_persist": True,
            "create_child": False
        }
    
    async def _create_child(self, parent_signal, trigger_number: int, temp_state: dict) -> Dict[str, Any]:
        """
        Cria um SINAL FILHO quando gatilho é ativado.
        """
        activation_num = temp_state["current_activation"] + 1
        print(activation_num, "activation_num")
        print(temp_state, "temp_state")
        temp_state["current_activation"] = activation_num
        temp_state["child_active"] = True
        
        # Dados do filho
        parent_id = self._get_id(parent_signal)
        child_id = None
        
        self._log(parent_signal, f"🎯 Gatilho {trigger_number} ativado! Criando filho #{activation_num}")
        
        # ══════════════════════════════════════════════════════════════════
        # CRIAR FILHO VIA save_signal
        # ══════════════════════════════════════════════════════════════════
        if self.save_signal:
            child_id = self.save_signal(
                roulette_id=self._get_attr(parent_signal, "roulette_id"),
                roulette_name=self._get_attr(parent_signal, "roulette_name"),
                roulette_url=self._get_attr(parent_signal, "roulette_url"),
                triggers=[trigger_number],  # Só o gatilho que ativou
                targets=self._get_attr(parent_signal, "targets") or [],
                bets=self._get_attr(parent_signal, "bets") or [],
                snapshot=self._get_attr(parent_signal, "snapshot") or [],
                status="processing",  # Filho já começa monitorando
                pattern="NUMEROS_PUXANDO_CHILD",  # Pattern diferente para identificar
                passed_spins=0,
                spins_required=0,
                gales=temp_state.get("gales_per_child", 3),
                score=temp_state.get("analysis_score", 0),
                message=f"[FILHO #{activation_num}] Monitorando após gatilho {trigger_number}",
                temp_state={
                    "signal_type": "child",
                    "parent_id": str(parent_id),
                    "trigger_number": trigger_number,
                    "activation_number": activation_num,
                    "attempts": 0,
                },
                tags=["numeros_puxando", "child", f"parent:{parent_id}"],
            )
            
            if child_id:
                temp_state["active_child_id"] = child_id
                temp_state["children_ids"].append(child_id)
                logger.info(f"[NUMEROS_PUXANDO] Filho {child_id} criado para pai {parent_id}")
        
        return {
            "action": "continue",
            "new_status": "waiting",  # PAI continua waiting
            "message": f"[PAI] Filho #{activation_num} criado (gatilho {trigger_number})",
            "should_persist": True,
            "create_child": True,
            "child_id": child_id,
            "trigger_number": trigger_number
        }
    
    def _should_finalize_parent(self, temp_state: dict) -> bool:
        """Verifica se o PAI deve ser finalizado."""
        max_activations = temp_state.get("max_activations", 3)
        max_spins = temp_state.get("max_spins", 30)
        
        # Atingiu máximo de ativações?
        if temp_state.get("current_activation", 0) >= max_activations:
            # Só finaliza se não tiver filho ativo
            if not temp_state.get("child_active", False):
                return True
        
        # Atingiu máximo de spins?
        if temp_state.get("total_spins", 0) >= max_spins:
            # Só finaliza se não tiver filho ativo
            if not temp_state.get("child_active", False):
                return True
        
        return False
    
    def _finalize_parent(self, signal, temp_state: dict) -> Dict[str, Any]:
        """Finaliza o SINAL PAI."""
        wins = temp_state.get("total_wins", 0)
        losses = temp_state.get("total_losses", 0)
        total = wins + losses
        activations = temp_state.get("current_activation", 0)
        spins = temp_state.get("total_spins", 0)
        
        win_rate = (wins / total * 100) if total > 0 else 0
        
        summary = (
            f"[PAI] COMPLETO | "
            f"Ativações: {activations} | "
            f"Filhos: {total} (W:{wins} L:{losses}) | "
            f"Taxa: {win_rate:.1f}% | "
            f"Spins: {spins}"
        )
        
        self._log(signal, f"🏁 {summary}")
        
        return {
            "action": "finalize",
            "new_status": "completed",  # PAI usa "completed", não "win"/"lost"
            "message": summary,
            "should_persist": True,
            "create_child": False,
            "final_stats": {
                "total_activations": activations,
                "total_children": total,
                "wins": wins,
                "losses": losses,
                "win_rate": win_rate,
                "total_spins": spins,
                "children_ids": temp_state.get("children_ids", [])
            }
        }
    
    # ══════════════════════════════════════════════════════════════════════════
    # PROCESSAMENTO DO FILHO
    # ══════════════════════════════════════════════════════════════════════════
    
    async def _process_child(self, signal, number: int) -> Dict[str, Any]:
        """
        Processa spin para SINAL FILHO.
        
        O FILHO:
        - Verifica se número está em bets
        - Conta tentativas (gales)
        - Finaliza como WIN ou LOST
        - Notifica PAI quando finaliza
        """
        temp_state = self._get_temp_state(signal)
        bets = self._get_bets(signal)
        gales = self._get_gales(signal)
        
        # Incrementar tentativas
        attempts = temp_state.get("attempts", 0) + 1
        temp_state["attempts"] = attempts
        
        # Atualizar histórico
        self._update_history(signal, number)
        
        trigger_number = temp_state.get("trigger_number", "?")
        activation_num = temp_state.get("activation_number", "?")
        
        if number in bets:
            # ✅ ACERTOU!
            self._log(signal, f"✅ GREEN! Número {number} no gale {attempts}")
            
            return {
                "action": "finalize",
                "new_status": "win",
                "message": f"[FILHO #{activation_num}] ✅ WIN! Número {number} (Gale {attempts})",
                "should_persist": True,
                "hit_number": number,
                "gale_hit": attempts,
                "notify_parent": True,
                "parent_id": temp_state.get("parent_id"),
                "result": "win"
            }
        
        else:
            # Não acertou
            if attempts >= gales:
                # ❌ PERDEU
                self._log(signal, f"❌ RED! Não bateu em {gales} tentativas")
                
                return {
                    "action": "finalize",
                    "new_status": "lost",
                    "message": f"[FILHO #{activation_num}] ❌ LOST! Não bateu em {gales} gales",
                    "should_persist": True,
                    "hit_number": None,
                    "gale_hit": None,
                    "notify_parent": True,
                    "parent_id": temp_state.get("parent_id"),
                    "result": "loss"
                }
            
            # Continua tentando
            return {
                "action": "continue",
                "new_status": "monitoring",
                "message": f"[FILHO #{activation_num}] 🔄 Gale {attempts}/{gales} - Número {number}",
                "should_persist": True,
                "notify_parent": False
            }
    
    # ══════════════════════════════════════════════════════════════════════════
    # NOTIFICAÇÃO DO FILHO PARA O PAI
    # ══════════════════════════════════════════════════════════════════════════
    
    async def notify_parent_of_child_result(
        self, 
        parent_signal, 
        child_result: str, 
        hit_number: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Notifica o PAI sobre o resultado do FILHO.
        
        Chamado pelo processor principal quando um FILHO finaliza.
        
        Args:
            parent_signal: Sinal pai
            child_result: "win" ou "loss"
            hit_number: Número que pagou (se win)
        """
        temp_state = self._get_temp_state(parent_signal)
        
        # Atualizar estatísticas
        if child_result == "win":
            temp_state["total_wins"] = temp_state.get("total_wins", 0) + 1
            temp_state["last_win_number"] = hit_number  # Para evitar criar filho imediato
            self._log(parent_signal, f"📊 Filho finalizou: WIN (número {hit_number})")
        else:
            temp_state["total_losses"] = temp_state.get("total_losses", 0) + 1
            temp_state["last_win_number"] = None
            self._log(parent_signal, f"📊 Filho finalizou: LOSS")
        
        # Liberar filho
        temp_state["child_active"] = False
        temp_state["active_child_id"] = None
        
        # Verificar se deve finalizar
        if self._should_finalize_parent(temp_state):
            return self._finalize_parent(parent_signal, temp_state)
        
        # Continua aguardando próximo gatilho
        return {
            "action": "continue",
            "new_status": "waiting",
            "message": f"[PAI] Filho finalizou ({child_result}), aguardando próximo gatilho...",
            "should_persist": True
        }
    
    # ══════════════════════════════════════════════════════════════════════════
    # HELPERS
    # ══════════════════════════════════════════════════════════════════════════
    
    def _get_signal_type(self, signal) -> str:
        """Retorna o tipo do sinal (parent/child)."""
        # Verificar em temp_state primeiro
        temp_state = self._get_temp_state(signal)
        if temp_state.get("signal_type"):
            return temp_state["signal_type"]
        
        # Verificar atributo direto
        if hasattr(signal, 'signal_type'):
            return signal.signal_type or "child"
        if isinstance(signal, dict):
            return signal.get('signal_type', 'child')
        
        # Verificar pelo pattern
        pattern = self._get_attr(signal, "pattern")
        if pattern == "NUMEROS_PUXANDO":
            return "parent"
        if pattern == "NUMEROS_PUXANDO_CHILD":
            return "child"
        
        return "child"  # Default
    
    def _get_temp_state(self, signal) -> dict:
        """Obtém ou inicializa temp_state."""
        if hasattr(signal, 'temp_state') and signal.temp_state:
            if isinstance(signal.temp_state, dict):
                return signal.temp_state
            if hasattr(signal.temp_state, '__dict__'):
                return signal.temp_state.__dict__
        if isinstance(signal, dict) and signal.get('temp_state'):
            return signal['temp_state']
        
        # Inicializar
        default = {"attempts": 0}
        if hasattr(signal, 'temp_state'):
            signal.temp_state = default
        elif isinstance(signal, dict):
            signal['temp_state'] = default
        return default
    
    def _get_attr(self, signal, attr: str, default=None):
        """Obtém atributo do sinal."""
        if hasattr(signal, attr):
            return getattr(signal, attr, default)
        if isinstance(signal, dict):
            return signal.get(attr, default)
        return default
    
    def _get_id(self, signal):
        return self._get_attr(signal, 'id')
    
    def _get_triggers(self, signal) -> list:
        return self._get_attr(signal, 'triggers') or []
    
    def _get_bets(self, signal) -> list:
        return self._get_attr(signal, 'bets') or []
    
    def _get_gales(self, signal) -> int:
        return self._get_attr(signal, 'gales') or 3
    
    def _update_history(self, signal, number: int):
        """Adiciona número ao histórico."""
        if hasattr(signal, 'history'):
            if signal.history is None:
                signal.history = []
            #signal.history.insert(0, number)
        elif isinstance(signal, dict):
            if 'history' not in signal:
                signal['history'] = []
            #signal['history'].insert(0, number)
    
    def _log(self, signal, message: str):
        """Adiciona entrada no log."""
        timestamp = datetime.now().strftime('%H:%M:%S')
        log_entry = f"[{timestamp}] {message}"
        
        if hasattr(signal, 'log'):
            if signal.log is None:
                signal.log = []
            signal.log.append(log_entry)
        elif isinstance(signal, dict):
            if 'log' not in signal:
                signal['log'] = []
            signal['log'].append(log_entry)
        
        logger.info(f"[NUMEROS_PUXANDO] {message}")


# ══════════════════════════════════════════════════════════════════════════════
# FUNÇÕES AUXILIARES PARA INTEGRAÇÃO
# ══════════════════════════════════════════════════════════════════════════════

def is_numeros_puxando_signal(signal) -> bool:
    """Verifica se o sinal é do pattern NUMEROS_PUXANDO."""
    pattern = None
    if hasattr(signal, 'pattern'):
        pattern = signal.pattern
    elif isinstance(signal, dict):
        pattern = signal.get('pattern')
    
    return pattern in ("NUMEROS_PUXANDO", "NUMEROS_PUXANDO_CHILD")


def is_parent_signal(signal) -> bool:
    """Verifica se é um sinal PAI."""
    pattern = None
    if hasattr(signal, 'pattern'):
        pattern = signal.pattern
    elif isinstance(signal, dict):
        pattern = signal.get('pattern')
    
    return pattern == "NUMEROS_PUXANDO"


def is_child_signal(signal) -> bool:
    """Verifica se é um sinal FILHO."""
    pattern = None
    if hasattr(signal, 'pattern'):
        pattern = signal.pattern
    elif isinstance(signal, dict):
        pattern = signal.get('pattern')
    
    return pattern == "NUMEROS_PUXANDO_CHILD"


def get_parent_id_from_child(signal) -> Optional[str]:
    """Obtém o ID do pai a partir de um sinal filho."""
    temp_state = None
    
    if hasattr(signal, 'temp_state') and signal.temp_state:
        temp_state = signal.temp_state
    elif isinstance(signal, dict):
        temp_state = signal.get('temp_state', {})
    
    if isinstance(temp_state, dict):
        return temp_state.get('parent_id')
    
    return None