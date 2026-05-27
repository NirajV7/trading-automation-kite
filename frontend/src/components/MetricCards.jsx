import React from 'react';

export default function MetricCards({ margin, onPanic }) {
  const buyingPower = margin ? margin.net : '₹0.00';
  const cashBuffer = margin ? margin.cash : '₹0.00';

  return (
    <div className="glass-panel risk-summary-panel">
      <div className="risk-summary-layout">
        <div className="metrics-row risk-metrics-row">
          <div className="metric-card risk-metric-card">
            <div className="metric-label">Capital Allocation</div>
            <div className="metric-value">₹5,00,000</div>
          </div>
          <div className="metric-card risk-metric-card">
            <div className="metric-label">Buying Power</div>
            <div className="metric-value">{buyingPower}</div>
          </div>
          <div className="metric-card risk-metric-card">
            <div className="metric-label">Cash Buffer</div>
            <div className="metric-value" style={{ color: 'var(--color-text-muted)' }}>{cashBuffer}</div>
          </div>
          <div className="metric-card risk-metric-card">
            <div className="metric-label">Max Risk Per Trade</div>
            <div className="metric-value" style={{ color: 'var(--color-gold)' }}>₹2,500</div>
          </div>
        </div>
        
        {/* Emergency Panic Square Off Trigger */}
        <button onClick={onPanic} className="btn btn-panic risk-panic-button">
          ⚠️ PANIC EXIT
        </button>
      </div>
    </div>
  );
}
