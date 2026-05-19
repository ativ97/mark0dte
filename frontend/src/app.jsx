import React, { useState, useEffect } from 'react';

export default function App() {
  const [telemetry, setTelemetry] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [activeTab, setActiveTab] = useState('dashboard');

  const [newPosition, setNewPosition] = useState({ type: 'Put Spread', strike: '', credit: '' });

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
    try {
      await fetch(`http://127.0.0.1:8000/api/positions/${id}/close`, { method: 'POST' });
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
            <p className="text-slate-400 text-sm">Algorithmic Decision Support Matrix V3.0 (Persistent State)</p>
          </div>
          <button onClick={fetchTelemetry} className="bg-slate-800 hover:bg-slate-700 text-slate-200 px-4 py-2 rounded shadow transition-colors">
            Refresh Data
          </button>
        </div>

        <div className="flex space-x-4">
          <button onClick={() => setActiveTab('dashboard')} className={`px-4 py-2 rounded font-semibold transition-colors ${activeTab === 'dashboard' ? 'bg-emerald-600 text-white' : 'bg-slate-800 text-slate-400'}`}>Live Dashboard</button>
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

            <form onSubmit={handleAddPosition} className="mb-6 space-y-3">
              <select className="w-full bg-slate-900 border border-slate-600 rounded p-2 text-slate-200 outline-none" value={newPosition.type} onChange={e => setNewPosition({...newPosition, type: e.target.value})}>
                <option>Put Spread</option><option>Call Spread</option><option>Iron Condor</option>
              </select>
              <div className="flex gap-2">
                <input type="text" placeholder="SPX Strike" className="w-1/2 bg-slate-900 border border-slate-600 rounded p-2 text-slate-200 outline-none" value={newPosition.strike} onChange={e => setNewPosition({...newPosition, strike: e.target.value})}/>
                <input type="text" placeholder="Credit ($)" className="w-1/2 bg-slate-900 border border-slate-600 rounded p-2 text-slate-200 outline-none" value={newPosition.credit} onChange={e => setNewPosition({...newPosition, credit: e.target.value})}/>
              </div>
              <button type="submit" className="w-full bg-emerald-600 hover:bg-emerald-500 text-white font-bold py-2 px-4 rounded">Track Position</button>
            </form>

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
                              P/L: {pos.estimated_pl >= 0 ? '+' : ''}{pos.estimated_pl?.toFixed(2)}
                            </span>
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
                          pos.exit_strategy.action === 'CLOSE_NOW' ? 'bg-red-900/40 border-red-700/50 text-red-200' :
                          pos.exit_strategy.action === 'CLOSE_SOON' ? 'bg-amber-900/30 border-amber-700/50 text-amber-200' :
                          pos.exit_strategy.action === 'HOLD_WITH_TRIGGER' ? 'bg-blue-900/20 border-blue-700/40 text-blue-200' :
                          'bg-emerald-900/20 border-emerald-700/40 text-emerald-300'
                        }`}>
                          <div className="flex items-center gap-1.5">
                            <span className={`font-bold text-[10px] uppercase tracking-wider shrink-0 ${
                              pos.exit_strategy.action === 'CLOSE_NOW' ? 'text-red-400' :
                              pos.exit_strategy.action === 'CLOSE_SOON' ? 'text-amber-400' :
                              pos.exit_strategy.action === 'LET_EXPIRE' ? 'text-emerald-400' :
                              'text-slate-400'
                            }`}>{pos.exit_strategy.action.replace(/_/g, ' ')}</span>
                            {pos.exit_strategy.target_price && (
                              <span className="font-mono font-bold">@${pos.exit_strategy.target_price}</span>
                            )}
                            {pos.exit_strategy.monitor_minutes > 0 && (
                              <span className="text-slate-500">| {pos.exit_strategy.monitor_minutes}min window</span>
                            )}
                          </div>
                          <div className="mt-0.5 text-slate-400">{pos.exit_strategy.instruction}</div>
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
      {activeTab === 'manual' && (
        <div className="max-w-4xl mx-auto space-y-6">

          {/* --- QUICK START --- */}
          <div className="bg-slate-800 border border-slate-700 rounded-lg p-8 shadow-xl">
            <h2 className="text-2xl font-bold text-emerald-400 mb-2">System Manual & User Guide</h2>
            <p className="text-slate-400 text-sm mb-6 border-b border-slate-700 pb-4">0DTE Algorithmic Decision Support Matrix V3.0</p>

            <h3 className="text-lg font-semibold text-slate-200 mb-3">Quick Start</h3>
            <ol className="list-decimal list-inside text-sm text-slate-300 space-y-2 mb-6">
              <li>Open the <span className="text-emerald-400 font-semibold">Live Dashboard</span> tab. The system auto-fetches SPY data from Alpaca every 30 seconds and computes the regime state.</li>
              <li>Check the <span className="text-amber-400 font-semibold">Market State</span> card to see the current regime (A, B, or C) and the recommended moat width.</li>
              <li>Before placing a trade, verify your planned short strike is at least as far away as the <span className="font-semibold text-slate-100">Required Moat Width</span>.</li>
              <li>After entering a position in your broker, log it in the <span className="text-emerald-400 font-semibold">Smart Ledger</span> panel on the right. Select the spread type, enter the SPX short strike, and the credit received.</li>
              <li>The system will compute a live moat (distance in SPX points) and display a color-coded status for each position. Follow the directives.</li>
              <li>When you close a position in your broker, click the <span className="text-red-400 font-semibold">X</span> button on that position to remove it from tracking.</li>
            </ol>
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
                  <li><span className="font-semibold text-slate-100">What to do:</span> Directional credit spreads are authorized (e.g., Put Spreads if bullish). You can use tighter moats (35-40 SPX points from your short strike).</li>
                  <li><span className="font-semibold text-slate-100">Stop-loss rule:</span> Strict 200% of premium received. If you collected $0.80, exit if the spread hits $1.60 debit.</li>
                </ul>
              </div>

              <div className="bg-amber-900/20 border border-amber-700/50 rounded-lg p-4">
                <div className="flex items-center gap-2 mb-2">
                  <span className="bg-amber-600 text-white text-xs font-bold px-2 py-0.5 rounded">Score 2</span>
                  <h4 className="font-bold text-amber-400">State B: Moderate Chop</h4>
                </div>
                <ul className="text-sm text-slate-300 space-y-1 ml-4">
                  <li><span className="font-semibold text-slate-100">What it means:</span> Mixed signals. Some indicators show trend, others show consolidation. Price may be range-bound with occasional breakout fakes.</li>
                  <li><span className="font-semibold text-slate-100">What to do:</span> Prefer neutral strategies (Iron Condors). Widen your moat to 50-60 SPX points.</li>
                  <li><span className="font-semibold text-slate-100">Stop-loss rule:</span> Hybrid approach. Exit at 250% premium OR if SPX moves within 15 points of your short strike, whichever comes first.</li>
                </ul>
              </div>

              <div className="bg-red-900/20 border border-red-700/50 rounded-lg p-4">
                <div className="flex items-center gap-2 mb-2">
                  <span className="bg-red-600 text-white text-xs font-bold px-2 py-0.5 rounded">Score 3-4</span>
                  <h4 className="font-bold text-red-400">State C: High Entropy / Whipsaw</h4>
                </div>
                <ul className="text-sm text-slate-300 space-y-1 ml-4">
                  <li><span className="font-semibold text-slate-100">What it means:</span> All indicators show chop. EMAs are compressed, RSI is dead-zone (45-55), efficiency ratio is very low. High risk of false breakouts and whipsaws.</li>
                  <li><span className="font-semibold text-slate-100">What to do:</span> Strictly neutral deployments only. Push moats out to 70+ SPX points. Consider sitting out entirely if you can't get that width at acceptable credit.</li>
                  <li><span className="font-semibold text-slate-100">Stop-loss rule:</span> Ignore premium spikes entirely (IV crush causes artificial premium inflation). Use asset-boundary stops ONLY. Exit only if SPX physically approaches your strike.</li>
                </ul>
              </div>
            </div>
          </div>

          {/* --- RISK ZONES --- */}
          <div className="bg-slate-800 border border-slate-700 rounded-lg p-8 shadow-xl">
            <h3 className="text-lg font-semibold text-slate-200 mb-4">Position Risk Zones</h3>
            <p className="text-sm text-slate-400 mb-4">For each tracked position, the system calculates the "moat" — the distance in SPX points between the current price and your short strike. This maps to three zones:</p>

            <div className="space-y-3">
              <div className="flex items-start gap-3 bg-slate-900/50 p-4 rounded border border-slate-700">
                <span className="bg-emerald-500 rounded-full w-3 h-3 mt-1 flex-shrink-0"></span>
                <div>
                  <span className="font-bold text-emerald-400">SAFE ZONE (&gt; 25 points)</span>
                  <p className="text-sm text-slate-300">Your position has a healthy buffer. Theta decay is working in your favor. No action needed — let time do the work.</p>
                </div>
              </div>
              <div className="flex items-start gap-3 bg-slate-900/50 p-4 rounded border border-slate-700">
                <span className="bg-amber-400 rounded-full w-3 h-3 mt-1 flex-shrink-0"></span>
                <div>
                  <span className="font-bold text-amber-400">WARNING ZONE (10-25 points)</span>
                  <p className="text-sm text-slate-300">Volatility expansion is likely. The system displays a regime-specific stop-loss directive. Be ready to act. Watch the stop-loss protocol displayed for each position — it changes based on the current market state.</p>
                </div>
              </div>
              <div className="flex items-start gap-3 bg-slate-900/50 p-4 rounded border border-slate-700">
                <span className="bg-red-500 rounded-full w-3 h-3 mt-1 flex-shrink-0"></span>
                <div>
                  <span className="font-bold text-red-400">GAMMA TRAP (0-10 points)</span>
                  <p className="text-sm text-slate-300">Critical danger zone. Delta/Gamma risk overrides any Theta edge. The system starts a 5-minute verification countdown. If SPX remains breached after 5 minutes, a <span className="text-red-400 font-bold">CRITICAL EJECT</span> order is issued. If the price recovers before the timer expires (whipsaw immunity), the timer resets and you stay in the trade.</p>
                </div>
              </div>
            </div>
          </div>

          {/* --- INDICATORS --- */}
          <div className="bg-slate-800 border border-slate-700 rounded-lg p-8 shadow-xl">
            <h3 className="text-lg font-semibold text-slate-200 mb-4">Indicator Reference</h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
              <div className="bg-slate-900/50 p-4 rounded border border-slate-700">
                <span className="font-bold text-slate-100">EMA 9 / EMA 21</span>
                <p className="text-slate-400 mt-1">Exponential Moving Averages. When they're far apart, the market is trending. When compressed (diff &lt; 0.1%), the market lacks conviction. Price above both = bullish bias. Below both = bearish.</p>
              </div>
              <div className="bg-slate-900/50 p-4 rounded border border-slate-700">
                <span className="font-bold text-slate-100">RSI (14)</span>
                <p className="text-slate-400 mt-1">Relative Strength Index. Measures momentum. Stuck between 45-55 = no momentum (adds +1 to chop score). Above 60 or below 40 = directional energy present.</p>
              </div>
              <div className="bg-slate-900/50 p-4 rounded border border-slate-700">
                <span className="font-bold text-slate-100">CHOP (14)</span>
                <p className="text-slate-400 mt-1">Choppiness Index. Above 61.8 = choppy, range-bound market (+1 to score). Below 38.2 = strong trend. This is the most direct measure of whether price action is noisy.</p>
              </div>
              <div className="bg-slate-900/50 p-4 rounded border border-slate-700">
                <span className="font-bold text-slate-100">Efficiency Ratio (ER)</span>
                <p className="text-slate-400 mt-1">Kaufman's ER. Measures how efficiently price moves from A to B. Below 0.20 = price is going nowhere despite moving a lot (+1 to score). Above 0.50 = clean directional movement.</p>
              </div>
              <div className="bg-slate-900/50 p-4 rounded border border-slate-700 md:col-span-2">
                <span className="font-bold text-slate-100">VWAP Deviation</span>
                <p className="text-slate-400 mt-1">Measures how far SPY has stretched from its Volume-Weighted Average Price. If deviation exceeds 0.35%, the system activates a <span className="text-amber-400 font-semibold">VWAP Elasticity Override</span>: all stop-losses are suspended for 10 minutes to let the "rubber band" snap back. This prevents getting stopped out on mean-reversion bounces.</p>
              </div>
            </div>
          </div>

          {/* --- SPX PROXY --- */}
          <div className="bg-slate-800 border border-slate-700 rounded-lg p-8 shadow-xl">
            <h3 className="text-lg font-semibold text-slate-200 mb-4">SPX Proxy Methodology</h3>
            <p className="text-sm text-slate-300 mb-3">This system trades <span className="text-emerald-400 font-semibold">SPX 0DTE options</span> but uses <span className="text-emerald-400 font-semibold">SPY ETF</span> data from Alpaca as a proxy, since Alpaca does not provide direct SPX index data.</p>
            <div className="bg-slate-900/50 p-4 rounded border border-amber-700/50 text-sm">
              <p className="text-amber-400 font-semibold mb-2">How the conversion works:</p>
              <p className="text-slate-300">SPX Proxy = SPY Price x Multiplier (currently 10.0). This ratio drifts slightly over time due to dividends and expense ratios. A 0.1% drift at SPX ~5900 = ~5.9 points, which matters when the Gamma Trap boundary is only 10 points. The multiplier is configurable in the backend and the SPX price displayed on the dashboard comes directly from the server calculation.</p>
            </div>
          </div>

          {/* --- SMART LEDGER GUIDE --- */}
          <div className="bg-slate-800 border border-slate-700 rounded-lg p-8 shadow-xl">
            <h3 className="text-lg font-semibold text-slate-200 mb-4">Using the Smart Ledger</h3>
            <div className="text-sm text-slate-300 space-y-3">
              <div className="bg-slate-900/50 p-4 rounded border border-slate-700">
                <span className="font-bold text-slate-100">Logging a position</span>
                <p className="text-slate-400 mt-1">Select the spread type (Put Spread, Call Spread, or Iron Condor), enter the <span className="font-semibold">SPX short strike</span> price (e.g., 5850), and the credit received (e.g., 0.80). Click "Track Position". The position is saved to the database and persists across browser refreshes.</p>
              </div>
              <div className="bg-slate-900/50 p-4 rounded border border-slate-700">
                <span className="font-bold text-slate-100">Reading the status</span>
                <p className="text-slate-400 mt-1">Each position shows a color-coded progress bar and a message. <span className="text-emerald-400">Green = Safe</span>. <span className="text-amber-400">Amber = Warning</span>. <span className="text-red-400">Red = Eject</span>. The moat value (e.g., +45.2 pts) shows how many SPX points separate the current price from your strike.</p>
              </div>
              <div className="bg-slate-900/50 p-4 rounded border border-slate-700">
                <span className="font-bold text-slate-100">Closing a position</span>
                <p className="text-slate-400 mt-1">After closing the position in your broker, click the red X on the position card. This removes it from active tracking. (Future update: closed trades will be logged for analytics.)</p>
              </div>
              <div className="bg-slate-900/50 p-4 rounded border border-slate-700">
                <span className="font-bold text-slate-100">Iron Condor note</span>
                <p className="text-slate-400 mt-1">Iron Condors have two short strikes. Currently, log each leg as a separate position (one Put Spread and one Call Spread) for accurate moat tracking on both sides.</p>
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