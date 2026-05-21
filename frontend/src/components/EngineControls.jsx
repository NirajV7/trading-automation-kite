import React, { useState, useEffect, useRef } from 'react';

export default function EngineControls({ 
  status, 
  engineMode, 
  setEngineMode, 
  onToggleLogger, 
  onToggleEngine, 
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
    onAddToWatchlist(symbol, direction);
    setSearchQuery('');
    setSearchResults([]);
  };

  const isLoggerActive = status.data_logger === 'active';
  const isEngineActive = status.kite_engine !== 'stopped';

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      
      {/* System Control Engine Panel */}
      <div className="glass-panel">
        <div className="panel-header">
          <span>Engine Controls</span>
          <span className="trend-badge trend-neut">SYS OPS</span>
        </div>
        
        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          {/* Data Logger Module */}
          <div style={{ display: 'flex', alignItems: 'center', justifySpaceBetween: 'space-between', justifyContent: 'space-between', paddingBottom: '8px', borderBottom: '1px solid rgba(255,255,255,0.03)' }}>
            <div style={{ display: 'flex', flexDirection: 'column' }}>
              <span style={{ fontSize: '0.85rem', fontWeight: 600 }}>WebSocket Logger</span>
              <span style={{ fontSize: '0.7rem', color: 'var(--color-text-muted)' }}>
                {isLoggerActive ? 'Ticks streaming...' : 'Offline'}
              </span>
            </div>
            <button 
              onClick={onToggleLogger} 
              className={isLoggerActive ? 'btn btn-crimson' : 'btn btn-emerald'}
            >
              <span>{isLoggerActive ? 'Stop' : 'Start'}</span>
            </button>
          </div>

          {/* Execution Core Strategy Engine */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div style={{ display: 'flex', flexDirection: 'column' }}>
                <span style={{ fontSize: '0.85rem', fontWeight: 600 }}>Execution Engine</span>
                <span style={{ fontSize: '0.7rem', color: 'var(--color-text-muted)' }}>
                  Mode: {status.kite_engine.toUpperCase()}
                </span>
              </div>
              <button 
                onClick={onToggleEngine} 
                className={isEngineActive ? 'btn btn-crimson' : 'btn btn-emerald'}
              >
                <span>{isEngineActive ? 'Stop' : 'Start'}</span>
              </button>
            </div>
            
            {/* Live mode selection toggle (Only active if stopped) */}
            {!isEngineActive && (
              <div style={{ display: 'flex', gap: '6px', marginTop: '4px' }}>
                <label style={{ flex: 1, textAlign: 'center', fontSize: '0.7rem', padding: '4px', border: '1px solid var(--border-color)', borderRadius: '4px', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '4px' }}>
                  <input 
                    type="radio" 
                    name="run_mode" 
                    value="dry" 
                    checked={engineMode === 'dry'}
                    onChange={() => setEngineMode('dry')} 
                  /> DRY
                </label>
                <label style={{ flex: 1, textAlign: 'center', fontSize: '0.7rem', padding: '4px', border: '1px solid var(--border-color)', borderRadius: '4px', cursor: 'pointer', color: 'var(--color-crimson)', borderColor: 'rgba(248, 81, 73, 0.2)', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '4px' }}>
                  <input 
                    type="radio" 
                    name="run_mode" 
                    value="live" 
                    checked={engineMode === 'live'}
                    onChange={() => setEngineMode('live')}
                  /> LIVE
                </label>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Watchlist Stock Search Panel */}
      <div className="glass-panel" ref={searchRef}>
        <div className="panel-header">
          <span>Add Instrument</span>
        </div>
        <div className="search-container">
          <input 
            type="text" 
            className="input-dark" 
            placeholder="Search Nifty 50..." 
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
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
                      + BUY
                    </button>
                    <button 
                      onClick={() => handleAdd(item.ticker, 'sell')} 
                      className="btn btn-crimson" 
                      style={{ padding: '2px 6px', fontSize: '0.65rem' }}
                    >
                      + SELL
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
      
    </div>
  );
}
