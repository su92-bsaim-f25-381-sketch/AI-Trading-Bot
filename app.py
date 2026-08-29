from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
import numpy as np
import time

app = Flask(__name__)
CORS(app)

wallet_balance = 10000.00
active_trades = []
closed_trades = []

def fetch_market_price_and_candles(symbol):
    clean_sym = symbol.replace('BINANCE:', '').replace('OANDA:', '').replace('FX:', '').replace('/', '').upper()
    
    # Crypto via Binance API
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

    # Metals / Gold (XAUUSD) & Forex Backup Stream via Free Price Engine
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
        # Fallback Default Base Values
        base_price = 2400.00 if "XAU" in clean_sym else (1.0850 if "EUR" in clean_sym else 65000.0)
        dummy_closes = [base_price + (np.random.randn() * 0.5) for _ in range(100)]
        return {"price": dummy_closes[-1], "highs": [c + 1.0 for c in dummy_closes], "lows": [c - 1.0 for c in dummy_closes], "closes": dummy_closes}

def calculate_quant_metrics(data):
    closes = np.array(data["closes"])
    highs = np.array(data["highs"])
    lows = np.array(data["lows"])
    current_price = closes[-1]
    
    # ATR Calculation
    tr1 = highs[1:] - lows[1:]
    tr2 = np.abs(highs[1:] - closes[:-1])
    tr3 = np.abs(lows[1:] - closes[:-1])
    tr = np.maximum(tr1, np.maximum(tr2, tr3))
    atr = np.mean(tr[-14:]) if len(tr) >= 14 else np.mean(tr)
    atr = max(atr, 0.5)
    
    # RSI & Moving Averages
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.mean(gains[-14:]) if len(gains) >= 14 else 1
    avg_loss = np.mean(losses[-14:]) if len(losses) >= 14 else 1
    rs = avg_gain / (avg_loss + 1e-9)
    rsi = 100.0 - (100.0 / (1.0 + rs))

    ema20 = np.mean(closes[-20:])
    ema50 = np.mean(closes[-50:])
    
    support = np.min(lows[-20:])
    resistance = np.max(highs[-20:])
    
    if (current_price > ema20) and (rsi < 65):
        signal = "HIGH-PROBABILITY BUY SETUP"
        action = "BUY"
    elif (current_price < ema20) and (rsi > 35):
        signal = "HIGH-PROBABILITY SELL SETUP"
        action = "SELL"
    else:
        signal = "MARKET CONSOLIDATING (HOLD)"
        action = "HOLD"
        
    return {
        "price": round(current_price, 2),
        "atr": round(atr, 2),
        "rsi": round(rsi, 2),
        "ema20": round(ema20, 2),
        "ema50": round(ema50, 2),
        "support": round(support, 2),
        "resistance": round(resistance, 2),
        "signal": signal,
        "suggested_action": action
    }

@app.route('/api/market', methods=['GET'])
def get_market_data():
    symbol = request.args.get('symbol', 'XAUUSD').upper()
    data = fetch_market_price_and_candles(symbol)
    metrics = calculate_quant_metrics(data)
    
    risk_amount = wallet_balance * 0.01
    recommended_lot = round(risk_amount / (metrics["atr"] * 10), 2) if metrics["atr"] > 0 else 0.10
    
    metrics["auto_lot"] = max(0.01, recommended_lot)
    metrics["wallet_balance"] = round(wallet_balance, 2)
    
    return jsonify(metrics)

@app.route('/api/trade/execute', methods=['POST'])
def execute_trade():
    global active_trades
    req = request.get_json() or {}
    
    symbol = req.get('symbol', 'XAU/USD')
    trade_type = req.get('type', 'BUY').upper()
    lots = float(req.get('lots', 0.10))
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

@app.route('/api/trade/close', methods=['POST'])
def close_trade():
    global wallet_balance, active_trades, closed_trades
    req = request.get_json() or {}
    trade_id = req.get('id')
    exit_price = float(req.get('exit_price', 0.00))

    trade_index = next((i for i, t in enumerate(active_trades) if t["id"] == trade_id), None)
    if trade_index is None:
        return jsonify({"status": "ERROR", "message": "Trade not found"}), 404

    trade = active_trades.pop(trade_index)
    pnl = (exit_price - trade["entry_price"]) * trade["lots"] * 10 if trade["type"] == "BUY" else (trade["entry_price"] - exit_price) * trade["lots"] * 10

    trade["exit_price"] = round(exit_price, 2)
    trade["pnl"] = round(pnl, 2)
    trade["close_time"] = time.strftime("%H:%M:%S")

    wallet_balance += pnl
    closed_trades.insert(0, trade)

    return jsonify({"status": "SUCCESS", "closed_trade": trade, "updated_wallet_balance": round(wallet_balance, 2)})

@app.route('/api/trades/active', methods=['GET'])
def get_active_trades():
    return jsonify({"active_trades": active_trades, "wallet_balance": round(wallet_balance, 2)})

@app.route('/api/trades/history', methods=['GET'])
def get_trade_history():
    return jsonify({"closed_trades": closed_trades, "wallet_balance": round(wallet_balance, 2)})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
