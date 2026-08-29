from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
import numpy as np

app = Flask(__name__)
CORS(app)  # Enables Cross-Origin Resource Sharing for GitHub Pages

# In-memory storage for positions and history
wallet_balance = 10000.00
active_trades = []
closed_trades = []

def fetch_binance_data(symbol, interval="1m", limit=50):
    """Fetch real-time candlestick data from Binance API"""
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
        res = requests.get(url, timeout=5)
        data = res.json()
        
        closes = [float(candle[4]) for candle in data]
        highs = [float(candle[2]) for candle in data]
        lows = [float(candle[3]) for candle in data]
        volumes = [float(candle[5]) for candle in data]
        
        return {
            "current_price": closes[-1],
            "highs": highs,
            "lows": lows,
            "closes": closes,
            "volumes": volumes
        }
    except Exception as e:
        # Fallback simulation if network issue occurs
        return None

def calculate_quant_metrics(data):
    """Calculates ATR, Support/Resistance, and Buyer/Seller Pressure using Python"""
    closes = np.array(data["closes"])
    highs = np.array(data["highs"])
    lows = np.array(data["lows"])
    
    # 1. ATR Calculation (14-period)
    tr1 = highs[1:] - lows[1:]
    tr2 = np.abs(highs[1:] - closes[:-1])
    tr3 = np.abs(lows[1:] - closes[:-1])
    tr = np.maximum(tr1, np.maximum(tr2, tr3))
    atr = np.mean(tr[-14:])
    
    # 2. Support / Resistance
    resistance = np.max(highs[-20:])
    support = np.min(lows[-20:])
    
    # 3. Order Flow / Pressure Matrix
    price_change = closes[-1] - closes[-2]
    buy_pressure = 50 + int((price_change / atr) * 20) if atr > 0 else 50
    buy_pressure = max(15, min(85, buy_pressure))
    sell_pressure = 100 - buy_pressure
    
    # 4. Quant Signal Decision
    if buy_pressure > 58:
        signal = "MONOKAVA BUY SETUP CONFIRMED"
    elif buy_pressure < 42:
        signal = "MONOKAVA SELL SETUP CONFIRMED"
    else:
        signal = "WAITING FOR SETUP"
        
    return {
        "price": round(closes[-1], 2),
        "atr": round(atr, 2),
        "support": round(support, 2),
        "resistance": round(resistance, 2),
        "buy_pressure": buy_pressure,
        "sell_pressure": sell_pressure,
        "signal": signal,
        "tp1": round(closes[-1] + (1.5 * atr), 2),
        "tp2": round(closes[-1] + (3.0 * atr), 2)
    }

@app.route('/api/market', methods=['GET'])
def get_market_data():
    symbol = request.args.get('symbol', 'BTCUSDT')
    
    # Handle Gold/Silver fallbacks or Binance symbols
    binance_symbol = symbol if symbol in ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT'] else 'BTCUSDT'
    
    data = fetch_binance_data(binance_symbol)
    if not data:
        return jsonify({"error": "Failed to fetch data"}), 500
        
    metrics = calculate_quant_metrics(data)
    
    # Risk Engine Calculation
    risk_amount = wallet_balance * 0.01
    recommended_lot = round(risk_amount / (metrics["atr"] * 10), 2) if metrics["atr"] > 0 else 0.10
    metrics["auto_lot"] = max(0.01, recommended_lot)
    metrics["balance"] = round(wallet_balance, 2)
    
    return jsonify(metrics)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
