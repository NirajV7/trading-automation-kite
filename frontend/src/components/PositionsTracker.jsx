import React from 'react';

export default function PositionsTracker({
  positions,
  onSelectSymbol,
  onModifyStopLoss,
  onScaleOut,
  onExit
}) {
  return (
    <div className="glass-panel">
      <div className="panel-header">
        <span>Active Zerodha Brackets & Risk Engine</span>
      </div>
      
      <table className="custom-table">
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
          {positions.length === 0 ? (
            <tr>
              <td colSpan="9" style={{ textAlign: 'center', color: 'var(--color-text-muted)', padding: '20px' }}>
                No active Zerodha positions discovered.
              </td>
            </tr>
          ) : (
            positions.map((p) => {
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
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', fontSize: '0.72rem' }}>
                      {/* Stop Loss order linked */}
                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px' }}>
                        <span style={{ color: 'var(--color-text-muted)' }}>SL:</span>
                        {p.sl_price ? (
                          <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--color-crimson)', fontWeight: 600 }}>
                            ₹{p.sl_price.toFixed(2)}
                          </span>
                        ) : (
                          <span style={{ color: 'var(--color-gold)', fontSize: '0.9em', fontWeight: 600 }}>
                            ⚠️ GHOST SL
                          </span>
                        )}
                      </div>
                      
                      {/* Target Limit order linked */}
                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px' }}>
                        <span style={{ color: 'var(--color-text-muted)' }}>TGT:</span>
                        {p.target_price ? (
                          <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--color-emerald)', fontWeight: 600 }}>
                            ₹{p.target_price.toFixed(2)}
                          </span>
                        ) : (
                          <span style={{ color: 'var(--color-gold)', fontSize: '0.9em', fontWeight: 600 }}>
                            ⚠️ GHOST LIMIT
                          </span>
                        )}
                      </div>
                    </div>
                  </td>
                  
                  {/* Risk Assessment */}
                  <td>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                      <div style={{ display: 'flex', alignHTML: 'center', alignItems: 'center', justifyContent: 'space-between', fontSize: '0.72rem' }}>
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
                        onClick={() => onModifyStopLoss(p)} 
                        className="btn btn-cyan" 
                        style={{ padding: '4px 8px', fontSize: '0.7rem' }}
                      >
                        MOD SL
                      </button>
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
  );
}
