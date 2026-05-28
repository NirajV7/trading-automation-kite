import React, { useEffect, useMemo, useState } from 'react';

const INR = new Intl.NumberFormat('en-IN', {
  style: 'currency',
  currency: 'INR',
  maximumFractionDigits: 0
});

function today() {
  const d = new Date();
  const month = `${d.getMonth() + 1}`.padStart(2, '0');
  const day = `${d.getDate()}`.padStart(2, '0');
  return `${d.getFullYear()}-${month}-${day}`;
}

function money(value) {
  return INR.format(Number(value || 0));
}

function eventClass(type = '') {
  const t = type.toLowerCase();
  if (t.includes('reject') || t.includes('failed') || t.includes('blocked') || t.includes('timeout')) return 'danger';
  if (t.includes('filled') || t.includes('closed') || t.includes('active')) return 'success';
  if (t.includes('hit') || t.includes('cooldown')) return 'warn';
  return 'neutral';
}

export default function TradeJournalPanel({ apiUrl }) {
  const [date, setDate] = useState(today());
  const [strategy, setStrategy] = useState('');
  const [symbol, setSymbol] = useState('');
  const [eventType, setEventType] = useState('');
  const [events, setEvents] = useState([]);
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(false);

  const query = useMemo(() => {
    const params = new URLSearchParams({ date });
    if (strategy) params.set('strategy', strategy);
    if (symbol) params.set('symbol', symbol.toUpperCase());
    if (eventType) params.set('event_type', eventType);
    params.set('limit', '600');
    return params.toString();
  }, [date, strategy, symbol, eventType]);

  const fetchJournal = async () => {
    setLoading(true);
    try {
      const [eventsRes, summaryRes] = await Promise.all([
        fetch(`${apiUrl}/api/trade-journal?${query}`),
        fetch(`${apiUrl}/api/trade-journal/summary?date=${date}`)
      ]);
      const eventsData = await eventsRes.json();
      const summaryData = await summaryRes.json();
      setEvents(eventsData.events || []);
      setSummary(summaryData.summary || null);
    } catch (e) {
      console.debug('Trade journal fetch failed', e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchJournal();
    const id = setInterval(fetchJournal, 5000);
    return () => clearInterval(id);
  }, [query, date]);

  return (
    <div className="journal-layout">
      <section className="glass-panel journal-hero">
        <div>
          <span className="journal-eyebrow">Execution Ledger</span>
          <h2>Trade Journal</h2>
          <p>Signals, order states, fills, exits, cooldowns, and blocked trades from one JSONL source.</p>
        </div>
        <button className="btn btn-cyan" onClick={fetchJournal} disabled={loading}>
          {loading ? <span className="btn-spinner" /> : 'Refresh'}
        </button>
      </section>

      <section className="journal-summary-grid">
        <div className="journal-stat"><span>Realized PnL</span><strong className={(summary?.realized_pnl || 0) < 0 ? 'loss' : 'gain'}>{money(summary?.realized_pnl)}</strong></div>
        <div className="journal-stat"><span>Trades</span><strong>{summary?.trades || 0}</strong></div>
        <div className="journal-stat"><span>Win Rate</span><strong>{summary?.win_rate || 0}%</strong></div>
        <div className="journal-stat"><span>Wins / Losses</span><strong>{summary?.wins || 0} / {summary?.losses || 0}</strong></div>
        <div className="journal-stat"><span>Avg Win</span><strong className="gain">{money(summary?.avg_win)}</strong></div>
        <div className="journal-stat"><span>Avg Loss</span><strong className="loss">{money(summary?.avg_loss)}</strong></div>
        <div className="journal-stat"><span>Blocked</span><strong>{summary?.blocked_signals || 0}</strong></div>
      </section>

      <section className="glass-panel journal-table-panel">
        <div className="journal-filter-row">
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
          <select value={strategy} onChange={(e) => setStrategy(e.target.value)}>
            <option value="">All Strategies</option>
            <option value="ORB">ORB</option>
            <option value="RADAR">Nifty Radar</option>
            <option value="RECONCILED">Reconciled</option>
            <option value="MANUAL">Manual</option>
          </select>
          <input value={symbol} onChange={(e) => setSymbol(e.target.value)} placeholder="Symbol" />
          <select value={eventType} onChange={(e) => setEventType(e.target.value)}>
            <option value="">All Events</option>
            <option value="SIGNAL_DETECTED">Signal</option>
            <option value="SIGNAL_BLOCKED">Blocked</option>
            <option value="ENTRY_FILLED">Entry Filled</option>
            <option value="SL_PLACED">SL Placed</option>
            <option value="TARGET_HIT">Target Hit</option>
            <option value="SL_HIT">SL Hit</option>
            <option value="TRADE_CLOSED">Closed Trade</option>
            <option value="COOLDOWN_SET">Cooldown</option>
          </select>
        </div>

        <div className="journal-table-wrap">
          <table className="journal-table">
            <thead>
              <tr>
                <th>Time</th>
                <th>Symbol</th>
                <th>Strategy</th>
                <th>Event</th>
                <th>State</th>
                <th>Qty</th>
                <th>Price</th>
                <th>PnL</th>
                <th>Reason</th>
              </tr>
            </thead>
            <tbody>
              {events.length === 0 ? (
                <tr><td colSpan="9" className="journal-empty">No journal events for selected filters.</td></tr>
              ) : events.map((event) => (
                <tr key={event.event_id}>
                  <td className="mono">{event.timestamp?.slice(11) || '-'}</td>
                  <td><strong>{event.symbol || '-'}</strong></td>
                  <td>{event.strategy || '-'}</td>
                  <td><span className={`journal-chip ${eventClass(event.event_type)}`}>{event.event_type}</span></td>
                  <td>{event.state || '-'}</td>
                  <td className="mono">{event.qty ?? '-'}</td>
                  <td className="mono">{event.price ? `₹${event.price}` : '-'}</td>
                  <td className={`mono ${(event.pnl || 0) < 0 ? 'loss' : (event.pnl || 0) > 0 ? 'gain' : ''}`}>{event.pnl == null ? '-' : money(event.pnl)}</td>
                  <td>{event.reason || '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
