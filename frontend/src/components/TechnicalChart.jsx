import React, { useEffect, useMemo, useRef, useState } from 'react';
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

const formatChartTime = (time, interval) => {
  const timestamp = typeof time === 'object'
    ? Date.UTC(time.year, time.month - 1, time.day) / 1000
    : time;
  const d = new Date(timestamp * 1000);

  if (interval === 'day') {
    return `${d.getUTCDate()} ${d.toLocaleString('en-US', { month: 'short', timeZone: 'UTC' })}`;
  }

  let hours = d.getUTCHours();
  const minutes = d.getUTCMinutes();
  const suffix = hours >= 12 ? 'PM' : 'AM';
  hours = hours % 12 || 12;
  return `${hours}:${String(minutes).padStart(2, '0')} ${suffix}`;
};

const calculateEma = (candles, period = 20) => {
  if (!candles.length) return [];
  const multiplier = 2 / (period + 1);
  let ema = candles[0].close;

  return candles.map((candle, index) => {
    ema = index === 0 ? candle.close : ((candle.close - ema) * multiplier) + ema;
    return { time: candle.time, value: ema };
  });
};

const calculateVwap = (candles) => {
  let cumulativePv = 0;
  let cumulativeVolume = 0;
  let activeDay = null;

  return candles
    .map((candle) => {
      const date = new Date(candle.time * 1000);
      const dayKey = `${date.getUTCFullYear()}-${date.getUTCMonth()}-${date.getUTCDate()}`;
      if (dayKey !== activeDay) {
        activeDay = dayKey;
        cumulativePv = 0;
        cumulativeVolume = 0;
      }

      const volume = Number(candle.volume || 0);
      if (volume <= 0) return null;

      const typicalPrice = (Number(candle.high) + Number(candle.low) + Number(candle.close)) / 3;
      cumulativePv += typicalPrice * volume;
      cumulativeVolume += volume;
      return { time: candle.time, value: cumulativePv / cumulativeVolume };
    })
    .filter(Boolean);
};

const drawingColor = {
  hline: '#2563eb',
  vline: '#475569',
  trend: '#f59e0b',
  selected: '#0f172a'
};

const distanceToSegment = (px, py, x1, y1, x2, y2) => {
  const dx = x2 - x1;
  const dy = y2 - y1;
  if (dx === 0 && dy === 0) return Math.hypot(px - x1, py - y1);
  const t = Math.max(0, Math.min(1, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)));
  const x = x1 + t * dx;
  const y = y1 + t * dy;
  return Math.hypot(px - x, py - y);
};

export default function TechnicalChart({ 
  selectedSymbol, 
  chartInterval, 
  onChangeInterval, 
  onSelectSymbol,
  apiUrl, 
  watchlistData 
}) {
  const chartContainerRef = useRef(null);
  const searchRef = useRef(null);
  const chartRef = useRef(null);
  const seriesRef = useRef(null);
  const vwapSeriesRef = useRef(null);
  const emaSeriesRef = useRef(null);
  const ltpLineRef = useRef(null);
  const candleDataRef = useRef([]);
  const indicatorDataRef = useRef({ vwap: [], ema: [] });
  const hasFitContentRef = useRef(false);
  const lastCandleRef = useRef(null);
  const [showVwap, setShowVwap] = useState(true);
  const [showEma, setShowEma] = useState(true);
  const [showLtp, setShowLtp] = useState(true);
  const [lastOhlc, setLastOhlc] = useState(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState([]);
  const [drawingTool, setDrawingTool] = useState('cursor');
  const [drawMenuOpen, setDrawMenuOpen] = useState(false);
  const [drawings, setDrawings] = useState([]);
  const [selectedDrawingId, setSelectedDrawingId] = useState(null);
  const [pendingTrendPoint, setPendingTrendPoint] = useState(null);
  const [dragState, setDragState] = useState(null);
  const [overlayVersion, setOverlayVersion] = useState(0);

  const activeInstrument = useMemo(() => {
    return (watchlistData || []).find(item => item.symbol === selectedSymbol);
  }, [watchlistData, selectedSymbol]);

  const quoteChange = Number(activeInstrument?.change ?? 0);
  const isPositive = quoteChange >= 0;
  const intervalOptions = [
    { label: '1m', value: 'minute' },
    { label: '5m', value: '5minute' },
    { label: '15m', value: '15minute' },
    { label: '1D', value: 'day' },
  ];

  const watchlistSymbols = useMemo(() => {
    return Array.from(new Set((watchlistData || []).map(item => item.symbol).filter(Boolean))).sort();
  }, [watchlistData]);

  const drawingStorageKey = useMemo(() => (
    `kite-chart-drawings:${selectedSymbol}:${chartInterval}`
  ), [selectedSymbol, chartInterval]);

  const applyIndicatorData = (candles) => {
    const vwapData = calculateVwap(candles);
    const emaData = calculateEma(candles, 20);
    indicatorDataRef.current = { vwap: vwapData, ema: emaData };
    if (vwapSeriesRef.current) vwapSeriesRef.current.setData(showVwap ? vwapData : []);
    if (emaSeriesRef.current) emaSeriesRef.current.setData(showEma ? emaData : []);
  };

  const fitChartToCurrentSymbol = () => {
    if (!chartRef.current || !seriesRef.current) return;
    chartRef.current.priceScale('right').applyOptions({ autoScale: true });
    chartRef.current.timeScale().fitContent();
    requestAnimationFrame(() => {
      if (!chartRef.current) return;
      chartRef.current.priceScale('right').applyOptions({ autoScale: true });
      chartRef.current.timeScale().fitContent();
    });
  };

  const bumpOverlay = () => setOverlayVersion((version) => version + 1);

  const chartPointToValue = (clientX, clientY) => {
    if (!chartContainerRef.current || !chartRef.current || !seriesRef.current) return null;
    const rect = chartContainerRef.current.getBoundingClientRect();
    const x = clientX - rect.left;
    const y = clientY - rect.top;
    const time = chartRef.current.timeScale().coordinateToTime(x);
    const price = seriesRef.current.coordinateToPrice(y);
    if (time === null || price === null || price === undefined) return null;
    return { x, y, time, price: Number(price) };
  };

  const setActiveDrawingTool = (tool) => {
    setDrawingTool(tool);
    setDrawMenuOpen(false);
    if (tool !== 'trend') setPendingTrendPoint(null);
  };

  const getRenderableDrawings = () => {
    const width = chartContainerRef.current?.clientWidth || 0;
    const height = chartContainerRef.current?.clientHeight || 0;
    if (!chartRef.current || !seriesRef.current || width <= 0 || height <= 0) return [];

    return drawings.map((drawing) => {
      if (drawing.type === 'hline') {
        const y = seriesRef.current.priceToCoordinate(drawing.price);
        if (y === null) return null;
        return { ...drawing, x1: 0, y1: y, x2: width, y2: y };
      }

      if (drawing.type === 'vline') {
        const x = chartRef.current.timeScale().timeToCoordinate(drawing.time);
        if (x === null) return null;
        return { ...drawing, x1: x, y1: 0, x2: x, y2: height };
      }

      const x1 = chartRef.current.timeScale().timeToCoordinate(drawing.points[0].time);
      const y1 = seriesRef.current.priceToCoordinate(drawing.points[0].price);
      const x2 = chartRef.current.timeScale().timeToCoordinate(drawing.points[1].time);
      const y2 = seriesRef.current.priceToCoordinate(drawing.points[1].price);
      if ([x1, y1, x2, y2].some((value) => value === null)) return null;
      return { ...drawing, x1, y1, x2, y2 };
    }).filter(Boolean);
  };

  const selectNearestDrawing = (x, y) => {
    const renderable = getRenderableDrawings();
    let best = null;
    for (const drawing of renderable) {
      const distance = distanceToSegment(x, y, drawing.x1, drawing.y1, drawing.x2, drawing.y2);
      if (distance <= 10 && (!best || distance < best.distance)) {
        best = { id: drawing.id, distance };
      }
    }
    setSelectedDrawingId(best?.id || null);
    return best?.id || null;
  };

  // Initialize Chart
  useEffect(() => {
    if (!chartContainerRef.current) return;
    
    const chart = createChart(chartContainerRef.current, {
      width: chartContainerRef.current.clientWidth || 600,
      height: chartContainerRef.current.clientHeight || 500,
      layout: {
        background: { type: 'solid', color: '#ffffff' },
        textColor: '#475569',
        fontFamily: 'Inter, -apple-system, BlinkMacSystemFont, sans-serif',
      },
      grid: {
        vertLines: { color: 'rgba(148, 163, 184, 0.16)' },
        horzLines: { color: 'rgba(148, 163, 184, 0.16)' },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: {
          color: 'rgba(15, 23, 42, 0.28)',
          width: 1,
          style: 2,
          labelBackgroundColor: '#0f172a',
        },
        horzLine: {
          color: 'rgba(15, 23, 42, 0.28)',
          width: 1,
          style: 2,
          labelBackgroundColor: '#0f172a',
        },
      },
      rightPriceScale: {
        borderColor: '#e2e8f0',
        scaleMargins: {
          top: 0.12,
          bottom: 0.12,
        },
      },
      timeScale: {
        borderColor: '#e2e8f0',
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 10,
        barSpacing: 10,
        tickMarkFormatter: (time) => formatChartTime(time, chartInterval),
      },
      localization: {
        timeFormatter: (time) => formatChartTime(time, chartInterval),
      },
      handleScroll: {
        mouseWheel: true,
        pressedMouseMove: true,
        horzTouchDrag: true,
        vertTouchDrag: true,
      },
      handleScale: {
        axisPressedMouseMove: true,
        mouseWheel: true,
        pinch: true,
      },
    });

    const candleSeries = chart.addCandlestickSeries({
      upColor: '#00b87c',
      downColor: '#f43f5e',
      borderUpColor: '#00b87c',
      borderDownColor: '#f43f5e',
      wickUpColor: '#00b87c',
      wickDownColor: '#f43f5e',
      priceLineVisible: false,
      lastValueVisible: true,
    });

    const vwapSeries = chart.addLineSeries({
      color: '#2563eb',
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: true,
      title: 'VWAP',
    });

    const emaSeries = chart.addLineSeries({
      color: '#f59e0b',
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: true,
      title: 'EMA 20',
    });

    chartRef.current = chart;
    seriesRef.current = candleSeries;
    vwapSeriesRef.current = vwapSeries;
    emaSeriesRef.current = emaSeries;

    // Use ResizeObserver for perfect dynamic window stretching (like TradingView)
    const resizeObserver = new ResizeObserver((entries) => {
      if (entries.length === 0 || !chartRef.current) return;
      const { width, height } = entries[0].contentRect;
      chartRef.current.resize(width, height);
      bumpOverlay();
    });
    resizeObserver.observe(chartContainerRef.current);

    const handleVisibleRangeChange = () => bumpOverlay();
    chart.timeScale().subscribeVisibleLogicalRangeChange(handleVisibleRangeChange);

    return () => {
      chart.timeScale().unsubscribeVisibleLogicalRangeChange(handleVisibleRangeChange);
      resizeObserver.disconnect();
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
      vwapSeriesRef.current = null;
      emaSeriesRef.current = null;
    };
  }, [chartInterval]);

  useEffect(() => {
    try {
      const saved = localStorage.getItem(drawingStorageKey);
      setDrawings(saved ? JSON.parse(saved) : []);
    } catch (e) {
      console.debug("Failed to load chart drawings:", e);
      setDrawings([]);
    }
    setSelectedDrawingId(null);
    setPendingTrendPoint(null);
    setDrawingTool('cursor');
  }, [drawingStorageKey]);

  useEffect(() => {
    try {
      localStorage.setItem(drawingStorageKey, JSON.stringify(drawings));
    } catch (e) {
      console.debug("Failed to save chart drawings:", e);
    }
    bumpOverlay();
  }, [drawings, drawingStorageKey]);

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
          candleDataRef.current = localData;
          seriesRef.current.setData(localData);
          applyIndicatorData(localData);
          if (localData.length > 0) {
            lastCandleRef.current = { ...localData[localData.length - 1] };
            setLastOhlc({ ...localData[localData.length - 1] });
          }
          if (!hasFitContentRef.current) {
            fitChartToCurrentSymbol();
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
        setLastOhlc(updateCandle);

        const candles = [...candleDataRef.current];
        const lastIndex = candles.length - 1;
        if (lastIndex >= 0 && candles[lastIndex].time === updateCandle.time) {
          candles[lastIndex] = { ...candles[lastIndex], ...updateCandle };
        } else {
          candles.push(updateCandle);
        }
        candleDataRef.current = candles;
        applyIndicatorData(candles);
      } catch (e) {
        // Suppress order/timestamp sequence warning in local logs
        console.debug("Live tick chart update suppressed:", e);
      }
    }
  }, [watchlistData, selectedSymbol, chartInterval]);

  // Keep only LTP as a horizontal reference; VWAP/EMA render as continuous overlay series.
  useEffect(() => {
    if (!seriesRef.current) return;

    if (ltpLineRef.current) {
      try {
        seriesRef.current.removePriceLine(ltpLineRef.current);
      } catch (e) {
        console.debug("Price line cleanup skipped:", e);
      }
      ltpLineRef.current = null;
    }

    if (!showLtp || !activeInstrument?.ltp) return;

    ltpLineRef.current = seriesRef.current.createPriceLine({
      price: Number(activeInstrument.ltp),
      color: '#0f172a',
      lineWidth: 2,
      lineStyle: 0,
      axisLabelVisible: true,
      title: 'LTP',
    });
  }, [activeInstrument, showLtp]);

  useEffect(() => {
    if (vwapSeriesRef.current) {
      vwapSeriesRef.current.setData(showVwap ? indicatorDataRef.current.vwap : []);
    }
    if (emaSeriesRef.current) {
      emaSeriesRef.current.setData(showEma ? indicatorDataRef.current.ema : []);
    }
  }, [showVwap, showEma]);

  useEffect(() => {
    if (!searchQuery.trim()) {
      setSearchResults([]);
      return;
    }

    const timer = setTimeout(async () => {
      try {
        const res = await fetch(`${apiUrl}/api/search?q=${searchQuery}`);
        const data = await res.json();
        setSearchResults(data || []);
      } catch (e) {
        console.error("Chart symbol search failed:", e);
      }
    }, 220);

    return () => clearTimeout(timer);
  }, [searchQuery, apiUrl]);

  useEffect(() => {
    function handleClickOutside(event) {
      if (searchRef.current && !searchRef.current.contains(event.target)) {
        setSearchResults([]);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  useEffect(() => {
    if (!chartRef.current) return;
    chartRef.current.applyOptions({
      watermark: {
        visible: true,
        text: selectedSymbol || '',
        color: 'rgba(15, 23, 42, 0.045)',
        fontSize: 84,
        horzAlign: 'center',
        vertAlign: 'center',
      },
    });
  }, [selectedSymbol]);

  const chooseSymbol = (symbol) => {
    if (!symbol || symbol === selectedSymbol) return;
    if (onSelectSymbol) onSelectSymbol(symbol);
    setSearchQuery('');
    setSearchResults([]);
  };

  const deleteSelectedDrawing = () => {
    if (!selectedDrawingId) {
      setDrawingTool('delete');
      setDrawMenuOpen(false);
      return;
    }
    setDrawings((items) => items.filter((item) => item.id !== selectedDrawingId));
    setSelectedDrawingId(null);
    setDrawingTool('cursor');
    setDrawMenuOpen(false);
  };

  const startDrawingDrag = (event, drawing) => {
    event.preventDefault();
    event.stopPropagation();
    const point = chartPointToValue(event.clientX, event.clientY);
    if (!point) return;
    setSelectedDrawingId(drawing.id);
    setDrawingTool('cursor');
    setDragState({
      id: drawing.id,
      startPoint: point,
      original: drawing,
    });
  };

  const clearDrawings = () => {
    if (drawings.length === 0) return;
    if (!confirm(`Clear ${drawings.length} drawing${drawings.length === 1 ? '' : 's'} for ${selectedSymbol} ${chartInterval}?`)) return;
    setDrawings([]);
    setSelectedDrawingId(null);
    setPendingTrendPoint(null);
    setDrawingTool('cursor');
  };

  const handleChartOverlayClick = (event) => {
    if (dragState) return;
    if (drawingTool === 'cursor') return;
    const point = chartPointToValue(event.clientX, event.clientY);
    if (!point) return;

    if (drawingTool === 'delete') {
      selectNearestDrawing(point.x, point.y);
      return;
    }

    const id = `${drawingTool}-${Date.now()}`;

    if (drawingTool === 'hline') {
      setDrawings((items) => [...items, { id, type: 'hline', price: point.price }]);
      setSelectedDrawingId(id);
      setDrawingTool('cursor');
      setDrawMenuOpen(false);
      return;
    }

    if (drawingTool === 'vline') {
      setDrawings((items) => [...items, { id, type: 'vline', time: point.time }]);
      setSelectedDrawingId(id);
      setDrawingTool('cursor');
      setDrawMenuOpen(false);
      return;
    }

    if (drawingTool === 'trend') {
      if (!pendingTrendPoint) {
        setPendingTrendPoint({ time: point.time, price: point.price });
        return;
      }

      setDrawings((items) => [
        ...items,
        {
          id,
          type: 'trend',
          points: [
            { time: pendingTrendPoint.time, price: pendingTrendPoint.price },
            { time: point.time, price: point.price }
          ]
        }
      ]);
      setSelectedDrawingId(id);
      setPendingTrendPoint(null);
      setDrawingTool('cursor');
      setDrawMenuOpen(false);
    }
  };

  useEffect(() => {
    if (!dragState) return undefined;

    const handleMove = (event) => {
      const point = chartPointToValue(event.clientX, event.clientY);
      if (!point) return;

      setDrawings((items) => items.map((drawing) => {
        if (drawing.id !== dragState.id) return drawing;
        const deltaX = point.x - dragState.startPoint.x;
        const deltaY = point.y - dragState.startPoint.y;

        if (dragState.original.type === 'hline') {
          const nextPrice = seriesRef.current.coordinateToPrice(dragState.original.y1 + deltaY);
          return nextPrice === null || nextPrice === undefined
            ? drawing
            : { ...drawing, price: Number(nextPrice) };
        }

        if (dragState.original.type === 'vline') {
          const nextTime = chartRef.current.timeScale().coordinateToTime(dragState.original.x1 + deltaX);
          return nextTime === null ? drawing : { ...drawing, time: nextTime };
        }

        const movedPoints = dragState.original.points.map((anchor, index) => {
          const sourceX = index === 0 ? dragState.original.x1 : dragState.original.x2;
          const sourceY = index === 0 ? dragState.original.y1 : dragState.original.y2;
          const nextTime = chartRef.current.timeScale().coordinateToTime(sourceX + deltaX);
          const nextPrice = seriesRef.current.coordinateToPrice(sourceY + deltaY);
          return {
            time: nextTime ?? anchor.time,
            price: nextPrice === null || nextPrice === undefined ? anchor.price : Number(nextPrice),
          };
        });

        return {
          ...drawing,
          points: movedPoints,
        };
      }));
    };

    const handleUp = () => setDragState(null);

    document.addEventListener('mousemove', handleMove);
    document.addEventListener('mouseup', handleUp);
    return () => {
      document.removeEventListener('mousemove', handleMove);
      document.removeEventListener('mouseup', handleUp);
    };
  }, [dragState]);

  useEffect(() => {
    const handleDrawingDeleteKey = (event) => {
      if (!selectedDrawingId) return;
      const target = event.target;
      const isTyping = target?.tagName === 'INPUT'
        || target?.tagName === 'TEXTAREA'
        || target?.isContentEditable;
      if (isTyping) return;
      if (event.key !== 'Delete' && event.key !== 'Backspace') return;
      event.preventDefault();
      setDrawings((items) => items.filter((item) => item.id !== selectedDrawingId));
      setSelectedDrawingId(null);
      setDrawingTool('cursor');
      setDrawMenuOpen(false);
    };

    document.addEventListener('keydown', handleDrawingDeleteKey);
    return () => document.removeEventListener('keydown', handleDrawingDeleteKey);
  }, [selectedDrawingId]);

  const renderableDrawings = useMemo(() => getRenderableDrawings(), [drawings, overlayVersion]);
  const pendingTrendAnchor = useMemo(() => {
    if (!pendingTrendPoint || !chartRef.current || !seriesRef.current) return null;
    const x = chartRef.current.timeScale().timeToCoordinate(pendingTrendPoint.time);
    const y = seriesRef.current.priceToCoordinate(pendingTrendPoint.price);
    if (x === null || y === null) return null;
    return { x, y };
  }, [pendingTrendPoint, overlayVersion]);

  return (
    <div className="glass-panel tv-chart-panel">
      <div className="tv-chart-header">
        <div className="tv-symbol-block">
          <div className="tv-symbol-title-row">
            <div>
              <span className="tv-eyebrow">NSE Equity Chart</span>
              <h2>{selectedSymbol}</h2>
            </div>
            <div className="tv-symbol-picker" ref={searchRef}>
              <input
                className="input-dark"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Change symbol..."
              />
              {searchResults.length > 0 && (
                <div className="tv-symbol-results">
                  {searchResults.map((item) => (
                    <button key={item.ticker} onClick={() => chooseSymbol(item.ticker)}>
                      <strong>{item.ticker}</strong>
                      <span>{item.name || 'NSE Equity'}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
          <div className="tv-live-quote">
            <strong>{activeInstrument?.ltp ? `₹${activeInstrument.ltp.toFixed(2)}` : '—'}</strong>
            <span className={isPositive ? 'text-up' : 'text-down'}>
              {isPositive ? '+' : ''}{quoteChange.toFixed(2)}%
            </span>
          </div>
        </div>
        
        <div className="tv-toolbar">
          <div className="tv-timeframe-tabs">
            {intervalOptions.map((option) => (
              <button
                key={option.value}
                onClick={() => onChangeInterval(option.value)}
                className={chartInterval === option.value ? 'active' : ''}
              >
                {option.label}
              </button>
            ))}
          </div>
          <div className="tv-drawing-menu">
            <button
              className={drawingTool === 'cursor' ? 'tv-tool-button' : 'tv-tool-button active'}
              onClick={() => setDrawMenuOpen(prev => !prev)}
            >
              Draw: {pendingTrendPoint ? 'Trend 2nd' : drawingTool === 'cursor' ? 'Cursor' : drawingTool.toUpperCase()}
            </button>
            {drawMenuOpen && (
              <div className="tv-drawing-dropdown">
                <button className={drawingTool === 'cursor' ? 'active' : ''} onClick={() => setActiveDrawingTool('cursor')}>Cursor</button>
                <button className={drawingTool === 'hline' ? 'active' : ''} onClick={() => setActiveDrawingTool('hline')}>Horizontal line</button>
                <button className={drawingTool === 'vline' ? 'active' : ''} onClick={() => setActiveDrawingTool('vline')}>Vertical line</button>
                <button className={drawingTool === 'trend' ? 'active' : ''} onClick={() => setActiveDrawingTool('trend')}>Trend line</button>
                <button className={drawingTool === 'delete' ? 'active danger' : 'danger'} onClick={() => setActiveDrawingTool('delete')}>Select line</button>
                <button className="danger" onClick={deleteSelectedDrawing}>Delete selected</button>
                <button className="danger" onClick={clearDrawings}>Clear current</button>
              </div>
            )}
          </div>
          <button className={showVwap ? 'tv-tool-button active' : 'tv-tool-button'} onClick={() => setShowVwap(prev => !prev)}>
            VWAP
          </button>
          <button className={showEma ? 'tv-tool-button active' : 'tv-tool-button'} onClick={() => setShowEma(prev => !prev)}>
            EMA 20
          </button>
          <button className={showLtp ? 'tv-tool-button active' : 'tv-tool-button'} onClick={() => setShowLtp(prev => !prev)}>
            LTP
          </button>
          <button className="tv-tool-button" onClick={() => chartRef.current?.timeScale().fitContent()}>
            Fit
          </button>
        </div>
      </div>

      {watchlistSymbols.length > 0 && (
        <div className="tv-watchlist-chips">
          <span>Watchlist</span>
          {watchlistSymbols.map((symbol) => (
            <button
              key={symbol}
              className={symbol === selectedSymbol ? 'active' : ''}
              onClick={() => chooseSymbol(symbol)}
            >
              {symbol}
            </button>
          ))}
        </div>
      )}

      <div className="tv-market-strip">
        <div><span>Open</span><strong>{lastOhlc ? `₹${lastOhlc.open.toFixed(2)}` : '—'}</strong></div>
        <div><span>High</span><strong>{lastOhlc ? `₹${lastOhlc.high.toFixed(2)}` : '—'}</strong></div>
        <div><span>Low</span><strong>{lastOhlc ? `₹${lastOhlc.low.toFixed(2)}` : '—'}</strong></div>
        <div><span>Close</span><strong>{lastOhlc ? `₹${lastOhlc.close.toFixed(2)}` : '—'}</strong></div>
        <div><span>VWAP 5m</span><strong>{activeInstrument?.m5_vwap ? `₹${activeInstrument.m5_vwap.toFixed(2)}` : '—'}</strong></div>
        <div><span>RSI 5m</span><strong>{activeInstrument?.m5_rsi ? activeInstrument.m5_rsi.toFixed(1) : '—'}</strong></div>
      </div>
      
      <div 
        ref={chartContainerRef} 
        className="tv-chart-canvas"
        onClick={handleChartOverlayClick}
        onWheel={bumpOverlay}
        onMouseUp={bumpOverlay}
      >
        <svg className="tv-drawing-overlay">
          {renderableDrawings.map((drawing) => {
            const selected = drawing.id === selectedDrawingId;
            const color = selected ? drawingColor.selected : drawingColor[drawing.type];
            return (
              <g key={drawing.id}>
                <line
                  x1={drawing.x1}
                  y1={drawing.y1}
                  x2={drawing.x2}
                  y2={drawing.y2}
                  stroke={color}
                  strokeWidth={selected ? 3 : 2}
                  strokeDasharray={drawing.type === 'vline' ? '5 5' : '0'}
                  className="tv-drawing-line"
                  onMouseDown={(event) => {
                    if (drawingTool !== 'delete') startDrawingDrag(event, drawing);
                  }}
                  onClick={(event) => {
                    event.stopPropagation();
                    if (dragState) return;
                    if (drawingTool === 'delete') {
                      setDrawings((items) => items.filter((item) => item.id !== drawing.id));
                      setSelectedDrawingId(null);
                      setDrawingTool('cursor');
                    } else {
                      setSelectedDrawingId(drawing.id);
                    }
                  }}
                />
                {selected && (
                  <>
                    <circle cx={drawing.x1} cy={drawing.y1} r="4" className="tv-drawing-anchor" />
                    <circle cx={drawing.x2} cy={drawing.y2} r="4" className="tv-drawing-anchor" />
                  </>
                )}
              </g>
            );
          })}
          {pendingTrendAnchor && (
            <circle cx={pendingTrendAnchor.x} cy={pendingTrendAnchor.y} r="5" className="tv-pending-anchor" />
          )}
        </svg>
        <div className="tv-chart-loading-note">Drag to pan • Mouse wheel to zoom • VWAP/EMA are continuous overlays</div>
      </div>
    </div>
  );
}
