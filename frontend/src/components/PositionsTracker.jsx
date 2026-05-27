import React, { useState, useEffect } from 'react';

function InlineNumericUpdater({ value, onChange, tickSize, themeClass }) {
  const [inputValue, setInputValue] = useState(value !== null && value !== undefined ? value.toFixed(2) : '');
  const [isSaving, setIsSaving] = useState(false);

  // Sync state if value prop changes from parent
  useEffect(() => {
    if (value !== null && value !== undefined) {
      setInputValue(value.toFixed(2));
    } else {
      setInputValue('');
    }
  }, [value]);

  const step = tickSize || 0.05;

  const handleSave = async (valStr) => {
    const val = parseFloat(valStr);
    if (isNaN(val) || val <= 0) {
      // Revert to parent value
      setInputValue(value !== null && value !== undefined ? value.toFixed(2) : '');
      return;
    }

    // Round properly to tick size
    const rounded = Math.round(val / step) * step;
    if (rounded === value) {
      setInputValue(rounded.toFixed(2));
      return; // No change
    }

    setIsSaving(true);
    try {
      const res = await onChange(rounded);
      if (res && res.status === 'error') {
        alert(`Failed to update: ${res.message}`);
        setInputValue(value !== null && value !== undefined ? value.toFixed(2) : '');
      } else {
        setInputValue(rounded.toFixed(2));
      }
    } catch (e) {
      console.error(e);
      setInputValue(value !== null && value !== undefined ? value.toFixed(2) : '');
    } finally {
      setIsSaving(false);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter') {
      e.target.blur();
    } else if (e.key === 'Escape') {
      setInputValue(value !== null && value !== undefined ? value.toFixed(2) : '');
      e.target.blur();
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      const current = parseFloat(inputValue) || value || 0;
      const nextVal = (current + step);
      setInputValue(nextVal.toFixed(2));
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      const current = parseFloat(inputValue) || value || 0;
      const nextVal = Math.max(0, current - step);
      setInputValue(nextVal.toFixed(2));
    }
  };

  const handleArrowClick = (direction) => {
    const current = parseFloat(inputValue) || value || 0;
    const nextVal = direction === 'up' 
      ? (current + step) 
      : Math.max(0, current - step);
    const rounded = Math.round(nextVal / step) * step;
    setInputValue(rounded.toFixed(2));
    handleSave(rounded.toFixed(2));
  };

  return (
    <div className={`numeric-updater-container ${themeClass}`} style={{ opacity: isSaving ? 0.7 : 1 }}>
      {isSaving && (
        <div className="numeric-updater-loading-container">
          <div className="numeric-updater-spinner" />
        </div>
      )}
      <input
        type="number"
        className="numeric-updater-input"
        style={{ paddingLeft: isSaving ? '20px' : '6px' }}
        value={inputValue}
        step={step}
        onChange={(e) => setInputValue(e.target.value)}
        onBlur={() => handleSave(inputValue)}
        onKeyDown={handleKeyDown}
        disabled={isSaving}
      />
      <div className="numeric-updater-buttons">
        <button 
          className="numeric-updater-btn" 
          onClick={() => handleArrowClick('up')}
          disabled={isSaving}
          title={`Increase by ${step}`}
        >
          ▲
        </button>
        <button 
          className="numeric-updater-btn" 
          onClick={() => handleArrowClick('down')}
          disabled={isSaving}
          title={`Decrease by ${step}`}
        >
          ▼
        </button>
      </div>
    </div>
  );
}

export default function PositionsTracker({
  positions,
  onSelectSymbol,
  onModifyStopLoss,
  onModifyTarget,
  onScaleOut,
  onExit
}) {
  const [subTab, setSubTab] = useState('active');

  const activePositions = positions.filter(p => p.quantity !== 0);
  const closedPositions = positions.filter(p => p.quantity === 0);

  return (
    <div className="glass-panel risk-table-panel positions-panel">
      {/* Panel Header with Sub-Tabs */}
      <div className="risk-panel-header">
        <div>
          <h2>Active Zerodha Brackets</h2>
          <p>Live position risk, SL/target controls, ADR exhaustion, and exit actions.</p>
        </div>
        <div className="risk-subtabs">
          <button 
            onClick={() => setSubTab('active')}
            className={subTab === 'active' ? 'active' : ''}
          >
            Active ({activePositions.length})
          </button>
          <button 
            onClick={() => setSubTab('closed')}
            className={subTab === 'closed' ? 'active' : ''}
          >
            Closed ({closedPositions.length})
          </button>
        </div>
      </div>

      {subTab === 'active' ? (
        <div className="risk-table-wrap">
        <table className="custom-table risk-data-table">
          <thead>
            <tr>
              <th>Symbol</th>
              <th>Net Qty</th>
              <th>Avg Entry</th>
              <th>LTP</th>
              <th>PnL (INR)</th>
              <th>SL / Target Status</th>
              <th>Risk Assessment</th>
              <th>ADR Exhaustion</th>
              <th style={{ textAlign: 'right' }}>Action</th>
            </tr>
          </thead>
          <tbody>
            {activePositions.length === 0 ? (
              <tr>
                <td colSpan="9" style={{ textAlign: 'center', color: 'var(--color-text-muted)', padding: '20px' }}>
                  <div className="risk-empty-state">
                    <strong>No active Zerodha positions</strong>
                    <span>Risk engine is armed. New live/manual positions will appear here.</span>
                  </div>
                </td>
              </tr>
            ) : (
              activePositions.map((p) => {
                const isHighExhaustion = p.adr_exhaustion_pct >= 90;
                const rowClass = isHighExhaustion ? 'gold-pulse-active' : '';

                return (
                  <tr 
                    key={p.symbol} 
                    className={rowClass} 
                    style={{ transition: 'all 0.3s ease' }}
                  >
                    {/* Symbol */}
                    <td 
                      style={{ fontWeight: 700, color: 'var(--color-cyan)', cursor: 'pointer' }} 
                      onClick={() => onSelectSymbol(p.symbol)} 
                      title="Click to view chart"
                    >
                      {p.symbol}
                    </td>
                    
                    {/* Net Qty */}
                    <td 
                      className={p.quantity > 0 ? 'text-up' : 'text-down'}
                      style={{ fontFamily: 'var(--font-mono)', fontWeight: 600 }} 
                    >
                      {p.quantity > 0 ? '+' : ''}{p.quantity}
                    </td>
                    
                    {/* Avg Entry */}
                    <td style={{ fontFamily: 'var(--font-mono)' }}>
                      ₹{p.average_price.toFixed(2)}
                    </td>
                    
                    {/* LTP */}
                    <td style={{ fontFamily: 'var(--font-mono)' }}>
                      ₹{p.last_price.toFixed(2)}
                    </td>
                    
                    {/* PnL */}
                    <td>
                      <div 
                        className={p.pnl >= 0 ? 'text-up' : 'text-down'}
                        style={{ fontFamily: 'var(--font-mono)', fontWeight: 700 }} 
                      >
                        ₹{p.pnl.toFixed(2)}
                      </div>
                      <div 
                        className={p.pnl >= 0 ? 'text-up' : 'text-down'}
                        style={{ fontFamily: 'var(--font-mono)', fontSize: '0.7rem' }} 
                      >
                        {p.pnl_pct.toFixed(2)}%
                      </div>
                    </td>
                    
                    {/* SL / Target Status */}
                    <td>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', fontSize: '0.72rem' }}>
                        {/* Stop Loss order linked */}
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '4px' }}>
                          <span style={{ color: 'var(--color-text-muted)', minWidth: '24px' }}>SL:</span>
                          <InlineNumericUpdater
                            value={p.sl_price || p.engine_sl}
                            tickSize={p.tick_size}
                            themeClass={p.sl_price ? "sl-theme" : "ghost-theme"}
                            onChange={(newVal) => onModifyStopLoss(
                              p.symbol,
                              newVal,
                              p.sl_order_id,
                              p.quantity,
                              p.product
                            )}
                          />
                        </div>
                        
                        {/* Target Limit order linked */}
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '4px' }}>
                          <span style={{ color: 'var(--color-text-muted)', minWidth: '24px' }}>TGT:</span>
                          <InlineNumericUpdater
                            value={p.target_price || p.engine_target}
                            tickSize={p.tick_size}
                            themeClass={p.target_price ? "tgt-theme" : (p.engine_target ? "tgt-vt-theme" : "ghost-theme")}
                            onChange={(newVal) => onModifyTarget(
                              p.symbol,
                              newVal,
                              p.target_order_id
                            )}
                          />
                        </div>
                      </div>
                    </td>
                    
                    {/* Risk Assessment */}
                    <td>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: '0.72rem' }}>
                          <span style={{ color: 'var(--color-text-muted)' }}>Risk:</span>
                          <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, color: 'var(--color-gold)' }}>
                            ₹{p.allocated_risk.toFixed(0)}
                          </span>
                        </div>
                        {/* Risk percentage gauge */}
                        <div className="exhaustion-track" style={{ height: '4px' }}>
                          <div className="exhaustion-bar gold" style={{ width: `${p.risk_pct}%` }} />
                        </div>
                      </div>
                    </td>
                    
                    {/* ADR Exhaustion progress */}
                    <td>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: '0.72rem' }}>
                          <span style={{ color: 'var(--color-text-muted)' }}>Exhaustion:</span>
                          <span 
                            className={isHighExhaustion ? 'text-down' : 'color-cyan'}
                            style={{ fontFamily: 'var(--font-mono)', fontWeight: 700 }}
                          >
                            {p.adr_exhaustion_pct.toFixed(0)}%
                          </span>
                        </div>
                        <div className="exhaustion-track">
                          <div 
                            className={isHighExhaustion ? 'exhaustion-bar gold' : 'exhaustion-bar'}
                            style={{ width: `${Math.min(100, p.adr_exhaustion_pct)}%` }} 
                          />
                        </div>
                      </div>
                    </td>
                    
                    {/* Action Buttons */}
                    <td style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>
                      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '6px' }}>
                        <button 
                          onClick={() => onScaleOut(p.symbol)} 
                          className="btn btn-emerald" 
                          style={{ padding: '4px 8px', fontSize: '0.7rem' }}
                        >
                          BOOK 50%
                        </button>
                        <button 
                          onClick={() => onExit(p.symbol)} 
                          className="btn btn-crimson" 
                          style={{ padding: '4px 8px', fontSize: '0.7rem' }}
                        >
                          EXIT
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
        </div>
      ) : (
        <div className="risk-table-wrap">
        <table className="custom-table risk-data-table">
          <thead>
            <tr>
              <th>Symbol</th>
              <th>Product</th>
              <th>Strategy</th>
              <th>Realized P&L (INR)</th>
            </tr>
          </thead>
          <tbody>
            {closedPositions.length === 0 ? (
              <tr>
                <td colSpan="4" style={{ textAlign: 'center', color: 'var(--color-text-muted)', padding: '20px' }}>
                  <div className="risk-empty-state">
                    <strong>No closed trades today</strong>
                    <span>Completed positions will show realized P&L here.</span>
                  </div>
                </td>
              </tr>
            ) : (
              closedPositions.map((p) => {
                return (
                  <tr key={p.symbol} style={{ transition: 'all 0.3s ease' }}>
                    {/* Symbol */}
                    <td 
                      style={{ fontWeight: 700, color: 'var(--color-cyan)', cursor: 'pointer' }} 
                      onClick={() => onSelectSymbol(p.symbol)}
                      title="Click to view chart"
                    >
                      {p.symbol}
                    </td>
                    
                    {/* Product */}
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8rem', color: 'var(--color-text-muted)' }}>
                      {p.product}
                    </td>
                    
                    {/* Strategy */}
                    <td style={{ fontSize: '0.8rem', color: 'var(--color-text-muted)' }}>
                      {p.strategy || 'UNTRACKED'}
                    </td>
                    
                    {/* PnL */}
                    <td 
                      className={p.pnl >= 0 ? 'text-up' : 'text-down'}
                      style={{ fontFamily: 'var(--font-mono)', fontWeight: 700 }} 
                    >
                      ₹{p.pnl.toFixed(2)}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
        </div>
      )}
    </div>
  );
}
