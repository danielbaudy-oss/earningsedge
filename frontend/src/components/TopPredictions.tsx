"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getUpcomingPredictions } from "@/lib/api";
import { formatPercent, getRecommendationColor, getConfidenceColor } from "@/lib/utils";
import { PredictionCard } from "@/components/PredictionCard";
import { TrendingUp, TrendingDown, AlertTriangle, X } from "lucide-react";

export function TopPredictions() {
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null);

  const { data: predictions, isLoading } = useQuery({
    queryKey: ["topPredictions"],
    queryFn: () => getUpcomingPredictions({ min_confidence: 0.0 }),
  });

  if (isLoading) {
    return (
      <div className="card animate-pulse">
        <div className="space-y-3">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="h-14 rounded bg-gray-100" />
          ))}
        </div>
      </div>
    );
  }

  if (!predictions?.length) {
    return (
      <div className="card text-center text-gray-500">
        No buy opportunities this week
      </div>
    );
  }

  // Filter to buys only, sort by score
  const buys = predictions
    .filter((p) => p.recommendation === "buy")
    .sort((a, b) => b.confidence_score - a.confidence_score);

  if (!buys.length) {
    return (
      <div className="card text-center text-gray-500">
        No buy opportunities this week — all signals are Avoid or Sell
      </div>
    );
  }

  const recIcon = {
    buy: <TrendingUp className="h-3.5 w-3.5" />,
    sell: <TrendingDown className="h-3.5 w-3.5" />,
    avoid: <AlertTriangle className="h-3.5 w-3.5" />,
  };

  return (
    <>
      <div className="card">
        <div className="divide-y divide-gray-100">
          {buys.slice(0, 8).map((pred) => (
            <button
              key={pred.id}
              onClick={() => setSelectedTicker(pred.ticker ?? null)}
              className="flex w-full items-center justify-between py-3 text-left hover:bg-gray-50 -mx-2 px-2 rounded-lg transition"
            >
              <div className="flex items-center gap-3">
                <span className={`badge ${getRecommendationColor(pred.recommendation)}`}>
                  <TrendingUp className="h-3.5 w-3.5" />
                  <span className="ml-1 uppercase text-xs">{pred.recommendation}</span>
                </span>
                <div>
                  <p className="font-medium text-gray-900">
                    {pred.ticker}
                    {pred.company_name && (
                      <span className="ml-2 text-xs font-normal text-gray-500">{pred.company_name}</span>
                    )}
                  </p>
                  <p className="text-xs text-gray-500">Reports: {pred.earnings_date}</p>
                </div>
              </div>
              <div className="text-right">
                <p className={`text-sm font-bold ${(pred.expected_move_pct ?? 0) >= 0 ? "text-green-700" : "text-red-700"}`}>
                  {formatPercent(pred.expected_move_pct)}
                </p>
                <p className="text-xs text-gray-400">
                  {(pred.confidence_score * 100).toFixed(0)}% score
                </p>
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* Popup Modal */}
      {selectedTicker && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
          onClick={() => setSelectedTicker(null)}
        >
          <div
            className="relative w-full max-w-lg"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              onClick={() => setSelectedTicker(null)}
              className="absolute -top-3 -right-3 z-10 rounded-full bg-white p-1.5 shadow-lg hover:bg-gray-100"
              aria-label="Close"
            >
              <X className="h-4 w-4 text-gray-600" />
            </button>
            <PredictionCard ticker={selectedTicker} />
          </div>
        </div>
      )}
    </>
  );
}
