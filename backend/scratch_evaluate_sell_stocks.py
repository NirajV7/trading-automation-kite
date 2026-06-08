import csv
import json
import os
import sys
import time
import pandas as pd
import numpy as np
import requests

# Set output formatting
pd.set_option('display.max_columns', None)
pd.set_option('display.width', 1000)

csv_path = "/Users/nj/.gemini/antigravity/scratch/trading-automation-kite/Stocks/SELL_STOCKS.csv"

def calculate_rsi(prices, period=14):
    if len(prices) <= period:
        return np.zeros_like(prices)
    deltas = np.diff(prices)
    seed = deltas[:period+1]
    up = seed[seed >= 0].sum() / period
    down = -seed[seed < 0].sum() / period
    rs = up / down if down != 0 else 0
    rsi = np.zeros_like(prices)
    rsi[:period] = 100. - 100. / (1. + rs)

    for i in range(period, len(prices)):
        delta = deltas[i - 1]
        if delta > 0:
            upval = delta
            downval = 0.
        else:
            upval = 0.
            downval = -delta

        up = (up * (period - 1) + upval) / period
        down = (down * (period - 1) + downval) / period
        rs = up / down if down != 0 else 0
        rsi[i] = 100. - 100. / (1. + rs)
    return rsi

# Symbol mappings for common names that might differ on NSE
SYMBOL_MAPPINGS = {
    'EIHOTEL': 'EIHOTEL',  # Eih Ltd is EIHOTEL on NSE
    'LOTUSDEV': 'LOTUSDEV', # Sri Lotus Developers
    'BLACKBUCK': 'BLACKBUCK', # BlackBuck Ltd
    'BECTORFOOD': 'BECTORFOOD', # Mrs Bectors
    'TECHNOE': 'TECHNOE', # Techno Electric
}

def get_yfinance_data(symbol):
    mapped_sym = SYMBOL_MAPPINGS.get(symbol, symbol)
    tickers_to_try = [f"{mapped_sym}.NS", f"{symbol}.NS", f"{mapped_sym}.BO", f"{symbol}.BO"]
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
    }

    for ticker in tickers_to_try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=60d&interval=1d"
        try:
            response = requests.get(url, headers=headers, timeout=5)
            if response.status_code == 200:
                data = response.json()
                result = data.get('chart', {}).get('result', [])
                if not result:
                    continue
                
                timestamps = result[0].get('timestamp', [])
                indicators = result[0].get('indicators', {}).get('quote', [{}])[0]
                
                opens = indicators.get('open', [])
                highs = indicators.get('high', [])
                lows = indicators.get('low', [])
                closes = indicators.get('close', [])
                volumes = indicators.get('volume', [])
                
                df = pd.DataFrame({
                    'timestamp': timestamps,
                    'open': opens,
                    'high': highs,
                    'low': lows,
                    'close': closes,
                    'volume': volumes
                })
                
                df = df.dropna().reset_index(drop=True)
                if len(df) >= 20:
                    return df, ticker
        except Exception as e:
            pass
            
    return None, None

def analyze_stocks():
    if not os.path.exists(csv_path):
        print(f"CSV file not found at {csv_path}")
        return
    
    symbols = []
    with open(csv_path, 'r') as f:
        reader = csv.reader(f)
        header = next(reader)
        for row in reader:
            if len(row) > 2:
                symbols.append((row[1], row[2])) # (Stock Name, Symbol)

    print(f"Loaded {len(symbols)} symbols. Fetching daily historical data from Yahoo Finance...")
    
    results = []
    failed_symbols = []
    for name, sym in symbols:
        sym = sym.strip()
        df, actual_ticker = get_yfinance_data(sym)
        if df is None:
            failed_symbols.append((name, sym))
            continue
        
        closes = df['close'].values
        volumes = df['volume'].values
        opens = df['open'].values
        highs = df['high'].values
        lows = df['low'].values
        
        # Calculations
        last_close = closes[-1]
        last_open = opens[-1]
        last_high = highs[-1]
        last_low = lows[-1]
        last_volume = volumes[-1]
        
        # Percentage Change
        pct_change = ((last_close - closes[-2]) / closes[-2]) * 100 if len(closes) > 1 else 0.0
        
        # EMAs
        df['ema_20'] = df['close'].ewm(span=20, adjust=False).mean()
        df['ema_50'] = df['close'].ewm(span=50, adjust=False).mean()
        ema_20 = df['ema_20'].iloc[-1]
        ema_50 = df['ema_50'].iloc[-1]
        
        # RSI 14
        rsi_vals = calculate_rsi(closes, 14)
        rsi = rsi_vals[-1]
        
        # Volume SMA 20
        vol_sma_20 = df['volume'].rolling(window=20).mean().iloc[-1]
        vol_ratio = last_volume / vol_sma_20 if vol_sma_20 > 0 else 0.0
        
        # Close position in day's range (0 = close at low, 1 = close at high)
        range_pos = (last_close - last_low) / (last_high - last_low) if last_high != last_low else 0.5
        
        # Distance to EMA 20
        dist_ema20 = ((last_close - ema_20) / ema_20) * 100
        
        # Daily Volume in Crores (Approximate turnover)
        turnover_cr = (last_volume * last_close) / 10000000
        
        results.append({
            'name': name,
            'symbol': sym,
            'ticker': actual_ticker,
            'close': round(last_close, 2),
            'pct_change': round(pct_change, 2),
            'volume_ratio': round(vol_ratio, 2),
            'rsi_14': round(rsi, 2),
            'range_pos': round(range_pos, 2),
            'dist_ema20': round(dist_ema20, 2),
            'turnover_cr': round(turnover_cr, 2)
        })
        time.sleep(0.1)
    
    results_df = pd.DataFrame(results)
    if results_df.empty:
        print("No stock data could be retrieved.")
        return
        
    # Custom score for shorting:
    # 40% weight on volume_ratio (intensity of distribution)
    # 40% weight on (1 - range_pos) (lower range pos is better, meaning closed near the low)
    # 20% weight on negative pct_change (strong downward momentum)
    results_df['score'] = (
        results_df['volume_ratio'] * 0.4 + 
        (1.0 - results_df['range_pos']) * 4.0 + 
        (-results_df['pct_change'] / 5.0) * 2.0
    )
    
    # Sort by score descending
    ranked_df = results_df.sort_values(by='score', ascending=False)
    
    print("\n--- ALL ANALYZED SHORT STOCKS ---")
    print(ranked_df[['name', 'symbol', 'close', 'pct_change', 'volume_ratio', 'rsi_14', 'range_pos', 'dist_ema20', 'turnover_cr', 'score']].to_string(index=False))
    
    if failed_symbols:
        print("\n--- FAILED TO FETCH DATA FOR ---")
        for name, sym in failed_symbols:
            print(f"- {name} ({sym})")
            
    # Top 5 recommendations for shorting
    top_5 = ranked_df.head(5)
    print("\n--- TOP 5 SHORT RECOMMENDATIONS FOR TOMORROW ---")
    for i, row in enumerate(top_5.to_dict('records'), 1):
        print(f"{i}. {row['name']} ({row['symbol']})")
        print(f"   - Close: ₹{row['close']} ({row['pct_change']}%)")
        print(f"   - Volume Ratio: {row['volume_ratio']}x (Relative to 20-day SMA)")
        print(f"   - RSI (14): {row['rsi_14']}")
        print(f"   - Range Position: {row['range_pos']} (Closed at {int(row['range_pos']*100)}% of daily range)")
        print(f"   - Dist to EMA 20: {row['dist_ema20']}%")
        print(f"   - Daily Turnover: ₹{row['turnover_cr']:.2f} Cr")
        print()

if __name__ == "__main__":
    analyze_stocks()
