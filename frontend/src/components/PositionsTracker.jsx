import React, { useState } from 'react';

export default function PositionsTracker({
  positions,
  onSelectSymbol,
  onModifyStopLoss,
  onScaleOut,
  onExit
}) {
  const [subTab, setSubTab] = useState('active');

  const activePositions = positions.filter(p => p.quantity !== 0);
  const closedPositions = positions.filter(p => p.quantity === 0);

  return (
    <div className="glass-panel">
      {/* Panel Header with Sub-Tabs */}
      <div className="panel-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span>Active Zerodha Brackets & Risk Engine</span>
        <div style={{ display: 'flex', gap: '6px', background: 'rgba(0, 0, 0, 0.2)', padding: '3px', borderRadius: '6px', border: '1px solid rgba(255, 255, 255, 0.05)' }}>
          <button 
            onClick={() => setSubTab('active')}
            style={{
              background: subTab === 'active' ? 'rgba(0, 229, 255, 0.15)' : 'transparent',
              color: subTab === 'active' ? 'var(--color-cyan)' : 'var(--color-text-muted)',
              border: '1px solid ' + (subTab === 'active' ? 'rgba(0, 229, 255, 0.3)' : 'transparent'),
              padding: '4px 12px',
              fontSize: '0.75rem',
              fontWeight: 600,
              borderRadius: '4px',
              cursor: 'pointer',
              transition: 'all 0.2s ease',
              outline: 'none'
            }}
          >
            Active ({activePositions.length})
          </button>
          <button 
            onClick={() => setSubTab('closed')}
            style={{
              background: subTab === 'closed' ? 'rgba(0, 229, 255, 0.15)' : 'transparent',
              color: subTab === 'closed' ? 'var(--color-cyan)' : 'var(--color-text-muted)',
              border: '1px solid ' + (subTab === 'closed' ? 'rgba(0, 229, 255, 0.3)' : 'transparent'),
              padding: '4px 12px',
              fontSize: '0.75rem',
              fontWeight: 600,
              borderRadius: '4px',
              cursor: 'pointer',
              transition: 'all 0.2s ease',
              outline: 'none'
            }}
          >
            Closed ({closedPositions.length})
          </button>
        </div>
      </div>

      {subTab === 'active' ? (
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
            {activePositions.length === 0 ? (
              <tr>
                <td colSpan="9" style={{ textAlign: 'center', color: 'var(--color-text-muted)', padding: '20px' }}>
                  No active Zerodha positions discovered.
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
                          ) : p.engine_target ? (
                            <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--color-cyan)', fontWeight: 600 }} title="Virtual Target Managed by Daemon">
                              ₹{p.engine_target.toFixed(2)} (VT)
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
      ) : (
        <table className="custom-table">
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
                  No closed trades logged today.
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
      )}
    </div>
  );
}
