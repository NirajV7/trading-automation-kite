import React from 'react';

export default function RadarCandidates({ candidates }) {
  if (!candidates || candidates.length === 0) {
    return (
      <div className="panel" style={{ padding: '40px', textAlign: 'center', background: 'var(--bg-panel)', border: '1px solid var(--border-color)', borderRadius: '8px', margin: '20px' }}>
        <div style={{ fontSize: '1.5rem', color: 'var(--color-text-muted)', marginBottom: '10px' }}>📡 No Active Radar Candidates</div>
        <p style={{ color: 'var(--color-text-muted)', fontSize: '0.9rem' }}>
          The background state-machine is scanning the Nifty 50 tickers for 1-minute volume spikes and price breakouts.
        </p>
      </div>
    );
  }

  return (
    <div className="panel" style={{ background: 'var(--bg-panel)', border: '1px solid var(--border-color)', borderRadius: '8px', padding: '24px', margin: '20px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid var(--border-color)', paddingBottom: '12px' }}>
        <h2 style={{ fontSize: '1.2rem', fontWeight: 700, letterSpacing: '0.5px', color: 'var(--color-cyan)', display: 'flex', alignItems: 'center', gap: '8px' }}>
          ⚡ NIFTY 50 VOLUME SPIKE RADAR PULLBACK MONITOR
        </h2>
        <span style={{ fontSize: '0.8rem', color: 'var(--color-text-muted)', background: 'rgba(255,255,255,0.04)', padding: '4px 10px', borderRadius: '20px', border: '1px solid var(--border-color)' }}>
          {candidates.length} active candidate{candidates.length !== 1 ? 's' : ''}
        </span>
      </div>

      <div style={{ overflowX: 'auto' }}>
        <table className="watchlist-table" style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
          <thead>
            <tr style={{ borderBottom: '1px solid var(--border-color)', fontSize: '0.8rem', color: 'var(--color-text-muted)', textTransform: 'uppercase', height: '40px' }}>
              <th style={{ padding: '8px 12px' }}>Ticker</th>
              <th style={{ padding: '8px 12px' }}>Direction</th>
              <th style={{ padding: '8px 12px' }}>State Phase</th>
              <th style={{ padding: '8px 12px' }}>LTP</th>
              <th style={{ padding: '8px 12px' }}>EMA20 (5m)</th>
              <th style={{ padding: '8px 12px' }}>Pullback Range</th>
              <th style={{ padding: '8px 12px' }}>Validation Levels</th>
              <th style={{ padding: '8px 12px' }}>Trigger / SL / Target</th>
              <th style={{ padding: '8px 12px' }}>Spike Time</th>
            </tr>
          </thead>
          <tbody>
            {candidates.map((cand) => {
              const isBuy = cand.direction === 'BUY';
              const directionBadge = isBuy ? (
                <span className="badge badge-emerald" style={{ display: 'inline-block', minWidth: '60px', textAlign: 'center', background: 'rgba(63, 185, 80, 0.1)', border: '1px solid var(--color-emerald)', color: 'var(--color-emerald)', padding: '2px 8px', borderRadius: '4px', fontSize: '0.75rem', fontWeight: 600 }}>
                  LONG
                </span>
              ) : (
                <span className="badge badge-crimson" style={{ display: 'inline-block', minWidth: '60px', textAlign: 'center', background: 'rgba(248, 81, 73, 0.1)', border: '1px solid var(--color-crimson)', color: 'var(--color-crimson)', padding: '2px 8px', borderRadius: '4px', fontSize: '0.75rem', fontWeight: 600 }}>
                  SHORT
                </span>
              );

              // State phase formatting
              const stateText = cand.state === 'WAITING_FOR_PULLBACK' ? 'WAITING PULLBACK' : 'IN PULLBACK';
              const stateBadgeColor = cand.state === 'WAITING_FOR_PULLBACK' ? 'var(--color-gold)' : 'var(--color-cyan)';
              const stateBadgeBg = cand.state === 'WAITING_FOR_PULLBACK' ? 'rgba(227, 179, 65, 0.08)' : 'rgba(0, 229, 255, 0.08)';

              const stateBadge = (
                <span style={{ 
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '6px',
                  background: stateBadgeBg, 
                  border: `1px solid ${stateBadgeColor}`, 
                  color: stateBadgeColor, 
                  padding: '2px 10px', 
                  borderRadius: '4px', 
                  fontSize: '0.75rem', 
                  fontWeight: 600,
                  textTransform: 'uppercase',
                  animation: cand.state === 'IN_PULLBACK' ? 'pulse 2s infinite' : 'none'
                }}>
                  <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: stateBadgeColor, display: 'inline-block' }}></span>
                  {stateText}
                </span>
              );

              // Extract trigger levels
              const ltp = cand.ltp !== null && cand.ltp !== undefined ? cand.ltp : null;
              const ema = cand.ema20_5m !== null && cand.ema20_5m !== undefined ? cand.ema20_5m : null;
              const orb_high = cand.orb_high;
              const orb_low = cand.orb_low;
              const vwap = cand.vwap_5m;
              const spike_open = cand.spike_open;
              const prev_high = cand.prev_high_5m;
              const prev_low = cand.prev_low_5m;

              // Pullback extreme range logic
              const extreme = isBuy ? cand.lowest_pullback_low : cand.highest_pullback_high;
              const triggerPrice = isBuy ? prev_high : prev_low;
              
              // Target / SL projections
              const sl_projected = extreme;
              const risk_width = isBuy 
                ? (ltp && sl_projected ? ltp - sl_projected : 0)
                : (sl_projected && ltp ? sl_projected - ltp : 0);
              const target_projected = isBuy
                ? (ltp ? ltp + 2.0 * risk_width : 0)
                : (ltp ? ltp - 2.0 * risk_width : 0);

              return (
                <tr key={cand.symbol} style={{ borderBottom: '1px solid var(--border-color)', height: '60px', transition: 'background-color 0.2s', fontFamily: 'var(--font-sans)', fontSize: '0.9rem' }} onMouseEnter={(e) => e.currentTarget.style.backgroundColor = 'var(--bg-panel-hover)'} onMouseLeave={(e) => e.currentTarget.style.backgroundColor = 'transparent'}>
                  {/* Ticker */}
                  <td style={{ padding: '8px 12px', fontWeight: 700, color: '#ffffff' }}>
                    {cand.symbol}
                  </td>
                  
                  {/* Direction */}
                  <td style={{ padding: '8px 12px' }}>
                    {directionBadge}
                  </td>
                  
                  {/* State */}
                  <td style={{ padding: '8px 12px' }}>
                    {stateBadge}
                  </td>
                  
                  {/* LTP */}
                  <td style={{ padding: '8px 12px', fontFamily: 'var(--font-mono)', fontWeight: 600, color: ltp ? 'var(--color-cyan)' : 'var(--color-text-muted)' }}>
                    {ltp ? `₹${ltp.toFixed(2)}` : '—'}
                  </td>
                  
                  {/* 5m EMA20 */}
                  <td style={{ padding: '8px 12px', fontFamily: 'var(--font-mono)', color: 'var(--color-text-muted)' }}>
                    {ema ? `₹${ema.toFixed(2)}` : '—'}
                  </td>
                  
                  {/* Pullback range */}
                  <td style={{ padding: '8px 12px', fontSize: '0.85rem' }}>
                    <div style={{ fontFamily: 'var(--font-mono)' }}>
                      <span style={{ color: 'var(--color-text-muted)', fontSize: '0.75rem' }}>Extreme:</span>{' '}
                      <span style={{ color: isBuy ? 'var(--color-crimson)' : 'var(--color-emerald)' }}>
                        {extreme ? `₹${extreme.toFixed(2)}` : '—'}
                      </span>
                    </div>
                  </td>
                  
                  {/* Validation Levels */}
                  <td style={{ padding: '8px 12px', fontSize: '0.8rem', color: 'var(--color-text-muted)' }}>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '2px', fontFamily: 'var(--font-mono)' }}>
                      <div>Spike Open: <span style={{ color: '#ffffff' }}>₹{spike_open?.toFixed(2)}</span></div>
                      <div>ORB Boundary: <span style={{ color: '#ffffff' }}>₹{isBuy ? orb_high?.toFixed(2) : orb_low?.toFixed(2)}</span></div>
                      <div>VWAP: <span style={{ color: '#ffffff' }}>₹{vwap?.toFixed(2)}</span></div>
                    </div>
                  </td>
                  
                  {/* Trigger / SL / Target */}
                  <td style={{ padding: '8px 12px', fontSize: '0.85rem' }}>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '2px', fontFamily: 'var(--font-mono)' }}>
                      <div>Trigger: <span style={{ color: 'var(--color-cyan)', fontWeight: 600 }}>{triggerPrice ? `₹${triggerPrice.toFixed(2)}` : '—'}</span></div>
                      <div>SL: <span style={{ color: 'var(--color-crimson)' }}>{sl_projected ? `₹${sl_projected.toFixed(2)}` : '—'}</span></div>
                      <div>Target: <span style={{ color: 'var(--color-emerald)' }}>{target_projected && target_projected > 0 ? `₹${target_projected.toFixed(2)}` : '—'}</span></div>
                    </div>
                  </td>

                  {/* Spike Time */}
                  <td style={{ padding: '8px 12px', fontSize: '0.8rem', color: 'var(--color-text-muted)', fontFamily: 'var(--font-mono)' }}>
                    {cand.spike_time ? cand.spike_time.split(' ')[1] : '—'}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
