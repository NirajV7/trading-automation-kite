import React, { useState, useEffect, useRef } from 'react';

const formatPrice = (value) => (
  value !== null && value !== undefined && Number.isFinite(Number(value))
    ? `₹${Number(value).toFixed(2)}`
    : '—'
);

const formatPercent = (value) => {
  const num = Number(value ?? 0);
  return `${num >= 0 ? '+' : ''}${num.toFixed(2)}%`;
};

const evaluateTrend = (ltp, vwap, ema20, ema50, ema200, rsi) => {
  if (!ltp || !vwap || !ema20 || !ema50 || !ema200 || !rsi) {
    return { state: "WAITING", class: "trend-neut", bias: "neutral" };
  }

  const isAboveVwap = ltp > vwap;
  const isBullishEma = ltp > ema20 && ema20 > ema50 && ema50 > ema200;
  const isBearishEma = ltp < ema20 && ema20 < ema50 && ema50 < ema200;

  if (isAboveVwap && isBullishEma && rsi > 50) {
    return { state: rsi > 70 ? "OVERBOUGHT" : "BULLISH", class: "trend-bull", bias: "bullish" };
  }
  if (!isAboveVwap && isBearishEma && rsi < 50) {
    return { state: rsi < 30 ? "OVERSOLD" : "BEARISH", class: "trend-bear", bias: "bearish" };
  }
  return { state: "CONGESTION", class: "trend-neut", bias: "neutral" };
};

const getConfluence = (direction, trend5m, trend15m) => {
  const wanted = direction === 'BUY' ? 'bullish' : 'bearish';
  const score = [trend5m.bias, trend15m.bias].filter((bias) => bias === wanted).length;

  if (score === 2) return { label: 'Aligned', className: 'ready', score };
  if (score === 1) return { label: 'Mixed', className: 'mixed', score };
  return { label: 'Waiting', className: 'waiting', score };
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
  const [activeScannerTab, setActiveScannerTab] = useState('long');
  const searchRef = useRef(null);

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

  const normalizedData = watchlistData || [];
  const buyItems = normalizedData.filter((i) => i.direction === 'BUY');
  const sellItems = normalizedData.filter((i) => i.direction === 'SELL');
  const activeItems = activeScannerTab === 'long' ? buyItems : sellItems;

  const renderScannerCard = (item, direction) => {
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
    const confluence = getConfluence(direction, trend5m, trend15m);
    const changeVal = Number(item.change ?? 0);
    const isLong = direction === 'BUY';

    return (
      <article className={`watch-card ${isLong ? 'long-card' : 'short-card'}`} key={item.symbol}>
        <div className="watch-card-main">
          <button
            className="watch-symbol-button"
            onClick={() => onSelectSymbol(item.symbol)}
            title="Open chart"
          >
            {item.symbol}
          </button>
          <span className={`watch-side-pill ${isLong ? 'long' : 'short'}`}>
            {isLong ? 'LONG SCAN' : 'SHORT SCAN'}
          </span>
          <span className={`watch-score-pill ${confluence.className}`}>
            {confluence.label} • {confluence.score}/2
          </span>
        </div>

        <div className="watch-price-block">
          <strong>{formatPrice(item.ltp)}</strong>
          <span className={changeVal >= 0 ? 'text-up' : 'text-down'}>{formatPercent(changeVal)}</span>
        </div>

        <div className="watch-timeframes">
          <div className="watch-tf-card">
            <div className="watch-tf-top">
              <span>5m</span>
              <span className={`trend-badge ${trend5m.class}`}>{trend5m.state}</span>
            </div>
            <div className="watch-indicator-grid">
              <span>VWAP <strong>{formatPrice(item.m5_vwap)}</strong></span>
              <span>RSI <strong>{item.m5_rsi ? Number(item.m5_rsi).toFixed(1) : '—'}</strong></span>
            </div>
          </div>

          <div className="watch-tf-card">
            <div className="watch-tf-top">
              <span>15m</span>
              <span className={`trend-badge ${trend15m.class}`}>{trend15m.state}</span>
            </div>
            <div className="watch-indicator-grid">
              <span>VWAP <strong>{formatPrice(item.m15_vwap)}</strong></span>
              <span>RSI <strong>{item.m15_rsi ? Number(item.m15_rsi).toFixed(1) : '—'}</strong></span>
            </div>
          </div>
        </div>

        <div className="watch-actions">
          <button className="btn btn-cyan" onClick={() => onSelectSymbol(item.symbol)}>
            Chart
          </button>
          <button className="btn btn-crimson" onClick={() => onRemove(item.symbol)}>
            Remove
          </button>
        </div>
      </article>
    );
  };

  const renderLane = (title, subtitle, items, direction) => {
    const isLong = direction === 'BUY';
    return (
      <section className={`watch-lane ${isLong ? 'long-lane' : 'short-lane'}`}>
        <div className="watch-lane-header">
          <div>
            <h3>{isLong ? '🟢' : '🔴'} {title}</h3>
            <p>{subtitle}</p>
          </div>
          <span>{items.length} symbol{items.length !== 1 ? 's' : ''}</span>
        </div>

        <div className="watch-card-list">
          {items.length > 0 ? (
            items.map((item) => renderScannerCard(item, direction))
          ) : (
            <div className="watch-empty-state">
              <strong>No instruments configured</strong>
              <span>Use search above to add {isLong ? 'long' : 'short'} scan candidates.</span>
            </div>
          )}
        </div>
      </section>
    );
  };

  return (
    <div className="glass-panel watchlist-panel">
      <div className="watchlist-header">
        <div>
          <h2>Watchlist Radar</h2>
          <p>Manual candidates with live 5m and 15m confluence checks.</p>
        </div>

        <div className="watchlist-toolbar">
          <div className="watchlist-stat">
            <span>Total</span>
            <strong>{normalizedData.length}</strong>
          </div>
          <div className="watchlist-stat long">
            <span>Long</span>
            <strong>{buyItems.length}</strong>
          </div>
          <div className="watchlist-stat short">
            <span>Short</span>
            <strong>{sellItems.length}</strong>
          </div>

          <div className="search-container watch-search" ref={searchRef}>
            <input
              type="text"
              className="input-dark"
              placeholder="Search symbol..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
            {searchResults.length > 0 && (
              <div className="search-results">
                {searchResults.map((item) => (
                  <div className="search-item" key={item.ticker}>
                    <span style={{ fontWeight: 700 }}>{item.ticker}</span>
                    <div style={{ display: 'flex', gap: '6px' }}>
                      <button
                        onClick={() => handleAdd(item.ticker, 'buy')}
                        className="btn btn-cyan"
                        style={{ padding: '3px 8px', fontSize: '0.65rem' }}
                      >
                        + Long
                      </button>
                      <button
                        onClick={() => handleAdd(item.ticker, 'sell')}
                        className="btn btn-crimson"
                        style={{ padding: '3px 8px', fontSize: '0.65rem' }}
                      >
                        + Short
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="watchlist-lanes">
        <div className="watchlist-subtabs">
          <button
            className={activeScannerTab === 'long' ? 'active long' : 'long'}
            onClick={() => setActiveScannerTab('long')}
          >
            Long Watchlist
            <span>{buyItems.length}</span>
          </button>
          <button
            className={activeScannerTab === 'short' ? 'active short' : 'short'}
            onClick={() => setActiveScannerTab('short')}
          >
            Short Watchlist
            <span>{sellItems.length}</span>
          </button>
        </div>

        {activeScannerTab === 'long'
          ? renderLane('Long Scanners', 'Price above VWAP + bullish EMA stack + RSI > 50.', activeItems, 'BUY')
          : renderLane('Short Scanners', 'Price below VWAP + bearish EMA stack + RSI < 50.', activeItems, 'SELL')}
      </div>
    </div>
  );
}
