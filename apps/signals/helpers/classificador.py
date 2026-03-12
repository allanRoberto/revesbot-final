

class ClassificadorProximidade:
    """Classifica números da roleta por proximidade"""
    
    def __init__(self, peso_principal=1, peso_vizinhos=0, peso_vizinhos1=0, peso_duzia=0, peso_cor=0, peso_puxada=0, qtd_puxada=0, decaimento=0):
        self.peso_principal = peso_principal
        self.peso_vizinhos = peso_vizinhos
        self.peso_vizinhos1 = peso_vizinhos1
        self.peso_duzia = peso_duzia
        self.peso_cor = peso_cor
        self.peso_puxada = peso_puxada
        self.qtd_puxada = qtd_puxada 
        self.decaimento = decaimento
        
        # Pontuação de cada número
        self.scores = {i: 0.0 for i in range(37)}

        # Histórico de números
        self.historico = []

         # Números vermelhos e pretos
        self.vermelhos = [1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36]
        self.pretos = [2, 4, 6, 8, 10, 11, 13, 15, 17, 20, 22, 24, 26, 28, 29, 31, 33, 35]
        
        # Vizinhos físicos na roleta europeia
        self.vizinhos = {
            0: [32, 26], 1: [20, 33], 2: [25, 21], 3: [26, 35],
            4: [21, 19], 5: [10, 24], 6: [27, 34], 7: [29, 28],
            8: [23, 30], 9: [22, 31], 10: [5, 23], 11: [30, 36],
            12: [28, 35], 13: [36, 27], 14: [31, 20], 15: [32, 19],
            16: [24, 33], 17: [25, 34], 18: [29, 22], 19: [15, 4],
            20: [14, 1], 21: [4, 2], 22: [18, 9], 23: [10, 8],
            24: [16, 5], 25: [17, 2], 26: [35, 3], 27: [13, 6],
            28: [12, 7], 29: [7, 18], 30: [8, 11], 31: [9, 14],
            32: [15, 19], 33: [1, 16], 34: [6, 17], 35: [3, 12],
            36: [11, 13]
        }

        self.vizinhos_1 = {
            0: [15, 3], 1: [14, 16], 2: [17, 4], 3: [0, 12],
            4: [2, 15], 5: [23, 16], 6: [17, 13], 7: [12, 18],
            8: [11, 10], 9: [18, 14], 10: [8, 24], 11: [13, 8],
            12: [3, 7], 13: [6, 11], 14: [9, 1], 15: [0, 4],
            16: [1, 5], 17: [2, 6], 18: [7, 9], 19: [32, 21],
            20: [31, 33], 21: [19, 25], 22: [29, 31], 23: [30, 5],
            24: [33, 10], 25: [21, 34], 26: [32, 35], 27: [34, 36],
            28: [35, 29], 29: [28, 22], 30: [36, 23], 31: [22, 20],
            32: [26, 19], 33: [20, 24], 34: [25, 27], 35: [26, 28],
            36: [27, 30]
        }
    
    def aplicar_peso_puxada(self, numero):
        """Aplica peso nos números que vieram após a última ocorrência deste número"""
        # Busca última ocorrência do número no histórico (excluindo a atual)
        ultima_ocorrencia = -1

        for i in range(len(self.historico) - 2, -1, -1):
            if self.historico[i] == numero:
                ultima_ocorrencia = i
                break
        
        if ultima_ocorrencia >= 0:
            # Pega os números após a última ocorrência
            inicio = ultima_ocorrencia + 1
            fim = min(inicio + self.qtd_puxada, len(self.historico) - 1)
            
            if inicio < fim:
                numeros_puxados = self.historico[inicio:fim]
                
                # Aplica peso gradativo (mais próximo = mais peso)
                for i, num_puxado in enumerate(numeros_puxados):
                    # Peso decresce conforme a distância
                    fator_distancia = 1 - (i / self.qtd_puxada)
                    peso = self.peso_puxada * fator_distancia
                    self.scores[num_puxado] += peso
    
    
    def get_cor(self, numero):
        """Retorna a cor do número (vermelho, preto) ou None para o zero"""
        if numero in self.vermelhos:
            return "vermelho"
        elif numero in self.pretos:
            return "preto"
        return None  # Zero não tem cor
    
    def get_numeros_cor(self, cor):
        """Retorna lista de números de uma cor"""
        if cor == "vermelho":
            return self.vermelhos.copy()
        elif cor == "preto":
            return self.pretos.copy()
        return []

    def get_duzia(self, numero):
        """Retorna a dúzia do número (1, 2, 3) ou None para o zero"""
        if numero == 0:
            return None
        elif 1 <= numero <= 12:
            return 1
        elif 13 <= numero <= 24:
            return 2
        elif 25 <= numero <= 36:
            return 3
    
    def get_numeros_duzia(self, duzia):
        """Retorna lista de números de uma dúzia"""
        if duzia == 1:
            return list(range(1, 13))
        elif duzia == 2:
            return list(range(13, 25))
        elif duzia == 3:
            return list(range(25, 37))
        return []


    def adicionar_numero(self, numero):
        """Adiciona um número e pontua ele e seus vizinhos"""
        if not 0 <= numero <= 36:
            raise ValueError(f"Número inválido: {numero}")
        
        # Adiciona ao histórico
        self.historico.append(numero)
        
        # Aplica decaimento
        for n in self.scores:
            self.scores[n] *= (1 - self.decaimento)
        
        # Pontua o número principal
        self.scores[numero] += self.peso_principal
        
        # Pontua os vizinhos
        for vizinho in self.vizinhos[numero]:
            self.scores[vizinho] += self.peso_vizinhos

        for vizinho_1 in self.vizinhos_1[numero]:
            self.scores[vizinho_1] += self.peso_vizinhos1

        # Pontua a dúzia
        duzia = self.get_duzia(numero)
        if duzia:  # Se não for zero
            numeros_duzia = self.get_numeros_duzia(duzia)
            for num_duzia in numeros_duzia:
                if num_duzia != numero:  # Não pontua duas vezes o número principal
                    self.scores[num_duzia] += self.peso_duzia
        
        # Pontua a cor
        cor = self.get_cor(numero)
        if cor:  # Se não for zero
            numeros_cor = self.get_numeros_cor(cor)
            for num_cor in numeros_cor:
                if num_cor != numero:  # Não pontua duas vezes o número principal
                    self.scores[num_cor] += self.peso_cor

        # Aplica peso de puxada (números que vieram após última ocorrência)
        self.aplicar_peso_puxada(numero)
    
    def get_scores(self):
        """Retorna todos os scores"""
        return self.scores
    
    def get_ranking(self):
        """Retorna ranking ordenado por score"""
        return sorted(self.scores.items(), key=lambda x: x[1], reverse=True)
    
    def limpar(self):
        """Limpa todas as pontuações"""
        self.scores = {i: 0.0 for i in range(37)}


