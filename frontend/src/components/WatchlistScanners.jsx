import React from 'react';

const evaluateTrend = (ltp, vwap, ema20, ema50, ema200, rsi) => {
  if (!ltp || !vwap || !ema20 || !ema50 || !ema200 || !rsi) {
    return { state: "WAITING", class: "trend-neut" };
  }
  
  const isAboveVwap = ltp > vwap;
  const isBullishEma = ltp > ema20 && ema20 > ema50 && ema50 > ema200;
  const isBearishEma = ltp < ema20 && ema20 < ema50 && ema50 < ema200;
  
  if (isAboveVwap && isBullishEma && rsi > 50) {
    return { state: rsi > 70 ? "OVERBOUGHT" : "BULLISH", class: "trend-bull" };
  } else if (!isAboveVwap && isBearishEma && rsi < 50) {
    return { state: rsi < 30 ? "OVERSOLD" : "BEARISH", class: "trend-bear" };
  }
  return { state: "CONGESTION", class: "trend-neut" };
};

export default function WatchlistScanners({ watchlistData, onSelectSymbol, onRemove }) {
  const buyItems = watchlistData.filter(i => i.direction === 'BUY');
  const sellItems = watchlistData.filter(i => i.direction === 'SELL');

  const renderTableRows = (items, colorClass) => {
    if (items.length === 0) {
      return (
        <tr>
          <td colSpan="5" style={{ textAlign: 'center', color: 'var(--color-text-muted)' }}>
            No instruments configured.
          </td>
        </tr>
      );
    }

    return items.map((item) => {
      const trend5m = evaluateTrend(
        item.ltp, 
        item.m5_vwap, 
        item.m5_ema20, 
        item.m5_ema50, 
        item.m5_ema200, 
        item.m5_rsi
      );
      const trend15m = evaluateTrend(
        item.ltp, 
        item.m15_vwap, 
        item.m15_ema20, 
        item.m15_ema50, 
        item.m15_ema200, 
        item.m15_rsi
      );

      const changeVal = item.change ?? 0;

      return (
        <tr key={item.symbol}>
          <td 
            style={{ fontWeight: 700, color: `var(${colorClass})`, cursor: 'pointer' }} 
            onClick={() => onSelectSymbol(item.symbol)} 
            title="Click to view chart"
          >
            {item.symbol}
          </td>
          <td>
            <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 600 }}>
              ₹{item.ltp ? item.ltp.toFixed(2) : '...'}
            </div>
            <div className={changeVal >= 0 ? 'text-up' : 'text-down'} style={{ fontSize: '0.7rem', fontFamily: 'var(--font-mono)' }}>
              {changeVal >= 0 ? '+' : ''}{changeVal.toFixed(2)}%
            </div>
          </td>
          <td style={{ textAlign: 'center' }}>
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '4px' }}>
              <div style={{ display: 'flex', gap: '4px', fontSize: '0.65rem' }}>
                <span className="indicator-bubble">VW: {item.m5_vwap ? item.m5_vwap.toFixed(1) : '...'}</span>
                <span className="indicator-bubble">RSI: {item.m5_rsi ? item.m5_rsi.toFixed(0) : '...'}</span>
              </div>
              <span className={`trend-badge ${trend5m.class}`}>
                {trend5m.state}
              </span>
            </div>
          </td>
          <td style={{ textAlign: 'center' }}>
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '4px' }}>
              <div style={{ display: 'flex', gap: '4px', fontSize: '0.65rem' }}>
                <span className="indicator-bubble">VW: {item.m15_vwap ? item.m15_vwap.toFixed(1) : '...'}</span>
                <span className="indicator-bubble">RSI: {item.m15_rsi ? item.m15_rsi.toFixed(0) : '...'}</span>
              </div>
              <span className={`trend-badge ${trend15m.class}`}>
                {trend15m.state}
              </span>
            </div>
          </td>
          <td>
            <button onClick={() => onRemove(item.symbol)} className="btn" style={{ padding: '2px 6px', fontSize: '0.65rem' }}>
              REMOVE
            </button>
          </td>
        </tr>
      );
    });
  };

  return (
    <div className="glass-panel">
      <div className="panel-header">
        <span>Watchlist Scanners (Confluence Evaluation)</span>
      </div>
      
      <div className="watchlist-grid">
        {/* Buy Watchlist Column */}
        <div className="watchlist-column">
          <h4 style={{ fontSize: '0.75rem', textTransform: 'uppercase', color: 'var(--color-emerald)', letterSpacing: '0.5px', marginBottom: '8px' }}>
            🟢 LONG SCANNERS
          </h4>
          <table className="custom-table">
            <thead>
              <tr>
                <th>Symbol</th>
                <th>LTP</th>
                <th style={{ textAlign: 'center' }}>5m indicators</th>
                <th style={{ textAlign: 'center' }}>15m indicators</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {renderTableRows(buyItems, '--color-emerald')}
            </tbody>
          </table>
        </div>

        {/* Sell Watchlist Column */}
        <div className="watchlist-column">
          <h4 style={{ fontSize: '0.75rem', textTransform: 'uppercase', color: 'var(--color-crimson)', letterSpacing: '0.5px', marginBottom: '8px' }}>
            🔴 SHORT SCANNERS
          </h4>
          <table className="custom-table">
            <thead>
              <tr>
                <th>Symbol</th>
                <th>LTP</th>
                <th style={{ textAlign: 'center' }}>5m indicators</th>
                <th style={{ textAlign: 'center' }}>15m indicators</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {renderTableRows(sellItems, '--color-crimson')}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
