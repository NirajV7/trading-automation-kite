import React from 'react';

export default function EngineControls({ 
  status, 
  engineMode, 
  setEngineMode, 
  onToggleLogger, 
  onToggleEngine, 
  loggerLoading, 
  loggerAction,
  engineLoading 
}) {
  const isLoggerActive = status.data_logger === 'active';
  const isEngineActive = status.kite_engine !== 'stopped';

  return (
    <div className="system-controls-stack">
      
      {/* System Control Engine Panel */}
      <div className="glass-panel system-controls-panel">
        <div className="system-panel-header">
          <div>
            <h2>Engine Controls</h2>
            <p>Start, stop, and choose execution mode.</p>
          </div>
          <span className="system-mode-badge">SYS OPS</span>
        </div>
        
        <div className="system-control-list">
          {/* Data Logger Module */}
          <div className="system-control-card">
            <div className="system-control-copy">
              <span className={isLoggerActive ? 'system-status-dot active' : 'system-status-dot'} />
              <div>
                <h3>WebSocket Logger</h3>
                <p>
                {isLoggerActive ? 'Ticks streaming...' : 'Offline'}
                </p>
              </div>
            </div>
            <button 
              onClick={onToggleLogger} 
              className={isLoggerActive ? 'btn btn-crimson system-action-button' : 'btn btn-emerald system-action-button'}
              disabled={loggerLoading}
            >
              {loggerLoading ? (
                <>
                  <span className="btn-spinner"></span>
                  <span>{loggerAction === 'stop' ? 'Stopping...' : 'Starting...'}</span>
                </>
              ) : (
                <span>{isLoggerActive ? 'Stop' : 'Start'}</span>
              )}
            </button>
          </div>

          {/* Execution Core Strategy Engine */}
          <div className="system-control-card engine-card">
            <div className="system-control-top">
              <div className="system-control-copy">
                <span className={isEngineActive ? 'system-status-dot active' : 'system-status-dot'} />
                <div>
                  <h3>Execution Engine</h3>
                  <p>Mode: {status.kite_engine.toUpperCase()}</p>
                </div>
              </div>
              <button 
                onClick={onToggleEngine} 
                className={isEngineActive ? 'btn btn-crimson system-action-button' : 'btn btn-emerald system-action-button'}
                disabled={engineLoading}
              >
                {engineLoading ? (
                  <>
                    <span className="btn-spinner"></span>
                    <span>{isEngineActive ? 'Stopping...' : 'Starting...'}</span>
                  </>
                ) : (
                  <span>{isEngineActive ? 'Stop' : 'Start'}</span>
                )}
              </button>
            </div>
            
            {/* Live mode selection toggle (Only active if stopped) */}
            {!isEngineActive && (
              <div className="engine-mode-selector">
                <label className={engineMode === 'dry' ? 'active' : ''}>
                  <input 
                    type="radio" 
                    name="run_mode" 
                    value="dry" 
                    checked={engineMode === 'dry'}
                    onChange={() => setEngineMode('dry')} 
                  /> DRY
                </label>
                <label className={engineMode === 'live' ? 'active danger' : 'danger'}>
                  <input 
                    type="radio" 
                    name="run_mode" 
                    value="live" 
                    checked={engineMode === 'live'}
                    onChange={() => setEngineMode('live')}
                  /> LIVE
                </label>
              </div>
            )}
          </div>
        </div>
      </div>
      
    </div>
  );
}
