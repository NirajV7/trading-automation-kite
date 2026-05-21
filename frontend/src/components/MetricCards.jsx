import React from 'react';

export default function MetricCards({ margin, onPanic }) {
  const buyingPower = margin ? margin.net : '₹0.00';
  const cashBuffer = margin ? margin.cash : '₹0.00';

  return (
    <div className="glass-panel" style={{ background: 'rgba(18, 20, 28, 0.95)', borderColor: 'rgba(255, 255, 255, 0.08)' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div className="metrics-row" style={{ flexGrow: 1, maxWidth: '80%' }}>
          <div className="metric-card">
            <div className="metric-label">Capital Allocation</div>
            <div className="metric-value">₹5,00,000</div>
          </div>
          <div className="metric-card">
            <div className="metric-label">Buying Power</div>
            <div className="metric-value">{buyingPower}</div>
          </div>
          <div className="metric-card">
            <div className="metric-label">Cash Buffer</div>
            <div className="metric-value" style={{ color: 'var(--color-text-muted)' }}>{cashBuffer}</div>
          </div>
          <div className="metric-card">
            <div className="metric-label">Max Risk Per Trade</div>
            <div className="metric-value" style={{ color: 'var(--color-gold)' }}>₹2,500</div>
          </div>
        </div>
        
        {/* Emergency Panic Square Off Trigger */}
        <button onClick={onPanic} className="btn btn-panic" style={{ height: '50px', padding: '0 24px' }}>
          ⚠️ PANIC EXIT
        </button>
      </div>
    </div>
  );
}
