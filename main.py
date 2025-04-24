import ccxt
import os
import time
import csv
import pandas as pd
import ta
import requests
from dotenv import load_dotenv
from collections import deque
from datetime import datetime, timezone

# Chargement des clés API
load_dotenv()
api_key = os.getenv("BINANCE_API_KEY")
secret_key = os.getenv("BINANCE_SECRET_KEY")
mode = os.getenv("MODE", "SIMU")

# Portefeuille fictif et seuils de sécurité
portfolio = {'USDC': 1000, 'BTC': 0}
MIN_USDC = 10
MIN_BTC = 0.00001
last_buy_price = None
trade_count = 0
max_trades = 10
start_time = time.time()
max_runtime = 60 * 60  # 1 heure

# Connexion Binance
binance = ccxt.binance({
    'apiKey': api_key,
    'secret': secret_key,
    'enableRateLimit': True,
    'timeout': 30000  # 30 secondes
})

# Telegram
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
    try:
        r = requests.post(url, data=payload)
        if r.status_code == 200:
            print("📲 Alerte Telegram envoyée.")
        else:
            print(f"❌ Échec Telegram : {r.status_code} {r.text}")
    except Exception as e:
        print(f"❌ Erreur Telegram : {e}")

history = deque(maxlen=30)
timestamps, prices = [], []
df = pd.DataFrame({
    "timestamp": pd.Series(dtype='datetime64[ns]'),
    "price": pd.Series(dtype='float'),
    "sma20": pd.Series(dtype='float'),
    "rsi": pd.Series(dtype='float'),
    "macd": pd.Series(dtype='float'),
    "macd_signal": pd.Series(dtype='float'),
    "bb_upper": pd.Series(dtype='float'),
    "bb_lower": pd.Series(dtype='float')
})

def get_price():
    try:
        ticker = binance.fetch_ticker('BTC/USDC')
        return ticker['last']
    except Exception as e:
        print(f"⚠️ Erreur lors de la récupération du prix : {e}")
        return None

def get_real_balance():
    balance = binance.fetch_balance()
    usdc = balance['total'].get('USDC', 0)
    btc = balance['total'].get('BTC', 0)
    return {'USDC': usdc, 'BTC': btc}

def log_trade(action, amount, price, value):
    file_exists = os.path.isfile('trades.csv')
    with open('trades.csv', mode='a', newline='') as file:
        writer = csv.writer(file)
        if not file_exists:
            writer.writerow(['timestamp', 'action', 'amount', 'price', 'value'])
        writer.writerow([
            datetime.now(timezone.utc).isoformat(),
            action,
            f"{amount:.8f}",
            f"{price:.2f}",
            f"{value:.2f}"
        ])

def real_buy(price):
    usdc = get_real_balance()['USDC']
    if usdc < MIN_USDC:
        print("❌ Solde USDC insuffisant pour acheter.")
        return
    quantity = round(usdc / price, 6)
    order = binance.create_market_buy_order('BTC/USDC', quantity)
    print("🟢 Ordre d'achat envoyé :", order)

def real_sell(price):
    btc = get_real_balance()['BTC']
    if btc < MIN_BTC:
        print("❌ Solle BTC insuffisant pour vendre.")
        return
    quantity = round(btc, 6)
    order = binance.create_market_sell_order('BTC/USDC', quantity)
    print("🔴 Ordre de vente envoyé :", order)

def simulate_buy(price):
    global last_buy_price, trade_count
    amount_usdc = portfolio['USDC']
    if amount_usdc > 0:
        btc_bought = (amount_usdc / price) * 0.999
        portfolio['BTC'] = btc_bought
        portfolio['USDC'] = 0
        last_buy_price = price
        value = btc_bought * price
        log_trade("BUY", btc_bought, price, value)
        trade_count += 1
        print(f"Achat simulé : {btc_bought:.6f} BTC à {price} USDC")
        if mode == "REAL":
            real_buy(price)

def simulate_sell(price):
    global last_buy_price, trade_count
    amount_btc = portfolio['BTC']
    if amount_btc > 0:
        usdc_gained = (amount_btc * price) * 0.999
        portfolio['USDC'] = usdc_gained
        portfolio['BTC'] = 0
        log_trade("SELL", amount_btc, price, usdc_gained)
        trade_count += 1
        if last_buy_price:
            diff = price - last_buy_price
            percent = (diff / last_buy_price) * 100
            print(f"🟢 Gain/Pertes: {diff:.2f} USDC (+{percent:.2f}%)")
            last_buy_price = None
        print(f"Vente simulée : {usdc_gained:.2f} USDC à {price} USDC")
        if mode == "REAL":
            real_sell(price)

def analyse_finale(prix_actuel):
    if mode == "REAL":
        solde = get_real_balance()
        total_usdc = solde['USDC'] + solde['BTC'] * prix_actuel
        print("\n📊 Analyse finale (solde réel Binance)")
    else:
        total_usdc = portfolio['USDC'] + portfolio['BTC'] * prix_actuel
        print("\n📊 Analyse finale (portefeuille fictif)")

    profit = total_usdc - 1000
    percent = (profit / 1000) * 100

    print("-" * 30)
    print(f"Trades simulés     : {trade_count}")
    print(f"Valeur totale (USDC): {total_usdc:.2f}")
    print(f"Profit / Perte     : {profit:.2f} USDC ({percent:.2f}%)")

# === Boucle principale ===
while True:
    price = get_price()
    if price is None:
        time.sleep(5)
        continue

    timestamp = datetime.now().strftime("%H:%M:%S")
    history.append(price)
    timestamps.append(timestamp)
    prices.append(price)

    new_row = {'timestamp': datetime.now(timezone.utc), 'price': price}
    df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    df = df.tail(100).reset_index(drop=True)

    if mode == "REAL":
        solde = get_real_balance()
    else:
        solde = portfolio

    if solde['USDC'] < MIN_USDC and solde['BTC'] < MIN_BTC:
        message = "🚨 Le bot s'est arrêté : solde insuffisant pour continuer à trader."
        send_telegram(message)
        print("❌ Solde insuffisant pour continuer. Le bot s'arrête.")
        analyse_finale(price)
        break

    if len(df) >= 26:
        df['sma20'] = ta.trend.sma_indicator(df['price'], window=20)
        df['rsi'] = ta.momentum.rsi(df['price'], window=14)
        df['macd'] = ta.trend.macd(df['price'])
        df['macd_signal'] = ta.trend.macd_signal(df['price'])
        bb = ta.volatility.BollingerBands(close=df['price'], window=20, window_dev=2)
        df['bb_upper'] = bb.bollinger_hband()
        df['bb_lower'] = bb.bollinger_lband()

        last_rsi = df.iloc[-1]['rsi']
        last_macd = df.iloc[-1]['macd']
        last_signal = df.iloc[-1]['macd_signal']
        last_upper = df.iloc[-1]['bb_upper']
        last_lower = df.iloc[-1]['bb_lower']

        if portfolio['USDC'] > 0 and last_rsi < 30 and price < last_lower and last_macd > last_signal:
            simulate_buy(price)
        elif portfolio['BTC'] > 0 and last_rsi > 70 and price > last_upper and last_macd < last_signal:
            simulate_sell(price)

    print(f"Prix actuel : {price:.2f}")
    print(f"👜 Solde : {solde}")

    elapsed = time.time() - start_time
    if trade_count >= max_trades:
        print("🛑 Limite de trades atteinte.")
        analyse_finale(price)
        break
    if elapsed > max_runtime:
        print("⏰ Durée maximale atteinte.")
        analyse_finale(price)
        break

    time.sleep(10)
