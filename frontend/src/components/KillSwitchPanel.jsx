import React, { useEffect, useState } from 'react';

const INR = new Intl.NumberFormat('en-IN', {
  style: 'currency',
  currency: 'INR',
  maximumFractionDigits: 0
});

const DEFAULT_KILL_SWITCH_SETTINGS = {
  enabled: true,
  daily_loss_limit: 2000,
  max_consecutive_losses: 2,
  max_trades_per_day: 5,
  max_open_positions: 3,
  stale_market_data_threshold_seconds: 15,
  halt_on_missing_sl: true,
  halt_on_broker_local_mismatch: true,
  halt_on_kite_auth_loss: true,
  halt_on_stale_market_data: true,
  one_symbol_loss_lockout: true
};

function normalizeSettings(settings = {}) {
  return {
    ...DEFAULT_KILL_SWITCH_SETTINGS,
    ...settings
  };
}

function formatMoney(value) {
  return INR.format(Number(value || 0));
}

function ToggleRow({ label, description, checked, onChange }) {
  return (
    <label className="kill-toggle-row">
      <div>
        <strong>{label}</strong>
        <span>{description}</span>
      </div>
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
    </label>
  );
}

export default function KillSwitchPanel({ governor, apiUrl, onRefresh }) {
  const settings = normalizeSettings(governor?.settings);
  const metrics = {
    remaining_loss_room: settings.daily_loss_limit,
    ...governor?.metrics
  };
  const state = governor?.state || {};
  const reasons = state.halt_reasons || [];
  const [draft, setDraft] = useState(settings);
  const [saving, setSaving] = useState(false);
  const [actionLoading, setActionLoading] = useState(null);

  useEffect(() => {
    setDraft(settings);
  }, [JSON.stringify(settings)]);

  const patchDraft = (key, value) => {
    setDraft(prev => ({ ...prev, [key]: value }));
  };

  const saveSettings = async () => {
    setSaving(true);
    try {
      const res = await fetch(`${apiUrl}/api/risk-governor/settings`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(draft)
      });
      if (!res.ok) throw new Error('Settings save failed');
      await onRefresh();
    } catch (e) {
      alert(`Risk Governor settings failed: ${e.message}`);
    } finally {
      setSaving(false);
    }
  };

  const resetDefaults = async () => {
    if (!confirm('Reset Kill Switch settings to safe defaults?')) return;
    setSaving(true);
    try {
      const res = await fetch(`${apiUrl}/api/risk-governor/settings/defaults`, { method: 'POST' });
      if (!res.ok) throw new Error('Default reset failed');
      setDraft(DEFAULT_KILL_SWITCH_SETTINGS);
      await onRefresh();
    } catch (e) {
      alert(`Risk Governor default reset failed: ${e.message}`);
    } finally {
      setSaving(false);
    }
  };

  const manualHalt = async () => {
    if (!confirm('Block all new automated entries now? Existing positions stay managed.')) return;
    setActionLoading('halt');
    try {
      await fetch(`${apiUrl}/api/risk-governor/halt`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: 'Manual halt from Kill Switch UI' })
      });
      await onRefresh();
    } finally {
      setActionLoading(null);
    }
  };

  const unhalt = async () => {
    if (!confirm('Unhalt trading? If the same risk problem still exists, governor will halt again.')) return;
    setActionLoading('reset');
    try {
      await fetch(`${apiUrl}/api/risk-governor/reset`, { method: 'POST' });
      await onRefresh();
    } finally {
      setActionLoading(null);
    }
  };

  const statusClass = governor?.status === 'HALTED'
    ? 'halted'
    : governor?.status === 'DISABLED'
      ? 'disabled'
      : 'armed';

  return (
    <div className="kill-switch-layout">
      <section className={`glass-panel kill-hero ${statusClass}`}>
        <div className="kill-hero-copy">
          <span className="kill-eyebrow">Risk Governor</span>
          <h2>{governor?.status || 'LOADING'}</h2>
          <p>
            {governor?.status === 'HALTED'
              ? 'New automated entries are blocked. Existing positions remain under SL and virtual-target management.'
              : governor?.status === 'DISABLED'
                ? 'Governor gates are disabled. Existing order safety still remains active.'
                : 'New entries are allowed while all guardrails stay inside configured limits.'}
          </p>
        </div>
        <div className="kill-hero-actions">
          <button className="btn btn-panic" onClick={manualHalt} disabled={actionLoading !== null}>
            {actionLoading === 'halt' ? <span className="btn-spinner" /> : 'Manual Halt'}
          </button>
          <button className="btn btn-emerald" onClick={unhalt} disabled={actionLoading !== null}>
            {actionLoading === 'reset' ? <span className="btn-spinner" /> : 'Unhalt Trading'}
          </button>
        </div>
      </section>

      <section className="kill-grid">
        <div className="glass-panel kill-metrics-panel">
          <div className="risk-panel-header">
            <div>
              <h2>Today Risk</h2>
              <p>Realized, unrealized, loss room, and rule counters.</p>
            </div>
          </div>
          <div className="kill-metric-grid">
            <div className="kill-metric"><span>Net PnL</span><strong className={metrics.net_pnl < 0 ? 'loss' : 'gain'}>{formatMoney(metrics.net_pnl)}</strong></div>
            <div className="kill-metric"><span>Realized</span><strong>{formatMoney(metrics.realized_pnl)}</strong></div>
            <div className="kill-metric"><span>Unrealized</span><strong>{formatMoney(metrics.unrealized_pnl)}</strong></div>
            <div className="kill-metric"><span>Loss Room</span><strong>{formatMoney(metrics.remaining_loss_room)}</strong></div>
            <div className="kill-metric"><span>Trades Today</span><strong>{metrics.trades_today || 0}/{draft.max_trades_per_day || 0}</strong></div>
            <div className="kill-metric"><span>Loss Streak</span><strong>{metrics.consecutive_losses || 0}/{draft.max_consecutive_losses || 0}</strong></div>
          </div>
        </div>

        <div className="glass-panel kill-reasons-panel">
          <div className="risk-panel-header">
            <div>
              <h2>Halt Reasons</h2>
              <p>Unhalt clears these, but live unresolved issues trip again.</p>
            </div>
          </div>
          {reasons.length === 0 ? (
            <div className="risk-empty-state">
              <strong>No active halt reasons</strong>
              <span>Governor is clean for current session.</span>
            </div>
          ) : (
            <div className="kill-reason-list">
              {reasons.map((reason) => (
                <div className="kill-reason" key={`${reason.code}-${reason.created_at}`}>
                  <strong>{reason.code}</strong>
                  <span>{reason.message}</span>
                  <small>{reason.created_at}</small>
                </div>
              ))}
            </div>
          )}
        </div>
      </section>

      <section className="glass-panel kill-settings-panel">
        <div className="risk-panel-header">
          <div>
            <h2>Kill Switch Settings</h2>
            <p>Safe defaults load automatically. Change only when you want custom risk limits.</p>
          </div>
          <div className="kill-settings-actions">
            <button className="btn btn-emerald" onClick={resetDefaults} disabled={saving}>
              Use Defaults
            </button>
            <button className="btn btn-cyan" onClick={saveSettings} disabled={saving}>
              {saving ? <span className="btn-spinner" /> : 'Save Settings'}
            </button>
          </div>
        </div>

        <div className="kill-settings-grid">
          <label className="kill-input-card">
            <span>Daily Loss Limit</span>
            <input type="number" min="1" value={draft.daily_loss_limit ?? DEFAULT_KILL_SWITCH_SETTINGS.daily_loss_limit} onChange={(e) => patchDraft('daily_loss_limit', Number(e.target.value))} />
          </label>
          <label className="kill-input-card">
            <span>Max Consecutive Losses</span>
            <input type="number" min="1" value={draft.max_consecutive_losses ?? DEFAULT_KILL_SWITCH_SETTINGS.max_consecutive_losses} onChange={(e) => patchDraft('max_consecutive_losses', Number(e.target.value))} />
          </label>
          <label className="kill-input-card">
            <span>Max Trades Per Day</span>
            <input type="number" min="1" value={draft.max_trades_per_day ?? DEFAULT_KILL_SWITCH_SETTINGS.max_trades_per_day} onChange={(e) => patchDraft('max_trades_per_day', Number(e.target.value))} />
          </label>
          <label className="kill-input-card">
            <span>Max Open Positions</span>
            <input type="number" min="1" value={draft.max_open_positions ?? DEFAULT_KILL_SWITCH_SETTINGS.max_open_positions} onChange={(e) => patchDraft('max_open_positions', Number(e.target.value))} />
          </label>
          <label className="kill-input-card">
            <span>Stale Data Seconds</span>
            <input type="number" min="1" value={draft.stale_market_data_threshold_seconds ?? DEFAULT_KILL_SWITCH_SETTINGS.stale_market_data_threshold_seconds} onChange={(e) => patchDraft('stale_market_data_threshold_seconds', Number(e.target.value))} />
          </label>
        </div>

        <div className="kill-toggle-grid">
          <ToggleRow label="Governor Enabled" description="Master gate for all new automated entries." checked={!!draft.enabled} onChange={(v) => patchDraft('enabled', v)} />
          <ToggleRow label="Halt On Missing SL" description="Trip if tracked position has no confirmed protective SL." checked={!!draft.halt_on_missing_sl} onChange={(v) => patchDraft('halt_on_missing_sl', v)} />
          <ToggleRow label="Broker / Local Mismatch" description="Trip if Zerodha position and local trade state disagree." checked={!!draft.halt_on_broker_local_mismatch} onChange={(v) => patchDraft('halt_on_broker_local_mismatch', v)} />
          <ToggleRow label="Kite Auth Loss" description="Trip if Kite session expires or login is required." checked={!!draft.halt_on_kite_auth_loss} onChange={(v) => patchDraft('halt_on_kite_auth_loss', v)} />
          <ToggleRow label="Stale Market Data" description="Trip during market window if live ticks stop updating." checked={!!draft.halt_on_stale_market_data} onChange={(v) => patchDraft('halt_on_stale_market_data', v)} />
          <ToggleRow label="Symbol Loss Lockout" description="Block same symbol again after loss today." checked={!!draft.one_symbol_loss_lockout} onChange={(v) => patchDraft('one_symbol_loss_lockout', v)} />
        </div>
      </section>
    </div>
  );
}
