from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from bs4 import BeautifulSoup
import time
import os
from webdriver_manager.chrome import ChromeDriverManager
import requests
from datetime import datetime

time.sleep(0.5)
# Definições para o Selenium funcionar no modo headless
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'

chrome_options = Options()
chrome_options.add_argument("--headless")
chrome_options.add_argument("--disable-gpu")
chrome_options.add_argument("--no-sandbox")
chrome_options.add_argument("--disable-dev-shm-usage")

# O buildpack deve definir automaticamente o caminho do ChromeDriver
#para rodar no heroku substitua um pelo outro
#service = Service(os.environ.get("CHROMEDRIVER_PATH"))
service = Service(ChromeDriverManager().install())
driver = webdriver.Chrome(service=service, options=chrome_options)

# Dicionário de URLs das roletas com nomes
roletas = {
    "Mega Roleta": "https://gamblingcounting.com/pt-BR/pragmatic-mega-roulette",
    #"Roulette Ruby":"https://gamblingcounting.com/pragmatic-roulette-ruby",
    #"Roulette Macao":"https://gamblingcounting.com/pragmatic-roulette-macao",
    #"Roulette Azure":"https://gamblingcounting.com/pragmatic-roulette-azure",
    #"German Roulette":"https://gamblingcounting.com/pragmatic-german-roulette",
    #"Turkish Roulette":"https://gamblingcounting.com/pragmatic-turkish-roulette",
    #"Roulette Indian":"https://gamblingcounting.com/pragmatic-roulette-indian",
    #"Spanish Roulette":"https://gamblingcounting.com/pragmatic-spanish-roulette",
    "xxxtreme-lightning-roulette": "https://gamblingcounting.com/xxxtreme-lightning-roulette",
    "Auto-Roulette Evolution":"https://gamblingcounting.com/evolution-auto-roulette",
    "Quantum Roulette Live":"https://gamblingcounting.com/quantum-roulette",
    "Roleta Brasileira":"https://gamblingcounting.com/playtech-roleta-brasileira",
    #"Auto Roulette Pragmatic":"https://gamblingcounting.com/pragmatic-auto-roulette",
    "Roleta Brasileira Pragmatic":"https://gamblingcounting.com/pragmatic-brazilian-roulette",
    "Auto Mega Roulette":"https://gamblingcounting.com/pragmatic-auto-mega-roulette",
    "Speed Roulette 1":"https://gamblingcounting.com/pragmatic-speed-roulette-1",
    "Speed Auto Roulette":"https://gamblingcounting.com/pragmatic-speed-auto-roulette",
    #"Roulette Green":"https://gamblingcounting.com/pragmatic-roulette-green",
    #"Brazillian Mega Roulette":"https://gamblingcounting.com/pragmatic-mega-roulette-brazilian",
    #"THE CLUB":"https://gamblingcounting.com/pragmatic-vip-roulette-the-club",
    "Speeed Roulette 2":"https://gamblingcounting.com/pragmatic-speed-roulette-2",
    "Lightning Roulette":"https://gamblingcounting.com/lightning-roulette",
    "Immersive Roulette":"https://gamblingcounting.com/immersive-roulette",
    #"Turkia Lightning Roulette":"https://gamblingcounting.com/turkey-lightning-roulette",
    #"Red Door Roulette":"https://gamblingcounting.com/red-door-roulette",
    #"Roulette Evo":"https://gamblingcounting.com/evolution-roulette",
    #"Gold Vault Roulette":"https://gamblingcounting.com/gold-vault-roulette",
    "Auto Roulette VIP Evo":"https://gamblingcounting.com/evolution-auto-roulette-vip",
    #"Roulette Spanish Evo":"https://gamblingcounting.com/ruleta-en-espanol",
    #"Roleta ao Vivo":"https://gamblingcounting.com/evolution-roleta-ao-vivo",
    "Speed Roulette Evo":"https://gamblingcounting.com/evolution-speed-roulette",
    #"Hind Lightining Roulette":"https://gamblingcounting.com/hindi-lightning-roulette",
    "Greek Quantum Roulette":"https://gamblingcounting.com/greek-quantum-roulette",
    "Turkish Roulette":"https://gamblingcounting.com/playtech-turkish-roulette",
    "Roulette":"https://gamblingcounting.com/playtech-roulette",
    "Arabic Roulette":"https://gamblingcounting.com/playtech-arabic-roulette",
    "Greek Roulette":"https://gamblingcounting.com/playtech-greek-roulette",
    "Roulette Italiana":"https://gamblingcounting.com/playtech-roulette-italiana",
    "Hind Roulette":"https://gamblingcounting.com/playtech-hindi-roulette",
    "Bucharest Roulette":"https://gamblingcounting.com/playtech-bucharest-roulette",


}

time.sleep(2)


# Lista fixa da roleta europeia
roulette_european_numbers = [
    0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23, 10, 5,
    24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26
]

# Função para encontrar vizinhos na roleta europeia
def find_neighbors(number):
    idx = roulette_european_numbers.index(number)
    neighbor_left = roulette_european_numbers[(idx - 1) % len(roulette_european_numbers)]
    neighbor_right = roulette_european_numbers[(idx + 1) % len(roulette_european_numbers)]
    return [neighbor_left, neighbor_right]

# Função para encontrar o espelho de um número
def find_mirror(number):
    mirror_mapping = {
        2: 20, 20: 2, 32: 23, 23: 32, 1:10, 10:1, 3:30, 30:3, 6:9, 9:6,
        12:21, 21:12, 13:31, 31:13, 16:19, 19:16, 26:29, 29:26,
    }
    return mirror_mapping.get(number, None)

chat_id = "-1002303395079"

# Função para enviar mensagens para o Telegram
def send_telegram_message(message):
    telegram_token = "8025852537:AAFj-j0rDK22RV5dZwdlHcxigLwwNwDo3ws"
    chat_id        = "-1002634558541"
    telegram_api_url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
    data = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown"  # Para formatar o texto em Markdown, se necessário
    }
    try:
        response = requests.post(telegram_api_url, data=data)
        if response.status_code == 200:
            print(f"Mensagem enviada para o Telegram: {message}")
        else:
            print(f"Erro ao enviar mensagem para o Telegram. Código de status: {response.status_code}")
    except Exception as e:
        print(f"Erro ao enviar mensagem para o Telegram: {e}")


def send_telegram_message_with_button(message, button_text, button_url):
    telegram_token = "8025852537:AAFj-j0rDK22RV5dZwdlHcxigLwwNwDo3ws"
    chat_id        = "-1002634558541"
    telegram_api_url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
    data = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown",
        "reply_markup": {
            "inline_keyboard": [
                [{"text": button_text, "url": button_url}]
            ]
        }
    }

    try:
        response = requests.post(telegram_api_url, json=data)
        if response.status_code == 200:
            result = response.json().get("result")
            message_id = result.get("message_id")
            print(f"Mensagem enviada com sucesso. ID da mensagem: {message_id}")
            return message_id  # Retorna o message_id para uso posterior
        else:
            print(f"Erro ao enviar mensagem. Código de status: {response.status_code}")
    except Exception as e:
        print(f"Erro ao enviar mensagem: {e}")
    return None


def delete_telegram_message(message_id):
    telegram_token = "8025852537:AAFj-j0rDK22RV5dZwdlHcxigLwwNwDo3ws"
    chat_id        = "-1002634558541"
    telegram_api_url = f"https://api.telegram.org/bot{telegram_token}/deleteMessage"
    data = {
        "chat_id": chat_id,
        "message_id": message_id
    }
    try:
        response = requests.post(telegram_api_url, json=data)
        if response.status_code == 200:
            print("Mensagem excluída com sucesso.")
        else:
            print(f"Erro ao excluir a mensagem. Código de status: {response.status_code}")
    except Exception as e:
        print(f"Erro ao excluir a mensagem: {e}")


def edit_telegram_message(new_text, button_text, button_url, message_id):
    telegram_token = "8025852537:AAFj-j0rDK22RV5dZwdlHcxigLwwNwDo3ws"
    chat_id        = "-1002634558541"
    telegram_api_url = f"https://api.telegram.org/bot{telegram_token}/editMessageText"
    data = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": new_text,
        "parse_mode": "Markdown",
        "reply_markup": {
            "inline_keyboard": [
                [{"text": button_text, "url": button_url}]
            ]
        }
    }
    try:
        response = requests.post(telegram_api_url, json=data)
        if response.status_code == 200:
            print("Mensagem editada com sucesso.")
        else:
            print(f"Erro ao editar a mensagem. Código de status: {response.status_code}")
    except Exception as e:
        print(f"Erro ao editar a mensagem: {e}")

# Enviar uma mensagem inicial para indicar que o bot está iniciando
start_message = "🤖 *Revesbot está iniciando!*\n"
send_telegram_message(start_message)


# Função para extrair os novos números da roleta (busca da página)
# Função para extrair os primeiros 50 números da roleta (excluindo multiplicadores)
def get_new_random_list(driver, url):
    driver.get(url)
    
    try:
        # Espera explícita até que os números da roleta sejam carregados
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CLASS_NAME, "roulette-number--small"))
        )   
    except Exception as e:
        print(f"Erro ao esperar por elementos na página: {e}")
        return []

    # Obtenção do HTML da página e parse com BeautifulSoup
    html = driver.page_source
    soup = BeautifulSoup(html, 'html.parser')

    # Extração dos números da roleta
    elements = soup.find_all(class_='roulette-number--small')

    value = []
    for element in elements:
        # Extrai o número da roleta, ignorando o multiplicador (elemento filho)
        numero = element.find(text=True, recursive=False).strip()  # Pega apenas o número diretamente dentro de 'roulette-number--small'
        
        if numero.isdigit():  # Verifica se o texto é realmente um número
            value.append(numero)
    
    try:
        # Conversão para lista de inteiros e limitar aos primeiros 50 números
        resultado = list(map(int, value[0:120]))  
        return resultado
    except ValueError as e:
        print(f"Erro na conversão para inteiro: {e}")
        return []  # Retorna lista vazia em caso de erro
    




# Obtenha o link personalizado da roleta
roletas_personalizadas = {
                "Mega Roleta": "https://bateu.bet.br/games/pragmaticplay/mega-roleta",
                #"Roulette Ruby":"https://lotusbet.live/live-casino/game/2830099?provider=Pragmatic&from=%2Flive-casino%3Fcategory%3D28454",
                #"Roulette Macao":"https://lotusbet.live/live-casino/game/2830486?provider=Pragmatic&from=%2Flive-casino%3Fcategory%3D28454",
                #"Roulette Azure":"https://lotusbet.live/live-casino/game/2830484?provider=Pragmatic&from=%2Flive-casino%3Fcategory%3D28454",
                #"German Roulette":"https://apostatudo.bet.br/games/pragmaticplay/roulette-5-german",
                #"Turkish Roulette":"https://apostatudo.bet.br/games/pragmaticplay/roulette-6-turkish",
                #"Roulette Indian":"https://apostatudo.bet.br/games/pragmaticplay/live-roulette-8-indian",
                #"Spanish Roulette":"https://apostatudo.bet.br/games/pragmaticplay/live-roulette-14-spanish",
                "xxxtreme-lightning-roulette": "https://bateu.bet.br/games/evolution/xxxtreme-lightning-roulette",
                "Auto-Roulette Evolution":"https://bateu.bet.br/games/evolution/auto-roulette",
                "Quantum Roulette Live":"https://bateu.bet.br/games/playtech/quantum-roulette",
                "Roleta Brasileira":"https://bateu.bet.br/games/playtech/roleta-brasileira",
                #"Auto Roulette Pragmatic":"https://lotusbet.live/live-casino/game/2830488?provider=Pragmatic&from=%2Flive-casino%3Fcategory%3D28454%26providerNames%3DPragmatic",
                "Roleta Brasileira Pragmatic":"https://bateu.bet.br/games/pragmaticplay/roleta-brasileira",
                "Auto Mega Roulette":"https://bateu.bet.br/games/pragmaticplay/auto-mega-roulette",
                "Speed Roulette 1":"https://bateu.bet.br/games/pragmaticplay/speed-roulette-1",
                "Speed Auto Roulette":"https://bateu.bet.br/games/pragmaticplay/speed-auto-roulette",
                #"Roulette Green":"https://lotusbet.live/live-casino/game/2830485?provider=Pragmatic&from=%2Flive-casino%3Fcategory%3D28454%26providerNames%3DPragmatic",
                #"Brazillian Mega Roulette":"https://gamblingcounting.com/pragmatic-mega-roulette-brazilian",
                #"THE CLUB":"https://lotusbet.live/live-casino/game/2834561?provider=Pragmatic&from=%2Flive-casino%3Fcategory%3D28454%26providerNames%3DPragmatic",
                "Speeed Roulette 2":"https://bateu.bet.br/games/pragmaticplay/live-speed-roulette-2",
                "Lightning Roulette":"https://bateu.bet.br/games/evolution/lightning-roulette",
                "Immersive Roulette":"https://bateu.bet.br/games/evolution/immersive-roulette",
                #"Turkia Lightning Roulette":"https://lotusbet.live/live-casino/game/2835792?provider=Evolution&from=%2Flive-casino%3Fcategory%3D28454%26providerNames%3DEvolution",
                #"Red Door Roulette":"https://lotusbet.live/live-casino/game/2835803?provider=Evolution&from=%2Flive-casino%3Fcategory%3D28454%26providerNames%3DEvolution",
                #"Roulette Evo":"https://lotusbet.live/live-casino/game/2836821?provider=Evolution&from=%2Flive-casino%3Fcategory%3D28454%26providerNames%3DEvolution",
                #"Gold Vault Roulette":"https://lotusbet.live/live-casino/game/2836482?provider=Evolution&from=%2Flive-casino%3Fcategory%3D28454%26providerNames%3DEvolution",
                "Auto Roulette VIP Evo":"https://bateu.bet.br/games/evolution/auto-roulette-vip",
                #"Roulette Spanish Evo":"https://lotusbet.live/live-casino/game/2836741?provider=Evolution&from=%2Flive-casino%3Fcategory%3D28454%26providerNames%3DEvolution",
                #"Roleta ao Vivo":"https://lotusbet.live/live-casino/game/2836816?provider=Evolution&from=%2Flive-casino%3Fcategory%3D28454%26providerNames%3DEvolution",
                "Speed Roulette Evo":"https://bateu.bet.br/games/evolution/speed-roulette",
                #"Hind Lightining Roulette":"https://lotusbet.live/live-casino/game/2835781?provider=Evolution&from=%2Flive-casino%3Fcategory%3D28454%26providerNames%3DEvolution",
                "Greek Quantum Roulette":"https://bateu.bet.br/games/playtech/greek-quantum-roulette",
                "Turkish Roulette":"https://bateu.bet.br/games/playtech/turkish-roulette",
                "Roulette":"https://bateu.bet.br/games/playtech/roulette",
                "Arabic Roulette":"https://bateu.bet.br/games/playtech/arabic-roulette",
                "Greek Roulette":"https://bateu.bet.br/games/playtech/greek-roulette",
                "Roulette Italiana":"https://bateu.bet.br/games/playtech/roulette-italiana",
                "Hind Roulette":"https://bateu.bet.br/games/playtech/hindi-roulette",
                "Bucharest Roulette":"https://bateu.bet.br/games/playtech/bucharest-roulette",

            }         

def get_terminal(num):
    return num % 10

def process_roleta(roleta, url, driver):
    # Obter a lista de números
    numeros = get_new_random_list(driver, url)
    if len(numeros) < 5:
        return  # Se não houver números suficientes, sai da função

    #Teste
    #numeros = [32, 34, 3, 8, 23, 17, 13, 0, 13, 29, 24, 16, 31, 6, 16, 3, 4, 29, 16, 22, 36, 22, 16, 22, 25, 35, 3, 29, 23, 2, 27, 30, 21, 22, 19, 2, 26, 33, 36, 3, 9, 7, 19, 19, 33, 15, 13, 21, 27, 28, 20, 28, 11, 22, 11, 14, 28, 21, 3, 34, 24, 1, 26, 13, 14, 4, 13, 20, 6, 36, 11, 12, 30, 32, 15, 21, 33, 19, 12, 5, 11, 5, 24, 10, 33, 8, 25, 13, 32, 19, 31, 19, 13, 29, 3, 20, 18, 23, 4, 3, 25, 36, 31, 29, 18, 21, 36, 16, 3, 12, 23, 28, 6, 5, 14, 17, 36, 35]


    # Definindo as posições conforme solicitado
    #Gatilhos
    pos7 = numeros[7]
    pos18 = numeros[18]
    terminal7 = get_terminal(pos7)

    #Verificações
    pos8 = numeros[8]
    pos17 = numeros[17]
    terminal8 = get_terminal(pos8)
    terminal17 = get_terminal(pos17)

    print(f"Roleta {roleta}")
    print(f"Lista extraida: {numeros} ")

    if pos7 != pos18:
        return
    
    if terminal7 == terminal8 or  terminal7 == terminal17 or terminal8 == terminal17:
        return
    
    if pos7 in numeros[0:7]:
        return


    # Recupera URL personalizada, se existir
    url_personalizada = roletas_personalizadas.get(roleta, url)
    button_text = "👉 CADASTRE AQUI"
    button_url = "https://go.aff.bateu.bet.br/tztpwxw1?utm_source=reves"
    numeros = get_new_random_list(driver, url)
    # Primeiro caso: pos8 não reaparece após a primeira confirmação

    message = (
            f"🥷 MINHA PRÓXIMA ENTRADA 🥷\n"
            f"🎰 *Mesa:* [{roleta}]({url_personalizada})\n\n"
            f"🔥 Próximo {pos7} \n Vou entrar em {pos17},{find_neighbors(pos17)} \n\n"
            f"Vou proteger o terminal {terminal17}\n\n"
            f" E 9 Rodadas do {pos7} \n Vou entrar {pos7},{find_neighbors(pos7)} e terminal {terminal7}\n\n"
            f"🟢 Vou Cobrir o zero\n\n"
            f"🔁 Vou Fazer até 2 gales\n\n"
            f"Últimos números que saíram {numeros[0]},{numeros[1]},{numeros[2]}\n\n"
            f"🔞 Apostas são para maiores de 18 anos, não há garantias de lucros, aposte com responsabilidade. 🔞"
        )
    send_telegram_message_with_button(message, button_text, button_url)
    return

while True:
    for roleta, url in roletas.items():
        process_roleta(roleta, url, driver)