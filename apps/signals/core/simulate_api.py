class SimulatedAPI:
    """Imita apenas o método .api() da RouletteAPI."""
    def __init__(self, history: list[int]):
        self.history = history         # lista de spins (nova→antiga)
        self.index   = 0               # qual já devolvemos

    async def api(self, roulette_id: str, num_results: int = 1):
        # Se já não há mais números, devolve None (comportamento igual ao real)
        if self.index >= len(self.history):
            return None

        # Pega num_results Spins a partir do índice atual
        slice_ = self.history[self.index : self.index + num_results]
        self.index += num_results

        # Formato igual ao RouletteAPI
        return {"results": slice_, "snapshot": slice_}
