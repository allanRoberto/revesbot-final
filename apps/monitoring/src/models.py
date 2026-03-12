from pydantic import BaseModel, Field, model_validator
from uuid import UUID
from typing import List, Dict, Optional, Any, Union, Literal

class ResultMessage(BaseModel):
    slug: str
    number: int = Field(..., alias="result")

    class Config:
        validate_by_name = True


class TemperatureState(BaseModel):
    value: float = 50.0
    last_event_id: Optional[str] = None
    updated_at: float = 0.0


class Signal(BaseModel):
    id: UUID
    roulette_id: Optional[str] = None
    roulette_name: Optional[str] = None
    roulette_url: Optional[str] = None
    pattern: Optional[str] = None
    
    # ══════════════════════════════════════════════════════════════════════════
    # NOVOS CAMPOS PARA SISTEMA PAI/FILHO
    # ══════════════════════════════════════════════════════════════════════════
    
    # Tipo do sinal: "parent" (controle) ou "child" (contabiliza WIN/LOSS)
    signal_type: Optional[Literal["parent", "child"]] = None
    
    # ID do pai (apenas para filhos)
    parent_id: Optional[str] = None
    
    # ══════════════════════════════════════════════════════════════════════════
    
    triggers: Union[int, List[int]] = Field(...)
    bets: Optional[List[int]] = Field(default_factory=list)
    targets: Optional[List[int]] = Field(default_factory=list)
    message: Optional[str] = None
    status: str
    broadcasted: bool = False
    created_at: Optional[Any] = None
    updated_at: Optional[Any] = None
    passed_spins: int = 0
    spins_after_trigger: int = 0
    
    # Monitoramento pós-WIN
    spins_after_win: int = 0
    greens_after_win: int = 0
    greens_after_win_at: List[int] = Field(default_factory=list)

    # Monitoramento pós-LOST  
    spins_after_lost: int = 0
    greens_after_lost: int = 0
    greens_after_lost_at: List[int] = Field(default_factory=list)

    # Monitoramento pós-CANCELLED
    spins_after_cancelled: int = 0
    greens_after_cancelled: int = 0
    greens_after_cancelled_at: List[int] = Field(default_factory=list)
    
    wait_spins_after_trigger: int = 0
    numbers_after_trigger: Optional[List[int]] = []

    monitoring_attempts: int = 0
    monitoring_gale: int = 0
    
    spins_required: int = 12
    gales: int = 12
    score: float = 1
    snapshot: Optional[List[int]] = []
    history: Optional[List[int]] = []
    attempts: int = Field(0)
    wait_spins: int = Field(0)
    from_0: int = Field(0) 
    paid_waiting: bool = False
    active_bet: bool = False
    imediate: bool = False
    tags: Optional[List[str]] = Field(default_factory=list)
    
    # ALTERADO: Agora aceita qualquer tipo de valor
    analysis: Dict[str, Any] = Field(default_factory=dict)
    
    # ALTERADO: Agora aceita dict genérico para temp_state
    temp_state: Optional[Union[Dict[str, Any], TemperatureState]] = None
    
    log: List[str] = Field(default_factory=list)
    temperature_score: float = 0.0
    temperature_confidence: float = 0.0
    temperature_decision: str = ""
    
    @model_validator(mode='before')
    @classmethod
    def normalize_triggers(cls, values):
        t = values.get('triggers')
        if isinstance(t, int):
            values['triggers'] = [t]
        return values

    class Config:
        extra = "ignore"
    
    # ══════════════════════════════════════════════════════════════════════════
    # MÉTODOS AUXILIARES
    # ══════════════════════════════════════════════════════════════════════════
    
    def is_parent(self) -> bool:
        """Verifica se é um sinal PAI."""
        return self.signal_type == "parent" or self.pattern == "NUMEROS_PUXANDO"
    
    def is_child(self) -> bool:
        """Verifica se é um sinal FILHO."""
        return self.signal_type == "child" or self.pattern == "NUMEROS_PUXANDO_CHILD"
    
    def should_count_result(self) -> bool:
        """
        Verifica se este sinal deve ser contabilizado como WIN/LOSS.
        
        PAIs não contabilizam, apenas FILHOs.
        """
        # Se é explicitamente um PAI, não contabiliza
        if self.is_parent():
            return False
        
        # Se tem tag "nao_contabilizar", não contabiliza
        if self.tags and "nao_contabilizar" in self.tags:
            return False
        
        return True
    
    def get_temp_state_value(self, key: str, default: Any = None) -> Any:
        """Obtém valor do temp_state de forma segura."""
        if self.temp_state is None:
            return default
        
        if isinstance(self.temp_state, dict):
            return self.temp_state.get(key, default)
        
        if hasattr(self.temp_state, key):
            return getattr(self.temp_state, key, default)
        
        return default
    
    def set_temp_state_value(self, key: str, value: Any) -> None:
        """Define valor no temp_state."""
        if self.temp_state is None:
            self.temp_state = {}
        
        if isinstance(self.temp_state, dict):
            self.temp_state[key] = value
        elif hasattr(self.temp_state, '__setattr__'):
            setattr(self.temp_state, key, value)
