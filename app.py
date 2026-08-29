from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
import numpy as np
import time

app = Flask(__name__)
CORS(app)  # Cross-Origin Resource Sharing enabled

# In-memory Trading Engine State
wallet_balance = 10000.00
active_trades = []
closed_trades = []

def fetch_binance_data(symbol, interval="1m", limit=100):
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
        return None

def calculate_ema(prices, period):
    """Calculates Exponential Moving Average (EMA)"""
    prices = np.array(prices)
    alpha = 2 / (period + 1)
    ema = [prices[0]]
    for price in prices[1:]:
        ema.append((price * alpha) + (ema[-1] * (1 - alpha)))
    return np.array(ema)

def calculate_rsi(prices, period=14):
    """Calculates Relative Strength Index (RSI)"""
    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])
    
    if avg_loss == 0:
        return 100.0
        
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        
    if avg_loss == 0:
        return 100.0
        
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))

def calculate_quant_metrics(data):
    """Calculates ATR, RSI, EMA 20/50, S/R, and Advanced Signals"""
    closes = np.array(data["closes"])
    highs = np.array(data["highs"])
    lows = np.array(data["lows"])
    current_price = closes[-1]
    
    # 1. ATR Calculation (14-period)
    tr1 = highs[1:] - lows[1:]
    tr2 = np.abs(highs[1:] - closes[:-1])
    tr3 = np.abs(lows[1:] - closes[:-1])
    tr = np.maximum(tr1, np.maximum(tr2, tr3))
    atr = np.mean(tr[-14:]) if len(tr) >= 14 else np.mean(tr)
    
    # 2. Indicators (EMA 20, EMA 50, RSI 14)
    ema20 = calculate_ema(closes, 20)[-1]
    ema50 = calculate_ema(closes, 50)[-1]
    rsi = calculate_rsi(closes, 14)
    
    # 3. Support & Resistance (Last 20 bars)
    resistance = np.max(highs[-20:])
    support = np.min(lows[-20:])
    
    # 4. Multi-Indicator Signal Decision
    # BUY: Bullish Trend (EMA20 > EMA50) + RSI Momentum (52 to 70)
    # SELL: Bearish Trend (EMA20 < EMA50) + RSI Momentum (30 to 48)
    if ema20 > ema50 and rsi > 52 and rsi < 70:
        signal = "STRONG BUY SETUP"
        action = "BUY"
    elif ema20 < ema50 and rsi < 48 and rsi > 30:
        signal = "STRONG SELL SETUP"
        action = "SELL"
    else:
        signal = "NEUTRAL / HOLD"
        action = "HOLD"
        
    # Pressure representation derived from RSI
    buy_pressure = int(rsi)
    sell_pressure = 100 - buy_pressure
        
    return {
        "price": round(current_price, 2),
        "atr": round(atr, 2),
        "rsi": round(rsi, 2),
        "ema20": round(ema20, 2),
        "ema50": round(ema50, 2),
        "support": round(support, 2),
        "resistance": round(resistance, 2),
        "buy_pressure": buy_pressure,
        "sell_pressure": sell_pressure,
        "signal": signal,
        "suggested_action": action,
        "tp1": round(current_price + (1.5 * atr), 2),
        "sl1": round(current_price - (1.0 * atr), 2)
    }

# --- API ENDPOINTS ---

@app.route('/api/market', methods=['GET'])
def get_market_data():
    """Returns Live Analysis & Auto-Lot Calculations"""
    symbol = request.args.get('symbol', 'BTCUSDT').upper().replace('/', '')
    if 'BINANCE:' in symbol:
        symbol = symbol.replace('BINANCE:', '')
        
    binance_symbol = symbol if symbol in ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT'] else 'BTCUSDT'
    
    data = fetch_binance_data(binance_symbol)
    if not data:
        return jsonify({"error": "Failed to fetch market data"}), 500
        
    metrics = calculate_quant_metrics(data)
    
    # Risk Engine: 1% Wallet Risk Allocation
    risk_amount = wallet_balance * 0.01
    recommended_lot = round(risk_amount / (metrics["atr"] * 10), 2) if metrics["atr"] > 0 else 0.10
    
    metrics["auto_lot"] = max(0.01, recommended_lot)
    metrics["wallet_balance"] = round(wallet_balance, 2)
    
    return jsonify(metrics)

@app.route('/api/trade/execute', methods=['POST'])
def execute_trade():
    """Executes a BUY or SELL trade (Manual or Auto Bot)"""
    global wallet_balance, active_trades
    req = request.get_json() or {}
    
    symbol = req.get('symbol', 'BTC/USDT')
    trade_type = req.get('type', 'BUY').upper()
    lots = float(req.get('lots', 0.10))
    price = float(req.get('price', 0.00))
    atr = float(req.get('atr', 10.0))

    if price <= 0:
        # Fallback price fetch if price was not sent
        clean_sym = symbol.replace('/', '').replace('BINANCE:', '')
        data = fetch_binance_data(clean_sym)
        price = data["current_price"] if data else 50000.0

    trade_id = int(time.time() * 1000)
    
    # Automatic SL/TP calculation
    sl = price - (1.0 * atr) if trade_type == 'BUY' else price + (1.0 * atr)
    tp = price + (1.5 * atr) if trade_type == 'BUY' else price - (1.5 * atr)

    new_trade = {
        "id": trade_id,
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

@app.route('/api/trade/close', methods=['POST'])
def close_trade():
    """Closes an active trade and updates wallet balance"""
    global wallet_balance, active_trades, closed_trades
    req = request.get_json() or {}
    trade_id = req.get('id')
    exit_price = float(req.get('exit_price', 0.00))

    trade_index = next((i for i, t in enumerate(active_trades) if t["id"] == trade_id), None)
    
    if trade_index is None:
        return jsonify({"status": "ERROR", "message": "Trade not found"}), 404

    trade = active_trades.pop(trade_index)
    
    if exit_price <= 0:
        exit_price = trade["entry_price"]

    # Calculate P&L based on trade direction
    if trade["type"] == "BUY":
        pnl = (exit_price - trade["entry_price"]) * trade["lots"] * 100
    else:
        pnl = (trade["entry_price"] - exit_price) * trade["lots"] * 100

    trade["exit_price"] = round(exit_price, 2)
    trade["pnl"] = round(pnl, 2)
    trade["close_time"] = time.strftime("%H:%M:%S")

    wallet_balance += pnl
    closed_trades.insert(0, trade)

    return jsonify({
        "status": "SUCCESS",
        "closed_trade": trade,
        "updated_wallet_balance": round(wallet_balance, 2)
    })

@app.route('/api/trades/active', methods=['GET'])
def get_active_trades():
    return jsonify({"active_trades": active_trades, "wallet_balance": round(wallet_balance, 2)})

@app.route('/api/trades/history', methods=['GET'])
def get_trade_history():
    return jsonify({"closed_trades": closed_trades, "wallet_balance": round(wallet_balance, 2)})

if __name__ == '__main__':
    print("🚀 TradePulse AI Backend running on http://localhost:5000")
    app.run(host='0.0.0.0', port=5000, debug=True)
