from typing import TypedDict, List, Optional
from datetime import datetime


class Signal(TypedDict):
    roulette_id: str
    description : str
    triggers : List[int]
    target : List[int]
    bets: List[int]
    snapshot: List[int]
    created_at : datetime
    pattern : str
