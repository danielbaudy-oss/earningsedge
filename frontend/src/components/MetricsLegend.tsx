"use client";

import { useState } from "react";
import { HelpCircle, X } from "lucide-react";

export function MetricsLegend() {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <>
      <button
        onClick={() => setIsOpen(true)}
        className="flex items-center gap-1.5 rounded-lg border border-gray-200 px-3 py-1.5 text-xs text-gray-500 hover:bg-gray-50 hover:text-gray-700"
      >
        <HelpCircle className="h-3.5 w-3.5" />
        What do these metrics mean?
      </button>

      {isOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="relative max-h-[80vh] w-full max-w-lg overflow-y-auto rounded-xl bg-white p-6 shadow-xl">
            <button
              onClick={() => setIsOpen(false)}
              className="absolute right-4 top-4 text-gray-400 hover:text-gray-600"
              aria-label="Close"
            >
              <X className="h-5 w-5" />
            </button>

            <h2 className="text-lg font-bold text-gray-900">
              Understanding the Metrics
            </h2>

            <div className="mt-4 space-y-4 text-sm text-gray-600">
              <div>
                <h3 className="font-semibold text-gray-900">🎯 Score (0–100%)</h3>
                <p>
                  Overall confidence in the opportunity. Combines earnings history,
                  analyst sentiment, fundamentals, and risk. Higher = stronger signal.
                </p>
                <ul className="mt-1 ml-4 list-disc text-xs text-gray-500">
                  <li>70%+ = Strong opportunity</li>
                  <li>50–70% = Moderate, proceed with caution</li>
                  <li>Below 50% = Weak or risky</li>
                </ul>
              </div>

              <div>
                <h3 className="font-semibold text-gray-900">📈 Expected Move</h3>
                <p>
                  How much the stock is predicted to move after earnings are reported.
                  Based on the stock's historical earnings reactions and current signals.
                  Positive = expected to go up. Negative = expected to drop.
                </p>
              </div>

              <div>
                <h3 className="font-semibold text-gray-900">✅ Beats Earnings?</h3>
                <p>
                  Probability that the company will report EPS (earnings per share)
                  above analyst estimates. A "beat" often (but not always) leads to
                  a stock price increase.
                </p>
              </div>

              <div>
                <h3 className="font-semibold text-gray-900">📊 Stock Goes Up?</h3>
                <p>
                  Probability the stock price rises the day after earnings. This can
                  differ from "beats earnings" — sometimes stocks drop even on a beat
                  if guidance is weak or expectations were too high.
                </p>
              </div>

              <div>
                <h3 className="font-semibold text-gray-900">🛡️ Risk Level</h3>
                <p>
                  How uncertain or volatile this prediction is. High risk means the
                  outcome is harder to predict — the stock could swing big in either direction.
                </p>
                <ul className="mt-1 ml-4 list-disc text-xs text-gray-500">
                  <li><span className="text-green-600 font-medium">Low (0–35%)</span> — Predictable, lower volatility</li>
                  <li><span className="text-amber-600 font-medium">Medium (35–60%)</span> — Some uncertainty</li>
                  <li><span className="text-red-600 font-medium">High (60%+)</span> — Very uncertain, big swings possible</li>
                </ul>
              </div>

              <div>
                <h3 className="font-semibold text-gray-900">🟢🔴🟡 Recommendation</h3>
                <p>The final call based on all factors combined:</p>
                <ul className="mt-1 ml-4 list-disc text-xs text-gray-500">
                  <li><span className="text-green-600 font-medium">BUY</span> — High score + stock likely to rise + manageable risk</li>
                  <li><span className="text-red-600 font-medium">SELL</span> — Low score + stock likely to drop</li>
                  <li><span className="text-amber-600 font-medium">AVOID</span> — Mixed signals or too risky to call</li>
                </ul>
              </div>

              <div className="rounded-lg bg-amber-50 p-3 text-xs text-amber-800">
                <strong>⚠️ Disclaimer:</strong> These predictions are based on historical
                patterns and publicly available data. They are not financial advice.
                Always do your own research before making investment decisions.
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
