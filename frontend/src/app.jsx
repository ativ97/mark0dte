import React, { useState, useEffect } from 'react';

export default function App() {
  const [telemetry, setTelemetry] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [activeTab, setActiveTab] = useState('dashboard'); // NEW: Tab state

  // Local state for the Manual Ledger
  const [positions, setPositions] = useState([]);
  const [newPosition, setNewPosition] = useState({ type: 'Put Spread', strike: '', credit: '' });

  const fetchTelemetry = async () => {
    try {
      setLoading(true);
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
    const interval = setInterval(fetchTelemetry, 60000);
    return () => clearInterval(interval);
  }, []);

  const handleAddPosition = (e) => {
    e.preventDefault();
    if (!newPosition.strike || !newPosition.credit) return;
    setPositions([...positions, { ...newPosition, id: Date.now() }]);
    setNewPosition({ type: 'Put Spread', strike: '', credit: '' });
  };

  const removePosition = (id) => {
    setPositions(positions.filter(p => p.id !== id));
  };

  // NEW: Dynamic Context Helper
  const getStateContext = (score) => {
    if (score <= 1) {
      return [
        "The market has a clear, unchallenged directional bias.",
        "Directional wings (Put Spreads / Call Spreads) are authorized.",
        "Trend failures happen fast: Respect strict 200% premium stop-losses."
      ];
    } else if (score === 2) {
      return [
        "The market is consolidating or building energy. Indicators are mixed.",
        "Neutral strategies (Iron Condors) are highly preferred.",
        "Absorb localized noise: Expand stops to 250% premium or a 15-pt asset boundary."
      ];
    } else {
      return [
        "The market is violently fluctuating with no directional progress.",
        "Strictly Neutral: Do NOT deploy single directional wings.",
        "Ignore IV premium spikes: Use strict asset boundary limits ONLY."
      ];
    }
  };

  return (
    <div className="min-h-screen bg-slate-900 text-slate-100 p-6 font-sans">
      <header className="mb-6 border-b border-slate-700 pb-4">
        <div className="flex justify-between items-center mb-4">
          <div>
            <h1 className="text-3xl font-bold text-emerald-400">0DTE System Commander</h1>
            <p className="text-slate-400 text-sm">Algorithmic Decision Support Matrix</p>
          </div>
          <button
            onClick={fetchTelemetry}
            className="bg-slate-800 hover:bg-slate-700 text-slate-200 px-4 py-2 rounded shadow transition-colors"
          >
            Refresh Data
          </button>
        </div>

        {/* NEW: Navigation Tabs */}
        <div className="flex space-x-4">
          <button
            onClick={() => setActiveTab('dashboard')}
            className={`px-4 py-2 rounded font-semibold transition-colors ${activeTab === 'dashboard' ? 'bg-emerald-600 text-white' : 'bg-slate-800 text-slate-400 hover:bg-slate-700'}`}
          >
            Live Dashboard
          </button>
          <button
            onClick={() => setActiveTab('manual')}
            className={`px-4 py-2 rounded font-semibold transition-colors ${activeTab === 'manual' ? 'bg-emerald-600 text-white' : 'bg-slate-800 text-slate-400 hover:bg-slate-700'}`}
          >
            System Manual & Rules
          </button>
        </div>
      </header>

      {error && (
        <div className="bg-red-900/50 border border-red-500 text-red-200 p-4 rounded mb-6">
          {error}
        </div>
      )}

      {/* --- VIEW 1: LIVE DASHBOARD --- */}
      {activeTab === 'dashboard' && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 space-y-6">

            {/* Telemetry Matrix */}
<div className="bg-slate-800 border border-slate-700 rounded-lg p-6 shadow-xl">
  <h2 className="text-xl font-semibold mb-4 text-slate-300 border-b border-slate-700 pb-2">Live Telemetry</h2>
  {loading && !telemetry ? (
    <p className="text-slate-400 animate-pulse">Initializing data streams...</p>
  ) : telemetry ? (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4"> {/* Changed to md:grid-cols-4 for better layout */}
      <MetricCard title="Spot Price" value={`$${telemetry.current_price}`} />
      <MetricCard title="EMA 9" value={telemetry.ema_9} color={telemetry.current_price > telemetry.ema_9 ? "text-emerald-400" : "text-red-400"} />
      <MetricCard title="EMA 21" value={telemetry.ema_21} color={telemetry.current_price > telemetry.ema_21 ? "text-emerald-400" : "text-red-400"} />
      <MetricCard title="RSI (14)" value={telemetry.rsi_14} color={telemetry.rsi_14 > 60 || telemetry.rsi_14 < 40 ? "text-amber-400" : "text-slate-200"} />
      <MetricCard title="CHOP (14)" value={telemetry.chop_value} color={telemetry.chop_value > 61.8 ? "text-red-400" : "text-emerald-400"} />
      <MetricCard title="Efficiency (ER)" value={telemetry.er_value} color={telemetry.er_value < 0.20 ? "text-red-400" : "text-emerald-400"} />

      {/* NEW: VWAP Deviation Card */}
      <MetricCard
        title="VWAP Deviation"
        value={`${telemetry.vwap_dev}%`}
        color={telemetry.vwap_dev > 0.35 ? "text-amber-400 font-extrabold animate-pulse" : "text-emerald-400"}
      />
    </div>
  ) : null}
</div>

            {/* Regime Brain Output */}
            {telemetry && (
              <div className={`border rounded-lg p-6 shadow-xl ${telemetry.regime_score > 1 ? 'bg-amber-900/20 border-amber-700/50' : 'bg-emerald-900/20 border-emerald-700/50'}`}>
                <h2 className="text-xl font-semibold mb-4 text-slate-300">Algorithmic Directives</h2>
                <div className="space-y-4">
                  <div className="flex justify-between items-center bg-slate-900/50 p-4 rounded border border-slate-700/50">
                    <span className="text-slate-400 font-medium">Market State:</span>
                    <span className="font-bold text-lg text-amber-400">{telemetry.regime_state}</span>
                  </div>
                  <div className="flex justify-between items-center bg-slate-900/50 p-4 rounded border border-slate-700/50">
                    <span className="text-slate-400 font-medium">Required Moat Width:</span>
                    <span className="font-bold text-lg text-slate-100">{telemetry.recommended_moat}</span>
                  </div>
                  <div className="flex justify-between items-center bg-slate-900/50 p-4 rounded border border-slate-700/50">
                    <span className="text-slate-400 font-medium">Stop-Loss Protocol:</span>
                    <span className="font-bold text-lg text-slate-100">{telemetry.stop_loss_rule}</span>
                  </div>

                  {/* NEW: Contextual Bullet Points */}
                  <div className="mt-4 bg-slate-900/80 p-4 rounded border border-slate-700">
                    <h3 className="text-sm font-bold text-slate-300 mb-2 uppercase tracking-wide">Context & Rules for Current State</h3>
                    <ul className="list-disc list-inside text-sm text-slate-300 space-y-1">
                      {getStateContext(telemetry.regime_score).map((point, idx) => (
                        <li key={idx}>{point}</li>
                      ))}
                    </ul>
                  </div>

                </div>
              </div>
            )}
          </div>

          {/* Manual Position Ledger */}
          <div className="bg-slate-800 border border-slate-700 rounded-lg p-6 shadow-xl">
            <h2 className="text-xl font-semibold mb-4 text-slate-300 border-b border-slate-700 pb-2">Active Ledger</h2>
            <form onSubmit={handleAddPosition} className="mb-6 space-y-3">
              <select
                className="w-full bg-slate-900 border border-slate-600 rounded p-2 text-slate-200 focus:border-emerald-500 outline-none"
                value={newPosition.type}
                onChange={e => setNewPosition({...newPosition, type: e.target.value})}
              >
                <option>Put Spread</option>
                <option>Call Spread</option>
                <option>Iron Condor</option>
              </select>
              <div className="flex gap-2">
                <input
                  type="text" placeholder="Short Strike"
                  className="w-1/2 bg-slate-900 border border-slate-600 rounded p-2 text-slate-200 focus:border-emerald-500 outline-none"
                  value={newPosition.strike} onChange={e => setNewPosition({...newPosition, strike: e.target.value})}
                />
                <input
                  type="text" placeholder="Credit ($)"
                  className="w-1/2 bg-slate-900 border border-slate-600 rounded p-2 text-slate-200 focus:border-emerald-500 outline-none"
                  value={newPosition.credit} onChange={e => setNewPosition({...newPosition, credit: e.target.value})}
                />
              </div>
              <button type="submit" className="w-full bg-emerald-600 hover:bg-emerald-500 text-white font-bold py-2 px-4 rounded transition-colors">
                Log Position
              </button>
            </form>

            <div className="space-y-3">
              {positions.length === 0 ? (
                <p className="text-slate-500 text-sm text-center italic mt-8">No active positions tracked. Awaiting deployment.</p>
              ) : (
                positions.map(pos => (
                  <div key={pos.id} className="bg-slate-700/50 p-3 rounded flex justify-between items-center border border-slate-600">
                    <div>
                      <div className="font-bold text-slate-200">{pos.type} @ {pos.strike}</div>
                      <div className="text-sm text-slate-400">Credit: ${pos.credit}</div>
                    </div>
                    <button onClick={() => removePosition(pos.id)} className="text-red-400 hover:text-red-300 font-bold px-2">X</button>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      )}

      {/* --- VIEW 2: SYSTEM MANUAL --- */}
      {activeTab === 'manual' && (
        <div className="bg-slate-800 border border-slate-700 rounded-lg p-8 shadow-xl max-w-4xl mx-auto">
          <h2 className="text-2xl font-bold text-emerald-400 mb-6 border-b border-slate-700 pb-4">System Manual & Trading Rules</h2>

          <div className="space-y-8">
            <section>
              <h3 className="text-xl font-semibold text-slate-200 mb-3">Core Philosophy</h3>
              <p className="text-slate-300 leading-relaxed">
                This algorithm acts as a <strong>Human-in-the-Loop Regime Classifier</strong>. It ingests live market telemetry on a 5-minute timeframe to determine the current operational environment. Based on the calculated "Regime Score" (0 to 4), it outputs dynamic constraints to protect short premium positions from structural intraday failures.
              </p>
            </section>

            <section>
              <h3 className="text-xl font-semibold text-slate-200 mb-3">The Telemetry Scoring</h3>
              <p className="text-slate-300 mb-2">The system assigns a +1 penalty score for every condition that indicates market inefficiency or chop:</p>
              <ul className="list-disc list-inside text-slate-300 space-y-2 bg-slate-900 p-4 rounded border border-slate-700">
                <li><strong>Moving Average Compression:</strong> Absolute difference between EMA 9 and 21 is less than 0.1% of price.</li>
                <li><strong>Oscillator Exhaustion:</strong> RSI (14) is stuck in the 45-55 "Dead Zone".</li>
                <li><strong>Trend Inefficiency:</strong> Choppiness Index (CHOP) is greater than 61.8.</li>
                <li><strong>Path Inefficiency:</strong> Kaufman's Efficiency Ratio (ER) is less than 0.20.</li>
              </ul>
            </section>

            <section className="space-y-4">
              <h3 className="text-xl font-semibold text-slate-200 mb-3">State Definitions</h3>

              <div className="bg-slate-900 border-l-4 border-emerald-500 p-4 rounded-r shadow">
                <h4 className="text-lg font-bold text-emerald-400">State A: Clean Trend (Score 0-1)</h4>
                <p className="text-slate-300 mt-2 text-sm">The market has a clear directional bias. MA lines are separated, CHOP is low, and ER is high. Directional wings are authorized. Because the trend is predictable, <strong>strict premium stop-losses (200%)</strong> are required. If the premium spikes, the trend is failing.</p>
              </div>

              <div className="bg-slate-900 border-l-4 border-amber-500 p-4 rounded-r shadow">
                <h4 className="text-lg font-bold text-amber-400">State B: Moderate Chop (Score 2)</h4>
                <p className="text-slate-300 mt-2 text-sm">The market is consolidating. Indicators are mixed. Neutral strategies are preferred. Broaden risk parameters to <strong>250% premium or a 15-point asset boundary</strong> to absorb normal IV fluctuations without getting stopped out by noise.</p>
              </div>

              <div className="bg-slate-900 border-l-4 border-red-500 p-4 rounded-r shadow">
                <h4 className="text-lg font-bold text-red-400">State C: High Entropy / Whipsaw (Score 3-4)</h4>
                <p className="text-slate-300 mt-2 text-sm">The market is violently fluctuating with zero net directional progress. Strictly neutral deployments only. <strong>Suspend all premium-based stops.</strong> Erratic IV will cause false stop-outs. Exit ONLY if the underlying asset's spot price physically breaches your boundary limit.</p>
              </div>
            </section>
          </div>
        </div>
      )}
    </div>
  );
}

// Helper Component
function MetricCard({ title, value, color = "text-slate-100" }) {
  return (
    <div className="bg-slate-900/80 p-4 rounded border border-slate-700">
      <div className="text-slate-400 text-xs font-semibold uppercase tracking-wider mb-1">{title}</div>
      <div className={`text-2xl font-bold ${color}`}>{value}</div>
    </div>
  );
}