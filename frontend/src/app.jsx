import React, { useState, useEffect } from 'react';

export default function App() {
  const [telemetry, setTelemetry] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [activeTab, setActiveTab] = useState('dashboard');

  const [newPosition, setNewPosition] = useState({ type: 'Put Spread', strike: '', credit: '' });
  const [tradeAnalysis, setTradeAnalysis] = useState(null);
  const [analyzingTrade, setAnalyzingTrade] = useState(false);

  // Trade History & Backtest state
  const [tradeHistory, setTradeHistory] = useState(null);
  const [backtestResult, setBacktestResult] = useState(null);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [backtestLoading, setBacktestLoading] = useState(false);
  const [historyError, setHistoryError] = useState(null);

  const uploadTradeHistory = async (file) => {
    setHistoryLoading(true);
    setHistoryError(null);
    const form = new FormData();
    form.append('file', file);
    try {
      const res = await fetch('http://127.0.0.1:8000/api/trade-history/upload', { method: 'POST', body: form });
      if (!res.ok) throw new Error(await res.text());
      setTradeHistory(await res.json());
    } catch (err) {
      setHistoryError(err.message || 'Upload failed');
    } finally {
      setHistoryLoading(false);
    }
  };

  const runBacktest = async (file) => {
    setBacktestLoading(true);
    setHistoryError(null);
    const form = new FormData();
    form.append('file', file);
    try {
      const res = await fetch('http://127.0.0.1:8000/api/trade-history/backtest', { method: 'POST', body: form });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      setTradeHistory({ stats: data.trade_stats, spreads: [] });
      setBacktestResult(data.backtest);
    } catch (err) {
      setHistoryError(err.message || 'Backtest failed');
    } finally {
      setBacktestLoading(false);
    }
  };

  const [selectedFile, setSelectedFile] = useState(null);

  const fetchTelemetry = async () => {
    try {
      const response = await fetch('http://127.0.0.1:8000/api/telemetry');
      if (!response.ok) throw new Error("Backend server not responding");
      const data = await response.json();
      setTelemetry(data);
      setError(null);
    } catch (err) {
      setError("Failed to connect to Quant Engine. Is the FastAPI server running?");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchTelemetry();
    const interval = setInterval(fetchTelemetry, 30000);
    return () => clearInterval(interval);
  }, []);

  // CRUD: Add Position to Database
  const handleAddPosition = async (e) => {
    e.preventDefault();
    if (!newPosition.strike || !newPosition.credit) return;

    try {
      await fetch('http://127.0.0.1:8000/api/positions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          type: newPosition.type,
          strike: parseFloat(newPosition.strike),
          credit: parseFloat(newPosition.credit)
        })
      });
      setNewPosition({ type: 'Put Spread', strike: '', credit: '' });
      fetchTelemetry(); // Instantly refresh UI state
    } catch (err) {
      console.error("Failed to save position to database", err);
    }
  };

  // Close Position (archive for analytics)
  const closePosition = async (id) => {
    const input = prompt("Close price? (leave blank to skip P/L tracking)");
    const closePrice = input ? parseFloat(input) : null;
    try {
      const url = closePrice !== null
        ? `http://127.0.0.1:8000/api/positions/${id}/close?close_price=${closePrice}`
        : `http://127.0.0.1:8000/api/positions/${id}/close`;
      await fetch(url, { method: 'POST' });
      fetchTelemetry();
    } catch (err) {
      console.error("Failed to close position", err);
    }
  };

  // Hard Delete Position (for mistakes)
  const deletePosition = async (id) => {
    if (!window.confirm("Delete this position permanently? This will NOT be archived.")) return;
    try {
      await fetch(`http://127.0.0.1:8000/api/positions/${id}`, { method: 'DELETE' });
      fetchTelemetry();
    } catch (err) {
      console.error("Failed to delete position", err);
    }
  };

  const analyzeTrade = async () => {
    if (!newPosition.strike || !newPosition.credit) return;
    setAnalyzingTrade(true);
    setTradeAnalysis(null);
    try {
      const response = await fetch('http://127.0.0.1:8000/api/analyze-trade', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          type: newPosition.type,
          strike: parseFloat(newPosition.strike),
          credit: parseFloat(newPosition.credit),
        }),
      });
      if (!response.ok) throw new Error('Analysis failed');
      const data = await response.json();
      setTradeAnalysis(data);
    } catch (err) {
      console.error('Trade analysis failed', err);
      setTradeAnalysis({ error: 'Failed to analyze trade. Is the server running?' });
    } finally {
      setAnalyzingTrade(false);
    }
  };

  const getStateContext = (score) => {
    if (score <= 1) return ["Clear directional bias.", "Directional wings authorized.", "Respect strict 200% premium stops."];
    else if (score === 2) return ["Consolidating market.", "Neutral Iron Condors preferred.", "Expand stops to 250% premium or 15-pt boundary."];
    else return ["High Entropy Whipsaw.", "Strictly Neutral deployments.", "Suspend premium stops: Use strict asset limits ONLY."];
  };

  const spxPrice = telemetry ? telemetry.spx_price : null;
  const spxSource = telemetry ? telemetry.spx_source : null;
  const activePositions = [...(telemetry?.positions || [])].sort((a, b) => b.strike - a.strike);

  // Recommendation helpers
  const allRecs = telemetry?.recommendations || [];
  const getPositionRecs = (id) => allRecs.filter(r => r.target_id === id);
  const criticalHighRecs = allRecs.filter(r => r.priority === 'CRITICAL' || r.priority === 'HIGH');
  const dedupedAlerts = (() => {
    const seen = new Map();
    for (const rec of criticalHighRecs) {
      const key = rec.target_id ?? `mkt_${rec.message.slice(0, 20)}`;
      if (!seen.has(key)) seen.set(key, rec);
    }
    return Array.from(seen.values());
  })();
  const shortMsg = (msg) => msg.split('. ')[0].replace(/\.$/, '') + '.';
  const marketWatchRecs = allRecs.filter(r => r.target_id === null && (r.confidence || 0) >= 0.7);
  const [expandedPosAlerts, setExpandedPosAlerts] = useState({});
  const [showMarketWatch, setShowMarketWatch] = useState(true);
  const togglePosAlerts = (id) => setExpandedPosAlerts(prev => ({ ...prev, [id]: !prev[id] }));

  return (
    <div className="min-h-screen bg-slate-900 text-slate-100 p-6 font-sans">
      <header className="mb-6 border-b border-slate-700 pb-4">
        <div className="flex justify-between items-center mb-4">
          <div>
            <h1 className="text-3xl font-bold text-emerald-400">0DTE System Commander</h1>
            <p className="text-slate-400 text-sm">Algorithmic Decision Support Matrix V4.0</p>
          </div>
          <button onClick={fetchTelemetry} className="bg-slate-800 hover:bg-slate-700 text-slate-200 px-4 py-2 rounded shadow transition-colors">
            Refresh Data
          </button>
        </div>

        <div className="flex space-x-4">
          <button onClick={() => setActiveTab('dashboard')} className={`px-4 py-2 rounded font-semibold transition-colors ${activeTab === 'dashboard' ? 'bg-emerald-600 text-white' : 'bg-slate-800 text-slate-400'}`}>Live Dashboard</button>
          <button onClick={() => setActiveTab('history')} className={`px-4 py-2 rounded font-semibold transition-colors ${activeTab === 'history' ? 'bg-emerald-600 text-white' : 'bg-slate-800 text-slate-400'}`}>Trade History</button>
          <button onClick={() => setActiveTab('manual')} className={`px-4 py-2 rounded font-semibold transition-colors ${activeTab === 'manual' ? 'bg-emerald-600 text-white' : 'bg-slate-800 text-slate-400'}`}>System Manual</button>
        </div>
      </header>

      {error && <div className="bg-red-900/50 border border-red-500 text-red-200 p-4 rounded mb-6">{error}</div>}

      {activeTab === 'dashboard' && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 space-y-6">

            <div className="bg-slate-800 border border-slate-700 rounded-lg p-6 shadow-xl">
              <div className="flex justify-between items-end border-b border-slate-700 pb-2 mb-4">
                <h2 className="text-xl font-semibold text-slate-300">Live Telemetry</h2>
                {spxPrice && <div className="text-sm font-medium text-slate-400">SPX: <span className="text-emerald-400 font-bold">${spxPrice.toFixed(2)}</span> <span className="text-slate-500 text-xs">({spxSource})</span></div>}
              </div>

              {loading && !telemetry ? (
                <p className="text-slate-400 animate-pulse">Initializing data streams...</p>
              ) : telemetry ? (
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                  <MetricCard title="Data Source" value={telemetry.symbol} color="text-emerald-400 text-sm" />
                  <MetricCard title="SPY Spot" value={`$${telemetry.current_price}`} />
                  <MetricCard title="EMA 9" value={telemetry.ema_9} color={telemetry.current_price > telemetry.ema_9 ? "text-emerald-400" : "text-red-400"} />
                  <MetricCard title="EMA 21" value={telemetry.ema_21} color={telemetry.current_price > telemetry.ema_21 ? "text-emerald-400" : "text-red-400"} />
                  <MetricCard title="RSI (14)" value={telemetry.rsi_14} color={telemetry.rsi_14 > 60 || telemetry.rsi_14 < 40 ? "text-amber-400" : "text-slate-200"} />
                  <MetricCard title="CHOP (14)" value={telemetry.chop_value} color={telemetry.chop_value > 61.8 ? "text-red-400" : "text-emerald-400"} />
                  <MetricCard title="Efficiency (ER)" value={telemetry.er_value} color={telemetry.er_value < 0.20 ? "text-red-400" : "text-emerald-400"} />
                  <MetricCard title="VWAP Deviation" value={`${telemetry.vwap_dev}%`} color={telemetry.vwap_dev > 0.35 ? "text-amber-400 font-extrabold animate-pulse" : "text-emerald-400"} />
                </div>
              ) : null}
            </div>

            {telemetry && (
              <div className={`border rounded-lg p-5 shadow-xl ${
                telemetry.directional_bias.includes('BEAR') ? 'bg-red-900/20 border-red-700/50' :
                telemetry.directional_bias.includes('BULL') ? 'bg-emerald-900/20 border-emerald-700/50' :
                'bg-slate-800 border-slate-700'
              }`}>
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-3">
                    <div className={`text-3xl font-black tracking-tight ${
                      telemetry.directional_bias.includes('BEAR') ? 'text-red-400' :
                      telemetry.directional_bias.includes('BULL') ? 'text-emerald-400' :
                      'text-slate-300'
                    }`}>
                      {telemetry.directional_bias.includes('BEAR') ? '▼' : telemetry.directional_bias.includes('BULL') ? '▲' : '◆'} {telemetry.directional_bias}
                    </div>
                    {telemetry.momentum && (
                      <span className={`text-xs font-bold px-2 py-0.5 rounded ${
                        telemetry.momentum.momentum_label.includes('SELLOFF') ? 'bg-red-900/50 text-red-400' :
                        telemetry.momentum.momentum_label.includes('RALLY') ? 'bg-emerald-900/50 text-emerald-400' :
                        'bg-slate-700 text-slate-400'
                      }`}>{telemetry.momentum.momentum_label}</span>
                    )}
                  </div>
                  <div className="text-right">
                    <div className="text-2xl font-bold text-slate-100">{telemetry.spx_price.toFixed(2)}</div>
                    <div className="text-xs text-slate-500">SPX ({telemetry.spx_source})</div>
                  </div>
                </div>
                <div className="bg-slate-900/60 rounded p-3 border border-slate-700/50">
                  <div className="flex justify-between text-xs text-slate-400 mb-1">
                    <span>Day Low: <span className="text-red-400 font-bold">{telemetry.day_low_spx.toFixed(2)}</span></span>
                    <span>Range: {telemetry.range_position.toFixed(0)}%</span>
                    <span>Day High: <span className="text-emerald-400 font-bold">{telemetry.day_high_spx.toFixed(2)}</span></span>
                  </div>
                  <div className="relative w-full bg-slate-800 rounded-full h-3">
                    <div className="absolute left-0 top-0 bg-gradient-to-r from-red-600 via-slate-500 to-emerald-600 h-3 rounded-full w-full opacity-30"></div>
                    <div className="absolute top-0 h-3 w-1 bg-white rounded-full shadow-lg shadow-white/50 transition-all duration-500" style={{ left: `${Math.max(1, Math.min(99, telemetry.range_position))}%` }}></div>
                  </div>
                  <div className="flex justify-between text-xs mt-1">
                    <span className={`${telemetry.range_position < 20 ? 'text-red-400 font-bold' : 'text-slate-500'}`}>
                      {telemetry.range_position < 20 ? '⚠ Near Day Low' : ''}
                    </span>
                    <span className={`${telemetry.range_position > 80 ? 'text-emerald-400 font-bold' : 'text-slate-500'}`}>
                      {telemetry.range_position > 80 ? '⚠ Near Day High' : ''}
                    </span>
                  </div>
                </div>
              </div>
            )}

            {/* --- SIMPLIFIED PRICE WATCH: 2 Key Levels --- */}
            {telemetry?.watch_levels && (telemetry.watch_levels.critical_above || telemetry.watch_levels.critical_below) && (
              <div className="grid grid-cols-2 gap-3">
                {/* CEILING */}
                <div className={`rounded-lg p-4 border ${
                  telemetry.watch_levels.critical_above?.severity === 'gamma' ? 'bg-red-900/30 border-red-600/50' :
                  telemetry.watch_levels.critical_above?.severity === 'warning' ? 'bg-amber-900/20 border-amber-700/50' :
                  'bg-slate-800 border-slate-700'
                }`}>
                  {telemetry.watch_levels.critical_above ? (
                    <>
                      <div className="text-xs font-bold text-emerald-400 mb-1">▲ CEILING</div>
                      <div className="text-3xl font-black text-emerald-400 font-mono">{telemetry.watch_levels.critical_above.price.toFixed(0)}</div>
                      <div className="text-xs text-slate-400 mt-1">{telemetry.watch_levels.critical_above.distance} pts above</div>
                      <div className={`text-xs mt-2 font-medium ${
                        telemetry.watch_levels.critical_above.severity === 'gamma' ? 'text-red-300' :
                        telemetry.watch_levels.critical_above.severity === 'warning' ? 'text-amber-300' :
                        'text-slate-300'
                      }`}>{telemetry.watch_levels.critical_above.impact}</div>
                    </>
                  ) : (
                    <>
                      <div className="text-xs font-bold text-emerald-400 mb-1">▲ CEILING</div>
                      <div className="text-lg text-slate-500 italic mt-2">No critical level above</div>
                    </>
                  )}
                </div>
                {/* FLOOR */}
                <div className={`rounded-lg p-4 border ${
                  telemetry.watch_levels.critical_below?.severity === 'gamma' ? 'bg-red-900/30 border-red-600/50' :
                  telemetry.watch_levels.critical_below?.severity === 'warning' ? 'bg-amber-900/20 border-amber-700/50' :
                  'bg-slate-800 border-slate-700'
                }`}>
                  {telemetry.watch_levels.critical_below ? (
                    <>
                      <div className="text-xs font-bold text-red-400 mb-1">▼ FLOOR</div>
                      <div className="text-3xl font-black text-red-400 font-mono">{telemetry.watch_levels.critical_below.price.toFixed(0)}</div>
                      <div className="text-xs text-slate-400 mt-1">{telemetry.watch_levels.critical_below.distance} pts below</div>
                      <div className={`text-xs mt-2 font-medium ${
                        telemetry.watch_levels.critical_below.severity === 'gamma' ? 'text-red-300' :
                        telemetry.watch_levels.critical_below.severity === 'warning' ? 'text-amber-300' :
                        'text-slate-300'
                      }`}>{telemetry.watch_levels.critical_below.impact}</div>
                    </>
                  ) : (
                    <>
                      <div className="text-xs font-bold text-red-400 mb-1">▼ FLOOR</div>
                      <div className="text-lg text-slate-500 italic mt-2">No critical level below</div>
                    </>
                  )}
                </div>
              </div>
            )}

            {/* --- CRITICAL / HIGH ALERTS STRIP (deduplicated, compact) --- */}
            {dedupedAlerts.length > 0 && (
              <div className="border border-red-600/60 bg-red-900/30 rounded-lg px-4 py-3 shadow-xl">
                <div className="flex items-center gap-2 mb-2">
                  <span className="bg-red-600 text-white text-[10px] font-bold px-2 py-0.5 rounded animate-pulse">ACTION REQUIRED</span>
                  <span className="text-[10px] text-red-300">{dedupedAlerts.length} position{dedupedAlerts.length > 1 ? 's' : ''}</span>
                </div>
                <div className="space-y-1">
                  {dedupedAlerts.map((rec, i) => (
                    <div key={i} className={`flex items-center gap-2 text-xs ${rec.priority === 'CRITICAL' ? 'text-red-200' : 'text-amber-200'}`}>
                      <span className={`shrink-0 w-1.5 h-1.5 rounded-full ${rec.priority === 'CRITICAL' ? 'bg-red-500' : 'bg-amber-500'}`}></span>
                      <span className="font-bold shrink-0">{rec.category}</span>
                      <span className="text-slate-400">—</span>
                      <span className="truncate">{shortMsg(rec.message)}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {telemetry && (
              <div className={`border rounded-lg p-6 shadow-xl ${telemetry.continuous_score > 2.5 ? 'bg-red-900/20 border-red-700/50' : telemetry.continuous_score > 1.5 ? 'bg-amber-900/20 border-amber-700/50' : 'bg-emerald-900/20 border-emerald-700/50'}`}>
                <div className="flex justify-between items-center mb-4">
                  <h2 className="text-xl font-semibold text-slate-300">Algorithmic Directives</h2>
                  <span className={`text-xs font-bold px-2 py-0.5 rounded ${
                    telemetry.time_pressure.time_pressure_level === 'HIGH' ? 'bg-red-600 text-white animate-pulse' :
                    telemetry.time_pressure.time_pressure_level === 'MODERATE' ? 'bg-amber-600 text-white' :
                    'bg-slate-600 text-slate-200'
                  }`}>{telemetry.time_pressure.hours_remaining}h left</span>
                </div>
                <div className="space-y-3">
                  <div className="flex justify-between items-center bg-slate-900/50 p-4 rounded border border-slate-700/50">
                    <span className="text-slate-400 font-medium">Market State:</span>
                    <div className="text-right">
                      <span className="font-bold text-lg text-amber-400">{telemetry.regime_state}</span>
                      <div className="text-xs text-slate-500">Binary: {telemetry.regime_score}/4 | Continuous: {telemetry.continuous_score}/4.0</div>
                    </div>
                  </div>
                  <div className="bg-slate-900/50 p-4 rounded border border-slate-700/50">
                    <div className="flex justify-between items-center mb-2">
                      <span className="text-slate-400 font-medium">Smart Moat:</span>
                      <span className="font-bold text-lg text-slate-100">{telemetry.effective_moat_min} pts</span>
                    </div>
                    {telemetry.smart_moat_data && (
                      <div>
                        <div className="text-xs text-slate-500 mb-2">{telemetry.smart_moat_data.moat_explanation}</div>
                        <div className="flex gap-2 flex-wrap">
                          <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
                            telemetry.smart_moat_data.range_context === 'TIGHT' ? 'bg-emerald-900/50 text-emerald-400' :
                            telemetry.smart_moat_data.range_context === 'CONTAINED' ? 'bg-blue-900/50 text-blue-400' :
                            telemetry.smart_moat_data.range_context === 'EXPANDING' ? 'bg-red-900/50 text-red-400' :
                            'bg-slate-800 text-slate-400'
                          }`}>Range: {telemetry.smart_moat_data.range_context}</span>
                          <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
                            telemetry.smart_moat_data.signal_quality === 'DEAD' ? 'bg-slate-700 text-slate-400' :
                            telemetry.smart_moat_data.signal_quality === 'DIRECTIONAL' ? 'bg-amber-900/50 text-amber-400' :
                            'bg-slate-800 text-slate-400'
                          }`}>Signal: {telemetry.smart_moat_data.signal_quality}</span>
                          {telemetry.smart_moat_data.range_exhausted && (
                            <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-emerald-900/50 text-emerald-400">RANGE EXHAUSTED</span>
                          )}
                          {telemetry.smart_moat_data.combined_factor < 1 && (
                            <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-emerald-900/30 text-emerald-300">
                              {Math.round((1 - telemetry.smart_moat_data.combined_factor) * 100)}% reduction
                            </span>
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                  <div className="flex justify-between items-center bg-slate-900/50 p-4 rounded border border-slate-700/50">
                    <span className="text-slate-400 font-medium">Stop-Loss Protocol:</span>
                    <span className="font-bold text-lg text-slate-100">{telemetry.stop_loss_rule}</span>
                  </div>
                  <div className="bg-slate-900/50 p-4 rounded border border-slate-700/50">
                    <div className="text-xs text-slate-400 font-semibold uppercase tracking-wider mb-2">Indicator Intensity (0 = trending, 1 = max chop)</div>
                    <div className="space-y-2">
                      <IntensityBar label="CHOP" value={telemetry.sub_scores.chop_intensity} />
                      <IntensityBar label="ER" value={telemetry.sub_scores.er_intensity} />
                      <IntensityBar label="RSI" value={telemetry.sub_scores.rsi_intensity} />
                      <IntensityBar label="EMA" value={telemetry.sub_scores.ema_intensity} />
                    </div>
                  </div>
                  <div className="bg-slate-900/50 p-4 rounded border border-slate-700/50">
                    <div className="text-xs text-slate-400 font-semibold uppercase tracking-wider mb-2">Momentum Context (Historical)</div>
                    <div className="grid grid-cols-2 gap-3 text-sm">
                      <div>
                        <span className="text-slate-500 text-xs">2h Change</span>
                        <div className={`font-bold ${telemetry.momentum.change_2h_pct > 0 ? 'text-emerald-400' : telemetry.momentum.change_2h_pct < -0.2 ? 'text-red-400' : 'text-slate-300'}`}>
                          {telemetry.momentum.change_2h_pct > 0 ? '+' : ''}{telemetry.momentum.change_2h_pct}% ({telemetry.momentum.change_2h_spx_pts > 0 ? '+' : ''}{telemetry.momentum.change_2h_spx_pts} SPX pts)
                        </div>
                      </div>
                      <div>
                        <span className="text-slate-500 text-xs">1h Change</span>
                        <div className={`font-bold ${telemetry.momentum.change_1h_pct > 0 ? 'text-emerald-400' : telemetry.momentum.change_1h_pct < -0.1 ? 'text-red-400' : 'text-slate-300'}`}>
                          {telemetry.momentum.change_1h_pct > 0 ? '+' : ''}{telemetry.momentum.change_1h_pct}%
                        </div>
                      </div>
                      <div>
                        <span className="text-slate-500 text-xs">RSI Δ (2h)</span>
                        <div className={`font-bold ${telemetry.momentum.rsi_delta_2h > 3 ? 'text-emerald-400' : telemetry.momentum.rsi_delta_2h < -3 ? 'text-red-400' : 'text-slate-300'}`}>
                          {telemetry.momentum.rsi_delta_2h > 0 ? '+' : ''}{telemetry.momentum.rsi_delta_2h}
                        </div>
                      </div>
                      <div>
                        <span className="text-slate-500 text-xs">Intraday Range</span>
                        <div className="font-bold text-slate-300">{telemetry.momentum.range_position}%</div>
                        <div className="text-xs text-slate-500">{telemetry.momentum.day_low_spy} — {telemetry.momentum.day_high_spy}</div>
                      </div>
                    </div>
                    <div className={`mt-3 text-xs font-bold px-2 py-1 rounded inline-block ${
                      telemetry.momentum.momentum_label.includes('SELLOFF') ? 'bg-red-900/50 text-red-400' :
                      telemetry.momentum.momentum_label.includes('RALLY') ? 'bg-emerald-900/50 text-emerald-400' :
                      'bg-slate-800 text-slate-400'
                    }`}>{telemetry.momentum.momentum_label}</div>
                  </div>
                  {/* --- VIX / EXPECTED MOVE --- */}
                  {telemetry.expected_move && telemetry.expected_move.vix && (
                    <div className="bg-slate-900/50 p-4 rounded border border-slate-700/50">
                      <div className="text-xs text-slate-400 font-semibold uppercase tracking-wider mb-2">VIX Expected Move</div>
                      <div className="grid grid-cols-3 gap-3 text-sm">
                        <div>
                          <span className="text-slate-500 text-xs">VIX</span>
                          <div className={`font-bold ${telemetry.expected_move.vix > 25 ? 'text-red-400' : telemetry.expected_move.vix > 18 ? 'text-amber-400' : 'text-emerald-400'}`}>
                            {telemetry.expected_move.vix}
                          </div>
                        </div>
                        {telemetry.expected_move.vix9d && (
                          <div>
                            <span className="text-slate-500 text-xs">VIX9D</span>
                            <div className="font-bold text-slate-200">{telemetry.expected_move.vix9d}</div>
                          </div>
                        )}
                        <div>
                          <span className="text-slate-500 text-xs">Eff. Vol</span>
                          <div className="font-bold text-slate-200">{telemetry.expected_move.effective_vol}</div>
                        </div>
                      </div>
                      <div className="grid grid-cols-3 gap-3 text-sm mt-2">
                        <div>
                          <span className="text-slate-500 text-xs">1σ Move</span>
                          <div className="font-bold text-blue-400">±{telemetry.expected_move.expected_1sigma} pts</div>
                        </div>
                        <div>
                          <span className="text-slate-500 text-xs">2σ Move</span>
                          <div className="font-bold text-amber-400">±{telemetry.expected_move.expected_2sigma} pts</div>
                        </div>
                        <div>
                          <span className="text-slate-500 text-xs">Rec Moat</span>
                          <div className="font-bold text-emerald-400">{telemetry.expected_move.recommended_moat} pts</div>
                        </div>
                      </div>
                      {telemetry.realized_distribution && (
                        <div className="mt-3 pt-3 border-t border-slate-700/50">
                          <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-1.5">Reality Check ({telemetry.realized_distribution.lookback_days}d)</div>
                          <div className="grid grid-cols-4 gap-1.5 text-xs">
                            {['0.5', '1.0', '1.5', '2.0'].map(t => {
                              const pct = telemetry.realized_distribution.exceedance?.[`pct_over_${t}`] || 0;
                              return (
                                <div key={t} className="text-center">
                                  <div className="text-slate-500">±{t}%</div>
                                  <div className="w-full bg-slate-800 rounded-full h-1.5 mt-0.5 mb-0.5">
                                    <div className={`h-1.5 rounded-full ${pct > 30 ? 'bg-red-500' : pct > 15 ? 'bg-amber-500' : 'bg-blue-500'}`}
                                      style={{width: `${Math.min(100, pct)}%`}} />
                                  </div>
                                  <div className={`font-bold ${pct > 30 ? 'text-red-400' : pct > 15 ? 'text-amber-400' : 'text-blue-400'}`}>{pct}%</div>
                                </div>
                              );
                            })}
                          </div>
                          <div className="text-[10px] text-slate-500 mt-1">Avg daily move: ±{telemetry.realized_distribution.mean_abs_move_pct}%</div>
                        </div>
                      )}
                    </div>
                  )}

                  {/* --- REGIME TRANSITION PREDICTION --- */}
                  {telemetry.regime_transition && (
                    <div className={`p-4 rounded border ${
                      telemetry.regime_transition.direction === 'DETERIORATING' ? 'bg-red-900/30 border-red-700/50' :
                      telemetry.regime_transition.direction === 'SOFTENING' ? 'bg-amber-900/20 border-amber-700/50' :
                      telemetry.regime_transition.direction === 'IMPROVING' ? 'bg-emerald-900/20 border-emerald-700/50' :
                      telemetry.regime_transition.direction === 'FIRMING' ? 'bg-blue-900/20 border-blue-700/50' :
                      'bg-slate-900/50 border-slate-700/50'
                    }`}>
                      <div className="flex justify-between items-center mb-1">
                        <div className="text-xs text-slate-400 font-semibold uppercase tracking-wider">Regime Transition</div>
                        <span className={`text-xs font-bold px-1.5 py-0.5 rounded ${
                          telemetry.regime_transition.direction === 'DETERIORATING' ? 'bg-red-600 text-white' :
                          telemetry.regime_transition.direction === 'SOFTENING' ? 'bg-amber-600 text-white' :
                          telemetry.regime_transition.direction === 'IMPROVING' ? 'bg-emerald-600 text-white' :
                          telemetry.regime_transition.direction === 'FIRMING' ? 'bg-blue-600 text-white' :
                          'bg-slate-600 text-slate-200'
                        }`}>{telemetry.regime_transition.direction}</span>
                      </div>
                      <div className="text-sm text-slate-300 mb-2">{telemetry.regime_transition.label}</div>
                      <div className="flex gap-3 text-xs text-slate-500">
                        <span>Δ30m: <span className={`font-bold ${telemetry.regime_transition.score_delta_30m > 0 ? 'text-red-400' : telemetry.regime_transition.score_delta_30m < 0 ? 'text-emerald-400' : 'text-slate-400'}`}>{telemetry.regime_transition.score_delta_30m > 0 ? '+' : ''}{telemetry.regime_transition.score_delta_30m}</span></span>
                        <span>ER: <span className="font-bold text-slate-300">{telemetry.regime_transition.er_trend}</span></span>
                        <span>CHOP: <span className="font-bold text-slate-300">{telemetry.regime_transition.chop_trend}</span></span>
                        <span>Conf: <span className="font-bold text-slate-300">{Math.round(telemetry.regime_transition.confidence * 100)}%</span></span>
                      </div>
                    </div>
                  )}

                  {/* --- INTRADAY WINDOW + MARKET EVENTS --- */}
                  {telemetry.time_pressure?.intraday_window && (
                    <div className={`p-4 rounded border ${
                      telemetry.time_pressure.intraday_window.entry_quality >= 70 ? 'bg-emerald-900/20 border-emerald-700/50' :
                      telemetry.time_pressure.intraday_window.entry_quality >= 40 ? 'bg-slate-900/50 border-slate-700/50' :
                      'bg-red-900/20 border-red-700/50'
                    }`}>
                      <div className="flex justify-between items-center mb-2">
                        <div className="text-xs text-slate-400 font-semibold uppercase tracking-wider">Trading Window</div>
                        <div className="flex items-center gap-2">
                          <span className={`text-xs font-bold px-1.5 py-0.5 rounded ${
                            telemetry.time_pressure.intraday_window.entry_quality >= 70 ? 'bg-emerald-600 text-white' :
                            telemetry.time_pressure.intraday_window.entry_quality >= 40 ? 'bg-amber-600 text-white' :
                            'bg-red-600 text-white'
                          }`}>{telemetry.time_pressure.intraday_window.label}</span>
                          <span className="text-xs text-slate-500">Entry: {telemetry.time_pressure.intraday_window.entry_quality}/100</span>
                        </div>
                      </div>
                      <div className="text-sm text-slate-300 mb-1">{telemetry.time_pressure.intraday_window.description}</div>
                      <div className="text-xs text-slate-400 italic">{telemetry.time_pressure.intraday_window.advice}</div>
                    </div>
                  )}

                  {/* --- MARKET EVENTS --- */}
                  {telemetry.time_pressure?.market_events && telemetry.time_pressure.market_events.risk_level !== 'NORMAL' && (
                    <div className={`p-3 rounded border text-sm ${
                      telemetry.time_pressure.market_events.risk_level === 'HIGH' ? 'bg-red-900/30 border-red-700/50 text-red-300' :
                      telemetry.time_pressure.market_events.risk_level === 'ELEVATED' ? 'bg-amber-900/30 border-amber-700/50 text-amber-300' :
                      'bg-blue-900/20 border-blue-700/50 text-blue-300'
                    }`}>
                      <div className="flex items-center gap-2 mb-1">
                        <span className="text-xs font-bold uppercase tracking-wider text-slate-400">Calendar Events</span>
                        <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
                          telemetry.time_pressure.market_events.risk_level === 'HIGH' ? 'bg-red-600 text-white animate-pulse' :
                          telemetry.time_pressure.market_events.risk_level === 'ELEVATED' ? 'bg-amber-600 text-white' :
                          'bg-blue-600 text-white'
                        }`}>{telemetry.time_pressure.market_events.risk_level} RISK</span>
                      </div>
                      <ul className="text-xs space-y-0.5">
                        {telemetry.time_pressure.market_events.events.map((e, i) => (
                          <li key={i} className="flex items-center gap-1">
                            <span className="w-1 h-1 rounded-full bg-current shrink-0"></span>
                            {e}
                          </li>
                        ))}
                      </ul>
                      {telemetry.time_pressure.market_events.moat_multiplier > 1.0 && (
                        <div className="text-xs mt-1 font-bold">Moat widened ×{telemetry.time_pressure.market_events.moat_multiplier}</div>
                      )}
                    </div>
                  )}

                  {/* --- GAMMA EXPOSURE (GEX) --- */}
                  {telemetry.gex_data && telemetry.gex_data.gex_regime !== 'UNAVAILABLE' && (
                    <div className={`p-4 rounded border ${
                      telemetry.gex_data.gex_regime === 'POSITIVE' ? 'bg-emerald-900/20 border-emerald-700/50' :
                      telemetry.gex_data.gex_regime === 'NEGATIVE' ? 'bg-red-900/20 border-red-700/50' :
                      'bg-slate-900/50 border-slate-700/50'
                    }`}>
                      <div className="flex justify-between items-center mb-2">
                        <div className="text-xs text-slate-400 font-semibold uppercase tracking-wider">Gamma Exposure (GEX)</div>
                        <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
                          telemetry.gex_data.gex_regime === 'POSITIVE' ? 'bg-emerald-600 text-white' :
                          telemetry.gex_data.gex_regime === 'NEGATIVE' ? 'bg-red-600 text-white' :
                          'bg-slate-600 text-white'
                        }`}>{telemetry.gex_data.gex_regime}</span>
                      </div>
                      <div className="text-xs text-slate-400 mb-3">{telemetry.gex_data.gex_regime_label}</div>
                      <div className="grid grid-cols-3 gap-2 mb-3">
                        <div className="bg-slate-900/60 rounded p-2 text-center">
                          <div className="text-[10px] text-emerald-400 font-bold">Gamma Wall</div>
                          <div className="text-sm font-bold text-slate-100">{telemetry.gex_data.gamma_wall_spx.toLocaleString()}</div>
                          <div className="text-[10px] text-slate-500">SPX magnet</div>
                        </div>
                        <div className="bg-slate-900/60 rounded p-2 text-center">
                          <div className="text-[10px] text-red-400 font-bold">Put Wall</div>
                          <div className="text-sm font-bold text-slate-100">{telemetry.gex_data.put_wall_spx.toLocaleString()}</div>
                          <div className="text-[10px] text-slate-500">SPX floor</div>
                        </div>
                        <div className="bg-slate-900/60 rounded p-2 text-center">
                          <div className="text-[10px] text-blue-400 font-bold">Call Wall</div>
                          <div className="text-sm font-bold text-slate-100">{telemetry.gex_data.call_wall_spx.toLocaleString()}</div>
                          <div className="text-[10px] text-slate-500">SPX ceiling</div>
                        </div>
                      </div>
                      <div className="flex items-center justify-between text-xs mb-2">
                        <span className="text-slate-500">Net GEX</span>
                        <span className={`font-bold ${telemetry.gex_data.net_gex > 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                          {(telemetry.gex_data.net_gex / 1e6).toFixed(1)}M
                        </span>
                      </div>
                      {telemetry.gex_data.top_levels && telemetry.gex_data.top_levels.length > 0 && (
                        <div className="border-t border-slate-700/50 pt-2">
                          <div className="text-[10px] text-slate-500 mb-1">Top GEX Levels (SPX)</div>
                          <div className="flex flex-wrap gap-1">
                            {telemetry.gex_data.top_levels.map((lvl, i) => (
                              <span key={i} className="text-[10px] font-mono bg-slate-800 text-slate-300 px-1.5 py-0.5 rounded border border-slate-700">
                                {lvl.strike_spx}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}
                      <div className="text-[10px] text-slate-600 mt-2">{telemetry.gex_data.data_source} • {telemetry.gex_data.total_strikes} strikes</div>
                    </div>
                  )}

                  <div className={`p-3 rounded border text-sm ${
                    telemetry.time_pressure.time_pressure_level === 'HIGH' ? 'bg-red-900/30 border-red-700/50 text-red-300' :
                    telemetry.time_pressure.time_pressure_level === 'MODERATE' ? 'bg-amber-900/30 border-amber-700/50 text-amber-300' :
                    'bg-slate-900/50 border-slate-700/50 text-slate-400'
                  }`}>
                    {telemetry.time_pressure.time_pressure_label}
                  </div>
                  <div className="bg-slate-900/80 p-4 rounded border border-slate-700">
                    <ul className="list-disc list-inside text-sm text-slate-300 space-y-1">
                      {getStateContext(telemetry.regime_score).map((p, i) => <li key={i}>{p}</li>)}
                    </ul>
                  </div>
                </div>
              </div>
            )}
          </div>

          <div className="bg-slate-800 border border-slate-700 rounded-lg p-6 shadow-xl flex flex-col h-full">
            <h2 className="text-xl font-semibold mb-4 text-slate-300 border-b border-slate-700 pb-2">Smart Ledger V3 (Database)</h2>

            {/* --- INTRADAY P/L DASHBOARD --- */}
            {telemetry?.intraday_pl && (
              <div className={`mb-4 rounded-lg p-3 border ${
                telemetry.intraday_pl.total_pl >= 0 ? 'bg-emerald-900/20 border-emerald-700/50' : 'bg-red-900/20 border-red-700/50'
              }`}>
                <div className="flex justify-between items-center">
                  <span className="text-xs text-slate-400 uppercase tracking-wider font-semibold">Day P/L</span>
                  <span className={`text-lg font-bold ${telemetry.intraday_pl.total_pl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                    {telemetry.intraday_pl.total_pl >= 0 ? '+' : ''}${telemetry.intraday_pl.total_pl.toFixed(2)}
                  </span>
                </div>
                <div className="flex gap-4 mt-1 text-xs">
                  <span className="text-slate-400">
                    Closed: <span className={telemetry.intraday_pl.closed_pl >= 0 ? 'text-emerald-400' : 'text-red-400'}>
                      {telemetry.intraday_pl.closed_pl >= 0 ? '+' : ''}${telemetry.intraday_pl.closed_pl.toFixed(2)}
                    </span> ({telemetry.intraday_pl.closed_count})
                  </span>
                  <span className="text-slate-400">
                    Open: <span className={telemetry.intraday_pl.open_pl >= 0 ? 'text-emerald-400' : 'text-red-400'}>
                      {telemetry.intraday_pl.open_pl >= 0 ? '+' : ''}${telemetry.intraday_pl.open_pl.toFixed(2)}
                    </span> ({telemetry.intraday_pl.open_count})
                  </span>
                </div>
              </div>
            )}

            {/* --- POSITION SUMMARY (Iron Condor View) --- */}
            {telemetry?.position_summary && telemetry.position_summary.positions_total > 0 && (() => {
              const ps = telemetry.position_summary;
              const tiltColor = ps.risk_tilt === 'BALANCED' ? 'text-emerald-400' : ps.risk_tilt === 'PUT_HEAVY' ? 'text-red-400' : 'text-amber-400';
              return (
                <div className="mb-4 bg-slate-900/80 rounded-lg p-3 border border-slate-700">
                  <div className="flex justify-between items-center mb-2">
                    <span className="text-xs font-bold text-slate-400 uppercase tracking-wider">{ps.structure.replace('_', ' ')}</span>
                    <span className={`text-sm font-bold ${ps.total_estimated_pl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                      Est. P/L: {ps.total_estimated_pl >= 0 ? '+' : ''}${ps.total_estimated_pl.toFixed(2)}
                    </span>
                  </div>
                  <div className="grid grid-cols-3 gap-2 text-center text-xs">
                    <div>
                      <div className="text-slate-500">Total Credit</div>
                      <div className="font-bold text-slate-200">${ps.total_credit.toFixed(2)}</div>
                    </div>
                    <div>
                      <div className="text-slate-500">Risk Tilt</div>
                      <div className={`font-bold ${tiltColor}`}>{ps.risk_tilt.replace('_', ' ')}</div>
                    </div>
                    <div>
                      <div className="text-slate-500">At Risk</div>
                      <div className={`font-bold ${ps.positions_at_risk > 0 ? 'text-amber-400' : 'text-emerald-400'}`}>{ps.positions_at_risk}/{ps.positions_total}</div>
                    </div>
                  </div>
                  {ps.safe_floor && ps.safe_ceiling && (
                    <div className="mt-2 text-xs text-center">
                      {ps.safe_floor < ps.safe_ceiling ? (
                        <span className="text-slate-500">
                          Safe corridor: <span className="text-slate-300 font-mono font-bold">{ps.safe_floor.toFixed(0)}</span> — <span className="text-slate-300 font-mono font-bold">{ps.safe_ceiling.toFixed(0)}</span>
                          {telemetry.spx_price >= ps.safe_floor && telemetry.spx_price <= ps.safe_ceiling
                            ? <span className="text-emerald-400 ml-1">✓ SPX inside</span>
                            : <span className="text-red-400 ml-1">✗ SPX outside</span>
                          }
                        </span>
                      ) : (
                        <span className="text-red-400 font-semibold">No safe corridor — positions too close to SPX</span>
                      )}
                    </div>
                  )}
                </div>
              );
            })()}

            {/* --- DANGER ZONE: Inner strike boundaries --- */}
            {activePositions.length > 1 && (() => {
              const calls = activePositions.filter(p => p.type === 'Call Spread');
              const puts = activePositions.filter(p => p.type === 'Put Spread');
              const dangerCeiling = calls.length > 0 ? Math.min(...calls.map(p => p.strike)) : null;
              const dangerFloor = puts.length > 0 ? Math.max(...puts.map(p => p.strike)) : null;
              if (!dangerCeiling && !dangerFloor) return null;
              const spx = telemetry?.spx_price;
              const ceilingDist = dangerCeiling && spx ? (dangerCeiling - spx).toFixed(0) : null;
              const floorDist = dangerFloor && spx ? (spx - dangerFloor).toFixed(0) : null;
              const ceilingBreached = dangerCeiling && spx && spx >= dangerCeiling;
              const floorBreached = dangerFloor && spx && spx <= dangerFloor;
              return (
                <div className="mb-3 bg-slate-900/60 rounded-lg p-2.5 border border-slate-700">
                  <div className="text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-1.5 text-center">Price Must Stay Between</div>
                  <div className="flex items-center justify-center gap-3">
                    {dangerFloor && (
                      <div className={`text-center ${floorBreached ? 'text-red-400' : 'text-slate-200'}`}>
                        <div className="text-lg font-mono font-bold">{dangerFloor.toFixed(0)}</div>
                        <div className="text-[10px] text-slate-500">Floor {floorBreached ? <span className="text-red-400 font-bold">BREACHED</span> : `(${floorDist} pts below)`}</div>
                      </div>
                    )}
                    <div className="text-slate-600 text-lg">—</div>
                    {dangerCeiling && (
                      <div className={`text-center ${ceilingBreached ? 'text-red-400' : 'text-slate-200'}`}>
                        <div className="text-lg font-mono font-bold">{dangerCeiling.toFixed(0)}</div>
                        <div className="text-[10px] text-slate-500">Ceiling {ceilingBreached ? <span className="text-red-400 font-bold">BREACHED</span> : `(${ceilingDist} pts above)`}</div>
                      </div>
                    )}
                  </div>
                  {dangerFloor && dangerCeiling && (
                    <div className="text-[10px] text-center mt-1 text-slate-500">
                      Safe band: <span className="font-mono font-bold text-slate-400">{(dangerCeiling - dangerFloor).toFixed(0)} pts</span>
                      {spx && !ceilingBreached && !floorBreached && (
                        <span className="text-emerald-400 ml-1">✓ SPX inside</span>
                      )}
                      {(ceilingBreached || floorBreached) && (
                        <span className="text-red-400 ml-1 font-bold">✗ POSITION AT RISK</span>
                      )}
                    </div>
                  )}
                </div>
              );
            })()}

            <form onSubmit={handleAddPosition} className="mb-4 space-y-3">
              <select className="w-full bg-slate-900 border border-slate-600 rounded p-2 text-slate-200 outline-none" value={newPosition.type} onChange={e => { setNewPosition({...newPosition, type: e.target.value}); setTradeAnalysis(null); }}>
                <option>Put Spread</option><option>Call Spread</option>
              </select>
              <div className="flex gap-2">
                <input type="text" placeholder="SPX Strike" className="w-1/2 bg-slate-900 border border-slate-600 rounded p-2 text-slate-200 outline-none" value={newPosition.strike} onChange={e => { setNewPosition({...newPosition, strike: e.target.value}); setTradeAnalysis(null); }}/>
                <input type="text" placeholder="Credit ($)" className="w-1/2 bg-slate-900 border border-slate-600 rounded p-2 text-slate-200 outline-none" value={newPosition.credit} onChange={e => { setNewPosition({...newPosition, credit: e.target.value}); setTradeAnalysis(null); }}/>
              </div>
              <div className="flex gap-2">
                <button type="button" onClick={analyzeTrade} disabled={analyzingTrade || !newPosition.strike || !newPosition.credit} className="w-1/2 bg-blue-600 hover:bg-blue-500 disabled:bg-slate-700 disabled:text-slate-500 text-white font-bold py-2 px-4 rounded transition-colors">
                  {analyzingTrade ? 'Analyzing...' : 'Analyze First'}
                </button>
                <button type="submit" className="w-1/2 bg-emerald-600 hover:bg-emerald-500 text-white font-bold py-2 px-4 rounded">Track Position</button>
              </div>
            </form>

            {/* Pre-Trade Analysis Result */}
            {tradeAnalysis && !tradeAnalysis.error && (
              <div className={`mb-4 rounded-lg border p-4 ${
                tradeAnalysis.verdict_color === 'emerald' ? 'border-emerald-500 bg-emerald-500/10' :
                tradeAnalysis.verdict_color === 'blue' ? 'border-blue-500 bg-blue-500/10' :
                tradeAnalysis.verdict_color === 'amber' ? 'border-amber-500 bg-amber-500/10' :
                'border-red-500 bg-red-500/10'
              }`}>
                <div className="flex items-center justify-between mb-3">
                  <span className={`text-lg font-bold ${
                    tradeAnalysis.verdict_color === 'emerald' ? 'text-emerald-400' :
                    tradeAnalysis.verdict_color === 'blue' ? 'text-blue-400' :
                    tradeAnalysis.verdict_color === 'amber' ? 'text-amber-400' :
                    'text-red-400'
                  }`}>{tradeAnalysis.verdict_label}</span>
                  <span className="text-2xl font-mono font-bold text-white">{tradeAnalysis.score}<span className="text-sm text-slate-400">/100</span></span>
                </div>

                {/* Score breakdown bar */}
                <div className="flex gap-1 mb-3 h-2 rounded overflow-hidden bg-slate-800">
                  {(() => {
                    const b = tradeAnalysis.breakdown;
                    const max = 100;
                    const segments = [
                      { val: b.moat_score, color: 'bg-emerald-500', label: 'Moat' },
                      { val: b.range_score, color: 'bg-blue-500', label: 'Range' },
                      { val: b.direction_score, color: 'bg-cyan-500', label: 'Direction' },
                      { val: b.time_score, color: 'bg-purple-500', label: 'Time' },
                      { val: b.credit_score, color: 'bg-amber-500', label: 'Credit' },
                      { val: b.portfolio_score, color: 'bg-teal-500', label: 'Portfolio' },
                    ];
                    return segments.map((s, i) => (
                      <div key={i} className={`${s.color} transition-all`} style={{ width: `${(s.val / max) * 100}%` }} title={`${s.label}: ${s.val}`} />
                    ));
                  })()}
                </div>

                {/* Breakdown detail */}
                <div className="grid grid-cols-3 gap-1 text-xs mb-3">
                  {[
                    ['Moat', tradeAnalysis.breakdown.moat_score, 30],
                    ['Range', tradeAnalysis.breakdown.range_score, 20],
                    ['Direction', tradeAnalysis.breakdown.direction_score, 15],
                    ['Time', tradeAnalysis.breakdown.time_score, 15],
                    ['Credit', tradeAnalysis.breakdown.credit_score, 10],
                    ['Portfolio', tradeAnalysis.breakdown.portfolio_score, 10],
                  ].map(([label, val, max]) => (
                    <div key={label} className="text-center">
                      <span className="text-slate-400">{label}</span>
                      <span className={`ml-1 font-mono ${val >= max * 0.7 ? 'text-emerald-400' : val >= max * 0.4 ? 'text-amber-400' : 'text-red-400'}`}>{val}/{max}</span>
                    </div>
                  ))}
                </div>

                {/* Penalties */}
                {(tradeAnalysis.breakdown.regime_penalty > 0 || tradeAnalysis.breakdown.range_stress_penalty > 0) && (
                  <div className="text-xs text-red-400 mb-2">
                    Penalties: {tradeAnalysis.breakdown.regime_penalty > 0 && <span className="mr-2">Regime −{tradeAnalysis.breakdown.regime_penalty}</span>}
                    {tradeAnalysis.breakdown.range_stress_penalty > 0 && <span>Range stress −{tradeAnalysis.breakdown.range_stress_penalty}</span>}
                  </div>
                )}

                {/* Moat info */}
                <div className="text-xs text-slate-300 mb-2">
                  Proposed moat: <span className="font-mono font-bold">{tradeAnalysis.moat} pts</span> (smart moat: {tradeAnalysis.context.smart_moat} pts)
                </div>

                {/* Reasons */}
                {tradeAnalysis.reasons_for.length > 0 && (
                  <div className="mb-2">
                    {tradeAnalysis.reasons_for.map((r, i) => (
                      <div key={i} className="text-xs text-emerald-400 flex items-start gap-1"><span>+</span><span>{r}</span></div>
                    ))}
                  </div>
                )}
                {tradeAnalysis.reasons_against.length > 0 && (
                  <div className="mb-2">
                    {tradeAnalysis.reasons_against.map((r, i) => (
                      <div key={i} className="text-xs text-red-400 flex items-start gap-1"><span>-</span><span>{r}</span></div>
                    ))}
                  </div>
                )}

                {/* Suggested alternative */}
                {tradeAnalysis.suggested_strike && (
                  <div className="text-xs text-blue-400 mt-2 pt-2 border-t border-slate-700">
                    Suggested: {newPosition.type} @ <span className="font-mono font-bold">{tradeAnalysis.suggested_strike}</span> for better score
                    <button
                      onClick={() => { setNewPosition({...newPosition, strike: String(tradeAnalysis.suggested_strike)}); setTradeAnalysis(null); }}
                      className="ml-2 px-2 py-0.5 bg-blue-600 hover:bg-blue-500 rounded text-white text-xs"
                    >Use</button>
                  </div>
                )}
              </div>
            )}

            {tradeAnalysis?.error && (
              <div className="mb-4 p-3 rounded bg-red-500/10 border border-red-500 text-red-400 text-xs">{tradeAnalysis.error}</div>
            )}

            <div className="space-y-4 overflow-y-auto flex-1">
              {activePositions.length === 0 ? (
                <p className="text-slate-500 text-sm text-center italic mt-8">No active positions tracked. Awaiting deployment.</p>
              ) : (
                activePositions.map((pos, idx) => {
                  const isUpperBound = idx === 0 && activePositions.length > 1;
                  const isLowerBound = idx === activePositions.length - 1 && activePositions.length > 1;
                  const posRecs = getPositionRecs(pos.id);
                  const hasCritical = posRecs.some(r => r.priority === 'CRITICAL');
                  const hasHigh = posRecs.some(r => r.priority === 'HIGH');
                  const borderColor = hasCritical ? 'border-l-red-500' : hasHigh ? 'border-l-amber-500' : pos.at_risk_side ? 'border-l-amber-700' : 'border-l-emerald-700';
                  const isExpanded = expandedPosAlerts[pos.id];

                  return (
                    <div key={pos.id} className={`bg-slate-900 p-4 rounded-lg border border-slate-700 border-l-[3px] ${borderColor} shadow-sm relative overflow-hidden`}>
                      {isUpperBound && (
                        <div className="text-[10px] font-bold text-emerald-500 uppercase tracking-widest mb-1">▲ Upper Bound</div>
                      )}
                      {isLowerBound && (
                        <div className="text-[10px] font-bold text-red-500 uppercase tracking-widest mb-1">▼ Lower Bound</div>
                      )}
                      <div className="flex justify-between items-start mb-2">
                        <div>
                          <div className="font-bold text-slate-100">{pos.type} @ {pos.strike}</div>
                          <div className="flex items-center gap-2 text-xs text-slate-400">
                            <span>Credit: ${pos.credit}</span>
                            <span className={`font-bold ${pos.estimated_pl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                              Est. P/L: {pos.estimated_pl >= 0 ? '+' : ''}${pos.estimated_pl?.toFixed(2)}
                            </span>
                            {pos.breakeven_event && (
                              <span className="font-bold text-yellow-400 animate-pulse">
                                BREAKEVEN ({pos.breakeven_event.touch_count}x)
                              </span>
                            )}
                            {pos.drift_alert && (
                              <span className="font-bold text-orange-400" title={`${pos.drift_alert.start_price}→${pos.drift_alert.current_price} over ${pos.drift_alert.window_minutes}min`}>
                                ↗ DRIFT +{pos.drift_alert.drift_pts}pts
                              </span>
                            )}
                          </div>
                        </div>
                        <div className="flex items-center gap-1">
                          {posRecs.length > 0 && (
                            <button onClick={() => togglePosAlerts(pos.id)} title="View alerts" className={`text-xs font-bold px-1.5 py-0.5 rounded transition-colors ${hasCritical ? 'bg-red-600 text-white animate-pulse' : hasHigh ? 'bg-amber-600 text-white' : 'bg-slate-700 text-slate-300'}`}>
                              {posRecs.length}
                            </button>
                          )}
                          <button onClick={() => closePosition(pos.id)} title="Close position (archive)" className="text-emerald-500 hover:text-emerald-400 font-bold px-1.5 py-0.5 text-sm rounded hover:bg-emerald-900/30">✓</button>
                          <button onClick={() => deletePosition(pos.id)} title="Delete (mistake)" className="text-red-500 hover:text-red-400 font-bold px-1.5 py-0.5 text-sm rounded hover:bg-red-900/30">✕</button>
                        </div>
                      </div>

                      <div className="mt-3">
                        <div className="flex justify-between text-xs mb-1">
                          <span className={pos.status_color}>{pos.message}</span>
                          <span className={`font-mono ${pos.status_color}`}>{pos.moat > 0 ? `+${pos.moat} pts` : `${pos.moat} pts`}</span>
                        </div>
                        <div className="w-full bg-slate-800 rounded-full h-2">
                          <div className={`${pos.bar_color} h-2 rounded-full transition-all duration-500`} style={{ width: `${pos.moat_pct}%` }}></div>
                        </div>
                      </div>

                      {/* Exit Strategy */}
                      {pos.exit_strategy?.instruction && (
                        <div className={`mt-2 text-xs px-2.5 py-1.5 rounded border ${
                          ['CRITICAL_EJECT', 'URGENT_CLOSE'].includes(pos.exit_strategy.action) ? 'bg-red-900/50 border-red-600/70 text-red-200 animate-pulse' :
                          pos.exit_strategy.action === 'CLOSE_NOW' ? 'bg-red-900/40 border-red-700/50 text-red-200' :
                          pos.exit_strategy.action === 'CLOSE_SOON' || pos.exit_strategy.action === 'CLOSE_RECOMMENDED' ? 'bg-amber-900/30 border-amber-700/50 text-amber-200' :
                          pos.exit_strategy.action === 'HOLD_WITH_TRIGGER' ? 'bg-blue-900/20 border-blue-700/40 text-blue-200' :
                          'bg-emerald-900/20 border-emerald-700/40 text-emerald-300'
                        }`}>
                          <div className="flex items-center gap-1.5">
                            <span className={`font-bold text-[10px] uppercase tracking-wider shrink-0 ${
                              ['CRITICAL_EJECT', 'URGENT_CLOSE'].includes(pos.exit_strategy.action) ? 'text-red-300' :
                              pos.exit_strategy.action === 'CLOSE_NOW' ? 'text-red-400' :
                              pos.exit_strategy.action === 'CLOSE_SOON' ? 'text-amber-400' :
                              pos.exit_strategy.action === 'LET_EXPIRE' ? 'text-emerald-400' :
                              'text-slate-400'
                            }`}>{pos.exit_strategy.action.replace(/_/g, ' ')}</span>
                            {pos.exit_strategy.escalation_level && !['SAFE', 'CAUTION'].includes(pos.exit_strategy.escalation_level) && (
                              <span className={`text-[9px] font-bold px-1 py-0.5 rounded ${
                                pos.exit_strategy.escalation_level === 'CRITICAL_EJECT' ? 'bg-red-600 text-white' :
                                pos.exit_strategy.escalation_level === 'URGENT_CLOSE' ? 'bg-red-700 text-red-100' :
                                pos.exit_strategy.escalation_level === 'CLOSE_RECOMMENDED' ? 'bg-amber-700 text-amber-100' :
                                'bg-slate-600 text-slate-200'
                              }`}>{pos.exit_strategy.escalation_level.replace(/_/g, ' ')}</span>
                            )}
                            {pos.exit_strategy.target_price && (
                              <span className="font-mono font-bold">Est. @${pos.exit_strategy.target_price}</span>
                            )}
                            {pos.exit_strategy.monitor_minutes > 0 && (
                              <span className="text-slate-500">| {pos.exit_strategy.monitor_minutes}min window</span>
                            )}
                            {pos.exit_strategy.signal_age > 0 && (
                              <span className={`text-[10px] ml-auto font-semibold ${
                                pos.exit_strategy.signal_stability === 'STABLE' ? 'text-emerald-400' :
                                pos.exit_strategy.signal_stability === 'CONFIRMING' ? 'text-blue-400' :
                                pos.exit_strategy.signal_stability === 'LOCKED' ? 'text-amber-400' :
                                pos.exit_strategy.signal_stability === 'COOLING' ? 'text-amber-300' :
                                'text-slate-500'
                              }`}>
                                {pos.exit_strategy.signal_stability === 'STABLE' ? '✓ ' :
                                 pos.exit_strategy.signal_stability === 'LOCKED' ? '🔒 ' :
                                 pos.exit_strategy.signal_stability === 'NEW' ? '⚡ ' : ''}
                                {pos.exit_strategy.signal_age}x {pos.exit_strategy.signal_stability}
                              </span>
                            )}
                          </div>
                          <div className="mt-0.5 text-slate-400">{pos.exit_strategy.instruction}</div>
                          {pos.premium_trend && pos.premium_trend.readings >= 3 && (
                            <div className="mt-1 flex items-center gap-2 text-[10px]">
                              <span className={`font-bold ${
                                pos.premium_trend.trend === 'RISING' ? 'text-red-400' :
                                pos.premium_trend.trend === 'FALLING' ? 'text-emerald-400' :
                                pos.premium_trend.trend === 'VOLATILE' ? 'text-amber-400' :
                                'text-slate-500'
                              }`}>
                                {pos.premium_trend.trend === 'RISING' ? '📈' :
                                 pos.premium_trend.trend === 'FALLING' ? '📉' :
                                 pos.premium_trend.trend === 'VOLATILE' ? '〰️' : '—'}
                                {' '}Est. ${pos.premium_trend.avg} avg
                              </span>
                              <span className="text-slate-600">
                                (${pos.premium_trend.min}–${pos.premium_trend.max}, {pos.premium_trend.readings} reads)
                              </span>
                            </div>
                          )}
                        </div>
                      )}

                      {/* Inline expandable alerts */}
                      {isExpanded && posRecs.length > 0 && (
                        <div className="mt-3 space-y-1.5 border-t border-slate-700/50 pt-2">
                          {posRecs.map((rec, i) => (
                            <div key={i} className={`text-xs px-2 py-1.5 rounded ${
                              rec.priority === 'CRITICAL' ? 'bg-red-900/40 text-red-200' :
                              rec.priority === 'HIGH' ? 'bg-amber-900/30 text-amber-200' :
                              'bg-slate-800 text-slate-400'
                            }`}>
                              <span className="font-bold">{rec.category}:</span> {rec.message}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })
              )}
            </div>
          </div>

          {/* --- TRADE PROPOSALS (Auto-suggested positions) --- */}
          {telemetry?.trade_proposals && telemetry.trade_proposals.length > 0 && (
            <div className="lg:col-span-3 bg-slate-800 border border-blue-700/50 rounded-lg shadow-xl p-4">
              <div className="flex items-center gap-2 mb-3">
                <h2 className="text-lg font-semibold text-blue-400">Trade Ideas</h2>
                <span className="text-xs text-slate-500">{telemetry.trade_proposals.length} candidates</span>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                {telemetry.trade_proposals.map((p, i) => (
                  <div key={i} className={`p-3 rounded border ${
                    p.verdict === 'STRONG_ENTRY' ? 'bg-emerald-900/20 border-emerald-700/50' : 'bg-slate-900/50 border-slate-700/50'
                  }`}>
                    <div className="flex justify-between items-center mb-1">
                      <span className="font-bold text-sm text-slate-200">{p.type} @ {p.strike}</span>
                      <span className={`text-xs font-bold px-1.5 py-0.5 rounded ${
                        p.verdict === 'STRONG_ENTRY' ? 'bg-emerald-700 text-emerald-100' : 'bg-blue-700 text-blue-100'
                      }`}>{p.score}/100 {p.verdict.replace('_', ' ')}</span>
                    </div>
                    <div className="text-xs text-slate-400">
                      Est. credit: ${p.estimated_credit} | Moat: {p.moat} pts
                    </div>
                    {p.reasons_for?.length > 0 && (
                      <div className="text-[10px] text-emerald-400 mt-1">+ {p.reasons_for[0]}</div>
                    )}
                    {p.reasons_against?.length > 0 && (
                      <div className="text-[10px] text-red-400">- {p.reasons_against[0]}</div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* --- MARKET WATCH & OPPORTUNITIES (collapsible, market-wide only) --- */}
          {marketWatchRecs.length > 0 && (
            <div className="lg:col-span-3 bg-slate-800 border border-slate-700 rounded-lg shadow-xl overflow-hidden">
              <button onClick={() => setShowMarketWatch(!showMarketWatch)} className="w-full flex justify-between items-center p-4 hover:bg-slate-750 transition-colors text-left">
                <div className="flex items-center gap-2">
                  <h2 className="text-lg font-semibold text-slate-300">Market Watch & Opportunities</h2>
                  <span className="text-xs text-slate-500">{marketWatchRecs.length} item{marketWatchRecs.length > 1 ? 's' : ''}</span>
                </div>
                <span className="text-slate-400 text-sm">{showMarketWatch ? '▼' : '▶'}</span>
              </button>
              {showMarketWatch && (
                <div className="px-4 pb-4 space-y-2">
                  {marketWatchRecs.map((rec, i) => {
                    const categoryIcon = { WATCH: '◎', ADJUST: '⟳', OPPORTUNITY: '◈' };
                    const priorityColor = rec.priority === 'MEDIUM' ? 'text-slate-300' : 'text-slate-400';
                    return (
                      <div key={i} className="flex items-start gap-2 bg-slate-900/40 p-3 rounded border border-slate-700/40">
                        <span className={`shrink-0 text-xs font-bold px-1.5 py-0.5 rounded ${rec.priority === 'MEDIUM' ? 'bg-slate-600 text-slate-200' : 'bg-slate-700 text-slate-300'}`}>
                          {categoryIcon[rec.category] || '•'} {rec.category}
                        </span>
                        <span className={`text-sm ${priorityColor}`}>{rec.message}</span>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}

        </div>
      )}
      {activeTab === 'history' && (
        <div className="max-w-6xl mx-auto space-y-6">
          {/* UPLOAD SECTION */}
          <div className="bg-slate-800 border border-slate-700 rounded-lg p-6 shadow-xl">
            <h2 className="text-xl font-bold text-emerald-400 mb-2">Trade History & Backtest</h2>
            <p className="text-sm text-slate-400 mb-4">Upload your Robinhood CSV export to analyze real trades and replay them against the regime engine using historical SPY data.</p>
            <div className="flex flex-col sm:flex-row gap-3 items-start">
              <input type="file" accept=".csv" onChange={e => setSelectedFile(e.target.files[0])} className="text-sm text-slate-300 file:mr-3 file:py-2 file:px-4 file:rounded file:border-0 file:bg-slate-700 file:text-slate-200 file:font-semibold hover:file:bg-slate-600 file:cursor-pointer" />
              <button onClick={() => selectedFile && uploadTradeHistory(selectedFile)} disabled={!selectedFile || historyLoading} className={`px-5 py-2 rounded font-semibold text-sm transition-colors ${!selectedFile || historyLoading ? 'bg-slate-700 text-slate-500' : 'bg-blue-600 hover:bg-blue-500 text-white'}`}>
                {historyLoading ? 'Parsing...' : 'Parse Trades'}
              </button>
              <button onClick={() => selectedFile && runBacktest(selectedFile)} disabled={!selectedFile || backtestLoading} className={`px-5 py-2 rounded font-semibold text-sm transition-colors ${!selectedFile || backtestLoading ? 'bg-slate-700 text-slate-500' : 'bg-emerald-600 hover:bg-emerald-500 text-white'}`}>
                {backtestLoading ? 'Running Backtest...' : 'Parse + Backtest'}
              </button>
            </div>
            {historyError && <div className="mt-3 text-sm text-red-400">{historyError}</div>}
            {backtestLoading && <div className="mt-3 text-sm text-amber-400 animate-pulse">Fetching historical data from Alpaca and running regime analysis for each trade date... This may take a minute.</div>}
          </div>

          {/* TRADE STATS */}
          {tradeHistory?.stats && tradeHistory.stats.total_trades > 0 && (
            <div className="bg-slate-800 border border-slate-700 rounded-lg p-6 shadow-xl">
              <h3 className="text-lg font-bold text-slate-200 mb-4">Performance Summary</h3>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
                <div className="bg-slate-900 rounded p-3 text-center">
                  <div className="text-xs text-slate-500">Total Trades</div>
                  <div className="text-2xl font-bold text-slate-100">{tradeHistory.stats.total_trades}</div>
                </div>
                <div className="bg-slate-900 rounded p-3 text-center">
                  <div className="text-xs text-slate-500">Win Rate</div>
                  <div className={`text-2xl font-bold ${tradeHistory.stats.win_rate >= 70 ? 'text-emerald-400' : tradeHistory.stats.win_rate >= 50 ? 'text-amber-400' : 'text-red-400'}`}>{tradeHistory.stats.win_rate}%</div>
                </div>
                <div className="bg-slate-900 rounded p-3 text-center">
                  <div className="text-xs text-slate-500">Total P/L</div>
                  <div className={`text-2xl font-bold ${tradeHistory.stats.total_pl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>${tradeHistory.stats.total_pl}</div>
                </div>
                <div className="bg-slate-900 rounded p-3 text-center">
                  <div className="text-xs text-slate-500">Profit Factor</div>
                  <div className="text-2xl font-bold text-slate-100">{tradeHistory.stats.profit_factor === Infinity ? '∞' : tradeHistory.stats.profit_factor}</div>
                </div>
              </div>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
                <div className="bg-slate-900 rounded p-3 text-center">
                  <div className="text-xs text-slate-500">Wins / Losses</div>
                  <div className="text-lg font-bold"><span className="text-emerald-400">{tradeHistory.stats.wins}</span> / <span className="text-red-400">{tradeHistory.stats.losses}</span></div>
                </div>
                <div className="bg-slate-900 rounded p-3 text-center">
                  <div className="text-xs text-slate-500">Put Win Rate</div>
                  <div className="text-lg font-bold text-slate-200">{tradeHistory.stats.put_win_rate}% <span className="text-xs text-slate-500">({tradeHistory.stats.put_trades})</span></div>
                </div>
                <div className="bg-slate-900 rounded p-3 text-center">
                  <div className="text-xs text-slate-500">Call Win Rate</div>
                  <div className="text-lg font-bold text-slate-200">{tradeHistory.stats.call_win_rate}% <span className="text-xs text-slate-500">({tradeHistory.stats.call_trades})</span></div>
                </div>
                <div className="bg-slate-900 rounded p-3 text-center">
                  <div className="text-xs text-slate-500">Avg P/L per Trade</div>
                  <div className={`text-lg font-bold ${tradeHistory.stats.avg_pl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>${tradeHistory.stats.avg_pl}</div>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div className="bg-emerald-900/20 border border-emerald-700/40 rounded p-3">
                  <div className="text-xs text-emerald-400 font-bold">Best Trade</div>
                  <div className="text-sm text-slate-200">{tradeHistory.stats.best_trade.date} — {tradeHistory.stats.best_trade.label}</div>
                  <div className="text-lg font-bold text-emerald-400">${tradeHistory.stats.best_trade.pl}</div>
                </div>
                <div className="bg-red-900/20 border border-red-700/40 rounded p-3">
                  <div className="text-xs text-red-400 font-bold">Worst Trade</div>
                  <div className="text-sm text-slate-200">{tradeHistory.stats.worst_trade.date} — {tradeHistory.stats.worst_trade.label}</div>
                  <div className="text-lg font-bold text-red-400">${tradeHistory.stats.worst_trade.pl}</div>
                </div>
              </div>
              {tradeHistory.stats.outcome_distribution && (
                <div className="mt-4 bg-slate-900 rounded p-3">
                  <div className="text-xs text-slate-500 mb-2">Outcome Distribution</div>
                  <div className="flex flex-wrap gap-2">
                    {Object.entries(tradeHistory.stats.outcome_distribution).map(([k, v]) => (
                      <span key={k} className={`text-xs font-bold px-2 py-1 rounded ${
                        k === 'EXPIRED' ? 'bg-emerald-900/50 text-emerald-400' :
                        k === 'ASSIGNED' ? 'bg-red-900/50 text-red-400' :
                        k === 'CLOSED' ? 'bg-blue-900/50 text-blue-400' :
                        'bg-slate-700 text-slate-300'
                      }`}>{k}: {v}</span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* BACKTEST RESULTS */}
          {backtestResult?.summary && (
            <div className="bg-slate-800 border border-slate-700 rounded-lg p-6 shadow-xl">
              <h3 className="text-lg font-bold text-slate-200 mb-2">Backtest: System vs Your Trades</h3>
              <p className="text-xs text-slate-400 mb-4">Each trade date was replayed through the regime engine using historical SPY 5-min bars. The system verdict shows what it would have recommended for your actual strikes.</p>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
                <div className="bg-slate-900 rounded p-3 text-center">
                  <div className="text-xs text-slate-500">Days Analyzed</div>
                  <div className="text-2xl font-bold text-slate-100">{backtestResult.summary.days_processed}</div>
                </div>
                <div className="bg-slate-900 rounded p-3 text-center">
                  <div className="text-xs text-slate-500">System Exit Flags</div>
                  <div className="text-2xl font-bold text-amber-400">{backtestResult.summary.system_exit_flags}</div>
                </div>
                <div className="bg-slate-900 rounded p-3 text-center">
                  <div className="text-xs text-slate-500">System Safe Flags</div>
                  <div className="text-2xl font-bold text-emerald-400">{backtestResult.summary.system_safe_flags}</div>
                </div>
                <div className="bg-slate-900 rounded p-3 text-center">
                  <div className="text-xs text-slate-500">Potential Savings</div>
                  <div className="text-2xl font-bold text-blue-400">${backtestResult.summary.potential_savings}</div>
                </div>
              </div>
              {backtestResult.summary.alignment && (
                <div className="bg-slate-900 rounded p-3 mb-4">
                  <div className="text-xs text-slate-500 mb-2">Alignment Analysis</div>
                  <div className="flex flex-wrap gap-2">
                    {Object.entries(backtestResult.summary.alignment).map(([k, v]) => (
                      <span key={k} className={`text-xs font-bold px-2 py-1 rounded ${
                        k === 'ALIGNED_WIN' ? 'bg-emerald-900/50 text-emerald-400' :
                        k === 'SYSTEM_CORRECT' ? 'bg-blue-900/50 text-blue-400' :
                        k === 'LUCKY_WIN' ? 'bg-amber-900/50 text-amber-400' :
                        k === 'BOTH_WRONG' ? 'bg-red-900/50 text-red-400' :
                        'bg-slate-700 text-slate-300'
                      }`}>{k.replace(/_/g, ' ')}: {v}</span>
                    ))}
                  </div>
                </div>
              )}

              {/* DAILY BREAKDOWN TABLE */}
              {backtestResult.daily_results && (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-xs text-slate-500 border-b border-slate-700">
                        <th className="text-left py-2 px-2">Date</th>
                        <th className="text-left px-2">Spread</th>
                        <th className="text-right px-2">P/L</th>
                        <th className="text-right px-2">Min Moat</th>
                        <th className="text-center px-2">System</th>
                        <th className="text-center px-2">Alignment</th>
                        <th className="text-left px-2">Detail</th>
                      </tr>
                    </thead>
                    <tbody>
                      {backtestResult.daily_results.flatMap((day) =>
                        day.spreads.map((s, j) => (
                          <tr key={`${day.date}-${j}`} className="border-b border-slate-800 hover:bg-slate-700/30">
                            <td className="py-2 px-2 font-mono text-slate-300">{day.display_date}</td>
                            <td className="px-2">
                              <span className={`text-xs font-bold px-1.5 py-0.5 rounded ${s.type === 'Put Spread' ? 'bg-red-900/40 text-red-400' : 'bg-emerald-900/40 text-emerald-400'}`}>{s.label}</span>
                              <span className="text-[10px] text-slate-500 ml-1">x{s.contracts}</span>
                            </td>
                            <td className={`text-right px-2 font-bold ${s.won ? 'text-emerald-400' : 'text-red-400'}`}>${s.net_pl}</td>
                            <td className={`text-right px-2 font-bold ${s.min_moat <= 0 ? 'text-red-500' : s.min_moat <= 15 ? 'text-red-400' : s.min_moat <= 30 ? 'text-amber-400' : 'text-slate-300'}`}>{s.min_moat} pts</td>
                            <td className="text-center px-2">
                              <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
                                s.system_verdict === 'SAFE' ? 'bg-emerald-900/50 text-emerald-400' :
                                s.system_verdict === 'EXIT_RECOMMENDED' ? 'bg-red-900/50 text-red-400' :
                                'bg-amber-900/50 text-amber-400'
                              }`}>{s.system_verdict}</span>
                            </td>
                            <td className="text-center px-2">
                              <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
                                s.alignment === 'ALIGNED_WIN' ? 'bg-emerald-900/50 text-emerald-400' :
                                s.alignment === 'SYSTEM_CORRECT' ? 'bg-blue-900/50 text-blue-400' :
                                s.alignment === 'LUCKY_WIN' ? 'bg-amber-900/50 text-amber-400' :
                                s.alignment === 'BOTH_WRONG' ? 'bg-red-900/50 text-red-400' :
                                'bg-slate-700 text-slate-300'
                              }`}>{s.alignment.replace(/_/g, ' ')}</span>
                            </td>
                            <td className="px-2 text-xs text-slate-400 max-w-[250px] truncate">{s.system_detail}</td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </div>
      )}
      {activeTab === 'manual' && (
        <div className="max-w-4xl mx-auto space-y-6">

          {/* --- QUICK START --- */}
          <div className="bg-slate-800 border border-slate-700 rounded-lg p-8 shadow-xl">
            <h2 className="text-2xl font-bold text-emerald-400 mb-2">System Manual & User Guide</h2>
            <p className="text-slate-400 text-sm mb-6 border-b border-slate-700 pb-4">0DTE Algorithmic Decision Support Matrix V5.0</p>

            <h3 className="text-lg font-semibold text-slate-200 mb-3">Quick Start</h3>
            <ol className="list-decimal list-inside text-sm text-slate-300 space-y-2 mb-6">
              <li>Open the <span className="text-emerald-400 font-semibold">Live Dashboard</span> tab. The system auto-fetches SPY data from Alpaca every 30 seconds and computes the market regime.</li>
              <li>Check the <span className="text-amber-400 font-semibold">Market State</span> to see the current regime (A, B, or C) and the <span className="font-semibold text-slate-100">Smart Moat</span> width.</li>
              <li>Check the <span className="text-emerald-400 font-semibold">Trading Window</span> panel. It tells you if now is a good time to enter trades (entry quality score from 0 to 100).</li>
              <li>Before placing a trade, verify your planned short strike is at least as far away as the Smart Moat width. Use the <span className="text-emerald-400 font-semibold">Trade Analyzer</span> to score your setup before entering.</li>
              <li>After entering a position in your broker, log it in the <span className="text-emerald-400 font-semibold">Smart Ledger</span> panel on the right.</li>
              <li>The system monitors each position in real-time. Follow the exit directives it displays — they adjust based on time of day and market conditions.</li>
              <li>When you close a position in your broker, click the <span className="text-red-400 font-semibold">X</span> button to remove it from tracking.</li>
            </ol>
          </div>

          {/* --- WHAT IS 0DTE? --- */}
          <div className="bg-slate-800 border border-slate-700 rounded-lg p-8 shadow-xl">
            <h3 className="text-lg font-semibold text-slate-200 mb-4">What is 0DTE Trading?</h3>
            <div className="text-sm text-slate-300 space-y-3">
              <p><span className="font-semibold text-slate-100">0DTE</span> stands for "zero days to expiration." These are options contracts that expire the same day they are traded.</p>
              <p>The strategy this system supports is <span className="font-semibold text-emerald-400">selling credit spreads</span>. You sell an option at one strike and buy a protective option further out. You collect a small premium (credit) upfront. If SPX stays away from your short strike until 4:00 PM ET, both options expire worthless and you keep the credit as profit.</p>
              <p>The two key concepts:</p>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mt-2">
                <div className="bg-slate-900/50 p-3 rounded border border-slate-700">
                  <span className="font-bold text-emerald-400">Theta (Time Decay)</span>
                  <p className="text-slate-400 mt-1">Your friend. As the clock ticks toward 4 PM, the option you sold loses value. This is how you profit — the premium you collected melts away to zero.</p>
                </div>
                <div className="bg-slate-900/50 p-3 rounded border border-slate-700">
                  <span className="font-bold text-red-400">Gamma (Movement Risk)</span>
                  <p className="text-slate-400 mt-1">Your enemy. If SPX moves toward your strike, losses accelerate. The closer to expiry, the more violent these moves become. This is why moat distance matters.</p>
                </div>
              </div>
            </div>
          </div>

          {/* --- MARKET STATES --- */}
          <div className="bg-slate-800 border border-slate-700 rounded-lg p-8 shadow-xl">
            <h3 className="text-lg font-semibold text-slate-200 mb-4">Understanding Market States</h3>
            <p className="text-sm text-slate-400 mb-4">The engine scores the market from 0 to 4 based on four indicators. Higher scores mean more chop and less trend. The score maps to three operational states:</p>

            <div className="space-y-4">
              <div className="bg-emerald-900/20 border border-emerald-700/50 rounded-lg p-4">
                <div className="flex items-center gap-2 mb-2">
                  <span className="bg-emerald-600 text-white text-xs font-bold px-2 py-0.5 rounded">Score 0-1</span>
                  <h4 className="font-bold text-emerald-400">State A: Clean Trend</h4>
                </div>
                <ul className="text-sm text-slate-300 space-y-1 ml-4">
                  <li><span className="font-semibold text-slate-100">What it means:</span> The market has a clear directional bias. EMAs are separated, RSI shows momentum, CHOP is low, and price is moving efficiently.</li>
                  <li><span className="font-semibold text-slate-100">What to do:</span> Directional credit spreads are authorized (e.g., Put Spreads if bullish). You can use tighter moats (35-40 SPX points).</li>
                  <li><span className="font-semibold text-slate-100">Stop-loss rule:</span> Strict 200% of premium received. If you collected $0.80, exit if the spread hits $1.60 debit.</li>
                </ul>
              </div>

              <div className="bg-amber-900/20 border border-amber-700/50 rounded-lg p-4">
                <div className="flex items-center gap-2 mb-2">
                  <span className="bg-amber-600 text-white text-xs font-bold px-2 py-0.5 rounded">Score 2</span>
                  <h4 className="font-bold text-amber-400">State B: Moderate Chop</h4>
                </div>
                <ul className="text-sm text-slate-300 space-y-1 ml-4">
                  <li><span className="font-semibold text-slate-100">What it means:</span> Mixed signals. Some indicators show trend, others show consolidation. False breakouts possible.</li>
                  <li><span className="font-semibold text-slate-100">What to do:</span> Prefer neutral strategies (Iron Condors). Widen your moat to 50-60 SPX points.</li>
                  <li><span className="font-semibold text-slate-100">Stop-loss rule:</span> Hybrid: Exit at 250% premium OR if SPX moves within 15 points of your strike.</li>
                </ul>
              </div>

              <div className="bg-red-900/20 border border-red-700/50 rounded-lg p-4">
                <div className="flex items-center gap-2 mb-2">
                  <span className="bg-red-600 text-white text-xs font-bold px-2 py-0.5 rounded">Score 3-4</span>
                  <h4 className="font-bold text-red-400">State C: High Entropy / Whipsaw</h4>
                </div>
                <ul className="text-sm text-slate-300 space-y-1 ml-4">
                  <li><span className="font-semibold text-slate-100">What it means:</span> All indicators show chop. High risk of false breakouts and sudden reversals.</li>
                  <li><span className="font-semibold text-slate-100">What to do:</span> Strictly neutral deployments only. Push moats to 70+ SPX points. Consider sitting out.</li>
                  <li><span className="font-semibold text-slate-100">Stop-loss rule:</span> Ignore premium spikes (they're caused by IV, not real moves). Exit only if SPX physically approaches your strike.</li>
                </ul>
              </div>
            </div>
          </div>

          {/* --- SMART MOAT --- */}
          <div className="bg-slate-800 border border-slate-700 rounded-lg p-8 shadow-xl">
            <h3 className="text-lg font-semibold text-slate-200 mb-4">Smart Moat System</h3>
            <p className="text-sm text-slate-400 mb-4">The "moat" is the distance in SPX points between the current price and your short strike. A wider moat = more safety. The Smart Moat dynamically adjusts the recommended width using five factors:</p>
            <div className="space-y-3 text-sm">
              <div className="bg-slate-900/50 p-3 rounded border border-slate-700">
                <span className="font-bold text-blue-400">VIX Expected Move</span>
                <p className="text-slate-400 mt-1">The base moat is calculated from the VIX (market fear index). Higher VIX = wider moat. The math: SPX price x (VIX/100) x sqrt(hours remaining / trading hours per year). This replaces guesswork with a mathematically grounded starting point.</p>
              </div>
              <div className="bg-slate-900/50 p-3 rounded border border-slate-700">
                <span className="font-bold text-slate-100">Range Context</span>
                <p className="text-slate-400 mt-1">If the day's range is tight (&lt;40 pts), the moat shrinks. If the range is expanding (&gt;110 pts), the moat widens. A tight range means the market isn't moving much, so you don't need as much buffer.</p>
              </div>
              <div className="bg-slate-900/50 p-3 rounded border border-slate-700">
                <span className="font-bold text-slate-100">Time Decay Credit</span>
                <p className="text-slate-400 mt-1">Positions that have survived most of the day deserve smaller moats. With 1 hour left, theta is aggressively decaying option premiums, so you need less buffer. The moat shrinks up to 45% in the final hour.</p>
              </div>
              <div className="bg-slate-900/50 p-3 rounded border border-slate-700">
                <span className="font-bold text-slate-100">Calendar Events</span>
                <p className="text-slate-400 mt-1">On high-volatility days (FOMC, CPI, Jobs Report, OPEX), moats are automatically widened. For example, FOMC days add a 40% buffer. The system knows the 2026 event calendar.</p>
              </div>
            </div>
          </div>

          {/* --- RISK ZONES --- */}
          <div className="bg-slate-800 border border-slate-700 rounded-lg p-8 shadow-xl">
            <h3 className="text-lg font-semibold text-slate-200 mb-4">Position Risk Zones</h3>
            <p className="text-sm text-slate-400 mb-4">Each tracked position gets a color-coded status based on its moat distance:</p>

            <div className="space-y-3">
              <div className="flex items-start gap-3 bg-slate-900/50 p-4 rounded border border-slate-700">
                <span className="bg-emerald-500 rounded-full w-3 h-3 mt-1 flex-shrink-0"></span>
                <div>
                  <span className="font-bold text-emerald-400">SAFE ZONE (&gt; 25 points)</span>
                  <p className="text-sm text-slate-300">Healthy buffer. Theta is working for you. No action needed — let time do the work.</p>
                </div>
              </div>
              <div className="flex items-start gap-3 bg-slate-900/50 p-4 rounded border border-slate-700">
                <span className="bg-amber-400 rounded-full w-3 h-3 mt-1 flex-shrink-0"></span>
                <div>
                  <span className="font-bold text-amber-400">WARNING ZONE (10-25 points)</span>
                  <p className="text-sm text-slate-300">Getting close. The system activates time-aware stop-loss protocols that change based on how much time is left (see Time-Aware Exits below).</p>
                </div>
              </div>
              <div className="flex items-start gap-3 bg-slate-900/50 p-4 rounded border border-slate-700">
                <span className="bg-red-500 rounded-full w-3 h-3 mt-1 flex-shrink-0"></span>
                <div>
                  <span className="font-bold text-red-400">GAMMA TRAP (0-10 points)</span>
                  <p className="text-sm text-slate-300">Critical danger. A 5-minute verification timer starts. If SPX stays breached for 5 minutes, a <span className="text-red-400 font-bold">CRITICAL EJECT</span> is issued. If price recovers (whipsaw), the timer resets — this prevents you from getting stopped out on a false spike.</p>
                </div>
              </div>
            </div>
          </div>

          {/* --- TIME-AWARE EXIT STRATEGIES --- */}
          <div className="bg-slate-800 border border-slate-700 rounded-lg p-8 shadow-xl">
            <h3 className="text-lg font-semibold text-slate-200 mb-4">Time-Aware Exit Strategies</h3>
            <p className="text-sm text-slate-400 mb-4">When a position enters the Warning Zone, the system does not blindly eject. Instead, it adjusts its behavior based on time remaining until 4:00 PM ET:</p>

            <div className="space-y-3 text-sm">
              <div className="bg-slate-900/50 p-4 rounded border border-emerald-700/50">
                <span className="font-bold text-emerald-400">Final 30 Minutes (3:30-4:00 PM)</span>
                <p className="text-slate-300 mt-1">HOLD unless your strike is actually breached. Premium spikes are ignored entirely because theta decay is at maximum — options are melting to zero. Don't exit a winning position over a temporary price blip.</p>
              </div>
              <div className="bg-slate-900/50 p-4 rounded border border-blue-700/50">
                <span className="font-bold text-blue-400">Final Hour (3:00-3:30 PM)</span>
                <p className="text-slate-300 mt-1">Premium-based stops are suspended. The system only exits if the underlying asset sustains a breach for 10+ minutes. Short-lived spikes are filtered out.</p>
              </div>
              <div className="bg-slate-900/50 p-4 rounded border border-amber-700/50">
                <span className="font-bold text-amber-400">1-2 Hours Left (2:00-3:00 PM)</span>
                <p className="text-slate-300 mt-1">Stops are widened to 250% and require 5 minutes of verification. This prevents whipsaw exits during the volatile afternoon session.</p>
              </div>
              <div className="bg-slate-900/50 p-4 rounded border border-slate-700">
                <span className="font-bold text-slate-100">&gt; 2 Hours Left (Morning/Midday)</span>
                <p className="text-slate-300 mt-1">Standard stop-loss rules apply based on the current Market State (A, B, or C).</p>
              </div>
            </div>
          </div>

          {/* --- VIX & EXPECTED MOVE --- */}
          <div className="bg-slate-800 border border-slate-700 rounded-lg p-8 shadow-xl">
            <h3 className="text-lg font-semibold text-slate-200 mb-4">VIX & Expected Move</h3>
            <div className="text-sm text-slate-300 space-y-3">
              <p>The <span className="font-semibold text-slate-100">VIX</span> is the market's "fear gauge." It measures how much the market expects SPX to move. A VIX of 15 is calm; 25+ is nervous; 35+ is panicking.</p>
              <p>The dashboard shows three derived values from the VIX:</p>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                <div className="bg-slate-900/50 p-3 rounded border border-slate-700">
                  <span className="font-bold text-blue-400">1-sigma Move</span>
                  <p className="text-slate-400 mt-1">The expected range that SPX will stay within ~68% of the time. Think of it as the "normal" range for the rest of the day.</p>
                </div>
                <div className="bg-slate-900/50 p-3 rounded border border-slate-700">
                  <span className="font-bold text-amber-400">2-sigma Move</span>
                  <p className="text-slate-400 mt-1">The wider range covering ~95% of outcomes. Your strike should ideally be outside this range.</p>
                </div>
                <div className="bg-slate-900/50 p-3 rounded border border-slate-700">
                  <span className="font-bold text-emerald-400">Recommended Moat</span>
                  <p className="text-slate-400 mt-1">Set at 1.5x the 1-sigma move. This is the math-based minimum distance for your short strike.</p>
                </div>
              </div>
            </div>
          </div>

          {/* --- TRADING WINDOWS --- */}
          <div className="bg-slate-800 border border-slate-700 rounded-lg p-8 shadow-xl">
            <h3 className="text-lg font-semibold text-slate-200 mb-4">Trading Windows</h3>
            <p className="text-sm text-slate-400 mb-4">The market behaves differently at different times of day. The system classifies the current period and gives each an entry quality score (0-100):</p>
            <div className="space-y-2 text-sm">
              <div className="flex items-center gap-3 bg-slate-900/50 p-3 rounded border border-red-700/30">
                <span className="text-red-400 font-bold w-32 shrink-0">9:30 - 10:00</span>
                <span className="text-slate-300">Opening Drive (score: 20). Wild volatility, fake breakouts. Avoid new entries.</span>
              </div>
              <div className="flex items-center gap-3 bg-slate-900/50 p-3 rounded border border-emerald-700/30">
                <span className="text-emerald-400 font-bold w-32 shrink-0">10:00 - 11:30</span>
                <span className="text-slate-300">Trend Establishment (score: 90). Best window for 0DTE entries. Regime signals most reliable.</span>
              </div>
              <div className="flex items-center gap-3 bg-slate-900/50 p-3 rounded border border-slate-700">
                <span className="text-slate-300 font-bold w-32 shrink-0">11:30 - 1:00</span>
                <span className="text-slate-300">Lunch Lull (score: 65). Lower volume, tighter ranges. Good for cautious entries.</span>
              </div>
              <div className="flex items-center gap-3 bg-slate-900/50 p-3 rounded border border-slate-700">
                <span className="text-slate-300 font-bold w-32 shrink-0">1:00 - 2:30</span>
                <span className="text-slate-300">Afternoon Session (score: 55). Trend can reverse. Use caution.</span>
              </div>
              <div className="flex items-center gap-3 bg-slate-900/50 p-3 rounded border border-amber-700/30">
                <span className="text-amber-400 font-bold w-32 shrink-0">2:30 - 3:00</span>
                <span className="text-slate-300">Pre-Power Hour (score: 25). Avoid new positions. Manage existing risk.</span>
              </div>
              <div className="flex items-center gap-3 bg-slate-900/50 p-3 rounded border border-red-700/30">
                <span className="text-red-400 font-bold w-32 shrink-0">3:00 - 4:00</span>
                <span className="text-slate-300">Power Hour / Final Minutes (score: 0-10). No new entries. Hold safe positions. Let theta work.</span>
              </div>
            </div>
          </div>

          {/* --- REGIME TRANSITION --- */}
          <div className="bg-slate-800 border border-slate-700 rounded-lg p-8 shadow-xl">
            <h3 className="text-lg font-semibold text-slate-200 mb-4">Regime Transition Prediction</h3>
            <p className="text-sm text-slate-400 mb-4">The system compares current indicator readings to where they were 30 minutes ago. This tells you if the market regime is shifting:</p>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-sm">
              <div className="bg-red-900/20 p-3 rounded border border-red-700/50">
                <span className="font-bold text-red-400">DETERIORATING</span>
                <p className="text-slate-400 mt-1">Regime is degrading fast. Chop increasing, trend fading. Widen moats and avoid new entries.</p>
              </div>
              <div className="bg-amber-900/20 p-3 rounded border border-amber-700/50">
                <span className="font-bold text-amber-400">SOFTENING</span>
                <p className="text-slate-400 mt-1">Trend is starting to weaken. Not critical yet, but watch for a full State transition.</p>
              </div>
              <div className="bg-emerald-900/20 p-3 rounded border border-emerald-700/50">
                <span className="font-bold text-emerald-400">IMPROVING</span>
                <p className="text-slate-400 mt-1">Regime is getting stronger. Trend forming, chop decreasing. Tighter moats may be viable.</p>
              </div>
              <div className="bg-blue-900/20 p-3 rounded border border-blue-700/50">
                <span className="font-bold text-blue-400">FIRMING</span>
                <p className="text-slate-400 mt-1">Chop is beginning to resolve. A directional move may be forming.</p>
              </div>
            </div>
            <p className="text-sm text-slate-500 mt-3">The confidence percentage tells you how strong the signal is. Below 50% = noise. Above 70% = pay attention.</p>
          </div>

          {/* --- INDICATORS --- */}
          <div className="bg-slate-800 border border-slate-700 rounded-lg p-8 shadow-xl">
            <h3 className="text-lg font-semibold text-slate-200 mb-4">Indicator Reference</h3>
            <p className="text-sm text-slate-400 mb-4">The dashboard shows four indicator intensity bars (0.0 = trending, 1.0 = max chop). Here's what each measures:</p>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
              <div className="bg-slate-900/50 p-4 rounded border border-slate-700">
                <span className="font-bold text-slate-100">EMA 9 / EMA 21</span>
                <p className="text-slate-400 mt-1">Exponential Moving Averages — smoothed price trends. When far apart, the market is trending. When compressed, no conviction. Price above both = bullish. Below both = bearish.</p>
              </div>
              <div className="bg-slate-900/50 p-4 rounded border border-slate-700">
                <span className="font-bold text-slate-100">RSI (14)</span>
                <p className="text-slate-400 mt-1">Relative Strength Index. Measures momentum on a 0-100 scale. Stuck at 45-55 = dead zone (no momentum). Above 60 or below 40 = directional energy.</p>
              </div>
              <div className="bg-slate-900/50 p-4 rounded border border-slate-700">
                <span className="font-bold text-slate-100">CHOP (14)</span>
                <p className="text-slate-400 mt-1">Choppiness Index. Above 61.8 = choppy, range-bound. Below 38.2 = strong trend. The most direct measure of whether price action is noisy or clean.</p>
              </div>
              <div className="bg-slate-900/50 p-4 rounded border border-slate-700">
                <span className="font-bold text-slate-100">Efficiency Ratio (ER)</span>
                <p className="text-slate-400 mt-1">How efficiently price moves from point A to B. Below 0.20 = lots of movement but going nowhere. Above 0.50 = clean directional move.</p>
              </div>
              <div className="bg-slate-900/50 p-4 rounded border border-slate-700 md:col-span-2">
                <span className="font-bold text-slate-100">VWAP Deviation</span>
                <p className="text-slate-400 mt-1">How far SPY has stretched from its average price. If &gt;0.35%, the system activates a <span className="text-amber-400 font-semibold">VWAP Elasticity Override</span>: stops are suspended for 10 minutes. Like a rubber band — the further it stretches, the more likely it snaps back.</p>
              </div>
            </div>
          </div>

          {/* --- CALENDAR EVENTS --- */}
          <div className="bg-slate-800 border border-slate-700 rounded-lg p-8 shadow-xl">
            <h3 className="text-lg font-semibold text-slate-200 mb-4">Calendar Event Awareness</h3>
            <p className="text-sm text-slate-400 mb-4">Certain days have predictably higher volatility. The system automatically detects these and widens moats:</p>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-sm">
              <div className="bg-slate-900/50 p-3 rounded border border-red-700/50">
                <span className="font-bold text-red-400">FOMC Days (+40% moat)</span>
                <p className="text-slate-400 mt-1">Federal Reserve interest rate decisions. Massive volatility around the 2:00 PM announcement. The most dangerous days for 0DTE.</p>
              </div>
              <div className="bg-slate-900/50 p-3 rounded border border-amber-700/50">
                <span className="font-bold text-amber-400">CPI / Jobs Report (+30% moat)</span>
                <p className="text-slate-400 mt-1">Inflation and employment data releases. Usually pre-market (8:30 AM) but volatility persists into the trading session.</p>
              </div>
              <div className="bg-slate-900/50 p-3 rounded border border-amber-700/50">
                <span className="font-bold text-amber-400">Quarterly OPEX (+50% moat)</span>
                <p className="text-slate-400 mt-1">Third Friday of Mar/Jun/Sep/Dec. Trillions in options expire. Maximum gamma pinning effects and erratic price action.</p>
              </div>
              <div className="bg-slate-900/50 p-3 rounded border border-slate-700">
                <span className="font-bold text-slate-100">Monthly OPEX (+15% moat)</span>
                <p className="text-slate-400 mt-1">Third Friday of every month. Elevated options volume and pinning effects, but less extreme than quarterly.</p>
              </div>
            </div>
          </div>

          {/* --- GEX (GAMMA EXPOSURE) --- */}
          <div className="bg-slate-800 border border-slate-700 rounded-lg p-8 shadow-xl">
            <h3 className="text-lg font-semibold text-slate-200 mb-4">Gamma Exposure (GEX)</h3>
            <p className="text-sm text-slate-400 mb-4">GEX measures the net gamma exposure of market makers across all option strikes. It tells you whether the market is likely to <span className="text-emerald-400 font-semibold">mean-revert</span> (stay in a range) or <span className="text-red-400 font-semibold">trend</span> (break out). Data is sourced from ThetaData, refreshed every 2 minutes.</p>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-sm mb-4">
              <div className="bg-emerald-900/20 p-3 rounded border border-emerald-700/50">
                <span className="font-bold text-emerald-400">POSITIVE GEX</span>
                <p className="text-slate-400 mt-1">Dealers are long gamma. They buy dips and sell rallies, acting as a stabilizer. Ranges hold, breakouts fade. Safer for credit spreads. Smart Moat tightened ×0.90.</p>
              </div>
              <div className="bg-red-900/20 p-3 rounded border border-red-700/50">
                <span className="font-bold text-red-400">NEGATIVE GEX</span>
                <p className="text-slate-400 mt-1">Dealers are short gamma. They sell into selloffs and buy into rallies, amplifying moves. Ranges break, trends accelerate. Wider moats needed. Smart Moat widened ×1.15.</p>
              </div>
              <div className="bg-slate-900/50 p-3 rounded border border-slate-700">
                <span className="font-bold text-slate-100">NEUTRAL</span>
                <p className="text-slate-400 mt-1">Balanced gamma. No strong directional bias from market maker hedging. Standard moat applies.</p>
              </div>
            </div>
            <div className="space-y-2 text-sm">
              <div className="bg-slate-900/50 p-3 rounded border border-slate-700">
                <span className="font-bold text-emerald-400">Gamma Wall</span>
                <span className="text-slate-400"> — The strike with the highest positive GEX. Acts as a price magnet — SPX tends to gravitate toward this level throughout the day.</span>
              </div>
              <div className="bg-slate-900/50 p-3 rounded border border-slate-700">
                <span className="font-bold text-red-400">Put Wall</span>
                <span className="text-slate-400"> — The strike with the most negative GEX. Acts as a support floor — strong buying pressure from dealer hedging makes it harder for SPX to break below.</span>
              </div>
              <div className="bg-slate-900/50 p-3 rounded border border-slate-700">
                <span className="font-bold text-blue-400">Call Wall</span>
                <span className="text-slate-400"> — The strike with the highest call-side GEX. Acts as a resistance ceiling — dealer selling pressure makes it harder for SPX to break above.</span>
              </div>
            </div>
            <p className="text-xs text-slate-500 mt-3">GEX is integrated into Smart Moat, Position Evaluation (wall proximity warnings), and Trade Analyzer (wall proximity scoring). The backtester also fetches historical GEX per trade date.</p>
          </div>

          {/* --- TRADE HISTORY & BACKTESTER --- */}
          <div className="bg-slate-800 border border-slate-700 rounded-lg p-8 shadow-xl">
            <h3 className="text-lg font-semibold text-slate-200 mb-4">Trade History & Backtester</h3>
            <p className="text-sm text-slate-400 mb-4">Upload your Robinhood CSV trade history to analyze past trades and replay them through the regime engine using historical market data.</p>
            <div className="space-y-3 text-sm">
              <div className="bg-slate-900/50 p-3 rounded border border-slate-700">
                <span className="font-bold text-slate-100">Parse Trades</span>
                <p className="text-slate-400 mt-1">Extracts credit spreads from your Robinhood CSV. Identifies STO/BTO pairs, computes P/L per spread, and shows win rate, profit factor, put/call splits, and outcome distribution.</p>
              </div>
              <div className="bg-slate-900/50 p-3 rounded border border-slate-700">
                <span className="font-bold text-slate-100">Parse + Backtest</span>
                <p className="text-slate-400 mt-1">Fetches historical SPY 5-min bars from Alpaca for each trade date and replays the full day through the regime engine. For each spread, it tracks the moat distance to your actual strikes and determines what the system would have recommended.</p>
              </div>
              <div className="bg-slate-900/50 p-3 rounded border border-slate-700">
                <span className="font-bold text-emerald-400">System Verdicts</span>
                <p className="text-slate-400 mt-1"><span className="text-emerald-400">SAFE</span> = spread stayed outside danger zones all day. <span className="text-amber-400">CAUTION</span> = warning zone entered but regime allowed holding. <span className="text-red-400">EXIT_RECOMMENDED</span> = system would have flagged exit.</p>
              </div>
              <div className="bg-slate-900/50 p-3 rounded border border-slate-700">
                <span className="font-bold text-blue-400">Alignment Labels</span>
                <p className="text-slate-400 mt-1"><span className="text-emerald-400">ALIGNED WIN</span> = system agreed, safe trade won. <span className="text-amber-400">LUCKY WIN</span> = system would have exited early, you held and won. <span className="text-red-400">SYSTEM CORRECT</span> = system flagged exit, following it would have helped. <span className="text-slate-300">BOTH WRONG</span> = system missed the danger too.</p>
              </div>
            </div>
            <p className="text-xs text-slate-500 mt-3">Note: Robinhood CSV has no entry timestamps. The backtester replays the entire day and shows the full regime timeline instead of guessing when you entered.</p>
          </div>

          {/* --- SPX PROXY --- */}
          <div className="bg-slate-800 border border-slate-700 rounded-lg p-8 shadow-xl">
            <h3 className="text-lg font-semibold text-slate-200 mb-4">SPX Proxy Methodology</h3>
            <p className="text-sm text-slate-300 mb-3">This system trades <span className="text-emerald-400 font-semibold">SPX 0DTE options</span> but uses <span className="text-emerald-400 font-semibold">SPY ETF</span> data from Alpaca as a proxy, since Alpaca does not provide direct SPX index data. The live SPX price comes from Yahoo Finance.</p>
            <div className="bg-slate-900/50 p-4 rounded border border-amber-700/50 text-sm">
              <p className="text-amber-400 font-semibold mb-2">How the conversion works:</p>
              <p className="text-slate-300">SPX Proxy = SPY Price x Multiplier (~10x). This ratio drifts slightly over time. A 0.1% drift at SPX ~5900 = ~5.9 points, which matters at Gamma Trap boundaries. The multiplier is configurable in the backend.</p>
            </div>
          </div>

          {/* --- SMART LEDGER GUIDE --- */}
          <div className="bg-slate-800 border border-slate-700 rounded-lg p-8 shadow-xl">
            <h3 className="text-lg font-semibold text-slate-200 mb-4">Using the Smart Ledger</h3>
            <div className="text-sm text-slate-300 space-y-3">
              <div className="bg-slate-900/50 p-4 rounded border border-slate-700">
                <span className="font-bold text-slate-100">Logging a position</span>
                <p className="text-slate-400 mt-1">Select the spread type (Put Spread, Call Spread, or Iron Condor), enter the <span className="font-semibold">SPX short strike</span> price (e.g., 5850), and the credit received (e.g., 0.80). Click "Track Position". The position persists across browser refreshes.</p>
              </div>
              <div className="bg-slate-900/50 p-4 rounded border border-slate-700">
                <span className="font-bold text-slate-100">Reading the status</span>
                <p className="text-slate-400 mt-1">Each position shows a color-coded bar and message. <span className="text-emerald-400">Green = Safe</span>. <span className="text-amber-400">Amber = Warning</span>. <span className="text-red-400">Red = Eject</span>. The moat value (e.g., +45.2 pts) shows how far SPX is from your strike.</p>
              </div>
              <div className="bg-slate-900/50 p-4 rounded border border-slate-700">
                <span className="font-bold text-slate-100">Closing a position</span>
                <p className="text-slate-400 mt-1">After closing the position in your broker, click the red X on the position card to remove it from active tracking.</p>
              </div>
              <div className="bg-slate-900/50 p-4 rounded border border-slate-700">
                <span className="font-bold text-slate-100">Iron Condor note</span>
                <p className="text-slate-400 mt-1">Iron Condors have two short strikes. Log each leg as a separate position (one Put Spread and one Call Spread) for accurate moat tracking on both sides.</p>
              </div>
            </div>
          </div>

        </div>
      )}
    </div>
  );
}

function MetricCard({ title, value, color = "text-slate-100", alert = null }) {
  return (
    <div className={`bg-slate-900/80 p-4 rounded border ${alert ? 'border-amber-700/50' : 'border-slate-700'} relative group`}>
      <div className="text-slate-400 text-xs font-semibold uppercase tracking-wider mb-1">
        {title}
        {alert && <span className="ml-1.5 text-amber-400 cursor-help inline-block animate-pulse">⚠</span>}
      </div>
      <div className={`text-2xl font-bold ${color}`}>{value}</div>
      {alert && (
        <div className="absolute bottom-full left-0 mb-2 w-72 bg-slate-900 border border-amber-600/50 rounded-lg p-3 text-xs text-amber-200 shadow-2xl hidden group-hover:block z-20">
          <div className="text-amber-400 font-bold mb-1">◎ WATCH</div>
          {alert}
          <div className="absolute top-full left-4 w-2 h-2 bg-slate-900 border-r border-b border-amber-600/50 transform rotate-45 -mt-1"></div>
        </div>
      )}
    </div>
  );
}

function IntensityBar({ label, value }) {
  const pct = Math.round(value * 100);
  const barColor = value > 0.7 ? 'bg-red-500' : value > 0.4 ? 'bg-amber-500' : 'bg-emerald-500';
  const textColor = value > 0.7 ? 'text-red-400' : value > 0.4 ? 'text-amber-400' : 'text-emerald-400';
  return (
    <div className="flex items-center gap-2">
      <span className="text-xs text-slate-400 w-10 text-right font-mono">{label}</span>
      <div className="flex-1 bg-slate-800 rounded-full h-2">
        <div className={`${barColor} h-2 rounded-full transition-all duration-500`} style={{ width: `${pct}%` }}></div>
      </div>
      <span className={`text-xs font-mono w-10 ${textColor}`}>{value.toFixed(2)}</span>
    </div>
  );
}