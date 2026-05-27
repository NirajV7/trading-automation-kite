import React, { useState, useEffect } from 'react';
import MetricCards from './components/MetricCards';
import EngineControls from './components/EngineControls';
import WatchlistScanners from './components/WatchlistScanners';
import TechnicalChart from './components/TechnicalChart';
import PositionsTracker from './components/PositionsTracker';
import TelemetryLog from './components/TelemetryLog';
import OrderBook from './components/OrderBook';
import RadarCandidates from './components/RadarCandidates';

const API_URL = "http://100.117.188.86:8080";

// Safely resolve Electron ipcRenderer if available
let ipcRenderer = null;
try {
  if (window.require) {
    ipcRenderer = window.require('electron').ipcRenderer;
  }
} catch (e) {
  console.log("Running outside of Electron context.");
}

export default function App() {
  // Navigation State
  const [activeTab, setActiveTab] = useState('radar'); // 'radar', 'spikes', 'chart', 'positions', 'system'

  // Master app states
  const [status, setStatus] = useState({
    data_logger: "stopped",
    kite_engine: "stopped",
    kite_needs_login: true,
    kite_auth_url: "#",
    kite_margin: null,
    network: { is_whitelisted: false }
  });
  const [engineMode, setEngineMode] = useState("dry"); // "dry" or "live"
  const [watchlistData, setWatchlistData] = useState([]);
  const [radarCandidates, setRadarCandidates] = useState([]);
  const [positions, setPositions] = useState([]);
  const [orders, setOrders] = useState([]);
  const [logOutput, setLogOutput] = useState("Connecting to FastAPI daemon...");
  const [selectedSymbol, setSelectedSymbol] = useState("RELIANCE");
  const [chartInterval, setChartInterval] = useState("5minute");

  // Operation Loading States
  const [loggerLoading, setLoggerLoading] = useState(false);
  const [loggerAction, setLoggerAction] = useState(null);
  const [engineLoading, setEngineLoading] = useState(false);
  const [refreshLoading, setRefreshLoading] = useState(false);
  const [panicLoading, setPanicLoading] = useState(false);
  const [shutdownLoading, setShutdownLoading] = useState(false);

  // Fetch status
  const fetchStatus = async () => {
    try {
      const res = await fetch(`${API_URL}/api/status`);
      const data = await res.json();
      setStatus(data);
    } catch (e) {
      setLogOutput(prev => prev + "\n[ERROR] FastAPI daemon connection failed. Ensure backend is running.");
    }
  };

  // Fetch watchlists
  const fetchWatchlistData = async () => {
    try {
      const res = await fetch(`${API_URL}/api/watchlist/data`);
      const data = await res.json();
      setWatchlistData(data.watchlist_data || []);
    } catch (e) {
      console.debug("Failed fetching watchlist data", e);
    }
  };

  // Fetch positions & sync tray
  const fetchPositions = async () => {
    try {
      const res = await fetch(`${API_URL}/api/kite/positions`);
      const data = await res.json();
      const posData = data.positions || [];
      setPositions(posData);

      // Send PnL updates to system tray
      if (ipcRenderer) {
        let totalPnL = 0;
        posData.forEach(p => { totalPnL += p.pnl; });
        const pnlText = totalPnL >= 0 ? `+₹${totalPnL.toFixed(0)}` : `-₹${Math.abs(totalPnL).toFixed(0)}`;
        ipcRenderer.send('update-tray-pnl', `PnL: ${pnlText}`);
      }
    } catch (e) {
      console.debug("Failed fetching positions", e);
    }
  };

  // Fetch orders
  const fetchOrders = async () => {
    try {
      const res = await fetch(`${API_URL}/api/kite/orders`);
      const data = await res.json();
      setOrders(data.orders || []);
    } catch (e) {
      console.debug("Failed fetching orders", e);
    }
  };

  // Fetch logs
  const fetchLogs = async () => {
    try {
      const res = await fetch(`${API_URL}/api/logs`);
      const data = await res.json();
      setLogOutput(data.logs || "");
    } catch (e) {
      console.debug("Failed fetching logs", e);
    }
  };

  // Fetch radar candidates
  const fetchRadarCandidates = async () => {
    try {
      const res = await fetch(`${API_URL}/api/radar/candidates`);
      const data = await res.json();
      setRadarCandidates(data.candidates || []);
    } catch (e) {
      console.debug("Failed fetching radar candidates", e);
    }
  };

  // Initial sync & polling
  useEffect(() => {
    fetchStatus();
    fetchWatchlistData();
    fetchRadarCandidates();
    fetchPositions();
    fetchOrders();
    fetchLogs();

    const intervalStatus = setInterval(fetchStatus, 5000);
    const intervalWatchlist = setInterval(fetchWatchlistData, 2000);
    const intervalRadar = setInterval(fetchRadarCandidates, 2000);
    const intervalPositions = setInterval(fetchPositions, 1500);
    const intervalOrders = setInterval(fetchOrders, 2000);
    const intervalLogs = setInterval(fetchLogs, 3000);

    return () => {
      clearInterval(intervalStatus);
      clearInterval(intervalWatchlist);
      clearInterval(intervalRadar);
      clearInterval(intervalPositions);
      clearInterval(intervalOrders);
      clearInterval(intervalLogs);
    };
  }, []);

  // Listen for IPC tray panic calls
  useEffect(() => {
    if (!ipcRenderer) return;

    const handleTrayPanic = () => {
      triggerPanic();
    };

    ipcRenderer.on('trigger-panic-kill', handleTrayPanic);
    return () => {
      ipcRenderer.removeListener('trigger-panic-kill', handleTrayPanic);
    };
  }, [positions]);

  // Operations
  const toggleLogger = async () => {
    const action = status.data_logger === 'active' ? 'stop_logger' : 'start_logger';
    setLoggerAction(action === 'stop_logger' ? 'stop' : 'start');
    setLoggerLoading(true);
    try {
      const res = await fetch(`${API_URL}/api/system/${action}`, { method: 'POST' });
      const data = await res.json();
      if (data.status === 'error') {
        alert(`❌ Logger Error: ${data.message}`);
      }
      // Delay to let process initialization or failure settle
      await new Promise(r => setTimeout(r, 1000));
      await fetchStatus();
    } catch (e) {
      alert(`❌ Failed to toggle data logger: ${e.message}`);
    } finally {
      setLoggerLoading(false);
      setLoggerAction(null);
    }
  };

  const toggleEngine = async () => {
    const action = status.kite_engine !== 'stopped' ? 'stop_engine' : 'start_engine';
    const body = action === 'start_engine' ? JSON.stringify({ mode: engineMode }) : undefined;
    setEngineLoading(true);
    try {
      const res = await fetch(`${API_URL}/api/system/${action}`, {
        method: 'POST',
        headers: body ? { 'Content-Type': 'application/json' } : {},
        body
      });
      const data = await res.json();
      if (data.status === 'error') {
        alert(`❌ Engine Error: ${data.message}`);
      }
      // Delay to let process initialization or failure settle
      await new Promise(r => setTimeout(r, 1000));
      await fetchStatus();
    } catch (e) {
      alert(`❌ Failed to toggle execution engine: ${e.message}`);
    } finally {
      setEngineLoading(false);
    }
  };

  const stopAll = async () => {
    if (!confirm("🛑 Shutdown all running backend services?")) return;
    setShutdownLoading(true);
    try {
      const res = await fetch(`${API_URL}/api/system/stop_all`, { method: 'POST' });
      const data = await res.json();
      alert(`🛑 ${data.message}`);
      await fetchStatus();
    } catch (e) {
      alert(`❌ Shutdown command failed: ${e.message}`);
    } finally {
      setShutdownLoading(false);
    }
  };

  const triggerPanic = async () => {
    if (!confirm("⚠️ PANIC EXIT: Cancel all orders & square off all positions?")) return;
    setPanicLoading(true);
    try {
      const res = await fetch(`${API_URL}/api/kite/panic`, { method: 'POST' });
      const data = await res.json();
      alert(data.message);
      await fetchPositions();
    } catch (e) {
      alert("Panic shutdown failed.");
    } finally {
      setPanicLoading(false);
    }
  };

  const forceRefresh = async () => {
    setRefreshLoading(true);
    try {
      const res = await fetch(`${API_URL}/api/system/force_refresh`, { method: 'POST' });
      const data = await res.json();
      console.log('[Force Refresh]', data.message);
    } catch (e) {
      alert(`❌ Force Refresh failed: ${e.message}`);
    } finally {
      // Re-fetch status/telemetry immediately
      await fetchStatus();
      await fetchPositions();
      await fetchOrders();
      await fetchWatchlistData();
      setRefreshLoading(false);
    }
  };

  const exitPosition = async (symbol) => {
    if (!confirm(`Exit position for ${symbol}?`)) return;
    try {
      await fetch(`${API_URL}/api/kite/exit_position`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol })
      });
      fetchPositions();
    } catch (e) {
      console.error(e);
    }
  };

  const scaleOutPosition = async (symbol) => {
    if (!confirm(`Book 50% profits on ${symbol}?`)) return;
    try {
      await fetch(`${API_URL}/api/kite/scale_out`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol })
      });
      fetchPositions();
    } catch (e) {
      console.error(e);
    }
  };

  const modifyStopLoss = async (symbol, newSL, slOrderId, quantity, product) => {
    try {
      const res = await fetch(`${API_URL}/api/kite/modify_sl`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          symbol,
          new_sl_price: parseFloat(newSL),
          sl_order_id: slOrderId || null,
          quantity,
          transaction_type: quantity > 0 ? "SELL" : "BUY",
          product
        })
      });
      const data = await res.json();
      fetchPositions();
      return data;
    } catch (e) {
      console.error("Failed to modify stop loss", e);
      return { status: 'error', message: e.message || 'Network error' };
    }
  };

  const modifyTarget = async (symbol, newTarget, targetOrderId) => {
    try {
      const res = await fetch(`${API_URL}/api/kite/modify_target`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          symbol,
          new_target_price: parseFloat(newTarget),
          target_order_id: targetOrderId || null
        })
      });
      const data = await res.json();
      fetchPositions();
      return data;
    } catch (e) {
      console.error("Failed to modify target", e);
      return { status: 'error', message: e.message || 'Network error' };
    }
  };

  const cancelOrder = async (orderId, variety = "regular") => {
    if (!confirm(`Cancel order ${orderId}?`)) return;
    try {
      const res = await fetch(`${API_URL}/api/kite/orders/cancel`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ order_id: orderId, variety })
      });
      const data = await res.json();
      if (data.status === 'success') {
        alert("Order cancelled successfully");
      } else {
        alert(`Error: ${data.message}`);
      }
      fetchOrders();
    } catch (e) {
      alert("Failed to cancel order.");
    }
  };

  const modifyOrderParams = async (orderId, variety, orderType, currentQty, currentPrice, currentTriggerPrice) => {
    const newQtyStr = prompt(`Enter new quantity for order ${orderId}:`, currentQty);
    if (newQtyStr === null) return;
    const qty = parseInt(newQtyStr);
    if (isNaN(qty) || qty <= 0) {
      alert("Invalid quantity");
      return;
    }

    let price = 0.0;
    if (orderType === "LIMIT" || orderType === "SL") {
      const newPriceStr = prompt(`Enter new limit price for order ${orderId}:`, currentPrice);
      if (newPriceStr === null) return;
      price = parseFloat(newPriceStr);
      if (isNaN(price) || price < 0) {
        alert("Invalid price");
        return;
      }
    }

    let triggerPrice = 0.0;
    if (orderType === "SL" || orderType === "SL-M") {
      const newTriggerStr = prompt(`Enter new trigger price for order ${orderId}:`, currentTriggerPrice);
      if (newTriggerStr === null) return;
      triggerPrice = parseFloat(newTriggerStr);
      if (isNaN(triggerPrice) || triggerPrice < 0) {
        alert("Invalid trigger price");
        return;
      }
    }

    try {
      const res = await fetch(`${API_URL}/api/kite/orders/modify`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          order_id: orderId,
          variety,
          quantity: qty,
          price,
          trigger_price: triggerPrice,
          order_type: orderType
        })
      });
      const data = await res.json();
      if (data.status === 'success') {
        alert("Order modified successfully");
      } else {
        alert(`Error: ${data.message}`);
      }
      fetchOrders();
    } catch (e) {
      alert("Failed to modify order.");
    }
  };

  const addToWatchlist = async (symbol, direction) => {
    try {
      await fetch(`${API_URL}/api/watchlist/add`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol, direction })
      });
      fetchWatchlistData();
    } catch (e) {
      alert("Failed to add symbol");
    }
  };

  const removeFromWatchlist = async (symbol) => {
    try {
      await fetch(`${API_URL}/api/watchlist/remove`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol })
      });
      fetchWatchlistData();
    } catch (e) {
      console.error(e);
    }
  };

  const selectChartSymbol = (symbol) => {
    setSelectedSymbol(symbol);
    // Switch to chart tab if user clicked an instrument from another view
    setActiveTab('chart');
  };

  return (
    <div className="app-shell" style={{ display: 'flex', flexDirection: 'column', height: '100vh', backgroundColor: 'var(--bg-darkest)' }}>
      {/* 1. Header Toolbar */}
      <header className="app-header">
        <div className="header-title">
          <span className="brand-mark">🛡️</span>
          <span className="brand-name">KITE QUANT TERMINAL</span>
          {status.network && status.network.is_whitelisted && (
            <span className="tailscale-pill" style={{ fontSize: '0.6em', background: 'rgba(0, 229, 255, 0.12)', color: 'var(--color-cyan)', padding: '2px 6px', borderRadius: '4px', border: '1px solid rgba(0, 229, 255, 0.3)' }}>
              TS SECURE
            </span>
          )}
        </div>
        
        <div className="header-status">
          {/* Zerodha Authentication Banner */}
          {status.kite_needs_login ? (
            <a href={status.kite_auth_url} target="_blank" className="btn btn-crimson top-action-button" style={{ textDecoration: 'none' }}>
              ⚠️ AUTHENTICATE ZERODHA
            </a>
          ) : (
            <span className="kite-status-pill" style={{ color: 'var(--color-emerald)', fontSize: '0.8rem', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '6px' }}>
              <span className="status-dot-live" style={{ width: '8px', height: '8px', background: 'var(--color-emerald)', borderRadius: '50%' }}></span>
              KITE CONNECT SECURE
            </span>
          )}

          {/* Force Refresh — busts caches and restarts dead logger */}
          <button 
            onClick={forceRefresh} 
            className="btn btn-cyan top-action-button" 
            style={{ padding: '6px 12px', fontSize: '0.75rem' }}
            disabled={refreshLoading || loggerLoading || engineLoading || panicLoading || shutdownLoading}
          >
            {refreshLoading ? <span className="btn-spinner"></span> : '🔄'} REFRESH
          </button>

          {/* Global Emergency Panic Switch */}
          <button 
            onClick={triggerPanic} 
            className="btn btn-panic top-action-button top-panic-button" 
            style={{ padding: '6px 16px', fontSize: '0.8rem' }}
            disabled={panicLoading || refreshLoading || loggerLoading || engineLoading || shutdownLoading}
          >
            {panicLoading ? <span className="btn-spinner"></span> : '⚠️'} PANIC EXIT
          </button>

          {/* System Global Shutdown Controls */}
          <button 
            onClick={stopAll} 
            className="btn btn-crimson top-action-button"
            disabled={shutdownLoading || refreshLoading || loggerLoading || engineLoading || panicLoading}
          >
            {shutdownLoading ? <span className="btn-spinner"></span> : '🛑'} SHUTDOWN ALL
          </button>
        </div>
      </header>

      {/* 2. Chrome-like tab bar navigation */}
      <div className="chrome-tabs app-nav-tabs" style={{ display: 'flex', gap: '4px', background: 'var(--bg-darker)', borderBottom: '1px solid var(--border-color)', padding: '0 20px', height: '40px', alignItems: 'flex-end', WebkitAppRegion: 'no-drag' }}>
        <button 
          onClick={() => setActiveTab('radar')}
          style={{
            background: activeTab === 'radar' ? 'var(--bg-panel)' : 'transparent',
            border: '1px solid ' + (activeTab === 'radar' ? 'var(--border-color)' : 'transparent'),
            borderBottom: 'none',
            borderTopLeftRadius: '8px',
            borderTopRightRadius: '8px',
            color: activeTab === 'radar' ? 'var(--color-cyan)' : 'var(--color-text-muted)',
            padding: '8px 16px',
            fontSize: '0.8rem',
            fontWeight: 600,
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            height: '34px',
            transition: 'all 0.2s ease',
            boxShadow: activeTab === 'radar' ? '0 -4px 10px rgba(0, 229, 255, 0.05)' : 'none',
            outline: 'none'
          }}
        >
          📡 Watchlist Radar
        </button>
        <button 
          onClick={() => setActiveTab('spikes')}
          style={{
            background: activeTab === 'spikes' ? 'var(--bg-panel)' : 'transparent',
            border: '1px solid ' + (activeTab === 'spikes' ? 'var(--border-color)' : 'transparent'),
            borderBottom: 'none',
            borderTopLeftRadius: '8px',
            borderTopRightRadius: '8px',
            color: activeTab === 'spikes' ? 'var(--color-cyan)' : 'var(--color-text-muted)',
            padding: '8px 16px',
            fontSize: '0.8rem',
            fontWeight: 600,
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            height: '34px',
            transition: 'all 0.2s ease',
            boxShadow: activeTab === 'spikes' ? '0 -4px 10px rgba(0, 229, 255, 0.05)' : 'none',
            outline: 'none'
          }}
        >
          ⚡ Spike Radar
        </button>
        <button 
          onClick={() => setActiveTab('chart')}
          style={{
            background: activeTab === 'chart' ? 'var(--bg-panel)' : 'transparent',
            border: '1px solid ' + (activeTab === 'chart' ? 'var(--border-color)' : 'transparent'),
            borderBottom: 'none',
            borderTopLeftRadius: '8px',
            borderTopRightRadius: '8px',
            color: activeTab === 'chart' ? 'var(--color-cyan)' : 'var(--color-text-muted)',
            padding: '8px 16px',
            fontSize: '0.8rem',
            fontWeight: 600,
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            height: '34px',
            transition: 'all 0.2s ease',
            boxShadow: activeTab === 'chart' ? '0 -4px 10px rgba(0, 229, 255, 0.05)' : 'none',
            outline: 'none'
          }}
        >
          📈 Technical Chart
        </button>
        <button 
          onClick={() => setActiveTab('positions')}
          style={{
            background: activeTab === 'positions' ? 'var(--bg-panel)' : 'transparent',
            border: '1px solid ' + (activeTab === 'positions' ? 'var(--border-color)' : 'transparent'),
            borderBottom: 'none',
            borderTopLeftRadius: '8px',
            borderTopRightRadius: '8px',
            color: activeTab === 'positions' ? 'var(--color-cyan)' : 'var(--color-text-muted)',
            padding: '8px 16px',
            fontSize: '0.8rem',
            fontWeight: 600,
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            height: '34px',
            transition: 'all 0.2s ease',
            boxShadow: activeTab === 'positions' ? '0 -4px 10px rgba(0, 229, 255, 0.05)' : 'none',
            outline: 'none'
          }}
        >
          💼 Risk & Positions
        </button>
        <button 
          onClick={() => setActiveTab('system')}
          style={{
            background: activeTab === 'system' ? 'var(--bg-panel)' : 'transparent',
            border: '1px solid ' + (activeTab === 'system' ? 'var(--border-color)' : 'transparent'),
            borderBottom: 'none',
            borderTopLeftRadius: '8px',
            borderTopRightRadius: '8px',
            color: activeTab === 'system' ? 'var(--color-cyan)' : 'var(--color-text-muted)',
            padding: '8px 16px',
            fontSize: '0.8rem',
            fontWeight: 600,
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            height: '34px',
            transition: 'all 0.2s ease',
            boxShadow: activeTab === 'system' ? '0 -4px 10px rgba(0, 229, 255, 0.05)' : 'none',
            outline: 'none'
          }}
        >
          ⚙️ System Operations
        </button>
      </div>

      {/* 3. Main Workspace Area */}
      <div style={{ flexGrow: 1, overflow: 'hidden', position: 'relative' }}>
        
        {/* Tab 1: Watchlist Radar */}
        {activeTab === 'radar' && (
          <main className="main-workspace" style={{ height: '100%', overflowY: 'auto' }}>
            <WatchlistScanners 
              watchlistData={watchlistData} 
              onSelectSymbol={selectChartSymbol}
              onRemove={removeFromWatchlist}
              onAddToWatchlist={addToWatchlist}
              apiUrl={API_URL}
            />
          </main>
        )}

        {/* Tab 1b: Spike Radar candidates */}
        {activeTab === 'spikes' && (
          <main className="main-workspace" style={{ height: '100%', overflowY: 'auto' }}>
            <RadarCandidates candidates={radarCandidates} />
          </main>
        )}

        {/* Tab 2: Technical Chart */}
        {activeTab === 'chart' && (
          <main className="main-workspace" style={{ height: 'calc(100vh - 112px)', overflowY: 'hidden', display: 'flex', flexDirection: 'column', padding: '24px' }}>
            <TechnicalChart 
              selectedSymbol={selectedSymbol}
              chartInterval={chartInterval}
              onChangeInterval={setChartInterval}
              onSelectSymbol={setSelectedSymbol}
              apiUrl={API_URL}
              watchlistData={watchlistData}
            />
          </main>
        )}

        {/* Tab 3: Risk & Positions */}
        {activeTab === 'positions' && (
          <main className="main-workspace" style={{ height: '100%', overflowY: 'auto' }}>
            <MetricCards 
              margin={status.kite_margin} 
              onPanic={triggerPanic} 
            />
            <PositionsTracker 
              positions={positions}
              onSelectSymbol={selectChartSymbol}
              onModifyStopLoss={modifyStopLoss}
              onModifyTarget={modifyTarget}
              onScaleOut={scaleOutPosition}
              onExit={exitPosition}
            />
            <OrderBook 
              orders={orders} 
              onSelectSymbol={selectChartSymbol} 
              onCancelOrder={cancelOrder}
              onModifyOrder={modifyOrderParams}
            />
          </main>
        )}

        {/* Tab 4: System Operations */}
        {activeTab === 'system' && (
          <main className="main-workspace system-workspace" style={{ height: '100%', overflowY: 'auto' }}>
            <EngineControls 
              status={status}
              engineMode={engineMode}
              setEngineMode={setEngineMode}
              onToggleLogger={toggleLogger}
              onToggleEngine={toggleEngine}
              loggerLoading={loggerLoading}
              loggerAction={loggerAction}
              engineLoading={engineLoading}
            />
            <TelemetryLog logOutput={logOutput} />
          </main>
        )}

      </div>
    </div>
  );
}
