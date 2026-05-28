import React, { useEffect, useState } from 'react';

const INR = new Intl.NumberFormat('en-IN', {
  style: 'currency',
  currency: 'INR',
  maximumFractionDigits: 0
});

function money(value) {
  return INR.format(Number(value || 0));
}

function statusClass(status) {
  if (status === 'BLOCKED') return 'blocked';
  if (status === 'DEGRADED') return 'degraded';
  return 'healthy';
}

function minutesLeft(item) {
  if (!item?.expires_at_epoch) return '';
  const sec = Math.max(0, item.expires_at_epoch - Date.now() / 1000);
  return `${Math.ceil(sec / 60)}m left`;
}

export default function StrategyHealthPanel({ apiUrl, health: externalHealth, onRefresh }) {
  const [health, setHealth] = useState(externalHealth || null);
  const [loading, setLoading] = useState(false);
  const displayHealth = health || externalHealth || null;

  const fetchHealth = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${apiUrl}/api/strategy-health`);
      const data = await res.json();
      if (!res.ok || !data.status) throw new Error(data.detail || 'Strategy health endpoint unavailable');
      setHealth(data);
      if (onRefresh) onRefresh(data);
    } catch (e) {
      const fallback = {
        status: 'DEGRADED',
        cards: [],
        cooldowns: {},
        governor: null,
        summary: null,
        error: e.message || 'Strategy health unavailable'
      };
      setHealth(fallback);
      if (onRefresh) onRefresh(fallback);
      console.debug('Strategy health fetch failed', e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (externalHealth) setHealth(externalHealth);
  }, [externalHealth]);

  useEffect(() => {
    fetchHealth();
    const id = setInterval(fetchHealth, 5000);
    return () => clearInterval(id);
  }, []);

  const cooldowns = Object.values(displayHealth?.cooldowns || {});
  const haltReasons = displayHealth?.governor?.state?.halt_reasons || [];

  return (
    <div className="health-layout">
      <section className={`glass-panel health-hero ${statusClass(displayHealth?.status)}`}>
        <div>
          <span className="journal-eyebrow">Execution Health</span>
          <h2>{displayHealth?.status || 'LOADING'}</h2>
          <p>{displayHealth?.error || 'Live readiness for entries, state machine, Risk Governor blockers, cooldowns, and strategy activity.'}</p>
        </div>
        <button className="btn btn-cyan" onClick={fetchHealth} disabled={loading}>
          {loading ? <span className="btn-spinner" /> : 'Refresh'}
        </button>
      </section>

      <section className="health-card-grid">
        {(displayHealth?.cards || []).map((card) => (
          <div className={`glass-panel health-card ${statusClass(card.status)}`} key={card.key}>
            <div className="health-card-head">
              <div>
                <span>{card.key}</span>
                <h3>{card.label}</h3>
              </div>
              <strong>{card.status}</strong>
            </div>
            <div className="health-metrics">
              <div><span>Trades</span><strong>{card.trades_today}</strong></div>
              <div><span>Blocked</span><strong>{card.blocked_count}</strong></div>
              <div><span>PnL</span><strong className={(card.pnl || 0) < 0 ? 'loss' : 'gain'}>{money(card.pnl)}</strong></div>
              <div><span>Active</span><strong>{card.active_states?.length || 0}</strong></div>
            </div>
            <div className="health-detail-list">
              <div>
                <span>Last Signal</span>
                <strong>{card.last_signal ? `${card.last_signal.symbol} ${card.last_signal.timestamp?.slice(11)}` : 'None'}</strong>
              </div>
              <div>
                <span>Last Trade</span>
                <strong>{card.last_trade ? `${card.last_trade.symbol} ${money(card.last_trade.pnl)}` : 'None'}</strong>
              </div>
              <div>
                <span>Active States</span>
                <strong>{card.active_states?.map((s) => `${s.symbol}:${s.state}`).join(', ') || 'None'}</strong>
              </div>
            </div>
          </div>
        ))}
      </section>

      <section className="health-bottom-grid">
        <div className="glass-panel health-list-panel">
          <div className="risk-panel-header">
            <div>
              <h2>Active Blockers</h2>
              <p>Risk Governor reasons currently stopping or degrading entries.</p>
            </div>
          </div>
          {haltReasons.length === 0 ? (
            <div className="risk-empty-state"><strong>No governor blockers</strong><span>Risk gate clean right now.</span></div>
          ) : haltReasons.map((reason) => (
            <div className="health-row" key={`${reason.code}-${reason.created_at}`}>
              <strong>{reason.code}</strong>
              <span>{reason.message}</span>
            </div>
          ))}
        </div>

        <div className="glass-panel health-list-panel">
          <div className="risk-panel-header">
            <div>
              <h2>Symbol Cooldowns</h2>
              <p>Only loss/error/manual-risk exits cool down symbols.</p>
            </div>
          </div>
          {cooldowns.length === 0 ? (
            <div className="risk-empty-state"><strong>No active cooldowns</strong><span>Clean profit exits do not block re-entry.</span></div>
          ) : cooldowns.map((item) => (
            <div className="health-row" key={item.symbol}>
              <strong>{item.symbol}</strong>
              <span>{item.reason} · {minutesLeft(item)}</span>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
