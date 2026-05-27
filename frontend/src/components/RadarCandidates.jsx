import React from 'react';

export default function RadarCandidates({ candidates }) {
  const formatPrice = (value) => (
    value !== null && value !== undefined && Number.isFinite(Number(value))
      ? `₹${Number(value).toFixed(2)}`
      : '—'
  );

  const formatTime = (value) => (value ? value.split(' ')[1] || value : '—');

  if (!candidates || candidates.length === 0) {
    return (
      <div className="glass-panel" style={{ padding: '40px', textAlign: 'center' }}>
        <div style={{ fontSize: '1.35rem', fontFamily: 'var(--font-header)', fontWeight: 700, color: 'var(--color-text-muted)', marginBottom: '10px' }}>
          📡 No Active Radar Candidates
        </div>
        <p style={{ color: 'var(--color-text-muted)', fontSize: '0.85rem' }}>
          The background state-machine is scanning the Nifty 50 tickers for 1-minute volume spikes and price breakouts.
        </p>
      </div>
    );
  }

  return (
    <div className="glass-panel radar-panel">
      <div className="radar-panel-header">
        <div>
          <h2>⚡ Spike Radar Pullback Monitor</h2>
          <p>Nifty 50 candidates waiting for clean trigger, stop, and target alignment.</p>
        </div>
        <span className="radar-count-pill">
          {candidates.length} active candidate{candidates.length !== 1 ? 's' : ''}
        </span>
      </div>

      <div className="radar-candidate-list">
        {candidates.map((cand) => {
          const isBuy = cand.direction === 'BUY';
          const ltp = cand.ltp ?? null;
          const ema = cand.ema20_5m ?? null;
          const orbBound = isBuy ? cand.orb_high : cand.orb_low;
          const extreme = isBuy ? cand.lowest_pullback_low : cand.highest_pullback_high;
          const triggerPrice = isBuy ? cand.prev_high_5m : cand.prev_low_5m;
          const slProjected = extreme;
          const riskWidth = isBuy
            ? (ltp && slProjected ? ltp - slProjected : 0)
            : (slProjected && ltp ? slProjected - ltp : 0);
          const targetProjected = isBuy
            ? (ltp ? ltp + 2.0 * riskWidth : 0)
            : (ltp ? ltp - 2.0 * riskWidth : 0);
          const isWaiting = cand.state === 'WAITING_FOR_PULLBACK';

          return (
            <article className="radar-candidate-card" key={cand.symbol}>
              <section className="radar-identity">
                <div>
                  <div className="radar-symbol">{cand.symbol}</div>
                  <div className="radar-subtext">Nifty 50 • spike {formatTime(cand.spike_time)}</div>
                </div>
                <div className="radar-badge-row">
                  <span className={`trend-badge ${isBuy ? 'trend-bull' : 'trend-bear'}`}>
                    {isBuy ? 'LONG' : 'SHORT'}
                  </span>
                  <span className={`radar-state-pill ${isWaiting ? 'state-waiting' : 'state-ready'}`}>
                    <span />
                    {isWaiting ? 'Waiting for pullback' : 'Pullback active'}
                  </span>
                </div>
              </section>

              <section className="radar-price-block">
                <div className="radar-block-title">Market Now</div>
                <div className="radar-big-price">{formatPrice(ltp)}</div>
                <div className="radar-subtext">EMA 20: {formatPrice(ema)}</div>
              </section>

              <section className="radar-level-group">
                <div className="radar-block-title">Validation</div>
                <div className="radar-level-grid">
                  <div className="radar-level-cell">
                    <span>Spike Open</span>
                    <strong>{formatPrice(cand.spike_open)}</strong>
                  </div>
                  <div className="radar-level-cell">
                    <span>ORB Bound</span>
                    <strong>{formatPrice(orbBound)}</strong>
                  </div>
                  <div className="radar-level-cell">
                    <span>VWAP</span>
                    <strong>{formatPrice(cand.vwap_5m)}</strong>
                  </div>
                  <div className="radar-level-cell radar-extreme-cell">
                    <span>{isBuy ? 'Pullback Low' : 'Pullback High'}</span>
                    <strong>{formatPrice(extreme)}</strong>
                  </div>
                </div>
              </section>

              <section className="radar-trade-plan">
                <div className="radar-block-title">Trade Plan</div>
                <div className="radar-plan-grid">
                  <div className="radar-plan-cell trigger">
                    <span>Trigger</span>
                    <strong>{formatPrice(triggerPrice)}</strong>
                  </div>
                  <div className="radar-plan-cell stop">
                    <span>Stop Loss</span>
                    <strong>{formatPrice(slProjected)}</strong>
                  </div>
                  <div className="radar-plan-cell target">
                    <span>Target</span>
                    <strong>{targetProjected > 0 ? formatPrice(targetProjected) : '—'}</strong>
                  </div>
                </div>
              </section>
            </article>
          );
        })}
      </div>
    </div>
  );
}
