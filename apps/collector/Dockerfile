# Usa imagem base do Python
FROM python:3.11-slim

# Define diretório de trabalho
WORKDIR /app

# Copia os arquivos para dentro do container
COPY . .

# Instala dependências
RUN pip install --no-cache-dir -r requirements.txt

# Define variável obrigatória para o Cloud Run
ENV PORT=8080

# Expõe a porta para o Cloud Run
EXPOSE 8080

# Comando de inicialização
CMD ["python", "main.py"]

