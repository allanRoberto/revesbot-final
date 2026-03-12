"""
patterns/base.py

Classe base abstrata para todos os padrões de análise
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any
from dataclasses import dataclass


@dataclass
class PatternResult:
    """
    Resultado da análise de um padrão
    
    Attributes:
        candidatos: Lista de números candidatos
        scores: Dicionário {número: score}
        metadata: Informações adicionais sobre a análise
        pattern_name: Nome do padrão que gerou este resultado
    """
    candidatos: List[int]
    scores: Dict[int, float]
    metadata: Dict[str, Any]
    pattern_name: str
    
    def get_top_n(self, n: int) -> List[tuple[int, float]]:
        """
        Retorna os top N candidatos ordenados por score
        
        Args:
            n: Quantidade de candidatos
        
        Returns:
            Lista de tuplas (número, score)
        """
        sorted_items = sorted(
            self.scores.items(),
            key=lambda x: x[1],
            reverse=True
        )
        return sorted_items[:n]


class BasePattern(ABC):
    """
    Classe base abstrata para todos os padrões
    
    Todos os padrões (Master, Estelar, Chain, Temporal) 
    devem herdar desta classe e implementar o método analyze()
    """
    
    def __init__(self, config: Dict[str, Any] = None):
        """
        Inicializa o padrão
        
        Args:
            config: Dicionário de configurações específicas do padrão
        """
        self.config = config or {}
        self.name = self.__class__.__name__
    
    @abstractmethod
    def analyze(self, history: List[int]) -> PatternResult:
        """
        Analisa o histórico e retorna candidatos
        
        Este método DEVE ser implementado por todas as classes filhas
        
        Args:
            history: Lista de números do histórico (mais recente no índice 0)
        
        Returns:
            PatternResult com candidatos, scores e metadata
        
        Raises:
            NotImplementedError: Se não for implementado pela classe filha
        """
        raise NotImplementedError(
            f"O padrão {self.name} deve implementar o método analyze()"
        )
    
    def validate_history(self, history: List[int], min_size: int = 10) -> bool:
        """
        Valida se o histórico tem tamanho mínimo e números válidos
        
        Args:
            history: Lista de números
            min_size: Tamanho mínimo do histórico
        
        Returns:
            True se válido, False caso contrário
        """
        if not history or len(history) < min_size:
            return False
        
        # Verificar se todos os números são válidos (0-36)
        return all(0 <= n <= 36 for n in history)
    
    def normalize_scores(self, scores: Dict[int, float]) -> Dict[int, float]:
        """
        Normaliza scores para o intervalo [0, 1]
        
        Args:
            scores: Dicionário {número: score}
        
        Returns:
            Dicionário com scores normalizados
        """
        if not scores:
            return {}
        
        max_score = max(scores.values())
        if max_score == 0:
            return scores
        
        return {
            numero: score / max_score
            for numero, score in scores.items()
        }
    
    def get_config_value(self, key: str, default: Any) -> Any:
        """
        Obtém valor de configuração com fallback para default
        
        Args:
            key: Chave da configuração
            default: Valor padrão
        
        Returns:
            Valor da configuração ou default
        """
        return self.config.get(key, default)
    
    def __str__(self) -> str:
        """Representação em string do padrão"""
        return f"{self.name}(config={self.config})"
    
    def __repr__(self) -> str:
        """Representação técnica do padrão"""
        return self.__str__()