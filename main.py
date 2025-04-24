import ccxt
import os
import time
import csv
import pandas as pd
import ta
import requests
import numpy as np
from dotenv import load_dotenv
from datetime import datetime, timezone

# Chargement des clés API
load_dotenv()
api_key = os.getenv("BINANCE_API_KEY")
secret_key = os.getenv("BINANCE_SECRET_KEY")

# Connexion Binance
binance = ccxt.binance({
    'apiKey': api_key,
    'secret': secret_key,
    'enableRateLimit': True,
    'timeout': 30000
})

# Telegram
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Paramètre de gain minimum (en pourcentage)
MIN_PROFIT_PCT = 0.2  # Par exemple, 0.2% minimum requis pour vendre

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

def log_trade(action, amount, price, total):
    file_exists = os.path.isfile('trades.csv')
    with open('trades.csv', mode='a', newline='') as file:
        writer = csv.writer(file)
        if not file_exists:
            writer.writerow(['timestamp', 'action', 'amount', 'price', 'total'])
        writer.writerow([
            datetime.now(timezone.utc).isoformat(),
            action,
            f"{amount:.8f}",
            f"{price:.2f}",
            f"{total:.2f}"
        ])

def real_buy(price):
    balance = get_real_balance()
    usdc = balance['USDC']
    if usdc < 10:
        print("❌ Solde USDC insuffisant pour acheter.")
        return None
    quantity = round((usdc / price) * 0.995, 6)  # Marge de sécurité de 0.5%
    order = binance.create_market_buy_order('BTC/USDC', quantity)
    print("🟢 Ordre d'achat envoyé :", order)
    log_trade("BUY", quantity, price, order['cost'])
    return price

def real_sell(price, last_buy_price):
    balance = get_real_balance()
    btc = balance['BTC']
    if btc < 0.00001:
        print("❌ Solde BTC insuffisant pour vendre.")
        return
    quantity = round(btc * 0.995, 6)  # Marge de sécurité de 0.5%
    order = binance.create_market_sell_order('BTC/USDC', quantity)
    print("🔴 Ordre de vente envoyé :", order)
    revenue = order['cost'] - order['fee']['cost']
    profit = revenue - (last_buy_price * quantity)
    percent = (profit / (last_buy_price * quantity)) * 100 if last_buy_price else 0

    if percent < MIN_PROFIT_PCT:
        print(f"⏸️ Vente ignorée : gain trop faible ({percent:.2f}%)")
        return

    print(f"🟢 Gain/Pertes réel: {profit:.2f} USDC ({percent:.2f}%)")
    log_trade("SELL", quantity, price, revenue)

df = pd.DataFrame(columns=['timestamp', 'price', 'sma20', 'rsi', 'macd', 'macd_signal', 'bb_upper', 'bb_lower'])
last_buy_price = None
start_time = time.time()

while True:
    price = get_price()
    if price is None:
        time.sleep(5)
        continue

    new_row = {
        'timestamp': datetime.now(timezone.utc),
        'price': price,
        'sma20': np.nan,
        'rsi': np.nan,
        'macd': np.nan,
        'macd_signal': np.nan,
        'bb_upper': np.nan,
        'bb_lower': np.nan
    }
    df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    df = df.tail(100).reset_index(drop=True)

    balance = get_real_balance()
    if balance['USDC'] < 10 and balance['BTC'] < 0.00001:
        print("❌ Solde insuffisant pour continuer. Le bot s'arrête.")
        send_telegram("🚨 Bot arrêté : solde insuffisant.")
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

        print(f"[INFO] RSI={last_rsi:.2f}, MACD={last_macd:.2f}, Signal={last_signal:.2f}, Bollinger=[{last_lower:.2f}, {last_upper:.2f}]")

        # 🎯 Stratégie conservatrice
        if balance['USDC'] > 10 and last_rsi < 30 and price < last_lower and last_macd > last_signal:
            last_buy_price = real_buy(price)

        elif balance['BTC'] > 0.00001 and last_rsi > 70 and price > last_upper and last_macd < last_signal:
            real_sell(price, last_buy_price)

        # 🔁 Stratégie active
        elif balance['USDC'] > 10 and last_rsi < 45 and last_macd > last_signal:
            last_buy_price = real_buy(price)

        elif balance['BTC'] > 0.00001 and last_rsi > 60 and last_macd < last_signal:
            real_sell(price, last_buy_price)

    print(f"Prix actuel : {price:.2f}")
    print(f"👜 Solde réel : {balance}")

    if time.time() - start_time > 8 * 60 * 60:
        print("⏰ Durée maximale atteinte. Le bot s'arrête.")
        send_telegram("⏰ Bot arrêté : durée maximale atteinte.")
        break

    time.sleep(5)
