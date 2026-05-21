import React, { useEffect, useRef } from 'react';

export default function TelemetryLog({ logOutput }) {
  const logBoxRef = useRef(null);

  // Auto-scroll to bottom of logs on update
  useEffect(() => {
    if (logBoxRef.current) {
      logBoxRef.current.scrollTop = logBoxRef.current.scrollHeight;
    }
  }, [logOutput]);

  return (
    <div className="glass-panel" style={{ flexGrow: 1, display: 'flex', flexDirection: 'column' }}>
      <div className="panel-header">
        <span>Engine Telemetry Log</span>
      </div>
      <div 
        className="log-box" 
        style={{ flexGrow: 1 }} 
        ref={logBoxRef}
      >
        {logOutput}
      </div>
    </div>
  );
}
