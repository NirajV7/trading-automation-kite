import React, { useState, useEffect, useRef } from 'react';

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

export default function WatchlistScanners({ 
  watchlistData, 
  onSelectSymbol, 
  onRemove,
  onAddToWatchlist,
  apiUrl
}) {
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState([]);
  const searchRef = useRef(null);

  // Debounced search ticker
  useEffect(() => {
    if (!searchQuery) {
      setSearchResults([]);
      return;
    }
    const delayDebounceFn = setTimeout(async () => {
      try {
        const res = await fetch(`${apiUrl}/api/search?q=${searchQuery}`);
        const data = await res.json();
        setSearchResults(data || []);
      } catch (e) {
        console.error("Search failed:", e);
      }
    }, 250);

    return () => clearTimeout(delayDebounceFn);
  }, [searchQuery, apiUrl]);

  // Click outside to dismiss search results
  useEffect(() => {
    function handleClickOutside(event) {
      if (searchRef.current && !searchRef.current.contains(event.target)) {
        setSearchResults([]);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const handleAdd = (symbol, direction) => {
    if (onAddToWatchlist) {
      onAddToWatchlist(symbol, direction);
    }
    setSearchQuery('');
    setSearchResults([]);
  };

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
                <span className="indicator-bubble">VW: {item.m5_vwap ? item.m5_vwap.toFixed(2) : '...'}</span>
                <span className="indicator-bubble">RSI: {item.m5_rsi ? item.m5_rsi.toFixed(2) : '...'}</span>
              </div>
              <span className={`trend-badge ${trend5m.class}`}>
                {trend5m.state}
              </span>
            </div>
          </td>
          <td style={{ textAlign: 'center' }}>
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '4px' }}>
              <div style={{ display: 'flex', gap: '4px', fontSize: '0.65rem' }}>
                <span className="indicator-bubble">VW: {item.m15_vwap ? item.m15_vwap.toFixed(2) : '...'}</span>
                <span className="indicator-bubble">RSI: {item.m15_rsi ? item.m15_rsi.toFixed(2) : '...'}</span>
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
      <div className="panel-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span>Watchlist Scanners (Confluence Evaluation)</span>
        
        {/* Compact stock search dropdown in panel header */}
        <div className="search-container" ref={searchRef} style={{ width: '260px', position: 'relative' }}>
          <input 
            type="text" 
            className="input-dark" 
            placeholder="🔍 Search & Add Instrument..." 
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            style={{ padding: '6px 12px', fontSize: '0.75rem' }}
          />
          {searchResults.length > 0 && (
            <div className="search-results">
              {searchResults.map((item) => (
                <div className="search-item" key={item.ticker}>
                  <span style={{ fontWeight: 600 }}>{item.ticker}</span>
                  <div style={{ display: 'flex', gap: '6px' }}>
                    <button 
                      onClick={() => handleAdd(item.ticker, 'buy')} 
                      className="btn btn-cyan" 
                      style={{ padding: '2px 6px', fontSize: '0.65rem' }}
                    >
                      + LONG
                    </button>
                    <button 
                      onClick={() => handleAdd(item.ticker, 'sell')} 
                      className="btn btn-crimson" 
                      style={{ padding: '2px 6px', fontSize: '0.65rem' }}
                    >
                      + SHORT
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
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
