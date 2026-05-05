"use client";

export default function MetricsPage() {
  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <h1 className="text-2xl font-bold text-gray-900">Understanding the Metrics</h1>
      <p className="text-gray-600">
        Here's what each metric means and how to use them for your investment decisions.
      </p>

      <div className="space-y-4">
        <div className="card">
          <h3 className="font-semibold text-gray-900">🎯 Score (0–100%)</h3>
          <p className="mt-1 text-sm text-gray-600">
            Overall confidence in the opportunity. Combines earnings history,
            analyst sentiment, fundamentals, momentum, and risk. Higher = stronger signal.
          </p>
          <ul className="mt-2 ml-4 list-disc text-xs text-gray-500 space-y-1">
            <li><span className="font-medium text-green-700">70%+</span> — Strong opportunity</li>
            <li><span className="font-medium text-amber-700">50–70%</span> — Moderate, proceed with caution</li>
            <li><span className="font-medium text-red-700">Below 50%</span> — Weak or risky</li>
          </ul>
        </div>

        <div className="card">
          <h3 className="font-semibold text-gray-900">📈 Expected Move</h3>
          <p className="mt-1 text-sm text-gray-600">
            How much the stock is predicted to move after earnings are reported.
            Based on the stock's historical earnings reactions, current momentum, and model signals.
            Positive = expected to go up. Negative = expected to drop.
          </p>
        </div>

        <div className="card">
          <h3 className="font-semibold text-gray-900">✅ Beats Earnings?</h3>
          <p className="mt-1 text-sm text-gray-600">
            Probability that the company will report EPS (earnings per share)
            above analyst estimates. A "beat" often (but not always) leads to
            a stock price increase. Some stocks beat on lowered expectations and still drop.
          </p>
        </div>

        <div className="card">
          <h3 className="font-semibold text-gray-900">📊 Stock Goes Up?</h3>
          <p className="mt-1 text-sm text-gray-600">
            Probability the stock price rises the day after earnings. This can
            differ from "beats earnings" — sometimes stocks drop even on a beat
            if guidance is weak, expectations were too high, or the stock is in a downtrend.
          </p>
        </div>

        <div className="card">
          <h3 className="font-semibold text-gray-900">🛡️ Risk Level</h3>
          <p className="mt-1 text-sm text-gray-600">
            How uncertain or volatile this prediction is. High risk means the
            outcome is harder to predict — the stock could swing big in either direction.
          </p>
          <ul className="mt-2 ml-4 list-disc text-xs text-gray-500 space-y-1">
            <li><span className="font-medium text-green-600">Low (0–35%)</span> — Predictable, lower volatility</li>
            <li><span className="font-medium text-amber-600">Medium (35–60%)</span> — Some uncertainty</li>
            <li><span className="font-medium text-red-600">High (60%+)</span> — Very uncertain, big swings possible</li>
          </ul>
        </div>

        <div className="card">
          <h3 className="font-semibold text-gray-900">🟢🔴🟡 Recommendation</h3>
          <p className="mt-1 text-sm text-gray-600">The final call based on all factors combined:</p>
          <ul className="mt-2 ml-4 list-disc text-xs text-gray-500 space-y-1">
            <li><span className="font-medium text-green-600">BUY</span> — High score + stock likely to rise + manageable risk</li>
            <li><span className="font-medium text-red-600">SELL</span> — Low score + stock likely to drop</li>
            <li><span className="font-medium text-amber-600">AVOID</span> — Mixed signals or too risky to call</li>
          </ul>
        </div>

        <div className="card">
          <h3 className="font-semibold text-gray-900">🔄 Trader vs Long-term Mode</h3>
          <p className="mt-1 text-sm text-gray-600">
            <strong>Trader:</strong> Optimized for short-term plays around earnings. Lower threshold for BUY signals, focuses on expected move size.
          </p>
          <p className="mt-1 text-sm text-gray-600">
            <strong>Long-term:</strong> More conservative. Needs higher score + lower risk to recommend BUY. Focuses on quality compounders you can hold through earnings.
          </p>
        </div>

        <div className="rounded-lg bg-amber-50 border border-amber-200 p-4 text-sm text-amber-800">
          <strong>⚠️ Disclaimer:</strong> These predictions are based on historical
          patterns and publicly available data. They are not financial advice.
          Always do your own research before making investment decisions.
        </div>
      </div>
    </div>
  );
}
