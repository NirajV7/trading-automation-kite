import React, { useState, useEffect } from 'react';
import MetricCards from './components/MetricCards';
import EngineControls from './components/EngineControls';
import WatchlistScanners from './components/WatchlistScanners';
import TechnicalChart from './components/TechnicalChart';
import PositionsTracker from './components/PositionsTracker';
import TelemetryLog from './components/TelemetryLog';
import OrderBook from './components/OrderBook';

const API_URL = "http://127.0.0.1:8080";

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
  const [activeTab, setActiveTab] = useState('radar'); // 'radar', 'positions', 'system'

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
  const [positions, setPositions] = useState([]);
  const [orders, setOrders] = useState([]);
  const [logOutput, setLogOutput] = useState("Connecting to FastAPI daemon...");
  const [selectedSymbol, setSelectedSymbol] = useState("RELIANCE");
  const [chartInterval, setChartInterval] = useState("5minute");

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

  // Initial sync & polling
  useEffect(() => {
    fetchStatus();
    fetchWatchlistData();
    fetchPositions();
    fetchOrders();
    fetchLogs();

    const intervalStatus = setInterval(fetchStatus, 5000);
    const intervalWatchlist = setInterval(fetchWatchlistData, 2000);
    const intervalPositions = setInterval(fetchPositions, 1500);
    const intervalOrders = setInterval(fetchOrders, 2000);
    const intervalLogs = setInterval(fetchLogs, 3000);

    return () => {
      clearInterval(intervalStatus);
      clearInterval(intervalWatchlist);
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
    try {
      await fetch(`${API_URL}/api/system/${action}`, { method: 'POST' });
      fetchStatus();
    } catch (e) {
      console.error(e);
    }
  };

  const toggleEngine = async () => {
    const action = status.kite_engine !== 'stopped' ? 'stop_engine' : 'start_engine';
    const body = action === 'start_engine' ? JSON.stringify({ mode: engineMode }) : undefined;
    try {
      await fetch(`${API_URL}/api/system/${action}`, {
        method: 'POST',
        headers: body ? { 'Content-Type': 'application/json' } : {},
        body
      });
      fetchStatus();
    } catch (e) {
      console.error(e);
    }
  };

  const stopAll = async () => {
    try {
      await fetch(`${API_URL}/api/system/stop_all`, { method: 'POST' });
      fetchStatus();
    } catch (e) {
      console.error(e);
    }
  };

  const triggerPanic = async () => {
    if (!confirm("⚠️ PANIC EXIT: Cancel all orders & square off all positions?")) return;
    try {
      const res = await fetch(`${API_URL}/api/kite/panic`, { method: 'POST' });
      const data = await res.json();
      alert(data.message);
      fetchPositions();
    } catch (e) {
      alert("Panic shutdown failed.");
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

  const modifyStopLoss = async (pos) => {
    const defaultPrice = pos.sl_price || pos.average_price;
    const newSL = prompt(`Enter new Stop Loss price for ${pos.symbol}:`, defaultPrice);
    if (newSL === null || isNaN(newSL)) return;

    try {
      const res = await fetch(`${API_URL}/api/kite/modify_sl`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          symbol: pos.symbol,
          new_sl_price: parseFloat(newSL),
          sl_order_id: pos.sl_order_id,
          quantity: pos.quantity,
          transaction_type: pos.quantity > 0 ? "SELL" : "BUY",
          product: pos.product
        })
      });
      const data = await res.json();
      if (data.status === 'success') {
        alert(`Stop Loss successfully updated to ₹${data.new_sl}`);
      } else {
        alert(`Error: ${data.message}`);
      }
      fetchPositions();
    } catch (e) {
      alert("Failed to modify stop loss.");
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
    setActiveTab('radar');
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', backgroundColor: 'var(--bg-darkest)' }}>
      {/* 1. Header Toolbar */}
      <header className="app-header">
        <div className="header-title">
          <span>🛡️</span> KITE QUANT TERMINAL
          {status.network && status.network.is_whitelisted && (
            <span style={{ fontSize: '0.6em', background: 'rgba(0, 229, 255, 0.12)', color: 'var(--color-cyan)', padding: '2px 6px', borderRadius: '4px', border: '1px solid rgba(0, 229, 255, 0.3)' }}>
              TS SECURE
            </span>
          )}
        </div>
        
        <div className="header-status">
          {/* Zerodha Authentication Banner */}
          {status.kite_needs_login ? (
            <a href={status.kite_auth_url} target="_blank" className="btn btn-crimson" style={{ textDecoration: 'none' }}>
              ⚠️ AUTHENTICATE ZERODHA
            </a>
          ) : (
            <span style={{ color: 'var(--color-emerald)', fontSize: '0.8rem', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '6px' }}>
              <span style={{ width: '8px', height: '8px', background: 'var(--color-emerald)', borderRadius: '50%' }}></span>
              KITE CONNECT SECURE
            </span>
          )}

          {/* Global Emergency Panic Switch */}
          <button onClick={triggerPanic} className="btn btn-panic" style={{ padding: '6px 16px', fontSize: '0.8rem' }}>
            ⚠️ PANIC EXIT
          </button>

          {/* System Global Shutdown Controls */}
          <button onClick={stopAll} className="btn btn-crimson">
            🛑 SHUTDOWN ALL
          </button>
        </div>
      </header>

      {/* 2. Chrome-like tab bar navigation */}
      <div className="chrome-tabs" style={{ display: 'flex', gap: '4px', background: 'var(--bg-darker)', borderBottom: '1px solid var(--border-color)', padding: '0 20px', height: '40px', alignItems: 'flex-end', WebkitAppRegion: 'no-drag' }}>
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
          📡 Radar & Charts
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
        
        {/* Tab 1: Radar & Charts */}
        {activeTab === 'radar' && (
          <main className="main-workspace" style={{ height: '100%', overflowY: 'auto' }}>
            <WatchlistScanners 
              watchlistData={watchlistData} 
              onSelectSymbol={selectChartSymbol}
              onRemove={removeFromWatchlist}
            />
            <TechnicalChart 
              selectedSymbol={selectedSymbol}
              chartInterval={chartInterval}
              onChangeInterval={setChartInterval}
              apiUrl={API_URL}
              watchlistData={watchlistData}
            />
          </main>
        )}

        {/* Tab 2: Risk & Positions */}
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
              onScaleOut={scaleOutPosition}
              onExit={exitPosition}
            />
            <OrderBook 
              orders={orders} 
              onSelectSymbol={selectChartSymbol} 
            />
          </main>
        )}

        {/* Tab 3: System Operations */}
        {activeTab === 'system' && (
          <main className="main-workspace" style={{ height: '100%', overflowY: 'auto', display: 'grid', gridTemplateColumns: '320px 1fr', gap: '20px' }}>
            <EngineControls 
              status={status}
              engineMode={engineMode}
              setEngineMode={setEngineMode}
              onToggleLogger={toggleLogger}
              onToggleEngine={toggleEngine}
              onAddToWatchlist={addToWatchlist}
              apiUrl={API_URL}
            />
            <TelemetryLog logOutput={logOutput} />
          </main>
        )}

      </div>
    </div>
  );
}
