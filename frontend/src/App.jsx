import React, { useState, useEffect } from 'react';
import MetricCards from './components/MetricCards';
import EngineControls from './components/EngineControls';
import WatchlistScanners from './components/WatchlistScanners';
import TechnicalChart from './components/TechnicalChart';
import PositionsTracker from './components/PositionsTracker';
import TelemetryLog from './components/TelemetryLog';

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
    fetchLogs();

    const intervalStatus = setInterval(fetchStatus, 5000);
    const intervalWatchlist = setInterval(fetchWatchlistData, 2000);
    const intervalPositions = setInterval(fetchPositions, 1500);
    const intervalLogs = setInterval(fetchLogs, 3000);

    return () => {
      clearInterval(intervalStatus);
      clearInterval(intervalWatchlist);
      clearInterval(intervalPositions);
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
  };

  return (
    <>
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

          {/* System Global Shutdown Controls */}
          <button onClick={stopAll} className="btn btn-crimson">
            🛑 SHUTDOWN ALL
          </button>
        </div>
      </header>

      {/* 2. Main Terminal Layout */}
      <div className="app-container">
        
        {/* Left Sidebar: Controls & Log stream */}
        <aside className="sidebar">
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
        </aside>

        {/* Right Workspace Area */}
        <main className="main-workspace">
          <MetricCards 
            margin={status.kite_margin} 
            onPanic={triggerPanic} 
          />

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

          <PositionsTracker 
            positions={positions}
            onSelectSymbol={selectChartSymbol}
            onModifyStopLoss={modifyStopLoss}
            onScaleOut={scaleOutPosition}
            onExit={exitPosition}
          />
        </main>

      </div>
    </>
  );
}
