import React, { useState, useEffect, useRef, useMemo } from 'react';

// Client-side log parser and deduplicator
function parseAndDeduplicateLogs(rawLogs) {
  if (!rawLogs) return [];
  const lines = rawLogs.split('\n');
  const parsed = [];

  // 1. Parse raw text lines into structured objects
  for (let line of lines) {
    line = line.trim();
    if (!line) continue;

    // Pattern matches:
    // Group 1: Date (e.g. 2026-05-28 or 5-28)
    // Group 2: Time (e.g. 02:49:38)
    // Group 3: Log level (e.g. INFO, ERROR, WARNING, SUCCESS, DEBUG)
    // Group 4: Message text
    const regex = /^(?:(\d{4}-\d{2}-\d{2}|\d{1,2}-\d{1,2})\s+(\d{2}:\d{2}:\d{2}))?\s*\[(INFO|ERROR|WARNING|DEBUG|SUCCESS)\]\s*(.*)$/i;
    const match = line.match(regex);

    if (match) {
      const date = match[1] || '';
      const time = match[2] || '';
      const level = match[3].toUpperCase();
      const message = match[4].trim();

      parsed.push({
        date,
        time,
        timestamp: time || (date ? `${date}` : ''),
        level,
        message,
        raw: line
      });
    } else {
      // Fallback for non-standard output
      parsed.push({
        date: '',
        time: '',
        timestamp: '',
        level: line.includes('ERROR') ? 'ERROR' : 'INFO',
        message: line,
        raw: line
      });
    }
  }

  // 2. Sliding window deduplication (15 lines window)
  const result = [];
  for (const item of parsed) {
    let duplicateIndex = -1;
    const searchStart = Math.max(0, result.length - 15);
    for (let i = searchStart; i < result.length; i++) {
      if (result[i].message === item.message && result[i].level === item.level) {
        duplicateIndex = i;
        break;
      }
    }

    if (duplicateIndex !== -1) {
      // Duplicate message found in sliding window.
      // If new item contains a timestamp but existing doesn't, enrich the existing one.
      const existing = result[duplicateIndex];
      if (item.timestamp && !existing.timestamp) {
        existing.date = item.date;
        existing.time = item.time;
        existing.timestamp = item.timestamp;
      }
      // Skip appending the duplicate row
    } else {
      result.push(item);
    }
  }

  return result;
}

export default function TelemetryLog({ logOutput }) {
  const [filterText, setFilterText] = useState('');
  const [levelFilter, setLevelFilter] = useState('ALL');
  const logBoxRef = useRef(null);

  // Parse and cache logs when logOutput updates
  const parsedLogs = useMemo(() => {
    return parseAndDeduplicateLogs(logOutput);
  }, [logOutput]);

  // Filter logs locally based on user search and dropdown level
  const filteredLogs = useMemo(() => {
    return parsedLogs.filter(item => {
      // Level Filter
      if (levelFilter !== 'ALL' && item.level !== levelFilter) {
        return false;
      }
      // Text Search Filter
      if (filterText.trim()) {
        const query = filterText.toLowerCase();
        const msgMatch = item.message.toLowerCase().includes(query);
        const levelMatch = item.level.toLowerCase().includes(query);
        const timeMatch = item.timestamp.toLowerCase().includes(query);
        return msgMatch || levelMatch || timeMatch;
      }
      return true;
    });
  }, [parsedLogs, filterText, levelFilter]);

  // Auto-scroll to bottom of logs on update (only if search filters are not active to avoid disrupting user reading)
  useEffect(() => {
    if (logBoxRef.current && !filterText && levelFilter === 'ALL') {
      logBoxRef.current.scrollTop = logBoxRef.current.scrollHeight;
    }
  }, [filteredLogs, filterText, levelFilter]);

  const levelCounts = useMemo(() => {
    return parsedLogs.reduce((acc, item) => {
      acc[item.level] = (acc[item.level] || 0) + 1;
      return acc;
    }, {});
  }, [parsedLogs]);

  return (
    <div className="glass-panel telemetry-panel">
      
      {/* Structured Telemetry Log Header with Filter controls */}
      <div className="telemetry-header">
        <div>
          <h2>Engine Telemetry Log</h2>
          <p>Live backend events, startup progress, warnings, and errors.</p>
        </div>
        
        {/* Local Search and Filter controls */}
        <div className="telemetry-toolbar">
          <input 
            type="text" 
            className="input-dark telemetry-search" 
            placeholder="Search log messages..." 
            value={filterText}
            onChange={(e) => setFilterText(e.target.value)}
          />
          <select
            className="telemetry-select"
            value={levelFilter}
            onChange={(e) => setLevelFilter(e.target.value)}
          >
            <option value="ALL">ALL LEVELS</option>
            <option value="INFO">INFO</option>
            <option value="ERROR">ERROR</option>
            <option value="WARNING">WARNING</option>
            <option value="SUCCESS">SUCCESS</option>
          </select>
        </div>
      </div>

      <div className="telemetry-stats">
        <div><span>Total</span><strong>{parsedLogs.length}</strong></div>
        <div><span>Info</span><strong>{levelCounts.INFO || 0}</strong></div>
        <div><span>Warnings</span><strong>{levelCounts.WARNING || 0}</strong></div>
        <div><span>Errors</span><strong>{levelCounts.ERROR || 0}</strong></div>
      </div>

      {/* Styled Structured Log Console Container */}
      <div 
        className="log-container-light telemetry-log-container" 
        ref={logBoxRef}
      >
        {filteredLogs.length === 0 ? (
          <div className="telemetry-empty-state">
            <strong>No matching log entries</strong>
            <span>Change search text or level filter.</span>
          </div>
        ) : (
          <div className="log-rows-list">
            {filteredLogs.map((item, idx) => (
              <div className="log-entry-row" key={idx}>
                <span className="log-entry-time">{item.timestamp || '--:--:--'}</span>
                <span className={`log-entry-badge log-badge-${item.level.toLowerCase()}`}>
                  {item.level}
                </span>
                <span className="log-entry-message">{item.message}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Footer Info showing count */}
      <div className="telemetry-footer">
        <span>Showing {filteredLogs.length} of {parsedLogs.length} entries</span>
        {(filterText || levelFilter !== 'ALL') && <button onClick={() => { setFilterText(''); setLevelFilter('ALL'); }}>Clear Filter</button>}
      </div>
    </div>
  );
}
