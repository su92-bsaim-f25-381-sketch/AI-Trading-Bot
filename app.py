from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
import numpy as np
import time

app = Flask(__name__)
CORS(app)

# Global State Variables
user_capital = 10000.00
active_trades = []
closed_trades = []

def fetch_market_price_and_candles(symbol):
    clean_sym = symbol.replace('BINANCE:', '').replace('OANDA:', '').replace('FX:', '').replace('/', '').upper()
    
    # 1. Crypto Live Data via Binance
    if 'BTC' in clean_sym or 'ETH' in clean_sym or 'SOL' in clean_sym or 'BNB' in clean_sym:
        try:
            url = f"https://api.binance.com/api/v3/klines?symbol={clean_sym}&interval=1m&limit=100"
            res = requests.get(url, timeout=5).json()
            closes = [float(c[4]) for c in res]
            highs = [float(c[2]) for c in res]
            lows = [float(c[3]) for c in res]
            return {"price": closes[-1], "highs": highs, "lows": lows, "closes": closes}
        except Exception:
            pass

    # 2. Forex / Gold Data via Yahoo Finance API
    try:
        yf_symbol = "GC=F" if "XAU" in clean_sym else f"{clean_sym}=X"
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yf_symbol}?interval=1m&range=1d"
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(url, headers=headers, timeout=5).json()
        result = res['chart']['result'][0]
        closes = [c for c in result['indicators']['quote'][0]['close'] if c is not None]
        highs = [h for h in result['indicators']['quote'][0]['high'] if h is not None]
        lows = [l for l in result['indicators']['quote'][0]['low'] if l is not None]
        return {"price": closes[-1], "highs": highs, "lows": lows, "closes": closes}
    except Exception:
        base_price = 2400.00 if "XAU" in clean_sym else (1.0850 if "EUR" in clean_sym else 65000.0)
        dummy_closes = [base_price + (np.random.randn() * 0.5) for _ in range(100)]
        return {"price": dummy_closes[-1], "highs": [c + 1.0 for c in dummy_closes], "lows": [c - 1.0 for c in dummy_closes], "closes": dummy_closes}

def calculate_ema(prices, period):
    prices = np.array(prices)
    alpha = 2 / (period + 1)
    ema = [prices[0]]
    for price in prices[1:]:
        ema.append((price * alpha) + (ema[-1] * (1 - alpha)))
    return np.array(ema)

def calculate_rsi(prices, period=14):
    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.mean(gains[-period:]) if len(gains) >= period else 1
    avg_loss = np.mean(losses[-period:]) if len(losses) >= period else 1
    rs = avg_gain / (avg_loss + 1e-9)
    return 100.0 - (100.0 / (1.0 + rs))

def calculate_macd(closes):
    ema12 = calculate_ema(closes, 12)
    ema26 = calculate_ema(closes, 26)
    macd_line = ema12 - ema26
    signal_line = calculate_ema(macd_line, 9)
    return macd_line, signal_line

def calculate_quant_metrics(data):
    closes = np.array(data["closes"])
    highs = np.array(data["highs"])
    lows = np.array(data["lows"])
    current_price = closes[-1]
    
    tr1 = highs[1:] - lows[1:]
    tr2 = np.abs(highs[1:] - closes[:-1])
    tr3 = np.abs(lows[1:] - closes[:-1])
    tr = np.maximum(tr1, np.maximum(tr2, tr3))
    atr = np.mean(tr[-14:]) if len(tr) >= 14 else np.mean(tr)
    atr = max(atr, 0.5)
    
    rsi = calculate_rsi(closes, 14)
    macd_line, signal_line = calculate_macd(closes)
    
    support = np.min(lows[-20:])
    resistance = np.max(highs[-20:])
    
    # Precise Crossover Filter Rules
    bullish_crossover = macd_line[-1] > signal_line[-1] and macd_line[-2] <= signal_line[-2]
    bearish_crossover = macd_line[-1] < signal_line[-1] and macd_line[-2] >= signal_line[-2]
    
    if bullish_crossover and rsi < 65:
        signal = "PRECISION BUY SETUP"
        action = "BUY"
    elif bearish_crossover and rsi > 35:
        signal = "PRECISION SELL SETUP"
        action = "SELL"
    else:
        signal = "WAITING FOR SETUP"
        action = "HOLD"
        
    return {
        "price": round(current_price, 2),
        "atr": round(atr, 2),
        "rsi": round(rsi, 2),
        "ema20": round(np.mean(closes[-20:]), 2),
        "ema50": round(np.mean(closes[-50:]), 2),
        "support": round(support, 2),
        "resistance": round(resistance, 2),
        "signal": signal,
        "suggested_action": action
    }

# API to Set Custom Capital
@app.route('/api/capital', methods=['POST'])
def set_capital():
    global user_capital
    req = request.get_json() or {}
    amount = float(req.get('capital', 10000.00))
    if amount > 0:
        user_capital = amount
        return jsonify({"status": "SUCCESS", "capital": user_capital, "message": "Capital updated successfully"})
    return jsonify({"status": "ERROR", "message": "Invalid capital amount"}), 400

# API to Fetch Market Analysis & Auto Risk Lot
@app.route('/api/market', methods=['GET'])
def get_market_data():
    symbol = request.args.get('symbol', 'BTCUSDT').upper()
    data = fetch_market_price_and_candles(symbol)
    metrics = calculate_quant_metrics(data)
    
    # 1% Risk Rule Auto-Lot Calculation
    risk_amount = user_capital * 0.01
    recommended_lot = round(risk_amount / (metrics["atr"] * 10), 2) if metrics["atr"] > 0 else 0.01
    
    metrics["auto_lot"] = max(0.01, recommended_lot)
    metrics["wallet_balance"] = round(user_capital, 2)
    
    return jsonify(metrics)

@app.route('/api/trade/execute', methods=['POST'])
def execute_trade():
    global active_trades
    req = request.get_json() or {}
    symbol = req.get('symbol', 'BTC/USDT')
    trade_type = req.get('type', 'BUY').upper()
    lots = float(req.get('lots', 0.01))
    price = float(req.get('price', 0.00))
    atr = float(req.get('atr', 2.0))

    if price <= 0:
        data = fetch_market_price_and_candles(symbol)
        price = data["price"]

    sl = price - (1.5 * atr) if trade_type == 'BUY' else price + (1.5 * atr)
    tp = price + (2.5 * atr) if trade_type == 'BUY' else price - (2.5 * atr)

    new_trade = {
        "id": int(time.time() * 1000),
        "symbol": symbol,
        "type": trade_type,
        "lots": lots,
        "entry_price": round(price, 2),
        "sl": round(sl, 2),
        "tp": round(tp, 2),
        "pnl": 0.00,
        "timestamp": time.strftime("%H:%M:%S")
    }

    active_trades.insert(0, new_trade)
    return jsonify({"status": "SUCCESS", "message": "Trade Executed", "trade": new_trade})

@app.route('/api/trades/active', methods=['GET'])
def get_active_trades():
    return jsonify({"active_trades": active_trades, "wallet_balance": round(user_capital, 2)})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
