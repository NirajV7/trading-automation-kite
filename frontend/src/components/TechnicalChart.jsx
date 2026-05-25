import React, { useEffect, useRef } from 'react';
import { createChart, CrosshairMode } from 'lightweight-charts';

const toLocalTimestamp = (utcSec) => {
  const d = new Date(utcSec * 1000);
  return Date.UTC(
    d.getFullYear(),
    d.getMonth(),
    d.getDate(),
    d.getHours(),
    d.getMinutes(),
    d.getSeconds()
  ) / 1000;
};

const alignTimestamp = (timestamp, interval) => {
  const date = new Date(timestamp * 1000);
  switch (interval) {
    case 'minute':
      return Math.floor(timestamp / 60) * 60;
    case '5minute':
      return Math.floor(timestamp / 300) * 300;
    case '15minute':
      return Math.floor(timestamp / 900) * 900;
    case 'day': {
      const d = new Date(date.getFullYear(), date.getMonth(), date.getDate());
      return Math.floor(d.getTime() / 1000);
    }
    default:
      return timestamp;
  }
};

export default function TechnicalChart({ 
  selectedSymbol, 
  chartInterval, 
  onChangeInterval, 
  apiUrl, 
  watchlistData 
}) {
  const chartContainerRef = useRef(null);
  const chartRef = useRef(null);
  const seriesRef = useRef(null);
  const hasFitContentRef = useRef(false);
  const lastCandleRef = useRef(null);

  // Initialize Chart
  useEffect(() => {
    if (!chartContainerRef.current) return;
    
    const chart = createChart(chartContainerRef.current, {
      width: chartContainerRef.current.clientWidth || 600,
      height: 350,
      layout: {
        background: { type: 'solid', color: '#0c0d12' },
        textColor: '#8b949e',
      },
      grid: {
        vertLines: { color: 'rgba(255, 255, 255, 0.03)' },
        horzLines: { color: 'rgba(255, 255, 255, 0.03)' },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
      },
      rightPriceScale: {
        borderColor: 'rgba(255, 255, 255, 0.08)',
      },
      timeScale: {
        borderColor: 'rgba(255, 255, 255, 0.08)',
        timeVisible: true,
        secondsVisible: false,
      },
    });

    const candleSeries = chart.addCandlestickSeries({
      upColor: '#3fb950',
      downColor: '#f85149',
      borderUpColor: '#3fb950',
      borderDownColor: '#f85149',
      wickUpColor: '#3fb950',
      wickDownColor: '#f85149',
    });

    chartRef.current = chart;
    seriesRef.current = candleSeries;

    const handleResize = () => {
      if (chartRef.current && chartContainerRef.current) {
        chartRef.current.resize(chartContainerRef.current.clientWidth, 350);
      }
    };
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, []);

  // Fetch Historical Candles
  useEffect(() => {
    if (!selectedSymbol || !seriesRef.current) return;

    // Reset flags for new symbol/interval
    hasFitContentRef.current = false;
    lastCandleRef.current = null;

    const loadChartData = async () => {
      try {
        const res = await fetch(`${apiUrl}/api/history/${selectedSymbol}?interval=${chartInterval}&days=5`);
        const json = await res.json();
        if (json.status === 'success' && json.data && seriesRef.current) {
          const localData = json.data.map(d => ({
            ...d,
            time: toLocalTimestamp(d.time)
          }));
          seriesRef.current.setData(localData);
          if (localData.length > 0) {
            lastCandleRef.current = { ...localData[localData.length - 1] };
          }
          if (!hasFitContentRef.current) {
            chartRef.current.timeScale().fitContent();
            hasFitContentRef.current = true;
          }
        }
      } catch (e) {
        console.error("Failed to load historical chart:", e);
      }
    };

    loadChartData();
    const intervalId = setInterval(loadChartData, 10000);

    return () => clearInterval(intervalId);
  }, [selectedSymbol, chartInterval, apiUrl]);

  // Handle Live Price Ticks
  useEffect(() => {
    if (!selectedSymbol || !seriesRef.current || !watchlistData || watchlistData.length === 0) return;
    const active = watchlistData.find(item => item.symbol === selectedSymbol);
    if (active && active.ltp) {
      try {
        const nowSeconds = Math.floor(Date.now() / 1000);
        const localNow = toLocalTimestamp(nowSeconds);
        const alignedTime = alignTimestamp(localNow, chartInterval);
        
        let updateCandle;
        if (lastCandleRef.current && alignedTime === lastCandleRef.current.time) {
          updateCandle = {
            time: alignedTime,
            open: lastCandleRef.current.open,
            high: Math.max(lastCandleRef.current.high, active.ltp),
            low: Math.min(lastCandleRef.current.low, active.ltp),
            close: active.ltp
          };
        } else {
          // If we don't have a last candle or a new time interval has started
          const openPrice = lastCandleRef.current ? lastCandleRef.current.close : active.ltp;
          updateCandle = {
            time: alignedTime,
            open: openPrice,
            high: Math.max(openPrice, active.ltp),
            low: Math.min(openPrice, active.ltp),
            close: active.ltp
          };
        }
        
        seriesRef.current.update(updateCandle);
        lastCandleRef.current = updateCandle;
      } catch (e) {
        // Suppress order/timestamp sequence warning in local logs
        console.debug("Live tick chart update suppressed:", e);
      }
    }
  }, [watchlistData, selectedSymbol, chartInterval]);

  return (
    <div className="glass-panel" style={{ display: 'flex', flexDirection: 'column', gap: '12px', minHeight: '430px' }}>
      <div className="panel-header" style={{ marginBottom: '8px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span>📈 Live Technical Chart:</span>
          <span style={{ color: 'var(--color-cyan)', fontWeight: 700 }}>{selectedSymbol}</span>
        </div>
        
        {/* Timeframe selectors */}
        <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
          <button 
            onClick={() => onChangeInterval('minute')} 
            className={chartInterval === 'minute' ? 'btn btn-cyan' : 'btn'} 
            style={{ padding: '2px 8px', fontSize: '0.7rem' }}
          >
            1m
          </button>
          <button 
            onClick={() => onChangeInterval('5minute')} 
            className={chartInterval === '5minute' ? 'btn btn-cyan' : 'btn'} 
            style={{ padding: '2px 8px', fontSize: '0.7rem' }}
          >
            5m
          </button>
          <button 
            onClick={() => onChangeInterval('15minute')} 
            className={chartInterval === '15minute' ? 'btn btn-cyan' : 'btn'} 
            style={{ padding: '2px 8px', fontSize: '0.7rem' }}
          >
            15m
          </button>
          <button 
            onClick={() => onChangeInterval('day')} 
            className={chartInterval === 'day' ? 'btn btn-cyan' : 'btn'} 
            style={{ padding: '2px 8px', fontSize: '0.7rem' }}
          >
            1d
          </button>
        </div>
      </div>
      
      <div 
        ref={chartContainerRef} 
        style={{ 
          width: '100%', 
          height: '350px', 
          position: 'relative', 
          borderRadius: '8px', 
          overflow: 'hidden', 
          background: '#0c0d12', 
          border: '1px solid rgba(255,255,255,0.03)' 
        }} 
      />
    </div>
  );
}
